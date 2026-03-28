import asyncio
import logging
from qdrant_client import QdrantClient, models
from langchain_qdrant import QdrantVectorStore

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class QdrantStore:
    def __init__(self, 
                 host: str, 
                 port: int, 
                 collection_name: str, 
                 embedding_model,
                 api_key: str = None, 
                 is_test: bool = False):
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self.api_key = api_key
        self.is_test = is_test
        self.embedding_model = embedding_model
        
        self.sync_client = None       
        self.vector_store = None

    async def initialize(self):
        """Connect to Qdrant and initialize vector store."""
        try:
            if self.is_test:
                self.sync_client = QdrantClient(location=":memory:")
            else:
                client_args = {"host": self.host, "port": self.port, "api_key": self.api_key}
                self.sync_client = QdrantClient(**client_args)

            # 1. Setup Collection
            if not self.sync_client.collection_exists(self.collection_name):
                logger.info(f"Creating collection: {self.collection_name}")
                self.sync_client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=self.embedding_model.vector_size,
                        distance=models.Distance.COSINE
                    )
                )
            
            # 2. Initialize Vector Store
            self.vector_store = QdrantVectorStore(
                client=self.sync_client, 
                collection_name=self.collection_name,
                embedding=self.embedding_model
            )      
        except Exception as e:
            logger.exception(f"Qdrant connection failed: {e}")
            raise e

    async def add(self, texts: list[str], metadatas: list[dict]): # TODO: logging
        """
        Insert documents into the collection.
        texts: list of text documents
        metadatas: list of dicts with info about each vector (text, source, etc.)
        """
        if not self.vector_store:
            raise ValueError("Vector store not initialized")
        # LangChain's aadd_texts is async, but internally calls sync client, so await is fine
        await self.vector_store.aadd_texts(texts=texts, metadatas=metadatas)

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Search with similarity scores included."""
        if not self.vector_store:
            raise ValueError("Vector store not initialized")
        
        results = await self.vector_store.asimilarity_search_with_score(query, k=top_k)
        
        return [
            {
                "text": doc.page_content, 
                "score": score, 
                "metadata": doc.metadata,
            } for doc, score in results
        ]

    async def delete(self, filter_dict: dict): #TODO: logging 
        """Delete documents matching filter (e.g., {"id": 1})"""
        if not self.sync_client:
            raise ValueError("Sync client not initialized")
        
        qdrant_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key=k,
                    match=models.MatchValue(value=v)
                ) for k, v in filter_dict.items()
            ]
        )
        
        self.sync_client.delete(
            collection_name=self.collection_name,
            points_selector=qdrant_filter
        )

    async def close(self):
        if self.sync_client:
            self.sync_client.close()

# ------------------------
# Test block
# ------------------------      
if __name__ == "__main__":
    class MockSettings:
        QDRANT_HOST = None
        QDRANT_PORT = None
    
    settings = MockSettings()
    
    # Assuming StubEmbeddingModel exists in your environment
    from models.embedding_model import StubEmbeddingModel

    async def main():
        embedding_model = StubEmbeddingModel(vector_size=768)
        qdrant_store = QdrantStore(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            collection_name="test_collection",
            is_test=True,
            embedding_model=embedding_model
        )

        try:
            print("--- Initializing ---")
            await qdrant_store.initialize()

            print("--- Adding Documents ---")
            await qdrant_store.add(
                texts=["Hello world", "FastAPI + Qdrant", "i'm the queen of the world"],
                metadatas=[{"id": 1}, {"id": 2}, {"topic": "A thought"}]
            )

            print("--- Searching ---")
            results = await qdrant_store.search("qdrant", top_k=1)
            print("Search results (with scores):", results)

            print("--- Deleting ---")
            await qdrant_store.delete({"id": 1})
            
            print("--- Verifying Deletion ---")
            # Minimal delay for memory index consistency
            await asyncio.sleep(0.1) 
            final_results = await qdrant_store.search("", top_k=5)
            ids = [r.get('metadata', {}) for r in final_results]
            print("Remaining IDs (should be [2]):", ids)

        finally:
            print("--- Closing Connection ---")
            await qdrant_store.close()
        
    asyncio.run(main())