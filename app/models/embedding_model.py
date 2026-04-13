from typing import List
import random
from google import genai
from langchain.embeddings.base import Embeddings
import logging


logger = logging.getLogger(__name__)


class StubEmbeddingModel(Embeddings):
    def __init__(self, vector_size: int = 768):
        self.vector_size = vector_size

    def embed_query(self, text: str) -> List[float]:
        logger.info(f"[EMBEDDING] StubEmbeddingModel.embed_query called with text: {text[:50]!r}")
        """Return a dummy vector for testing"""
        return [random.random() for _ in range(self.vector_size)]

    def embed_documents(self, docs: List[str]) -> List[List[float]]:
        logger.info(f"[EMBEDDING] StubEmbeddingModel.embed_documents called with {len(docs)} docs")
        return [self.embed_query(t) for t in docs]
    

class GeminiEmbeddingModel(Embeddings):

    def __init__(self, api_key, embedding_model="gemini-embedding-001", vector_size=3072):
        self.vector_size = vector_size
        self.client = genai.Client(api_key=api_key)
        self.embedding_model = embedding_model

    def embed_documents(self, docs):
        logger.info(f"[EMBEDDING] GeminiEmbeddingModel.embed_documents called with {len(docs)} docs")
        try:
            contents = [{"parts": [{"text": doc}]} for doc in docs]
            result = self.client.models.embed_content(model=self.embedding_model, contents=contents)
            logger.info(f"[EMBEDDING] GeminiEmbeddingModel.embed_documents result: {len(result.embeddings)} embeddings")
            return [e.values for e in result.embeddings]
        except Exception as e:
            logger.error(f"[EMBEDDING] GeminiEmbeddingModel.embed_documents error: {e}", exc_info=True)
            raise Exception(f"Embedding request failed: {e}") from e
        
    
    def embed_query(self, text):
        logger.info(f"[EMBEDDING] GeminiEmbeddingModel.embed_query called with text: {text[:50]!r}")
        try:
            contents = {"parts": [{"text": text}]}
            result = self.client.models.embed_content(model=self.embedding_model, contents=contents)
            logger.info(f"[EMBEDDING] GeminiEmbeddingModel.embed_query result: {len(result.embeddings[0].values)} values")
            return result.embeddings[0].values
        except Exception as e:
            logger.error(f"[EMBEDDING] GeminiEmbeddingModel.embed_query error: {e}", exc_info=True)
            raise Exception(f"Embedding request failed: {e}") from e

        
if __name__ == "__main__":

    # # stub model
    # stub_embedding_model = StubEmbeddingModel(vector_size=768)
    # my_doc = "bot Yaana"
    # my_docs = ["a", "b", "c", "d"]
    # embeded_doc = stub_embedding_model.embed_query(text=my_doc)
    # embedded_docs = stub_embedding_model.embed_documents(my_docs)
    # print()

    # gemini
    import os 
    api_key = os.getenv("GOOGLE_API_KEY")
    
    my_text = "what is love?" 
    my_docs = ["what is love?", "baby don't hurt me", "don't hurt me no more"]
    gemini_embedding_model = GeminiEmbeddingModel(api_key=api_key)
    my_embedding = gemini_embedding_model.embed_query(my_text)
    my_embeddings = gemini_embedding_model.embed_documents(my_docs)
    print()




