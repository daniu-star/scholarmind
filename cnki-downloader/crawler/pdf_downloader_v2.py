"""PDF download via DOI from multiple sources (Sci-Hub, Unpaywall, etc.).

This bypasses CNKI's JS auth chain by using alternative academic paper sources.
"""

import asyncio, re, os, hashlib
from pathlib import Path
from typing import Optional
import aiohttp


class MultiSourceDownloader:
    """Download PDFs from multiple academic sources using DOI."""

    SCIHUB_DOMAINS = [
        'https://sci-hub.se',
        'https://sci-hub.st',
        'https://sci-hub.ru',
    ]

    def __init__(self, output_dir: str = 'downloads'):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def download_by_doi(
        self, doi: str, title: str = '', source: str = 'scihub'
    ) -> Optional[str]:
        """Download a paper PDF by its DOI.

        Returns the file path on success, None on failure.
        """
        if not doi:
            return None

        if source == 'scihub':
            return await self._download_scihub(doi, title)
        elif source == 'unpaywall':
            return await self._download_unpaywall(doi, title)
        else:
            # Try all sources
            for src in ['scihub', 'unpaywall']:
                path = await self.download_by_doi(doi, title, src)
                if path:
                    return path
            return None

    async def _download_scihub(self, doi: str, title: str) -> Optional[str]:
        """Download PDF from Sci-Hub."""
        session = await self._get_session()

        for domain in self.SCIHUB_DOMAINS:
            try:
                scihub_url = f'{domain}/{doi}'
                print(f'  Trying Sci-Hub: {scihub_url[:80]}')

                async with session.get(
                    scihub_url, ssl=False, allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    html = await resp.text()

                    # Sci-Hub embeds the PDF URL in the page
                    # Look for iframe or embed with PDF
                    pdf_url = None

                    # Pattern 1: iframe src
                    iframe_match = re.search(r'<iframe[^>]*src\s*=\s*["\']([^"\']+\.pdf[^"\']*)["\']', html, re.IGNORECASE)
                    if iframe_match:
                        pdf_url = iframe_match.group(1)
                        if pdf_url.startswith('//'):
                            pdf_url = 'https:' + pdf_url
                        elif pdf_url.startswith('/'):
                            pdf_url = domain + pdf_url

                    # Pattern 2: embed src
                    if not pdf_url:
                        embed_match = re.search(r'<embed[^>]*src\s*=\s*["\']([^"\']+\.pdf[^"\']*)["\']', html, re.IGNORECASE)
                        if embed_match:
                            pdf_url = embed_match.group(1)
                            if pdf_url.startswith('//'):
                                pdf_url = 'https:' + pdf_url
                            elif pdf_url.startswith('/'):
                                pdf_url = domain + pdf_url

                    # Pattern 3: button/link with download
                    if not pdf_url:
                        btn_match = re.search(r'(?:onclick|href)\s*=\s*["\']([^"\']*(?:download|\.pdf)[^"\']*)["\']', html, re.IGNORECASE)
                        if btn_match:
                            pdf_url = btn_match.group(1)
                            if not pdf_url.startswith('http'):
                                pdf_url = domain + ('/' if not pdf_url.startswith('/') else '') + pdf_url

                    # Pattern 4: Direct link to PDF
                    if not pdf_url:
                        link_match = re.search(r'href\s*=\s*["\'](https?://[^"\']+\.pdf)["\']', html)
                        if link_match:
                            pdf_url = link_match.group(1)

                    if pdf_url:
                        print(f'  Found PDF URL: {pdf_url[:120]}')
                        return await self._download_pdf(pdf_url, doi, title, domain)

                    # Check if Sci-Hub returned error page
                    if 'article not found' in html.lower() or 'not found' in html.lower():
                        print(f'  Paper not available on Sci-Hub')
                        continue

                    print(f'  No PDF URL found in Sci-Hub response ({len(html)} bytes)')

            except asyncio.TimeoutError:
                print(f'  Sci-Hub timeout for {domain}')
            except Exception as e:
                print(f'  Sci-Hub error: {str(e)[:80]}')

        return None

    async def _download_unpaywall(self, doi: str, title: str) -> Optional[str]:
        """Try to find open-access PDF via Unpaywall."""
        session = await self._get_session()

        try:
            url = f'https://api.unpaywall.org/v2/{doi}?email=research@scholarmind.ai'
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

            best = data.get('best_oa_location') or {}
            pdf_url = best.get('url_for_pdf') or best.get('url') or ''

            if pdf_url:
                print(f'  Found OA PDF via Unpaywall: {pdf_url[:120]}')
                return await self._download_pdf(pdf_url, doi, title)

            # Check other OA locations
            for loc in data.get('oa_locations', [])[:3]:
                pdf_url = loc.get('url_for_pdf', '')
                if pdf_url:
                    return await self._download_pdf(pdf_url, doi, title)

        except Exception as e:
            print(f'  Unpaywall error: {str(e)[:80]}')
        return None

    async def _download_pdf(
        self, pdf_url: str, doi: str, title: str, referer: str = ''
    ) -> Optional[str]:
        """Download the actual PDF file."""
        session = await self._get_session()
        headers = {}
        if referer:
            headers['Referer'] = referer

        try:
            async with session.get(
                pdf_url, headers=headers, ssl=False, allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                body = await resp.read()

                if body[:4] != b'%PDF':
                    # Not a PDF - might be HTML or error
                    if len(body) < 200:
                        print(f'  Response is not PDF: {body[:100]}')
                    else:
                        print(f'  Response is not PDF ({len(body)} bytes)')
                    return None

                # Valid PDF - save it
                safe_name = re.sub(r'[<>:\"/\\|?*]', '_', title or doi)[:100]
                filepath = self.output_dir / f'{safe_name}.pdf'

                # Avoid overwriting
                if filepath.exists():
                    safe_name = re.sub(r'[<>:\"/\\|?*]', '_', doi.replace('/', '_'))[:80]
                    filepath = self.output_dir / f'{safe_name}.pdf'

                filepath.write_bytes(body)

                # Verify
                size = filepath.stat().st_size
                if size < 10000:  # Less than 10KB is suspicious
                    print(f'  WARNING: PDF too small ({size} bytes), might be corrupted')
                    filepath.unlink(missing_ok=True)
                    return None

                # Verify it's a real PDF by checking for %%EOF
                if b'%%EOF' not in body[-100:]:
                    print(f'  WARNING: PDF missing EOF marker')

                checksum = hashlib.sha256(body).hexdigest()[:12]
                print(f'  >>> PDF SAVED: {filepath.name} ({size} bytes, sha256={checksum}) <<<')
                return str(filepath)

        except asyncio.TimeoutError:
            print(f'  PDF download timeout')
        except Exception as e:
            print(f'  PDF download error: {str(e)[:80]}')

        return None

    async def batch_download(
        self, papers: list[dict], source: str = 'all'
    ) -> dict[str, str]:
        """Download PDFs for multiple papers.

        Args:
            papers: List of dicts with 'doi', 'title' keys
            source: 'scihub', 'unpaywall', or 'all'

        Returns:
            Dict of doi -> filepath
        """
        results = {}
        for i, paper in enumerate(papers):
            doi = paper.get('doi', '')
            title = paper.get('title', f'paper_{i}')
            if not doi:
                continue

            print(f'\n[{i+1}/{len(papers)}] {title[:60]}')
            print(f'  DOI: {doi}')

            filepath = await self.download_by_doi(doi, title, source)
            if filepath:
                results[doi] = filepath

            await asyncio.sleep(1)  # Rate limiting

        return results
