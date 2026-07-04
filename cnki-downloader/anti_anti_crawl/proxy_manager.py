"""Clash for Windows proxy verification and rotation.

Clash provides a local proxy pool at http://127.0.0.1:7890.
This module verifies proxy health, rotates on block detection,
and tracks proxy performance statistics.

Reuses proxy configuration pattern from bilibili-spider skill.
"""

from __future__ import annotations

import asyncio
import structlog
import random
import time
from typing import Optional

import aiohttp

from config.settings import settings
from crawler.block_tracker import CNKIBlockTracker

logger = structlog.get_logger()


class ProxyManager:
    """Manages Clash proxy pool with health checking and auto-rotation.

    Task 4.2: 集成 CNKIBlockTracker 共享封锁状态。
    当 CNKI 418 拦截发生时，auto_rotate_on_block() 会将当前代理标记到
    CNKIBlockTracker（持久化到 cnki_block_status.json），使其他组件
    （如 hybrid_scraper 使用的 ProxyPool）能感知到该代理被封锁。
    """

    def __init__(self):
        self.proxy_url = settings.PROXY_URL
        self.enabled = settings.PROXY_ENABLED
        self._verify_interval = 300  # 5 minutes
        self._last_verify = 0.0
        self._last_ip = ""
        self._rotation_count = 0
        self._block_count = 0
        self._session: Optional[aiohttp.ClientSession] = None
        # Task 4.2: 共享 CNKI 封锁状态（与 ProxyPool/CNKIBlockTracker 统一）
        self._block_tracker = CNKIBlockTracker()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
            )
        return self._session

    async def verify(self) -> bool:
        """Verify proxy is working by checking external IP via proxy."""
        if not self.enabled:
            return True

        try:
            session = await self._get_session()
            async with session.get(
                "https://httpbin.org/ip",
                proxy=self.proxy_url,
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    ip = data.get("origin", "")
                    self._last_ip = str(ip)
                    self._last_verify = time.time()
                    logger.debug("proxy_verified", ip=ip)
                    return True
        except Exception as e:
            logger.warning("proxy_verify_failed", error=str(e))
        return False

    async def get_current_ip(self) -> str:
        """Get the current public IP through the proxy."""
        if not self.enabled:
            return "direct"

        await self.verify()
        return self._last_ip

    async def rotate(self) -> bool:
        """Rotate to the next proxy in Clash group.

        For Clash, you can switch proxy nodes by calling Clash's
        REST API or by using different proxy groups configured in Clash.
        """
        if not self.enabled:
            return True

        self._rotation_count += 1

        # Attempt to rotate via Clash API (if available)
        # Clash API typically runs on http://127.0.0.1:9090
        clash_api = "http://127.0.0.1:9090"
        try:
            session = await self._get_session()

            # Get current proxy groups
            async with session.get(
                f"{clash_api}/proxies",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Find a proxy group to rotate
                    proxy_groups = {
                        k: v for k, v in data.get("proxies", {}).items()
                        if v.get("type") == "Selector" and "now" in v
                    }

                    if proxy_groups:
                        group_name = random.choice(list(proxy_groups.keys()))
                        group = proxy_groups[group_name]
                        available = group.get("all", [])
                        current = group.get("now", "")

                        # Pick a different node
                        others = [n for n in available if n != current]
                        if others:
                            new_node = random.choice(others)
                            async with session.put(
                                f"{clash_api}/proxies/{group_name}",
                                json={"name": new_node},
                            ) as put_resp:
                                if put_resp.status == 204:
                                    logger.info(
                                        "proxy_rotated",
                                        group=group_name,
                                        from_node=current,
                                        to_node=new_node,
                                    )
                                    await asyncio.sleep(2)
                                    return await self.verify()
        except Exception as e:
            logger.debug("clash_api_rotate_failed", error=str(e))

        # If Clash API is unavailable, proxy rotation depends on Clash's
        # built-in load balancing or round-robin configuration
        logger.info("proxy_rotation_fallback", count=self._rotation_count)
        return await self.verify()

    async def auto_rotate_on_block(self) -> None:
        """Called when CNKI blocks the current IP. Rotate proxy.

        Task 4.2: 标记当前代理为 CNKI 封锁（写入 CNKIBlockTracker 持久化状态），
        使 ProxyPool 等其他组件能感知并跳过该代理。
        """
        self._block_count += 1
        # Task 4.2: 共享封锁状态到 CNKIBlockTracker
        if self.proxy_url:
            self._block_tracker.mark_blocked(self.proxy_url)
            logger.warning(
                "proxy_marked_blocked",
                proxy_url=self.proxy_url,
                block_count=self._block_count,
            )
        success = await self.rotate()
        if not success:
            logger.error("proxy_rotation_all_failed")

    def is_blocked(self) -> bool:
        """Task 4.2: 检查当前代理是否被 CNKI 封锁。

        Returns:
            True 表示当前代理处于 CNKI 封锁冷却期
        """
        if not self.enabled or not self.proxy_url:
            return False
        return self._block_tracker.is_blocked(self.proxy_url)

    async def get_proxy_config(self) -> Optional[dict]:
        """Return proxy configuration for Playwright."""
        if not self.enabled:
            return None

        return {"server": self.proxy_url}

    async def health_loop(self) -> None:
        """Background task: periodically verify proxy health."""
        while True:
            await asyncio.sleep(self._verify_interval)
            healthy = await self.verify()
            if not healthy:
                logger.warning("proxy_unhealthy")
                await self.rotate()

    async def get_stats(self) -> dict:
        """Return proxy statistics."""
        return {
            "enabled": self.enabled,
            "proxy_url": self.proxy_url,
            "current_ip": self._last_ip,
            "rotation_count": self._rotation_count,
            "block_count": self._block_count,
            "last_verify": self._last_verify,
            "healthy": await self.verify() if self.enabled else True,
            # Task 4.2: 暴露 CNKI 封锁状态供监控
            "cnki_blocked": self.is_blocked(),
            "cnki_blocked_proxies": self._block_tracker.blocked_proxies(),
        }

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None


# Global singleton
proxy_manager = ProxyManager()
