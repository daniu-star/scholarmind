"""RAG (Retrieval-Augmented Generation) service for semantic search and context injection."""

import structlog
from typing import Optional

from ..config import settings

logger = structlog.get_logger(__name__)


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
    ) -> dict:
        """语义检索相关学术资源。

        Returns:
            dict 包含以下字段:
                - results: list[dict]，每条含 id, title, authors, year, source, abstract 等
                - degraded: bool，是否降级为关键词搜索
                - reason: str，降级原因（未降级时为空字符串）
        """
        vector = self._get_vector_service()
        if not vector.is_ready:
            logger.warning("向量服务未就绪，降级到关键词搜索")
            results = self._keyword_search(query, top_k)
            return {
                "results": results,
                "degraded": True,
                "reason": "vector_service_not_ready",
            }

        # 向量检索
        results = vector.search(query, top_k=top_k, filters=filters)
        if not results:
            logger.warning("向量检索无结果，降级到关键词搜索")
            results = self._keyword_search(query, top_k)
            return {
                "results": results,
                "degraded": True,
                "reason": "vector_search_no_results",
            }

        # 批量从数据库补全元数据（避免 N+1 查询）
        db = self._get_db_service()
        enriched = self._batch_enrich_results(db, results)

        return {
            "results": enriched,
            "degraded": False,
            "reason": "",
        }

    def _batch_enrich_results(
        self, db, vector_results: list[dict]
    ) -> list[dict]:
        """批量从数据库补全向量搜索结果的元数据（避免 N+1 查询）。

        收集所有 title 后一次性查询数据库，替代逐条 search_resources 调用。
        """
        # 收集所有非空 title
        titles = [
            r.get("metadata", {}).get("title", "")
            for r in vector_results
            if r.get("metadata", {}).get("title", "")
        ]

        # 批量查询数据库（单次查询替代 N 次 search_resources 调用）
        if titles and hasattr(db, "search_resources_by_titles"):
            db_records = db.search_resources_by_titles(titles, limit=len(titles) * 2)
        else:
            # TODO 优化: db_service 暂无 batch 方法时回退到逐条查询
            db_records = []
            for title in titles:
                db_records.extend(db.search_resources(title, limit=1))

        # 构建 title → record 映射（优先匹配引用数最高的记录，已按 citations DESC 排序）
        title_to_record: dict[str, dict] = {}
        for rec in db_records:
            rec_title = rec.get("title", "")
            for vt in titles:
                if vt and (vt in rec_title or rec_title in vt):
                    if vt not in title_to_record:
                        title_to_record[vt] = rec
                    break

        # 组装结果
        enriched = []
        for r in vector_results:
            doc_id = r.get("id", "")
            metadata = r.get("metadata", {})
            title = metadata.get("title", "")
            if title and title in title_to_record:
                enriched.append(title_to_record[title])
            else:
                # 向量搜索结果作为回退
                enriched.append({
                    "id": doc_id,
                    "title": title,
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
    ) -> dict:
        """组装 RAG 上下文字符串，供 Agent 系统提示词注入。

        Returns:
            dict 包含以下字段:
                - context: str，格式化的学术资源上下文（无结果时为空字符串）
                - degraded: bool，是否降级为关键词搜索
                - reason: str，降级原因（未降级时为空字符串）
        """
        try:
            search_result = self.search(query, top_k=top_k)
        except Exception as e:
            logger.error(f"RAG search failed: {e}")
            return {"context": "", "degraded": False, "reason": ""}

        results = search_result.get("results", [])
        degraded = search_result.get("degraded", False)
        reason = search_result.get("reason", "")

        if not results:
            return {"context": "", "degraded": degraded, "reason": reason}

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

        return {
            "context": "\n".join(lines),
            "degraded": degraded,
            "reason": reason,
        }

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
