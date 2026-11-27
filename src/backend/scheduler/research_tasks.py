"""Celery 执行入口：让研究任务可以走真实 broker。

生产默认仍由进程内 ``ResearchDispatcher`` 调度（``TASK_BACKEND="background"``）；
本模块只在显式发布 ``research.execute_task`` 消息、或做 broker/worker 恢复演练时使用。

为什么要单独一个任务：``execute_task`` 需要 ``AsyncSession``，而 Celery worker
是同步进程，这里用 ``asyncio.run`` 建一个一次性事件循环，并在结束时释放引擎。
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

from celery.signals import worker_ready

from .celery_app import celery_app

logger = structlog.get_logger(__name__)


class _SlowClient:
    """演练用包装：每次模型调用前 sleep，制造足够长的「执行中」窗口以便 kill。"""

    def __init__(self, inner: Any, delay_ms: int) -> None:
        self._inner = inner
        self._delay = max(0, int(delay_ms)) / 1000.0

    async def complete(self, system: str, user: str, *, json_schema: Optional[dict] = None) -> str:
        if self._delay:
            await asyncio.sleep(self._delay)
        return await self._inner.complete(system, user, json_schema=json_schema)


async def _execute(task_id: str, holder: str, slow_ms: int) -> dict:
    from src.backend.config import settings
    from src.backend.db.session import (
        create_async_engine_from_url,
        create_async_sessionmaker_from_engine,
    )
    from sqlalchemy import select

    from src.backend.research import runtime, task_runner
    from src.backend.research.contracts import utcnow
    from src.backend.research.models import ResearchTask, TaskAttempt

    engine = create_async_engine_from_url(settings.DATABASE_URL)
    factory = create_async_sessionmaker_from_engine(engine)
    try:
        async with factory() as db:
            task = await db.get(ResearchTask, task_id)
            if task is None:
                return {"task_id": task_id, "status": "missing"}
            if str(task.status) == "running":
                # 崩溃重投的常见竞态：消息回来了，但旧执行者的租约还没过期。
                # 此时直接 execute_task 会「安全放弃」并让 Celery ack 掉消息，
                # 任务就永远停在 running。正确做法是等租约过期后再试。
                attempt = await db.scalar(
                    select(TaskAttempt)
                    .where(
                        TaskAttempt.task_id == task_id,
                        TaskAttempt.status == "running",
                        TaskAttempt.lease_expires_at.is_not(None),
                        TaskAttempt.lease_expires_at > utcnow(),
                    )
                    .order_by(TaskAttempt.attempt_no.desc())
                )
                if attempt is not None:
                    wait = max(2, int((attempt.lease_expires_at - utcnow()).total_seconds()) + 5)
                    return {
                        "task_id": task_id,
                        "status": "deferred",
                        "defer_seconds": wait,
                    }
            client = None
            if slow_ms > 0:
                # 用真实快照构造客户端，再包一层 sleep；不改变流水线语义。
                _, snapshot = task_runner._model_snapshot(task)  # noqa: SLF001 - 演练工具
                client = _SlowClient(runtime.get_client(snapshot), slow_ms)
            await task_runner.execute_task(db, task, holder=holder, client=client)
            await db.commit()
            await db.refresh(task)
            return {
                "task_id": task_id,
                "status": task.status,
                "attempt_no": task.attempt_no,
            }
    finally:
        await engine.dispose()


@celery_app.task(
    bind=True,
    name="research.execute_task",
    acks_late=True,
    max_retries=3,
    default_retry_delay=5,
)
def execute_research_task(
    self,
    task_id: str,
    holder: Optional[str] = None,
    slow_ms: int = 0,
) -> dict:
    """消费一条研究任务消息；重复投递由任务状态机与租约保证 exactly-once。"""
    resolved = holder or f"celery:{self.request.id}"
    try:
        outcome = asyncio.run(_execute(task_id, resolved, int(slow_ms or 0)))
        if outcome.get("status") == "deferred":
            raise self.retry(countdown=int(outcome.get("defer_seconds") or 10))
        return outcome
    except Exception as exc:  # noqa: BLE001 - 交给 Celery 记录并重试
        logger.warning(
            "research.celery_task_failed",
            task_id=task_id,
            error=type(exc).__name__,
            detail=str(exc)[:200],
        )
        raise


async def _reap() -> int:
    from src.backend.config import settings
    from src.backend.db.session import (
        create_async_engine_from_url,
        create_async_sessionmaker_from_engine,
    )
    from src.backend.research import task_service

    engine = create_async_engine_from_url(settings.DATABASE_URL)
    factory = create_async_sessionmaker_from_engine(engine)
    try:
        async with factory() as db:
            return await task_service.expire_stale_queued_tasks(db)
    finally:
        await engine.dispose()


@celery_app.task(name="research.reap_stale_queued", acks_late=False)
def reap_stale_queued() -> dict:
    """把排队超时的任务诚实失败并释放额度。

    为什么需要它：broker 丢消息（例如 Redis 未持久化却被重启）时，消息永远不会再
    投递，任务会永久停在 ``queued``。进程内 dispatcher 有 30s 的清扫循环，但 broker
    模式下没有 ``_maybe_reap()``，所以这里补一个周期性清扫（beat 每分钟）并在
    worker 启动时立即扫一次，避免「重启后才恢复」的长期悬挂。
    """
    count = asyncio.run(_reap())
    if count:
        logger.warning("research.stale_queued_reaped", count=count)
    return {"reaped": count}


@worker_ready.connect
def _reap_on_worker_ready(**_kwargs: Any) -> None:
    """worker 启动即扫一次：恢复演练里重启 worker 后立刻可见诚实失败。"""
    try:
        reap_stale_queued.delay()
    except Exception:  # noqa: BLE001 - 清扫失败不应阻止 worker 启动
        logger.warning("research.reaper_dispatch_failed", exc_info=True)


__all__ = ["execute_research_task", "reap_stale_queued"]
