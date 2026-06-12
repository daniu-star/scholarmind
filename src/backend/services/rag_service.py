"""RAG (Retrieval-Augmented Generation) service for semantic search and context injection."""

import logging
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)


class RAGService:
    """RAG service that combines vector search with context assembly for Agent injection."""

    def __init__(self, vector_service=None, db_service=None):
        self._vector_service = vector_service
        self._db_service = db_service

    def _get_vector_service(self):
        if self._vector_service is None:
            from .vector_service import get_vector_service
            self._vector_service = get_vector_service()
        return self._vector_service

    def _get_db_service(self):
        if self._db_service is None:
            from .db_service import get_db_service
            self._db_service = get_db_service()
        return self._db_service

    def search(
        self, query: str, top_k: int = 5, filters: Optional[dict] = None
    ) -> list[dict]:
        """Semantic search for relevant academic papers.

        Returns list of dicts with: id, title, authors, year, source, abstract, etc.
        """
        vector = self._get_vector_service()
        if not vector.is_ready:
            logger.warning("Vector service not ready, falling back to keyword search")
            return self._keyword_search(query, top_k)

        # Vector search
        results = vector.search(query, top_k=top_k, filters=filters)
        if not results:
            return self._keyword_search(query, top_k)

        # Enrich with full metadata from database
        db = self._get_db_service()
        enriched = []
        for r in results:
            doc_id = r.get("id", "")
            metadata = r.get("metadata", {})
            # Try to get full record from DB
            db_results = db.search_resources(metadata.get("title", ""), limit=1)
            if db_results:
                enriched.append(db_results[0])
            else:
                # Use vector search result as fallback
                enriched.append({
                    "id": doc_id,
                    "title": metadata.get("title", ""),
                    "source_db": metadata.get("source_db", ""),
                    "year": metadata.get("year", ""),
                    "abstract": r.get("document", ""),
                    "keywords": metadata.get("keywords", "[]"),
                })

        return enriched

    def _keyword_search(self, query: str, limit: int) -> list[dict]:
        """Fallback keyword search using SQLite LIKE."""
        db = self._get_db_service()
        return db.search_resources(query, limit=limit)

    def build_context(
        self, query: str, agent_id: Optional[str] = None, top_k: int = 5
    ) -> str:
        """Assemble RAG context string for Agent system prompt injection.

        Returns a formatted string with relevant academic papers,
        or empty string if no results found.
        """
        try:
            results = self.search(query, top_k=top_k)
        except Exception as e:
            logger.error(f"RAG search failed: {e}")
            return ""

        if not results:
            return ""

        import json
        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "无标题")
            authors = r.get("authors", "")
            year = r.get("year", "")
            source = r.get("source", "")
            citations = r.get("citations", 0)
            abstract = r.get("abstract", "")
            source_db = r.get("source_db", "")

            # Format: 1. [Title] (Authors, Year, Source) — Citations: N
            line = f"{i}. [{title}]"
            meta_parts = []
            if authors:
                meta_parts.append(authors[:50])
            if year:
                meta_parts.append(year)
            if source:
                meta_parts.append(source[:30])
            if meta_parts:
                line += f" ({', '.join(meta_parts)})"
            if citations:
                line += f" — 引用数: {citations}"
            line += f" [{source_db}]"

            lines.append(line)

            # Add abstract (truncated)
            if abstract:
                lines.append(f"   摘要：{abstract[:200]}{'...' if len(abstract) > 200 else ''}")

        return "\n".join(lines)

    def rebuild_index(self) -> int:
        """Rebuild the entire vector index from the database.

        Returns the number of documents indexed.
        """
        vector = self._get_vector_service()
        db = self._get_db_service()
        return vector.rebuild_from_db(db)

    def get_stats(self) -> dict:
        """Return statistics about the RAG system."""
        vector = self._get_vector_service()
        db = self._get_db_service()

        vector_stats = vector.get_collection_stats()
        db_count = db.get_resource_count()

        return {
            "vector_ready": vector_stats.get("ready", False),
            "vector_count": vector_stats.get("count", 0),
            "db_count": db_count,
            "embedding_model": settings.RAG_EMBEDDING_MODEL,
            "top_k": settings.RAG_TOP_K,
        }


# Singleton instance
_rag_service: Optional[RAGService] = None


def get_rag_service() -> RAGService:
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service
