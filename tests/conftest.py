import pytest
import asyncio
from app.database.vector_store import QdrantStore
from app.models.embedding_model import StubEmbeddingModel

@pytest.fixture
async def qdrant_store():
    # Use the Stub model to avoid API costs during testing
    embed_model = StubEmbeddingModel(vector_size=768)
    store = QdrantStore(
        host="localhost", 
        port=6333, 
        collection_name="test_collection", 
        embedding_model=embed_model,
        is_test=True  # Use in-memory Qdrant
    )
    await store.initialize()
    yield store
    await store.close()