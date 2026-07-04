"""Paper detail page crawler — extracts full metadata and download URL."""

from __future__ import annotations

import asyncio
import structlog
import random
import re
from typing import Optional, TYPE_CHECKING

from crawler.cnki_navigator import CNKINavigator

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = structlog.get_logger()


class PaperCrawler:
    """Crawls a single CNKI paper detail page for metadata and download URL."""

    def __init__(self, navigator: Optional[CNKINavigator] = None):
        self.navigator = navigator or CNKINavigator()

    async def crawl_paper(
        self, page: "Page", paper_url: str, paper_info: dict
    ) -> dict:
        """Navigate to paper detail page and extract full metadata.

        Args:
            page: Playwright page
            paper_url: CNKI paper detail page URL
            paper_info: Basic info from issue page (title, authors, etc.)

        Returns:
            dict with full metadata + download_url
        """
        result = {
            **paper_info,
            "abstract": "",
            "keywords": [],
            "doi": "",
            "download_url": "",
            "file_format": "",
            "author_affiliations": [],
            "funding": "",
            "cnki_url": paper_url,
        }

        if not paper_url:
            logger.error("paper_no_url")
            return result

        # Navigate to paper detail page
        success = await self.navigator.safe_navigate(
            page,
            paper_url,
            wait_selector=".abstract-text, .detail-content, [class*='abstract'], [class*='detail']",
        )

        if not success:
            logger.error("paper_navigate_failed", url=paper_url[:80])
            return result

        await self.navigator.dismiss_overlays(page)

        # Extract metadata
        try:
            metadata = await page.evaluate("""
                () => {
                    const result = {
                        abstract: '',
                        keywords: [],
                        doi: '',
                        download_url: '',
                        download_urls: [],
                        author_affiliations: [],
                        funding: '',
                        file_format: '',
                    };

                    // Extract abstract
                    const abstractEl = document.querySelector('.abstract-text, [class*="abstract"], #abstract, .abstract, .row-abstract');
                    if (abstractEl) {
                        result.abstract = (abstractEl.textContent || '').trim().replace(/\\s+/g, ' ');
                        // Clean up common prefixes
                        result.abstract = result.abstract.replace(/^[摘\\s]*要[：:\\s]*/, '').trim();
                    }

                    // Extract keywords
                    document.querySelectorAll('.keywords a, .keyword, [class*="keyword"] a, [class*="keywords"] a').forEach(el => {
                        const kw = (el.textContent || '').trim();
                        if (kw && kw.length > 1 && kw.length < 30) {
                            result.keywords.push(kw);
                        }
                    });

                    // Extract DOI
                    const doiEl = document.querySelector('[class*="doi"], .doi, a[href*="doi.org"]');
                    if (doiEl) {
                        const doiText = (doiEl.textContent || doiEl.href || '').trim();
                        const doiMatch = doiText.match(/10\\.\\d{4,}\\/[^\\s"<>]+/);
                        if (doiMatch) result.doi = doiMatch[0];
                    }

                    // Find PDF download link
                    // Strategy 1: Direct PDF download button
                    const pdfSelectors = [
                        'a:has-text("PDF下载")', 'a:has-text("pdf下载")',
                        'a[href*="download"]', 'a[class*="download-pdf"]',
                        'a:has-text("下载")', '[class*="btn-pdf"]', '[class*="pdf-btn"]',
                        'a[onclick*="download"]', 'a[href$=".pdf"]',
                    ];

                    for (const sel of pdfSelectors) {
                        try {
                            const el = document.querySelector(sel);
                            if (el && el.href) {
                                if (!result.download_urls.includes(el.href)) {
                                    result.download_urls.push(el.href);
                                }
                            }
                        } catch(e) {}
                    }

                    // Strategy 2: Find download links in the page structure
                    document.querySelectorAll('a').forEach(a => {
                        const text = (a.textContent || '').toLowerCase();
                        const href = (a.href || '').toLowerCase();
                        if (
                            (text.includes('pdf') || text.includes('下载') || text.includes('download') || text.includes('全文')) &&
                            !result.download_urls.includes(a.href)
                        ) {
                            result.download_urls.push(a.href);
                        }
                        if (
                            (href.includes('download') || href.includes('.pdf')) &&
                            !result.download_urls.includes(a.href)
                        ) {
                            result.download_urls.push(a.href);
                        }
                    });

                    // Strategy 3: CAJ format link
                    document.querySelectorAll('a').forEach(a => {
                        const text = (a.textContent || '').toLowerCase();
                        const href = (a.href || '').toLowerCase();
                        if (
                            (text.includes('caj') || href.includes('caj') || text.includes('整本')) &&
                            !result.download_urls.includes(a.href)
                        ) {
                            result.download_urls.push(a.href);
                        }
                    });

                    // Select best download URL (prefer PDF over CAJ)
                    const pdfUrls = result.download_urls.filter(u => u.includes('pdf') || u.includes('download'));
                    const cajUrls = result.download_urls.filter(u => u.includes('caj'));
                    if (pdfUrls.length > 0) {
                        result.download_url = pdfUrls[0];
                        result.file_format = 'pdf';
                    } else if (cajUrls.length > 0) {
                        result.download_url = cajUrls[0];
                        result.file_format = 'caj';
                    } else if (result.download_urls.length > 0) {
                        result.download_url = result.download_urls[0];
                    }

                    // Extract author affiliations
                    document.querySelectorAll('.author-affiliation, [class*="affiliation"], .org, [class*="org"]').forEach(el => {
                        const text = (el.textContent || '').trim();
                        if (text && text.length > 3) result.author_affiliations.push(text);
                    });

                    // Extract funding info
                    const fundingEl = document.querySelector('[class*="fund"], .fund, .funding');
                    if (fundingEl) {
                        result.funding = (fundingEl.textContent || '').trim();
                    }

                    return result;
                }
            """)

            result.update(metadata)

            # Clean up abstract
            if result.get("abstract"):
                result["abstract"] = result["abstract"].strip()[:2000]

            # Normalize download URL
            download_url = result.get("download_url", "")
            if download_url and not download_url.startswith("http"):
                download_url = f"https://kns.cnki.net{download_url}"
                result["download_url"] = download_url

        except Exception as e:
            logger.error("paper_extract_failed", url=paper_url[:60], error=str(e))

        logger.info(
            "paper_crawled",
            title=(result.get("title", ""))[:40],
            has_abstract=bool(result.get("abstract")),
            has_download=bool(result.get("download_url")),
            file_format=result.get("file_format", ""),
        )

        return result
