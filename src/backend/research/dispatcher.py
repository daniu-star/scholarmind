"""研究任务派发器（PRD FR-11「提交后才派发」/ T08 装配层）。

为什么需要这一层：``task_service.create_task`` 只把任务登记进数据库，并把派发
意图写进 outbox（同一事务）；真正执行必须由**事务提交之后**的消费方完成。
本模块就是 R0 的消费方：

- 轮询 ``research_outbox_messages`` 的 ``pending`` 记录，标记已投递后按任务 ID
  交给 ``task_runner.execute_task``；
- 并发按 PRD §9 预算收敛：系统最多 3 个、单用户最多 1 个（用信号量 + 计数）；
- 每个任务独立会话，执行完提交；异常回滚但不打断轮询；
- 顺带清理超时排队任务（``task_service.expire_stale_queued_tasks``）。

进程内单实例即可满足 R0；切换到 Celery 时只需把 ``_dispatch_one`` 换成投递，
接口与 outbox 主题保持不变（见 PRD D-06）。
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Dict, Optional, Set

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import outbox, task_service
from .contracts import new_id, utcnow
from .models import ResearchTask

logger = logging.getLogger(__name__)

#: 派发主题（受理与手工重新入队都要消费）。
DISPATCH_TOPICS = frozenset({outbox.TOPIC_TASK_ACCEPTED, outbox.TOPIC_TASK_DISPATCH})

#: 轮询间隔（秒）：R0 用轻量轮询，不引入第二条队列。
POLL_INTERVAL_SECONDS = 0.5
#: 每轮最多取多少条待投递消息。
BATCH_SIZE = 20
#: 排队超时清理的检查周期（秒）。
REAP_INTERVAL_SECONDS = 30.0


class ResearchDispatcher:
    """进程内研究任务派发器。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        system_limit: int = 3,
        per_user_limit: int = 1,
        poll_interval: float = POLL_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._system_limit = max(1, int(system_limit))
        self._per_user_limit = max(1, int(per_user_limit))
        self._poll_interval = max(0.05, float(poll_interval))
        self._semaphore = asyncio.Semaphore(self._system_limit)
        self._in_flight: Set[asyncio.Task] = set()
        self._active = 0
        self._user_in_flight: Dict[int, int] = {}
        self._stop = asyncio.Event()
        self._worker: Optional[asyncio.Task] = None
        self._last_reap = 0.0

    # ── 生命周期 ────────────────────────────────────────────
    async def start(self) -> None:
        if self._worker is not None and not self._worker.done():
            return
        self._stop.clear()
        self._worker = asyncio.create_task(self._loop(), name="research-dispatcher")
        logger.info(
            "research dispatcher started (system_limit=%s per_user_limit=%s)",
            self._system_limit,
            self._per_user_limit,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(self._worker, timeout=5)
            self._worker = None
        pending = list(self._in_flight)
        for job in pending:
            job.cancel()
        if pending:
            with contextlib.suppress(Exception):
                await asyncio.gather(*pending, return_exceptions=True)
        self._in_flight.clear()
        logger.info("research dispatcher stopped")

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.drain_once()
            except asyncio.CancelledError:  # pragma: no cover - 关闭路径
                raise
            except Exception:  # noqa: BLE001 - 轮询不能因单轮异常退出
                logger.warning("research dispatcher iteration failed", exc_info=True)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval)

    # ── 单轮 ────────────────────────────────────────────────
    async def drain_once(self) -> int:
        """消费一批待投递消息，返回本轮提交执行的任务数。"""
        async with self._session_factory() as db:
            messages = await outbox.pending(db, limit=BATCH_SIZE)
            if not messages:
                await self._maybe_reap(db)
                return 0
            dispatched = 0
            for message in messages:
                if message.topic not in DISPATCH_TOPICS:
                    # 未知主题：标记已投递，避免永远堵在队列里。
                    await outbox.mark_published(db, message)
                    continue
                task_id = (message.payload_json or {}).get("task_id") or message.task_id
                await outbox.mark_published(db, message)
                if not task_id:
                    continue
                if await self._submit(str(task_id)):
                    dispatched += 1
            await db.commit()
            return dispatched

    async def _submit(self, task_id: str) -> bool:
        """在并发预算内启动一个任务执行协程；超预算则跳过（下一轮再试）。"""
        if self._active >= self._system_limit:
            return False
        self._active += 1
        job = asyncio.create_task(self._dispatch_one(task_id), name=f"research-task-{task_id}")
        self._in_flight.add(job)

        def _done(_job: asyncio.Task) -> None:
            self._in_flight.discard(_job)
            self._active = max(0, self._active - 1)

        job.add_done_callback(_done)
        return True

    async def _dispatch_one(self, task_id: str) -> None:
        from .task_runner import execute_task

        async with self._semaphore:
            async with self._session_factory() as db:
                task = await db.get(ResearchTask, task_id)
                if task is None:
                    return
                owner_id = int(getattr(task, "owner_id", 0) or 0)
                if self._user_in_flight.get(owner_id, 0) >= self._per_user_limit:
                    # 单用户并发已满：不动任务状态，下一轮重新派发。
                    return
                self._user_in_flight[owner_id] = self._user_in_flight.get(owner_id, 0) + 1
                try:
                    await execute_task(db, task, holder=f"dispatcher:{new_id('disp')}")
                    await db.commit()
                except Exception:  # noqa: BLE001 - 单任务失败不影响派发器
                    await db.rollback()
                    logger.exception("research task dispatch failed: %s", task_id)
                finally:
                    remaining = self._user_in_flight.get(owner_id, 1) - 1
                    if remaining > 0:
                        self._user_in_flight[owner_id] = remaining
                    else:
                        self._user_in_flight.pop(owner_id, None)

    async def _maybe_reap(self, db: AsyncSession) -> None:
        now = utcnow().timestamp()
        if now - self._last_reap < REAP_INTERVAL_SECONDS:
            return
        self._last_reap = now
        try:
            expired = await task_service.expire_stale_queued_tasks(db)
            await db.commit()
            if expired:
                logger.info("expired %s stale queued research task(s)", expired)
        except Exception:  # noqa: BLE001
            await db.rollback()
            logger.warning("stale queued research task reaper failed", exc_info=True)


def create_dispatcher(session_factory: async_sessionmaker[AsyncSession]) -> ResearchDispatcher:
    """按 PRD §9 预算创建派发器（并发与超时值来自 settings）。"""
    from ..config import settings

    return ResearchDispatcher(
        session_factory,
        system_limit=int(getattr(settings, "RESEARCH_MAX_CONCURRENT_SYSTEM", 3)),
        per_user_limit=int(getattr(settings, "RESEARCH_MAX_CONCURRENT_PER_USER", 1)),
    )


__all__ = ["ResearchDispatcher", "create_dispatcher", "DISPATCH_TOPICS", "POLL_INTERVAL_SECONDS"]
