from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
from telegram import Bot
from django.conf import settings

# Create your views here.

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)

@csrf_exempt
@require_POST
def notify_bot(request):
    try:
        data = json.loads(request.body.decode("utf-8"))

        chat_id = data.get("chat_id")
        status = data.get("status")
        order_id = data.get("order_id")

        if not chat_id or not status or not order_id:
            return JsonResponse({"error": "Missing fields"}, status=400)

        # Construct message
        if status == "accepted":
            message = f"✅ Your order {order_id} has been *ACCEPTED*. Please proceed with payment."
        elif status == "rejected":
            message = f"❌ Your order {order_id} has been *REJECTED*."
        elif status == "completed":
            message = f"🎉 Your order {order_id} is *COMPLETED*. Thank you for using Vendora!"
        else:
            message = f"ℹ️ Update for your order {order_id}: {status}"

        # Send message to user
        bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown") # type: ignore

        return JsonResponse({"success": True, "message_sent": message})

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)