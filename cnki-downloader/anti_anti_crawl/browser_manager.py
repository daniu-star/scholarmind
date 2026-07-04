"""Playwright browser lifecycle management with stealth mode.

Each worker thread gets its own BrowserContext from this manager's pool.
"""

from __future__ import annotations

import asyncio
import structlog
import random
from typing import Optional
from contextlib import asynccontextmanager

try:
    from playwright.async_api import (
        async_playwright,
        Playwright,
        Browser,
        BrowserContext,
        Page,
    )
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

from config.settings import settings

logger = structlog.get_logger()

# ═══════════════════════════════════════════════════════════════
# Stealth JS Injection Scripts
# ═══════════════════════════════════════════════════════════════

STEALTH_SCRIPTS = [
    # Hide webdriver property
    """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    """,
    # Fake plugins
    """
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const plugins = [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', length: 1 },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', length: 1 },
                { name: 'Native Client', filename: 'internal-nacl-plugin', length: 2 },
            ];
            plugins.item = (i) => plugins[i] || null;
            plugins.namedItem = (n) => plugins.find(p => p.name === n) || null;
            plugins.refresh = () => {};
            return plugins;
        }
    });
    Object.defineProperty(navigator, 'plugins', { configurable: false });
    """,
    # Fake languages
    """
    Object.defineProperty(navigator, 'languages', {
        get: () => ['zh-CN', 'zh', 'en-US', 'en']
    });
    """,
    # Fake chrome object
    """
    window.chrome = {
        runtime: {},
        loadTimes: function() {},
        csi: function() {},
        app: {}
    };
    """,
    # Override permissions to hide automation
    """
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
    );
    """,
    # Hide headless mode
    """
    Object.defineProperty(navigator, 'headless', { get: () => false });
    """,
]


def _stealth_hardware_script() -> str:
    """动态生成硬件指纹脚本，每次调用产生不同的随机值。

    避免 f-string 在模块导入时固化，确保每个浏览器上下文获得
    不同的 hardwareConcurrency 和 deviceMemory 值。
    """
    hc = random.randint(4, 16)
    dm = random.randint(4, 16)
    return f"""
    Object.defineProperty(navigator, 'hardwareConcurrency', {{
        get: () => {hc}
    }});
    Object.defineProperty(navigator, 'deviceMemory', {{
        get: () => {dm}
    }});
    """


# ═══════════════════════════════════════════════════════════════
# Browser Manager
# ═══════════════════════════════════════════════════════════════

class BrowserManager:
    """Manages Playwright browser lifecycle with stealth and context pooling."""

    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context_pool: list[BrowserContext] = []
        self._max_contexts = settings.BROWSER_CONTEXT_POOL_SIZE
        self._pages_per_context = settings.BROWSER_MAX_PAGES_PER_CONTEXT
        self._context_page_counts: dict[int, int] = {}
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized and self._browser is not None

    async def initialize(self) -> None:
        """Launch browser and create initial context pool."""
        if not HAS_PLAYWRIGHT:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            )

        self._playwright = await async_playwright().start()

        # Browser launch args for stealth
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-site-isolation-trials",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            f"--window-size={random.choice([1366, 1440, 1536, 1920])},{random.choice([768, 864, 900])}",
        ]

        proxy_config = None
        if settings.PROXY_ENABLED:
            proxy_config = {"server": settings.PROXY_URL}

        self._browser = await self._playwright.chromium.launch(
            headless=settings.BROWSER_HEADLESS,
            args=launch_args,
            proxy=proxy_config,
        )

        # Pre-warm context pool
        for _ in range(self._max_contexts):
            ctx = await self._create_context()
            self._context_pool.append(ctx)

        self._initialized = True
        logger.info(
            "browser_initialized",
            headless=settings.BROWSER_HEADLESS,
            proxy_enabled=settings.PROXY_ENABLED,
            context_pool_size=len(self._context_pool),
        )

    async def _create_context(self) -> BrowserContext:
        """Create a new browser context with stealth and random viewport."""
        viewport = {
            "width": random.choice([1366, 1440, 1536, 1920]),
            "height": random.choice([768, 864, 900]),
        }

        context = await self._browser.new_context(
            viewport=viewport,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            ignore_https_errors=True,
            user_agent=(
                f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                f"AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{random.choice([120, 121, 122, 123, 124])}.0.0.0 Safari/537.36"
            ),
            bypass_csp=True,
            extra_http_headers={
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )

        # Inject stealth scripts
        for script in STEALTH_SCRIPTS:
            await context.add_init_script(script)
        # 动态注入硬件指纹脚本（每次创建上下文时随机生成）
        await context.add_init_script(_stealth_hardware_script())

        # Enable download handling
        context.set_default_timeout(30000)

        logger.debug("browser_context_created", viewport=viewport)
        return context

    async def get_context(self) -> BrowserContext:
        """Get an available browser context (pop from pool or create new)."""
        if not self._initialized:
            await self.initialize()

        # Find a context with usage under the limit
        for ctx in self._context_pool:
            ctx_id = id(ctx)
            if self._context_page_counts.get(ctx_id, 0) < self._pages_per_context:
                return ctx

        # All exhausted — create new if pool not full
        if len(self._context_pool) < self._max_contexts * 2:
            ctx = await self._create_context()
            self._context_pool.append(ctx)
            return ctx

        # Pool full — rotate oldest
        await self.rotate_context()
        return self._context_pool[0]

    async def new_page(self) -> Page:
        """Get a context and create a fresh page."""
        context = await self.get_context()
        page = await context.new_page()
        ctx_id = id(context)
        self._context_page_counts[ctx_id] = self._context_page_counts.get(ctx_id, 0) + 1
        return page

    async def close_page(self, page: Page) -> None:
        """Close a page and decrement the context usage counter."""
        context = page.context
        ctx_id = id(context)
        self._context_page_counts[ctx_id] = max(0, self._context_page_counts.get(ctx_id, 1) - 1)
        await page.close()

    async def rotate_context(self) -> None:
        """Destroy the most-used context and create a fresh one."""
        if self._context_pool and len(self._context_pool) > 0:
            oldest = self._context_pool.pop(0)
            ctx_id = id(oldest)
            self._context_page_counts.pop(ctx_id, None)
            try:
                await oldest.close()
            except Exception:
                pass

        ctx = await self._create_context()
        self._context_pool.append(ctx)
        logger.info("browser_context_rotated", pool_size=len(self._context_pool))

    async def rotate_all_contexts(self) -> None:
        """Destroy all contexts and create fresh ones (used on proxy rotation)."""
        for ctx in self._context_pool:
            try:
                await ctx.close()
            except Exception:
                pass
        self._context_pool.clear()
        self._context_page_counts.clear()

        for _ in range(self._max_contexts):
            ctx = await self._create_context()
            self._context_pool.append(ctx)
        logger.info("all_contexts_rotated", pool_size=len(self._context_pool))

    async def shutdown(self) -> None:
        """Gracefully close browser and all contexts."""
        for ctx in self._context_pool:
            try:
                await ctx.close()
            except Exception:
                pass
        self._context_pool.clear()

        if self._browser:
            await self._browser.close()
            self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        self._initialized = False
        logger.info("browser_shutdown")


# ═══════════════════════════════════════════════════════════════
# Global Browser Manager Singleton
# ═══════════════════════════════════════════════════════════════

_browser_manager: Optional[BrowserManager] = None


def get_browser_manager() -> BrowserManager:
    """Get or create the global browser manager singleton."""
    global _browser_manager
    if _browser_manager is None:
        _browser_manager = BrowserManager()
    return _browser_manager


async def shutdown_browser_manager() -> None:
    global _browser_manager
    if _browser_manager:
        await _browser_manager.shutdown()
        _browser_manager = None
