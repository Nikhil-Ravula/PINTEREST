"""
Bot runner — builds a fresh Application per background thread.

Each background thread runs its own asyncio event loop (via asyncio.run()),
so we cannot share a single Application instance across threads. Instead we
build a lightweight Application for every incoming webhook update.

Handler registration is fast (no network calls), so there is no meaningful
overhead per request.
"""

import logging

from django.conf import settings
from telegram.ext import Application, CommandHandler

logger = logging.getLogger(__name__)


def build_bot_application() -> Application:
    """
    Build and return a new Application with all command handlers registered.
    Does NOT call app.initialize() — that is done inside the async context.
    """
    from pinapp.management.commands.run_bot import (
        cmd_start,
        cmd_new,
        cmd_stats,
        cmd_reset,
        error_handler,
    )

    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_error_handler(error_handler)
    return app
