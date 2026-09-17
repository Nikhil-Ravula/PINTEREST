"""
Bot runner — lazy-initialized singleton Application for webhook mode.
The bot is built once on the first incoming webhook request and reused.
"""

import logging

from django.conf import settings
from telegram import Update
from telegram.ext import Application, CommandHandler

logger = logging.getLogger(__name__)

_bot_app_instance = None


def _build_application(token: str) -> Application:
    """Build the Application and register all command handlers."""
    # Import handlers from run_bot so we don't duplicate logic
    from pinapp.management.commands.run_bot import (
        cmd_start,
        cmd_new,
        cmd_stats,
        cmd_reset,
        error_handler,
    )

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_error_handler(error_handler)
    return app


async def get_or_create_bot_app() -> Application:
    """
    Return the cached bot Application, creating and initializing it on first call.
    Safe to call on every webhook request — initialization only runs once.
    """
    global _bot_app_instance

    if _bot_app_instance is None:
        token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")

        app = _build_application(token)
        await app.initialize()
        _bot_app_instance = app
        logger.info("Bot application initialized.")

    return _bot_app_instance
