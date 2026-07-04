"""Complete CNKI paper pipeline: RSS discovery -> metadata -> download URL extraction.

This module uses aiohttp + institutional cookies and works WITHOUT browser automation.
The final PDF download step requires browser JS execution (handled separately).
"""

import asyncio, re, os, json, hashlib
from pathlib import Path
from datetime import datetime
from xml.etree import ElementTree as ET
from dataclasses import dataclass, field, asdict
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup


@dataclass
class PaperMetadata:
    """Complete paper metadata extracted from CNKI."""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int = 0
    journal_name: str = ""
    discipline: str = ""
    issue_number: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    doi: str = ""
    filename: str = ""
    dbcode: str = ""
    paper_url: str = ""
    pdf_order_url: str = ""
    caj_order_url: str = ""
    auth_check_url: str = ""
    downloaded: bool = False
    file_path: str = ""
    file_format: str = ""
    file_size: int = 0


class CNKIPipeline:
    """Complete CNKI paper acquisition pipeline using RSS + aiohttp."""

    def __init__(self, cookies_raw: str, output_base: str = "../数据库/cnki"):
        self.cookies_raw = cookies_raw
        self.output_base = Path(output_base)
        self.output_base.mkdir(parents=True, exist_ok=True)
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def headers(self):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Cookie': self.cookies_raw,
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.headers)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── RSS Paper Discovery ─────────────────────────────────

    async def get_papers_from_rss(
        self, journal_code: str, max_papers: int = 20
    ) -> list[dict]:
        """Get latest papers from a journal via RSS feed.

        Args:
            journal_code: CNKI journal product code (e.g., 'GJXW' for 国际新闻界)
            max_papers: Maximum papers to return (RSS returns 20 max)

        Returns:
            List of dicts with title, link, author, description
        """
        session = await self._get_session()
        url = f'https://rss.cnki.net/knavi/rss/{journal_code}?pcode=CJFD,CCJD'

        async with session.get(url, ssl=False) as resp:
            rss_xml = await resp.text()

        root = ET.fromstring(rss_xml)
        papers = []
        for item in root.findall('.//item')[:max_papers]:
            papers.append({
                'title': (item.findtext('title', '') or '').strip(),
                'link': (item.findtext('link', '') or '').strip(),
                'author': (item.findtext('author', '') or '').strip(),
                'description': (item.findtext('description', '') or '').strip(),
                'pub_date': (item.findtext('pubDate', '') or '').strip(),
            })
        return papers

    # ── Paper Detail Extraction ────────────────────────────

    async def get_paper_metadata(self, paper_url: str, discipline: str = "") -> PaperMetadata:
        """Extract full metadata from a paper's detail page.

        Args:
            paper_url: Full URL from RSS feed
            discipline: Research discipline for categorization

        Returns:
            PaperMetadata with all extracted fields
        """
        session = await self._get_session()
        meta = PaperMetadata(paper_url=paper_url, discipline=discipline)

        async with session.get(paper_url, ssl=False, allow_redirects=True) as resp:
            html = await resp.text()

        soup = BeautifulSoup(html, 'html.parser')

        # Title
        title_el = soup.select_one('h1, .title, [class*="title"]')
        if title_el:
            meta.title = title_el.get_text(strip=True)

        # Abstract
        abstract_el = soup.select_one('.abstract-text, [class*="abstract"], #abstract')
        if abstract_el:
            meta.abstract = abstract_el.get_text(strip=True)[:2000]

        # Keywords
        for kw in soup.select('.keywords a, [class*="keyword"] a'):
            text = kw.get_text(strip=True).rstrip(';')
            if text and len(text) > 1:
                meta.keywords.append(text)

        # DOI
        doi_match = re.search(r'10\.\d{4,}/[^\s"\'<&]+', html)
        if doi_match:
            meta.doi = doi_match.group(0)

        # Filename & dbcode (for constructing download URLs)
        fn_match = re.search(r'filename=([^&"\'\s]+)', html)
        if fn_match:
            meta.filename = fn_match.group(1)

        db_match = re.search(r'dbcode=([^&"\'\s]+)', html)
        if db_match:
            meta.dbcode = db_match.group(1)

        # Authors
        author_el = soup.select_one('.author, [class*="author"]')
        if author_el:
            author_text = author_el.get_text(strip=True)
            meta.authors = [a.strip() for a in author_text.replace('\n', ';').split(';') if a.strip()]

        # Year
        year_match = re.search(r'(?:year|date|年)[:\s]*(\d{4})', html)
        if year_match:
            meta.year = int(year_match.group(1))

        # Journal name
        journal_el = soup.select_one('.source, [class*="source"], .journal')
        if journal_el:
            meta.journal_name = journal_el.get_text(strip=True)

        # Download order URLs
        order_match = re.findall(
            r'bar\.cnki\.net/bar/download/order\?id=([^"\'&\s]+)', html
        )
        # CNKI detail page has 2 order URLs: one for PDF, one for CAJ
        if len(order_match) >= 1:
            meta.pdf_order_url = f'https://bar.cnki.net/bar/download/order?id={order_match[0]}'
        if len(order_match) >= 2:
            meta.caj_order_url = f'https://bar.cnki.net/bar/download/order?id={order_match[1]}'

        # Auth-check URL (alternative download path)
        auth_match = re.search(
            r'https://x\.cnki\.net/web/page/auth-check\?[^"\'\s]+',
            html
        )
        if auth_match:
            meta.auth_check_url = auth_match.group(0).replace('&amp;', '&')

        return meta

    # ── Journal Crawl (All Issues) ─────────────────────────

    async def crawl_journal(
        self,
        journal_code: str,
        journal_name: str,
        discipline: str,
        max_papers: int = 500,
    ) -> list[PaperMetadata]:
        """Crawl papers from a journal via RSS (latest papers).

        Note: RSS returns ~20 latest papers. For historical papers (2016-2026),
        use the search-based approach or batch processing.

        Args:
            journal_code: CNKI journal code
            journal_name: Human-readable journal name
            discipline: Research discipline
            max_papers: Maximum papers to return

        Returns:
            List of PaperMetadata objects
        """
        papers = await self.get_papers_from_rss(journal_code, min(max_papers, 20))
        print(f'  RSS returned {len(papers)} papers for {journal_name}')

        results = []
        for i, paper in enumerate(papers):
            if len(results) >= max_papers:
                break

            print(f'  [{i+1}/{len(papers)}] {paper["title"][:50]}...')
            try:
                meta = await self.get_paper_metadata(paper['link'], discipline)
                meta.journal_name = journal_name

                if not meta.title:
                    meta.title = paper['title']
                if not meta.authors and paper['author']:
                    meta.authors = [a.strip() for a in paper['author'].split(';') if a.strip()]

                results.append(meta)
            except Exception as e:
                print(f'    Error: {e}')
                continue

            await asyncio.sleep(0.5)  # Rate limiting

        return results

    # ── Save Results ───────────────────────────────────────

    def save_metadata(self, papers: list[PaperMetadata], output_dir: Optional[Path] = None):
        """Save paper metadata as JSON files."""
        if output_dir is None:
            output_dir = self.output_base

        for paper in papers:
            if not paper.title:
                continue

            safe_dir = re.sub(r'[<>:"/\\|?*]', '_', paper.journal_name or 'unknown')[:50]
            paper_dir = output_dir / (paper.discipline or 'papers') / safe_dir / str(paper.year or datetime.now().year)
            paper_dir.mkdir(parents=True, exist_ok=True)

            safe_title = re.sub(r'[<>:"/\\|?*]', '_', paper.title)[:80]
            meta_path = paper_dir / f'{safe_title}_metadata.json'
            meta_path.write_text(
                json.dumps(asdict(paper), ensure_ascii=False, indent=2),
                encoding='utf-8'
            )

            if paper.doi:
                paper_dir.joinpath('dois.txt').open('a', encoding='utf-8').write(
                    f'{paper.doi}\n'
                )

            # Write download URL list for browser-based download
            if paper.pdf_order_url or paper.caj_order_url:
                dl_list = paper_dir / 'download_urls.txt'
                with dl_list.open('a', encoding='utf-8') as f:
                    f.write(f'# {paper.title[:60]}\n')
                    if paper.pdf_order_url:
                        f.write(f'PDF: {paper.pdf_order_url}\n')
                    if paper.caj_order_url:
                        f.write(f'CAJ: {paper.caj_order_url}\n')
                    f.write('\n')

        print(f'Saved {len(papers)} papers to {output_dir}')

    # ── Batch Download ─────────────────────────────────────

    async def download_all_journals(
        self,
        journal_list: list[tuple[str, str, str]],
        papers_per_journal: int = 20,
    ) -> dict[str, list[PaperMetadata]]:
        """Download metadata for multiple journals.

        Args:
            journal_list: List of (code, name, discipline) tuples
            papers_per_journal: Papers per journal

        Returns:
            Dict of discipline -> list of PaperMetadata
        """
        all_results = {}

        for code, name, discipline in journal_list:
            print(f'\n{"="*60}')
            print(f'Journal: {name} ({code}) - {discipline}')
            print(f'{"="*60}')

            papers = await self.crawl_journal(code, name, discipline, papers_per_journal)
            self.save_metadata(papers)

            if discipline not in all_results:
                all_results[discipline] = []
            all_results[discipline].extend(papers)

            print(f'  Completed: {len(papers)} papers from {name}')

        return all_results

    def generate_download_list(self, papers: list[PaperMetadata]) -> str:
        """Generate a text file with all download URLs for browser-based batch downloading."""
        lines = [
            '# CNKI Paper Download List',
            f'# Generated: {datetime.now().isoformat()}',
            f'# Total papers: {len(papers)}',
            f'# Instructions: Open each URL below in your browser to download',
            '',
        ]

        for paper in papers:
            lines.append(f'## {paper.title}')
            lines.append(f'  Authors: {"; ".join(paper.authors)}')
            lines.append(f'  Journal: {paper.journal_name}')
            lines.append(f'  DOI: {paper.doi}')
            if paper.pdf_order_url:
                lines.append(f'  PDF: {paper.pdf_order_url}')
            if paper.caj_order_url:
                lines.append(f'  CAJ: {paper.caj_order_url}')
            lines.append('')

        return '\n'.join(lines)
