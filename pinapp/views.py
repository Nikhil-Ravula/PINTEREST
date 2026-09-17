import asyncio
import json
import logging
import threading

from django.conf import settings
from django.db import close_old_connections
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from telegram import Update

from pinapp.bot.runner import build_bot_application

logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(["POST"])
def telegram_webhook_view(request):
    """
    Receives incoming Telegram updates via HTTP POST.

    Returns 200 OK to Telegram immediately, then processes the update
    in a background thread. This prevents WSGI timeouts for slow commands
    like /new (Amazon scraping + Gemini calls take 30-60s).
    """
    # Optional: validate secret header to block fake requests
    secret = getattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
    if secret:
        incoming = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if incoming != secret:
            return HttpResponseForbidden("Invalid secret token.")

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return HttpResponseBadRequest("Invalid JSON.")

    def _process_in_background():
        # Close stale DB connections inherited from the main thread
        close_old_connections()

        async def _async_process():
            try:
                app = build_bot_application()
                await app.initialize()
                update = Update.de_json(data, app.bot)
                await app.process_update(update)
            except Exception as exc:
                logger.error("Error processing Telegram update: %s", exc, exc_info=True)
            finally:
                close_old_connections()

        asyncio.run(_async_process())

    thread = threading.Thread(target=_process_in_background, daemon=True)
    thread.start()

    # Return immediately — Telegram won't timeout or retry
    return HttpResponse("OK")
