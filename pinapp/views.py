import json
import logging

from asgiref.sync import async_to_sync
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from telegram import Update

from pinapp.bot.runner import get_or_create_bot_app

logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(["POST"])
def telegram_webhook_view(request):
    """
    Receives incoming Telegram updates via HTTP POST.
    Telegram calls this URL for every user message/command.
    """
    # Optional: verify the secret token header to block fake requests
    secret = getattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
    if secret:
        incoming = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if incoming != secret:
            return HttpResponseForbidden("Invalid secret token.")

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return HttpResponseBadRequest("Invalid JSON.")

    async def _process():
        app = await get_or_create_bot_app()
        update = Update.de_json(data, app.bot)
        await app.process_update(update)

    try:
        async_to_sync(_process)()
    except Exception as exc:
        logger.error("Error processing Telegram update: %s", exc, exc_info=True)
        # Always return 200 so Telegram does not retry endlessly
        return HttpResponse("Error logged.", status=200)

    return HttpResponse("OK")
