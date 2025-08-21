# orders/views.py
from rest_framework.views import APIView
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status, serializers

from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models.signals import post_save
from django.dispatch import receiver

import json

from .models import Asset, Order, Proof, Transaction
from .serializers import AssetSerializer, OrderSerializer, ProofSerializer
from .bot_notify import BotNotifier


# -----------------------------
# REST API pieces (kept from earlier)
# -----------------------------
class AssetListAPIView(APIView):
    def get(self, request):
        assets = Asset.objects.all()
        serializer = AssetSerializer(assets, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class CreateOrderAPIView(APIView):
    def post(self, request):
        serializer = OrderSerializer(data=request.data)
        if serializer.is_valid():
            order = serializer.save()

            # Ensure a transaction record is present
            Transaction.objects.get_or_create(order=order, defaults={"status": "pending"})

            # Make sure bot notifier can refer to a customer name
            customer_name = getattr(order, "customer_telegram_id", "unknown")

            if isinstance(order, Order):
                BotNotifier.notify_vendor_new_order(order)
                BotNotifier.notify_customer(order)
            else:
                # Handle the case where serializer.save() returns a list or invalid type
                return Response({"error": "Order creation failed: invalid order object."}, status=status.HTTP_400_BAD_REQUEST)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UploadProofAPIView(APIView):
    def post(self, request, order_id):
        order = get_object_or_404(Order, id=order_id)
        serializer = ProofSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(order=order)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UpdateOrderStatusAPIView(APIView):
    def post(self, request, order_id):
        order = get_object_or_404(Order, id=order_id)
        status_choice = request.data.get("status")
        if status_choice not in dict(Order.STATUS_CHOICES):
            return Response({"error": "Invalid status"}, status=status.HTTP_400_BAD_REQUEST)

        order.status = status_choice
        order.save()  # triggers signal to notify bot

        # if cancelled, notify vendor about customer cancellation
        if status_choice == "cancelled":
            BotNotifier.notify_vendor_customer_cancelled(order)

        return Response({"message": f"Order {order.id} status updated to {order.status}"}, status=status.HTTP_200_OK)


@api_view(["GET"])
def get_rate(request):
    asset_code = request.query_params.get("asset")
    try:
        asset = Asset.objects.get(code__iexact=asset_code)
        return Response({"rate": str(asset.rate)})
    except Asset.DoesNotExist:
        return Response({"error": "Asset not found"}, status=404)


# Serializer for bot -> order creation (kept for compatibility)
class OrderCreateSerializer(serializers.ModelSerializer):
    asset_code = serializers.CharField(write_only=True, max_length=10)

    class Meta:
        model = Order
        fields = (
            "id",
            "order_type",
            "asset_code",
            "customer_telegram_id",
            "amount",
            "fiat_amount",
            "contract_address",
            "bank_account",
            "status",
        )
        read_only_fields = ("id", "status")

    def validate(self, attrs):
        order_type = attrs.get("order_type")
        if order_type not in ("buy", "sell"):
            raise serializers.ValidationError({"order_type": 'Must be "buy" or "sell".'})
        amount = attrs.get("amount")
        if amount is None or amount <= 0:
            raise serializers.ValidationError({"amount": "Amount must be a positive number."})
        return attrs

    def create(self, validated_data):
        code = validated_data.pop("asset_code").upper()
        try:
            asset = Asset.objects.get(code__iexact=code)
        except Asset.DoesNotExist:
            raise serializers.ValidationError({"asset_code": "Unknown asset code."})
        validated_data.setdefault("status", "pending")
        order = Order.objects.create(asset=asset, **validated_data)
        Transaction.objects.get_or_create(order=order, defaults={"status": "pending"})
        # safe fallback for notifier
        customer_name = getattr(order, "customer_telegram_id", "unknown")

        BotNotifier.notify_vendor_new_order(order)
        BotNotifier.notify_customer(order)
        return order


# -----------------------------
# Bot: Create order via webhook
# -----------------------------
@csrf_exempt
def bot_create_order(request):
    if request.method != "POST":
        return Response({"error": "Invalid method"}, status=405)
    try:
        data = json.loads(request.body.decode("utf-8"))
        asset = Asset.objects.get(code__iexact=data.get("asset_code"))
        order = Order.objects.create(
            order_type=data.get("order_type"),
            asset=asset,
            customer_telegram_id=data.get("customer_telegram_id"),
            amount=data.get("amount"),
            fiat_amount=data.get("fiat_amount"),
            contract_address=data.get("contract_address"),
            bank_account=data.get("bank_account"),
            status="pending",
        )
        Transaction.objects.get_or_create(order=order, defaults={"status": "pending"})
        if not hasattr(order, "customer_name"):
            order.customer_name = getattr(order, "customer_telegram_id", "unknown")

        BotNotifier.notify_vendor_new_order(order)
        BotNotifier.notify_customer(order)
        return Response({"status": "ok", "order_id": order.id}, status=201)
    except Exception as e:
        return Response({"status": "error", "error": str(e)}, status=400)


# -----------------------------
# Django signals for notifications
# -----------------------------
@receiver(post_save, sender=Order)
def push_order_update(sender, instance, created, **kwargs):
    # We only notify customers on updates (not on creation — creation handled above)
    if not created:
        try:
            BotNotifier.notify_customer(instance)
        except Exception:
            pass


# -----------------------------
# Vendor webapp views (UI)
# -----------------------------
@login_required
def vendor_dashboard(request):
    """
    Vendor dashboard showing orders and transaction status.
    """
    orders = (
        Order.objects.select_related("asset")
        .prefetch_related("proofs")
        .all()
        .order_by("-created_at")
    )
    return render(request, "orders/vendor_dashboard.html", {"orders": orders})


@login_required
def complete_transaction(request, order_id):
    """
    Mark transaction and order as completed.
    Accepts POST with optional 'tx_hash' and 'reference'.
    """
    order = get_object_or_404(Order, id=order_id)
    if request.method == "POST":
        tx_hash = request.POST.get("tx_hash", "").strip() or None
        reference = request.POST.get("reference", "").strip() or None

        transaction, _ = Transaction.objects.get_or_create(order=order)
        transaction.tx_hash = tx_hash
        transaction.reference = reference
        transaction.status = "completed"
        transaction.save()

        order.status = "completed"
        order.save()

        # Notify customer & vendor (if needed)
        BotNotifier.notify_customer(order)
        messages.success(request, f"Order {order.id} marked as completed.")
        return redirect("vendor_dashboard")

    # If GET, redirect to dashboard (we use modal POST from dashboard)
    return redirect("vendor_dashboard")


@login_required
def reject_transaction(request, order_id):
    """
    Reject transaction with a reason.
    If GET: show a small form (reject_transaction.html).
    If POST: accept 'reason' and update objects, notify customer.
    """
    order = get_object_or_404(Order, id=order_id)

    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()
        transaction, _ = Transaction.objects.get_or_create(order=order)
        transaction.rejection_reason = reason or "Not specified"
        transaction.status = "rejected"
        transaction.save()

        order.status = "rejected"
        order.save()

        BotNotifier.notify_customer(order)
        # Also let vendor know cancellation/rejection acknowledged (no extra notify needed)
        messages.error(request, f"Order {order.id} rejected with reason.")
        return redirect("vendor_dashboard")

    return render(request, "orders/reject_transaction.html", {"order": order})
