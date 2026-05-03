"""
hitl.py
───────
Parses LangGraph HITL interrupt objects and builds the Telegram approval UI
(message text + inline keyboard) for each tool action.

Public API:
  has_interrupt(result)                               → bool
  parse_interrupt(result)                             → (action_name, args) | (None, None)
  format_document_card(text, metadata)                → HTML string
  build_approval_ui(action_name, args, vs, user_data) → (confirm_text, keyboard)
  build_multi_delete_text(docs, selected, page)        → HTML string
  build_multi_delete_keyboard(docs, selected, page)    → list[list[InlineKeyboardButton]]
  PAGE_SIZE                                            → int
"""

import logging
from telegram import InlineKeyboardButton
from app.bot.formatting import visible_meta, HIDDEN_META_KEYS
from app.bot.structure_types import render_item_line, STRUCTURED_ITEM_TYPES, is_list_type, get_type_info

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


# ── Document card formatter ───────────────────────────────────────────────────

# Emoji per item_type — add more types here as needed
_TYPE_EMOJI: dict[str, str] = {
    "movie":         "🎬",
    "series":        "📺",
    "book":          "📚",
    "task":          "✅",
    "shopping_list": "🛒",
    "note":          "📝",
    "music":         "🎵",
    "game":          "🎮",
    "podcast":       "🎙️",
    "article":       "📰",
    "person":        "👤",
}

# Human-readable labels for known metadata keys
_META_LABEL: dict[str, str] = {
    "item_type":   "Type",
    "status":      "Status",
    "rating":      "Rating",
    "update_date": "Date",
    "genre":       "Genre",
    "author":      "Author",
    "director":    "Director",
    "year":        "Year",
    "language":    "Language",
    "priority":    "Priority",
    "tags":        "Tags",
}


def format_document_card(text: str, metadata: dict) -> str:
    """
    Returns a nicely formatted HTML card for a single vault document.

    Flat document:
        🎬 <b>The Godfather</b>
        ├ Status:  watched
        └ Rating:  10

    List document:
        🛒 <b>Groceries</b>
        ✅ milk
        ☐ eggs
        ☐ bread
    """
    meta      = visible_meta(metadata)
    item_type = meta.get("item_type", "")
    type_cfg  = get_type_info(item_type)
    emoji     = _TYPE_EMOJI.get(item_type, type_cfg.get("emoji", "📄"))

    # ── Structured (list) document ────────────────────────────────────────────
    if is_list_type(item_type):
        items = metadata.get("items", [])
        lines = [f"{emoji} <b>{text}</b>"]
        for item in items[:10]:   # cap preview at 10 items in HITL card
            lines.append(f"  {render_item_line(item, item_type)}")
        if len(items) > 10:
            lines.append(f"  <i>… and {len(items) - 10} more</i>")
        return "\n".join(lines)

    # ── Flat document ─────────────────────────────────────────────────────────
    lines = [f"{emoji} <b>{text}</b>"]
    meta_items = [(k, v) for k, v in meta.items() if k != "item_type"]
    for i, (k, v) in enumerate(meta_items):
        prefix = "└" if i == len(meta_items) - 1 else "├"
        label = _META_LABEL.get(k, k.replace("_", " ").capitalize())
        lines.append(f"{prefix} {label}:  {v}")

    return "\n".join(lines)


def _format_after_card(
    original_text: str,
    new_text: str | None,
    original_meta: dict,
    new_meta_proposed: dict,
) -> str:
    """
    Builds the 'After' card for the update preview.
    Changed fields are shown with strikethrough old → bold new.
    Items[] arrays are rendered as human-readable lines.
    """
    after_text = new_text if new_text else original_text
    after_meta = {**original_meta, **new_meta_proposed}
    item_type = after_meta.get("item_type", "")
    emoji = _TYPE_EMOJI.get(item_type, "📄")

    lines = []
    if new_text and new_text != original_text:
        lines.append(f"{emoji} <s>{original_text}</s> → <b>{new_text}</b>")
    else:
        lines.append(f"{emoji} <b>{after_text}</b>")

    after_items = [(k, v) for k, v in after_meta.items() if k != "item_type"]
    for i, (k, v) in enumerate(after_items):
        prefix = "└" if i == len(after_items) - 1 else "├"
        label = _META_LABEL.get(k, k.replace("_", " ").capitalize())
        old_v = original_meta.get(k)
        changed = k in new_meta_proposed and str(old_v) != str(v)

        # Render items[] as human-readable lines instead of raw dicts
        if k == "items" and isinstance(v, list):
            lines.append(f"{prefix} {label}{'  <i>(updated)</i>' if changed else ''}:")
            for item in v:
                lines.append(f"     {render_item_line(item, item_type)}")
        elif changed:
            lines.append(f"{prefix} {label}:  <s>{old_v}</s> → <b>{v}</b>")
        else:
            lines.append(f"{prefix} {label}:  {v}")

    return "\n".join(lines)


# ── Keyboards ─────────────────────────────────────────────────────────────────

def _add_keyboard() -> list:
    return [
        [InlineKeyboardButton("✅ Approve", callback_data="approve"),
         InlineKeyboardButton("🔄 Retry",   callback_data="reject_and_retry")],
        [InlineKeyboardButton("📝 Edit",    callback_data="edit"),
         InlineKeyboardButton("❌ Abort",   callback_data="abort")],
    ]


def _delete_keyboard() -> list:
    return [
        [InlineKeyboardButton("✅ Approve", callback_data="approve"),
         InlineKeyboardButton("❌ Abort",   callback_data="abort")],
    ]


# ── Multi-delete UI ───────────────────────────────────────────────────────────

PAGE_SIZE = 5  # documents per page


def build_multi_delete_text(docs: list[dict], selected: set[int], page: int) -> str:
    """
    Builds the message text for the multi-delete selection screen.
    Shows PAGE_SIZE docs at a time; selected items have a ✅ prefix.
    """
    total = len(docs)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    start = page * PAGE_SIZE
    page_docs = docs[start: start + PAGE_SIZE]

    lines = [f"🗑️ <b>Select items to delete</b>  ({total} found, page {page+1}/{total_pages})\n"]
    for rel_i, doc in enumerate(page_docs):
        abs_i = start + rel_i
        card = format_document_card(doc.get("text", ""), doc.get("metadata", {}))
        check = "✅" if abs_i in selected else "☐"
        # Indent card lines after the first
        card_lines = card.splitlines()
        indented = "\n   ".join(card_lines)
        lines.append(f"{check} [{abs_i + 1}]  {indented}")

    if selected:
        sel_nums = ", ".join(str(i + 1) for i in sorted(selected))
        lines.append(f"\n<i>Selected: {sel_nums}</i>")
    else:
        lines.append("\n<i>No items selected yet.</i>")

    return "\n".join(lines)


def build_multi_delete_keyboard(docs: list[dict], selected: set[int], page: int) -> list:
    """
    Returns an inline keyboard for the multi-delete UI:
    - One button per visible doc to toggle selection
    - Pagination row (Prev / Next)
    - Confirm-delete and Abort row
    """
    total = len(docs)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    start = page * PAGE_SIZE
    page_docs = docs[start: start + PAGE_SIZE]

    buttons = []

    # Toggle buttons (one per visible doc)
    for rel_i, doc in enumerate(page_docs):
        abs_i = start + rel_i
        text_preview = doc.get("text", f"Item {abs_i + 1}")
        if len(text_preview) > 28:
            text_preview = text_preview[:25] + "…"
        check = "✅" if abs_i in selected else "☐"
        buttons.append([InlineKeyboardButton(
            f"{check} {abs_i + 1}. {text_preview}",
            callback_data=f"del_toggle_{abs_i}",
        )])

    # Pagination row
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀ Prev", callback_data=f"del_page_{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Next ▶", callback_data=f"del_page_{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    # Action row
    confirm_label = f"🗑️ Delete ({len(selected)})" if selected else "🗑️ Delete (none)"
    buttons.append([
        InlineKeyboardButton(confirm_label,          callback_data="del_confirm"),
        InlineKeyboardButton("❌ Abort",              callback_data="del_abort"),
    ])
    buttons.append([
        InlineKeyboardButton("🔍 Search again", callback_data="del_refine"),
    ])

    return buttons


def _update_keyboard() -> list:
    return [
        [InlineKeyboardButton("✅ Approve",          callback_data="confirm_update"),
         InlineKeyboardButton("🔍 Another Document", callback_data="refine_update")],
        [InlineKeyboardButton("❌ Abort",             callback_data="abort_update")],
    ]


# ── Per-action UI builders ────────────────────────────────────────────────────

def _build_add_ui(args: dict) -> tuple[str, list]:
    doc_text = args.get("text", "")
    metadata = args.get("metadata", {})
    card = format_document_card(doc_text, metadata)
    confirm_text = f"📥 Add this item to your vault?\n\n{card}"
    return confirm_text, _add_keyboard()


async def _build_delete_ui(args: dict, vs, user_data: dict) -> tuple[str, list]:
    """
    Fetches ALL matching documents and returns a multi-select UI.
    Stores docs + filter state in user_data for the del_confirm callback.

    Handles a common agent mistake: using 'text' as a filter key.
    'text' is not a metadata field — if the agent passes it we fall back to
    a semantic search with that value as the query.
    """
    filters = args.get("filters", {})

    # ── Detect and fix the agent's "text as filter" mistake ──────────────────
    text_query = filters.pop("text", None)

    docs: list[dict] = []
    if vs:
        try:
            doc_id = filters.get("id") or filters.get("_id")
            if doc_id:
                # Precise id-based lookup
                docs = await vs.search(query="", filter_dict={"id": doc_id}, top_k=50)
            elif filters:
                # Normal metadata filter (scroll path — fast, no embedding)
                docs = await vs.search(query="", filter_dict=filters, top_k=50)
            elif text_query:
                # Agent incorrectly used 'text' as a filter — do semantic search
                logger.info(f"[hitl] Agent passed 'text' as filter key; falling back to semantic search: {text_query!r}")
                docs = await vs.search(query=text_query, top_k=50)
            logger.info(f"[hitl] Delete candidates: {len(docs)} docs for filters={filters!r}, text_query={text_query!r}")
        except Exception as e:
            logger.warning(f"[hitl] Could not fetch documents for delete preview: {e}")

    if not docs:
        # No results — fall back to a simple one-button prompt
        confirm_text = f"🗑️ No documents found matching:\n<i>{filters}</i>"
        keyboard = [[InlineKeyboardButton("❌ Abort", callback_data="del_abort")]]
        return confirm_text, keyboard

    # Persist state for callbacks
    user_data["pending_delete_docs"]    = docs
    user_data["pending_delete_filters"] = filters
    user_data["pending_delete_selected"] = set()   # nothing selected yet
    user_data["pending_delete_page"]    = 0

    text = build_multi_delete_text(docs, set(), 0)
    keyboard = build_multi_delete_keyboard(docs, set(), 0)
    return text, keyboard


async def _build_update_ui(args: dict, vs, user_data: dict) -> tuple[str, list]:
    """
    Fetches the current document from Qdrant and builds a before/after diff card.
    Stores pending update state into user_data for the confirm_update callback.
    """
    filters = args.get("filters", {})
    proposed_new_metadata = dict(args.get("new_metadata", {}))

    if vs and filters:
        try:
            doc_id = filters.get("id") or filters.get("_id")
            if doc_id:
                results = await vs.search(query="", filter_dict={"id": doc_id}, top_k=1)
            else:
                results = await vs.search(
                    query=" ".join(str(v) for v in filters.values()),
                    filter_dict=filters, top_k=1,
                )

            if results:
                found_doc = results[0]
                doc_text = found_doc.get("text", "")
                meta = visible_meta(found_doc.get("metadata", {}))

                # Agent puts new document text under "text" key — rename to "__text__"
                new_text_proposed = proposed_new_metadata.pop("text", None)
                new_meta_proposed = {
                    k: v for k, v in proposed_new_metadata.items()
                    if k not in HIDDEN_META_KEYS | {"__text__"}
                }

                current_card = format_document_card(doc_text, found_doc.get("metadata", {}))
                after_card   = _format_after_card(doc_text, new_text_proposed, meta, new_meta_proposed)
                doc_display  = f"<b>Before:</b>\n{current_card}\n\n<b>After:</b>\n{after_card}"

                # Restore content key for the apply step
                if new_text_proposed:
                    proposed_new_metadata["__text__"] = new_text_proposed

                # Persist pending state for confirm_update callback
                user_data["pending_update_doc"]          = found_doc
                user_data["pending_update_filters"]      = filters
                user_data["pending_update_new_metadata"] = proposed_new_metadata
                logger.info(f"[hitl] Update preview built: {doc_text!r} → proposed={proposed_new_metadata}")
            else:
                doc_display = f"<i>No document found matching: {filters}</i>"
        except Exception as e:
            logger.warning(f"[hitl] Could not fetch document for update preview: {e}")
            doc_display = f"<i>Filters: {filters}</i>"
    else:
        doc_display = f"<i>Filters: {filters}</i>"

    confirm_text = f"✏️ Approve this update?\n\n{doc_display}"
    return confirm_text, _update_keyboard()


# ── Entry point ───────────────────────────────────────────────────────────────

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
        return await _build_delete_ui(args, vs, user_data)
    if action_name == "update_vault_metadata":
        return await _build_update_ui(args, vs, user_data)

    # Unknown action — generic fallback
    return f"⚠️ Action requires approval:\n\n{args}", _add_keyboard()
