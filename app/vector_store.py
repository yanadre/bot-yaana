from qdrant_client import QdrantClient, models
from langchain_qdrant import QdrantVectorStore

class QdrantStore:
    def __init__(self, host: str, 
                 port: int, 
                 collection_name: str, 
                 embedding_model):
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        self.client = None
        self.vector_store= None


    async def initialize(self):
        """Connect to Qdrant and create collection if missing."""
        try:
            self.client = QdrantClient(host=self.host, port=self.port)
            # Check if collection exists
            if not self.client.collection_exists(self.collection_name):
                print(f"Creating collection: {self.collection_name}")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=self.embedding_model.vector_size,
                        distance=models.Distance.COSINE
                    )
                )   
                self.vector_store =  QdrantVectorStore(
                    client=self.client,
                    collection_name=self.collection_name,
                    embedding=self.embedding_model
                )      
            else:
                print(f"Collection '{self.collection_name}' already exists")
        except Exception as e:
            print(f"Qdrant connection failed: {e}")
            raise e


    async def add(self, texts: list[str], metadatas: list[dict]):
        """
        Insert documents into the collection.
        texts: list of text documents
        metadatas: list of dicts with info about each vector (text, source, etc.)
        """
        if not self.vector_store:
            raise ValueError("Vector store not initialized")
        self.vector_store.add_texts(texts=texts, metadatas=metadatas)

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Search the collection for top_k similar vectors.
        Returns list of documents/metadata
        """

        if not self.vector_store:
            raise ValueError("Vector store not initialized")
        results = self.vector_store.similarity_search(query, k=top_k)
        return [{"text": r.page_content, **r.metadata} for r in results]
    

    async def delete(self, filter: dict):
        """Delete documents matching filter (e.g., {"id": 1})"""
        if not self.vector_store:
            raise ValueError("Vector store not initialized")
        self.client.delete(
            collection_name=self.collection_name,
            filter=models.Filter(
                must=[models.FieldCondition(
                    key=k,
                    match=models.MatchValue(value=v)
                ) for k, v in filter.items()]
            )
        )


    async def delete(self, filter: dict):
        """Delete documents matching filter (e.g., {"id": 1})"""
        if not self.vector_store:
            raise ValueError("Vector store not initialized")
        self.client.delete(
            collection_name=self.collection_name,
            filter=models.Filter(
                must=[models.FieldCondition(
                    key=k,
                    match=models.MatchValue(value=v)
                ) for k, v in filter.items()]
            )
        )


# ------------------------
# Test/debug block
# ------------------------      
if __name__ == "__main__":
    
    import asyncio
    from config import settings
    from models.embedding_model import StubEmbeddingModel


    embedding_model = StubEmbeddingModel(vector_size=768)
    
    qdrant_store = QdrantStore(host=settings.QDRANT_HOST,
                               port=settings.QDRANT_PORT,
                               collection_name=settings.QDRANT_COLLECTION_NAME,
                               embedding_model=embedding_model


                               )
    
    asyncio.run(qdrant_store.initialize())

    asyncio.run(qdrant_store.add(
        texts=["Hello world", "FastAPI + Qdrant", "LangChain is cool"],
        metadatas=[{"id": 1}, {"id": 2}, {"id": 3}]
    ))

    results = asyncio.run(qdrant_store.search("Hello"))
    print("Search results:", results)

    asyncio.run(qdrant_store.delete({"id": 1}))
    print("Deleted document with id 1")
    
    print()
