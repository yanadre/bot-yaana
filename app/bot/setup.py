"""
setup.py
────────
Bot lifecycle: logging setup, vector store + agent initialization,
startup/shutdown hooks.
"""

import logging
import os

import sys
from logging.handlers import WatchedFileHandler

from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langgraph.checkpoint.memory import MemorySaver
from telegram.ext import Application

from app.models.embedding_model import GeminiEmbeddingModel
from app.database.vector_store import QdrantStore
from app.agent.tools import tools
from app.bot.structure_types import build_system_prompt
from app.config import settings


# ── Logging ───────────────────────────────────────────────────────────────────

def configure_logging() -> logging.Logger:
    """
    Set up the "bot" logger with a stream handler and an optional file handler.

    Stream handler (stdout) is always active — this is what Docker captures.
    File handler writes to /app/logs/bot.log but is only attached when that
    directory exists, so local dev runs don't fail on a missing path.

    Called once at module import time. Returns the configured logger.
    """
    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(log_formatter)

    logger = logging.getLogger("bot")
    logger.setLevel(logging.INFO)
    logger.addHandler(stream_handler)

    log_path = '/app/logs/bot.log'
    if os.path.isdir(os.path.dirname(log_path)):
        file_handler = WatchedFileHandler(log_path)
        file_handler.setFormatter(log_formatter)
        logger.addHandler(file_handler)

    return logger


logger = configure_logging()


# ── HITL interrupt config ─────────────────────────────────────────────────────

_HITL_INTERRUPT_ON = {
    # Each key is a tool name. The value controls whether execution pauses:
    #   dict  → pause and show approval UI; "allowed_decisions" lists valid responses
    #   False → run automatically, no confirmation needed
    "add_to_vault":          {"allowed_decisions": ["approve", "reject", "edit"]},
    "delete_from_vault":     {"allowed_decisions": ["approve", "reject"]},
    "update_vault_metadata": {"allowed_decisions": ["approve", "reject", "edit"]},
    "search_vault":          False,
}


# ── Lifecycle hooks ────────────────────────────────────────────────────────────

async def on_startup(app: Application) -> None:
    """
    PTB startup hook — called once when the bot process starts.

    Initialises the following (in order) and stores results in app.bot_data:
      1. Embedding model (Gemini)
      2. Qdrant vector store — creates the collection if it doesn't exist yet
      3. Task list ID — resolved before building the prompt because the prompt
         embeds the ID so the agent can reference the task list directly
      4. System prompt — generated at runtime from STRUCTURED_TYPES so the
         agent's vault description is always in sync with the code
      5. LangGraph agent — wired with the LLM, all tools, a MemorySaver
         checkpointer for per-thread history, and the HITL middleware

    All results are stored in app.bot_data and accessed by handlers via
    context.bot_data["vs"], context.bot_data["agent"], etc.
    """
    logger.info("\n\n==== BOT SESSION START ====")
    logger.info("Initializing vector store and agent.")

    embedding = GeminiEmbeddingModel(
        api_key=settings.GOOGLE_API_KEY,
        embedding_model=settings.EMBEDDING_MODEL_NAME,
        vector_size=settings.EMBEDDING_VECTOR_SIZE,
    )

    vs = QdrantStore(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
        collection_name=settings.QDRANT_COLLECTION_NAME,
        embedding_model=embedding,
    )
    await vs.initialize()
    app.bot_data["vs"] = vs

    try:
        vs.print_all_documents(limit=100)
    except Exception as e:
        logger.error(f"[on_startup] print_all_documents failed: {e}", exc_info=True)

    app.bot_data["task_list_id"] = await _resolve_task_list(vs)

    system_prompt = build_system_prompt(app.bot_data["task_list_id"] or "unknown")

    llm = ChatGoogleGenerativeAI(model=settings.LLM_MODEL, temperature=0)
    hitl_middleware = HumanInTheLoopMiddleware(interrupt_on=_HITL_INTERRUPT_ON)

    app.bot_data["agent"] = create_agent(
        model=llm,
        tools=tools,
        checkpointer=MemorySaver(),   # per-thread conversation history (in-process)
        middleware=[hitl_middleware],
        system_prompt=system_prompt,
    )
    logger.info("[on_startup] Ready.")


async def on_shutdown(app: Application) -> None:
    """
    PTB shutdown hook — called once when the bot process stops.

    Closes the Qdrant connection cleanly so in-flight requests are not
    left hanging and resources are released before the process exits.
    """
    logger.info("Shutting down — closing vector store.")
    await app.bot_data["vs"].close()
    logger.info("==== BOT SESSION END ====\n")


# ── Private helpers ────────────────────────────────────────────────────────────

async def _resolve_task_list(vs) -> str | None:
    """
    Find the single task_list document in the vault and return its ID.

    Possible outcomes:
      - Exactly one task_list found  → return its ID (normal case)
      - Multiple found               → log a warning, use the first one's ID
      - None found (first run)       → create an empty task_list, return its ID
      - Unexpected exception         → log the error, return None (the bot still
                                       starts but the system prompt shows id='unknown')
    """
    try:
        results = await vs.search(query="tasks", filter_dict={"item_type": "task_list"})
        if results:
            if len(results) > 1:
                logger.warning(f"[startup] Found {len(results)} task_list documents — expected 1. Using the first.")
            task_list_id = results[0]["metadata"]["id"]
            logger.info(f"[startup] Found task list id={task_list_id}")
            return task_list_id

        # First run — create an empty task list
        await vs.add(texts=["Tasks: (empty)"], metadatas=[{
            "item_type": "task_list",
            "name":      "Tasks",
            "items":     [],
        }])
        new_results = await vs.search(query="tasks", filter_dict={"item_type": "task_list"})
        task_list_id = new_results[0]["metadata"]["id"]
        logger.info(f"[startup] Created task list id={task_list_id}")
        return task_list_id

    except Exception as e:
        logger.error(f"[startup] Failed to resolve task list: {e}", exc_info=True)
        return None
