from typing import List
import random
from langchain.embeddings.base import Embeddings


class StubEmbeddingModel(Embeddings):
    def __init__(self, vector_size: int = 768):
        self.vector_size = vector_size

    def embed_query(self, text: str) -> List[float]:
        """Return a dummy vector for testing"""
        return [random.random() for _ in range(self.vector_size)]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_query(t) for t in texts]
    

if __name__ == "__main__":

    
    stub_embedding_model = StubEmbeddingModel(vector_size=768)
    my_doc = "bot Yaana"
    my_docs = ["a", "b", "c", "d"]
    embeded_doc = stub_embedding_model.embed_query(text=my_doc)
    embedded_docs = stub_embedding_model.embed_documents(my_docs)
    print()
