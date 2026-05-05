# bot-yaana 🤖

A private personal assistant that lives in Telegram. It maintains a knowledge vault backed by a Qdrant vector store and uses a Gemini-powered LangGraph agent with Human-In-The-Loop (HITL) confirmation for all write operations.

For full documentation see **[DOCS.md](DOCS.md)**.

---

## Features

| Capability | Status |
|---|---|
| Save / update / delete anything in plain language | ✅ |
| Auto-extract and store structured fields from free-text | ✅ |
| Search the vault by meaning | ✅ |
| Interactive list UI (shopping, tasks, watchlists, …) | ✅ |
| Fast-path list commands (`/list`, `/tasks`, `/newlist`, `/newtasks`) | ✅ |
| Confirm before any write (preview + approve/reject) | ✅ |
| Answer questions using stored data as context | ⚠️ Basic |
| Reminders / proactive push messages | ❌ Not yet |

---

## Project structure

```
app/
├── main_telegram_v2.py     Entry point — wires handlers, starts polling
├── config.py               Pydantic settings (reads .env)
├── chat_bot_agent.py       LangGraph agent definition
├── agent/
│   ├── tools.py            Agent tools: add/update/delete/search vault
│   └── schemas.py          Pydantic schemas for tool inputs
├── bot/
│   ├── setup.py            Startup/shutdown lifecycle hooks
│   ├── formatting.py       Markdown/HTML formatting helpers
│   ├── hitl.py             HITL interrupt rendering (previews, keyboards)
│   ├── lists.py            List/task UI rendering (text + inline keyboard)
│   ├── structure_types.py  Structured-type registry, emoji maps, item factory
│   ├── update_flow.py      Direct-update helpers
│   └── handlers/
│       ├── callbacks.py    All inline keyboard callbacks
│       ├── chat.py         Agent chat entry point (handles HITL states)
│       ├── commands.py     /start, /migrate
│       └── list_commands.py /list, /tasks, /newlist, /newtasks
├── database/
│   └── vector_store.py     Qdrant wrapper (add/search/update/delete/patch)
└── models/
    └── embedding_model.py  Embedding model factory
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Bot framework | `python-telegram-bot` v21 (async) |
| AI agent | `langgraph` with Google Gemini LLM |
| Vector store | `qdrant-client` + `langchain-qdrant` |
| Embeddings | `langchain-google-genai` (Gemini embeddings) |
| Runtime | Docker Compose |

---

## Setup

### Prerequisites

- Docker & Docker Compose v2
- Google API key (Gemini)
- Telegram bot token

### Environment variables

Create a `.env` file (never commit it):

```env
TELEGRAM_TOKEN=...
GOOGLE_API_KEY=...
AUTHORIZED_ID=...                      # Your Telegram user ID
QDRANT_HOST=qdrant
QDRANT_PORT=6333
QDRANT_COLLECTION_NAME=documents
LLM_MODEL=gemini-2.0-flash
EMBEDDING_MODEL_NAME=gemini-embedding-001
EMBEDDING_VECTOR_SIZE=3072
```

### Run (production)

```bash
docker compose -f compose.yaml up --build -d
```

### Run (dev, with hot-reload)

```bash
docker compose up   # applies compose.override.yaml automatically
```

---

## Changelog

### v0.4 — 2026-05
- Interactive list UI for shopping, tasks, and any `*_list` type
- Fast-path commands: `/list`, `/tasks`, `/newlist`, `/newtasks`
- Structured-type registry (`structure_types.py`) with emoji, labels, item factory
- Paginated list view, toggle checked state, clear done items
- Hot-reload dev setup with `watchfiles` + VS Code attach debugging

### v0.3 — 2026-04-21
- Refactored `main_telegram.py` into modular `app/bot/` package (`main_telegram_v2.py`)
- Update confirmation now shows **before ↔ after diff** with strikethrough on changed fields
- Fixed async blocking: replaced `asyncio.run_until_complete` with proper `await`
- Stale/duplicate Telegram callback queries now silently ignored

### v0.2 — 2026-04-14
- HITL approval flow for add, delete, and update operations
- Update document flow with document preview
- Graceful handling of Gemini 429 (quota) and 503 (unavailable) errors

### v0.1 — 2026-03-29
- Initial working bot: add, search, delete via Telegram
- Qdrant vector store with Gemini embeddings
- Docker Compose setup