"""
lists.py
────────
Renders the interactive UI for structured list documents (shopping lists,
task lists, and any future STRUCTURED_ITEM_TYPES).

Public API:
  render_list_text(doc, page, show_done, category, edit_mode)     → HTML string
  render_list_keyboard(doc, page, show_done, category, edit_mode) → list[list[InlineKeyboardButton]]
  render_task_form_text(task_name, priority, effort, category)    → HTML string
  render_task_form_keyboard(doc_id, task_name, ...)               → list[list[InlineKeyboardButton]]
  LIST_ITEM_PAGE_SIZE                                              → int
"""

import logging
from telegram import InlineKeyboardButton

from app.bot.structure_types import STRUCTURED_TYPES, render_item_line, get_type_info

logger = logging.getLogger("bot")

LIST_ITEM_PAGE_SIZE = 8   # items per page


# ── Public API ────────────────────────────────────────────────────────────────

def render_list_text(doc: dict, page: int = 0, show_done: bool = False,
                     category: str | None = None, edit_mode: bool = False) -> str:
    """
    Builds the HTML message body for a list document.

    Args:
        doc:       Full document dict as returned by the vector store,
                   expected to have a "metadata" key containing at minimum
                   "item_type", "name", and "items".
        page:      Zero-based page index for paginating the item list.
                   Defaults to 0 (first page).
        show_done: When True, checked (done) items are included in the
                   rendered output. When False (default), they are hidden.
        category:  If set, only items whose "category" field matches this
                   value are shown. Pass None (default) to show all categories.
        edit_mode: When True, shows an instruction line indicating that the
                   keyboard buttons allow editing or deleting individual items.

    Returns:
        An HTML-formatted string ready to be sent as a Telegram message.
    """
    meta      = doc.get("metadata", {})
    item_type = meta.get("item_type", "")
    name      = meta.get("name", "List")
    items     = meta.get("items", [])

    type_cfg   = get_type_info(item_type)
    emoji      = type_cfg.get("emoji", "📋")
    total      = len(items)
    done_count = sum(1 for i in items if i.get("checked"))

    indexed    = _visible_items(items, show_done, category)
    pages      = _total_pages(indexed)
    page_items = _page_slice(indexed, page)

    lines = [
        _build_header(name, emoji, total, done_count, show_done, page, pages, category),
        "━━━━━━━━━━━━━━━━━━━",
    ]

    if edit_mode:
        lines.append("<i>✏️ Tap an item to edit its text · 🗑️ to delete it</i>")
        lines.append("")

    if page_items:
        lines += [render_item_line(item, item_type) for _, item in page_items]
    elif not show_done and done_count > 0:
        lines.append('<i>All items done! 🎉  Tap "Show ✅ done" to see them.</i>')
    else:
        lines.append("<i>No items yet. Use the button below to add one.</i>")

    return "\n".join(lines)


def render_list_keyboard(doc: dict, page: int = 0, show_done: bool = False,
                         category: str | None = None, edit_mode: bool = False) -> list:
    """Builds the full inline keyboard for a list document."""
    meta       = doc.get("metadata", {})
    item_type  = meta.get("item_type", "")
    doc_id     = meta.get("id", "")
    items      = meta.get("items", [])
    done_count = sum(1 for i in items if i.get("checked"))

    indexed    = _visible_items(items, show_done, category)
    pages      = _total_pages(indexed)
    page_items = _page_slice(indexed, page)

    # ── Edit mode: replace toggle buttons with ✏️/🗑️ per item ────────────────
    if edit_mode:
        buttons = _build_edit_item_buttons(page_items, doc_id)
        nav_row = _build_pagination_row(doc_id, page, pages)
        if nav_row:
            buttons.append(nav_row)
        buttons.append([InlineKeyboardButton(
            "✅ Done editing", callback_data=f"list_editmode_{doc_id}_0",
        )])
        return buttons

    # ── Normal mode ───────────────────────────────────────────────────────────
    buttons  = _build_toggle_buttons(page_items, doc_id)
    nav_row  = _build_pagination_row(doc_id, page, pages)
    if nav_row:
        buttons.append(nav_row)

    # Category filter row — only for types with a category field
    type_info = get_type_info(item_type)
    if "category" in type_info.get("item_fields", []):
        cat_row = _build_category_row(items, doc_id, category)
        if cat_row:
            buttons.append(cat_row)

    buttons += _build_action_rows(doc_id, done_count, show_done, item_type)

    return buttons


# ── Internal helpers ──────────────────────────────────────────────────────────

def _visible_items(items: list, show_done: bool, category: str | None = None) -> list[tuple[int, dict]]:
    """
    Returns [(absolute_index, item), …] for items that should be displayed.
    When show_done=False, checked items are excluded.
    When category is set (non-None, non-empty), only items matching that category are shown.
    """
    result = []
    for i, item in enumerate(items):
        if not show_done and item.get("checked"):
            continue
        if category and item.get("category", "") != category:
            continue
        result.append((i, item))
    return result


def _page_slice(indexed: list, page: int) -> list[tuple[int, dict]]:
    """Returns the subset of indexed_items for the given page."""
    start = page * LIST_ITEM_PAGE_SIZE
    return indexed[start: start + LIST_ITEM_PAGE_SIZE]


def _total_pages(indexed: list) -> int:
    return max(1, (len(indexed) + LIST_ITEM_PAGE_SIZE - 1) // LIST_ITEM_PAGE_SIZE)


def _build_header(name: str, emoji: str, total: int, done_count: int,
                  show_done: bool, page: int, pages: int,
                  category: str | None = None) -> str:
    hidden_note   = f", {done_count} hidden ✅" if (not show_done and done_count > 0) else ""
    page_note     = f" · page {page + 1}/{pages}" if pages > 1 else ""
    category_note = f" · 🏷 {category}" if category else ""
    return (
        f"{emoji} <b>{name}</b>  "
        f"<i>({total} items, {done_count} done{hidden_note}{page_note}{category_note})</i>"
    )


def _build_toggle_buttons(page_items: list[tuple[int, dict]], doc_id: str) -> list:
    """One button row per visible item (normal mode)."""
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


def _build_edit_item_buttons(page_items: list[tuple[int, dict]], doc_id: str) -> list:
    """In edit mode: one row per visible item with ✏️ edit and 🗑️ delete buttons."""
    rows = []
    for abs_i, item in page_items:
        text    = item.get("text", f"Item {abs_i + 1}")
        preview = text if len(text) <= 22 else text[:19] + "…"
        rows.append([
            InlineKeyboardButton(f"✏️  {preview}", callback_data=f"list_item_edit_{doc_id}_{abs_i}"),
            InlineKeyboardButton("🗑️",             callback_data=f"list_item_del_{doc_id}_{abs_i}"),
        ])
    return rows


def _build_pagination_row(doc_id: str, page: int, total_pages: int) -> list | None:
    """Returns a nav row [◀ Prev] [Next ▶] or None if not needed."""
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"list_page_{doc_id}_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"list_page_{doc_id}_{page + 1}"))
    return nav or None


def _build_action_rows(doc_id: str, done_count: int, show_done: bool, item_type: str = "") -> list:
    """➕ Add item, show/hide done toggle, edit items, rename, and optionally remove done."""
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
    edit_row = [InlineKeyboardButton("✏️ Edit items", callback_data=f"list_editmode_{doc_id}_1")]
    if item_type != "task_list":
        edit_row.append(InlineKeyboardButton("✏️ Rename list", callback_data=f"list_rename_{doc_id}"))
    rows.append(edit_row)
    return rows


def _build_category_row(items: list, doc_id: str, active_category: str | None) -> list | None:
    """
    Returns a row of category filter buttons for types that have a 'category' field.
    The active category button is marked with a ✦ prefix. An 'All' button clears the filter.
    Returns None if there are no categories on any item.

    callback_data uses index (|0, |1, …) instead of the full name to stay under
    Telegram's 64-byte callback_data limit. The callback handler resolves the index
    back to a name by re-deriving the same sorted category list from the doc.
    """
    categories = sorted({item.get("category", "") for item in items if item.get("category")})
    if not categories:
        return None

    buttons = []
    all_label = "✦ All" if not active_category else "All"
    buttons.append(InlineKeyboardButton(all_label, callback_data=f"list_catfilter_{doc_id}|"))
    for idx, cat in enumerate(categories):
        label = f"✦ {cat}" if cat == active_category else cat
        buttons.append(InlineKeyboardButton(label, callback_data=f"list_catfilter_{doc_id}|{idx}"))
    return buttons


# ── Task add form ─────────────────────────────────────────────────────────────

from app.bot.structure_types import PRIORITY_EMOJI, EFFORT_EMOJI

def render_task_form_text(task_name: str, priority: str | None,
                          effort: str | None, category: str | None) -> str:
    """Builds the HTML text for the new-task inline form."""
    lines = [f"✅ <b>New task:</b> <i>{task_name}</i>\n"]
    p = f"{PRIORITY_EMOJI.get(priority, '')} {priority.capitalize()}" if priority else "—"
    e = f"{EFFORT_EMOJI.get(effort, '')} {effort.capitalize()}" if effort else "—"
    c = category if category else "—"
    lines.append(f"Priority:  {p}")
    lines.append(f"Effort:    {e}")
    lines.append(f"Category:  {c}")
    return "\n".join(lines)


def render_task_form_keyboard(doc_id: str, task_name: str,
                               priority: str | None, effort: str | None,
                               category: str | None,
                               existing_categories: list[str]) -> list:
    """
    Builds the inline keyboard for the new-task form.
    Active selection is marked with ✦. Tapping again deselects (clears).

    Form state (task_name, priority, effort, category) is stored in user_data,
    NOT encoded in callback_data — Telegram enforces a 64-byte limit on callback_data.

    callback_data format:
      task_form_p_<doc_id>|<new_value>   (priority)
      task_form_e_<doc_id>|<new_value>   (effort)
      task_form_c_<doc_id>|<new_value>   (category)
      task_form_add_<doc_id>             (commit)
      task_form_cancel_<doc_id>          (cancel)
    """
    p = priority or ""
    e = effort or ""
    c = category or ""

    def _sel(label, is_active): return f"✦ {label}" if is_active else label
    def _p_cb(val): return f"task_form_p_{doc_id}|{'' if p == val else val}"
    def _e_cb(val): return f"task_form_e_{doc_id}|{'' if e == val else val}"
    def _c_cb(val): return f"task_form_c_{doc_id}|{'' if c == val else val}"

    priority_row = [
        InlineKeyboardButton(_sel("1️⃣ High",   p == "high"),   callback_data=_p_cb("high")),
        InlineKeyboardButton(_sel("2️⃣ Medium", p == "medium"), callback_data=_p_cb("medium")),
        InlineKeyboardButton(_sel("3️⃣ Low",    p == "low"),    callback_data=_p_cb("low")),
    ]
    effort_row = [
        InlineKeyboardButton(_sel("🟢 Small",  e == "small"),  callback_data=_e_cb("small")),
        InlineKeyboardButton(_sel("🟡 Medium", e == "medium"), callback_data=_e_cb("medium")),
        InlineKeyboardButton(_sel("🩷 Large",  e == "large"),  callback_data=_e_cb("large")),
    ]

    rows = [priority_row, effort_row]

    if existing_categories:
        # Use index in callback_data to stay under Telegram's 64-byte limit.
        # The callback handler resolves the index back to a name via user_data.
        cat_row = []
        for idx, cat in enumerate(existing_categories[:4]):
            is_active = (c == cat)
            # Empty string → deselect; index → select
            cb = f"task_form_c_{doc_id}|{'x' if is_active else idx}"
            cat_row.append(InlineKeyboardButton(_sel(cat, is_active), callback_data=cb))
        rows.append(cat_row)

    # Always show a button to type a new / custom category
    cat_action_label = f"🏷 Category: {c}" if c else "🏷 Set category…"
    rows.append([
        InlineKeyboardButton(cat_action_label, callback_data=f"task_form_newcat_{doc_id}"),
    ])

    rows.append([
        InlineKeyboardButton("✅ Add task", callback_data=f"task_form_add_{doc_id}"),
        InlineKeyboardButton("❌ Cancel",   callback_data=f"task_form_cancel_{doc_id}"),
    ])
    return rows

