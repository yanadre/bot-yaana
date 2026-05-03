"""
structure_types.py
──────────────────
Central registry for all structured (complex) document types.

When you add a new complex type (e.g. "recipe", "habit_tracker"):
  1. Add its item schema as a TypedDict below.
  2. Add an entry to STRUCTURED_TYPES.
  3. The rendering, keyboard, and HITL preview all pick it up automatically.

Public API:
  STRUCTURED_ITEM_TYPES        → set of item_type strings that use the items[] schema
  PRIORITY_EMOJI               → dict[str, str]
  EFFORT_EMOJI                 → dict[str, str]
  render_item_line(item, type) → str   (one formatted line per item)
  make_item(text, **kwargs)    → dict  (creates a new item with timestamps)
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
        "item_fields": ["priority", "effort", "due_date"],
    },
}

# Convenience set for quick membership checks
STRUCTURED_ITEM_TYPES: set[str] = set(STRUCTURED_TYPES.keys())


# ── Item factory ──────────────────────────────────────────────────────────────

def make_item(text: str, **kwargs: Any) -> dict:
    """
    Create a new item dict with required timestamps.
    Pass any optional fields as kwargs (priority, effort, due_date, …).

    Example:
        make_item("milk")
        make_item("Fix bug", priority="high", effort="small", due_date="2026-05-10")
    """
    now = datetime.now(timezone.utc).isoformat()
    item: dict[str, Any] = {
        "text":       text,
        "checked":    False,
        "added_at":   now,
        "checked_at": None,
    }
    # Only include known optional fields that were actually provided
    for field in ("priority", "effort", "due_date"):
        if field in kwargs and kwargs[field] is not None:
            item[field] = kwargs[field]
    return item


# ── Per-item line renderer ────────────────────────────────────────────────────

def render_item_line(item: dict, item_type: str) -> str:
    """
    Returns a single formatted line for one item, e.g.:

      Shopping list:   ✅ milk
      Task list:       ☐ 1️⃣ 🟢 Fix login bug  · due May 10  ⚠️
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

    # Task-specific badges
    if item_type == "task_list":
        priority = item.get("priority")
        effort   = item.get("effort")
        if priority:
            parts.append(PRIORITY_EMOJI.get(priority, ""))
        if effort:
            parts.append(EFFORT_EMOJI.get(effort, ""))

    parts.append(body)

    # Due date + overdue indicator
    due = item.get("due_date")
    if due and not checked:
        try:
            due_dt = datetime.fromisoformat(due)
            # Make it timezone-aware if it isn't
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            label = due_dt.strftime("%-d %b")          # e.g. "10 May"
            overdue = " ⚠️" if due_dt.date() < now.date() else ""
            parts.append(f"· due {label}{overdue}")
        except ValueError:
            parts.append(f"· due {due}")

    return "  ".join(p for p in parts if p)


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
