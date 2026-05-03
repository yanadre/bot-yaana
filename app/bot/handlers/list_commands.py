"""
handlers/list_commands.py
─────────────────────────
Fast-path command handlers for structured list documents.
No LLM involved — direct Qdrant queries + render via lists.py.

Commands:
  /list              → show all shopping lists (pick one)
  /list <name>       → open a specific shopping list
  /tasks             → show all task lists (pick one)
  /tasks <name>      → open a specific task list
  /newlist <name>    → instantly create a new (empty) shopping list
  /newtasks <name>   → instantly create a new (empty) task list
"""

import logging
import uuid
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.config import settings
from app.bot.lists import render_list_text, render_list_keyboard
from app.bot.structure_types import regenerate_text

logger = logging.getLogger("bot")


def _is_authorized(user_id: int) -> bool:
    return user_id == settings.AUTHORIZED_ID


async def _open_list(update: Update, context: ContextTypes.DEFAULT_TYPE, item_type: str) -> None:
    """
    Shared logic for /list and /tasks.
    With no args: shows all lists of that type to pick from.
    With a name arg: opens that specific list directly.
    """
    user_id = update.effective_user.id
    if not _is_authorized(user_id):
        await update.message.reply_text("🚫 Access denied.")
        return

    vs = context.bot_data.get("vs")
    if not vs:
        await update.message.reply_text("❌ Vector store not available.")
        return

    args = context.args  # words after the command
    name_query = " ".join(args).strip().lower() if args else ""

    try:
        docs = await vs.search(
            query=name_query or item_type,
            filter_dict={"item_type": item_type},
            top_k=20,
            score_threshold=0.0,
        )
    except Exception as e:
        logger.error(f"[list_commands] search failed: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Could not fetch lists: {e}")
        return

    if not docs:
        type_label = "shopping lists" if item_type == "shopping_list" else "task lists"
        await update.message.reply_text(
            f"📭 No {type_label} found.\n\n"
            f'You can ask me to create one, e.g. <i>"Create a groceries shopping list"</i>',
            parse_mode="HTML",
        )
        return

    # If user provided a name, try to find an exact (or close) match
    if name_query:
        match = next(
            (d for d in docs if d.get("metadata", {}).get("name", "").lower() == name_query),
            docs[0],  # fall back to best semantic match
        )
        await _send_list(update, match, page=0)
        return

    # No name given and only one list → open it directly
    if len(docs) == 1:
        await _send_list(update, docs[0], page=0)
        return

    # Multiple lists → show a picker
    type_label = "Shopping Lists" if item_type == "shopping_list" else "Task Lists"
    emoji = "🛒" if item_type == "shopping_list" else "✅"
    buttons = []
    for doc in docs:
        meta = doc.get("metadata", {})
        name = meta.get("name", "Unnamed")
        doc_id = meta.get("id", "")
        count = len(meta.get("items", []))
        done  = sum(1 for i in meta.get("items", []) if i.get("checked"))
        buttons.append([InlineKeyboardButton(
            f"{emoji} {name}  ({done}/{count})",
            callback_data=f"list_open_{doc_id}",
        )])

    await update.message.reply_text(
        f"<b>{type_label}</b>\nChoose a list:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _send_list(update: Update, doc: dict, page: int = 0, show_done: bool = False) -> None:
    text     = render_list_text(doc, page=page, show_done=show_done)
    keyboard = render_list_keyboard(doc, page=page, show_done=show_done)
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Public handlers ───────────────────────────────────────────────────────────

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/list [name] — open a shopping list"""
    await _open_list(update, context, item_type="shopping_list")


async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/tasks [name] — open a task list"""
    await _open_list(update, context, item_type="task_list")


# ── New list creation helpers ─────────────────────────────────────────────────

async def _create_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    item_type: str,
) -> None:
    """
    Shared logic for /newlist and /newtasks.
    Requires a name argument — creates an empty structured document immediately.
    """
    user_id = update.effective_user.id
    if not _is_authorized(user_id):
        await update.message.reply_text("🚫 Access denied.")
        return

    vs = context.bot_data.get("vs")
    if not vs:
        await update.message.reply_text("❌ Vector store not available.")
        return

    args = context.args
    name = " ".join(args).strip() if args else ""
    if not name:
        type_str = "shopping list" if item_type == "shopping_list" else "task list"
        await update.message.reply_text(
            f"❌ Please provide a name.\n"
            f"Usage: <code>/{'newlist' if item_type == 'shopping_list' else 'newtasks'} My {type_str.title()}</code>",
            parse_mode="HTML",
        )
        return

    # Check for duplicate names (same type)
    try:
        existing = await vs.search(
            query=name,
            filter_dict={"item_type": item_type},
            top_k=5,
            score_threshold=0.0,
        )
        if any(d.get("metadata", {}).get("name", "").lower() == name.lower() for d in existing):
            await update.message.reply_text(
                f"⚠️ A list named <b>{name}</b> already exists.\n"
                f"Use <code>/{'list' if item_type == 'shopping_list' else 'tasks'} {name}</code> to open it.",
                parse_mode="HTML",
            )
            return
    except Exception as e:
        logger.warning(f"[list_commands] duplicate-check search failed (non-fatal): {e}")

    now    = datetime.now(timezone.utc).isoformat()
    doc_id = str(uuid.uuid4())
    metadata = {
        "id":               doc_id,
        "name":             name,
        "item_type":        item_type,
        "items":            [],
        "creation_datetime": now,
        "update_datetime":  now,
    }
    text = regenerate_text(name, [])

    try:
        await vs.add(texts=[text], metadatas=[metadata])
        logger.info(f"[list_commands] created {item_type} doc_id={doc_id!r} name={name!r}")
    except Exception as e:
        logger.error(f"[list_commands] failed to create list: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Could not create list: {e}")
        return

    # Build a minimal doc dict for rendering
    doc = {"text": text, "metadata": metadata}
    text_msg  = render_list_text(doc, page=0, show_done=False)
    keyboard  = render_list_keyboard(doc, page=0, show_done=False)
    type_label = "Shopping list" if item_type == "shopping_list" else "Task list"
    await update.message.reply_text(
        f"✅ <b>{type_label} created!</b>\n\n{text_msg}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def newlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/newlist <name> — instantly create an empty shopping list"""
    await _create_list(update, context, item_type="shopping_list")


async def newtasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/newtasks <name> — instantly create an empty task list"""
    await _create_list(update, context, item_type="task_list")
