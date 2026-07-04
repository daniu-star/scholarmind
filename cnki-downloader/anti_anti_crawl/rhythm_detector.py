"""CNKI response pattern detector and adaptive strategy adjuster.

Analyzes page load timing, CAPTCHA frequency, and HTTP responses
to detect when CNKI is getting suspicious and adapt behavior accordingly.

States: normal → suspicious → captcha → blocked
"""

from __future__ import annotations

import asyncio
import structlog
import time
from collections import deque
from typing import Optional, TYPE_CHECKING

from config.settings import settings

if TYPE_CHECKING:
    from playwright.async_api import Page, Response

logger = structlog.get_logger()


class RhythmState:
    NORMAL = "normal"
    SUSPICIOUS = "suspicious"
    CAPTCHA = "captcha"
    BLOCKED = "blocked"


class RhythmDetector:
    """Detects CNKI's anti-crawl response patterns and adapts strategy."""

    def __init__(self, window_size: int = 20):
        self._state = RhythmState.NORMAL
        self._response_times: deque[float] = deque(maxlen=window_size)
        self._block_count = 0
        self._captcha_count = 0
        self._consecutive_suspicious = 0
        self._last_state_change = time.time()
        self._page_load_threshold_normal = 5.0  # seconds
        self._page_load_threshold_suspicious = 10.0

    @property
    def current_state(self) -> str:
        return self._state

    @property
    def delay_multiplier(self) -> float:
        """Get the current delay multiplier based on state."""
        if self._state == RhythmState.NORMAL:
            return 1.0
        if self._state == RhythmState.SUSPICIOUS:
            return settings.SUSPICIOUS_DELAY_MULTIPLIER
        if self._state == RhythmState.CAPTCHA:
            return 3.0
        return 0.0  # BLOCKED — shouldn't be making requests

    def record_response(self, response_time: float, status_code: int = 200) -> None:
        """Record a page load or request response time."""
        self._response_times.append(response_time)

        # Detect rate limiting by response time
        if response_time > self._page_load_threshold_suspicious:
            self._consecutive_suspicious += 1
        else:
            self._consecutive_suspicious = max(0, self._consecutive_suspicious - 1)

    def record_block(self) -> None:
        """Record a block event (403, captcha page, etc.)."""
        self._block_count += 1
        self._update_state()

    def record_captcha(self) -> None:
        """Record a CAPTCHA encounter."""
        self._captcha_count += 1
        self._update_state()

    def record_success(self) -> None:
        """Record a successful page load — may help recover from suspicious state."""
        self._consecutive_suspicious = max(0, self._consecutive_suspicious - 2)

        # Auto-recover from suspicious to normal after sustained success
        if self._state == RhythmState.SUSPICIOUS and self._consecutive_suspicious <= 0:
            self._state = RhythmState.NORMAL
            self._last_state_change = time.time()
            logger.info("rhythm_recovered_to_normal")

    async def check(self, page: "Page") -> str:
        """Check current page for anti-crawl indicators. Returns state."""
        # Check for CAPTCHA elements
        captcha_selectors = [
            ".yidun_slider", ".yidun_modal", ".nc_wrapper",
            ".captcha-slider", "#captcha", '[class*="captcha"]',
            '[id*="captcha"]', '.verify-captcha', '.verify-form',
            'img[src*="checkcode"]', 'img[src*="captcha"]',
        ]
        for sel in captcha_selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    self.record_captcha()
                    return self._state
            except Exception:
                pass

        # Check title for block indicators
        try:
            title = await page.title()
            block_keywords = ["访问过于频繁", "系统繁忙", "验证", "安全验证", "403", "禁止访问"]
            for keyword in block_keywords:
                if keyword in title:
                    self.record_block()
                    self._state = RhythmState.BLOCKED
                    return self._state
        except Exception:
            pass

        # Check URL for redirect to verification
        try:
            url = page.url
            if any(kw in url for kw in ["verify", "captcha", "challenge", "blocked"]):
                self.record_block()
                return self._state
        except Exception:
            pass

        # Update based on cumulative behavior
        self._update_state()
        return self._state

    def _update_state(self) -> None:
        """Update state based on accumulated signals."""
        old_state = self._state

        # Determine new state
        if self._block_count >= 3:
            self._state = RhythmState.BLOCKED
        elif self._captcha_count >= 2 or self._consecutive_suspicious >= 5:
            self._state = RhythmState.CAPTCHA
        elif self._consecutive_suspicious >= 3:
            self._state = RhythmState.SUSPICIOUS

        if self._state != old_state:
            self._last_state_change = time.time()
            logger.warning(
                "rhythm_state_changed: %s -> %s (blocks=%d captchas=%d suspicious=%d)",
                old_state, self._state, self._block_count,
                self._captcha_count, self._consecutive_suspicious,
            )

    def get_delay_range(self) -> tuple[float, float]:
        """Get appropriate delay range for current state."""
        multiplier = self.delay_multiplier
        return (
            settings.DEFAULT_DELAY_MIN * multiplier,
            settings.DEFAULT_DELAY_MAX * multiplier,
        )

    async def adapt_delays(self) -> None:
        """Adapt system-wide delays based on current state."""
        if self._state == RhythmState.BLOCKED:
            cooldown = settings.BLOCKED_COOLDOWN_MINUTES * 60
            logger.warning("rhythm_blocked_cooldown", minutes=settings.BLOCKED_COOLDOWN_MINUTES)
            await asyncio.sleep(cooldown)
            self._state = RhythmState.CAPTCHA  # Step down from blocked
            self._block_count = 0

        min_d, max_d = self.get_delay_range()
        logger.debug(
            "rhythm_delays_adapted",
            state=self._state,
            delay_range=(round(min_d, 1), round(max_d, 1)),
        )

    def get_average_response_time(self) -> float:
        """Get average response time over the sliding window."""
        if not self._response_times:
            return 0.0
        return sum(self._response_times) / len(self._response_times)

    def get_stats(self) -> dict:
        """Get detector statistics."""
        return {
            "state": self._state,
            "avg_response_time": round(self.get_average_response_time(), 2),
            "block_count": self._block_count,
            "captcha_count": self._captcha_count,
            "consecutive_suspicious": self._consecutive_suspicious,
            "delay_multiplier": self.delay_multiplier,
            "window_size": len(self._response_times),
        }


# Global singleton
rhythm_detector = RhythmDetector()
