"""任务事件重放与流式推送（PRD §7.3 / FR-11）。

要点：

- 事件在**写入数据库之后**才推送；断流不改变任务状态，也不触发结算。
- 客户端按 ``sequence`` 去重，因此流里的 ``id`` 就等于 ``sequence``。
- 事件接口接受 ``after_sequence`` 或 ``Last-Event-ID``；二者同时提供且不一致
  则 422 ``EVENT_SEQUENCE_MISMATCH``。
- 早于保留窗口的游标返回 410 ``EVENT_HISTORY_EXPIRED``（R0 尚未裁剪历史，
  用 ``MIN_EVENT_SEQUENCE`` 占位保留语义，路由层可据此提示改用快照）。
- 首次读取即终态且已排空时**立即结束**，不会挂起。
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import SCHEMA_VERSION, TERMINAL_STATUSES, TaskStatus
from .errors import ResearchAPIError, invalid
from .models import ResearchTask, TaskEvent
from . import task_repository

#: 保留窗口下界（占位）：序号 1 是每个任务的第一个事件。
MIN_EVENT_SEQUENCE = 1
#: 实时段的轮询间隔（秒）。
POLL_INTERVAL_SECONDS = 1.0
#: 单次流的最长存活时间（秒）。终态排空后立即返回，不受此限制。
#: 设上限是为了让代理/浏览器断开后的服务端协程一定退出，而不是无限挂起。
STREAM_MAX_SECONDS = 300.0
#: 按序号重放时的单次上限，避免一次读出巨量事件。
MAX_REPLAY_EVENTS = 2000


def serialize_event(event: TaskEvent) -> Dict[str, Any]:
    """把 ORM 行序列化为规范事件（PRD §7.3 字段集）。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": event.task_id,
        "sequence": int(event.sequence),
        "attempt_no": int(event.attempt_no or 0),
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "type": event.type,
        "payload": dict(event.payload_json or {}),
    }


def _resolve_cursor(
    *, after_sequence: Optional[int], last_event_id: Optional[int]
) -> int:
    """统一两种游标；都给出时必须一致（PRD §7.3）。"""
    normalized: List[int] = []
    for name, value in (
        ("after_sequence", after_sequence),
        ("last_event_id", last_event_id),
    ):
        if value is None:
            continue
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise invalid(
                "INVALID_EVENT_CURSOR", f"{name} 必须是整数。", {"field": name}
            ) from exc
        if number < 0:
            raise invalid(
                "INVALID_EVENT_CURSOR", f"{name} 不能为负数。", {"field": name}
            )
        normalized.append(number)

    if len(normalized) == 2 and normalized[0] != normalized[1]:
        raise invalid(
            "EVENT_SEQUENCE_MISMATCH",
            "after_sequence 与 Last-Event-ID 不一致。",
            {"after_sequence": normalized[0], "last_event_id": normalized[1]},
        )

    cursor = normalized[0] if normalized else 0
    if cursor < MIN_EVENT_SEQUENCE - 1:
        raise ResearchAPIError(
            "EVENT_HISTORY_EXPIRED",
            410,
            "事件历史已超出保留窗口。",
            {
                "min_sequence": MIN_EVENT_SEQUENCE,
                "snapshot_url": f"/api/research/tasks/{'unknown'}",
            },
        )
    return cursor


def _task_status(task: ResearchTask) -> Optional[TaskStatus]:
    try:
        return TaskStatus(task.status)
    except ValueError:  # pragma: no cover - 行数据损坏
        return None


def _is_terminal(task: ResearchTask) -> bool:
    status = _task_status(task)
    return status is not None and status in TERMINAL_STATUSES


async def replay(
    db: AsyncSession,
    task: ResearchTask,
    *,
    after_sequence: Optional[int] = None,
    last_event_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """按游标重放已持久化事件（升序）。"""
    cursor = _resolve_cursor(
        after_sequence=after_sequence, last_event_id=last_event_id
    )
    events = await task_repository.list_events(db, task.id, after_sequence=cursor)
    if len(events) > MAX_REPLAY_EVENTS:
        events = events[:MAX_REPLAY_EVENTS]
    return [serialize_event(event) for event in events]


async def stream(
    db: AsyncSession,
    task: ResearchTask,
    *,
    after_sequence: Optional[int] = None,
    last_event_id: Optional[int] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """先重放存量事件，再轮询增量；任务终态且排空后立即结束。"""
    cursor = _resolve_cursor(
        after_sequence=after_sequence, last_event_id=last_event_id
    )

    buffered = await task_repository.list_events(db, task.id, after_sequence=cursor)
    for event in buffered:
        cursor = max(cursor, int(event.sequence))
        yield serialize_event(event)
    if buffered and _is_terminal(task):
        return

    loop = asyncio.get_running_loop()
    deadline = loop.time() + float(STREAM_MAX_SECONDS)

    while True:
        if _is_terminal(task):
            # 终态之后再排空一次，确保最后一条事件不会因为事务快照而漏掉。
            tail = await task_repository.list_events(
                db, task.id, after_sequence=cursor
            )
            for event in tail:
                cursor = max(cursor, int(event.sequence))
                yield serialize_event(event)
            return

        if loop.time() >= deadline:
            # 超时不改状态、不结算：客户端可带 Last-Event-ID 重连（PRD §7.3）。
            return

        remaining = max(0.0, deadline - loop.time())
        await asyncio.sleep(min(float(POLL_INTERVAL_SECONDS), remaining) or 0.01)

        # 结束当前只读快照，下一次查询才能看到别的会话提交的新事件。
        try:
            await db.commit()
        except Exception:  # pragma: no cover - 只读会话极少失败
            await db.rollback()
        await db.refresh(task)

        fresh = await task_repository.list_events(db, task.id, after_sequence=cursor)
        for event in fresh:
            cursor = max(cursor, int(event.sequence))
            yield serialize_event(event)


__all__ = [
    "MIN_EVENT_SEQUENCE",
    "POLL_INTERVAL_SECONDS",
    "STREAM_MAX_SECONDS",
    "MAX_REPLAY_EVENTS",
    "serialize_event",
    "replay",
    "stream",
]
