"""
session.py
──────────
Per-user agent session management based on inactivity timeout.

A "session" maps directly to a LangGraph thread_id. When the user is inactive
for SESSION_TIMEOUT_MINUTES, the next text message starts a fresh thread —
clearing conversation context while vault data in Qdrant is untouched.

Public API:
  get_thread_id(chat_id, user_data)    → str   (current thread_id; no side-effects)
  log_prefix(chat_id, user_data)       → str   (log tag with session id, e.g. "[chat_id=1 session=2]")
  advance_session_if_needed(user_data) → bool  (True if a new session was started)
  touch_session(user_data)             → None  (record current time as last interaction)
"""

import logging
from datetime import datetime, timezone

from app.config import settings

logger = logging.getLogger("bot")

_KEY_LAST_TS   = "session_last_ts"   # float  — epoch seconds of last interaction
_KEY_SESSION   = "session_id"        # int    — monotonically incrementing per user


def get_thread_id(chat_id: int, user_data: dict) -> str:
    """
    Returns the LangGraph thread_id for the current session.
    Format: "<chat_id>:<session_id>"

    Pure read — no side-effects. Call advance_session_if_needed() first
    when handling new text messages.
    """
    session_id = user_data.get(_KEY_SESSION, 0)
    return f"{chat_id}:{session_id}"


def log_prefix(chat_id: int, user_data: dict) -> str:
    """
    Returns a log tag with the current session for consistent log correlation.
    Example: "[chat_id=123 session=2]"
    Use at the start of every log line in the message handler.
    """
    session_id = user_data.get(_KEY_SESSION, 0)
    return f"[chat_id={chat_id} session={session_id}]"


def _log_session_banner(session_id: int, reason: str) -> None:
    """Emits a secondary session-start banner, subordinate to ==== BOT SESSION START ====."""
    logger.info(f"\n---- USER SESSION #{session_id} ---- ({reason})")


def advance_session_if_needed(user_data: dict) -> bool:
    """
    Checks whether SESSION_TIMEOUT_MINUTES have elapsed since the last
    interaction. If so, increments the session counter (which causes
    get_thread_id() to return a new thread_id on the next call).

    Returns True if a new session was started, False otherwise.
    Call this once at the top of handle_agent_chat, before building the config.
    """
    last_ts = user_data.get(_KEY_LAST_TS)
    if last_ts is None:
        # First ever message — no timeout to check
        return False

    elapsed_minutes = (datetime.now(timezone.utc).timestamp() - last_ts) / 60
    timeout = settings.SESSION_TIMEOUT_MINUTES

    if elapsed_minutes >= timeout:
        new_id = user_data.get(_KEY_SESSION, 0) + 1
        user_data[_KEY_SESSION] = new_id
        logger.info(
            f"[session] Inactivity timeout ({elapsed_minutes:.1f} min ≥ {timeout} min) "
            f"→ new session #{new_id}"
        )
        _log_session_banner(new_id, reason="inactivity timeout")
        return True

    return False


def touch_session(user_data: dict) -> None:
    """
    Record the current UTC timestamp as the last interaction time.
    Call this after every successful agent invocation (and optionally
    after button interactions) to keep the timer fresh.
    """
    user_data[_KEY_LAST_TS] = datetime.now(timezone.utc).timestamp()
