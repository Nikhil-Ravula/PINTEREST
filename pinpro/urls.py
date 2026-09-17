from django.contrib import admin
from django.urls import path

from pinapp.views import telegram_webhook_view

urlpatterns = [
    path('admin/', admin.site.urls),
    path('telegram/webhook/', telegram_webhook_view, name='telegram_webhook'),
]
