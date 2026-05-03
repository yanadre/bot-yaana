"""
lists.py
────────
Renders the interactive UI for structured list documents (shopping lists,
task lists, and any future STRUCTURED_ITEM_TYPES).

Public API:
  render_list_text(doc, page, show_done)     → HTML string
  render_list_keyboard(doc, page, show_done) → list[list[InlineKeyboardButton]]
  LIST_ITEM_PAGE_SIZE                        → int
"""

import logging
from telegram import InlineKeyboardButton

from app.bot.structure_types import STRUCTURED_TYPES, render_item_line, get_type_info

logger = logging.getLogger("bot")

LIST_ITEM_PAGE_SIZE = 8   # items per page


# ── Internal helpers ──────────────────────────────────────────────────────────

def _visible_items(items: list, show_done: bool) -> list[tuple[int, dict]]:
    """
    Returns [(absolute_index, item), …] for items that should be displayed.
    When show_done=False, checked items are excluded.
    """
    if show_done:
        return list(enumerate(items))
    return [(i, item) for i, item in enumerate(items) if not item.get("checked")]


def _page_slice(indexed: list, page: int) -> list[tuple[int, dict]]:
    """Returns the subset of indexed_items for the given page."""
    start = page * LIST_ITEM_PAGE_SIZE
    return indexed[start: start + LIST_ITEM_PAGE_SIZE]


def _total_pages(indexed: list) -> int:
    return max(1, (len(indexed) + LIST_ITEM_PAGE_SIZE - 1) // LIST_ITEM_PAGE_SIZE)


def _build_header(name: str, emoji: str, total: int, done_count: int,
                  show_done: bool, page: int, pages: int) -> str:
    hidden_note = f", {done_count} hidden ✅" if (not show_done and done_count > 0) else ""
    page_note   = f" · page {page + 1}/{pages}" if pages > 1 else ""
    return (
        f"{emoji} <b>{name}</b>  "
        f"<i>({total} items, {done_count} done{hidden_note}{page_note})</i>"
    )


def _build_toggle_buttons(page_items: list[tuple[int, dict]], doc_id: str) -> list:
    """One button row per visible item."""
    rows = []
    for abs_i, item in page_items:
        checked = item.get("checked", False)
        text    = item.get("text", f"Item {abs_i + 1}")
        preview = text if len(text) <= 25 else text[:22] + "…"
        mark    = "✅" if checked else "☐"
        rows.append([InlineKeyboardButton(
            f"{mark}  {preview}",
            callback_data=f"list_toggle_{doc_id}_{abs_i}",
        )])
    return rows


def _build_pagination_row(doc_id: str, page: int, total_pages: int) -> list | None:
    """Returns a nav row [◀ Prev] [Next ▶] or None if not needed."""
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"list_page_{doc_id}_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"list_page_{doc_id}_{page + 1}"))
    return nav or None


def _build_action_rows(doc_id: str, done_count: int, show_done: bool) -> list:
    """➕ Add item + show/hide done toggle, and optionally a 🗑️ Remove done row."""
    toggle_btn = InlineKeyboardButton(
        "🙈 Hide done" if show_done else f"👁 Show done ({done_count})",
        callback_data=f"list_showdone_{doc_id}_{'0' if show_done else '1'}",
    )
    rows = [[
        InlineKeyboardButton("➕ Add item", callback_data=f"list_add_{doc_id}"),
        toggle_btn,
    ]]
    if done_count > 0:
        rows.append([InlineKeyboardButton(
            "🗑️ Remove done items", callback_data=f"list_clear_{doc_id}",
        )])
    return rows


# ── Public API ────────────────────────────────────────────────────────────────

def render_list_text(doc: dict, page: int = 0, show_done: bool = False) -> str:
    """Builds the HTML message body for a list document."""
    meta      = doc.get("metadata", {})
    item_type = meta.get("item_type", "")
    name      = meta.get("name", "List")
    items     = meta.get("items", [])

    type_cfg   = get_type_info(item_type)
    emoji      = type_cfg.get("emoji", "📋")
    total      = len(items)
    done_count = sum(1 for i in items if i.get("checked"))

    indexed    = _visible_items(items, show_done)
    pages      = _total_pages(indexed)
    page_items = _page_slice(indexed, page)

    lines = [
        _build_header(name, emoji, total, done_count, show_done, page, pages),
        "━━━━━━━━━━━━━━━━━━━",
    ]

    if page_items:
        lines += [render_item_line(item, item_type) for _, item in page_items]
    elif not show_done and done_count > 0:
        lines.append('<i>All items done! 🎉  Tap "Show ✅ done" to see them.</i>')
    else:
        lines.append("<i>No items yet. Use the button below to add one.</i>")

    return "\n".join(lines)


def render_list_keyboard(doc: dict, page: int = 0, show_done: bool = False) -> list:
    """Builds the full inline keyboard for a list document."""
    meta       = doc.get("metadata", {})
    doc_id     = meta.get("id", "")
    items      = meta.get("items", [])
    done_count = sum(1 for i in items if i.get("checked"))

    indexed    = _visible_items(items, show_done)
    pages      = _total_pages(indexed)
    page_items = _page_slice(indexed, page)

    buttons  = _build_toggle_buttons(page_items, doc_id)
    nav_row  = _build_pagination_row(doc_id, page, pages)
    if nav_row:
        buttons.append(nav_row)
    buttons += _build_action_rows(doc_id, done_count, show_done)

    return buttons
