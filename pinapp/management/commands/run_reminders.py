import os
import sys
import time
import requests
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Send recurring 'Ready to post?' check-in reminders to Telegram."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=int,
            default=None,
            help="Interval in minutes (default from REMINDER_INTERVAL_MINUTES or 30).",
        )
        parser.add_argument(
            "--now",
            action="store_true",
            help="Send one reminder immediately and exit.",
        )
        parser.add_argument(
            "--hourly",
            action="store_true",
            help="For PythonAnywhere Free Tier hourly tasks: sends now, sleeps 30 mins, sends again, then exits.",
        )

    def handle(self, *args, **options):
        token = getattr(settings, "TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat_id:
            self.stderr.write("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env.")
            return

        interval_minutes = options["interval"] or getattr(settings, "REMINDER_INTERVAL_MINUTES", 30)
        interval_seconds = interval_minutes * 60

        def _send():
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
                resp = requests.post(url, json=payload, timeout=20)
                if resp.status_code == 200:
                    self.stdout.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Reminder sent successfully.")
                else:
                    self.stderr.write(f"Failed to send reminder: {resp.status_code} {resp.text}")
            except Exception as exc:
                self.stderr.write(f"Error sending reminder: {exc}")

        if options["now"]:
            _send()
            return

        # PythonAnywhere Free Tier hourly scheduled task mode
        if options["hourly"]:
            self.stdout.write(self.style.SUCCESS("Hourly task mode started."))
            _send()
            self.stdout.write("Sleeping 30 minutes for second check-in...")
            time.sleep(1800)
            _send()
            self.stdout.write("Hourly cycle complete.")
            return

        # Continuous loop mode (e.g. inside PythonAnywhere console)
        self.stdout.write(self.style.SUCCESS(
            f"Reminder service started! Sending check-ins every {interval_minutes} minutes to chat {chat_id}."
        ))
        while True:
            _send()
            self.stdout.write(f"Sleeping for {interval_minutes} minutes ({interval_seconds}s)...")
            try:
                time.sleep(interval_seconds)
            except KeyboardInterrupt:
                self.stdout.write("Reminder service stopped.")
                break
