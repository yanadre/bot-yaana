from typing import List
import random
from google import genai
from langchain.embeddings.base import Embeddings


class StubEmbeddingModel(Embeddings):
    def __init__(self, vector_size: int = 768):
        self.vector_size = vector_size

    def embed_query(self, text: str) -> List[float]:
        """Return a dummy vector for testing"""
        return [random.random() for _ in range(self.vector_size)]

    def embed_documents(self, docs: List[str]) -> List[List[float]]:
        return [self.embed_query(t) for t in docs]
    

class GeminiEmbeddingModel(Embeddings):

    def __init__(self, api_key, embedding_model="gemini-embedding-001", vector_size=3072):
        self.vector_size = vector_size
        self.client = genai.Client(api_key=api_key)
        self.embedding_model = embedding_model

    def embed_documents(self, docs):
        try:
            contents = [{"parts": [{"text": doc}]} for doc in docs]
            result = self.client.models.embed_content(model=self.embedding_model, contents=contents)
            return [e.values for e in result.embeddings]
        except Exception as e:
            raise Exception(f"Embedding request failed: {e}") from e
        
    
    def embed_query(self, text):
        try:
            contents = {"parts": [{"text": text}]}
            result = self.client.models.embed_content(model=self.embedding_model, contents=contents)
            return result.embeddings[0].values
        except Exception as e:
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




