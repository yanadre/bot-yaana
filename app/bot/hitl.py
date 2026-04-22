"""
hitl.py
───────
Parses LangGraph HITL interrupt objects and builds the Telegram approval UI
(message text + inline keyboard) for each tool action.

The entry point is `parse_interrupt(result)` which returns
  (action_name, args)   or   (None, None)  if no interrupt is present.

`build_approval_ui(action_name, args, vs, user_data)` returns
  (confirm_text: str, keyboard: list[list[InlineKeyboardButton]])
and populates `user_data` with any pending-update state.
"""

import logging
from telegram import InlineKeyboardButton
from app.bot.formatting import visible_meta, HIDDEN_META_KEYS

logger = logging.getLogger("bot")


# ── Interrupt parsing ─────────────────────────────────────────────────────────

def has_interrupt(result) -> bool:
    if hasattr(result, "__interrupt__") and getattr(result, "__interrupt__", None):
        return True
    if isinstance(result, dict) and result.get("__interrupt__"):
        return True
    return False


def parse_interrupt(result) -> tuple[str | None, dict | None]:
    """
    Extract (action_name, args) from a LangGraph HITL interrupt result.
    Returns (None, None) if no interrupt or no action requests found.
    """
    if not has_interrupt(result):
        return None, None

    if hasattr(result, "__interrupt__"):
        interrupt_obj = getattr(result, "__interrupt__")[0]
    else:
        interrupt_obj = result["__interrupt__"][0]

    if isinstance(interrupt_obj, dict):
        value = interrupt_obj.get("value", {})
    else:
        value = getattr(interrupt_obj, "value", None)
        if value is None and hasattr(interrupt_obj, "__dict__"):
            value = interrupt_obj.__dict__.get("value", {})

    action_requests = (value or {}).get("action_requests", [])
    if not action_requests:
        return None, None

    action = action_requests[0]
    return action.get("name"), action.get("args", {})


# ── Approval UI builders ──────────────────────────────────────────────────────

def _add_keyboard() -> list:
    return [
        [InlineKeyboardButton("✅ Approve", callback_data="approve"),
         InlineKeyboardButton("🔄 Retry",   callback_data="reject_and_retry")],
        [InlineKeyboardButton("📝 Edit",    callback_data="edit"),
         InlineKeyboardButton("❌ Abort",   callback_data="abort")],
    ]


def _update_keyboard() -> list:
    return [
        [InlineKeyboardButton("✅ Approve",           callback_data="confirm_update"),
         InlineKeyboardButton("🔍 Another Document",  callback_data="refine_update")],
        [InlineKeyboardButton("❌ Abort",              callback_data="abort_update")],
    ]


def _build_add_ui(args: dict) -> tuple[str, list]:
    doc_text = args.get("text", "")
    metadata = args.get("metadata", {})
    details = []
    if doc_text:
        details.append(f"<b>Content:</b> {doc_text}")
    if metadata:
        meta_lines = "\n".join(f"  • {k}: {v}" for k, v in metadata.items())
        details.append(f"<b>Metadata:</b>\n{meta_lines}")
    confirm_text = "📝 Are you sure you want to add this item to your vault?\n\n" + "\n".join(details)
    return confirm_text, _add_keyboard()


def _build_delete_ui(args: dict) -> tuple[str, list]:
    filters = args.get("filters", {})
    filter_lines = "\n".join(f"  • {k}: {v}" for k, v in filters.items())
    confirm_text = f"⚠️ Are you sure you want to delete item(s) matching:\n\n{filter_lines}"
    return confirm_text, _add_keyboard()


async def _build_update_ui(args: dict, vs, user_data: dict) -> tuple[str, list]:
    """
    Fetches the current document from Qdrant and builds a before/after diff preview.
    Stores pending update state into user_data.
    """
    filters = args.get("filters", {})
    proposed_new_metadata = dict(args.get("new_metadata", {}))

    doc_display = ""
    if vs and filters:
        try:
            doc_id = filters.get("id") or filters.get("_id")
            if doc_id:
                results = await vs.search(query="", filter_dict={"id": doc_id}, top_k=1)
            else:
                results = await vs.search(
                    query=" ".join(str(v) for v in filters.values()),
                    filter_dict=filters, top_k=1
                )

            if results:
                found_doc = results[0]

                # ── Current version ───────────────────────────────────────
                doc_text = found_doc.get("text", "")
                meta = visible_meta(found_doc.get("metadata", {}))
                meta_lines = "\n".join(f"  • {k}: {v}" for k, v in meta.items())
                current_block = f"<b>📄 Content:</b> {doc_text}\n<b>🏷 Metadata:</b>\n{meta_lines}"

                # ── Proposed new version ──────────────────────────────────
                # Agent puts new content under "text" key; we rename to "__text__"
                new_text_proposed = proposed_new_metadata.pop("text", None)
                new_meta_proposed = {
                    k: v for k, v in proposed_new_metadata.items()
                    if k not in HIDDEN_META_KEYS | {"__text__"}
                }

                new_block_lines = [
                    f"  📄 Content: {new_text_proposed if new_text_proposed else doc_text}"
                ]
                merged_meta = {**meta, **new_meta_proposed}
                for k, v in merged_meta.items():
                    old_v = meta.get(k)
                    if k in new_meta_proposed and str(old_v) != str(v):
                        new_block_lines.append(f"  🏷 {k}: <s>{old_v}</s> → <b>{v}</b>")
                    else:
                        new_block_lines.append(f"  🏷 {k}: {v}")

                new_block = "\n".join(new_block_lines)
                doc_display = f"<b>Before:</b>\n{current_block}\n\n<b>After:</b>\n{new_block}"

                # Restore content key for the update step
                if new_text_proposed:
                    proposed_new_metadata["__text__"] = new_text_proposed

                # Persist pending state for confirm_update callback
                user_data["pending_update_doc"]          = found_doc
                user_data["pending_update_filters"]      = filters
                user_data["pending_update_new_metadata"] = proposed_new_metadata
                logger.info(f"[hitl] Update preview built for doc={doc_text!r}, proposed={proposed_new_metadata}")
            else:
                doc_display = f"<b>Filters used:</b> {filters}\n(Document not found)"
        except Exception as e:
            logger.warning(f"[hitl] Could not fetch document for update preview: {e}")
            doc_display = f"<b>Filters:</b> {filters}"
    else:
        doc_display = f"<b>Filters:</b> {filters}"

    confirm_text = f"✏️ Approve this update?\n\n{doc_display}"
    return confirm_text, _update_keyboard()


async def build_approval_ui(
    action_name: str,
    args: dict,
    vs,
    user_data: dict,
) -> tuple[str, list]:
    """
    Returns (confirm_text, keyboard) for any HITL action.
    For update_vault_metadata, also populates user_data with pending state.
    """
    if action_name == "add_to_vault":
        return _build_add_ui(args)
    if action_name == "delete_from_vault":
        return _build_delete_ui(args)
    if action_name == "update_vault_metadata":
        return await _build_update_ui(args, vs, user_data)

    # Unknown action — generic fallback
    confirm_text = f"⚠️ Action requires approval:\n\n{args}"
    return confirm_text, _add_keyboard()
