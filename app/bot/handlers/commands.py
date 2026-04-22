"""
handlers/commands.py
────────────────────
Telegram command handlers: /start
(The legacy /add and /search commands are kept here but commented out —
they were replaced by the conversational agent flow.)
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes
from app.config import settings

logger = logging.getLogger("bot")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    logger.info(f"[/start] user_id={user_id}, chat_id={chat_id}")
    try:
        if user_id != settings.AUTHORIZED_ID:
            logger.warning(f"[/start] Unauthorized user_id={user_id}")
            await update.message.reply_text("🚫 Access Denied. You are not authorized.")
            return
        await update.message.reply_text("Welcome back!")
    except Exception as e:
        logger.error(f"[/start] Exception: {e}", exc_info=True)
