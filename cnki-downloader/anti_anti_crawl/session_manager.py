"""Cookie/session persistence, warmup, and rotation.

Maintains session state across browser restarts so sessions appear
"seasoned" and less likely to trigger CAPTCHA challenges.
"""

from __future__ import annotations

import asyncio
import json
import structlog
import random
import time
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from config.settings import settings

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page

logger = structlog.get_logger()


class SessionManager:
    """Manages browser session persistence for anti-detection."""

    def __init__(self, session_dir: str = "./sessions"):
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._session_pool: dict[str, list[dict]] = {}
        self._session_last_used: dict[str, float] = {}
        self._max_sessions_per_discipline = 2

    async def save_session(self, context: "BrowserContext", name: str) -> None:
        """Export cookies and localStorage from a browser context."""
        try:
            cookies = await context.cookies()
            session_data = {
                "name": name,
                "cookies": cookies,
                "saved_at": time.time(),
                "cookie_count": len(cookies),
            }

            # Save to disk
            filepath = self.session_dir / f"{name}.json"
            filepath.write_text(json.dumps(session_data, ensure_ascii=False, indent=2))

            # Update pool
            self._session_pool[name] = cookies
            self._session_last_used[name] = time.time()

            logger.debug("session_saved", name=name, cookie_count=len(cookies))
        except Exception as e:
            logger.warning("session_save_failed", name=name, error=str(e))

    async def load_session(self, name: str) -> Optional[list[dict]]:
        """Load cookies from disk, validate expiry, return None if all expired."""
        # Check memory first
        if name in self._session_pool:
            cookies = self._session_pool[name]
            if self._cookies_valid(cookies):
                self._session_last_used[name] = time.time()
                return cookies

        # Load from disk
        filepath = self.session_dir / f"{name}.json"
        if not filepath.exists():
            return None

        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            cookies = data.get("cookies", [])
            if self._cookies_valid(cookies):
                self._session_pool[name] = cookies
                self._session_last_used[name] = time.time()
                return cookies
            else:
                filepath.unlink(missing_ok=True)
                return None
        except Exception as e:
            logger.warning("session_load_failed", name=name, error=str(e))
            return None

    @staticmethod
    def _cookies_valid(cookies: list[dict]) -> bool:
        """Check if at least some cookies haven't expired."""
        now = time.time()
        valid_count = 0
        for cookie in cookies:
            expires = cookie.get("expires", -1)
            if expires == -1:  # Session cookie
                valid_count += 1
            elif expires > now:
                valid_count += 1
        return valid_count > 2  # Need at least a few valid cookies

    async def warmup_session_via_tls(self, duration: int = 15) -> Optional[list[dict]]:
        """Acquire fresh CNKI cookies via TLS-impersonated HTTP, before Playwright.

        Uses curl_cffi's Chrome TLS fingerprint to visit CNKI pages.
        The resulting cookies were obtained with a real-browser JA3 hash,
        making the session appear "pre-seasoned" when later injected into Playwright.

        Returns list of cookie dicts suitable for context.add_cookies(), or None.
        """
        from anti_anti_crawl.tls_client import TLSClient

        tls = TLSClient(
            impersonate="chrome124",
            proxy_url=settings.PROXY_URL if settings.PROXY_ENABLED else None,
        )
        cookies: list[dict] = []

        try:
            logger.info("tls_session_warmup_started")

            warmup_urls = [
                "https://www.cnki.net/",
                "https://kns.cnki.net/kns8s/",
                "https://navi.cnki.net/knavi/",
            ]
            for url in warmup_urls:
                try:
                    resp = await tls.get(url)
                    if resp.status_code == 200:
                        # Extract cookies from curl_cffi response
                        for c in resp.cookies.jar:
                            cookies.append({
                                "name": c.name,
                                "value": c.value,
                                "domain": c.domain or ".cnki.net",
                                "path": c.path or "/",
                                "expires": c.expires.timestamp() if c.expires else -1,
                                "secure": c.secure or True,
                                "httpOnly": False,
                            })
                    await asyncio.sleep(random.uniform(1.5, 4.0))
                except Exception as e:
                    logger.debug("tls_warmup_url_failed", url=url[:60], error=str(e))

            if cookies:
                logger.info(
                    "tls_session_warmup_completed",
                    cookie_count=len(cookies),
                )
            else:
                logger.warning("tls_session_warmup_no_cookies")

            return cookies if cookies else None

        except Exception as e:
            logger.warning("tls_session_warmup_failed", error=str(e))
            return None
        finally:
            await tls.close()

    async def warmup_session(self, page: "Page", duration: int = 30) -> None:
        """Warm up a fresh browser session by casually browsing CNKI.

        Visits CNKI homepage, scrolls around, and waits to establish
        a more "seasoned" session profile that's less likely to trigger CAPTCHAs.
        """
        from anti_anti_crawl.behavior_simulator import behavior_simulator

        try:
            logger.info("session_warmup_started", duration=duration)

            # Visit CNKI homepage
            await page.goto("https://www.cnki.net/", wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(2, 5))

            # Scroll homepage
            await behavior_simulator.slow_scroll_through(page)

            # Visit a few more pages casually
            warmup_urls = [
                "https://kns.cnki.net/kns8s/",
                "https://navi.cnki.net/knavi/",
            ]
            start = asyncio.get_event_loop().time()
            for url in warmup_urls:
                if asyncio.get_event_loop().time() - start > duration:
                    break
                await page.goto(url, wait_until="domcontentloaded")
                await asyncio.sleep(random.uniform(3, 8))
                await behavior_simulator.human_scroll(page, random.randint(200, 500))

            # Random browsing to build trust
            await behavior_simulator.random_browsing(page, duration_seconds=min(duration, 20))

            logger.info("session_warmup_completed")
        except Exception as e:
            logger.warning("session_warmup_failed", error=str(e))

    async def rotate_session(
        self, discipline: str, context: "BrowserContext"
    ) -> str:
        """Get the least-recently-used session for a discipline, or create new."""
        discipline_sessions = [
            k for k in self._session_last_used
            if k.startswith(discipline)
        ]

        if discipline_sessions:
            # Find least-recently-used
            lru = min(discipline_sessions, key=lambda k: self._session_last_used.get(k, 0))
            cookies = await self.load_session(lru)
            if cookies:
                await context.add_cookies(cookies)
                logger.info("session_rotated", discipline=discipline, session=lru)
                return lru

        # Create new session
        new_name = f"{discipline}_{int(time.time())}_{random.randint(0, 9999)}"
        page = await context.new_page()
        try:
            await self.warmup_session(page)
            await self.save_session(context, new_name)
        finally:
            await page.close()

        # Evict oldest if pool full
        if len(discipline_sessions) >= self._max_sessions_per_discipline:
            oldest = max(discipline_sessions, key=lambda k: self._session_last_used.get(k, 0))
            self._session_pool.pop(oldest, None)
            self._session_last_used.pop(oldest, None)
            (self.session_dir / f"{oldest}.json").unlink(missing_ok=True)

        logger.info("session_created", discipline=discipline, name=new_name)
        return new_name

    def list_sessions(self) -> list[dict]:
        """List all available sessions with metadata."""
        result = []
        for filepath in self.session_dir.glob("*.json"):
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                result.append({
                    "name": data.get("name", filepath.stem),
                    "cookie_count": data.get("cookie_count", 0),
                    "saved_at": data.get("saved_at", 0),
                })
            except Exception:
                pass
        return sorted(result, key=lambda x: x.get("saved_at", 0), reverse=True)


# Global singleton
session_manager = SessionManager()
