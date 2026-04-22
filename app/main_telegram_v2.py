"""
main_telegram_v2.py
───────────────────
Entry point for the Telegram bot (v2 — modular).
All logic lives in app/bot/; this file only wires handlers and starts polling.

To run:
  docker-compose up --build
  or locally:
  python -m app.main_telegram_v2
"""

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from app.config import settings
from app.bot.setup import on_startup, on_shutdown
from app.bot.handlers.commands import start, migrate
from app.bot.handlers.chat import handle_agent_chat
from app.bot.handlers.callbacks import handle_callback


def build_application():
    app = (
        ApplicationBuilder()
        .token(settings.TELEGRAM_TOKEN)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("migrate", migrate))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_agent_chat))

    return app


if __name__ == "__main__":
    build_application().run_polling()
