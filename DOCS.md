# bot-yaana — Project Documentation

> Personal Telegram bot with an AI agent (LangGraph), a vector store (Qdrant), and a personal knowledge vault with interactive list management.

---

## Project Overview

**bot-yaana** is a private personal assistant that lives in Telegram and grows smarter the more you use it.

---

### Vision

The long-term goal is a single assistant that **knows your life and actively helps you live it** — not just a place to store things, but something that:

- Stores whatever you give it, in whatever form you give it — "I watched Dune, loved it" gets saved as a movie record; "just finished reading Dune by Frank Herbert" updates that same record rather than creating a new one. You can paste in a full article you wrote, or start a trip record before you leave and keep adding to it — notes, costs, impressions — during and after. No manual schema or categories; the agent figures out what fields are worth keeping
- Answers questions and helps make decisions using what it knows about you ("what should I watch tonight?" → draws on your taste, ratings, and what's already on your list)
- Manages structured things (shopping, tasks, watchlists) with a real interactive UI
- Sends smart reminders and surfaces things proactively, not just when asked
- Eventually: finds and indexes files on your phone so everything is reachable through conversation

The key design principle is that **capture should be effortless and retrieval should be intelligent** — the bot does the work of structuring, filtering, and reasoning, not you. At the same time, common actions (opening a list, adding an item, checking something off) bypass the AI entirely for instant response — the agent is invoked only when it adds real value.

---

### Where it is today

The foundation is built and working:

| Capability | Status |
|---|---|
| Save / update / delete anything in plain language | ✅ Working |
| Auto-extract and store structured fields from free-text | ✅ Working (quality depends on system prompt) |
| Search the vault by meaning | ✅ Working |
| Interactive list UI (shopping, tasks, watchlists, …) | ✅ Working |
| Fast-path list commands (`/list`, `/tasks`, `/newlist`, `/newtasks`) | ✅ Working |
| Confirm before any write (preview + approve/reject) | ✅ Working |
| Answer questions using stored data as context | ⚠️ Basic — reacts when asked, doesn't reason proactively |
| Automatically narrow searches based on question intent | ⚠️ Partial — not reliable |
| Find the right amount of data for the question | ⚠️ Partial — not reliable |
| Reminders / proactive push messages | ❌ Not implemented |
| Scheduling and calendar awareness | ❌ Not implemented |
| Ingest files from phone (photos, voice, docs) | ❌ Not implemented |

---

### Roadmap to the vision

**Phase 1 — Make the intelligence layer reliable** *(current focus)*

The infrastructure is sound but the agent's reasoning is shallow. The priority is closing the gap between what the system *can* do and what it *reliably does*:

1. **Smarter search** — the agent should automatically narrow results based on what the question implies, combine different search strategies, and retrieve the right amount of data for the question at hand. See `BACKLOG.txt` F0.
2. **Smarter capture** — the agent should infer and store standard fields for known domains (e.g. status, year, genre, rating for media) even when not explicitly mentioned, so the vault is more useful later.
3. **Fix known bugs** — list type toggle labels (B3), agent not creating lists from existing docs (B2). See `BACKLOG.txt`.

**Phase 2 — From reactive to proactive**

Once retrieval is reliable, the agent can start doing things without being asked:

4. **Due-date reminders** — daily scan of task items; push a Telegram message when something is due or overdue.
5. **Proactive surfacing** — periodic nudges based on vault state ("you have 5 unwatched Villeneuve films", "your reading list hasn't changed in 3 weeks").
6. **Smarter answers to open questions** — when asked "what should I watch?", the agent doesn't just list unwatched items; it reasons about ratings, genres, mood, and recency.

**Phase 3 — Richer input and scheduling**

7. **File ingestion** — accept photos, voice memos, and documents via Telegram. Extract text (OCR / Whisper), generate metadata, store in vault.
8. **Scheduling awareness** — understand dates, recurring events, and deadlines as first-class concepts.
9. **Calendar integration** — read/write events in an external calendar based on conversation.

---

### What it is not

- Not a multi-user service — access is locked to a single `AUTHORIZED_ID`.
- Not a general-purpose chatbot — every response is grounded in your personal vault.

---

### Tech stack

| Layer | Technology |
|---|---|
| Bot framework | `python-telegram-bot` (v20+, async) |
| AI agent | `langgraph` with Gemini / OpenAI LLM |
| Vector store | `qdrant-client` + `langchain-qdrant` |
| Embeddings | `langchain-google-genai` / `langchain-openai` |
| Runtime | Docker Compose (dev + prod configs) |

For the full bug and feature list see **`BACKLOG.txt`** at the project root.


---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture Overview](#architecture-overview)
3. [Project Structure](#project-structure)
4. [Data Schema](#data-schema)
5. [Commands Reference](#commands-reference)
6. [Flows](#flows)
   - [Agent Chat Flow (HITL)](#agent-chat-flow-hitl)
   - [Fast-Path List/Task Flow](#fast-path-listtask-flow)
   - [Callback (Inline Keyboard) Flow](#callback-inline-keyboard-flow)
7. [Structured Types Registry](#structured-types-registry)
8. [Dev / Prod Separation](#dev--prod-separation)
9. [Hot-Reload Development](#hot-reload-development)
10. [Deployment](#deployment)
11. [Extending the Bot](#extending-the-bot)

---

## Architecture Overview

```
Telegram ──► PTB Application ──► Handlers
                                    │
                    ┌───────────────┼──────────────────┐
                    ▼               ▼                  ▼
              CommandHandlers  CallbackQuery     MessageHandler
              (/list, /newlist…)  (inline btns)   (agent chat)
                    │               │                  │
                    └───────────────┴──────────────────┘
                                    │
                              Vector Store (Qdrant)
                              AI Agent (LangGraph)
```

**Key libraries:**

| Library | Role |
|---|---|
| `python-telegram-bot` | Telegram API client & dispatcher |
| `langgraph` | Agent graph with human-in-the-loop (HITL) interrupts |
| `qdrant-client` + `langchain-qdrant` | Semantic vector store |
| `langchain-google-genai` / `langchain-openai` | Embeddings + LLM calls |

---

## Project Structure

```
app/
├── main_telegram_v2.py     Entry point — wires all handlers, starts polling
├── config.py               Pydantic settings (reads .env / .env.dev)
├── chat_bot_agent.py       LangGraph agent definition
│
├── agent/
│   ├── tools.py            Agent tools: add/update/delete/search vault
│   └── schemas.py          Pydantic schemas for tool inputs
│
├── bot/
│   ├── setup.py            on_startup / on_shutdown lifecycle hooks
│   ├── formatting.py       Markdown/HTML formatting helpers
│   ├── hitl.py             HITL interrupt rendering (previews, keyboards)
│   ├── lists.py            List/task UI rendering (text + inline keyboard)
│   ├── structure_types.py  Structured-type registry, emoji maps, item factory
│   ├── update_flow.py      Direct-update helpers (apply_direct_update)
│   │
│   └── handlers/
│       ├── callbacks.py    All inline keyboard callbacks
│       ├── chat.py         Agent chat entry point (handles HITL states)
│       ├── commands.py     /start, /migrate
│       └── list_commands.py /list, /tasks, /newlist, /newtasks
│
├── database/
│   └── vector_store.py     QdrantVectorStore wrapper (add/search/update/delete/patch)
│
└── models/
    └── embedding_model.py  Embedding model factory
```

---

## Data Schema

### Flat documents

The most common form — a document with a set of metadata fields the agent inferred from what you said. Fields vary by type and context; there is no fixed schema.

```json
{
  "id":                "uuid",
  "item_type":         "book",
  "title":             "Dune",
  "author":            "Frank Herbert",
  "status":            "reading",
  "version":           "new",
  "creation_datetime": "2025-01-01T00:00:00+00:00",
  "update_datetime":   "2025-01-01T00:00:00+00:00"
}
```

### Structured (list/task) documents

Documents with an `item_type` ending in `_list` (e.g. `shopping_list`, `task_list`, `movie_list`, `book_list`) carry an `items` array. The bot recognises any `*_list` type — you don't need to register new list types explicitly.

```json
{
  "id":                "uuid",
  "name":              "Groceries",
  "item_type":         "shopping_list",
  "items": [
    {
      "text":       "milk",
      "checked":    false,
      "added_at":   "2025-01-01T00:00:00+00:00",
      "checked_at": null
    }
  ],
  "version":           "new",
  "creation_datetime": "2025-01-01T00:00:00+00:00",
  "update_datetime":   "2025-01-01T00:00:00+00:00"
}
```

Task list items also support optional fields:

```json
{
  "text":       "Fix login bug",
  "checked":    false,
  "priority":   "high",
  "effort":     "small",
  "due_date":   "2026-05-10",
  "added_at":   "...",
  "checked_at": null
}
```

**Priority values:** `high` · `medium` · `low`  
**Effort values:** `small` · `medium` · `large`

---

## Commands Reference

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/migrate` | Migrate legacy documents to versioned schema |
| `/list [name]` | Open a shopping list (picker if multiple, direct if name given) |
| `/tasks [name]` | Open a task list |
| `/newlist <name>` | Instantly create a new empty shopping list |
| `/newtasks <name>` | Instantly create a new empty task list |

**Free-text messages** are routed to the AI agent for natural language add/search/update/delete.

---

## Flows

### Agent Chat Flow (HITL)

```
User sends message
      │
      ▼
handle_agent_chat()
      │
      ├─ state: pending_list_add_doc_id  ──► append item to list, re-render UI
      ├─ state: awaiting_update_changes  ──► parse new field values, apply update
      ├─ state: refining_delete_search   ──► re-run delete search
      ├─ state: refining_update_search   ──► re-run update search
      │
      └─ default: invoke agent (LangGraph)
                │
                ├─ agent runs, hits interrupt (HITL)
                │         │
                │         ├─ __interrupt__: add/delete/update preview
                │         │   → show preview message + inline keyboard
                │         │     [Approve] [Reject & Retry] [Edit] [Abort]
                │         │
                │         └─ agent decides tool, agent done
                │
                └─ final message to user
```

**HITL interrupt types:**

| Interrupt | UI shown | Possible responses |
|---|---|---|
| `add_to_vault` | Document preview | Approve / Reject & Retry / Edit / Abort |
| `delete_from_vault` | Multi-select list | Toggle items, Confirm, Abort, Refine search |
| `update_document` | Diff preview | Confirm Update / Abort / Refine search |

### Fast-Path List/Task Flow

```
/list [name]  or  /tasks [name]
      │
      ▼
_open_list()
      │
      ├─ no docs found        → friendly empty-state message
      ├─ name arg + match     → open single list directly
      ├─ one list total       → open it directly
      └─ multiple lists       → picker (inline keyboard with names + progress)

/newlist <name>  or  /newtasks <name>
      │
      ▼
_create_list()
      │
      ├─ duplicate name check
      ├─ create empty doc in Qdrant
      └─ render list UI immediately
```

### Callback (Inline Keyboard) Flow

All callbacks go through `handle_callback()` in `app/bot/handlers/callbacks.py`.

| Prefix | Action |
|---|---|
| `approve` | Resume agent — execute the proposed tool call |
| `reject_and_retry` | Resume agent — retry with feedback |
| `edit` | Resume agent — edit mode |
| `abort` | Reject agent silently, tell user aborted |
| `del_toggle_<idx>` | Toggle document in multi-delete selection |
| `del_page_<n>` | Navigate multi-delete list pages |
| `del_confirm` | Execute deletion of selected items |
| `del_abort` | Cancel multi-delete |
| `del_refine` | Ask user for a new search query |
| `confirm_update` | Apply the proposed document update |
| `abort_update` | Cancel the update |
| `refine_update` | Ask user to describe target document differently |
| `list_open_<doc_id>` | Open a list from a picker |
| `list_toggle_<doc_id>_<idx>` | Toggle item checked state |
| `list_page_<doc_id>_<page>` | Navigate list pages |
| `list_showdone_<doc_id>_<0\|1>` | Toggle visibility of done items |
| `list_add_<doc_id>` | Prompt user to type a new item |
| `list_clear_<doc_id>` | Ask confirmation before removing done items |
| `list_clear_confirm_<doc_id>` | Execute removal of done items (after confirmation) |

---

## Structured Types Registry

`app/bot/structure_types.py` is the single source of truth for all complex document types.

Any `item_type` ending in `_list` is automatically treated as a structured list type — no registration needed. For types that need custom emoji, labels, or per-item field rendering, add an explicit entry to `STRUCTURED_TYPES`. Always use `is_list_type(item_type)` in code rather than checking `STRUCTURED_ITEM_TYPES` directly, so ad-hoc agent-created types (e.g. `movie_list`) render correctly without code changes.

To **add a new structured type** with custom rendering (e.g. a recipe):

1. Add an entry to `STRUCTURED_TYPES`:

```python
STRUCTURED_TYPES["recipe"] = {
    "label":       "Recipe",
    "emoji":       "🍳",
    "item_fields": ["quantity", "unit"],
}
```

2. If the new type needs custom per-item rendering, extend `render_item_line()`.  
3. Optionally add a `/recipe` command in `list_commands.py` following the same pattern as `/list`.

No changes needed to callbacks, HITL, or the agent — they all read from the registry.

---

## Dev / Prod Separation

| File | Purpose |
|---|---|
| `.env` | Production secrets (Qdrant `documents` collection) |
| `.env.dev` | Development secrets (Qdrant `documents_tests` collection) |
| `compose.yaml` | Production Docker Compose |
| `compose.override.yaml` | Dev overrides: bind-mount source, hot-reload, debugger port |
| `Dockerfile.dev` | Dev image with `watchfiles` for hot-reload |

**Run in dev mode:**

```bash
docker compose up        # applies compose.override.yaml automatically
```

**Run in prod mode:**

```bash
docker compose -f compose.yaml up --build
```

The `QDRANT_COLLECTION_NAME` env var controls which collection is used. Dev uses `documents_tests` so you never pollute production data.

---

## Hot-Reload Development

The dev setup uses [`watchfiles`](https://watchfiles.readthedocs.io/) to restart the bot process whenever a Python file changes:

```yaml
# compose.override.yaml (relevant part)
command: ["watchfiles", "--filter", "python", "python -m app.main_telegram_v2"]
volumes:
  - .:/app
```

Changes to any `.py` file under `/app` trigger an automatic restart — no image rebuild needed.

**VS Code debugging** is also configured in `.vscode/launch.json` for attach-mode debugging on port `5678`.

---

## Deployment

### Prerequisites

- Docker + Docker Compose v2
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- An OpenAI API key
- A running Qdrant instance (or use the one in `compose.yaml`)

### Steps

1. Copy `.env.example` (or create `.env`) with:

```env
TELEGRAM_TOKEN=<your token>
OPENAI_API_KEY=<your key>
AUTHORIZED_ID=<your Telegram user ID>
QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION_NAME=documents
```

2. Build and start:

```bash
docker compose -f compose.yaml up --build -d
```

3. Check logs:

```bash
docker compose logs -f bot
```

4. To update after code changes:

```bash
docker compose -f compose.yaml up --build -d
```

### Finding your Telegram user ID

Send any message to your bot, then check the logs — it will log the `user_id` from incoming updates.

---

## Extending the Bot

### Add a new flat document type (e.g. "movie")

Just chat with the bot: _"Add a movie: Dune, director: Villeneuve, status: watched"_. The agent handles all flat types automatically.

### Add a new structured type

See [Structured Types Registry](#structured-types-registry) above.

### Add a new command

1. Write a handler function in `app/bot/handlers/` (or add it to an existing file).
2. Register it in `build_application()` in `app/main_telegram_v2.py`.

### Add a new agent tool

1. Define the tool in `app/agent/tools.py`.
2. Add the corresponding Pydantic schema in `app/agent/schemas.py`.
3. Register the tool in the agent graph in `app/chat_bot_agent.py`.
4. Add HITL interrupt handling in `app/bot/hitl.py` if the tool requires user confirmation.

---
