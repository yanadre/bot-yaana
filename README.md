# Bot Yaana 🤖

A personal Telegram bot that manages a private knowledge vault backed by a Qdrant vector store.  
The bot uses a Gemini-powered LangGraph agent with Human-In-The-Loop (HITL) confirmation for all write operations.

---

## Features

| Feature | Status |
|---------|--------|
| Add items to vault via natural language | ✅ |
| Search vault via natural language | ✅ |
| Delete items from vault with confirmation | ✅ |
| Edit/update items with before↔after preview | ✅ |
| HITL approval for all write operations | ✅ |
| Multi-language support (Hebrew / English) | ✅ |

---

## Architecture

```
app/
  bot/
    setup.py            ← Startup/shutdown, vector store & agent init
    formatting.py       ← Response formatting helpers
    hitl.py             ← HITL interrupt parsing & approval UI builders
    update_flow.py      ← Update document logic (direct + user-described)
    handlers/
      commands.py       ← /start command
      chat.py           ← Main message handler (state machine)
      callbacks.py      ← Inline keyboard button handler
  agent/
    tools.py            ← LangChain tools: add, search, delete, update
    schemas.py          ← Tool input/output schemas
  database/
    vector_store.py     ← Qdrant wrapper (add, search, update, delete)
  models/
    embedding_model.py  ← Gemini embedding model wrapper
  config.py             ← Settings (loaded from environment)
  main_telegram_v2.py   ← Entry point (wires handlers, starts polling)
  main_telegram.py      ← Legacy entry point (kept for reference)
```

### User interaction state machine

```
Normal message
    └─► agent.invoke()
            ├─► No interrupt ──────────────────► reply with agent response
            └─► HITL interrupt
                    ├─► add_to_vault    ─────► [Approve / Retry / Edit / Abort]
                    ├─► delete_from_vault ───► [Approve / Retry / Edit / Abort]
                    └─► update_vault_metadata
                            └─► show before↔after diff
                                    ├─► [Approve] ── apply changes directly
                                    ├─► [Another Document] ── refining_update_search
                                    └─► [Abort]
```

---

## Tech Stack

- **LLM**: Google Gemini (via `langchain-google-genai`)
- **Agent framework**: LangGraph + LangChain agents
- **Vector store**: Qdrant
- **Bot framework**: python-telegram-bot v21
- **Infrastructure**: Docker Compose

---

## Setup

### Prerequisites
- Docker & Docker Compose
- Google API key (Gemini)
- Telegram bot token

### Environment variables

Create a `.env` file (never commit it):

```env
TELEGRAM_TOKEN=...
GOOGLE_API_KEY=...
AUTHORIZED_ID=...          # Your Telegram user ID
QDRANT_HOST=qdrant
QDRANT_PORT=6333
QDRANT_COLLECTION_NAME=documents
LLM_MODEL=gemini-2.0-flash
EMBEDDING_MODEL_NAME=models/text-embedding-004
EMBEDDING_VECTOR_SIZE=768
```

### Run

```bash
docker-compose up --build
```

---

## Planned Improvements

- [ ] **Streaming responses** — show a live "typing…" placeholder that updates token-by-token as Gemini responds (skeleton already in `chat.py`)
- [ ] **Search-with-button** — tap "🔍 Search" then type a query directly; bypasses the LLM for pure search (hook in `callbacks.py`)
- [ ] **Multiple users** — per-user Qdrant namespacing + auth list
- [ ] **Async agent calls** — `agent.ainvoke()` to avoid blocking the event loop under load

---

## Changelog

### v0.3 — 2026-04-21
- Refactored `main_telegram.py` into modular `app/bot/` package (`main_telegram_v2.py`)
- Update confirmation now shows **before ↔ after diff** with strikethrough on changed fields
- Fixed async blocking: `asyncio.run_until_complete` replaced with proper `await` in callback handler
- Stale/duplicate Telegram callback queries now silently ignored instead of raising an error

### v0.2 — 2026-04-14
- Added HITL approval flow for add, delete, and update operations
- Added update document flow with document preview
- Graceful handling of Gemini 429 (quota) and 503 (unavailable) errors

### v0.1 — 2026-03-29
- Initial working bot: add, search, delete via Telegram
- Qdrant vector store with Gemini embeddings
- Docker Compose setup