"""
scripts/wipe_db.py
──────────────────
Standalone script to wipe all documents from the Qdrant collection.
Useful for resetting the database during testing without running the bot.

Usage (from the repo root):
  python -m scripts.wipe_db

You will be prompted to confirm before anything is deleted.
"""

import asyncio
import sys

# ── Ensure repo root is on the path when running directly ────────────────────
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.models.embedding_model import GeminiEmbeddingModel
from app.database.vector_store import QdrantStore


async def main() -> None:
    print(f"Collection : {settings.QDRANT_COLLECTION_NAME}")
    print(f"Host       : {settings.QDRANT_HOST}:{settings.QDRANT_PORT}")
    print()

    answer = input("⚠️  This will permanently delete ALL documents. Type 'yes' to confirm: ").strip()
    if answer.lower() != "yes":
        print("Aborted. Nothing was deleted.")
        return

    embedding = GeminiEmbeddingModel(
        api_key=settings.GOOGLE_API_KEY,
        embedding_model=settings.EMBEDDING_MODEL_NAME,
        vector_size=settings.EMBEDDING_VECTOR_SIZE,
    )

    # Always use localhost — this script runs on the host machine, not inside Docker.
    # The .env file sets QDRANT_HOST=qdrant (Docker service name), which is not
    # reachable from outside the container network.
    vs = QdrantStore(
        host="localhost",
        port=settings.QDRANT_PORT,
        collection_name=settings.QDRANT_COLLECTION_NAME,
        embedding_model=embedding,
    )
    await vs.initialize()

    count = await vs.clear_all()
    await vs.close()

    print(f"✅ Done. {count} document(s) deleted. Collection recreated and ready.")


if __name__ == "__main__":
    asyncio.run(main())
