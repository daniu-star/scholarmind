"""CNKI 爬虫 418 冷却调度器 — 指数退避 + 随机抖动。

为 HTTP 418 反爬虫拦截提供统一的冷却等待策略：
  - wait(attempt): 指数退避 + 随机抖动，避免惊群效应
  - should_switch_proxy(attempt): 达到最大重试次数后建议切换代理
"""
from __future__ import annotations

import asyncio
import random


class CooldownScheduler:
    """418 冷却调度器：指数退避 + 随机抖动。

    Args:
        base_delay: 基础延迟（秒），默认 60.0
        max_delay: 最大延迟上限（秒），默认 1800.0（30 分钟）
        max_retries: 最大重试次数，达到后建议切换代理，默认 5
    """

    def __init__(
        self,
        base_delay: float = 60.0,
        max_delay: float = 1800.0,
        max_retries: int = 5,
    ) -> None:
        self.base_delay = float(base_delay)
        self.max_delay = float(max_delay)
        self.max_retries = int(max_retries)

    async def wait(self, attempt: int) -> float:
        """根据重试次数计算冷却时间并 await sleep。

        公式：min(base_delay * 2^attempt + random(0, base_delay), max_delay)

        Args:
            attempt: 当前重试次数（从 0 开始）

        Returns:
            实际等待的秒数
        """
        delay = min(
            self.base_delay * (2 ** attempt) + random.uniform(0, self.base_delay),
            self.max_delay,
        )
        await asyncio.sleep(delay)
        return delay

    def should_switch_proxy(self, attempt: int) -> bool:
        """判断是否应该切换代理。

        Args:
            attempt: 当前重试次数

        Returns:
            attempt >= max_retries 时返回 True
        """
        return attempt >= self.max_retries
