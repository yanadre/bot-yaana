"""
structure_types.py
──────────────────
Central registry for all structured (complex) document types.
This is the single source of truth for per-item fields — adding a field here
automatically propagates to make_item(), render_item_line(), and the system prompt.

When you add a new complex type (e.g. "recipe", "habit_tracker"):
  1. Add an entry to STRUCTURED_TYPES with its label, emoji, and item_fields.
  2. The rendering, keyboard, HITL preview, and system prompt all pick it up automatically.

When you add a new field to an existing type (e.g. "recurring" to task_list):
  1. Add the field name to item_fields in STRUCTURED_TYPES.
  2. If it needs a badge in the rendered line, handle it in render_item_line().
  3. No other files need to change.

Public API:
  STRUCTURED_ITEM_TYPES        → set of item_type strings that use the items[] schema
  PRIORITY_EMOJI               → dict[str, str]
  EFFORT_EMOJI                 → dict[str, str]
  is_list_type(item_type)      → bool
  get_type_info(item_type)     → dict
  render_item_line(item, type) → str   (one formatted line per item)
  make_item(text, item_type, **kwargs) → dict  (creates a new item with timestamps)
  regenerate_text(name, items) → str   (summary text for embedding)
"""

from datetime import datetime, timezone
from typing import Any

# ── Emoji maps ────────────────────────────────────────────────────────────────

PRIORITY_EMOJI: dict[str, str] = {
    "high":   "1️⃣",
    "medium": "2️⃣",
    "low":    "3️⃣",
}

EFFORT_EMOJI: dict[str, str] = {
    "small":  "🟢",
    "medium": "🟡",
    "large":  "🩷",
}

# ── Structured type registry ──────────────────────────────────────────────────
# Each entry describes one item_type that uses the items[] sub-document schema.
#
# Fields:
#   label        human-readable name shown in the UI header
#   emoji        icon shown next to the list name
#   item_fields  ordered list of optional per-item metadata fields
#                (determines what the agent is told to include)

STRUCTURED_TYPES: dict[str, dict] = {
    "shopping_list": {
        "label":       "Shopping List",
        "emoji":       "🛒",
        "item_fields": [],                                # just text + checked
    },
    "task_list": {
        "label":       "Task List",
        "emoji":       "✅",
        "item_fields": ["category", "priority", "effort", "due_date"],
    },
    "movie_list": {
        "label":       "Movie List",
        "emoji":       "🎬",
        "item_fields": ["status"],                        # e.g. to_watch / watched
    },
    "book_list": {
        "label":       "Book List",
        "emoji":       "📚",
        "item_fields": ["status"],                        # e.g. to_read / read
    },
    "series_list": {
        "label":       "Series List",
        "emoji":       "📺",
        "item_fields": ["status"],
    },
}

# Convenience set for quick membership checks
STRUCTURED_ITEM_TYPES: set[str] = set(STRUCTURED_TYPES.keys())


def is_list_type(item_type: str) -> bool:
    """
    Returns True for any known structured list type OR any item_type
    ending in '_list' (allows agent to create ad-hoc lists like 'recipe_list').
    """
    return item_type in STRUCTURED_ITEM_TYPES or item_type.endswith("_list")


def get_type_info(item_type: str) -> dict:
    """
    Returns the STRUCTURED_TYPES entry for a known type, or a sensible
    default for unknown *_list types created by the agent.
    """
    if item_type in STRUCTURED_TYPES:
        return STRUCTURED_TYPES[item_type]
    if item_type.endswith("_list"):
        label = item_type.replace("_", " ").title()
        return {"label": label, "emoji": "📋", "item_fields": []}
    return {"label": item_type, "emoji": "📋", "item_fields": []}


# ── Item factory ──────────────────────────────────────────────────────────────

def make_item(text: str, item_type: str = "", **kwargs: Any) -> dict:
    """
    Create a new item dict with required timestamps.
    Optional fields are derived from the STRUCTURED_TYPES registry for the
    given item_type, so adding a field to the registry is the only change needed.

    Pass optional field values as kwargs — only fields declared in the registry
    (or any kwarg for unknown types) are included if their value is not None.

    Example:
        make_item("milk")
        make_item("Fix bug", item_type="task_list", priority="high", effort="small", due_date="2026-05-10")
        make_item("Fix bug", item_type="task_list", category="work", priority="high")
    """
    now = datetime.now(timezone.utc).isoformat()
    item: dict[str, Any] = {
        "text":       text,
        "checked":    False,
        "added_at":   now,
        "checked_at": None,
    }
    # Determine which optional fields to accept from the registry
    known_fields = get_type_info(item_type).get("item_fields", []) if item_type else list(kwargs.keys())
    for field in known_fields:
        if field in kwargs and kwargs[field] is not None:
            item[field] = kwargs[field]
    return item


# ── Per-item line renderer ────────────────────────────────────────────────────

def render_item_line(item: dict, item_type: str) -> str:
    """
    Returns a single formatted line for one item, e.g.:

      Shopping list:   ✅ milk
      Task list:       ☐ 1️⃣ 🟢 Fix login bug  [work]  · due May 10  ⚠️

    Which badges appear is driven by the item_fields declared in STRUCTURED_TYPES,
    so no code change is needed when fields are added to the registry.
    """
    checked = item.get("checked", False)
    text    = item.get("text", "")

    if checked:
        check = "✅"
        body  = f"<s>{text}</s>"
    else:
        check = "☐"
        body  = text

    parts = [check]

    item_fields = get_type_info(item_type).get("item_fields", [])

    if "priority" in item_fields:
        priority = item.get("priority")
        if priority:
            parts.append(PRIORITY_EMOJI.get(priority, ""))

    if "effort" in item_fields:
        effort = item.get("effort")
        if effort:
            parts.append(EFFORT_EMOJI.get(effort, ""))

    parts.append(body)

    if "category" in item_fields:
        category = item.get("category")
        if category:
            parts.append(f"[{category}]")

    # Due date + overdue indicator (applies to any type that declares due_date)
    if "due_date" in item_fields:
        due = item.get("due_date")
        if due and not checked:
            try:
                due_dt = datetime.fromisoformat(due)
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                label = due_dt.strftime("%-d %b")      # e.g. "10 May"
                overdue = " ⚠️" if due_dt.date() < now.date() else ""
                parts.append(f"· due {label}{overdue}")
            except ValueError:
                parts.append(f"· due {due}")

    return "  ".join(p for p in parts if p)


# ── System prompt builder ─────────────────────────────────────────────────────

def build_tool_list_hints() -> str:
    """
    Returns a human-readable string describing each structured list type and
    its per-item fields, for use in agent tool descriptions.
    Generated from STRUCTURED_TYPES — stays in sync automatically.

    Example output:
      - task_list    (Task List ✅): item fields: text, checked, category, priority, effort, due_date
      - shopping_list (Shopping List 🛒): item fields: text, checked
    """
    lines = []
    for type_key, info in STRUCTURED_TYPES.items():
        fields = ["text", "checked"] + info.get("item_fields", [])
        lines.append(
            f"  - {type_key:<16} ({info['label']} {info['emoji']}): "
            f"item fields: {', '.join(fields)}"
        )
    return "\n".join(lines)


def build_system_prompt(task_list_id: str) -> str:
    """
    Generate the full agent system prompt, with the vault structure section
    derived from STRUCTURED_TYPES. This is the single source of truth —
    adding a type or field to STRUCTURED_TYPES automatically updates the prompt.
    """
    from app.config import settings  # local import to avoid circular dependency

    # Build vault structure lines from the registry
    lines = ["  Any item_type ending in '_list' is an interactive list with an items[] array."]
    for type_key, info in STRUCTURED_TYPES.items():
        fields = ["text", "checked"] + info.get("item_fields", [])
        lines.append(f"  {type_key:<16} → {info['label']} (fields: {', '.join(fields)})")
    lines.append("  <anything>_list  → generic list")
    vault_structure = "\n".join(lines)

    # Task list item field schema for the prompt
    task_fields = STRUCTURED_TYPES["task_list"]["item_fields"]
    task_item_schema = ", ".join(
        f'"{f}": "..."' if f not in ("priority", "effort", "due_date") else
        '"{f}": "{vals}"'.format(
            f=f,
            vals="high|medium|low" if f == "priority" else
                 "small|medium|large" if f == "effort" else
                 "YYYY-MM-DD"
        )
        for f in task_fields
    )

    return settings.SYSTEM_PROMPT_TEMPLATE.format(
        vault_structure=vault_structure,
        task_list_id=task_list_id,
        task_item_schema=task_item_schema,
    )


# ── Embedding text regenerator ────────────────────────────────────────────────

def regenerate_text(name: str, items: list[dict]) -> str:
    """
    Builds the plain-text summary stored in Qdrant's page_content field.
    This is what gets embedded — keep it information-dense.

    Example: "Groceries: milk, eggs, bread (checked: milk, eggs)"
    """
    all_texts     = [i.get("text", "") for i in items]
    checked_texts = [i.get("text", "") for i in items if i.get("checked")]

    summary = f"{name}: {', '.join(all_texts)}"
    if checked_texts:
        summary += f" (done: {', '.join(checked_texts)})"
    return summary
