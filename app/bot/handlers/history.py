"""
handlers/history.py
───────────────────
/history command — shows the conversation history of the current agent session.

Reads directly from the LangGraph MemorySaver checkpointer for the current
thread_id, so it reflects exactly what the agent "remembers" right now.

Message types rendered:
  👤  HumanMessage  — what the user said
  🤖  AIMessage     — what the agent replied (text only; tool-call-only messages skipped)
  🔧  ToolMessage   — tool calls are summarised (name + truncated result), not shown in full

Output is split into Telegram-safe chunks (≤ 4096 chars each).
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from app.config import settings
from app.bot.session import get_thread_id, log_prefix

logger = logging.getLogger("bot")

_MAX_MSG_LEN   = 4096   # Telegram hard limit
_PREVIEW_LEN   = 120    # max chars shown per tool result


def _format_history(messages: list, session_id: int) -> str:
    """
    Converts a LangGraph messages list into a readable HTML string.
    Returns an empty string if there are no displayable messages.
    """
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

    lines = [f"<b>📜 Session #{session_id} — conversation history</b>\n"]
    turn  = 0

    for msg in messages:
        if isinstance(msg, HumanMessage):
            turn += 1
            text = str(msg.content).strip()
            lines.append(f"<b>👤 [{turn}] You:</b>  {_esc(text)}")

        elif isinstance(msg, AIMessage):
            text = str(msg.content).strip() if msg.content else ""
            if text:
                lines.append(f"<b>🤖 Bot:</b>  {_esc(text)}")
            elif getattr(msg, "tool_calls", None):
                # Tool-call-only message — note which tools were called
                names = ", ".join(tc.get("name", "?") for tc in msg.tool_calls)
                lines.append(f"<b>🔧 Bot called:</b>  <i>{_esc(names)}</i>")

        elif isinstance(msg, ToolMessage):
            result = str(msg.content).strip()
            preview = result[:_PREVIEW_LEN] + "…" if len(result) > _PREVIEW_LEN else result
            lines.append(f"  <i>↳ result: {_esc(preview)}</i>")

    if len(lines) == 1:
        # Only the header — nothing to show
        return ""

    return "\n".join(lines)


def _esc(text: str) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _chunk(text: str) -> list[str]:
    """Split a long string into Telegram-safe chunks, breaking on newlines."""
    if len(text) <= _MAX_MSG_LEN:
        return [text]

    chunks = []
    while text:
        if len(text) <= _MAX_MSG_LEN:
            chunks.append(text)
            break
        # Find the last newline within the limit
        split_at = text.rfind("\n", 0, _MAX_MSG_LEN)
        if split_at == -1:
            split_at = _MAX_MSG_LEN
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /history — sends the current session's conversation history to the user.
    """
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    prefix  = log_prefix(chat_id, context.user_data)

    if user_id != settings.AUTHORIZED_ID:
        return

    vs    = context.bot_data.get("vs")
    agent = context.bot_data.get("agent")
    if not agent:
        await update.message.reply_text("⚠️ Agent not available.")
        return

    thread_id  = get_thread_id(chat_id, context.user_data)
    session_id = context.user_data.get("session_id", 0)
    config     = {"configurable": {"thread_id": thread_id, "vs": vs}}

    try:
        state    = agent.get_state(config)
        messages = state.values.get("messages", []) if state and state.values else []
    except Exception as e:
        logger.warning(f"{prefix} /history — could not fetch state: {e}")
        await update.message.reply_text("⚠️ Could not retrieve session history.")
        return

    logger.info(f"{prefix} /history — {len(messages)} messages in thread {thread_id!r}")

    formatted = _format_history(messages, session_id)
    if not formatted:
        await update.message.reply_text(
            "🕳 <i>No conversation history in this session yet.</i>",
            parse_mode="HTML",
        )
        return

    for chunk in _chunk(formatted):
        await update.message.reply_text(chunk, parse_mode="HTML")
