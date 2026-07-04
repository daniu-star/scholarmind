"""CrossRef crawler adapter — uses public REST API."""

import structlog
from datetime import datetime, timedelta

import aiohttp

from .base import BaseCrawler
from ..config import settings

logger = structlog.get_logger(__name__)


class CrossRefCrawler(BaseCrawler):
    """CrossRef crawler using the public REST API."""

    source_db = "crossref"
    rate_limit = 1.0

    API_BASE = "https://api.crossref.org/works"

    async def _fetch(self, params: dict) -> list[dict]:
        """Fetch results from CrossRef API."""
        headers = {
            "User-Agent": f"ScholarMind/1.0 (mailto:support@scholarmind.ai)",
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(self.API_BASE, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"[crossref] API returned status {resp.status}")
                    return []
                data = await resp.json()
                items = data.get("message", {}).get("items", [])
                return items

    def _parse_item(self, item: dict) -> dict:
        """Parse a CrossRef API item into standard format."""
        title_list = item.get("title", [])
        title = title_list[0] if title_list else ""

        authors_list = item.get("author", [])
        authors = ", ".join(
            f"{a.get('given', '')} {a.get('family', '')}".strip()
            for a in authors_list
        )

        year = ""
        pub_date = item.get("published-print", {}).get("date-parts", [[]])
        if pub_date and pub_date[0]:
            year = str(pub_date[0][0])
        if not year:
            pub_date = item.get("published-online", {}).get("date-parts", [[]])
            if pub_date and pub_date[0]:
                year = str(pub_date[0][0])

        container = item.get("container-title", [])
        source = container[0] if container else ""

        abstract = item.get("abstract", "")
        # Remove HTML tags from abstract
        if abstract:
            import re
            abstract = re.sub(r"<[^>]+>", "", abstract)

        doi = item.get("DOI", "")
        citations = item.get("is-referenced-by-count", 0)
        keywords_list = item.get("subject", [])

        return {
            "title": title,
            "authors": authors,
            "year": year,
            "source": source,
            "abstract": abstract[:1000] if abstract else "",
            "doi": doi,
            "citations": citations,
            "is_core": False,
            "keywords": keywords_list,
            "url": f"https://doi.org/{doi}" if doi else "",
        }

    async def crawl_hot(self, count: int = 50) -> list[dict]:
        """Crawl hot papers sorted by citation count."""
        params = {
            "sort": "is-referenced-by-count",
            "order": "desc",
            "rows": min(count, 100),
            "filter": "from-pub-date:2023",
        }
        try:
            items = await self.run_with_rate_limit(self._fetch, params)
            raw = [self._parse_item(item) for item in items]
            return self.normalize_batch(raw)
        except Exception as e:
            logger.error(f"[crossref] crawl_hot failed: {e}")
            return []

    async def crawl_latest(self, count: int = 100) -> list[dict]:
        """Crawl latest papers sorted by publication date."""
        recent = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        params = {
            "sort": "published",
            "order": "desc",
            "rows": min(count, 100),
            "filter": f"from-pub-date:{recent}",
        }
        try:
            items = await self.run_with_rate_limit(self._fetch, params)
            raw = [self._parse_item(item) for item in items]
            return self.normalize_batch(raw)
        except Exception as e:
            logger.error(f"[crossref] crawl_latest failed: {e}")
            return []

    async def crawl_by_keyword(self, keyword: str, count: int = 20) -> list[dict]:
        """Crawl papers by keyword query."""
        params = {
            "query": keyword,
            "sort": "score",
            "order": "desc",
            "rows": min(count, 100),
        }
        try:
            items = await self.run_with_rate_limit(self._fetch, params)
            raw = [self._parse_item(item) for item in items]
            return self.normalize_batch(raw)
        except Exception as e:
            logger.error(f"[crossref] crawl_by_keyword failed for '{keyword}': {e}")
            return []
