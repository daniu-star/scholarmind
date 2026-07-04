"""Journal homepage crawler — extracts issue list for 2016-2026."""

from __future__ import annotations

import asyncio
import structlog
import random
from typing import Optional, TYPE_CHECKING

from crawler.cnki_navigator import CNKINavigator
from models.journal import Journal, Issue

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = structlog.get_logger()


class JournalCrawler:
    """Crawls a CNKI journal homepage to extract issues for 2016-2026."""

    def __init__(self, navigator: Optional[CNKINavigator] = None):
        self.navigator = navigator or CNKINavigator()

    async def crawl_journal(
        self, page: "Page", journal: Journal
    ) -> list[Issue]:
        """Navigate to journal homepage and extract all issues for 2016-2026.

        Returns a list of Issue objects with URLs ready for crawling.
        """
        issues: list[Issue] = []

        if not journal.navi_url:
            logger.error("journal_no_url", journal=journal.name)
            return issues

        # Navigate to journal homepage
        success = await self.navigator.safe_navigate(
            page,
            journal.navi_url,
            wait_selector=".year-list, .issue-list, .journal-year, [class*='year']",
        )

        if not success:
            logger.error("journal_navigate_failed", journal=journal.name)
            return issues

        # Dismiss any popups
        await self.navigator.dismiss_overlays(page)

        # Extract issues using page.evaluate for the React-rendered content
        try:
            year_start, year_end = journal.year_range

            issues = await page.evaluate(f"""
                () => {{
                    const issues = [];
                    const yearStart = {year_start};
                    const yearEnd = {year_end};

                    // CNKI journal pages typically render year nodes with data-year
                    // or year sections containing issue links
                    document.querySelectorAll('[data-year], .year-item, .year-section, [class*="year"]').forEach(yearEl => {{
                        const yearText = (yearEl.getAttribute('data-year') || yearEl.textContent || '').trim();
                        const yearMatch = yearText.match(/(\\d{{4}})/);
                        if (!yearMatch) return;
                        const year = parseInt(yearMatch[1]);
                        if (year < yearStart || year > yearEnd) return;

                        // Find issue links within this year section
                        yearEl.querySelectorAll('a[href*="issue"], a[href*="detail"], a[href]').forEach(link => {{
                            const href = link.href || '';
                            const text = (link.textContent || '').trim();

                            // Only include links that look like issue links
                            if (href.includes('issue') || href.includes('Detail') || /第.*期/.test(text) || /\\d{{4}}\\s*No\\./.test(text)) {{
                                let issueNumber = text.replace(/第|期/g, '').trim();
                                if (!issueNumber) {{
                                    const match = text.match(/No\\.?\s*(\\d+)/);
                                    if (match) issueNumber = match[1];
                                }}
                                if (!issueNumber) issueNumber = text.replace(/\\s+/g, '').slice(-4);

                                issues.push({{
                                    journal_name: '{journal.name}',
                                    discipline: '{journal.discipline}',
                                    year: year,
                                    number: issueNumber,
                                    url: href,
                                    description: text,
                                    paper_count: 0
                                }});
                            }}
                        }});
                    }});

                    // Alternative: look for flat issue list (some journal pages)
                    if (issues.length === 0) {{
                        document.querySelectorAll('a[href*="knavi"], a[href*="journal"], a[href*="detail"]').forEach(link => {{
                            const href = link.href || '';
                            const text = (link.textContent || '').trim();
                            const yearMatch = text.match(/(\\d{{4}})/);
                            if (yearMatch) {{
                                const year = parseInt(yearMatch[1]);
                                if (year >= yearStart && year <= yearEnd) {{
                                    const numberMatch = text.match(/第\s*(\\d+)\\s*期|No\\.?\s*(\\d+)/);
                                    const number = numberMatch ? (numberMatch[1] || numberMatch[2]) : '';
                                    issues.push({{
                                        journal_name: '{journal.name}',
                                        discipline: '{journal.discipline}',
                                        year: year,
                                        number: number,
                                        url: href,
                                        description: text,
                                        paper_count: 0
                                    }});
                                }}
                            }}
                        }});
                    }}

                    return issues;
                }}
            """)


            # Convert to Issue objects
            result: list[Issue] = []
            for iss_data in issues:
                try:
                    issue = Issue(
                        journal_name=iss_data.get("journal_name", journal.name),
                        discipline=iss_data.get("discipline", journal.discipline),
                        year=int(iss_data.get("year", 0)),
                        number=str(iss_data.get("number", "")),
                        url=str(iss_data.get("url", "")),
                        description=str(iss_data.get("description", "")),
                    )
                    result.append(issue)
                except Exception as e:
                    logger.debug("issue_parse_error", error=str(e), data=str(iss_data)[:100])
                    continue

            # Sort by year descending, then by issue number
            result.sort(key=lambda x: (x.year, x.number), reverse=True)

        except Exception as e:
            logger.error("journal_extract_failed", journal=journal.name, error=str(e))

        logger.info(
            "journal_crawled",
            journal=journal.name,
            issues_found=len(result),
            year_range=f"{journal.year_range[0]}-{journal.year_range[1]}",
        )

        return result


# Global singleton
journal_crawler = JournalCrawler()
