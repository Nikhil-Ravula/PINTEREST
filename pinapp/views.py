import asyncio
import json
import logging
import threading

from django.conf import settings
from django.db import close_old_connections
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from telegram import Update

from pinapp.bot.runner import build_bot_application
from pinapp.models import SentProduct

logger = logging.getLogger(__name__)


# ── Dashboard pages ────────────────────────────────────────────────────────────

def index(request):
    return render(request, 'pinapp/index.html')

def discovery(request):
    return render(request, 'pinapp/discovery.html')

def library(request):
    return render(request, 'pinapp/library.html')

def automations(request):
    return render(request, 'pinapp/automations.html')


# ── API endpoints ──────────────────────────────────────────────────────────────

def api_sent_products(request):
    """Return list of sent products as JSON for the Library page."""
    products = SentProduct.objects.order_by('-sent_at')[:50]
    return JsonResponse({
        'total': SentProduct.objects.count(),
        'products': [{
            'asin': p.asin,
            'title': p.title,
            'url': f'https://www.amazon.in/dp/{p.asin}' if p.asin else '',
            'image_url': '',
            'sent_at': p.sent_at.strftime('%d %b %Y, %H:%M') if p.sent_at else '',
        } for p in products]
    })

@csrf_exempt
def api_reset(request):
    """Clear all sent product history."""
    if request.method == 'POST':
        n = SentProduct.objects.count()
        SentProduct.objects.all().delete()
        return JsonResponse({'cleared': n})
    return JsonResponse({'error': 'POST required'}, status=405)


# ── Telegram webhook ───────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def telegram_webhook_view(request):
    """
    Receives incoming Telegram updates via HTTP POST.

    Returns 200 OK to Telegram immediately, then processes the update
    in a background thread. This prevents WSGI timeouts for slow commands
    like /new (Amazon scraping + Gemini calls take 30-60s).
    """
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

    return HttpResponse("OK")
