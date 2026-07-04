"""Multi-Source Academic Paper Collector — Long-Term Distributed Crawler Core.

Data sources (ordered by reliability):
  1. CNKI RSS feeds    — NO cookies needed, 20 papers/journal, requires CNKI access
  2. CrossRef API       — NO auth needed, global coverage, full metadata
  3. Semantic Scholar   — Free API, citations + references
  4. arXiv API          — Free, preprints, CS/physics/math
  5. CNKI Detail Pages  — Requires cookies + CNKI access, full Chinese metadata

Architecture:
  - Stateless: each source is independent, no shared state
  - Rate-limited: built-in delays to respect API limits
  - Auto-degrade: when CNKI 418 detected, skips CNKI sources automatically
  - Cookie-aware: gracefully degrades when CNKI cookies are expired
  - Distributed: designed for Redis-based task queue (master/worker pattern)
"""

import asyncio
import re
import json
import time
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional
from xml.etree import ElementTree as ET
from urllib.parse import quote, urlencode

from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# ── Data Models ────────────────────────────────────────────────

@dataclass
class PaperRecord:
    """Unified paper record from any data source."""
    # Core fields
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int = 0
    journal: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    doi: str = ""

    # Extended fields
    citations: int = 0
    references_count: int = 0
    is_core: bool = False
    language: str = "zh"

    # URLs
    cnki_url: str = ""
    pdf_url: str = ""
    fulltext_url: str = ""

    # Source tracking
    source: str = ""          # "cnki_rss" | "crossref" | "semantic_scholar" | "arxiv" | "cnki_detail"
    source_id: str = ""       # Native ID from source
    fetch_time: str = ""      # ISO timestamp
    data_quality: int = 0     # 0-10: how many fields are populated

    # CNKI-specific
    cnki_filename: str = ""
    cnki_dbcode: str = ""
    cnki_order_url: str = ""

    # Body text (from PDF extraction)
    body_text: str = ""
    body_text_length: int = 0

    def calculate_quality(self) -> int:
        """Calculate data quality score (0-10) based on populated fields."""
        score = 0
        if self.title: score += 2
        if self.authors: score += 1
        if self.year: score += 1
        if self.journal: score += 1
        if self.abstract and len(self.abstract) > 50: score += 2
        if self.keywords: score += 1
        if self.doi: score += 1
        if self.body_text: score += 1
        self.data_quality = score
        return score

    def to_dict(self) -> dict:
        d = asdict(self)
        d["data_quality"] = self.calculate_quality()
        return d


# ── Source: CNKI RSS ──────────────────────────────────────────

class CNKIRSSSource:
    """CNKI RSS feed — NO cookies required, always works."""

    BASE = "https://rss.cnki.net/knavi/rss"

    def __init__(self, tls: AsyncSession):
        self.tls = tls

    async def fetch_journal(self, journal_code: str) -> list[PaperRecord]:
        """Fetch recent papers from a journal's RSS feed.

        Returns up to 20 papers with title, authors, date, and link.
        """
        url = f"{self.BASE}/{journal_code}?pcode=CJFD,CCJD"
        try:
            resp = await self.tls.get(url)
            if resp.status_code != 200:
                logger.warning("rss_fetch_failed: %s status=%d", journal_code, resp.status_code)
                return []

            root = ET.fromstring(resp.text)
            papers = []
            for item in root.findall(".//item"):
                pub_date = (item.findtext("pubDate", "") or "").strip()
                year = 0
                ym = re.search(r"(\d{4})", pub_date)
                if ym:
                    year = int(ym.group(1))

                paper = PaperRecord(
                    title=(item.findtext("title", "") or "").strip(),
                    authors=[
                        a.strip()
                        for a in (item.findtext("author", "") or "").split(";")
                        if a.strip()
                    ],
                    year=year,
                    cnki_url=(item.findtext("link", "") or "").strip(),
                    abstract=(item.findtext("description", "") or "").strip()[:1000],
                    source="cnki_rss",
                    source_id=journal_code,
                    fetch_time=datetime.now().isoformat(),
                )
                paper.calculate_quality()
                papers.append(paper)

            return papers
        except Exception as e:
            logger.error("rss_fetch_error: %s %s", journal_code, e)
            return []

    async def fetch_multiple(self, journal_codes: list[str]) -> list[PaperRecord]:
        """Fetch RSS papers from multiple journals concurrently."""
        tasks = [self.fetch_journal(code) for code in journal_codes]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_papers = []
        for code, result in zip(journal_codes, results):
            if isinstance(result, Exception):
                logger.error("rss_batch_error: %s %s", code, result)
            else:
                all_papers.extend(result)

        # Deduplicate by title
        seen = set()
        unique = []
        for p in all_papers:
            key = p.title[:50]
            if key not in seen:
                seen.add(key)
                unique.append(p)

        return unique


# ── Source: arXiv API ─────────────────────────────────────────

class ArXivSource:
    """arXiv API — free, no auth, good for preprints and CS/physics."""

    BASE = "https://export.arxiv.org/api/query"

    def __init__(self, tls: AsyncSession):
        self.tls = tls

    async def search(self, query: str, max_results: int = 10) -> list[PaperRecord]:
        params = {
            "search_query": f"all:{query}",
            "max_results": min(max_results, 50),
            "sortBy": "relevance",
        }
        url = f"{self.BASE}?{urlencode(params)}"
        try:
            resp = await self.tls.get(url, timeout=20)
            if resp.status_code != 200:
                return []
            root = ET.fromstring(resp.text)
            ns = {"a": "http://www.w3.org/2005/Atom"}
            papers = []
            for entry in root.findall("a:entry", ns):
                title = entry.find("a:title", ns)
                summary = entry.find("a:summary", ns)
                published = entry.find("a:published", ns)
                authors = [
                    a.find("a:name", ns).text or ""
                    for a in entry.findall("a:author", ns)
                ]
                links = entry.findall("a:link", ns)
                pdf_url = ""
                doi = ""
                for link in links:
                    href = link.get("href", "")
                    title_attr = link.get("title", "")
                    if title_attr == "pdf":
                        pdf_url = href
                    elif "doi.org" in href:
                        doi = href.replace("https://doi.org/", "")

                paper = PaperRecord(
                    title=title.text.strip() if title is not None else "",
                    authors=[a for a in authors if a],
                    year=int(published.text[:4]) if published is not None else 0,
                    journal="arXiv",
                    abstract=summary.text.strip()[:2000] if summary is not None else "",
                    doi=doi,
                    pdf_url=pdf_url,
                    fulltext_url=pdf_url,
                    language="en",
                    source="arxiv",
                    fetch_time=datetime.now().isoformat(),
                )
                paper.calculate_quality()
                papers.append(paper)
            return papers
        except Exception as e:
            logger.error("arxiv_search_error: %s", e)
            return []


# ── Source: CrossRef API ──────────────────────────────────────

class CrossRefSource:
    """CrossRef API — free, global, no auth required."""

    BASE = "https://api.crossref.org/works"

    def __init__(self, tls: AsyncSession):
        self.tls = tls

    async def search(
        self, query: str, rows: int = 10, year_filter: str = ""
    ) -> list[PaperRecord]:
        """Search CrossRef for papers by keyword."""
        params = {
            "query": query,
            "rows": min(rows, 50),
            "sort": "relevance",
        }
        if year_filter:
            params["filter"] = f"from-pub-date:{year_filter},until-pub-date:{year_filter}"

        url = f"{self.BASE}?{urlencode(params)}"
        try:
            resp = await self.tls.get(url)
            if resp.status_code != 200:
                return []
            data = json.loads(resp.text)
            items = data.get("message", {}).get("items", [])
            return [self._parse_item(item) for item in items]
        except Exception as e:
            logger.error("crossref_search_error: %s", e)
            return []

    async def lookup_doi(self, doi: str) -> Optional[PaperRecord]:
        """Look up a specific paper by DOI — returns FULL metadata."""
        url = f"{self.BASE}/{quote(doi, safe='')}"
        try:
            resp = await self.tls.get(url)
            if resp.status_code != 200:
                return None
            data = json.loads(resp.text)
            item = data.get("message", {})
            return self._parse_item(item) if item else None
        except Exception:
            return None

    def _parse_item(self, item: dict) -> PaperRecord:
        """Parse CrossRef item into PaperRecord."""
        title_list = item.get("title", [])
        title = title_list[0] if title_list else ""

        authors = []
        for a in item.get("author", []):
            name = f"{a.get('family', '')} {a.get('given', '')}".strip()
            if name:
                authors.append(name)

        year = 0
        published = item.get("published-print") or item.get("published-online") or {}
        parts = published.get("date-parts", [[0]])
        if parts and parts[0]:
            year = parts[0][0]

        container = item.get("container-title", [])
        journal = container[0] if container else ""

        abstract = item.get("abstract", "")
        abstract = re.sub(r"<[^>]+>", "", abstract)  # Strip HTML tags
        abstract = abstract.replace("<jats:p>", "").replace("</jats:p>", "")

        keywords = item.get("subject", [])

        doi = item.get("DOI", "")
        citations = item.get("is-referenced-by-count", 0)
        refs = item.get("references-count", 0)

        # Build URLs
        url = f"https://doi.org/{doi}" if doi else ""
        fulltext_links = item.get("link", [])
        fulltext_url = ""
        for link in fulltext_links:
            if link.get("content-type") in ("text/xml", "application/pdf", "text/html"):
                fulltext_url = link.get("URL", "")
                break

        paper = PaperRecord(
            title=title,
            authors=authors,
            year=year,
            journal=journal,
            abstract=abstract[:2000],
            keywords=keywords[:10],
            doi=doi,
            citations=citations,
            references_count=refs,
            language="en",
            cnki_url=url,
            fulltext_url=fulltext_url,
            source="crossref",
            source_id=doi,
            fetch_time=datetime.now().isoformat(),
        )
        paper.calculate_quality()
        return paper


# ── Source: Semantic Scholar ──────────────────────────────────

class SemanticScholarSource:
    """Semantic Scholar API — free, good citation data."""

    BASE = "https://api.semanticscholar.org/graph/v1"

    def __init__(self, tls: AsyncSession, api_key: str = ""):
        self.tls = tls
        self.api_key = api_key

    async def search(
        self, query: str, limit: int = 10, year: str = ""
    ) -> list[PaperRecord]:
        """Search papers by keyword, with retry on 429 rate limit."""
        params = {
            "query": query,
            "limit": min(limit, 50),
            "fields": "title,authors,year,abstract,externalIds,citationCount,referenceCount,journal,publicationTypes,openAccessPdf",
        }
        if year:
            params["year"] = year

        url = f"{self.BASE}/paper/search?{urlencode(params)}"
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        for attempt in range(3):
            try:
                await asyncio.sleep(1.0 * attempt)  # Progressive delay
                resp = await self.tls.get(url, headers=headers)
                if resp.status_code == 429:
                    logger.warning("semantic_scholar_429: rate limited, attempt %d/3", attempt + 1)
                    await asyncio.sleep(3.0 * (attempt + 1))
                    continue
                if resp.status_code != 200:
                    return []
                data = json.loads(resp.text)
                items = data.get("data", [])
                return [self._parse_item(item) for item in items]
            except Exception as e:
                logger.error("semantic_scholar_error: %s", e)
                if attempt < 2:
                    await asyncio.sleep(2.0)
        return []

    async def lookup_doi(self, doi: str) -> Optional[PaperRecord]:
        """Look up paper by DOI for citation data enrichment."""
        url = f"{self.BASE}/paper/DOI:{quote(doi, safe='')}?fields=title,authors,year,abstract,citationCount,referenceCount,journal,openAccessPdf"
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        try:
            resp = await self.tls.get(url, headers=headers)
            if resp.status_code != 200:
                return None
            item = json.loads(resp.text)
            return self._parse_item(item) if item else None
        except Exception:
            return None

    def _parse_item(self, item: dict) -> PaperRecord:
        authors = [a.get("name", "") for a in item.get("authors", [])]
        external = item.get("externalIds", {})
        doi = external.get("DOI", "")
        oa = item.get("openAccessPdf", {})
        pdf_url = oa.get("url", "") if oa else ""
        journal_info = item.get("journal", {})
        journal = journal_info.get("name", "") if journal_info else ""

        paper = PaperRecord(
            title=item.get("title", ""),
            authors=authors,
            year=item.get("year", 0) or 0,
            journal=journal,
            abstract=item.get("abstract", "")[:2000] if item.get("abstract") else "",
            doi=doi,
            citations=item.get("citationCount", 0) or 0,
            references_count=item.get("referenceCount", 0) or 0,
            language="en",
            pdf_url=pdf_url,
            cnki_url=f"https://doi.org/{doi}" if doi else "",
            source="semantic_scholar",
            source_id=item.get("paperId", ""),
            fetch_time=datetime.now().isoformat(),
        )
        paper.calculate_quality()
        return paper


# ── Source: CNKI Detail Pages (cookie-enhanced) ───────────────

class CNKIDetailSource:
    """CNKI paper detail pages — requires cookies, provides full Chinese metadata."""

    def __init__(self, tls: AsyncSession, cookies: dict[str, str]):
        self.tls = tls
        self.cookies = cookies
        self._cookies_set = False

    async def _ensure_cookies(self):
        if not self._cookies_set:
            for name, value in self.cookies.items():
                self.tls.cookies.set(name, value, domain=".cnki.net")
            self._cookies_set = True

    async def enrich_paper(self, paper: PaperRecord) -> PaperRecord:
        """Enrich a PaperRecord with CNKI detail page metadata.

        Only works when cookies are valid. Gracefully handles failures.
        """
        if not paper.cnki_url or "kns.cnki.net" not in paper.cnki_url:
            paper.source = paper.source or "cnki_rss_enrich_failed"
            return paper

        await self._ensure_cookies()

        try:
            resp = await self.tls.get(paper.cnki_url)
            if resp.status_code != 200:
                logger.debug("cnki_detail_http_error: %d", resp.status_code)
                return paper

            html = resp.text

            # Check if we got actual content vs CAPTCHA page
            if len(html) < 3000 or "verify" in resp.url.lower():
                logger.debug("cnki_detail_blocked_or_captcha")
                return paper

            soup = BeautifulSoup(html, "html.parser")

            # Abstract
            abs_el = (
                soup.select_one(".abstract-text")
                or soup.select_one('[class*="abstract"]')
            )
            if abs_el:
                text = abs_el.get_text(strip=True)
                text = re.sub(r"^摘要[：:\s]*", "", text)
                if len(text) > len(paper.abstract or ""):
                    paper.abstract = text[:2000]

            # Keywords
            kw_els = soup.select(".keywords a, [class*='keyword'] a")
            if kw_els:
                kws = []
                for el in kw_els:
                    kw = el.get_text(strip=True).rstrip(";；")
                    if kw and len(kw) > 1:
                        kws.append(kw)
                if kws:
                    paper.keywords = kws

            # DOI
            if not paper.doi:
                dm = re.search(r"10\.\d{4,}/[^\s\"'<>&]+", html)
                if dm:
                    paper.doi = dm.group(0).rstrip(".")

            # Journal
            if not paper.journal:
                j_el = soup.select_one(".source, [class*='source'], .journal")
                if j_el:
                    paper.journal = j_el.get_text(strip=True)[:100]

            # Core journal flag
            if not paper.is_core:
                paper.is_core = bool(
                    re.search(r"核心|CSSCI|北大核心|CSCD", html, re.IGNORECASE)
                )

            # CNKI-specific download info
            fn_m = re.search(r"filename=([^&\"'\\s]+)", html)
            if fn_m:
                paper.cnki_filename = fn_m.group(1)
            db_m = re.search(r"dbcode=([^&\"'\\s]+)", html)
            if db_m:
                paper.cnki_dbcode = db_m.group(1)
            order_m = re.findall(
                r"bar\.cnki\.net/bar/download/order\?id=([^\"'&\s]+)", html
            )
            if order_m:
                paper.cnki_order_url = f"https://bar.cnki.net/bar/download/order?id={order_m[0]}"

            # Mark as enriched
            paper.source = "cnki_detail"
            paper.calculate_quality()

        except Exception as e:
            logger.debug("cnki_detail_enrich_error: %s", e)

        return paper

    async def enrich_batch(
        self, papers: list[PaperRecord], concurrency: int = 3
    ) -> list[PaperRecord]:
        """Enrich multiple papers with rate-limited concurrency."""
        sem = asyncio.Semaphore(concurrency)

        async def enrich_one(paper):
            async with sem:
                await asyncio.sleep(1.5)  # Rate limit
                return await self.enrich_paper(paper)

        tasks = [enrich_one(p) for p in papers]
        return list(await asyncio.gather(*tasks))


# ── Multi-Source Collector ────────────────────────────────────

class MultiSourceCollector:
    """Orchestrates collection from all sources, merges, and deduplicates."""

    def __init__(
        self,
        cookies: Optional[dict[str, str]] = None,
        semantic_scholar_key: str = "",
        output_dir: str = "../数据库/cnki/multi_source",
    ):
        self.cookies = cookies or {}
        self.semantic_scholar_key = semantic_scholar_key
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._tls: Optional[AsyncSession] = None
        self._stats: dict[str, int] = {}

    async def _get_tls(self) -> AsyncSession:
        if self._tls is None:
            self._tls = AsyncSession(impersonate="chrome124", timeout=30, verify=False)
        return self._tls

    async def close(self):
        if self._tls:
            await self._tls.close()

    async def _check_cnki_blocked(self, tls: AsyncSession) -> bool:
        """快速检测 CNKI 是否被 418 阻断。

        Returns:
            True if CNKI is returning HTTP 418 (blocked)
        """
        try:
            resp = await tls.get(
                "https://www.cnki.net/",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
            if resp.status_code == 418:
                logger.warning("CNKI 418 BLOCKED — Tencent EdgeOne WAF is blocking this IP")
                return True
            return False
        except Exception:
            return True

    async def collect(
        self,
        journal_codes: Optional[list[str]] = None,
        search_queries: Optional[list[str]] = None,
        enrich_with_cnki: bool = True,
        force_skip_cnki: bool = False,
    ) -> list[PaperRecord]:
        """Collect papers from all available sources.

        Args:
            journal_codes: CNKI journal codes for RSS (e.g., ["GJXW", "YANJ"])
            search_queries: Keywords for CrossRef/Semantic Scholar search
            enrich_with_cnki: Whether to enrich RSS papers with CNKI detail pages
            force_skip_cnki: Force skip CNKI sources (even if not blocked)

        Returns:
            Deduplicated list of PaperRecords sorted by data quality
        """
        tls = await self._get_tls()
        all_papers: list[PaperRecord] = []
        self._stats = {}

        # Pre-check: is CNKI blocked?
        cnki_blocked = force_skip_cnki or await self._check_cnki_blocked(tls)
        if cnki_blocked:
            print("  [!] CNKI is BLOCKED (HTTP 418) - skipping CNKI sources, using alternatives")
            print("  [!] Only CrossRef + Semantic Scholar + arXiv will be used")
            self._stats["cnki_status"] = 418

        # ── Source 1: CNKI RSS (requires CNKI access) ──
        if journal_codes and not cnki_blocked:
            print(f"[1/5] CNKI RSS: {len(journal_codes)} journals...")
            rss = CNKIRSSSource(tls)
            rss_papers = await rss.fetch_multiple(journal_codes)
            self._stats["cnki_rss"] = len(rss_papers)
            all_papers.extend(rss_papers)
            print(f"       → {len(rss_papers)} papers from RSS")
        elif journal_codes and cnki_blocked:
            print("[1/5] CNKI RSS: SKIPPED (CNKI blocked)")
            self._stats["cnki_rss"] = "skipped_418"

        # ── Source 2: CrossRef (always available) ──
        if search_queries:
            print(f"[2/5] CrossRef: {len(search_queries)} queries...")
            crossref = CrossRefSource(tls)
            cr_total = 0
            for query in search_queries:
                cr_papers = await crossref.search(query, rows=8)
                all_papers.extend(cr_papers)
                cr_total += len(cr_papers)
                await asyncio.sleep(0.3)
            self._stats["crossref"] = cr_total
            print(f"       → {cr_total} papers from CrossRef")

        # ── Source 3: Semantic Scholar (always available) ──
        if search_queries:
            print(f"[3/5] Semantic Scholar: {len(search_queries)} queries...")
            s2 = SemanticScholarSource(tls, self.semantic_scholar_key)
            s2_total = 0
            for query in search_queries[:2]:  # Limit to avoid rate limits
                await asyncio.sleep(0.5)
                s2_papers = await s2.search(query, limit=5)
                all_papers.extend(s2_papers)
                s2_total += len(s2_papers)
                await asyncio.sleep(1.0)  # Rate limit: 1 req/sec
            self._stats["semantic_scholar"] = s2_total
            print(f"       → {s2_total} papers from Semantic Scholar")

        # ── Source 4: arXiv (always available, preprints) ──
        if search_queries:
            print(f"[4/5] arXiv: {len(search_queries)} queries...")
            arxiv = ArXivSource(tls)
            arxiv_total = 0
            for query in search_queries[:3]:
                arxiv_papers = await arxiv.search(query, max_results=5)
                all_papers.extend(arxiv_papers)
                arxiv_total += len(arxiv_papers)
                await asyncio.sleep(0.5)
            self._stats["arxiv"] = arxiv_total
            print(f"       → {arxiv_total} papers from arXiv")

        # ── Source 5: CNKI Detail Pages (cookie-enhanced, requires CNKI) ──
        if enrich_with_cnki and self.cookies and all_papers and not cnki_blocked:
            cnki_papers = [p for p in all_papers if p.cnki_url and "kns.cnki.net" in p.cnki_url]
            if cnki_papers:
                print(f"[5/5] CNKI Detail enrichment: {len(cnki_papers)} papers...")
                detail = CNKIDetailSource(tls, self.cookies)
                enriched = await detail.enrich_batch(cnki_papers)
                enriched_map = {p.cnki_url: p for p in enriched}
                for i, p in enumerate(all_papers):
                    if p.cnki_url in enriched_map:
                        all_papers[i] = enriched_map[p.cnki_url]
                self._stats["cnki_detail_enriched"] = len(cnki_papers)
                print(f"       → enriched {len(cnki_papers)} papers")
        else:
            self._stats["cnki_detail_enriched"] = "skipped_418"

        # ── Pre-check summary ──
        if cnki_blocked:
            print("\n  " + "=" * 50)
            print("  CNKI 阻断诊断")
            print("  " + "-" * 50)
            print("  CNKI (www.cnki.net) 返回 HTTP 418 (Tencent EdgeOne)")
            print("  当前 IP 已被知网 WAF 列入黑名单")
            print("")
            print("  解决方案:")
            print("  1. 使用校园网 VPN 或代理更换 IP")
            print("  2. 运行多源采集器(当前)从 CrossRef/arXiv 获取数据")
            print("  3. 从浏览器手动下载 PDF (Phase 2 模式)")
            print("  " + "=" * 50)

        # Deduplicate by DOI (preferred) or title similarity
        all_papers = self._deduplicate(all_papers)

        # Sort by data quality (best first)
        for p in all_papers:
            p.calculate_quality()
        all_papers.sort(key=lambda p: p.data_quality, reverse=True)

        return all_papers

    @staticmethod
    def _deduplicate(papers: list[PaperRecord]) -> list[PaperRecord]:
        """Deduplicate by DOI first, then by title similarity."""
        seen_dois: set[str] = set()
        seen_titles: list[str] = []
        unique: list[PaperRecord] = []

        for p in papers:
            # DOI-based dedup
            if p.doi and p.doi in seen_dois:
                continue
            if p.doi:
                seen_dois.add(p.doi)

            # Title-based dedup
            title_key = re.sub(r"\s+", "", p.title[:30].lower())
            is_dup = False
            for seen in seen_titles:
                if title_key == seen:
                    is_dup = True
                    break
            if is_dup:
                continue
            seen_titles.append(title_key)

            unique.append(p)

        return unique

    def save_results(self, papers: list[PaperRecord]) -> Path:
        """Save collected papers as JSON output."""
        output = {
            "timestamp": datetime.now().isoformat(),
            "total_papers": len(papers),
            "stats": self._stats,
            "papers": [p.to_dict() for p in papers],
        }
        out_path = self.output_dir / f"collection_{datetime.now():%Y%m%d_%H%M%S}.json"
        out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        return out_path

    def quality_report(self, papers: list[PaperRecord]) -> str:
        """Generate a data quality report."""
        if not papers:
            return "No papers collected."

        qualities = [p.data_quality for p in papers]
        avg = sum(qualities) / len(qualities)
        excellent = sum(1 for q in qualities if q >= 8)
        good = sum(1 for q in qualities if 5 <= q < 8)
        poor = sum(1 for q in qualities if q < 5)

        fields = ["title", "authors", "year", "journal", "abstract", "keywords", "doi", "body_text"]
        field_stats = {}
        for f in fields:
            count = sum(1 for p in papers if getattr(p, f, None))
            field_stats[f] = f"{count}/{len(papers)}"

        lines = [
            "=" * 60,
            "Data Quality Report",
            "=" * 60,
            f"Total papers: {len(papers)}",
            f"Avg quality: {avg:.1f}/10",
            f"Excellent (8+): {excellent}",
            f"Good (5-7): {good}",
            f"Poor (<5): {poor}",
            "",
            "Field completeness:",
        ]
        for f, s in field_stats.items():
            lines.append(f"  {f:15s}: {s}")
        lines.append("")
        lines.append("Sources:")
        for source, count in self._stats.items():
            lines.append(f"  {source}: {count}")

        return "\n".join(lines)
