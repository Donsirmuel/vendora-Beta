from django.contrib import admin
from .models import Asset, Order

@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ("name", "rate", "updated_at")
    search_fields = ("name",)

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "asset", "order_type", "status", "created_at")
    list_filter = ("status", "order_type", "asset")
    search_fields = ("order_id", "customer_username")
    readonly_fields = ("id", "created_at", "updated_at")
