"""
update_flow.py
──────────────
Logic for the update document flow:
  - apply_direct_update: used by confirm_update callback when the agent
    already proposed specific changes.
  - apply_user_described_update: used when the user types their changes
    after being asked (the "awaiting_update_changes" state).
  - build_update_summary: formats a human-readable summary of changes.

Both apply_* functions return the changes they made so the caller can
display a confirmation message.
"""

import json
import re
import logging
from app.config import settings
from app.bot.formatting import HIDDEN_META_KEYS

logger = logging.getLogger("bot")

# Keys never treated as update targets
_INTERNAL_KEYS = HIDDEN_META_KEYS | {"__text__"}


def build_update_summary(new_text: str | None, new_metadata: dict) -> str:
    """Returns a formatted bullet-list of changes made."""
    lines = []
    if new_text:
        lines.append(f"  • content: {new_text}")
    for k, v in new_metadata.items():
        lines.append(f"  • {k}: {v}")
    return "\n".join(lines) or "  (no changes detected)"


async def apply_direct_update(vs, pending_filters: dict, pending_new_metadata: dict) -> tuple[str | None, dict]:
    """
    Apply the agent's already-proposed update directly to the vector store.
    Returns (new_text, new_metadata) that were applied.
    """
    # Safety-net normalization: agent might have left "text" instead of "__text__"
    if "text" in pending_new_metadata and "__text__" not in pending_new_metadata:
        pending_new_metadata["__text__"] = pending_new_metadata.pop("text")

    new_text = pending_new_metadata.pop("__text__", None)
    new_metadata = {k: v for k, v in pending_new_metadata.items() if k not in _INTERNAL_KEYS}

    await vs.update_document(filter_dict=pending_filters, new_text=new_text, new_metadata=new_metadata)
    logger.info(f"[update_flow] Direct update applied. filters={pending_filters}, new_text={new_text!r}, new_metadata={new_metadata}")
    return new_text, new_metadata


async def apply_user_described_update(
    vs,
    pending_filters: dict,
    pending_doc: dict | None,
    user_change_text: str,
) -> tuple[str | None, dict]:
    """
    Parse the user's free-text change description with an LLM call,
    then apply the update. Returns (new_text, new_metadata) that were applied.

    NOTE: This path requires a second LLM call. In the typical flow the agent
    already knows what to change, so this is only hit when the agent provided
    no new_metadata. Consider improving the agent system prompt to always
    include specific change proposals so this branch is rarely reached.

    # TODO: FUTURE — replace this LLM parse call with an inline Telegram
    #   "force_reply" prompt so the user fills structured fields directly,
    #   eliminating the extra API round trip.
    """
    from langchain_google_genai import ChatGoogleGenerativeAI

    current_meta = pending_doc.get("metadata", {}) if pending_doc else {}
    current_text = pending_doc.get("text", "") if pending_doc else ""

    parse_prompt = (
        f"The user wants to update a document.\n"
        f"Current document text: {current_text}\n"
        f"Current metadata: {current_meta}\n"
        f"User's requested changes: \"{user_change_text}\"\n\n"
        f"Return ONLY a valid JSON object with the metadata fields that should be changed/added. "
        f"If the user wants to change the text/content itself, include a key \"__text__\" with the new text. "
        f"Example: {{\"status\": \"watched\", \"rating\": 9}}\n"
        f"Do not include fields that are not being changed. Do not include any explanation."
    )

    parse_llm = ChatGoogleGenerativeAI(model=settings.LLM_MODEL, temperature=0)
    parse_response = parse_llm.invoke(parse_prompt)
    raw = parse_response.content

    # Gemini may return content as a list of typed parts
    if isinstance(raw, list):
        raw = " ".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in raw
        )
    raw = raw.strip()

    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    new_fields = json.loads(json_match.group()) if json_match else {}
    logger.info(f"[update_flow] Parsed update fields from user text: {new_fields}")

    new_text = new_fields.pop("__text__", None)
    new_metadata = {k: v for k, v in new_fields.items() if k not in _INTERNAL_KEYS}

    await vs.update_document(filter_dict=pending_filters, new_text=new_text, new_metadata=new_metadata)
    logger.info(f"[update_flow] User-described update applied. filters={pending_filters}, new_text={new_text!r}, new_metadata={new_metadata}")
    return new_text, new_metadata
