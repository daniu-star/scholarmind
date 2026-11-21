"""任务与事件的持久化原语（PRD FR-11 / §7.1 / §7.3）。

本模块只做**行级**读写，不提交事务、不做鉴权、不扣额度：

- 事务边界由 ``task_service`` 统一持有（受理 = 任务行 + 额度预留 + 事件 +
  outbox 同事务提交，PRD FR-11）；
- 归属过滤由 ``ownership.require_*`` 在服务层完成，本层不做隐式放行；
- ``transition`` 是唯一允许改 ``status`` 的入口：它复用
  ``contracts.can_transition``，保证状态机与 ``state_revision`` 单调递增
  无法被绕过（PRD §7.1）。
"""
from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import (
    SCHEMA_VERSION,
    Actor,
    Coverage,
    EventType,
    QualityVerdict,
    ResearchTaskInput,
    TaskStatus,
    TERMINAL_STATUSES,
    can_transition,
    new_id,
    normalize_text,
    utcnow,
)
from .errors import conflict, internal, invalid
from .models import ResearchTask, TaskAttempt, TaskEvent

#: 新 attempt 默认租约（PRD §9「任务累计运行期限 1200 秒」）。
DEFAULT_LEASE_SECONDS = 1200

#: 当前执行器持有的 fencing token（PRD FR-11：租约转移后旧执行器不得再写）。
_LEASE_TOKEN: ContextVar[Optional[int]] = ContextVar("research_lease_token", default=None)


def set_lease_scope(fencing_token: Optional[int]) -> Any:
    """把 fencing token 绑定到当前执行上下文（由 ``task_runner`` 执行期调用）。"""
    return _LEASE_TOKEN.set(fencing_token)


def reset_lease_scope(handle: Any) -> None:
    """恢复上一个上下文 token，必须与 :func:`set_lease_scope` 成对使用。"""
    _LEASE_TOKEN.reset(handle)


async def _current_fencing_token(db: AsyncSession, task_id: str) -> Optional[int]:
    """该任务当前最大 attempt 的 fencing token（没有 attempt 时返回 None）。"""
    value = await db.scalar(
        select(func.max(TaskAttempt.fencing_token)).where(TaskAttempt.task_id == task_id)
    )
    return int(value) if value is not None else None


async def _enforce_fence(
    db: AsyncSession, task_id: str, fencing_token: Optional[int]
) -> None:
    """拒绝「租约已被接管」的旧执行器写入（PRD FR-11 fencing）。

    ``fencing_token`` 缺省时回退到 :func:`set_lease_scope` 绑定的上下文 token；
    两者都没有（例如 API 层的 cancel/retry 这类无租约写入）时不校验——那时
    写入者并不是某一个 attempt，允许按状态机规则迁移。
    """
    effective = fencing_token if fencing_token is not None else _LEASE_TOKEN.get()
    if effective is None:
        return
    current = await _current_fencing_token(db, task_id)
    if current is None:
        return  # 任务没有任何 attempt：不构成「租约转移」
    if int(effective) == current:
        return
    raise conflict(
        "STALE_ATTEMPT",
        "执行权已转移，本次写入被拒绝。",
        {"fencing_token": int(effective), "current_fencing_token": current},
    )
#: 事件序号并发冲突的重试次数（含首次尝试共 2 次写入）。
EVENT_SEQUENCE_RETRIES = 2


def _validation_details(exc: ValidationError) -> Dict[str, Any]:
    errors = []
    for item in exc.errors()[:20]:
        errors.append(
            {
                "loc": [str(part) for part in item.get("loc", ())],
                "type": str(item.get("type", "")),
                "msg": str(item.get("msg", "")),
            }
        )
    return {"errors": errors}


def _coerce_coverage(value: Any) -> Coverage:
    if isinstance(value, Coverage):
        return value
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        # analysis_ratio / full_coverage 是派生属性，不接受回写。
        data = {
            key: item
            for key, item in value.items()
            if key not in {"analysis_ratio", "full_coverage"}
        }
        try:
            return Coverage.model_validate(data)
        except ValidationError as exc:
            raise invalid("INVALID_COVERAGE", "覆盖数据不合法。", _validation_details(exc)) from exc
    raise invalid("INVALID_COVERAGE", "覆盖数据必须是对象。")


def _coerce_verdict(value: Any) -> Optional[QualityVerdict]:
    if value is None:
        return None
    if isinstance(value, QualityVerdict):
        return value
    try:
        return QualityVerdict(str(value))
    except ValueError as exc:
        raise invalid("INVALID_QUALITY_VERDICT", "质量结论取值不合法。") from exc


def _jsonable(value: Any, *, field: str) -> Dict[str, Any]:
    if isinstance(value, BaseModel):
        return dict(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return dict(value)
    raise invalid("INVALID_PAYLOAD", f"{field} 必须是对象。", {"field": field})


def _base_summary(payload: ResearchTaskInput, now: datetime) -> Dict[str, Any]:
    """受理时的执行快照（诚实版）：模型与预算由执行层补齐（PRD §8.3）。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": payload.kind.value,
        "mode_requested": payload.mode,
        "skill_ids": list(payload.skill_ids),
        "input_version_ids": {
            "document_version_id": payload.input.document_version_id,
            "outline_document_version_id": payload.input.outline_document_version_id,
        },
        "source_ids_count": len(payload.input.source_ids),
        "finding_ids_count": len(payload.scope.finding_ids),
        "accepted_at": now.isoformat(),
        "actual_model": "unknown",
    }


def _validate_event(
    *,
    task_id: str,
    sequence: int,
    attempt_no: int,
    event_type: str,
    created_at: datetime,
    payload: Dict[str, Any],
) -> None:
    # 复用契约 DTO 校验 payload 规则（tool.completed 必须带持久化 ID 等）。
    from .contracts import TaskEventDTO

    try:
        TaskEventDTO.model_validate(
            {
                "task_id": task_id,
                "sequence": sequence,
                "attempt_no": attempt_no,
                "created_at": created_at,
                "type": event_type,
                "payload": payload,
            }
        )
    except ValidationError as exc:
        raise invalid(
            "INVALID_EVENT_PAYLOAD",
            "事件负载不合法。",
            _validation_details(exc),
        ) from exc


async def create_task(
    db: AsyncSession,
    actor: Actor,
    payload: ResearchTaskInput,
    *,
    idempotency_key: Optional[str],
    request_fingerprint: str,
    billing_group_id: str,
) -> ResearchTask:
    """写入任务行（queued / state_revision=1），不提交。"""
    now = utcnow()
    task = ResearchTask(
        id=new_id("task"),
        owner_id=actor.user_id,
        project_id=payload.project_id,
        kind=payload.kind.value,
        status=TaskStatus.QUEUED.value,
        objective=normalize_text(payload.objective),
        input_json=payload.input.model_dump(mode="json"),
        scope_json=payload.scope.model_dump(mode="json"),
        constraints_json=payload.constraints.model_dump(mode="json"),
        state_revision=1,
        billing_group_id=billing_group_id,
        billing_state=None,
        attempt_no=0,
        snapshot_summary=_base_summary(payload, now),
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    await db.flush()
    return task


async def find_by_idempotency(
    db: AsyncSession, owner_id: int, key: str
) -> Optional[ResearchTask]:
    """按 (owner, Idempotency-Key) 找已受理任务；必须带 owner 过滤。"""
    result = await db.execute(
        select(ResearchTask).where(
            ResearchTask.owner_id == owner_id,
            ResearchTask.idempotency_key == key,
        )
    )
    return result.scalars().first()


async def next_sequence(db: AsyncSession, task_id: str) -> int:
    """下一个事件序号（严格单调，从 1 开始）。"""
    value = await db.scalar(
        select(func.max(TaskEvent.sequence)).where(TaskEvent.task_id == task_id)
    )
    return int(value or 0) + 1


async def append_event(
    db: AsyncSession,
    task: ResearchTask,
    event_type: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
    fencing_token: Optional[int] = None,
) -> TaskEvent:
    """追加事件；``(task_id, sequence)`` 唯一，冲突时重算序号重试一次。"""
    await _enforce_fence(db, task.id, fencing_token)
    try:
        event_type_value = EventType(str(event_type)).value
    except ValueError as exc:
        raise invalid("INVALID_EVENT_TYPE", f"未知事件类型：{event_type!r}") from exc

    body = dict(payload or {})
    attempt_no = int(task.attempt_no or 0)
    last_error: Optional[BaseException] = None

    for _ in range(EVENT_SEQUENCE_RETRIES):
        sequence = await next_sequence(db, task.id)
        created_at = utcnow()
        _validate_event(
            task_id=task.id,
            sequence=sequence,
            attempt_no=attempt_no,
            event_type=event_type_value,
            created_at=created_at,
            payload=body,
        )
        event = TaskEvent(
            task_id=task.id,
            sequence=sequence,
            attempt_no=attempt_no,
            type=event_type_value,
            payload_json=body,
            created_at=created_at,
        )
        try:
            async with db.begin_nested():
                db.add(event)
                await db.flush()
            return event
        except IntegrityError as exc:  # 并发写入同一序号
            last_error = exc
            continue

    raise conflict(
        "EVENT_SEQUENCE_CONFLICT",
        "事件序号冲突，请重试。",
        {"task_id": task.id},
    ) from last_error


async def transition(
    db: AsyncSession,
    task: ResearchTask,
    status: TaskStatus | str,
    *,
    error: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    coverage: Optional[Any] = None,
    quality_verdict: Optional[Any] = None,
    snapshot_summary: Optional[Dict[str, Any]] = None,
    fencing_token: Optional[int] = None,
) -> ResearchTask:
    """唯一的状态迁移入口：校验 ALLOWED_TRANSITIONS，递增 state_revision。"""
    await _enforce_fence(db, task.id, fencing_token)
    try:
        target = status if isinstance(status, TaskStatus) else TaskStatus(str(status))
    except ValueError as exc:
        raise invalid("INVALID_STATUS", f"未知任务状态：{status!r}") from exc
    try:
        current = TaskStatus(task.status)
    except ValueError as exc:  # pragma: no cover - 行数据损坏
        raise internal("任务状态数据损坏，请联系支持。") from exc

    if not can_transition(current, target):
        raise conflict(
            "INVALID_TRANSITION",
            f"任务不能从 {current.value} 迁移到 {target.value}。",
            {"from": current.value, "to": target.value},
        )

    coverage_model = _coerce_coverage(coverage) if coverage is not None else None
    verdict = _coerce_verdict(quality_verdict)
    if verdict is not None and target is not TaskStatus.SUCCEEDED:
        raise invalid(
            "QUALITY_VERDICT_NOT_ALLOWED",
            "仅 succeeded 任务可携带质量结论。",
            {"status": target.value},
        )

    now = utcnow()
    task.status = target.value
    task.state_revision = int(task.state_revision or 0) + 1
    task.updated_at = now

    if error is not None:
        task.error_json = _jsonable(error, field="error")
    if result is not None:
        task.result_json = _jsonable(result, field="result")
    if coverage_model is not None:
        task.coverage_json = coverage_model.model_dump(mode="json")
    if verdict is not None:
        task.quality_verdict = verdict.value
    if snapshot_summary:
        merged = dict(task.snapshot_summary or {})
        merged.update(snapshot_summary)
        task.snapshot_summary = merged
    if target in TERMINAL_STATUSES:
        task.ended_at = now

    await db.flush()
    return task


async def open_attempt(
    db: AsyncSession,
    task: ResearchTask,
    *,
    lease_holder: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> TaskAttempt:
    """领取执行权：递增 attempt_no 与 fencing_token，写租约（PRD FR-11）。"""
    if not isinstance(lease_holder, str) or not lease_holder.strip():
        raise ValueError("lease_holder 必须是非空字符串")
    if not isinstance(lease_seconds, int) or lease_seconds <= 0:
        raise ValueError("lease_seconds 必须是正整数")
    holder = lease_holder.strip()[:64]

    # 终态任务不可再领取执行权（FR-11「拒绝覆盖旧结果」）。
    current_status = TaskStatus(task.status)
    if current_status in TERMINAL_STATUSES:
        raise conflict(
            "TASK_NOT_CLAIMABLE",
            "任务已结束，不可再次领取执行权。",
            {"task_id": task.id, "status": current_status.value},
        )

    # 已有未过期租约时拒绝重复领取，保证重入不重复执行（FR-11 租约 + fencing）。
    lease_held = await db.scalar(
        select(TaskAttempt.id)
        .where(
            TaskAttempt.task_id == task.id,
            TaskAttempt.status == "running",
            TaskAttempt.lease_expires_at.is_not(None),
            TaskAttempt.lease_expires_at > utcnow(),
        )
        .limit(1)
    )
    if lease_held is not None:
        raise conflict(
            "LEASE_HELD",
            "该任务已由其他执行器持有租约。",
            {"task_id": task.id},
        )

    def _new_attempt(number: int) -> TaskAttempt:
        now = utcnow()
        return TaskAttempt(
            id=new_id("attempt"),
            task_id=task.id,
            attempt_no=number,
            status="running",
            lease_holder=holder,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            fencing_token=number,
            started_at=now,
        )

    task.attempt_no = int(task.attempt_no or 0) + 1
    attempt = _new_attempt(task.attempt_no)
    try:
        async with db.begin_nested():
            db.add(attempt)
            await db.flush()
        return attempt
    except IntegrityError as exc:
        # 并发领取同一 attempt_no：重新读取最新序号后重试一次。
        await db.refresh(task)
        task.attempt_no = int(task.attempt_no or 0) + 1
        attempt = _new_attempt(task.attempt_no)
        try:
            async with db.begin_nested():
                db.add(attempt)
                await db.flush()
            return attempt
        except IntegrityError as second:  # pragma: no cover - 极端并发
            raise conflict(
                "ATTEMPT_CONFLICT",
                "任务执行权冲突，请重试。",
                {"task_id": task.id},
            ) from second
        finally:
            _ = exc


async def close_attempt(
    db: AsyncSession,
    attempt: TaskAttempt,
    status: str,
    *,
    error: Optional[Dict[str, Any]] = None,
    fencing_token: Optional[int] = None,
) -> None:
    """结束一次 attempt；不删除行（审计与 fencing 需要保留）。"""
    await _enforce_fence(db, attempt.task_id, fencing_token)
    attempt.status = str(status)[:24]
    if error is not None:
        attempt.error_json = _jsonable(error, field="error")
    attempt.ended_at = utcnow()
    await db.flush()


async def list_events(
    db: AsyncSession, task_id: str, *, after_sequence: int = 0
) -> List[TaskEvent]:
    """按序号升序列出 ``sequence > after_sequence`` 的事件。"""
    result = await db.execute(
        select(TaskEvent)
        .where(
            TaskEvent.task_id == task_id,
            TaskEvent.sequence > int(after_sequence),
        )
        .order_by(TaskEvent.sequence)
    )
    return list(result.scalars().all())


__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "EVENT_SEQUENCE_RETRIES",
    "create_task",
    "find_by_idempotency",
    "next_sequence",
    "append_event",
    "transition",
    "open_attempt",
    "close_attempt",
    "list_events",
    "set_lease_scope",
    "reset_lease_scope",
]
