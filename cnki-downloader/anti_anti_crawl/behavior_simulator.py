"""Human-like browser behavior simulation.

Simulates realistic mouse movements, scrolling, typing, and browsing patterns
to evade CNKI's behavioral analysis detection.
"""

from __future__ import annotations

import asyncio
import structlog
import math
import random
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = structlog.get_logger()


class BehaviorSimulator:
    """Generates human-like interaction patterns on web pages."""

    def __init__(self):
        self._last_mouse_position: tuple[float, float] = (random.randint(200, 600), random.randint(200, 400))

    # ── Delays ──────────────────────────────────────────────

    @staticmethod
    def human_delay(
        min_ms: float = 500,
        max_ms: float = 3000,
        distribution: str = "poisson",
    ) -> float:
        """Generate human-like delay with Poisson distribution."""
        if distribution == "poisson":
            lam = (max_ms - min_ms) / 3 + min_ms
            delay = random.expovariate(1.0 / (lam - min_ms + 0.001)) + min_ms
            return min(delay, max_ms)

        if distribution == "reading":
            return random.uniform(2000, 8000)

        if distribution == "click":
            return random.uniform(300, 1500)

        if distribution == "typing":
            return random.uniform(50, 250)

        return random.uniform(min_ms, max_ms)

    async def random_delay(self, min_ms: float = 500, max_ms: float = 3000) -> None:
        """Sleep for a random human-like duration."""
        delay = self.human_delay(min_ms, max_ms) / 1000.0
        await asyncio.sleep(delay)

    # ── Mouse Movement ──────────────────────────────────────

    @staticmethod
    def _bezier_curve(
        p0: tuple[float, float],
        p1: tuple[float, float],
        p2: tuple[float, float],
        p3: tuple[float, float],
        t: float,
    ) -> tuple[float, float]:
        """Cubic bezier curve point at time t."""
        x = ((1 - t) ** 3) * p0[0] + 3 * ((1 - t) ** 2) * t * p1[0] + 3 * (1 - t) * (t ** 2) * p2[0] + (t ** 3) * p3[0]
        y = ((1 - t) ** 3) * p0[1] + 3 * ((1 - t) ** 2) * t * p1[1] + 3 * (1 - t) * (t ** 2) * p2[1] + (t ** 3) * p3[1]
        return (x, y)

    async def mouse_move(self, page: "Page", target_x: float, target_y: float, steps: int = 30) -> None:
        """Move mouse to target with bezier curve path."""
        start_x, start_y = self._last_mouse_position

        # Generate control points with some randomness
        cp1_x = start_x + (target_x - start_x) * random.uniform(0.2, 0.4)
        cp1_y = start_y + random.uniform(-50, 50)
        cp2_x = start_x + (target_x - start_x) * random.uniform(0.6, 0.8)
        cp2_y = target_y + random.uniform(-50, 50)

        for i in range(steps + 1):
            t = i / steps
            # Variable speed: accelerate then decelerate
            t_eased = t  # Could use easing function here
            x, y = self._bezier_curve(
                (start_x, start_y), (cp1_x, cp1_y), (cp2_x, cp2_y), (target_x, target_y), t_eased
            )
            await page.mouse.move(x, y)
            # Variable delay between steps
            await asyncio.sleep(random.uniform(0.002, 0.015))

        # 10% chance of overshoot and correct
        if random.random() < 0.1:
            overshoot_x = target_x + random.uniform(-20, 20)
            overshoot_y = target_y + random.uniform(-20, 20)
            await page.mouse.move(overshoot_x, overshoot_y)
            await asyncio.sleep(random.uniform(0.05, 0.15))
            await page.mouse.move(target_x, target_y)

        self._last_mouse_position = (target_x, target_y)

    async def human_click(self, page: "Page", selector: str) -> None:
        """Click an element with human-like behavior."""
        try:
            element = await page.query_selector(selector)
            if element is None:
                raise ValueError(f"Element not found: {selector}")

            box = await element.bounding_box()
            if box is None:
                raise ValueError(f"Element has no bounding box: {selector}")

            # Click slightly off-center
            target_x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
            target_y = box["y"] + box["height"] * random.uniform(0.3, 0.7)

            await self.mouse_move(page, target_x, target_y)
            await asyncio.sleep(random.uniform(0.05, 0.2))
            await page.mouse.click(target_x, target_y)
            logger.debug("human_click", selector=selector[:50])
        except Exception as e:
            logger.warning("human_click_failed", selector=selector[:50], error=str(e))
            # Fallback: direct click
            await page.click(selector)

    # ── Scrolling ───────────────────────────────────────────

    async def human_scroll(self, page: "Page", distance: Optional[int] = None, direction: str = "down") -> None:
        """Scroll page with variable speed and micro-pauses."""
        if distance is None:
            distance = random.randint(200, 600)

        if direction == "up":
            distance = -distance

        # Break scroll into 5-15 small steps
        steps = random.randint(5, 15)
        step_size = distance / steps

        for i in range(steps):
            actual_step = step_size * random.uniform(0.5, 1.5)
            await page.mouse.wheel(0, actual_step)
            # Variable delay between scroll steps
            if random.random() < 0.2:
                # Occasional micro-pause (simulate reading/scanning)
                await asyncio.sleep(random.uniform(0.1, 0.5))
            else:
                await asyncio.sleep(random.uniform(0.02, 0.08))

        logger.debug("human_scroll", distance=distance, steps=steps)

    async def slow_scroll_through(self, page: "Page") -> None:
        """Slowly scroll through page content simulating reading behavior."""
        viewport = page.viewport_size
        if viewport is None:
            return

        page_height = await page.evaluate("document.body.scrollHeight")
        current = 0

        while current < page_height:
            scroll_amount = random.randint(
                int(viewport["height"] * 0.5),
                int(viewport["height"] * 0.9),
            )
            await self.human_scroll(page, scroll_amount, "down")
            current += scroll_amount

            # Sometimes scroll back up a bit (re-reading)
            if random.random() < 0.15:
                back_amount = random.randint(50, 200)
                await self.human_scroll(page, back_amount, "up")
                current -= back_amount

            # Reading pause
            await asyncio.sleep(random.uniform(1.0, 4.0))

    # ── Typing ──────────────────────────────────────────────

    async def human_type(self, page: "Page", selector: str, text: str) -> None:
        """Type text with variable inter-key delays and occasional typos."""
        await page.click(selector)
        await asyncio.sleep(random.uniform(0.1, 0.3))

        for i, char in enumerate(text):
            # Variable typing speed
            if char in "，。！？；：""''（）【】":
                await asyncio.sleep(random.uniform(0.1, 0.3))  # Slower on punctuation
            else:
                await asyncio.sleep(random.uniform(0.03, 0.15))

            # 5% chance of typo + backspace
            if random.random() < 0.05:
                typo_char = random.choice("abcdefghijklmnopqrstuvwxyz")
                await page.keyboard.type(typo_char)
                await asyncio.sleep(random.uniform(0.1, 0.2))
                await page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.05, 0.1))

            await page.keyboard.type(char)

        logger.debug("human_type", text_length=len(text))

    # ── Random Browsing ─────────────────────────────────────

    async def random_browsing(self, page: "Page", duration_seconds: float = 30.0) -> None:
        """Simulate random browsing behavior to build session trust."""
        start_time = asyncio.get_event_loop().time()

        actions = 0
        while asyncio.get_event_loop().time() - start_time < duration_seconds:
            action = random.choice(["scroll", "hover", "pause", "navigate"])

            if action == "scroll":
                await self.human_scroll(page, random.randint(-300, 600))
                actions += 1
            elif action == "hover":
                try:
                    elements = await page.query_selector_all("a, button, span, div")
                    if elements:
                        el = random.choice(elements[:20])
                        box = await el.bounding_box()
                        if box:
                            await self.mouse_move(
                                page,
                                box["x"] + box["width"] / 2,
                                box["y"] + box["height"] / 2,
                            )
                            await asyncio.sleep(random.uniform(0.5, 2.0))
                            actions += 1
                except Exception:
                    pass
            elif action == "pause":
                await asyncio.sleep(random.uniform(1.0, 4.0))
            elif action == "navigate":
                # Simulate quick visit to a benign Chinese website
                # (just hover/scroll, don't actually navigate away)
                await self.human_scroll(page, random.randint(100, 400))

        logger.debug("random_browsing_completed", duration=duration_seconds, actions=actions)

    # ── Element Detection ───────────────────────────────────

    async def wait_for_human(self, page: "Page", selector: str, timeout: int = 15000) -> bool:
        """Wait for element with natural delay after appearance."""
        try:
            await page.wait_for_selector(selector, timeout=timeout)
            await asyncio.sleep(random.uniform(0.3, 1.0))
            return True
        except Exception:
            return False


# Global singleton
behavior_simulator = BehaviorSimulator()
