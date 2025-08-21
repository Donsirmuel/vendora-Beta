from django.urls import path
from .views import (
    AssetListAPIView,
    CreateOrderAPIView,
    UploadProofAPIView,
    UpdateOrderStatusAPIView,
    get_rate,
    bot_create_order,
)
from . import views

app_name = "orders"

urlpatterns = [
    # web UI
    path("dashboard/", views.vendor_dashboard, name="vendor_dashboard"),
    path("transaction/<uuid:order_id>/complete/", views.complete_transaction, name="complete_transaction"),
    path("transaction/<uuid:order_id>/reject/", views.reject_transaction, name="reject_transaction"),

    # API endpoints (keep these for bot/web integration)
    path("assets/", views.AssetListAPIView.as_view(), name="asset_list"),
    path("create-order/", views.CreateOrderAPIView.as_view(), name="create_order"),
    path("upload-proof/<uuid:order_id>/", views.UploadProofAPIView.as_view(), name="upload_proof"),
    path("update-status/<uuid:order_id>/", views.UpdateOrderStatusAPIView.as_view(), name="update_status"),
    path("get-rate/", views.get_rate, name="get_rate"),
    path("bot/create-order/", views.bot_create_order, name="bot_create_order"),
]