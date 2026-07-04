"""Lightweight CNKI search executor using Playwright + anti-detection.

Designed to be called from the Master API as a search service for the
ScholarMind backend. Reuses the full anti-anti-crawl stack (fingerprint
randomization, behavior simulation, CAPTCHA bypass, TLS client) but in
a lightweight, one-shot manner — no Redis/worker pipeline needed.
"""

from __future__ import annotations

import asyncio
import random
import structlog
import time
from typing import Optional, TYPE_CHECKING
from urllib.parse import urlencode

from crawler.cnki_navigator import CNKINavigator
from config.settings import settings

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = structlog.get_logger()


class SearchExecutor:
    """Perform CNKI searches using Playwright with full anti-detection.

    Intended for use by:
    - master/app.py  POST /search endpoint
    - Standalone search scripts
    - Backend integration via HTTP

    Each search call:
    1. Gets a fresh browser page from the pool
    2. Applies fingerprint randomization
    3. Navigates to CNKI search with CAPTCHA handling
    4. Extracts results via page.evaluate()
    5. Returns structured data
    """

    def __init__(self):
        self._search_count = 0
        self._success_count = 0
        self._captcha_count = 0
        self._last_search_time = 0.0

    async def search(
        self,
        query: str,
        year_filter: str = "",
        count: int = 20,
        timeout: int = 30,
    ) -> dict:
        """Execute a CNKI search and return structured results.

        Returns:
            {
                "success": True/False,
                "query": str,
                "count": int,
                "results": [{"title", "author", "year", "source", "citations", "abstract", "doi"}],
                "error": str (if failed),
                "source": "playwright",
            }
        """
        self._search_count += 1
        self._last_search_time = time.time()
        start_time = time.time()

        from anti_anti_crawl.browser_manager import get_browser_manager
        from anti_anti_crawl.fingerprint_engine import fingerprint_engine
        from anti_anti_crawl.behavior_simulator import behavior_simulator
        from anti_anti_crawl.captcha_bypass import captcha_bypass
        from anti_anti_crawl.rhythm_detector import rhythm_detector

        bm = get_browser_manager()
        page: Optional[Page] = None

        try:
            page = await bm.new_page()

            # Apply fingerprint randomization
            await fingerprint_engine.randomize_all(page)

            # Build search URL
            search_url = self._build_search_url(query, year_filter)
            logger.info("search_executor_starting", query=query[:50], url=search_url[:80])

            # Navigate with anti-detection
            navigated = await CNKINavigator.safe_navigate(
                page,
                search_url,
                wait_selector=".result-table-list, [class*='result'], table",
                timeout=timeout * 1000,
            )

            if not navigated:
                # Check for CAPTCHA
                if await CNKINavigator.check_for_captcha(page):
                    self._captcha_count += 1
                    solved = await captcha_bypass.handle_persistent_captcha(page, max_attempts=2)
                    if solved:
                        # Retry after solve
                        await page.goto(search_url, wait_until="domcontentloaded")
                        await CNKINavigator.wait_for_cnki_render(
                            page, ".result-table-list, [class*='result']"
                        )
                        await CNKINavigator.dismiss_overlays(page)
                    else:
                        return self._fail_result(query, "CAPTCHA unsolvable")

                # Check rhythm state
                if rhythm_detector.current_state == "blocked":
                    return self._fail_result(query, "Blocked by CNKI (rate limit)")

            # Dismiss any overlays that appeared
            await CNKINavigator.dismiss_overlays(page)

            # Simulate brief human reading behavior before extracting
            await behavior_simulator.human_scroll(page, random.randint(200, 500))
            await asyncio.sleep(random.uniform(0.5, 1.5))

            # Extract results
            results = await self._extract_search_results(page, count)

            elapsed = time.time() - start_time
            self._success_count += 1
            logger.info(
                "search_executor_success",
                query=query[:50],
                result_count=len(results),
                elapsed_seconds=round(elapsed, 1),
            )

            return {
                "success": True,
                "query": query,
                "count": len(results),
                "results": results,
                "source": "playwright",
                "elapsed_seconds": round(elapsed, 1),
            }

        except Exception as e:
            logger.error("search_executor_failed", query=query[:50], error=str(e))
            return self._fail_result(query, str(e))
        finally:
            if page is not None:
                try:
                    await bm.close_page(page)
                except Exception:
                    pass

    def _build_search_url(self, query: str, year_filter: str = "") -> str:
        """Build CNKI search URL with query parameters."""
        params = {
            "classid": "WD0FTY92",
            "korder": "SU",
            "kw": query,
            "crossDbcodes": "CJFQ,CJRF,CDMD,CIPD,CCND,BDZK,CISD,SNAD,CCJD,GXDB_SECTION,CJFN",
        }
        if year_filter:
            if "-" in year_filter:
                start, end = year_filter.split("-", 1)
                params["publishdate_from"] = start
                params["publishdate_to"] = end
            else:
                params["publishdate_from"] = year_filter
                params["publishdate_to"] = year_filter
        return f"{settings.CNKI_BASE_URL}/kns8s/search?{urlencode(params)}"

    @staticmethod
    async def _extract_search_results(page: "Page", count: int) -> list[dict]:
        """Extract search results from CNKI's React-rendered page.

        Uses a multi-strategy approach to handle CNKI's changing UI:
        1. Standard table rows (result-table-list)
        2. Generic result containers
        3. Any link-based fallback
        """
        return await page.evaluate(
            """(maxCount) => {
            const results = [];

            // Strategy 1: Standard CNKI result table rows
            const rows = document.querySelectorAll('tr.result-table-list, tr[class*="result"]');
            for (const row of rows) {
                if (results.length >= maxCount) break;

                const titleEl = row.querySelector('a.fz14, td.name a, td[class*="name"] a');
                const authorEl = row.querySelector('td.author, td[class*="author"]');
                const sourceEl = row.querySelector('td.source, td[class*="source"]');
                const dateEl = row.querySelector('td.date, td[class*="date"]');
                const citeEl = row.querySelector('td.cite, td[class*="cite"]');

                if (titleEl) {
                    const title = (titleEl.textContent || '').trim();
                    if (title.length > 3) {
                        results.push({
                            title: title,
                            author: authorEl ? authorEl.textContent.trim() : '',
                            source: sourceEl ? sourceEl.textContent.trim() : '',
                            year: dateEl ? (dateEl.textContent.match(/\d{4}/) || [''])[0] : '',
                            citations: citeEl ? (parseInt(citeEl.textContent) || 0) : 0,
                            abstract: '',
                            doi: '',
                            url: titleEl.href || '',
                        });
                    }
                }
            }

            // Strategy 2: If no table rows found, try generic result cards
            if (results.length === 0) {
                const cards = document.querySelectorAll(
                    '[class*="result-item"], [class*="search-item"], li[class*="paper"]'
                );
                for (const card of cards) {
                    if (results.length >= maxCount) break;
                    const titleEl = card.querySelector('a[href*="detail"], a[href*="abstract"]');
                    if (titleEl) {
                        const title = (titleEl.textContent || '').trim();
                        if (title.length > 3) {
                            results.push({
                                title: title,
                                author: '',
                                source: '',
                                year: '',
                                citations: 0,
                                abstract: '',
                                doi: '',
                                url: titleEl.href || '',
                            });
                        }
                    }
                }
            }

            // Strategy 3: Desperate fallback — any link that looks like a paper title
            if (results.length === 0) {
                const links = document.querySelectorAll(
                    'a[href*="article"], a[href*="abstract"], a[href*="detail"]'
                );
                for (const link of links) {
                    if (results.length >= maxCount) break;
                    const text = (link.textContent || '').trim();
                    if (text.length > 10 && text.length < 300) {
                        results.push({
                            title: text,
                            author: '',
                            source: '',
                            year: '',
                            citations: 0,
                            abstract: '',
                            doi: '',
                            url: link.href || '',
                        });
                    }
                }
            }

            return results;
        }""",
            count,
        )

    @staticmethod
    def _fail_result(query: str, error: str) -> dict:
        return {
            "success": False,
            "query": query,
            "count": 0,
            "results": [],
            "source": "playwright",
            "error": error,
        }

    @property
    def stats(self) -> dict:
        return {
            "total_searches": self._search_count,
            "successful_searches": self._success_count,
            "captcha_encounters": self._captcha_count,
            "success_rate": (
                self._success_count / max(self._search_count, 1)
            ),
            "last_search_time": self._last_search_time,
        }


# Global singleton
search_executor = SearchExecutor()
