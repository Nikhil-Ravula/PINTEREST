import asyncio
import base64
import json
import logging
import os
import threading
import urllib.parse

import requests
from django.conf import settings
from django.db import close_old_connections
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import render, redirect
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

def privacy(request):
    return render(request, 'pinapp/privacy.html')


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


@csrf_exempt
def trigger_reminder_view(request):
    """
    HTTP endpoint to trigger the 'Ready for post?' Telegram check-in.
    Can be called by free external cron services (e.g. cron-job.org) every 30 minutes.
    """
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return JsonResponse({"error": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set"}, status=500)

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": (
            "⏰ <b>Ready for a new Pinterest post?</b>\n\n"
            "Would you like to discover a fresh trending product and create a Pin right now?"
        ),
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "✅ Yes, let's post!", "callback_data": "reminder_yes"},
                    {"text": "❌ No, not now", "callback_data": "reminder_no"},
                ]
            ]
        },
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            return JsonResponse({"status": "success", "message": "Reminder sent to Telegram"})
        else:
            return JsonResponse({"status": "error", "details": resp.text}, status=resp.status_code)
    except Exception as exc:
        logger.error(f"Failed to send reminder via trigger: {exc}")
        return JsonResponse({"status": "error", "error": str(exc)}, status=500)


# ── Pinterest OAuth2 Flow ──────────────────────────────────────────────────────

def update_env_variable(key: str, value: str):
    """Update or append an environment variable to the .env file and process environment."""
    env_path = settings.BASE_DIR / '.env'
    os.environ[key] = value
    setattr(settings, key, value)
    if not env_path.exists():
        return
    try:
        lines = env_path.read_text(encoding='utf-8').splitlines()
        found = False
        new_lines = []
        for line in lines:
            if line.startswith(f"{key}="):
                new_lines.append(f"{key}={value}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={value}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding='utf-8')
    except Exception as exc:
        logger.error(f"Error updating .env for {key}: {exc}")


def pinterest_connect(request):
    """Redirect user to Pinterest OAuth2 authorization page with full write scopes."""
    client_id = getattr(settings, "PINTEREST_APP_ID", "1631413")
    redirect_uri = getattr(settings, "PINTEREST_REDIRECT_URI", "https://6049.pythonanywhere.com/pinterest/callback/")
    scopes = "boards:read,boards:write,pins:read,pins:write,user_accounts:read"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "state": "pinorbit_auth",
    }
    url = f"https://www.pinterest.com/oauth/?{urllib.parse.urlencode(params)}"
    return redirect(url)


def pinterest_callback(request):
    """Handle Pinterest OAuth2 redirect and exchange authorization code for access and refresh tokens."""
    error = request.GET.get("error")
    if error:
        desc = request.GET.get("error_description", error)
        return HttpResponse(f"<h2>Pinterest Authorization Denied</h2><p>{desc}</p><a href='/'>Return home</a>", status=400)

    code = request.GET.get("code")
    if not code:
        return HttpResponse("<h2>Missing authorization code from Pinterest</h2>", status=400)

    client_id = getattr(settings, "PINTEREST_APP_ID", "1631413")
    client_secret = getattr(settings, "PINTEREST_APP_SECRET", "")
    redirect_uri = getattr(settings, "PINTEREST_REDIRECT_URI", "https://6049.pythonanywhere.com/pinterest/callback/")

    if not client_secret:
        return HttpResponse("<h2>PINTEREST_APP_SECRET not set in .env</h2>", status=500)

    auth_str = f"{client_id}:{client_secret}"
    b64_auth = base64.b64encode(auth_str.encode()).decode()

    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }

    try:
        resp = requests.post(
            "https://api.pinterest.com/v5/oauth/token",
            headers=headers,
            data=data,
            timeout=30,
        )
        if resp.status_code in (200, 201):
            token_data = resp.json()
            access_token = token_data.get("access_token", "")
            refresh_token = token_data.get("refresh_token", "")
            scope = token_data.get("scope", "")

            if access_token:
                update_env_variable("PINTEREST_ACCESS_TOKEN", access_token)
            if refresh_token:
                update_env_variable("PINTEREST_REFRESH_TOKEN", refresh_token)

            return render(request, 'pinapp/pinterest_success.html', {
                'scope': scope,
                'has_refresh': bool(refresh_token),
            })
        else:
            err = resp.json() if resp.content else {}
            msg = err.get("message") or resp.text
            return HttpResponse(
                f"<h2>Token Exchange Failed ({resp.status_code})</h2><p>{msg}</p><a href='/'>Return home</a>",
                status=resp.status_code,
            )
    except Exception as exc:
        logger.error(f"Failed to exchange Pinterest code: {exc}", exc_info=True)
        return HttpResponse(f"<h2>Connection error during token exchange</h2><p>{exc}</p>", status=500)
