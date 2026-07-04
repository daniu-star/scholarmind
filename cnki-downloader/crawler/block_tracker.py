"""CNKI IP 封锁状态追踪器 — 记录被 CNKI 418 拦截的代理/IP。

CNKI 使用腾讯 EdgeOne CDN 进行 IP 级封锁（HTTP 418）。
本模块追踪哪些代理被 CNKI 封锁，记录封锁时间与冷却到期时间，
并提供查询接口供爬虫在选代理时跳过被封锁的节点。

特性：
  - is_blocked(proxy_url): 判断代理是否处于封锁状态
  - cooldown_remaining(proxy_url): 返回剩余冷却秒数
  - mark_blocked(proxy_url): 标记代理被 CNKI 封锁
  - 自动过期：封锁 24 小时后自动解除
  - 持久化：状态保存到 cnki_block_status.json
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional


class CNKIBlockTracker:
    """追踪被 CNKI 418 封锁的代理/IP。

    Args:
        state_path: 状态文件路径，默认 cnki_block_status.json
        block_duration: 封锁持续时间（秒），默认 86400（24 小时）
    """

    #: 默认封锁持续时间（24 小时）
    DEFAULT_BLOCK_DURATION: int = 86400

    def __init__(
        self,
        state_path: str | Path = "cnki_block_status.json",
        block_duration: int = DEFAULT_BLOCK_DURATION,
    ) -> None:
        self._state_path = Path(state_path)
        self._block_duration = int(block_duration)
        # 内部状态：{proxy_url: {"blocked_at": float, "expires_at": float}}
        self._blocks: dict[str, dict[str, float]] = {}
        self._load()

    # ── 持久化 ──────────────────────────────────────────────────

    def _load(self) -> None:
        """从 JSON 文件加载封锁状态。

        文件不存在或解析失败时使用空状态。
        加载时自动清理已过期的封锁记录。
        """
        if not self._state_path.exists():
            self._blocks = {}
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                self._blocks = {}
                return
            # 规范化加载的数据
            self._blocks = {}
            now = time.time()
            for proxy_url, info in data.items():
                if not isinstance(info, dict):
                    continue
                blocked_at = float(info.get("blocked_at", 0))
                expires_at = float(info.get("expires_at", 0))
                # 加载时自动清理已过期的记录
                if expires_at > now:
                    self._blocks[proxy_url] = {
                        "blocked_at": blocked_at,
                        "expires_at": expires_at,
                    }
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            self._blocks = {}

    def _save(self) -> None:
        """将封锁状态写入 JSON 文件。"""
        try:
            self._state_path.write_text(
                json.dumps(self._blocks, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    # ── 公开接口 ────────────────────────────────────────────────

    def mark_blocked(self, proxy_url: str) -> None:
        """标记代理被 CNKI 封锁（收到 418）。

        记录封锁时间戳，设置 24 小时后过期的冷却时间。

        Args:
            proxy_url: 被封锁的代理 URL
        """
        if not proxy_url:
            return
        now = time.time()
        self._blocks[proxy_url] = {
            "blocked_at": now,
            "expires_at": now + self._block_duration,
        }
        self._save()

    def is_blocked(self, proxy_url: str) -> bool:
        """判断代理是否处于 CNKI 封锁状态。

        自动检查是否已过期，过期的记录会被清除。

        Args:
            proxy_url: 代理 URL

        Returns:
            True 表示该代理当前被 CNKI 封锁
        """
        if not proxy_url:
            return False
        info = self._blocks.get(proxy_url)
        if info is None:
            return False
        # 检查是否已过期
        if time.time() >= info.get("expires_at", 0):
            # 自动清理过期记录
            self._blocks.pop(proxy_url, None)
            self._save()
            return False
        return True

    def cooldown_remaining(self, proxy_url: str) -> float:
        """返回代理的剩余冷却秒数。

        Args:
            proxy_url: 代理 URL

        Returns:
            剩余秒数；未封锁或已过期返回 0.0
        """
        if not proxy_url:
            return 0.0
        info = self._blocks.get(proxy_url)
        if info is None:
            return 0.0
        remaining = info.get("expires_at", 0) - time.time()
        if remaining <= 0:
            # 已过期，清理记录
            self._blocks.pop(proxy_url, None)
            self._save()
            return 0.0
        return remaining

    def unblock(self, proxy_url: str) -> bool:
        """手动解除代理的封锁状态。

        Args:
            proxy_url: 代理 URL

        Returns:
            True 表示成功解除，False 表示该代理未被封锁
        """
        if proxy_url in self._blocks:
            self._blocks.pop(proxy_url, None)
            self._save()
            return True
        return False

    def blocked_proxies(self) -> list[str]:
        """返回当前所有被封锁的代理 URL 列表。

        Returns:
            被封锁的代理 URL 列表（已自动清理过期记录）
        """
        now = time.time()
        expired = [
            url for url, info in self._blocks.items()
            if now >= info.get("expires_at", 0)
        ]
        for url in expired:
            self._blocks.pop(url, None)
        if expired:
            self._save()
        return list(self._blocks.keys())

    def clear_all(self) -> None:
        """清除所有封锁记录。"""
        self._blocks.clear()
        self._save()
