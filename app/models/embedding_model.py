from typing import List
import random

class StubEmbeddingModel:
    def __init__(self, vector_size: int = 768):
        self.vector_size = vector_size

    def embed(self, text: str) -> List[float]:
        """Return a dummy vector for testing"""
        return [random.random() for _ in range(self.vector_size)]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.embed(t) for t in texts]
    

if __name__ == "__main__":

    
    stub_embedding_model = StubEmbeddingModel(vector_size=768)
    my_doc = "bot Yaana"
    my_docs = ["a", "b", "c", "d"]
    embeded_doc = stub_embedding_model.embed(text=my_doc)
    embedded_docs = stub_embedding_model.embed_batch(my_docs)
    print()
