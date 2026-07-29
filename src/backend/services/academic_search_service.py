"""多源学术搜索聚合服务

统一管理 CNKI / Semantic Scholar / arXiv / CrossRef / PubMed 5 个数据源，
并行检索 + 结果聚合 + 去重排序。

从 cnki_service.py 拆分出独立文件（原 1248 行 → 762 行 + 本文件 466 行）。
"""

from __future__ import annotations

import asyncio
import structlog
import time
from datetime import datetime
from typing import Any, Optional, TYPE_CHECKING

from ..utils.cache import CacheManager

if TYPE_CHECKING:
    from .cnki_service import CNKIService, CNKIResult
    from .semantic_scholar_service import SemanticScholarService
    from .arxiv_service import ArxivService

logger = structlog.get_logger(__name__)


class AcademicSearchService:
    """多源学术搜索聚合服务

    统一管理 CNKI / Semantic Scholar / arXiv / CrossRef / PubMed 5 个数据源，
    并行检索 + 结果聚合 + 去重排序。
    """

    # 全部数据源列表
    ALL_SOURCES = ["cnki", "semantic_scholar", "arxiv", "crossref", "pubmed"]

    def __init__(
        self,
        cnki_service: Optional[CNKIService] = None,
        semantic_scholar_service: Optional[SemanticScholarService] = None,
        arxiv_service: Optional[ArxivService] = None,
        cache_ttl: int = 1800,
        max_concurrent: int = 5,
        timeout: int = 15,
    ) -> None:
        """初始化多源学术搜索聚合服务

        Args:
            cnki_service: CNKI 服务实例（同时用于 CrossRef 和 PubMed 检索）
            semantic_scholar_service: Semantic Scholar 服务实例
            arxiv_service: arXiv 服务实例
            cache_ttl: 聚合结果缓存 TTL（秒），默认 30 分钟
            max_concurrent: 最大并发数
            timeout: 单个数据源检索超时（秒）
        """
        self.cnki_service = cnki_service
        self.semantic_scholar_service = semantic_scholar_service
        self.arxiv_service = arxiv_service
        self.cache_ttl = cache_ttl
        self.max_concurrent = max_concurrent
        self.timeout = timeout

        self._cache = CacheManager(default_ttl=cache_ttl)

    @staticmethod
    def _cache_key(query: str, count: int, source_filter: Optional[str], year_filter: str) -> str:
        return f"multi:{query}|{count}|{source_filter}|{year_filter}"

    # ── CNKIResult 转换 ────────────────────────────────────

    @staticmethod
    def _convert_cnki_result(result: CNKIResult, source: str) -> dict:
        """将 CNKIResult 转换为统一 dict 格式"""
        authors: list[str] = []
        if result.author:
            authors = [a.strip() for a in result.author.split(",") if a.strip()]
            if authors and authors[-1].lower().startswith("et al"):
                authors = authors[:-1]

        year: Optional[int] = None
        if result.year:
            try:
                year = int(result.year)
            except ValueError:
                year = None

        url = f"https://doi.org/{result.doi}" if result.doi else ""

        return {
            "title": result.title,
            "authors": authors,
            "year": year,
            "abstract": result.abstract if result.abstract else None,
            "citation_count": result.citations,
            "url": url,
            "source": source,
            "doi": result.doi if result.doi else None,
            "pdf_url": None,
        }

    # ── 单源检索方法 ────────────────────────────────────────

    async def _search_cnki(self, query: str, count: int, year_filter: str) -> tuple[list[dict], str]:
        """通过 CNKI 服务检索"""
        if not self.cnki_service:
            return [], "CNKI 服务未配置"
        try:
            results = await asyncio.wait_for(
                self.cnki_service.search(query, year_filter, count),
                timeout=self.timeout,
            )
            return [self._convert_cnki_result(r, "cnki") for r in results], ""
        except asyncio.TimeoutError:
            return [], f"CNKI 检索超时（{self.timeout}s）"
        except Exception as e:
            return [], f"CNKI 检索失败: {e}"

    async def _search_semantic_scholar(self, query: str, count: int) -> tuple[list[dict], str]:
        if not self.semantic_scholar_service:
            return [], "Semantic Scholar 服务未配置"
        try:
            papers = await asyncio.wait_for(
                self.semantic_scholar_service.search(query, count),
                timeout=self.timeout,
            )
            return [p.to_dict() for p in papers], ""
        except asyncio.TimeoutError:
            return [], f"Semantic Scholar 检索超时（{self.timeout}s）"
        except Exception as e:
            return [], f"Semantic Scholar 检索失败: {e}"

    async def _search_arxiv(self, query: str, count: int) -> tuple[list[dict], str]:
        if not self.arxiv_service:
            return [], "arXiv 服务未配置"
        try:
            papers = await asyncio.wait_for(
                self.arxiv_service.search(query, count),
                timeout=self.timeout,
            )
            return [p.to_dict() for p in papers], ""
        except asyncio.TimeoutError:
            return [], f"arXiv 检索超时（{self.timeout}s）"
        except Exception as e:
            return [], f"arXiv 检索失败: {e}"

    async def _search_crossref(self, query: str, count: int, year_filter: str) -> tuple[list[dict], str]:
        if not self.cnki_service:
            return [], "CrossRef 检索不可用（CNKI 服务未配置）"
        try:
            results = await asyncio.wait_for(
                self.cnki_service.search_crossref(query, count, year_filter),
                timeout=self.timeout,
            )
            return [self._convert_cnki_result(r, "crossref") for r in results], ""
        except asyncio.TimeoutError:
            return [], f"CrossRef 检索超时（{self.timeout}s）"
        except Exception as e:
            return [], f"CrossRef 检索失败: {e}"

    async def _search_pubmed(self, query: str, count: int, year_filter: str) -> tuple[list[dict], str]:
        if not self.cnki_service:
            return [], "PubMed 检索不可用（CNKI 服务未配置）"
        try:
            results = await asyncio.wait_for(
                self.cnki_service.search_pubmed(query, count, year_filter),
                timeout=self.timeout,
            )
            return [self._convert_cnki_result(r, "pubmed") for r in results], ""
        except asyncio.TimeoutError:
            return [], f"PubMed 检索超时（{self.timeout}s）"
        except Exception as e:
            return [], f"PubMed 检索失败: {e}"

    # ── 多源聚合检索 ────────────────────────────────────────

    async def search_multi_source(
        self,
        query: str,
        count: int = 20,
        source_filter: Optional[str] = None,
        year_filter: str = "",
    ) -> dict[str, Any]:
        """并行检索多个数据源并聚合结果"""
        if not query or not query.strip():
            return {
                "success": False,
                "query": query,
                "count": 0,
                "results": [],
                "sources": {},
                "sources_tried": [],
                "error": "query 不能为空",
            }

        query = query.strip()

        # 检查缓存
        cache_key = self._cache_key(query, count, source_filter, year_filter)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info(f"多源检索缓存命中: {query}")
            return cached

        # 确定要查询的数据源
        if source_filter:
            sources = [s.strip() for s in source_filter.split(",") if s.strip() in self.ALL_SOURCES]
        else:
            sources = list(self.ALL_SOURCES)

        # 并行检索
        tasks = {}
        for source in sources:
            if source == "cnki":
                tasks[source] = self._search_cnki(query, count, year_filter)
            elif source == "semantic_scholar":
                tasks[source] = self._search_semantic_scholar(query, count)
            elif source == "arxiv":
                tasks[source] = self._search_arxiv(query, count)
            elif source == "crossref":
                tasks[source] = self._search_crossref(query, count, year_filter)
            elif source == "pubmed":
                tasks[source] = self._search_pubmed(query, count, year_filter)

        gather_results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        # 聚合结果
        all_results: list[dict] = []
        sources_status: dict[str, dict] = {}
        sources_tried: list[str] = list(tasks.keys())

        for source, result in zip(tasks.keys(), gather_results):
            if isinstance(result, Exception):
                sources_status[source] = {
                    "count": 0,
                    "error": str(result),
                }
                continue
            items, error = result
            if error:
                sources_status[source] = {
                    "count": 0,
                    "error": error,
                }
            else:
                sources_status[source] = {
                    "count": len(items),
                    "error": None,
                }
                all_results.extend(items)

        # 去重 + 排序
        all_results = self._deduplicate_and_sort(all_results)

        result_dict = {
            "success": True,
            "query": query,
            "count": len(all_results),
            "results": all_results[:count],
            "sources": sources_status,
            "sources_tried": sources_tried,
        }

        # 写入缓存
        self._cache.set(cache_key, result_dict)

        logger.info(f"多源检索完成: query={query!r}, 聚合后 {len(all_results)} 条结果")
        return result_dict

    @staticmethod
    def _deduplicate_and_sort(results: list[dict]) -> list[dict]:
        """按标题去重，按引用数降序排序"""
        sorted_results = sorted(results, key=lambda x: x.get("citation_count", 0), reverse=True)
        deduplicated: list[dict] = []
        seen_titles: list[str] = []
        for result in sorted_results:
            title = (result.get("title") or "").strip().lower()
            if not title:
                deduplicated.append(result)
                continue
            # 模糊去重
            is_dup = False
            for seen in seen_titles:
                if _title_similar(title, seen):
                    is_dup = True
                    break
            if not is_dup:
                seen_titles.append(title)
                deduplicated.append(result)
        return deduplicated

    # ── 健康检查 ────────────────────────────────────────────

    async def check_status(self) -> dict[str, Any]:
        """检查各数据源连通状态"""
        sources_status = {}
        start_time = time.time()
        # Start all probes together so the endpoint is bounded by the slowest
        # source instead of the sum of three independent timeouts.
        cnki_probe = (
            asyncio.create_task(self.cnki_service.search("test", count=1))
            if self.cnki_service
            else asyncio.create_task(asyncio.sleep(0))
        )
        semantic_probe = (
            asyncio.create_task(self.semantic_scholar_service.search("test", count=1))
            if self.semantic_scholar_service
            else None
        )
        arxiv_probe = asyncio.create_task(self.arxiv_service.search("test", count=1)) if self.arxiv_service else None

        # CNKI status
        try:
            await asyncio.wait_for(
                cnki_probe,
                timeout=5.0,
            )
            sources_status["cnki"] = {
                "status": "connected",
                "latency_ms": int((time.time() - start_time) * 1000),
                "last_check": datetime.now().isoformat(),
                "error": "",
            }
        except asyncio.TimeoutError:
            sources_status["cnki"] = {
                "status": "disconnected",
                "latency_ms": 5000,
                "last_check": datetime.now().isoformat(),
                "error": "timeout (5s)",
            }
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            sources_status["cnki"] = {
                "status": "disconnected",
                "latency_ms": latency_ms,
                "last_check": datetime.now().isoformat(),
                "error": str(e),
            }

        # Semantic Scholar status
        if self.semantic_scholar_service:
            try:
                t0 = time.time()
                await asyncio.wait_for(
                    semantic_probe,
                    timeout=5.0,
                )
                sources_status["semantic_scholar"] = {
                    "status": "connected",
                    "latency_ms": int((time.time() - t0) * 1000),
                    "last_check": datetime.now().isoformat(),
                    "error": "",
                }
            except asyncio.TimeoutError:
                sources_status["semantic_scholar"] = {
                    "status": "disconnected",
                    "latency_ms": 5000,
                    "last_check": datetime.now().isoformat(),
                    "error": "timeout (5s)",
                }
            except Exception as e:
                sources_status["semantic_scholar"] = {
                    "status": "disconnected",
                    "latency_ms": int((time.time() - t0) * 1000),
                    "last_check": datetime.now().isoformat(),
                    "error": str(e),
                }
        else:
            sources_status["semantic_scholar"] = {
                "status": "not_configured",
                "latency_ms": 0,
                "last_check": datetime.now().isoformat(),
                "error": "service not configured",
            }

        # arXiv status
        if self.arxiv_service:
            try:
                t0 = time.time()
                await asyncio.wait_for(
                    arxiv_probe,
                    timeout=5.0,
                )
                sources_status["arxiv"] = {
                    "status": "connected",
                    "latency_ms": int((time.time() - t0) * 1000),
                    "last_check": datetime.now().isoformat(),
                    "error": "",
                }
            except asyncio.TimeoutError:
                sources_status["arxiv"] = {
                    "status": "disconnected",
                    "latency_ms": 5000,
                    "last_check": datetime.now().isoformat(),
                    "error": "timeout (5s)",
                }
            except Exception as e:
                sources_status["arxiv"] = {
                    "status": "disconnected",
                    "latency_ms": int((time.time() - t0) * 1000),
                    "last_check": datetime.now().isoformat(),
                    "error": str(e),
                }
        else:
            sources_status["arxiv"] = {
                "status": "not_configured",
                "latency_ms": 0,
                "last_check": datetime.now().isoformat(),
                "error": "service not configured",
            }

        # 其他数据源（跨源通过 CNKI 服务）
        for src in ["crossref", "pubmed"]:
            sources_status[src] = {
                "status": "connected" if self.cnki_service else "not_configured",
                "latency_ms": 0,
                "last_check": datetime.now().isoformat(),
                "error": "" if self.cnki_service else "CNKI service not configured",
            }

        return {
            "status": "ok",
            "sources": sources_status,
            "timestamp": datetime.now().isoformat(),
        }

    # ── 资源清理 ────────────────────────────────────────────

    async def close(self) -> None:
        """关闭底层服务的资源"""
        if self.cnki_service is not None:
            await self.cnki_service.close()
        if self.semantic_scholar_service is not None:
            await self.semantic_scholar_service.close()
        if self.arxiv_service is not None:
            await self.arxiv_service.close()


def _title_similar(t1: str, t2: str, threshold: float = 0.85) -> bool:
    """检查两个标题是否相似（基于子串匹配）"""
    if t1 == t2:
        return True
    if len(t1) < 10 or len(t2) < 10:
        return False
    # 简单 Jaccard 相似度
    words1 = set(t1.split())
    words2 = set(t2.split())
    if not words1 or not words2:
        return False
    intersection = words1 & words2
    union = words1 | words2
    return len(intersection) / len(union) > threshold
