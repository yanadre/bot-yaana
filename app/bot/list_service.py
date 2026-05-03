"""
list_service.py
───────────────
Shared helpers for list document I/O and Telegram rendering.
Used by chat.py, callbacks.py, and list_commands.py so that
render + edit/reply logic lives in one place.

Public API:
  fetch_doc(vs, doc_id)                          → dict | None
  save_items(vs, doc_id, meta, items)            → None
  render_list(doc, context, doc_id)              → (text, keyboard)
  edit_list_message(bot, chat_id, msg_id, ...)   → bool
  reply_list_message(message, doc, ...)          → None
"""

import logging

from telegram import InlineKeyboardMarkup, Message
from telegram.ext import ContextTypes

from app.bot.lists import render_list_text, render_list_keyboard
from app.bot.structure_types import regenerate_text

logger = logging.getLogger("bot")


# ── Qdrant helpers ─────────────────────────────────────────────────────────────

async def fetch_doc(vs, doc_id: str) -> dict | None:
    """Fetch the current (version=new) doc by its logical id. Returns None if not found."""
    docs = await vs.search(query="", filter_dict={"id": doc_id}, top_k=1)
    return docs[0] if docs else None


async def save_items(vs, doc_id: str, meta: dict, items: list) -> None:
    """
    Persist a new items list to the document via patch_metadata.
    Re-embeds the text vector in-place (no new versioned copy).
    """
    from datetime import datetime, timezone
    now      = datetime.now(timezone.utc).isoformat()
    new_text = regenerate_text(meta.get("name", ""), items)
    await vs.patch_metadata(doc_id, {"items": items, "update_datetime": now}, new_text=new_text)


# ── Rendering helpers ──────────────────────────────────────────────────────────

def render_list(doc: dict, context: ContextTypes.DEFAULT_TYPE, doc_id: str) -> tuple[str, list]:
    """Return (html_text, keyboard) respecting stored page/show_done state."""
    page      = context.user_data.get(f"list_page_{doc_id}", 0)
    show_done = context.user_data.get(f"list_showdone_{doc_id}", False)
    text      = render_list_text(doc, page=page, show_done=show_done)
    keyboard  = render_list_keyboard(doc, page=page, show_done=show_done)
    return text, keyboard


async def edit_list_message(
    bot,
    chat_id: int,
    message_id: int,
    doc: dict,
    context: ContextTypes.DEFAULT_TYPE,
    doc_id: str,
) -> bool:
    """
    Edit an existing Telegram message in-place with the updated list UI.
    Returns True on success, False on failure (caller can fall back to reply).
    """
    text, keyboard = render_list(doc, context, doc_id)
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return True
    except Exception as e:
        logger.warning(f"[list_service] edit_list_message failed: {e}")
        return False


async def reply_list_message(
    message: Message,
    doc: dict,
    context: ContextTypes.DEFAULT_TYPE,
    doc_id: str,
) -> None:
    """Send the list UI as a new reply message."""
    text, keyboard = render_list(doc, context, doc_id)
    await message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
