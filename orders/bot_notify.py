import logging
from typing import Optional
from telegram import Bot
from django.conf import settings
from .models import Order, Transaction

logger = logging.getLogger(__name__)

# -----------------------------
# BOT CONFIG
# -----------------------------
TOKEN = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is not set in environment")
bot = Bot(token=TOKEN)

VENDOR_TELEGRAM_ID = getattr(settings, "VENDOR_TELEGRAM_ID", None)


# -----------------------------
# NOTIFIER CLASS
# -----------------------------
class BotNotifier:
    @staticmethod
    def format_order_message(order: Order) -> str:
        """Format status update for customer."""
        msg = (
            f"📌 Order Update\n"
            f"Order ID: {order.id}\n"
            f"Type: {order.order_type.upper()}\n"
            f"Asset: {order.asset.code if order.asset else 'N/A'}\n"
            f"Amount: {order.amount}\n"
            f"Fiat (est.): {order.fiat_amount}\n"
            f"Status: {order.status.upper()}\n"
        )

        # Add transaction details if available
        transaction: Optional[Transaction] = None
        try:
            transaction = getattr(order, "transaction", None)
        except Exception:
            transaction = None

        if order.status.lower() == "completed":
            if order.order_type.lower() == "buy":
                msg += f"✅ Your crypto has been sent to {order.contract_address}\n"
            else:
                msg += f"✅ Your fiat has been sent to {order.bank_account}\n"

            if transaction:
                if transaction.tx_hash:
                    msg += f"🔗 Tx Hash: {transaction.tx_hash}\n"
                if transaction.reference:
                    msg += f"🏦 Reference: {transaction.reference}\n"

        elif order.status.lower() == "rejected":
            reason = (
                transaction.rejection_reason
                if transaction and transaction.rejection_reason
                else "Not specified"
            )
            msg += f"❌ Your order was rejected.\nReason: {reason}\n"

        elif order.status.lower() == "cancelled":
            msg += "⚠️ Your order has been cancelled by you.\n"

        return msg

    # -----------------------------
    # CUSTOMER NOTIFICATIONS
    # -----------------------------
    @staticmethod
    def notify_customer(order: Order) -> None:
        """Notify customer of order creation or status change."""
        if not isinstance(order, Order):
            logger.warning(f"Expected Order, got {type(order)}")
            return

        chat_id: Optional[str] = (
            str(order.customer_telegram_id) if order.customer_telegram_id else None
        )
        if not chat_id:
            return

        try:
            message = BotNotifier.format_order_message(order)
            bot.send_message(chat_id=chat_id, text=message)  # type: ignore
            logger.info(f"Sent status update to customer {chat_id} for order {order.id}")
        except Exception as e:
            logger.error(f"Failed to send Telegram message to customer {chat_id}: {e}")

    # -----------------------------
    # VENDOR NOTIFICATIONS
    # -----------------------------
    @staticmethod
    def notify_vendor_new_order(order: Order) -> None:
        """Notify vendor of a new order."""
        if not isinstance(order, Order) or not VENDOR_TELEGRAM_ID:
            return

        try:
            msg = (
                f"🆕 New Order\n"
                f"Order ID: {order.id}\n"
                f"Customer: {order.customer_telegram_id if hasattr(order, 'customer') and hasattr(order.customer_telegram_id, 'username') else 'N/A'}\n"
                f"Type: {order.order_type.upper()} {order.asset.code if order.asset else 'N/A'}\n"
                f"Amount: {order.amount} (≈ {order.fiat_amount} fiat)"
            )
            bot.send_message(chat_id=VENDOR_TELEGRAM_ID, text=msg)  # type: ignore
            logger.info(f"Sent new order notification to vendor for order {order.id}")
        except Exception as e:
            logger.error(f"Failed to notify vendor for order {order.id}: {e}")

    @staticmethod
    def notify_vendor_customer_cancelled(order: Order) -> None:
        """Notify vendor when customer cancels an order."""
        if not isinstance(order, Order) or not VENDOR_TELEGRAM_ID:
            return

        try:
            msg = (
                f"⚠️ Customer Cancelled Order\n"
                f"Order ID: {order.id}\n"
                f"Type: {order.order_type.upper()} {order.asset.code if order.asset else 'N/A'}\n"
                f"Amount: {order.amount} (≈ {order.fiat_amount} fiat)"
            )
            bot.send_message(chat_id=VENDOR_TELEGRAM_ID, text=msg)  # type: ignore
            logger.info(
                f"Notified vendor of customer cancellation for order {order.id}"
            )
        except Exception as e:
            logger.error(
                f"Failed to notify vendor of cancellation for order {order.id}: {e}"
            )
