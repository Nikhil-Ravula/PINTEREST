from django.contrib import admin
from django.urls import path

from pinapp.views import (
    index, discovery, library, automations, privacy,
    api_sent_products, api_reset,
    telegram_webhook_view,
    trigger_reminder_view,
    pinterest_connect, pinterest_callback,
)

urlpatterns = [
    path('admin/', admin.site.urls),

    # Dashboard pages
    path('', index, name='index'),
    path('discovery/', discovery, name='discovery'),
    path('library/', library, name='library'),
    path('automations/', automations, name='automations'),
    path('privacy/', privacy, name='privacy'),

    # Pinterest OAuth2
    path('pinterest/connect/', pinterest_connect, name='pinterest_connect'),
    path('pinterest/callback/', pinterest_callback, name='pinterest_callback'),

    # API
    path('api/sent-products/', api_sent_products, name='api_sent_products'),
    path('api/reset/', api_reset, name='api_reset'),

    # Telegram webhook & reminder trigger
    path('telegram/webhook/', telegram_webhook_view, name='telegram_webhook'),
    path('telegram/trigger-reminder/', trigger_reminder_view, name='trigger_reminder'),
]
