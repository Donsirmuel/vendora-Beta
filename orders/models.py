from django.db import models
from django.utils import timezone
import uuid

# Each crypto asset
class Asset(models.Model):
    name = models.CharField(max_length=50, unique=True)  # e.g., BTC, ETH
    code = models.CharField(max_length=10, unique=True)  # e.g., btc, eth
    rate = models.DecimalField(max_digits=20, decimal_places=2)  # current rate in fiat
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


# Vendors (for future webapp logic)
class Vendor(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField(blank=True, null=True)
    telegram_id = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


# Customer orders (buy/sell)
class Order(models.Model):
    ORDER_TYPE = (
        ('buy', 'Buy'),
        ('sell', 'Sell'),
    )
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('vendor_accepted', 'Vendor Accepted'),
        ('vendor_rejected', 'Vendor Rejected'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_type = models.CharField(max_length=4, choices=ORDER_TYPE, default="")
    asset = models.ForeignKey(
        Asset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    customer_telegram_id = models.CharField(max_length=100, default="")  # customer identifier
    amount = models.DecimalField(max_digits=20, decimal_places=8, blank=True, null=True)
    fiat_amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    contract_address = models.CharField(max_length=200, blank=True, null=True)
    bank_account = models.CharField(max_length=200, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        asset_code = self.asset.code if self.asset else "N/A"
        return f"{self.order_type.upper()} - {asset_code} - {self.id}"


# Proofs of payment / transaction receipts
class Proof(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="proofs")
    file = models.FileField(upload_to="proofs/")
    uploaded_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Proof for Order {self.order.id}"


# Transaction linked to an order
class Transaction(models.Model):
    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name="transaction"
    )
    tx_hash = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Blockchain transaction hash if applicable"
    )
    reference = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Bank transfer reference or external ref"
    )
    status = models.CharField(
        max_length=20,
        choices=[("pending", "Pending"), ("completed", "Completed"), ("rejected", "Rejected")],
        default="pending"
    )
    rejection_reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Transaction for Order {self.order.id} - {self.status}"


# Bot session storage (for buttons and stage)
class BotSession(models.Model):
    telegram_id = models.BigIntegerField(unique=True)
    data = models.JSONField(default=dict)  # e.g., {"stage": "...", "asset_id": 1}
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"BotSession({self.telegram_id})"
