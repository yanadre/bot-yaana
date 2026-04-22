"""
handlers/chat.py
────────────────
Handles all incoming text messages from the user.

State machine (stored in context.user_data):
┌─────────────────────────────┬──────────────────────────────────────────────┐
│ Key                         │ Meaning                                      │
├─────────────────────────────┼──────────────────────────────────────────────┤
│ awaiting_update_changes     │ User confirmed the doc; waiting for them to  │
│                             │ type what should change (free-text input).   │
│ pending_update_doc          │ The current document dict (before/after).    │
│ pending_update_filters      │ Qdrant filter dict used to locate the doc.   │
│ pending_update_new_metadata │ Agent-proposed changes (may be pre-filled).  │
│ refining_update_search      │ User asked for "another document" — next     │
│                             │ message is passed straight to the agent.     │
└─────────────────────────────┴──────────────────────────────────────────────┘

# TODO: FUTURE — streaming responses
#   Replace agent.invoke() with agent.astream_events() so the user sees
#   a "typing…" placeholder that updates token-by-token as Gemini responds.
#   Controlled by settings.STREAM_RESPONSES (default False).
#   Skeleton:
#
#     placeholder = await update.message.reply_text("⏳ Thinking…")
#     buffer = ""
#     async for event in agent.astream_events(…, version="v2"):
#         if event["event"] == "on_chat_model_stream":
#             chunk = event["data"]["chunk"].content
#             if isinstance(chunk, str):
#                 buffer += chunk
#                 await placeholder.edit_text(buffer or "⏳ Thinking…")
#     # Final edit with complete text already done in the loop.

# TODO: FUTURE — search-with-button flow
#   Add a new user_data state: "awaiting_search_query".
#   When the user taps a "🔍 Search" button (sent by a /search command or
#   the agent), set this flag, then on the next message call vs.search()
#   directly and display results — no LLM call needed, much faster.
#   Entry point: callbacks.py "search_query" callback_data → set flag.
"""

import logging
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.config import settings
from app.bot.formatting import format_agent_response
from app.bot.hitl import parse_interrupt, has_interrupt, build_approval_ui, build_multi_delete_text, build_multi_delete_keyboard
from app.bot.update_flow import (
    apply_user_described_update,
    build_update_summary,
)

logger = logging.getLogger("bot")


def _agent_config(chat_id: int, vs) -> dict:
    return {
        "configurable": {
            "thread_id": str(chat_id),
            "vs": vs,
        }
    }


async def handle_agent_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = update.message.text
    logger.info(f"[chat] user_id={user_id}, chat_id={chat_id}: {text!r}")

    try:
        if user_id != settings.AUTHORIZED_ID:
            logger.warning(f"[chat] Unauthorized user_id={user_id}")
            return

        vs = context.bot_data["vs"]
        agent = context.bot_data["agent"]

        # ── State: refining delete search — run a direct VS search ───────────
        if context.user_data.pop("refining_delete_search", False):
            logger.info(f"[chat] Delete refinement query: {text!r}")
            try:
                results = await vs.search(query=text, top_k=50)
                if results:
                    context.user_data["pending_delete_docs"]     = results
                    context.user_data["pending_delete_filters"]  = {}
                    context.user_data["pending_delete_selected"] = set()
                    context.user_data["pending_delete_page"]     = 0
                    msg_text = build_multi_delete_text(results, set(), 0)
                    keyboard  = build_multi_delete_keyboard(results, set(), 0)
                    await update.message.reply_text(
                        msg_text,
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                    )
                else:
                    await update.message.reply_text("🔍 No matching documents found. Try a different description.")
            except Exception as e:
                logger.error(f"[chat] Delete refinement search failed: {e}", exc_info=True)
                await update.message.reply_text(f"❌ Search failed: {e}")
            return

        # ── State: awaiting free-text update description ──────────────────────
        if context.user_data.get("awaiting_update_changes"):
            context.user_data.pop("awaiting_update_changes")
            pending_doc     = context.user_data.pop("pending_update_doc", None)
            pending_filters = context.user_data.pop("pending_update_filters", None)
            context.user_data.pop("pending_update_new_metadata", None)

            if not pending_filters:
                await update.message.reply_text("⚠️ Lost track of which document to update. Please start over.")
                return

            try:
                new_text, new_metadata = await apply_user_described_update(
                    vs, pending_filters, pending_doc, text
                )
                summary = build_update_summary(new_text, new_metadata)
                await update.message.reply_text(
                    f"✅ Document updated!\n\n<b>Changes applied:</b>\n{summary}",
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"[chat] User-described update failed: {e}", exc_info=True)
                await update.message.reply_text(f"❌ Update failed: {e}")
            return

        # ── State: refining document search — fall through to agent ───────────
        if context.user_data.pop("refining_update_search", False):
            logger.info("[chat] Refinement message — forwarding to agent.")

        # ── Normal agent invocation ───────────────────────────────────────────
        config = _agent_config(chat_id, vs)
        result = agent.invoke({"messages": [("user", text)]}, config)
        logger.info(f"[chat] Agent result keys: {list(result.keys()) if isinstance(result, dict) else type(result)}")

        if has_interrupt(result):
            action_name, args = parse_interrupt(result)
            logger.info(f"[chat] HITL interrupt: action={action_name}")

            if action_name:
                confirm_text, keyboard = await build_approval_ui(
                    action_name, args, vs, context.user_data
                )
            else:
                confirm_text = "⚠️ Action requires approval."
                from app.bot.hitl import _add_keyboard
                keyboard = _add_keyboard()

            await update.message.reply_text(
                confirm_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML",
            )
        else:
            content = result["messages"][-1].content
            reply_text = format_agent_response(content)
            if not reply_text.strip():
                reply_text = "⚠️ Operation completed, but no details were returned."
            await update.message.reply_text(reply_text)

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
