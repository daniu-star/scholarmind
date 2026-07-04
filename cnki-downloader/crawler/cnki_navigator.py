"""Low-level CNKI page navigation primitives.

Handles React rendering waits, overlay/popup dismissal,
CAPTCHA detection, and structured data extraction from CNKI pages.
"""

from __future__ import annotations

import asyncio
import structlog
import random
from typing import Optional, Any, TYPE_CHECKING

from models.enums import CAPTCHAType

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = structlog.get_logger()


class CNKINavigator:
    """Low-level page interaction primitives for CNKI's React-based UI."""

    # Known CNKI overlay/popup selectors
    OVERLAY_SELECTORS = [
        ".layui-layer-close", ".close-btn", ".popup-close",
        "a:has-text('跳过')", "a:has-text('关闭')", "button:has-text('跳过')",
        "span:has-text('×')", "[class*='close']", ".dialog-close",
        ".modal-close", ".el-message-box__close", ".el-dialog__close",
    ]

    AD_SELECTORS = [
        ".advertisement", ".ad-banner", ".popup-ad",
        "[class*='ad-']", "[class*='popup']", ".float-ad",
        "iframe[src*='ad']", "[id*='ad']",
    ]

    @staticmethod
    async def wait_for_cnki_render(
        page: "Page",
        primary_selector: str = "",
        timeout: int = 15000,
    ) -> bool:
        """Wait for CNKI's React page to fully render.

        Strategy:
        1. Wait for primary content selector
        2. Fallback: wait for network idle
        3. Additional buffer for lazy-loaded content
        """
        try:
            if primary_selector:
                await page.wait_for_selector(primary_selector, timeout=timeout)
            else:
                await page.wait_for_load_state("networkidle", timeout=timeout)

            # Extra wait for React hydration + lazy loading
            await asyncio.sleep(random.uniform(1.0, 3.0))

            # Verify page is not a CAPTCHA/block page
            title = await page.title()
            if any(kw in title for kw in ["验证", "禁止访问", "系统繁忙", "403"]):
                logger.warning("cnki_render_blocked", title=title)
                return False

            return True
        except Exception as e:
            logger.warning("cnki_render_timeout", selector=primary_selector[:50], error=str(e))
            return False

    @staticmethod
    async def dismiss_overlays(page: "Page") -> int:
        """Dismiss all popups, ads, and overlays on the page."""
        from anti_anti_crawl.behavior_simulator import behavior_simulator

        dismissed = 0

        # Dismiss known overlay close buttons
        for selector in CNKINavigator.OVERLAY_SELECTORS:
            try:
                el = await page.query_selector(selector)
                if el and await el.is_visible():
                    await behavior_simulator.human_click(page, selector)
                    dismissed += 1
                    await asyncio.sleep(random.uniform(0.5, 1.0))
            except Exception:
                continue

        # Try pressing Escape to dismiss modals
        if dismissed > 0:
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.5)
            except Exception:
                pass

        if dismissed:
            logger.debug("overlays_dismissed", count=dismissed)

        return dismissed

    @staticmethod
    async def check_for_captcha(page: "Page") -> bool:
        """Quick check if a CAPTCHA element is visible."""
        captcha_indicators = [
            ".yidun_slider", ".nc_wrapper", ".captcha-form",
            "#captcha", '[src*="checkcode"]', '[src*="captcha"]',
            ".verify-captcha", ".yidun_modal",
        ]
        for sel in captcha_indicators:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    async def extract_texts(
        page: "Page", selector: str, attribute: str = "textContent"
    ) -> list[str]:
        """Extract text content from multiple matching elements."""
        try:
            return await page.evaluate(f"""
                () => {{
                    const els = document.querySelectorAll('{selector}');
                    return Array.from(els).map(el => (el.{attribute} || '').trim());
                }}
            """)
        except Exception:
            return []

    @staticmethod
    async def extract_links(
        page: "Page", parent_selector: str, link_selector: str = "a"
    ) -> list[dict[str, str]]:
        """Extract links (text + href) from a section of the page."""
        try:
            return await page.evaluate(f"""
                () => {{
                    const parent = document.querySelector('{parent_selector}');
                    if (!parent) return [];
                    const links = parent.querySelectorAll('{link_selector}');
                    return Array.from(links).map(a => ({{
                        text: (a.textContent || '').trim(),
                        href: a.href || '',
                        title: a.title || ''
                    }}));
                }}
            """)
        except Exception:
            return []

    @staticmethod
    async def safe_navigate(
        page: "Page",
        url: str,
        wait_selector: str = "",
        timeout: int = 15000,
        max_retries: int = 2,
    ) -> bool:
        """Navigate to URL with retry and CAPTCHA handling.

        CNKI redirects to a blockPuzzle CAPTCHA at /verify/home when it detects
        automated access. We detect this, solve the CAPTCHA, then retry.
        """
        from anti_anti_crawl.behavior_simulator import behavior_simulator
        from anti_anti_crawl.captcha_bypass import captcha_bypass

        for attempt in range(max_retries + 1):
            try:
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout,
                )

                if response and response.status in (403, 429):
                    logger.warning("cnki_blocked_response", status=response.status, url=url[:60])
                    # Rotate proxy on block
                    from anti_anti_crawl.proxy_manager import proxy_manager
                    await proxy_manager.auto_rotate_on_block()
                    if attempt < max_retries:
                        await asyncio.sleep(random.uniform(5, 15))
                        continue
                    return False

                # Check if redirected to CAPTCHA page
                current_url = page.url
                if "verify" in current_url and "captcha" in current_url.lower():
                    logger.info("captcha_redirect_detected", url=current_url[:80])
                    solved = await captcha_bypass.handle_persistent_captcha(page, max_attempts=2)
                    if solved:
                        # Retry navigation after CAPTCHA solve
                        await asyncio.sleep(random.uniform(1, 3))
                        continue
                    else:
                        logger.error("captcha_unsolvable", url=url[:60])
                        return False

                # Wait for render
                rendered = await CNKINavigator.wait_for_cnki_render(page, wait_selector, timeout)
                if not rendered:
                    if attempt < max_retries:
                        await asyncio.sleep(random.uniform(5, 15))
                        continue
                    return False

                # Dismiss any overlays
                await CNKINavigator.dismiss_overlays(page)

                return True

            except Exception as e:
                logger.warning(
                    "navigate_attempt_failed",
                    url=url[:60],
                    attempt=attempt + 1,
                    error=str(e),
                )
                if attempt < max_retries:
                    await asyncio.sleep(random.uniform(3, 10))

        return False

    @staticmethod
    async def scroll_to_bottom(page: "Page") -> None:
        """Scroll to bottom of page to trigger lazy loading."""
        from anti_anti_crawl.behavior_simulator import behavior_simulator
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(random.uniform(1, 3))

    @staticmethod
    async def handle_pagination(page: "Page") -> Optional[str]:
        """Check for and handle pagination on search/issue pages.

        Returns the "next page" URL if available, None otherwise.
        """
        next_selectors = [
            "a:has-text('下一页')", "a:has-text('>')",
            ".next a", ".pagination .next",
            "[class*='next']:not([class*='disabled'])",
        ]
        for sel in next_selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    href = await el.get_attribute("href")
                    if href and href != "#":
                        return href
            except Exception:
                continue
        return None
