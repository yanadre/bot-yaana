"""
formatting.py
─────────────
Helpers for formatting agent/tool responses into user-friendly Telegram text,
and for filtering internal metadata fields before display.
"""

# Metadata keys that are internal/system and should never be shown to the user.
HIDDEN_META_KEYS = frozenset({
    "_id", "_collection_name", "version",
    "creation_datetime", "update_datetime", "id",
})


def visible_meta(metadata: dict) -> dict:
    """Return metadata dict with internal system keys removed."""
    return {k: v for k, v in metadata.items() if k not in HIDDEN_META_KEYS}


def format_meta_lines(metadata: dict) -> str:
    """Return a bullet-list string of visible metadata fields."""
    meta = visible_meta(metadata)
    return "\n".join(f"  • {k}: {v}" for k, v in meta.items())


def format_agent_response(response) -> str:
    """
    Formats an agent/tool response for Telegram output.
    Handles: list-of-dicts (search results), plain string, None, empty.
    """
    if response is None:
        return "⚠️ No response from the agent. Please try again."

    if isinstance(response, str):
        text = response.strip()
        return text if text else "⚠️ Operation completed, but no details were returned."

    if isinstance(response, list):
        # Gemini sometimes returns content as a list of typed parts
        if response and isinstance(response[0], dict):
            # Search results: list of {"text": ..., ...}
            texts = [str(x.get("text", "")) for x in response if x.get("text")]
            if texts:
                return "\n".join(texts)
            # Gemini message parts: list of {"type": "text", "text": ...}
            parts = [x.get("text", "") for x in response if x.get("type") == "text"]
            if parts:
                return " ".join(parts).strip()
        return "ℹ️ No results found."

    # Fallback for any other type
    text = str(response).strip()
    return text if text else "⚠️ Operation completed, but no details were returned."
