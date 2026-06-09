"""
handlers/commands.py
────────────────────
Telegram command handlers: /start, /migrate, /newsession
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes
from app.config import settings
from app.bot.session import touch_session, log_prefix, _KEY_SESSION, _log_session_banner

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


async def migrate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    One-time admin command: stamps version='new' onto any documents that
    predate the versioning system (i.e. have no 'version' metadata field).
    """
    user_id = update.effective_user.id
    if user_id != settings.AUTHORIZED_ID:
        return
    vs = context.bot_data.get("vs")
    if not vs:
        await update.message.reply_text("❌ Vector store not available.")
        return
    await update.message.reply_text("⏳ Running migration…")
    try:
        count = await vs.migrate_unversioned_documents()
        await update.message.reply_text(
            f"✅ Migration complete. {count} document(s) updated with <code>version='new'</code>.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"[/migrate] Exception: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Migration failed: {e}")


async def new_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /newsession — immediately starts a fresh agent session.
    Clears LangGraph conversation context; vault data in Qdrant is untouched.
    """
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if user_id != settings.AUTHORIZED_ID:
        return

    context.user_data[_KEY_SESSION] = context.user_data.get(_KEY_SESSION, 0) + 1
    touch_session(context.user_data)

    new_id = context.user_data[_KEY_SESSION]
    _log_session_banner(new_id, reason="/newsession command")
    prefix = log_prefix(chat_id, context.user_data)
    logger.info(f"{prefix} /newsession — session manually reset by user")
    await update.message.reply_text(
        "🔄 <i>New session started. Conversation context has been cleared.</i>",
        parse_mode="HTML",
    )
