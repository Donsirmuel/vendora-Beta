# orders/bot_handlers.py
import logging
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    User,
)
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .bot_notify import BotNotifier

logger = logging.getLogger(__name__)

# -----------------------------
# STATE
# -----------------------------
user_sessions: Dict[int, Dict[str, Any]] = {}

# -----------------------------
# HELPERS
# -----------------------------
def get_username_or_id(u: Optional[User]) -> str:
    if u and getattr(u, "username", None):
        return str(u.username)
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
    if update.effective_user and update.effective_user.id:
        user_sessions[update.effective_user.id] = {}
    keyboard = [["Buy", "Sell"], ["Query"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("👋 Welcome to Vendora Bot! Choose an option:", reply_markup=reply_markup)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    user_id = update.effective_user.id
    text_raw = update.message.text
    text = (text_raw or "").strip().lower()
    session = user_sessions.setdefault(user_id, {})

    # Top-level choices
    if text in ["buy", "sell"]:
        session.clear()
        session.update({"type": text})
        if update.effective_chat and update.effective_chat.id:
            await send_asset_menu(update.effective_chat.id, context, text)
        return

    if text == "query":
        session.clear()
        session.update({"stage": "awaiting_query"})
        await update.message.reply_text("Please type your query message:")
        return

    # Handle order amount
    if session.get("stage") == "awaiting_amount":
        raw = (update.message.text or "").strip()
        try:
            amt = Decimal(raw)
            if amt <= 0:
                raise InvalidOperation()
        except Exception:
            await update.message.reply_text("❌ Invalid amount. Enter a positive number (e.g., 0.015).")
            return

        session.update({"amount": str(amt), "stage": "awaiting_contract_or_bank"})
        prompt = ("Please enter your contract address:" if session.get("type") == "buy"
                  else "Please enter your bank account for fiat transfer:")
        await update.message.reply_text(prompt)
        return

    # Handle customer query
    if session.get("stage") == "awaiting_query":
        msg = (update.message.text or "").strip()
        await update.message.reply_text("✅ Your query has been sent. You’ll get a reply here.")
        await BotNotifier.notify_vendor_new_order(msg)  # You might replace this with a proper notify_vendor_query function
        session["stage"] = "done"
        return

    await update.message.reply_text("Type Buy, Sell, or Query (or /start to begin).")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    user_id = update.effective_user.id
    session = user_sessions.get(user_id, {})
    if session.get("stage") != "awaiting_proof":
        return
    if not update.message.photo:
        return
    session["proof_file_id"] = update.message.photo[-1].file_id
    session["stage"] = "awaiting_contract_or_bank"

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
    session = user_sessions.setdefault(user_id, {})
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
            await query.edit_message_text(f"Enter amount of {asset} you want to {session['type']} (e.g., 0.015):")
        return

    if data == "CANCEL":
        session.clear()
        await query.edit_message_text("❌ Your order has been cancelled.")
        return

# -----------------------------
# REGISTRATION FUNCTION
# -----------------------------
def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
