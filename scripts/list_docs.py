"""
scripts/list_docs.py
────────────────────
Standalone script to display all documents in the Qdrant collection.
Useful for inspecting the database state during testing.

Usage (from the repo root):
  python -m scripts.list_docs
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.models.embedding_model import GeminiEmbeddingModel
from app.database.vector_store import QdrantStore


async def main() -> None:
    print(f"Collection : {settings.QDRANT_COLLECTION_NAME}")
    print(f"Host       : localhost:{settings.QDRANT_PORT}")
    print()

    embedding = GeminiEmbeddingModel(
        api_key=settings.GOOGLE_API_KEY,
        embedding_model=settings.EMBEDDING_MODEL_NAME,
        vector_size=settings.EMBEDDING_VECTOR_SIZE,
    )

    vs = QdrantStore(
        host="localhost",
        port=settings.QDRANT_PORT,
        collection_name=settings.QDRANT_COLLECTION_NAME,
        embedding_model=embedding,
    )
    await vs.initialize()

    # Scroll all points directly (no version filter, no embedding needed)
    points, _ = vs.sync_client.scroll(
        collection_name=vs.collection_name,
        limit=500,
        with_payload=True,
    )

    await vs.close()

    if not points:
        print("Collection is empty.")
        return

    print(f"Found {len(points)} document(s):\n")
    print("─" * 60)
    for i, p in enumerate(points, 1):
        text     = p.payload.get("page_content", "")
        metadata = p.payload.get("metadata", {})
        version  = metadata.get("version", "—")
        item_type = metadata.get("item_type", "—")
        doc_id   = metadata.get("id", str(p.id))
        print(f"[{i}] {text!r}")
        print(f"     type={item_type}  version={version}  id={doc_id}")
        # Print remaining metadata fields
        skip = {"id", "version", "item_type", "_id", "_collection_name"}
        extra = {k: v for k, v in metadata.items() if k not in skip}
        if extra:
            for k, v in extra.items():
                # Truncate long values (e.g. items[] arrays)
                v_str = str(v)
                if len(v_str) > 80:
                    v_str = v_str[:77] + "…"
                print(f"     {k}={v_str}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
