"""ChromaDB vector database service for semantic search over academic papers."""

import structlog
from typing import Optional

from ..config import settings

logger = structlog.get_logger(__name__)


class VectorService:
    """ChromaDB vector database service for storing and searching paper embeddings."""

    COLLECTION_NAME = "academic_papers"

    def __init__(self, chroma_dir: Optional[str] = None):
        self.chroma_dir = chroma_dir or settings.CHROMA_DIR
        self._client = None
        self._collection = None
        self._embedding_fn = None
        # 降级标记：嵌入模型加载失败时置为 True，检索质量可能下降
        self.degraded = False

    def init(self):
        """Initialize ChromaDB client, embedding function, and collection."""
        try:
            import chromadb
        except ImportError:
            logger.warning("chromadb not installed, vector service disabled")
            return False

        try:
            self._client = chromadb.PersistentClient(path=self.chroma_dir)

            # Use sentence-transformers embedding function
            try:
                from chromadb.utils import embedding_functions
                self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                    model_name=settings.RAG_EMBEDDING_MODEL
                )
            except Exception as e:
                logger.warning(f"Failed to load sentence-transformers model: {e}")
                logger.error("嵌入模型加载失败,ChromaDB 将使用默认嵌入,检索质量可能下降")
                logger.info("Falling back to ChromaDB default embedding function")
                self._embedding_fn = None
                self.degraded = True

            # Get or create collection
            self._collection = self._client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                embedding_function=self._embedding_fn,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                f"ChromaDB initialized: {self._collection.count()} documents in '{self.COLLECTION_NAME}'"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB: {e}")
            return False

    @property
    def is_ready(self) -> bool:
        # 嵌入模型降级时视为未就绪，触发 RAG 关键词搜索回退
        return self._collection is not None and not self.degraded

    def add_documents(self, documents: list[dict]):
        """Add documents to the vector collection.

        Each document dict should have: id, title, abstract, source_db, year, keywords
        """
        if not self.is_ready or not documents:
            return

        ids = []
        texts = []
        metadatas = []

        for doc in documents:
            doc_id = doc.get("id", "")
            title = doc.get("title", "")
            abstract = doc.get("abstract", "")
            text = f"{title}. {abstract}" if abstract else title

            if not text.strip():
                continue

            ids.append(doc_id)
            texts.append(text)
            metadatas.append({
                "source_db": doc.get("source_db", ""),
                "year": doc.get("year", ""),
                "keywords": doc.get("keywords", "[]"),
                "title": title[:200],  # Truncate for metadata size limits
            })

        if not ids:
            return

        # Add in batches of 100 to avoid size limits
        batch_size = 100
        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i:i + batch_size]
            batch_texts = texts[i:i + batch_size]
            batch_metadatas = metadatas[i:i + batch_size]

            try:
                self._collection.upsert(
                    ids=batch_ids,
                    documents=batch_texts,
                    metadatas=batch_metadatas,
                )
            except Exception as e:
                logger.error(f"Failed to add document batch {i // batch_size}: {e}")

        logger.info(f"Added/updated {len(ids)} documents in vector collection")

    def search(
        self, query: str, top_k: int = 5, filters: Optional[dict] = None
    ) -> list[dict]:
        """Semantic search for relevant papers.

        Returns list of dicts with: id, document (text), metadata, distance
        """
        if not self.is_ready:
            return []

        try:
            kwargs = {
                "query_texts": [query],
                "n_results": min(top_k, self._collection.count()) if self._collection.count() > 0 else 1,
            }
            if filters:
                where_clauses = []
                for key, value in filters.items():
                    where_clauses.append({key: value})
                if len(where_clauses) == 1:
                    kwargs["where"] = where_clauses[0]
                elif len(where_clauses) > 1:
                    kwargs["where"] = {"$and": where_clauses}

            results = self._collection.query(**kwargs)

            if not results["ids"] or not results["ids"][0]:
                return []

            output = []
            for i, doc_id in enumerate(results["ids"][0]):
                output.append({
                    "id": doc_id,
                    "document": results["documents"][0][i] if results["documents"] else "",
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else None,
                })
            return output
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    def get_collection_stats(self) -> dict:
        """Return statistics about the vector collection."""
        if not self.is_ready:
            return {"count": 0, "ready": False}

        return {
            "count": self._collection.count(),
            "ready": True,
            "collection_name": self.COLLECTION_NAME,
        }

    def rebuild_from_db(self, db_service) -> int:
        """Rebuild the entire vector index from the SQLite database.

        Returns the number of documents indexed.
        """
        if not self.is_ready:
            return 0

        # Delete existing collection and recreate
        try:
            self._client.delete_collection(self.COLLECTION_NAME)
        except Exception:
            pass

        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

        # Fetch all resources from SQLite
        resources = db_service.get_all_resources_for_index()
        if not resources:
            logger.info("No resources to index")
            return 0

        self.add_documents(resources)
        logger.info(f"Rebuilt vector index with {len(resources)} documents")
        return len(resources)

    def delete_by_ids(self, ids: list[str]):
        """Delete documents by their IDs."""
        if not self.is_ready or not ids:
            return
        try:
            self._collection.delete(ids=ids)
        except Exception as e:
            logger.error(f"Failed to delete documents: {e}")


# Singleton instance
_vector_service: Optional[VectorService] = None


def get_vector_service() -> VectorService:
    global _vector_service
    if _vector_service is None:
        _vector_service = VectorService()
        _vector_service.init()
    return _vector_service
