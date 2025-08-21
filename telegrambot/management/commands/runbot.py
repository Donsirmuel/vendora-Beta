import os
import logging
import uuid
from decimal import Decimal, InvalidOperation
import requests
from typing import Any, Dict, Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    User,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from orders.models import BotSession

# -----------------------------
# CONFIGURATION
# -----------------------------
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
VENDOR_TELEGRAM_ID = int(os.environ.get("VENDORA_VENDOR_ID", 0))
RATES_URL = os.environ.get("VENDORA_RATES_URL", "http://127.0.0.1:8000/orders/get-rate/")
CREATE_ORDER_URL = os.environ.get("VENDORA_CREATE_ORDER_URL", "http://127.0.0.1:8000/orders/bot/create-order/")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# -----------------------------
# DATABASE SESSION HELPERS
# -----------------------------
def get_session(user_id: int) -> dict:
    session_obj, _ = BotSession.objects.get_or_create(telegram_id=user_id)
    return session_obj.data

def save_session(user_id: int, data: dict) -> None:
    session_obj, _ = BotSession.objects.get_or_create(telegram_id=user_id)
    session_obj.data = data
    session_obj.save()

# -----------------------------
# BOT HELPERS
# -----------------------------
def generate_order_id() -> str:
    return str(uuid.uuid4())[:8]

def fetch_rate(asset_code: str) -> Optional[Decimal]:
    try:
        r = requests.get(RATES_URL, params={"asset": asset_code}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            rate_val = data.get("rate", "")
            if rate_val in (None, ""):
                return None
            return Decimal(str(rate_val))
    except Exception as e:
        logger.error(f"fetch_rate error: {e}")
    return None

def post_order_to_webapp(payload: Dict[str, Any]) -> Optional[str]:
    try:
        r = requests.post(CREATE_ORDER_URL, json=payload, timeout=15)
        if r.status_code in (200, 201):
            return str(r.json().get("order_id"))
        logger.warning(f"Order create failed: {r.status_code} {r.text}")
    except Exception as e:
        logger.error(f"post_order_to_webapp error: {e}")
    return None

async def notify_vendor(application, message: str) -> None:
    if VENDOR_TELEGRAM_ID:
        try:
            await application.bot.send_message(chat_id=VENDOR_TELEGRAM_ID, text=message)
        except Exception as e:
            logger.warning(f"notify_vendor error: {e}")

def get_username_or_id(u: Optional[User]) -> str:
    if u and getattr(u, "username", None):
        return str(u.username) if u.username else "unknown"
    if u and getattr(u, "id", None):
        return str(u.id)
    return "unknown"

async def send_asset_menu(chat_id: int, context: ContextTypes.DEFAULT_TYPE, order_type: str) -> None:
    prefix = "BUY" if order_type == "buy" else "SELL"
    keyboard = [
        [InlineKeyboardButton("BTC", callback_data=f"{prefix}:BTC")],
        [InlineKeyboardButton("ETH", callback_data=f"{prefix}:ETH")],
        [InlineKeyboardButton("USDT (TRC20)", callback_data=f"{prefix}:USDT")],
        [InlineKeyboardButton("SOLANA", callback_data=f"{prefix}:SOLANA")],
        [InlineKeyboardButton("Other", callback_data=f"{prefix}:OTHER")],
    ]
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Select an asset to {order_type.upper()}:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# -----------------------------
# COMMANDS & HANDLERS
# -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user_id = update.effective_user.id
    save_session(user_id, {})  # clear previous session
    keyboard = [["Buy", "Sell"], ["Query"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("👋 Welcome to Vendora Bot! Choose an option:", reply_markup=reply_markup)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    user_id = update.effective_user.id
    text_raw = update.message.text
    text = (text_raw or "").strip().lower()
    session = get_session(user_id)

    # -----------------------------
    # Top-level choices
    # -----------------------------
    if text in ["buy", "sell"]:
        session.clear()
        session.update({"type": text})
        save_session(user_id, session)
        await send_asset_menu(update.effective_chat.id, context, text)
        return

    if text == "query":
        session.clear()
        session.update({"stage": "awaiting_query"})
        save_session(user_id, session)
        await update.message.reply_text("Please type your query message:")
        return

    if session.get("stage") == "awaiting_amount":
        raw = (update.message.text or "").strip()
        try:
            amt = Decimal(raw)
            if amt <= 0:
                raise InvalidOperation()
        except Exception:
            await update.message.reply_text("❌ Invalid amount. Enter a positive number (e.g., 0.015).")
            return

        asset = session.get("asset")
        if not asset:
            await update.message.reply_text("Asset missing. Please /start again.")
            session.clear()
            save_session(user_id, session)
            return

        rate = fetch_rate(asset)
        if rate is None:
            await update.message.reply_text("⚠️ Could not fetch rate. Try again later.")
            return

        fiat = (amt * rate).quantize(Decimal("0.01"))
        session.update({
            "amount": str(amt),
            "rate": str(rate),
            "fiat_amount": str(fiat),
            "stage": "rate_confirm",
            "order_id": generate_order_id(),
        })
        save_session(user_id, session)

        keyboard = [[
            InlineKeyboardButton("Continue", callback_data="CONTINUE"),
            InlineKeyboardButton("Cancel", callback_data="CANCEL"),
        ]]
        await update.message.reply_text(
            f"🧾 Summary\n"
            f"Type: {session.get('type','').upper()}\n"
            f"Asset: {asset}\n"
            f"Amount: {amt}\n"
            f"Rate: {rate}\n"
            f"Fiat (est.): {fiat}\n\n"
            f"Proceed?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if session.get("stage") == "awaiting_contract_or_bank":
        entered = (update.message.text or "").strip()
        if session.get("type") == "buy":
            session["contract_address"] = entered
        else:
            session["bank_account"] = entered

        payload = {
            "order_type": session.get("type"),
            "asset_code": session.get("asset", ""),
            "customer_telegram_id": str(user_id),
            "amount": session.get("amount"),
            "fiat_amount": session.get("fiat_amount"),
            "contract_address": session.get("contract_address", None),
            "bank_account": session.get("bank_account", None),
        }
        created_id = post_order_to_webapp(payload)

        await update.message.reply_text(
            f"✅ Order received! Order ID: {session.get('order_id','N/A')}"
            + ("" if created_id else "\n(Will sync with webapp later.)")
        )

        await notify_vendor(
            context.application,
            f"New order from @{get_username_or_id(update.effective_user)}\n"
            f"Type: {session.get('type','').upper()} {session.get('asset','')}\n"
            f"Amount: {session.get('amount','')} (≈ {session.get('fiat_amount','')} fiat)\n"
            f"Local ID: {session.get('order_id','N/A')}\n"
            f"Webapp ID: {created_id or 'n/a'}"
        )
        session["stage"] = "done"
        save_session(user_id, session)
        return

    if session.get("stage") == "awaiting_query":
        msg = (update.message.text or "").strip()
        await update.message.reply_text("✅ Your query has been sent. You’ll get a reply here.")
        await notify_vendor(
            context.application,
            f"Customer query from @{get_username_or_id(update.effective_user)}:\n{msg}"
        )
        session["stage"] = "done"
        save_session(user_id, session)
        return

    await update.message.reply_text("Type Buy, Sell, or Query (or /start to begin).")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    user_id = update.effective_user.id
    session = get_session(user_id)
    if session.get("stage") != "awaiting_proof":
        return
    if not update.message.photo:
        return
    session["proof_file_id"] = update.message.photo[-1].file_id
    session["stage"] = "awaiting_contract_or_bank"
    save_session(user_id, session)

    prompt = ("✅ Proof received! Please send your contract address to receive crypto."
              if session.get("type") == "buy"
              else "✅ Proof received! Please send your bank account details to receive fiat.")
    await update.message.reply_text(prompt)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    user = query.from_user
    user_id = user.id if user else 0
    session = get_session(user_id)
    data = (query.data or "").strip().upper()

    if data.startswith(("BUY:", "SELL:")):
        parts = data.split(":")
        if len(parts) == 2:
            action, asset = parts
            session.clear()
            session.update({
                "type": "buy" if action == "BUY" else "sell",
                "asset": asset,
                "stage": "awaiting_amount",
            })
            save_session(user_id, session)
            await query.edit_message_text(f"Enter amount of {asset} you want to {session['type']} (e.g., 0.015):")
        return

    if data == "CONTINUE":
        session["stage"] = "awaiting_payment"
        save_session(user_id, session)
        keyboard = [[InlineKeyboardButton("Payment Made", callback_data="PAYMENT_MADE")]]
        await query.edit_message_text(
            "🔔 Vendor has been notified. When you've paid/sent, tap **Payment Made**.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        await notify_vendor(
            context.application,
            f"Customer @{get_username_or_id(user)} started {session.get('type','').upper()} "
            f"{session.get('asset','')} | Amount {session.get('amount','')} "
            f"(≈ {session.get('fiat_amount','')} fiat). Awaiting payment/proof."
        )
        return

    if data == "CANCEL":
        session.clear()
        save_session(user_id, session)
        await query.edit_message_text("❌ Your order has been cancelled.")
        await notify_vendor(context.application, f"Customer @{get_username_or_id(user)} cancelled the order.")
        return

    if data == "PAYMENT_MADE":
        session["stage"] = "awaiting_proof"
        save_session(user_id, session)
        await query.edit_message_text("📤 Please upload your proof (photo).")
        return

# -----------------------------
# ENTRYPOINT
# -----------------------------
class Command:
    help = "Run the Telegram bot"

    def handle(self, *args, **options):
        if not TOKEN:
            raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set.")
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CallbackQueryHandler(button_handler))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
        app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        app.add_handler(CommandHandler("query", start))

        print("Bot is running…")
        app.run_polling()
