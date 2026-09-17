"""
Management command to register or remove the Telegram webhook.

Usage:
    # Register webhook (run this once on PythonAnywhere):
    python manage.py set_webhook --url https://NikhilRavula.pythonanywhere.com

    # Remove webhook (switch back to polling):
    python manage.py set_webhook --delete
"""

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Register (or delete) the Telegram webhook with Telegram's servers."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--url",
            help="Your PythonAnywhere base URL, e.g. https://NikhilRavula.pythonanywhere.com",
        )
        group.add_argument(
            "--delete",
            action="store_true",
            help="Remove the currently registered webhook.",
        )
        parser.add_argument(
            "--secret",
            default="",
            help="Optional secret token Telegram will send in X-Telegram-Bot-Api-Secret-Token header.",
        )

    def handle(self, *args, **options):
        token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise CommandError("Set TELEGRAM_BOT_TOKEN in .env first.")

        api_base = f"https://api.telegram.org/bot{token}"

        if options["delete"]:
            self._delete_webhook(api_base)
        else:
            base_url = options["url"].rstrip("/")
            webhook_url = f"{base_url}/telegram/webhook/"
            secret = options.get("secret", "")
            self._set_webhook(api_base, webhook_url, secret)

    def _set_webhook(self, api_base, webhook_url, secret):
        payload = {
            "url": webhook_url,
            "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": True,
        }
        if secret:
            payload["secret_token"] = secret

        self.stdout.write(f"Registering webhook: {webhook_url}")
        resp = requests.post(f"{api_base}/setWebhook", json=payload, timeout=15)
        result = resp.json()

        if result.get("ok"):
            self.stdout.write(self.style.SUCCESS(
                f"Webhook set! Telegram will now POST to:\n  {webhook_url}"
            ))
        else:
            raise CommandError(f"Telegram error: {result.get('description', result)}")

    def _delete_webhook(self, api_base):
        self.stdout.write("Deleting webhook...")
        resp = requests.post(
            f"{api_base}/deleteWebhook",
            json={"drop_pending_updates": True},
            timeout=15,
        )
        result = resp.json()
        if result.get("ok"):
            self.stdout.write(self.style.SUCCESS("Webhook deleted. Bot is now in polling mode."))
        else:
            raise CommandError(f"Telegram error: {result.get('description', result)}")
