from django.contrib import admin
from django.urls import path

from pinapp.views import (
    index, discovery, library, automations,
    api_sent_products, api_reset,
    telegram_webhook_view,
)

urlpatterns = [
    path('admin/', admin.site.urls),

    # Dashboard pages
    path('', index, name='index'),
    path('discovery/', discovery, name='discovery'),
    path('library/', library, name='library'),
    path('automations/', automations, name='automations'),

    # API
    path('api/sent-products/', api_sent_products, name='api_sent_products'),
    path('api/reset/', api_reset, name='api_reset'),

    # Telegram webhook
    path('telegram/webhook/', telegram_webhook_view, name='telegram_webhook'),
]
