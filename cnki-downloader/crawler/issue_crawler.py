"""Issue page crawler — extracts paper list from a journal issue page."""

from __future__ import annotations

import asyncio
import structlog
import random
from typing import Optional, TYPE_CHECKING

from crawler.cnki_navigator import CNKINavigator
from models.journal import Issue

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = structlog.get_logger()


class IssueCrawler:
    """Crawls a specific journal issue page to extract paper metadata."""

    def __init__(self, navigator: Optional[CNKINavigator] = None):
        self.navigator = navigator or CNKINavigator()

    async def crawl_issue(
        self, page: "Page", issue: Issue
    ) -> list[dict]:
        """Navigate to an issue page and extract all paper metadata.

        Returns list of dicts with: title, authors, year, paper_url, abstract_preview
        """
        papers: list[dict] = []

        if not issue.url:
            logger.error("issue_no_url", issue=issue.display_name)
            return papers

        # Navigate to issue page
        success = await self.navigator.safe_navigate(
            page,
            issue.url,
            wait_selector=".result-table-list, .paper-list, table, [class*='result'], [class*='paper']",
        )

        if not success:
            logger.error("issue_navigate_failed", issue=issue.display_name)
            return papers

        await self.navigator.dismiss_overlays(page)

        # Handle pagination — some issues have 50+ papers
        all_papers: list[dict] = []
        page_num = 0
        max_pages = 10  # Safety limit

        while page_num < max_pages:
            page_papers = await self._extract_papers_from_current_page(page, issue)
            all_papers.extend(page_papers)

            # Check for next page
            next_url = await self.navigator.handle_pagination(page)
            if not next_url:
                break

            # Navigate to next page
            success = await self.navigator.safe_navigate(page, next_url)
            if not success:
                break

            page_num += 1
            await asyncio.sleep(random.uniform(2, 5))

        # Update issue paper count
        issue.paper_count = len(all_papers)

        logger.info(
            "issue_crawled",
            issue=issue.display_name,
            papers_found=len(all_papers),
            pages=page_num + 1,
        )

        return all_papers

    async def _extract_papers_from_current_page(
        self, page: "Page", issue: Issue
    ) -> list[dict]:
        """Extract paper metadata from the currently loaded issue page."""
        papers: list[dict] = []

        try:
            papers = await page.evaluate(f"""
                () => {{
                    const papers = [];
                    const year = {issue.year};
                    const journalName = '{issue.journal_name}';
                    const discipline = '{issue.discipline}';
                    const issueNumber = '{issue.number}';

                    // Strategy 1: CNKI result table (standard layout)
                    document.querySelectorAll('tr.result-table-list, tr[class*="result"]').forEach(row => {{
                        const titleEl = row.querySelector('a.fz14, a[class*="title"], td.name a, td[class*="title"] a');
                        const authorEl = row.querySelector('td.author, td[class*="author"]');
                        const sourceEl = row.querySelector('td.source, td[class*="source"]');
                        const dateEl = row.querySelector('td.date, td[class*="date"]');
                        const abstractEl = row.querySelector('.abstract, [class*="abstract"]');

                        if (titleEl) {{
                            papers.push({{
                                title: (titleEl.textContent || '').trim().replace(/\\s+/g, ' '),
                                paper_url: titleEl.href || '',
                                authors: (authorEl ? authorEl.textContent || '' : '').trim(),
                                source: (sourceEl ? sourceEl.textContent || '' : '').trim(),
                                year: year,
                                journal_name: journalName,
                                discipline: discipline,
                                issue_number: issueNumber,
                                abstract_preview: (abstractEl ? abstractEl.textContent || '' : '').trim().slice(0, 500)
                            }});
                        }}
                    }});

                    // Strategy 2: Generic paper list (alternative layouts)
                    if (papers.length === 0) {{
                        document.querySelectorAll('li[class*="paper"], div[class*="paper-item"], .paper-card, article[class*="paper"]').forEach(el => {{
                            const titleEl = el.querySelector('a, h3, h4, .title');
                            const authorEl = el.querySelector('.author, [class*="author"]');
                            const linkEl = el.querySelector('a[href]');

                            if (titleEl && linkEl) {{
                                papers.push({{
                                    title: (titleEl.textContent || '').trim().replace(/\\s+/g, ' '),
                                    paper_url: linkEl.href || '',
                                    authors: (authorEl ? authorEl.textContent || '' : '').trim(),
                                    source: journalName,
                                    year: year,
                                    journal_name: journalName,
                                    discipline: discipline,
                                    issue_number: issueNumber,
                                    abstract_preview: ''
                                }});
                            }}
                        }});
                    }}

                    // Strategy 3: Any link within content area (desperate fallback)
                    if (papers.length === 0) {{
                        const contentArea = document.querySelector('.content, .main, article, #content, [class*="content"]');
                        if (contentArea) {{
                            contentArea.querySelectorAll('a[href*="article"], a[href*="detail"], a[href*="abstract"]').forEach(link => {{
                                const text = (link.textContent || '').trim();
                                if (text.length > 10) {{  // Likely a paper title
                                    papers.push({{
                                        title: text.replace(/\\s+/g, ' '),
                                        paper_url: link.href || '',
                                        authors: '',
                                        source: journalName,
                                        year: year,
                                        journal_name: journalName,
                                        discipline: discipline,
                                        issue_number: issueNumber,
                                        abstract_preview: ''
                                    }});
                                }}
                            }});
                        }}
                    }}

                    return papers;
                }}
            """)

        except Exception as e:
            logger.error("issue_extract_papers_failed", error=str(e))

        # Filter out non-paper entries
        papers = [
            p for p in papers
            if p.get("title") and len(p.get("title", "")) > 5 and p.get("paper_url")
        ]

        return papers
