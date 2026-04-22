"""
setup.py
────────
Bot lifecycle: logging setup, vector store + agent initialization,
startup/shutdown hooks.
"""

import logging
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
from app.config import settings


# ── Logging ───────────────────────────────────────────────────────────────────

def configure_logging() -> logging.Logger:
    import os
    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(log_formatter)

    logger = logging.getLogger("bot")
    logger.setLevel(logging.INFO)
    logger.addHandler(stream_handler)

    # File handler — only attach if the log directory exists (Docker environment)
    log_path = '/app/logs/bot.log'
    if os.path.isdir(os.path.dirname(log_path)):
        file_handler = WatchedFileHandler(log_path)
        file_handler.setFormatter(log_formatter)
        logger.addHandler(file_handler)

    return logger


logger = configure_logging()


# ── HITL middleware config ─────────────────────────────────────────────────────

_HITL_INTERRUPT_ON = {
    "add_to_vault":         {"allowed_decisions": ["approve", "reject", "edit"]},
    "delete_from_vault":    {"allowed_decisions": ["approve", "reject", "edit"]},
    "update_vault_metadata":{"allowed_decisions": ["approve", "reject", "edit"]},
    "search_vault":         False,  # search runs automatically, no confirmation needed
}


# ── Lifecycle hooks ────────────────────────────────────────────────────────────

async def on_startup(app: Application) -> None:
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

    llm = ChatGoogleGenerativeAI(model=settings.LLM_MODEL, temperature=0)
    hitl_middleware = HumanInTheLoopMiddleware(interrupt_on=_HITL_INTERRUPT_ON)

    app.bot_data["agent"] = create_agent(
        model=llm,
        tools=tools,
        checkpointer=MemorySaver(),
        middleware=[hitl_middleware],
        system_prompt=settings.SYSTEM_PROMPT,
    )
    logger.info("[on_startup] Ready.")


async def on_shutdown(app: Application) -> None:
    logger.info("Shutting down — closing vector store.")
    await app.bot_data["vs"].close()
    logger.info("==== BOT SESSION END ====\n")
