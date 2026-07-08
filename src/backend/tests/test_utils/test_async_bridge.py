"""async_bridge 工具测试"""
from __future__ import annotations

import asyncio
import pytest

from ...utils.async_bridge import run_async


async def _add(a: int, b: int) -> int:
    return a + b


async def _slow_return(value: str, delay: float = 0.01) -> str:
    await asyncio.sleep(delay)
    return value


class TestRunAsync:
    """同步→异步桥接"""

    def test_simple_coroutine(self):
        """直接调用 asyncio.run（无运行中 loop）"""
        result = run_async(_add(1, 2))
        assert result == 3

    def test_with_timeout_ok(self):
        """超时时间内完成"""
        result = run_async(_slow_return("done", delay=0.01), timeout=1.0)
        assert result == "done"

    def test_with_timeout_exceeded(self):
        """超时触发 TimeoutError"""
        with pytest.raises(asyncio.TimeoutError):
            run_async(_slow_return("slow", delay=10.0), timeout=0.01)

    def test_nested_loop(self):
        """在有运行中 event loop 时仍能工作（线程隔离）"""
        async def _inner():
            # 在已运行的 event loop 中调用 run_async（会走线程分支）
            return run_async(_add(3, 4))

        result = asyncio.run(_inner())
        assert result == 7
