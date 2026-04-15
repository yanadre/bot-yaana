import asyncio
import logging
from qdrant_client import QdrantClient, models
from qdrant_client.http import models as rest_models
from langchain_qdrant import QdrantVectorStore
import sys
from datetime import datetime
import uuid

# Use a named logger to ensure all logs go to both file and stream handlers set up in main_telegram.py
logger = logging.getLogger("bot")

# --- DIAGNOSTIC: Module-level log to confirm import-time logging ---
logger.info("[QDRANT] vector_store.py module imported (import-time log)")

# --- DIAGNOSTIC: Explicitly set propagate and level ---
logger.propagate = True
logger.setLevel(logging.DEBUG)

# --- DIAGNOSTIC: Top-level logger test function ---
def logger_test():
    try:
        logger.info("[QDRANT] logger_test: This is a test INFO log from vector_store.py")
        logger.debug("[QDRANT] logger_test: This is a test DEBUG log from vector_store.py")
        for handler in logger.handlers:
            handler.flush()
    except Exception as e:
        print(f"[QDRANT] logger_test: Exception during logging: {e}", file=sys.stderr)

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

    async def add(self, texts: list[str], metadatas: list[dict]):
        """
        Insert documents into the collection.
        Adds versioning and timestamps to each document.
        texts: list of text documents
        metadatas: list of dicts with info about each vector (text, source, etc.)
        """
        logger.info(f"[QDRANT] add called with texts={texts}, metadatas={metadatas}")
        if not self.vector_store:
            raise ValueError("Vector store not initialized")
        now = datetime.utcnow().isoformat()
        new_texts = []
        new_metadatas = []
        for text, metadata in zip(texts, metadatas):
            doc_id = metadata.get("id", str(uuid.uuid4()))
            metadata = metadata.copy()
            metadata["id"] = doc_id
            metadata["version"] = "new"
            metadata["creation_datetime"] = now
            metadata["update_datetime"] = now
            new_texts.append(text)
            new_metadatas.append(metadata)
            logger.debug(f"[QDRANT] add: Added versioning to doc_id={doc_id}, creation_datetime={now}")
        # LangChain's aadd_texts is async, but internally calls sync client, so await is fine
        await self.vector_store.aadd_texts(texts=new_texts, metadatas=new_metadatas)
        logger.info(f"[QDRANT] add completed for {len(new_texts)} texts with versioning and timestamps.")

    def _build_filter(self, filter_dict: dict = None) -> models.Filter | None:
        """
        Build a Qdrant filter from a dictionary of metadata.
        """
        if not filter_dict:
            return None
        conditions = []
        for key, value in filter_dict.items():
            # LangChain nests metadata under the 'metadata' key in the payload
            conditions.append(
                models.FieldCondition(
                    key=f"metadata.{key}", 
                    match=models.MatchValue(value=value)
                )
            )
        return models.Filter(must=conditions)

    async def search(self, query: str, filter_dict: dict = None, top_k: int = 5, score_threshold: float = 0.2):
        """
        Semantic search or list documents in the collection.
        Always filters for version='new' unless explicitly overridden.
        query: search string (if empty, lists docs)
        filter_dict: metadata filter
        top_k: number of results
        score_threshold: minimum similarity score
        """
        logger.info(f"[QDRANT] search called with query='{query}', filter_dict={filter_dict}, top_k={top_k}, score_threshold={score_threshold}")
        if not self.vector_store:
            raise ValueError("Vector store not initialized")
        # Always filter for version='new' unless explicitly overridden
        if filter_dict is None:
            filter_dict = {}
        if "version" not in filter_dict:
            filter_dict["version"] = "new"
        qdrant_filter = self._build_filter(filter_dict)
        if not query or query.strip() == "":
            points, _ = self.sync_client.scroll(
                collection_name=self.collection_name,
                scroll_filter=qdrant_filter,
                limit=top_k
            )
            results = [
                {
                    "text": p.payload.get("page_content", ""), 
                    "metadata": p.payload.get("metadata", {}),
                    "score": 1.0
                } for p in points
            ]
            logger.info(f"[QDRANT] search (list docs) result: {results}")
            return results
        results = await self.vector_store.asimilarity_search_with_score(
            query, 
            k=top_k, 
            filter=qdrant_filter,
            score_threshold=score_threshold
        )
        formatted = [
            {
                "text": doc.page_content, 
                "score": score, 
                "metadata": doc.metadata,
            } for doc, score in results
        ]
        logger.info(f"[QDRANT] search result: {formatted}")
        return formatted

    async def update_document(self, filter_dict: dict, new_text: str = None, new_metadata: dict = None):
        """
        Versioned update: mark old doc as 'old', insert new doc as 'new' with updated fields.
        filter_dict: metadata filter to find the document to update
        new_text: new text content (if provided)
        new_metadata: new metadata fields to update (merged with existing)
        """
        logger.info(f"[QDRANT] update_document called with filter_dict={filter_dict}, new_text={new_text}, new_metadata={new_metadata}")
        if not self.sync_client:
            raise ValueError("Sync client not initialized")
        # Always filter for version='new'
        filter_dict = filter_dict.copy()
        filter_dict["version"] = "new"
        qdrant_filter = self._build_filter(filter_dict)
        points, _ = self.sync_client.scroll(
            collection_name=self.collection_name,
            scroll_filter=qdrant_filter,
            limit=1
        )
        if not points:
            logger.error(f"[QDRANT] update_document: No matching document found for filter {filter_dict}")
            raise Exception("Document to update not found.")
        point = points[0]
        old_metadata = point.payload.get("metadata", {}).copy()
        old_text = point.payload.get("page_content", "")
        doc_id = old_metadata.get("id", str(uuid.uuid4()))
        creation_datetime = old_metadata.get("creation_datetime", datetime.utcnow().isoformat())

        # Mark current as 'old'
        self.sync_client.set_payload(
            collection_name=self.collection_name,
            payload={"metadata": {**old_metadata, "version": "old", "update_datetime": datetime.utcnow().isoformat()}},
            points=[point.id]
        )
        logger.info(f"[QDRANT] update_document: Marked old doc id={point.id} as 'old'.")

        # Insert new version
        now = datetime.utcnow().isoformat()
        new_doc_metadata = old_metadata.copy()
        if new_metadata:
            new_doc_metadata.update(new_metadata)
        new_doc_metadata["version"] = "new"
        new_doc_metadata["id"] = doc_id
        new_doc_metadata["creation_datetime"] = creation_datetime
        new_doc_metadata["update_datetime"] = now
        new_doc_text = new_text if new_text is not None else old_text

        await self.vector_store.aadd_texts(texts=[new_doc_text], metadatas=[new_doc_metadata])
        logger.info(f"[QDRANT] update_document: Inserted new version for doc_id={doc_id}, creation_datetime={creation_datetime}, update_datetime={now}")


    async def delete(self, filter_dict: dict):
        logger.info(f"[QDRANT] delete called with filter_dict={filter_dict}")
        if not self.sync_client:
            raise ValueError("Sync client not initialized")
        qdrant_filter = self._build_filter(filter_dict)
        self.sync_client.delete(
            collection_name=self.collection_name,
            points_selector=qdrant_filter
        )
        logger.info(f"[QDRANT] delete completed for filter_dict={filter_dict}")

    async def close(self):
        if self.sync_client:
            self.sync_client.close()

    def print_all_documents(self, limit=100):
        """Log all documents in the Qdrant collection for debugging."""
        try:
            logger.info(f"[QDRANT] print_all_documents: ENTERED for collection '{self.collection_name}' with limit={limit}")
            logger.debug(f"[QDRANT] print_all_documents: DEBUG log for diagnostics.")
            for handler in logger.handlers:
                handler.flush()
            if not self.sync_client:
                logger.error("[QDRANT] print_all_documents: Sync client not initialized!")
                for handler in logger.handlers:
                    handler.flush()
                raise ValueError("Sync client not initialized")
            logger.info(f"[QDRANT] print_all_documents: About to call scroll on collection '{self.collection_name}' (host={self.host}, port={self.port})")
            for handler in logger.handlers:
                handler.flush()
            points, _ = self.sync_client.scroll(
                collection_name=self.collection_name,
                limit=limit
            )
            logger.info(f"[QDRANT] print_all_documents: scroll returned type(points)={type(points)}, len(points)={len(points)}")
            for handler in logger.handlers:
                handler.flush()
            msg = f"[QDRANT] print_all_documents: Collection '{self.collection_name}' - Found {len(points)} documents."
            logger.info(msg)
            for handler in logger.handlers:
                handler.flush()
            if not points:
                msg = f"[QDRANT] print_all_documents: Collection '{self.collection_name}' is EMPTY."
                logger.info(msg)
                for handler in logger.handlers:
                    handler.flush()
            for i, p in enumerate(points):
                msg = f"[QDRANT] Document {i+1}: id={getattr(p, 'id', 'N/A')}, text={p.payload.get('page_content', '')!r}, metadata={p.payload.get('metadata', {})!r}"
                logger.info(msg)
                for handler in logger.handlers:
                    handler.flush()
        except Exception as e:
            logger.error(f"[QDRANT] print_all_documents: Exception occurred: {e}", exc_info=True)
            for handler in logger.handlers:
                handler.flush()

