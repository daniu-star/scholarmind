"""事务外盒（PRD FR-11 / §6 OutboxMessage / §8.3）。

任务登记、额度预留与待投递记录必须在**同一事务**内写入（由
``task_service.create_task`` 保证）：本模块的 ``enqueue`` 只把消息挂到当前会话，
不提交、不派发；事务提交之后才允许执行器读取 ``pending`` 并投递。
重复投递是允许的，重复执行副作用则由消费方（bill_group 幂等）负责。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import new_id, utcnow
from .models import OutboxMessage

#: 任务被受理后派发给执行器的主题（PRD FR-11「提交后才派发」）。
TOPIC_TASK_ACCEPTED = "research.task.accepted"
#: 需要执行器重新拾取任务的主题（resume / 可选钩子 enqueue_task）。
TOPIC_TASK_DISPATCH = "research.task.dispatch"

#: ``OutboxMessage.last_error`` 列长度（String(400)），写入前截断，避免提交失败。
MAX_ERROR_LENGTH = 400
#: 单次批量读取上限；调用方可以请求更小的批。
MAX_PENDING_LIMIT = 500


def enqueue(
    db: AsyncSession,
    topic: str,
    payload: Dict[str, Any],
    *,
    task_id: Optional[str] = None,
) -> OutboxMessage:
    """把待投递消息挂到当前事务（同步、无 I/O、不 flush）。

    必须由调用方在同一事务内 flush/commit；本函数不捕获异常也不提交。
    """
    if not topic or not isinstance(topic, str):
        raise ValueError("outbox topic 必须是非空字符串")
    message = OutboxMessage(
        id=new_id("outbox"),
        topic=topic,
        task_id=task_id,
        payload_json=dict(payload or {}),
    )
    db.add(message)
    return message


async def pending(db: AsyncSession, *, limit: int = 50) -> List[OutboxMessage]:
    """按创建顺序读取未投递消息（``published_at IS NULL``）。"""
    if limit <= 0:
        raise ValueError("limit 必须为正整数")
    limit = min(int(limit), MAX_PENDING_LIMIT)
    result = await db.execute(
        select(OutboxMessage)
        .where(OutboxMessage.published_at.is_(None))
        .order_by(OutboxMessage.created_at, OutboxMessage.id)
        .limit(limit)
    )
    return list(result.scalars().all())


async def mark_published(db: AsyncSession, message: OutboxMessage) -> None:
    """标记已投递；重复调用保持首次时间（幂等）。"""
    if message.published_at is None:
        message.published_at = utcnow()
    await db.flush()


async def mark_failed(db: AsyncSession, message: OutboxMessage, error: str) -> None:
    """记录一次失败尝试；不改变 ``published_at``，由调度器决定重试节奏。"""
    message.attempts = int(message.attempts or 0) + 1
    message.last_error = (error or "")[:MAX_ERROR_LENGTH]
    await db.flush()


__all__ = [
    "TOPIC_TASK_ACCEPTED",
    "TOPIC_TASK_DISPATCH",
    "MAX_ERROR_LENGTH",
    "MAX_PENDING_LIMIT",
    "enqueue",
    "pending",
    "mark_published",
    "mark_failed",
]
