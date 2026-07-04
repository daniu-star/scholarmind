"""Dynamic CSS selector detection for CNKI's frequently-changing React UI.

CNKI updates its frontend periodically, which breaks hardcoded CSS selectors.
This module tests known selector patterns at runtime and returns the first
one that matches, providing a self-healing mechanism against UI changes.
"""

from __future__ import annotations

import structlog
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = structlog.get_logger()


class SelectorRegistry:
    """Tests and returns active CSS selectors for CNKI's current page structure.

    Each selector list is ordered by confidence — the first selector is the
    most recently verified pattern, and later ones are fallbacks for older
    or alternative page layouts.
    """

    # ── Search Result Selectors ───────────────────────────

    SEARCH_RESULT_ROWS = [
        (".result-table-list", 0.9, "standard-table"),
        ("tr[class*='result']", 0.7, "generic-result-row"),
        ("[class*='search-result']", 0.6, "search-result-container"),
        ("tr:has(td.name)", 0.5, "name-column-fallback"),
        ("[class*='result-item']", 0.4, "result-item-card"),
    ]

    TITLE_SELECTORS = [
        ("a.fz14", 0.9, "standard-title"),
        ("td.name a", 0.8, "name-cell-link"),
        ("td[class*='name'] a", 0.7, "generic-name-link"),
        ("a[target='_blank']:not([href*='javascript'])", 0.5, "any-blank-link"),
        ("a[href*='detail']", 0.3, "detail-link-fallback"),
    ]

    AUTHOR_SELECTORS = [
        ("td.author", 0.9, "standard-author"),
        ("td[class*='author']", 0.8, "generic-author"),
        ("[class*='author']", 0.5, "any-author"),
    ]

    SOURCE_SELECTORS = [
        ("td.source", 0.9, "standard-source"),
        ("td[class*='source']", 0.8, "generic-source"),
        ("[class*='source']", 0.5, "any-source"),
    ]

    # ── Paper Detail Selectors ────────────────────────────

    ABSTRACT_SELECTORS = [
        (".abstract-text", 0.9, "standard-abstract"),
        ("#abstract", 0.8, "abstract-id"),
        ("[class*='abstract']:not([class*='label'])", 0.7, "generic-abstract"),
        ("div.row:has(span:has-text('摘要'))", 0.6, "label-abstract-row"),
    ]

    KEYWORD_SELECTORS = [
        (".keywords a", 0.9, "standard-keywords"),
        (".keyword", 0.8, "generic-keyword"),
        ("[class*='keyword']", 0.7, "any-keyword"),
        ("a[class*='kw']", 0.5, "kw-link"),
    ]

    DOI_SELECTORS = [
        ("[class*='doi']", 0.9, "doi-class"),
        ("a[href*='doi.org']", 0.8, "doi-link"),
        ("span:has-text('DOI')", 0.6, "doi-label"),
    ]

    DOWNLOAD_SELECTORS = [
        ("a:has-text('PDF下载')", 0.95, "pdf-download-exact"),
        ("a:has-text('PDF')", 0.9, "pdf-link"),
        ("a[href*='download']", 0.8, "download-href"),
        ("[class*='btn-pdf']", 0.7, "btn-pdf-class"),
        ("a:has-text('下载')", 0.6, "download-text"),
        ("a:has-text('全文')", 0.5, "fulltext-link"),
    ]

    # ── Journal/Issue Selectors ───────────────────────────

    YEAR_SELECTORS = [
        ("[data-year]", 0.9, "data-year-attr"),
        (".year-item", 0.8, "year-item-class"),
        ("[class*='year']", 0.6, "generic-year"),
        (".year-section", 0.5, "year-section"),
    ]

    ISSUE_SELECTORS = [
        ("[data-issue]", 0.9, "data-issue-attr"),
        (".issue-item a", 0.8, "issue-item-link"),
        ("a:has-text('期')", 0.7, "issue-text-link"),
        ("[class*='issue'] a", 0.6, "generic-issue-link"),
    ]

    PAGINATION_SELECTORS = [
        ("a:has-text('下一页')", 0.9, "next-page-cn"),
        ("a:has-text('>')", 0.7, "next-arrow"),
        (".next a:not([class*='disabled'])", 0.7, "next-class"),
        ("[class*='pagination'] [class*='next']", 0.6, "pagination-next"),
    ]

    # ── CAPTCHA Selectors ─────────────────────────────────

    CAPTCHA_SELECTORS = [
        (".yidun_slider", 0.9, "yidun-slider"),
        (".yidun_modal", 0.9, "yidun-modal"),
        (".nc_wrapper", 0.8, "netease-wrapper"),
        ("#captcha", 0.7, "captcha-id"),
        ('[src*="checkcode"]', 0.7, "checkcode-img"),
        ('[src*="captcha"]', 0.6, "captcha-img"),
        (".verify-captcha", 0.6, "verify-captcha"),
    ]

    # ── Detection Methods ─────────────────────────────────

    @staticmethod
    async def detect_active(
        page: "Page",
        selector_list: list[tuple[str, float, str]],
        min_count: int = 1,
    ) -> Optional[str]:
        """Test each selector and return the first one that matches.

        Args:
            page: Playwright page
            selector_list: List of (selector, confidence, name) tuples
            min_count: Minimum number of matching elements required

        Returns:
            First matching selector string, or None if none match
        """
        for selector, confidence, name in selector_list:
            try:
                count = await page.evaluate(
                    f"document.querySelectorAll('{selector}').length"
                )
                if count >= min_count:
                    logger.debug(
                        "selector_detected",
                        name=name,
                        selector=selector[:60],
                        confidence=confidence,
                        count=count,
                    )
                    return selector
            except Exception:
                continue

        logger.warning(
            "no_valid_selector_found",
            tried=[name for _, _, name in selector_list],
        )
        return None

    @staticmethod
    async def detect_best_result_selector(page: "Page") -> Optional[str]:
        """Find the best selector for search result rows."""
        return await SelectorRegistry.detect_active(page, SelectorRegistry.SEARCH_RESULT_ROWS)

    @staticmethod
    async def detect_best_download_selector(page: "Page") -> Optional[str]:
        """Find the best selector for PDF download links."""
        return await SelectorRegistry.detect_active(page, SelectorRegistry.DOWNLOAD_SELECTORS)

    @staticmethod
    async def detect_captcha_selectors(page: "Page") -> list[str]:
        """Return all currently active CAPTCHA selectors on the page."""
        active = []
        for selector, confidence, name in SelectorRegistry.CAPTCHA_SELECTORS:
            try:
                count = await page.evaluate(
                    f"document.querySelectorAll('{selector}').length"
                )
                if count > 0:
                    active.append(selector)
            except Exception:
                continue
        return active

    @staticmethod
    async def page_has_any(page: "Page", selector_list: list[str]) -> bool:
        """Quick check: does the page match any of the given selectors?"""
        for selector in selector_list:
            try:
                count = await page.evaluate(
                    f"document.querySelectorAll('{selector}').length"
                )
                if count > 0:
                    return True
            except Exception:
                continue
        return False


# Global singleton
selector_registry = SelectorRegistry()
