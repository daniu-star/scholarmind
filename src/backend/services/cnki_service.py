from __future__ import annotations

import aiohttp
import asyncio
import difflib
import re
import json
import structlog
import random
import time
from datetime import datetime
from typing import Optional, TYPE_CHECKING, Any
from dataclasses import dataclass, asdict
from urllib.parse import quote

from ..config import settings

if TYPE_CHECKING:
    from ..utils.cache import CacheManager
    from ..utils.circuit_breaker import CircuitBreaker
    from .semantic_scholar_service import SemanticScholarService
    from .arxiv_service import ArxivService

logger = structlog.get_logger(__name__)


@dataclass
class CNKIResult:
    title: str
    author: str
    year: str
    source: str  # 期刊名称
    citations: int
    core: bool  # 是否核心期刊
    abstract: str
    doi: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class CNKIService:
    """CNKI academic search service with MCP tool integration and caching"""

    def __init__(
        self,
        cache: CacheManager | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        self.base_url = "https://kns.cnki.net"
        self.search_url = "https://kns.cnki.net/kns8s/search"
        self.bright_data_proxy: Optional[str] = None
        self.cnki_api_key: Optional[str] = None
        self.session: Optional[aiohttp.ClientSession] = None

        # 缓存：注入外部 CacheManager 或使用内置缓存
        self.cache = cache
        self._internal_cache: dict[str, tuple[list[CNKIResult], float]] = {}
        self._cache_ttl = 1800  # 30 分钟缓存

        # 熔断器
        self.circuit_breaker = circuit_breaker

        # MCP 工具配置
        self.mcp_tools: dict[str, dict] = {}
        self.mcp_enabled = False

        # 速率限制
        self._last_request_time: float = 0.0
        self._min_interval: float = 3.0  # 两次请求最小间隔（秒）

        # 指标追踪
        self._metrics: dict[str, int] = {
            "direct_attempts": 0,
            "direct_successes": 0,
            "mcp_attempts": 0,
            "mcp_successes": 0,
            "crossref_fallbacks": 0,
            "pubmed_fallbacks": 0,
            "cache_hits": 0,
        }

    async def _rate_limit(self) -> None:
        """Enforce rate limiting with random jitter to appear human."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_interval:
            jitter = random.uniform(0.5, 2.0)
            wait = self._min_interval - elapsed + jitter
            await asyncio.sleep(wait)
        self._last_request_time = time.time()

    def get_health_metrics(self) -> dict:
        """Return CNKI search health metrics."""
        total_direct = max(self._metrics["direct_attempts"], 1)
        total_mcp = max(self._metrics["mcp_attempts"], 1)
        return {
            **self._metrics,
            "direct_success_rate": round(
                self._metrics["direct_successes"] / total_direct, 3
            ),
            "mcp_success_rate": round(
                self._metrics["mcp_successes"] / total_mcp, 3
            ),
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(limit=10)
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )
        return self.session

    def _cache_key(self, query: str, year_filter: str, count: int) -> str:
        """生成缓存键"""
        return f"cnki:{query}|{year_filter}|{count}"

    def _get_cached(self, key: str) -> Optional[list[CNKIResult]]:
        """获取缓存结果（优先使用注入的 CacheManager）"""
        if self.cache is not None:
            return self.cache.get(key)

        if key in self._internal_cache:
            results, ts = self._internal_cache[key]
            if time.time() - ts < self._cache_ttl:
                return results
            del self._internal_cache[key]
        return None

    def _set_cached(self, key: str, results: list[CNKIResult]) -> None:
        """设置缓存（优先使用注入的 CacheManager）"""
        if self.cache is not None:
            self.cache.set(key, results, self._cache_ttl)
            return

        self._internal_cache[key] = (results, time.time())
        # 清理过期缓存
        now = time.time()
        expired = [k for k, (_, ts) in self._internal_cache.items() if now - ts > self._cache_ttl]
        for k in expired:
            del self._internal_cache[k]

    async def search(
        self, query: str, year_filter: str = "", count: int = 20
    ) -> list[CNKIResult]:
        """Search CNKI for academic papers, with fallback to CrossRef and PubMed"""
        # 检查缓存
        cache_key = self._cache_key(query, year_filter, count)
        cached = self._get_cached(cache_key)
        if cached is not None:
            self._metrics["cache_hits"] += 1
            logger.info(f"CNKI cache hit for query: {query}")
            return cached[:count]

        results: list[CNKIResult] = []

        # Method 0: MCP 工具调用（优先级最高）
        if self.mcp_enabled and "cnki_search" in self.mcp_tools:
            self._metrics["mcp_attempts"] += 1
            try:
                results = await self._call_with_cb(
                    self._search_via_mcp(query, year_filter, count)
                )
                if results:
                    self._metrics["mcp_successes"] += 1
                    logger.info(f"MCP CNKI search returned {len(results)} results")
                    self._set_cached(cache_key, results)
                    return results[:count]
            except Exception as e:
                logger.warning(f"MCP CNKI search failed: {e}")

        # Method 1: Direct CNKI search (with rate limiting)
        self._metrics["direct_attempts"] += 1
        await self._rate_limit()
        try:
            results = await self._call_with_cb(
                self._search_cnki_direct(query, year_filter, count)
            )
            if results:
                self._metrics["direct_successes"] += 1
                logger.info(f"CNKI direct search returned {len(results)} results")
                self._set_cached(cache_key, results)
                return results[:count]
        except Exception as e:
            logger.warning(f"CNKI direct search failed: {e}")

        # Method 2: Try with Bright Data proxy if configured
        if self.bright_data_proxy:
            try:
                results = await self._call_with_cb(
                    self._search_cnki_proxy(query, year_filter, count)
                )
                if results:
                    logger.info(f"CNKI proxy search returned {len(results)} results")
                    self._set_cached(cache_key, results)
                    return results[:count]
            except Exception as e:
                logger.warning(f"CNKI proxy search failed: {e}")

        # Method 3: Fallback to CrossRef + PubMed
        logger.info("Falling back to CrossRef and PubMed APIs")
        self._metrics["crossref_fallbacks"] += 1
        self._metrics["pubmed_fallbacks"] += 1
        crossref_task = self._search_crossref(query, count // 2)
        pubmed_task = self._search_pubmed(query, count // 2)
        crossref_results, pubmed_results = await asyncio.gather(
            crossref_task, pubmed_task, return_exceptions=True
        )

        if isinstance(crossref_results, list):
            results.extend(crossref_results)
        if isinstance(pubmed_results, list):
            results.extend(pubmed_results)

        if results:
            self._set_cached(cache_key, results)

        return results[:count]

    async def _call_with_cb(self, coro):
        """通过熔断器包装调用（如果熔断器已配置）"""
        if self.circuit_breaker is not None:
            async with self.circuit_breaker:
                return await coro
        return await coro

    async def _search_via_mcp(
        self, query: str, year_filter: str, count: int
    ) -> list[CNKIResult]:
        """Search CNKI via cnki-downloader Master API (Playwright-based).

        The Master API at {CNKI_MASTER_URL}/search performs a full browser-based
        search with TLS impersonation, fingerprint randomization, behavior
        simulation, and CAPTCHA handling.
        """
        tool_config = self.mcp_tools.get("cnki_search", {})
        mcp_endpoint = tool_config.get("endpoint", "")
        if not mcp_endpoint:
            return []

        session = await self._get_session()

        # Payload matches cnki-downloader Master POST /search format
        payload = {
            "query": query,
            "year_filter": year_filter,
            "count": count,
        }

        try:
            async with session.post(
                mcp_endpoint,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        f"cnki-downloader Master returned status {resp.status}"
                    )
                    return []
                data = await resp.json()
        except asyncio.TimeoutError:
            logger.warning("cnki-downloader Master search timed out (60s)")
            return []
        except Exception as e:
            logger.warning(f"cnki-downloader Master search failed: {e}")
            return []

        if not data.get("success"):
            logger.warning(
                f"cnki-downloader Master search unsuccessful: {data.get('error', '')}"
            )
            return []

        results: list[CNKIResult] = []
        items = data.get("results", [])
        for item in items:
            results.append(CNKIResult(
                title=item.get("title", ""),
                author=item.get("author", ""),
                year=str(item.get("year", "")),
                source=item.get("source", ""),
                citations=item.get("citations", 0),
                core=item.get("core", False),
                abstract=item.get("abstract", "")[:500],
                doi=item.get("doi", ""),
            ))

        return results

    async def _search_cnki_direct(
        self, query: str, year_filter: str, count: int
    ) -> list[CNKIResult]:
        """Direct HTTP search on CNKI using TLS-impersonated client.

        Uses curl_cffi to emulate Chrome's TLS handshake fingerprint (JA3/JA4),
        which is the critical missing layer that plain aiohttp cannot provide.
        Includes exponential backoff retry and TLS fingerprint rotation on failure.
        """
        from ..utils.tls_client import BackendTLSClient

        # 完整浏览器指纹头 (also passed to TLS client for HTTP/2 header consistency)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://kns.cnki.net/",
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }

        max_retries = 3
        backoff_times = [1, 2, 4]

        search_params = {
            "classid": "WD0FTY92",
            "korder": "SU",
            "kw": query,
            "crossDbcodes": "CJFQ,CJRF,CDMD,CIPD,CCND,BDZK,CISD,SNAD,CCJD,GXDB_SECTION,CJFN",
        }

        if year_filter:
            if "-" in year_filter:
                start, end = year_filter.split("-", 1)
                search_params["publishdate_from"] = start
                search_params["publishdate_to"] = end
            else:
                search_params["publishdate_from"] = year_filter
                search_params["publishdate_to"] = year_filter

        # 创建 TLS 客户端 — 模拟 Chrome TLS 握手指纹
        tls = BackendTLSClient(
            impersonate=getattr(settings, "CNKI_TLS_IMPERSONATE", "chrome124"),
            proxy_url=self.bright_data_proxy,
            timeout=15,
        )

        last_exception: Optional[Exception] = None

        for attempt in range(max_retries):
            try:
                # Step 1: Visit CNKI homepage with TLS impersonation to get cookies
                resp = await tls.get(self.base_url, headers=headers)
                if resp.status_code != 200:
                    raise ConnectionError(
                        f"CNKI homepage returned status {resp.status_code} "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )

                # Step 2: POST search request via same TLS session (cookies carry over)
                resp = await tls.post(
                    f"{self.base_url}/kns8s/search",
                    data=search_params,
                    headers=headers,
                )
                if resp.status_code != 200:
                    # 403/429 indicate the TLS fingerprint or IP is blocked
                    if resp.status_code in (403, 429):
                        tls.rotate_impersonate()
                        raise ConnectionError(
                            f"CNKI search blocked ({resp.status_code}), "
                            f"rotating TLS fingerprint for retry"
                        )
                    raise ConnectionError(
                        f"CNKI search returned status {resp.status_code} "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                html = resp.text

                await tls.close()
                return self._parse_cnki_html(html)

            except asyncio.TimeoutError:
                last_exception = ConnectionError(
                    f"CNKI connection timed out (15s), attempt {attempt + 1}/{max_retries}"
                )
                logger.warning(
                    f"CNKI direct search timeout, attempt {attempt + 1}/{max_retries}"
                )
                tls.rotate_impersonate()
            except ConnectionError:
                raise  # Don't wrap ConnectionError
            except Exception as e:
                last_exception = e
                logger.warning(
                    f"CNKI direct search failed (attempt {attempt + 1}/{max_retries}): {e}"
                )
                tls.rotate_impersonate()

            if attempt < max_retries - 1:
                wait_time = backoff_times[attempt]
                logger.info(f"等待 {wait_time}s 后重试 CNKI 直接检索...")
                await asyncio.sleep(wait_time)

        await tls.close()

        raise last_exception if last_exception else ConnectionError(
            "CNKI direct search failed after all retries"
        )

    async def _search_cnki_proxy(
        self, query: str, year_filter: str, count: int
    ) -> list[CNKIResult]:
        """Search CNKI via Bright Data proxy"""
        session = await self._get_session()

        proxy_url = self.bright_data_proxy
        search_params = {
            "classid": "WD0FTY92",
            "korder": "SU",
            "kw": query,
        }

        if year_filter:
            if "-" in year_filter:
                start, end = year_filter.split("-", 1)
                search_params["publishdate_from"] = start
                search_params["publishdate_to"] = end
            else:
                search_params["publishdate_from"] = year_filter
                search_params["publishdate_to"] = year_filter

        async with session.post(
            f"{self.base_url}/kns8s/search",
            data=search_params,
            proxy=proxy_url,
            allow_redirects=True,
        ) as resp:
            if resp.status != 200:
                raise ConnectionError(f"CNKI proxy search returned status {resp.status}")
            html = await resp.text()

        return self._parse_cnki_html(html)

    async def _search_crossref(self, query: str, count: int) -> list[CNKIResult]:
        """Fallback: Search CrossRef API"""
        session = await self._get_session()
        encoded_query = quote(query)
        url = (
            f"https://api.crossref.org/works?"
            f"query={encoded_query}&rows={count}&sort=relevance"
        )

        async with session.get(url) as resp:
            if resp.status != 200:
                logger.warning(f"CrossRef API returned status {resp.status}")
                return []
            data = await resp.json()

        results: list[CNKIResult] = []
        items = data.get("message", {}).get("items", [])

        for item in items:
            title_list = item.get("title", [])
            title = title_list[0] if title_list else "No title"

            author_list = item.get("author", [])
            authors = ", ".join(
                f"{a.get('family', '')} {a.get('given', '')}".strip()
                for a in author_list[:3]
            )
            if len(author_list) > 3:
                authors += " et al."

            year = ""
            published = item.get("published-print") or item.get("published-online")
            if published:
                parts = published.get("date-parts", [[]])
                if parts and parts[0]:
                    year = str(parts[0][0])

            source_list = item.get("container-title", [])
            source = source_list[0] if source_list else ""

            citations = item.get("is-referenced-by-count", 0)

            abstract = item.get("abstract", "")
            abstract = re.sub(r"<[^>]+>", "", abstract)

            doi = item.get("DOI", "")

            results.append(
                CNKIResult(
                    title=title,
                    author=authors,
                    year=year,
                    source=source,
                    citations=citations,
                    core=False,
                    abstract=abstract[:500] if abstract else "",
                    doi=doi,
                )
            )

        return results

    async def _search_pubmed(self, query: str, count: int) -> list[CNKIResult]:
        """Fallback: Search PubMed E-utilities API"""
        session = await self._get_session()
        encoded_query = quote(query)

        search_url = (
            f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?"
            f"db=pubmed&term={encoded_query}&retmax={count}&retmode=json"
        )

        async with session.get(search_url) as resp:
            if resp.status != 200:
                logger.warning(f"PubMed search API returned status {resp.status}")
                return []
            search_data = await resp.json()

        id_list = search_data.get("esearchresult", {}).get("idlist", [])
        if not id_list:
            return []

        ids_str = ",".join(id_list)
        fetch_url = (
            f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?"
            f"db=pubmed&id={ids_str}&retmode=json"
        )

        async with session.get(fetch_url) as resp:
            if resp.status != 200:
                logger.warning(f"PubMed fetch API returned status {resp.status}")
                return []
            fetch_data = await resp.json()

        results: list[CNKIResult] = []
        articles = fetch_data.get("result", {})

        for pmid in id_list:
            article = articles.get(pmid, {})
            if not article or article.get("error"):
                continue

            title = article.get("title", "No title")

            author_list = article.get("authors", [])
            authors = ", ".join(
                f"{a.get('name', '')}".strip() for a in author_list[:3]
            )
            if len(author_list) > 3:
                authors += " et al."

            year = ""
            pub_date = article.get("pubdate", "")
            if pub_date:
                match = re.search(r"\d{4}", pub_date)
                if match:
                    year = match.group()

            source = article.get("source", "")
            abstract = article.get("abstract", "")
            doi = ""
            article_ids = article.get("articleids", [])
            for aid in article_ids:
                if aid.get("idtype") == "doi":
                    doi = aid.get("value", "")
                    break

            results.append(
                CNKIResult(
                    title=title,
                    author=authors,
                    year=year,
                    source=source,
                    citations=0,
                    core=False,
                    abstract=abstract[:500] if abstract else "",
                    doi=doi,
                )
            )

        return results

    def _parse_cnki_html(self, html: str) -> list[CNKIResult]:
        """Parse CNKI search results HTML page"""
        results: list[CNKIResult] = []

        result_pattern = re.compile(
            r'<tr[^>]*class="result-table-list"[^>]*>(.*?)</tr>',
            re.DOTALL,
        )
        matches = result_pattern.findall(html)

        for match in matches:
            try:
                title_match = re.search(
                    r'<a[^>]*class="fz14"[^>]*>(.*?)</a>', match, re.DOTALL
                )
                title = ""
                if title_match:
                    title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()

                author_match = re.search(
                    r'<td[^>]*class="author"[^>]*>(.*?)</td>', match, re.DOTALL
                )
                author = ""
                if author_match:
                    author = re.sub(r"<[^>]+>", "", author_match.group(1)).strip()

                source_match = re.search(
                    r'<td[^>]*class="source"[^>]*>(.*?)</td>', match, re.DOTALL
                )
                source = ""
                if source_match:
                    source = re.sub(r"<[^>]+>", "", source_match.group(1)).strip()

                date_match = re.search(
                    r'<td[^>]*class="date"[^>]*>(.*?)</td>', match, re.DOTALL
                )
                year = ""
                if date_match:
                    date_text = re.sub(r"<[^>]+>", "", date_match.group(1)).strip()
                    year_match = re.search(r"\d{4}", date_text)
                    if year_match:
                        year = year_match.group()

                cite_match = re.search(
                    r'<td[^>]*class="cite"[^>]*>(.*?)</td>', match, re.DOTALL
                )
                citations = 0
                if cite_match:
                    cite_text = re.sub(r"<[^>]+>", "", cite_match.group(1)).strip()
                    try:
                        citations = int(cite_text) if cite_text else 0
                    except ValueError:
                        citations = 0

                core = bool(
                    re.search(r"核心|CSSCI|北大核心|CSCD", match, re.IGNORECASE)
                )

                doi_match = re.search(r'DOI[:\s]*([10]\.\d{4,}/[^\s<"]+)', match)
                doi = doi_match.group(1) if doi_match else ""

                abstract_match = re.search(
                    r'<span[^>]*class="abstract"[^>]*>(.*?)</span>',
                    match,
                    re.DOTALL,
                )
                abstract = ""
                if abstract_match:
                    abstract = re.sub(r"<[^>]+>", "", abstract_match.group(1)).strip()

                if title:
                    results.append(
                        CNKIResult(
                            title=title,
                            author=author,
                            year=year,
                            source=source,
                            citations=citations,
                            core=core,
                            abstract=abstract[:500] if abstract else "",
                            doi=doi,
                        )
                    )
            except Exception as e:
                logger.warning(f"Failed to parse CNKI result item: {e}")
                continue

        return results

    def configure_proxy(self, proxy_url: Optional[str]) -> None:
        """Configure Bright Data proxy URL"""
        self.bright_data_proxy = proxy_url
        logger.info(f"CNKI proxy configured: {'set' if proxy_url else 'cleared'}")

    def configure_api_key(self, api_key: Optional[str]) -> None:
        """Configure CNKI API key for authenticated access"""
        self.cnki_api_key = api_key
        logger.info(f"CNKI API key configured: {'set' if api_key else 'cleared'}")

    def configure_mcp(self, tools: dict) -> None:
        """Configure MCP tools for CNKI search

        Args:
            tools: dict of tool_name -> {"endpoint": url, "auth": ...}
        """
        self.mcp_tools = tools
        self.mcp_enabled = bool(tools)
        logger.info(f"MCP tools configured: {list(tools.keys()) if tools else 'none'}")

    async def check_connection(self) -> dict:
        """Check connectivity to CNKI and fallback APIs"""
        status = {
            "cnki": {"connected": False, "method": "direct"},
            "crossref": {"connected": False},
            "pubmed": {"connected": False},
            "mcp": {"connected": False, "tools": list(self.mcp_tools.keys())},
        }

        session = await self._get_session()

        # Check CNKI
        try:
            async with session.get(self.base_url, allow_redirects=True) as resp:
                status["cnki"]["connected"] = resp.status == 200
        except Exception:
            status["cnki"]["connected"] = False

        # Check CrossRef
        try:
            async with session.get("https://api.crossref.org/works?rows=0") as resp:
                status["crossref"]["connected"] = resp.status == 200
        except Exception:
            status["crossref"]["connected"] = False

        # Check PubMed
        try:
            async with session.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi?retmode=json"
            ) as resp:
                status["pubmed"]["connected"] = resp.status == 200
        except Exception:
            status["pubmed"]["connected"] = False

        # Check MCP
        if self.mcp_enabled and "cnki_search" in self.mcp_tools:
            try:
                endpoint = self.mcp_tools["cnki_search"].get("endpoint", "")
                if endpoint:
                    async with session.get(endpoint, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        status["mcp"]["connected"] = resp.status < 500
            except Exception:
                status["mcp"]["connected"] = False

        if self.bright_data_proxy:
            status["cnki"]["method"] = "proxy"

        if self.mcp_enabled:
            status["cnki"]["method"] = "mcp"

        return status

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None


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

        # 聚合结果内存缓存：key -> (result, timestamp)
        self._cache: dict[str, tuple[dict, float]] = {}

    # ── 缓存相关 ────────────────────────────────────────────

    def _cache_key(
        self, query: str, count: int, source_filter: Optional[str], year_filter: str
    ) -> str:
        """生成缓存键"""
        return f"multi:{query}|{count}|{source_filter}|{year_filter}"

    def _get_cached(self, key: str) -> Optional[dict]:
        """获取缓存结果，过期则清除"""
        if key not in self._cache:
            return None
        result, ts = self._cache[key]
        if time.time() - ts < self.cache_ttl:
            return result
        del self._cache[key]
        return None

    def _set_cached(self, key: str, result: dict) -> None:
        """设置缓存并清理过期项"""
        self._cache[key] = (result, time.time())
        now = time.time()
        expired = [k for k, (_, ts) in self._cache.items() if now - ts > self.cache_ttl]
        for k in expired:
            del self._cache[k]

    # ── CNKIResult 转换 ────────────────────────────────────

    @staticmethod
    def _convert_cnki_result(result: CNKIResult, source: str) -> dict:
        """将 CNKIResult 转换为统一 dict 格式

        Args:
            result: CNKIResult 实例
            source: 数据源标识（"cnki" / "crossref" / "pubmed"）

        Returns:
            统一格式的 dict
        """
        # 解析作者列表（CNKIResult.author 为逗号分隔字符串）
        authors: list[str] = []
        if result.author:
            authors = [a.strip() for a in result.author.split(",") if a.strip()]
            # 处理 "et al." 后缀
            if authors and authors[-1].lower().startswith("et al"):
                authors = authors[:-1]

        # 解析年份
        year: Optional[int] = None
        if result.year:
            try:
                year = int(result.year)
            except ValueError:
                year = None

        # 构造 URL
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

    async def _search_cnki(
        self, query: str, count: int, year_filter: str
    ) -> list[dict]:
        """检索 CNKI"""
        if self.cnki_service is None:
            return []
        results = await self.cnki_service.search(
            query, year_filter=year_filter, count=count
        )
        return [self._convert_cnki_result(r, "cnki") for r in results]

    async def _search_semantic_scholar(
        self, query: str, count: int
    ) -> list[dict]:
        """检索 Semantic Scholar"""
        if self.semantic_scholar_service is None:
            return []
        results = await self.semantic_scholar_service.search(query, count=count)
        return [p.to_dict() for p in results]

    async def _search_arxiv(self, query: str, count: int) -> list[dict]:
        """检索 arXiv"""
        if self.arxiv_service is None:
            return []
        results = await self.arxiv_service.search(query, count=count)
        return [p.to_dict() for p in results]

    async def _search_crossref(self, query: str, count: int) -> list[dict]:
        """检索 CrossRef（通过 CNKIService 的现有方法）"""
        if self.cnki_service is None:
            return []
        results = await self.cnki_service._search_crossref(query, count)
        return [self._convert_cnki_result(r, "crossref") for r in results]

    async def _search_pubmed(self, query: str, count: int) -> list[dict]:
        """检索 PubMed（通过 CNKIService 的现有方法）"""
        if self.cnki_service is None:
            return []
        results = await self.cnki_service._search_pubmed(query, count)
        return [self._convert_cnki_result(r, "pubmed") for r in results]

    def _get_source_coro(
        self, source: str, query: str, count: int, year_filter: str
    ) -> Optional[Any]:
        """获取指定数据源的检索协程

        Args:
            source: 数据源标识
            query: 检索词
            count: 单源结果数量上限
            year_filter: 年份过滤

        Returns:
            检索协程；若数据源未配置则返回 None
        """
        if source == "cnki":
            return self._search_cnki(query, count, year_filter)
        elif source == "semantic_scholar":
            return self._search_semantic_scholar(query, count)
        elif source == "arxiv":
            return self._search_arxiv(query, count)
        elif source == "crossref":
            return self._search_crossref(query, count)
        elif source == "pubmed":
            return self._search_pubmed(query, count)
        return None

    # ── 核心检索方法 ────────────────────────────────────────

    async def search_multi_source(
        self,
        query: str,
        count: int = 20,
        source_filter: Optional[str] = None,
        year_filter: str = "",
    ) -> dict:
        """多源并行检索

        Args:
            query: 检索词
            count: 总结果数量上限
            source_filter: 数据源过滤，逗号分隔（如 "cnki,semantic_scholar,arxiv"），None 表示全部
            year_filter: 年份过滤

        Returns:
            {
                "success": True,
                "query": query,
                "count": len(results),
                "results": [...],  # 聚合去重后的结果列表
                "sources": {
                    "cnki": {"status": "success"|"failed"|"timeout", "count": N, "error": "..."},
                    "semantic_scholar": {...},
                    "arxiv": {...},
                    "crossref": {...},
                    "pubmed": {...},
                },
                "sources_tried": ["cnki", "semantic_scholar", ...],
            }
        """
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
        cached = self._get_cached(cache_key)
        if cached is not None:
            logger.info(f"多源检索缓存命中: {query}")
            return cached

        # 确定要查询的数据源
        if source_filter:
            sources = [
                s.strip()
                for s in source_filter.split(",")
                if s.strip() in self.ALL_SOURCES
            ]
        else:
            sources = list(self.ALL_SOURCES)

        sources_tried = list(sources)

        # 每个数据源分摊的结果数量（多取一些用于去重后仍有足够结果）
        per_source_count = max(count, 10)

        # 构建任务列表
        tasks: list[asyncio.Future] = []
        task_sources: list[str] = []

        for source in sources:
            coro = self._get_source_coro(source, query, per_source_count, year_filter)
            if coro is not None:
                # 用 asyncio.wait_for 包装，超时则取消
                tasks.append(asyncio.wait_for(coro, timeout=self.timeout))
                task_sources.append(source)

        if not tasks:
            return {
                "success": False,
                "query": query,
                "count": 0,
                "results": [],
                "sources": {},
                "sources_tried": sources_tried,
                "error": "没有可用的数据源",
            }

        # 并行检索所有数据源
        logger.info(
            f"多源并行检索: query={query!r}, sources={task_sources}, count={count}"
        )
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 聚合结果
        all_results: list[dict] = []
        sources_status: dict[str, dict] = {}

        for source, result in zip(task_sources, raw_results):
            if isinstance(result, asyncio.TimeoutError):
                sources_status[source] = {
                    "status": "timeout",
                    "count": 0,
                    "error": f"timeout after {self.timeout}s",
                }
                logger.warning(f"数据源 {source} 检索超时（{self.timeout}s）")
            elif isinstance(result, Exception):
                sources_status[source] = {
                    "status": "failed",
                    "count": 0,
                    "error": str(result),
                }
                logger.warning(f"数据源 {source} 检索失败: {result}")
            else:
                sources_status[source] = {
                    "status": "success",
                    "count": len(result),
                    "error": "",
                }
                all_results.extend(result)
                logger.info(f"数据源 {source} 返回 {len(result)} 条结果")

        # 去重
        all_results = self._deduplicate(all_results)

        # 按引用数降序排序
        all_results.sort(
            key=lambda x: x.get("citation_count", 0), reverse=True
        )

        # 截取前 count 条
        all_results = all_results[:count]

        result_dict = {
            "success": True,
            "query": query,
            "count": len(all_results),
            "results": all_results,
            "sources": sources_status,
            "sources_tried": sources_tried,
        }

        # 写入缓存
        self._set_cached(cache_key, result_dict)

        logger.info(
            f"多源检索完成: query={query!r}, 聚合后 {len(all_results)} 条结果"
        )
        return result_dict

    # ── 去重 ────────────────────────────────────────────────

    def _deduplicate(self, results: list[dict]) -> list[dict]:
        """基于标题相似度去重

        使用 difflib.SequenceMatcher 计算标题相似度，
        相似度 > 0.85 视为重复，保留引用数更高的那条。

        Args:
            results: 待去重的结果列表

        Returns:
            去重后的结果列表
        """
        if not results:
            return []

        # 按引用数降序排序，这样高引用的会先被保留
        sorted_results = sorted(
            results, key=lambda x: x.get("citation_count", 0), reverse=True
        )

        deduplicated: list[dict] = []
        seen_titles: list[str] = []

        for result in sorted_results:
            title = (result.get("title") or "").strip().lower()
            if not title:
                # 无标题的结果直接保留
                deduplicated.append(result)
                continue

            # 检查是否与已保留的结果重复
            is_duplicate = False
            for seen_title in seen_titles:
                similarity = difflib.SequenceMatcher(
                    None, title, seen_title
                ).ratio()
                if similarity > 0.85:
                    is_duplicate = True
                    break

            if not is_duplicate:
                deduplicated.append(result)
                seen_titles.append(title)

        return deduplicated

    # ── 连通状态检测 ────────────────────────────────────────

    async def check_status(self) -> dict:
        """检测所有数据源的连通状态

        对每个数据源发起一个简单请求（如搜索 "test"），测量延迟。
        超时 5 秒。

        Returns:
            {
                "cnki": {"status": "connected"|"disconnected", "latency_ms": int, "last_check": "..."},
                "semantic_scholar": {...},
                "arxiv": {...},
                "crossref": {...},
                "pubmed": {...},
            }
        """
        status: dict[str, dict] = {}

        for source in self.ALL_SOURCES:
            status[source] = await self._check_source_status(source)

        return status

    async def _check_source_status(self, source: str) -> dict:
        """检测单个数据源的连通状态

        Args:
            source: 数据源标识

        Returns:
            {
                "status": "connected"|"disconnected",
                "latency_ms": int,
                "last_check": "ISO 时间戳",
                "error": "错误信息（成功时为空）",
            }
        """
        start_time = time.time()
        now_iso = datetime.now().isoformat()

        # 检查服务是否已配置
        if source in ("cnki", "crossref", "pubmed") and self.cnki_service is None:
            return {
                "status": "disconnected",
                "latency_ms": 0,
                "last_check": now_iso,
                "error": "cnki_service 未配置",
            }
        if source == "semantic_scholar" and self.semantic_scholar_service is None:
            return {
                "status": "disconnected",
                "latency_ms": 0,
                "last_check": now_iso,
                "error": "semantic_scholar_service 未配置",
            }
        if source == "arxiv" and self.arxiv_service is None:
            return {
                "status": "disconnected",
                "latency_ms": 0,
                "last_check": now_iso,
                "error": "arxiv_service 未配置",
            }

        # 构建检测协程（搜索 "test"，count=1）
        coro = self._get_source_coro(source, "test", 1, "")
        if coro is None:
            return {
                "status": "disconnected",
                "latency_ms": 0,
                "last_check": now_iso,
                "error": f"未知数据源: {source}",
            }

        try:
            await asyncio.wait_for(coro, timeout=5)
            latency_ms = int((time.time() - start_time) * 1000)
            return {
                "status": "connected",
                "latency_ms": latency_ms,
                "last_check": datetime.now().isoformat(),
                "error": "",
            }
        except asyncio.TimeoutError:
            return {
                "status": "disconnected",
                "latency_ms": 5000,
                "last_check": datetime.now().isoformat(),
                "error": "timeout (5s)",
            }
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            return {
                "status": "disconnected",
                "latency_ms": latency_ms,
                "last_check": datetime.now().isoformat(),
                "error": str(e),
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
