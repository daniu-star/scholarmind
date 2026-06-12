from __future__ import annotations

import aiohttp
import asyncio
import re
import json
import logging
import time
from typing import Optional, TYPE_CHECKING
from dataclasses import dataclass, asdict
from urllib.parse import quote

if TYPE_CHECKING:
    from ..utils.cache import CacheManager
    from ..utils.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


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
            logger.info(f"CNKI cache hit for query: {query}")
            return cached[:count]

        results: list[CNKIResult] = []

        # Method 0: MCP 工具调用（优先级最高）
        if self.mcp_enabled and "cnki_search" in self.mcp_tools:
            try:
                results = await self._call_with_cb(
                    self._search_via_mcp(query, year_filter, count)
                )
                if results:
                    logger.info(f"MCP CNKI search returned {len(results)} results")
                    self._set_cached(cache_key, results)
                    return results[:count]
            except Exception as e:
                logger.warning(f"MCP CNKI search failed: {e}")

        # Method 1: Direct CNKI search
        try:
            results = await self._call_with_cb(
                self._search_cnki_direct(query, year_filter, count)
            )
            if results:
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
        """通过 MCP 工具调用 CNKI 搜索"""
        tool_config = self.mcp_tools.get("cnki_search", {})
        mcp_endpoint = tool_config.get("endpoint", "")
        if not mcp_endpoint:
            return []

        session = await self._get_session()
        payload = {
            "tool": "cnki_search",
            "arguments": {
                "query": query,
                "year_filter": year_filter,
                "count": count,
            },
        }

        headers = {"Content-Type": "application/json"}
        if self.cnki_api_key:
            headers["Authorization"] = f"Bearer {self.cnki_api_key}"

        async with session.post(
            mcp_endpoint, json=payload, headers=headers
        ) as resp:
            if resp.status != 200:
                logger.warning(f"MCP endpoint returned status {resp.status}")
                return []
            data = await resp.json()

        results: list[CNKIResult] = []
        items = data.get("results", [])
        for item in items:
            results.append(CNKIResult(
                title=item.get("title", ""),
                author=item.get("author", ""),
                year=item.get("year", ""),
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
        """Direct HTTP search on CNKI"""
        session = await self._get_session()

        # Step 1: Get a session cookie by visiting the homepage
        async with session.get(self.base_url) as resp:
            if resp.status != 200:
                raise ConnectionError(f"CNKI homepage returned status {resp.status}")

        # Step 2: POST search request
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

        async with session.post(
            f"{self.base_url}/kns8s/search",
            data=search_params,
            allow_redirects=True,
        ) as resp:
            if resp.status != 200:
                raise ConnectionError(f"CNKI search returned status {resp.status}")
            html = await resp.text()

        return self._parse_cnki_html(html)

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
