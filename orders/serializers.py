from rest_framework import serializers
from .models import Asset, Order, Proof

class AssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = ['id', 'name', 'code', 'rate', 'updated_at']

class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = '__all__'

class ProofSerializer(serializers.ModelSerializer):
    class Meta:
        model = Proof
        fields = ['id', 'order', 'file', 'uploaded_at']

class OrderCreateSerializer(serializers.ModelSerializer):
    asset_code = serializers.CharField(write_only=True, max_length=10)

    class Meta:
        model = Order
        fields = (
            "id",
            "order_type",           # "buy" | "sell"
            "asset_code",           # "BTC" | "ETH" | ...
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

        # Default status when created by the bot
        validated_data.setdefault("status", "pending")
        order = Order.objects.create(asset=asset, **validated_data)
        return order