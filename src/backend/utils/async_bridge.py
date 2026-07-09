"""同步→异步桥接工具

在 Celery 同步任务或 CLI 脚本中安全地调用 async 协程。

设计要点：
- 复用单一 ThreadPoolExecutor（避免每次调用创建/销毁线程池）
- 检测是否有运行中的 event loop，自动选择直调 asyncio.run 或线程隔离
- 明确标注适用场景和风险

用法：
    from src.backend.utils.async_bridge import run_async
    result = run_async(my_async_function(arg1, arg2))
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")

# 专用线程池（用于隔离 event loop），避免每次调用创建新线程池
_loop_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="async-bridge-")


def run_async(coro: Coroutine[Any, Any, T], timeout: float | None = None) -> T:
    """在同步上下文中运行异步协程。

    Args:
        coro: 异步协程对象
        timeout: 可选的超时时间（秒），None 表示无限等待

    Returns:
        协程的返回值

    Raises:
        asyncio.TimeoutError: 超时未完成时抛出

    实现策略:
        - 若无运行中的 event loop → 直接 asyncio.run(coro)（最简单可靠）
        - 若有运行中的 event loop → 在新线程中创建独立 loop 运行（避免嵌套 loop 冲突）
          典型场景：Celery worker 使用了 asyncio 事件循环时调用 sync 任务

    注意:
        此函数会阻塞当前线程直到协程完成。仅适用于同步→异步的桥接场景
        （如 Celery 任务调用 async 服务方法），不应在 async 请求处理路径中使用。
    """
    try:
        _ = asyncio.get_running_loop()
    except RuntimeError:
        # 无运行中的 event loop → 直接在当前线程运行
        if timeout is not None:
            return asyncio.run(asyncio.wait_for(coro, timeout=timeout))
        return asyncio.run(coro)

    # 有运行中的 event loop（如 Celery worker 已在 asyncio 模式下）
    # → 在新线程的独立 event loop 中运行，避免冲突
    future = _loop_executor.submit(_run_in_new_loop, coro, timeout)
    return future.result()


def _run_in_new_loop(coro: Coroutine[Any, Any, T], timeout: float | None = None) -> T:
    """在新线程的独立 event loop 中运行协程。"""
    if timeout is not None:
        return asyncio.run(asyncio.wait_for(coro, timeout=timeout))
    return asyncio.run(coro)
