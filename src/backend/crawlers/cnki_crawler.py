"""CNKI crawler adapter — reuses CNKIService search logic."""

import logging
from typing import Optional

from .base import BaseCrawler

logger = logging.getLogger(__name__)

# Default hot keywords for CNKI crawling
DEFAULT_HOT_KEYWORDS = [
    "人工智能", "深度学习", "大语言模型", "数字化转型",
    "乡村振兴", "碳中和", "新质生产力", "数字经济",
    "社会治理", "心理健康", "教育改革", "气候变化",
]


class CNKICrawler(BaseCrawler):
    """CNKI crawler that reuses the existing CNKIService for search."""

    source_db = "cnki"
    rate_limit = 3.0

    def __init__(self, cnki_service=None):
        self._cnki_service = cnki_service

    async def _get_service(self):
        if self._cnki_service is None:
            from ..services.cnki_service import CNKIService
            self._cnki_service = CNKIService()
        return self._cnki_service

    async def crawl_hot(self, count: int = 50) -> list[dict]:
        """Crawl hot papers by searching popular keywords."""
        service = await self._get_service()
        all_results = []
        keywords = DEFAULT_HOT_KEYWORDS

        for kw in keywords:
            if len(all_results) >= count:
                break
            try:
                results = await self.run_with_rate_limit(
                    service.search, query=kw, count=min(10, count - len(all_results))
                )
                for r in results:
                    all_results.append({
                        "title": r.title,
                        "authors": r.author,
                        "year": r.year,
                        "source": r.source,
                        "abstract": r.abstract,
                        "doi": r.doi,
                        "citations": r.citations,
                        "is_core": r.core,
                        "url": f"https://kns.cnki.net/kcms2/article/abstract?v={r.doi}" if r.doi else "",
                    })
            except Exception as e:
                logger.warning(f"[cnki] Failed to search keyword '{kw}': {e}")
                continue

        return self.normalize_batch(all_results[:count])

    async def crawl_latest(self, count: int = 100) -> list[dict]:
        """Crawl latest papers — CNKI doesn't have a direct 'latest' API,
        so we search by current year keywords."""
        service = await self._get_service()
        from datetime import datetime
        current_year = str(datetime.now().year)
        all_results = []

        for kw in DEFAULT_HOT_KEYWORDS[:5]:
            if len(all_results) >= count:
                break
            try:
                results = await self.run_with_rate_limit(
                    service.search, query=kw, year_filter=current_year,
                    count=min(20, count - len(all_results))
                )
                for r in results:
                    all_results.append({
                        "title": r.title,
                        "authors": r.author,
                        "year": r.year,
                        "source": r.source,
                        "abstract": r.abstract,
                        "doi": r.doi,
                        "citations": r.citations,
                        "is_core": r.core,
                    })
            except Exception as e:
                logger.warning(f"[cnki] Failed to search latest for '{kw}': {e}")
                continue

        return self.normalize_batch(all_results[:count])

    async def crawl_by_keyword(self, keyword: str, count: int = 20) -> list[dict]:
        """Crawl papers by a specific keyword."""
        service = await self._get_service()
        try:
            results = await self.run_with_rate_limit(
                service.search, query=keyword, count=count
            )
            raw = [{
                "title": r.title,
                "authors": r.author,
                "year": r.year,
                "source": r.source,
                "abstract": r.abstract,
                "doi": r.doi,
                "citations": r.citations,
                "is_core": r.core,
            } for r in results]
            return self.normalize_batch(raw)
        except Exception as e:
            logger.error(f"[cnki] Keyword search failed for '{keyword}': {e}")
            return []
