"""Wanfang (万方) crawler adapter — HTTP + HTML parsing."""

import logging
import re

import aiohttp
from bs4 import BeautifulSoup

from .base import BaseCrawler
from ..config import settings

logger = logging.getLogger(__name__)


class WanfangCrawler(BaseCrawler):
    """Wanfang Data crawler using HTTP requests and HTML parsing."""

    source_db = "wanfang"
    rate_limit = 3.0

    SEARCH_URL = "https://s.wanfangdata.com.cn/paper"

    async def _search(self, keyword: str, count: int = 20) -> list[dict]:
        """Search Wanfang and parse results."""
        headers = {
            "User-Agent": self.get_random_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        params = {
            "q": keyword,
            "s": "50",  # sort by relevance
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(self.SEARCH_URL, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"[wanfang] Search returned status {resp.status}")
                    return []
                html = await resp.text()

        return self._parse_search_results(html)

    def _parse_search_results(self, html: str) -> list[dict]:
        """Parse Wanfang search results HTML."""
        results = []
        try:
            soup = BeautifulSoup(html, "lxml")
            items = soup.select(".normal-list, .result-item, .paper-item")

            for item in items:
                title_el = item.select_one("a.title, .title a, h3 a")
                title = title_el.get_text(strip=True) if title_el else ""
                url = title_el.get("href", "") if title_el else ""
                if url and not url.startswith("http"):
                    url = settings.WANFANG_BASE_URL + url

                author_el = item.select_one(".author, .authors")
                authors = author_el.get_text(strip=True) if author_el else ""

                source_el = item.select_one(".source, .journal")
                source = source_el.get_text(strip=True) if source_el else ""

                year = ""
                date_el = item.select_one(".date, .year, .pub-date")
                if date_el:
                    year_match = re.search(r"\d{4}", date_el.get_text())
                    if year_match:
                        year = year_match.group()

                abstract_el = item.select_one(".abstract, .summary")
                abstract = abstract_el.get_text(strip=True)[:500] if abstract_el else ""

                if title:
                    results.append({
                        "title": title,
                        "authors": authors,
                        "year": year,
                        "source": source,
                        "abstract": abstract,
                        "doi": "",
                        "citations": 0,
                        "is_core": False,
                        "keywords": [],
                        "url": url,
                    })
        except Exception as e:
            logger.error(f"[wanfang] HTML parse error: {e}")

        return results

    async def crawl_hot(self, count: int = 50) -> list[dict]:
        """Crawl hot papers by searching popular keywords."""
        hot_keywords = ["人工智能", "深度学习", "大数据", "乡村振兴", "数字经济"]
        all_results = []

        for kw in hot_keywords:
            if len(all_results) >= count:
                break
            try:
                results = await self.run_with_rate_limit(
                    self._search, keyword=kw, count=min(10, count - len(all_results))
                )
                all_results.extend(results)
            except Exception as e:
                logger.warning(f"[wanfang] Failed to search '{kw}': {e}")
                continue

        return self.normalize_batch(all_results[:count])

    async def crawl_latest(self, count: int = 100) -> list[dict]:
        """Crawl latest papers — search with current year filter."""
        from datetime import datetime
        current_year = str(datetime.now().year)
        hot_keywords = ["人工智能", "机器学习", "数字经济", "新质生产力"]
        all_results = []

        for kw in hot_keywords:
            if len(all_results) >= count:
                break
            try:
                results = await self.run_with_rate_limit(
                    self._search, keyword=f"{kw} {current_year}",
                    count=min(25, count - len(all_results))
                )
                all_results.extend(results)
            except Exception as e:
                logger.warning(f"[wanfang] Failed to search latest for '{kw}': {e}")
                continue

        return self.normalize_batch(all_results[:count])

    async def crawl_by_keyword(self, keyword: str, count: int = 20) -> list[dict]:
        """Crawl papers by keyword."""
        try:
            results = await self.run_with_rate_limit(
                self._search, keyword=keyword, count=count
            )
            return self.normalize_batch(results)
        except Exception as e:
            logger.error(f"[wanfang] crawl_by_keyword failed for '{keyword}': {e}")
            return []
