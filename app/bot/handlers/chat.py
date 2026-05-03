"""
handlers/chat.py
────────────────
Handles all incoming text messages from the user.

State machine (stored in context.user_data):
┌──────────────────────────────┬──────────────────────────────────────────────┐
│ Key                          │ Meaning                                      │
├──────────────────────────────┼──────────────────────────────────────────────┤
│ awaiting_update_changes      │ User confirmed the doc; waiting for them to  │
│                              │ type what should change (free-text input).   │
│ pending_update_doc           │ The current document dict (before/after).    │
│ pending_update_filters       │ Qdrant filter dict used to locate the doc.   │
│ pending_update_new_metadata  │ Agent-proposed changes (may be pre-filled).  │
│ refining_update_search       │ User asked for "another document" — next     │
│                              │ message is passed straight to the agent.     │
│ pending_list_add_doc_id      │ doc_id of the list the user is adding an     │
│                              │ item to; next message is the new item text.  │
│ pending_list_add_message_id  │ message_id of the list UI to edit in-place.  │
│ list_page_<doc_id>           │ Current page index for a list document UI.   │
│ list_showdone_<doc_id>       │ Whether done items are shown in this list.   │
└──────────────────────────────┴──────────────────────────────────────────────┘
"""

import ast
import json
import logging

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.config import settings
from app.bot.formatting import format_agent_response
from app.bot.hitl import (
    parse_interrupt, has_interrupt, build_approval_ui,
    build_multi_delete_text, build_multi_delete_keyboard,
)
from app.bot.list_service import fetch_doc, save_items, edit_list_message, reply_list_message
from app.bot.structure_types import make_item, is_list_type
from app.bot.update_flow import apply_user_described_update, build_update_summary

logger = logging.getLogger("bot")


def _agent_config(chat_id: int, vs) -> dict:
    return {
        "configurable": {
            "thread_id": str(chat_id),
            "vs": vs,
        }
    }


# ── Entry point ───────────────────────────────────────────────────────────────

async def handle_agent_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text    = update.message.text
    logger.info(f"[chat] user_id={user_id}, chat_id={chat_id}: {text!r}")

    try:
        if user_id != settings.AUTHORIZED_ID:
            logger.warning(f"[chat] Unauthorized user_id={user_id}")
            return

        vs    = context.bot_data["vs"]
        agent = context.bot_data["agent"]

        # ── Pending state checks (fast path, no LLM) ─────────────────────────
        if doc_id := context.user_data.pop("pending_list_add_doc_id", None):
            await _handle_list_add(update, context, vs, text, doc_id)
            return

        if context.user_data.pop("refining_delete_search", False):
            await _handle_delete_refinement(update, context, vs, text)
            return

        if context.user_data.pop("awaiting_update_changes", False):
            await _handle_update_description(update, context, vs, text)
            return

        # refining_update_search: fall through to agent (no early return)
        if context.user_data.pop("refining_update_search", False):
            logger.info("[chat] Refinement message — forwarding to agent.")

        # ── Agent invocation ──────────────────────────────────────────────────
        config = _agent_config(chat_id, vs)
        result = agent.invoke({"messages": [("user", text)]}, config)
        logger.info(f"[chat] Agent result keys: {list(result.keys()) if isinstance(result, dict) else type(result)}")

        if has_interrupt(result):
            action_name, args = parse_interrupt(result)
            logger.info(f"[chat] HITL interrupt: action={action_name}")
            if action_name:
                confirm_text, keyboard = await build_approval_ui(action_name, args, vs, context.user_data)
            else:
                from app.bot.hitl import _add_keyboard
                confirm_text, keyboard = "⚠️ Action requires approval.", _add_keyboard()
            await update.message.reply_text(
                confirm_text, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        else:
            await _reply_agent_result(update, context, vs, result)

    except Exception as e:
        logger.error(f"[chat] Exception: {e}", exc_info=True)
        try:
            err_str = str(e)
            if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str or "quota" in err_str.lower():
                await update.message.reply_text(
                    "⏳ The AI model is temporarily unavailable (rate limit / quota exceeded).\n"
                    "Please wait a minute and try again."
                )
            else:
                await update.message.reply_text("⚠️ Something went wrong. Please try again.")
        except Exception:
            pass


# ── State handlers ────────────────────────────────────────────────────────────

async def _handle_list_add(update: Update, context, vs, text: str, doc_id: str) -> None:
    """User typed a new item after tapping ➕ Add item in a list UI."""
    try:
        doc = await fetch_doc(vs, doc_id)
        if not doc:
            await update.message.reply_text("❌ List not found.")
            return

        meta      = doc.get("metadata", {})
        items     = list(meta.get("items", []))
        item_type = meta.get("item_type", "")

        # Inline shortcut: "Fix bug | high | small | 2026-05-10"
        parts    = [p.strip() for p in text.split("|")]
        new_item = make_item(
            parts[0],
            priority=parts[1] if len(parts) > 1 and item_type == "task_list" else None,
            effort  =parts[2] if len(parts) > 2 and item_type == "task_list" else None,
            due_date=parts[3] if len(parts) > 3 and item_type == "task_list" else None,
        )
        items.append(new_item)

        await save_items(vs, doc_id, meta, items)

        # Refresh from store after save
        doc = await fetch_doc(vs, doc_id) or doc

        # Edit the original list message in-place; fall back to new message
        msg_id  = context.user_data.pop("pending_list_add_message_id", None)
        chat_id = update.effective_chat.id
        if msg_id:
            edited = await edit_list_message(context.bot, chat_id, msg_id, doc, context, doc_id)
            if edited:
                # Delete the user's typed message to keep chat clean
                try:
                    await update.message.delete()
                except Exception:
                    pass
                return
        # Fallback: send new message
        await reply_list_message(update.message, doc, context, doc_id)

    except Exception as e:
        logger.error(f"[chat] list_add failed: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Could not add item: {e}")


async def _handle_delete_refinement(update: Update, context, vs, text: str) -> None:
    """User typed a new search query to refine the delete selection."""
    try:
        results = await vs.search(query=text, top_k=50)
        if results:
            context.user_data["pending_delete_docs"]     = results
            context.user_data["pending_delete_filters"]  = {}
            context.user_data["pending_delete_selected"] = set()
            context.user_data["pending_delete_page"]     = 0
            await update.message.reply_text(
                build_multi_delete_text(results, set(), 0),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(build_multi_delete_keyboard(results, set(), 0)),
            )
        else:
            await update.message.reply_text("🔍 No matching documents found. Try a different description.")
    except Exception as e:
        logger.error(f"[chat] Delete refinement search failed: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Search failed: {e}")


async def _handle_update_description(update: Update, context, vs, text: str) -> None:
    """User typed what changes to make after confirming a document for update."""
    pending_doc     = context.user_data.pop("pending_update_doc", None)
    pending_filters = context.user_data.pop("pending_update_filters", None)
    context.user_data.pop("pending_update_new_metadata", None)

    if not pending_filters:
        await update.message.reply_text("⚠️ Lost track of which document to update. Please start over.")
        return
    try:
        new_text, new_metadata = await apply_user_described_update(vs, pending_filters, pending_doc, text)
        summary = build_update_summary(new_text, new_metadata)
        await update.message.reply_text(
            f"✅ Document updated!\n\n<b>Changes applied:</b>\n{summary}",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"[chat] User-described update failed: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Update failed: {e}")


async def _reply_agent_result(update: Update, context, vs, result: dict) -> None:
    """
    Sends the final agent response.
    If the last tool call returned a structured list doc, renders the interactive UI.
    Otherwise sends a plain formatted text reply.
    """
    messages = result.get("messages", [])
    logger.info(f"[agent_result] {len(messages)} messages in result")

    # Find the LAST AIMessage that has tool_calls
    last_ai_idx = None
    for i, msg in enumerate(messages):
        if getattr(msg, "tool_calls", None):
            last_ai_idx = i

    if last_ai_idx is not None:
        # Collect all ToolMessages that follow it (before the next AIMessage)
        tool_results = []
        for msg in messages[last_ai_idx + 1:]:
            if getattr(msg, "tool_calls", None):
                break
            if hasattr(msg, "tool_call_id") or getattr(msg, "type", None) == "tool":
                tool_results.append(msg)

        logger.info(f"[agent_result] {len(tool_results)} tool result(s) after last AI tool call")

        for tool_msg in tool_results:
            doc = _try_extract_list_doc(tool_msg.content)
            if doc:
                doc_id    = doc.get("metadata", {}).get("id")
                logger.info(f"[agent_result] Rendering list UI for doc_id={doc_id}")
                fresh     = await fetch_doc(vs, doc_id)
                final_doc = fresh if fresh else doc
                await reply_list_message(update.message, final_doc, context, doc_id)
                return

    # Default: plain text reply
    reply_text = format_agent_response(result["messages"][-1].content)
    if not reply_text.strip():
        reply_text = "⚠️ Operation completed, but no details were returned."
    await update.message.reply_text(reply_text)


def _try_extract_list_doc(content) -> dict | None:
    """
    Parse a tool message's content and return the first structured list doc found,
    or None if content doesn't contain one.
    Handles: already-a-list, JSON string, Python repr string.
    """
    try:
        if isinstance(content, list):
            docs = content
        elif isinstance(content, str):
            raw = content.strip()
            if raw.startswith("[") or raw.startswith("{"):
                try:
                    docs = json.loads(raw)
                except json.JSONDecodeError:
                    docs = ast.literal_eval(raw)
            else:
                docs = ast.literal_eval(raw)
        else:
            return None

        if not isinstance(docs, list):
            docs = [docs]

        for candidate in docs:
            if isinstance(candidate, dict):
                item_type = candidate.get("metadata", {}).get("item_type", "")
                if is_list_type(item_type):
                    return candidate
    except Exception as e:
        logger.debug(f"[_try_extract_list_doc] parse failed: {e}")
    return None
