import asyncio
import json
import logging
import threading

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

    Returns 200 OK immediately to Telegram, then processes the update
    in a background thread. This prevents WSGI timeouts for slow commands
    like /new (which does Amazon scraping + Gemini calls).
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

    # Process in a background thread so we return 200 to Telegram instantly.
    # Without this, slow commands (/new takes 30-60s) will timeout.
    def _process_in_background():
        async def _async_process():
            try:
                app = await get_or_create_bot_app()
                update = Update.de_json(data, app.bot)
                await app.process_update(update)
            except Exception as exc:
                logger.error("Error processing Telegram update: %s", exc, exc_info=True)

        asyncio.run(_async_process())

    thread = threading.Thread(target=_process_in_background, daemon=True)
    thread.start()

    # Return 200 immediately — Telegram won't retry
    return HttpResponse("OK")
