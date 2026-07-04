"""NetEase YiDun (网易易盾) specific CAPTCHA handling for CNKI.

CNKI redirects to YiDun's verification page at /verify/home when it detects
suspicious activity. YiDun uses a multi-layered verification system:

1. blockPuzzle (slider) — the most common type on CNKI
2. clickCaptcha — click characters in specified order
3. intelligentVerification — risk-based, may pass silently or trigger puzzles

YiDun collects extensive behavioral telemetry (mouse trajectory, timing,
keyboard events) during the CAPTCHA interaction and sends it to their
server for risk assessment. Even a correctly solved puzzle can be rejected
if the behavioral data looks bot-like.

This module handles YiDun-specific:
- Parameter extraction (captchaId, challenge, fp from page JS state)
- Verification token injection after external solve
- Behavioral telemetry smoothing for better pass rates
"""

from __future__ import annotations

import asyncio
import random
import structlog
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = structlog.get_logger()


class YiDunHandler:
    """Handles NetEase YiDun CAPTCHA flow on CNKI."""

    VERIFY_PAGE_INDICATORS = [
        "/verify/home",
        "verify.cnki.net",
        "yidun",
    ]

    @staticmethod
    def is_yidun_page(url: str) -> bool:
        """Check if current page is a YiDun verification page."""
        return any(indicator in url.lower() for indicator in YiDunHandler.VERIFY_PAGE_INDICATORS)

    @staticmethod
    async def extract_params(page: "Page") -> dict:
        """Extract YiDun captchaId, challenge, and fingerprint from page JS state.

        These are needed by external CAPTCHA solving services to create the
        correct task type for CNKI's YiDun instance.
        """
        return await page.evaluate("""() => {
            const params = {
                captchaId: '',
                challenge: '',
                fp: '',
                neOptions: null,
            };

            // Try multiple sources for YiDun params
            if (window._yidun_captchaId) params.captchaId = window._yidun_captchaId;
            if (window._yidun_challenge) params.challenge = window._yidun_challenge;
            if (window._yidun_fp) params.fp = window._yidun_fp;

            // Alternative: extract from initNECaptcha call or data attributes
            const containers = document.querySelectorAll('[id*="captcha"], [class*="yidun"]');
            for (const el of containers) {
                if (el.dataset.captchaId && !params.captchaId) params.captchaId = el.dataset.captchaId;
                if (el.getAttribute('data-challenge') && !params.challenge) params.challenge = el.getAttribute('data-challenge');
            }

            // Try window.NECaptchaValidate
            if (window._ne_options) {
                try {
                    params.neOptions = JSON.parse(JSON.stringify(window._ne_options));
                } catch(e) {}
            }

            return params;
        }""")

    @staticmethod
    async def inject_solution(page: "Page", solution: dict) -> bool:
        """Inject the verification token after external CAPTCHA solve.

        YiDun expects the verification result to be passed to a callback
        function or to trigger NECaptchaValidate.
        """
        validate = solution.get("validate", "")
        token = solution.get("token", "") or solution.get("challenge", "")

        if not validate:
            logger.warning("yidun_inject_missing_validate")
            return False

        return await page.evaluate("""([validate, token]) => {
            // Method 1: Call NECaptchaValidate if available
            if (typeof window.NECaptchaValidate === 'function') {
                try {
                    window.NECaptchaValidate(validate, token);
                    return true;
                } catch(e) {}
            }

            // Method 2: Populate hidden form fields
            const validateInput = document.querySelector(
                'input[name="NECaptchaValidate"], input[name="validate"]'
            );
            if (validateInput) {
                validateInput.value = validate;
                const form = validateInput.closest('form');
                if (form) {
                    form.submit();
                    return true;
                }
            }

            // Method 3: Dispatch custom event that YiDun listens for
            window.dispatchEvent(new CustomEvent('necValidate', {
                detail: { validate: validate, token: token }
            }));

            return false;
        }""", [validate, token])

    @staticmethod
    async def smooth_behavior_telemetry(page: "Page") -> None:
        """Generate human-like behavioral telemetry before interacting with YiDun.

        YiDun collects mousemove, scroll, and timing events from the page.
        Pre-generating natural-looking events improves the risk score and
        increases the chance of passing even with a correct solution.
        """
        try:
            viewport = page.viewport_size
            if viewport is None:
                return

            w, h = viewport["width"], viewport["height"]

            # Simulate natural mouse movement across the page
            points = [
                (random.randint(100, 300), random.randint(100, 300)),
                (random.randint(400, 700), random.randint(200, 400)),
                (random.randint(600, w - 100), random.randint(300, 500)),
                (random.randint(200, w - 200), random.randint(100, h - 100)),
            ]
            for tx, ty in points:
                await page.mouse.move(tx, ty)
                await asyncio.sleep(random.uniform(0.15, 0.6))

            # Micro-scroll
            await page.mouse.wheel(0, random.randint(30, 80))
            await asyncio.sleep(random.uniform(0.3, 0.8))
            await page.mouse.wheel(0, -random.randint(10, 30))

            logger.debug("yidun_telemetry_smoothed")
        except Exception as e:
            logger.debug("yidun_telemetry_failed: %s", e)

    @staticmethod
    async def wait_and_retry_after_block(page: "Page", base_delay: int = 60) -> bool:
        """After being blocked by YiDun, wait and refresh.

        YiDun blocks typically last a few minutes. Returns True if the page
        is no longer on the verification page after the wait.
        """
        jitter = random.uniform(0.7, 1.3)
        delay = base_delay * jitter
        logger.info("yidun_block_cooldown", delay_seconds=int(delay))
        await asyncio.sleep(delay)

        try:
            await page.reload()
            await asyncio.sleep(2)
            url = page.url
            return not YiDunHandler.is_yidun_page(url)
        except Exception:
            return False


# Global singleton
yidun_handler = YiDunHandler()
