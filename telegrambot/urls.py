from django.urls import path
from . import views

urlpatterns = [
    path("notify-bot/", views.notify_bot, name="notify_bot"),
]
