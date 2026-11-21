"""任务额度账本编排（PRD FR-14 / §8.3 / 账本表 PRD line 252-264）。

设计边界：

- **不重写扣减规则**：真正的扣减/退回复用
  ``services.entitlement_service.EntitlementService.consume_pipeline`` /
  ``refund_pipeline``，避免出现两份额度语义。本模块只做账本行
  （``research_billing_operations``）与 ``ResearchTask.billing_state`` 的编排，
  与任务登记同事务，不提交。
- 能力映射固定，不允许按请求临时改变（FR-14）：
  review→external_review、revision→modification、
  draft_from_outline→generation、literature_review→external_review、
  chart/export→None（不消耗单次研究额度）。

不变量（由数据库唯一约束兜底，而不是只靠代码顺序）：

1. 同一 ``billing_group_id`` 同时最多一个**有效预留**（``state='reserved'`` 且
   ``operation LIKE 'reserve:%'``）：重试/恢复必须先释放旧预留，否则 409
   ``BILLING_GROUP_ACTIVE``——同一个计费组不能同时持有两份额度。
2. 同一 ``billing_group_id`` 最多**一次结算**：结算行 ``operation`` 恒为
   ``settle``，唯一约束 ``uq_billing_group_operation`` 保证重复结算只生效一次。
3. 每个预留最多**释放一次**：释放行 ``operation = 'release:<reserve 序号>'``。
4. ``settle`` / ``release`` 幂等：重复调用不再次扣减/退还，也不改账本金额
   （PRD「重复回调/投递/点击 → 返回既有结果不重复」）。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.entitlement_service import (
    EntitlementError,
    EntitlementService,
    PipelineCapability,
)
from .contracts import Actor, BillingState, TaskKind, new_id, utcnow
from .errors import conflict, invalid, payment_required
from .models import BillingOperation, ResearchTask

#: 固定的任务类型 → 计费能力映射（PRD FR-14，逐项固定，不允许运行时改写）。
CAPABILITY_BY_KIND: Dict[TaskKind, Optional[PipelineCapability]] = {
    TaskKind.REVIEW: "external_review",
    TaskKind.REVISION: "modification",
    TaskKind.DRAFT_FROM_OUTLINE: "generation",
    TaskKind.LITERATURE_REVIEW: "external_review",
    TaskKind.CHART: None,
    TaskKind.EXPORT: None,
}

#: 账本行的操作名（``operation`` 列 String(16)，受 ``uq_billing_group_operation`` 约束）。
RESERVE_PREFIX = "reserve:"
SETTLE_OPERATION = "settle"
RELEASE_PREFIX = "release:"

#: 预留/持有/结算/释放的生命周期状态（写入 ``BillingOperation.state``）。
OP_RESERVED = "reserved"
OP_SETTLED = "settled"
OP_RELEASED = "released"

#: ``BillingOperation.note`` 列长度；超出会被截断而不是让提交失败。
MAX_NOTE_LENGTH = 400


# ── 内部工具 ─────────────────────────────────────────────────


def _capability_for(kind: TaskKind | str) -> Optional[PipelineCapability]:
    try:
        kind_enum = kind if isinstance(kind, TaskKind) else TaskKind(str(kind))
    except ValueError as exc:  # pragma: no cover - 由契约层保证
        raise invalid("INVALID_TASK_KIND", f"未知任务类型：{kind!r}") from exc
    return CAPABILITY_BY_KIND[kind_enum]


def _note(task_id: str, *, consumed: str, detail: str = "") -> str:
    parts = [f"task={task_id}", f"consumed={consumed or 'none'}"]
    if detail:
        parts.append(detail)
    return ";".join(parts)[:MAX_NOTE_LENGTH]


def _parse_note(note: str | None) -> Dict[str, str]:
    """把 ``task=...;consumed=...`` 解析回键值对（note 是唯一能存文本的列）。"""
    parsed: Dict[str, str] = {}
    for chunk in (note or "").split(";"):
        if "=" in chunk:
            key, value = chunk.split("=", 1)
            parsed[key.strip()] = value.strip()
    return parsed


def _set_task_billing(task: ResearchTask, state: BillingState) -> None:
    task.billing_state = state.value


def _reservation_payload(row: BillingOperation) -> Dict[str, Any]:
    parsed = _parse_note(row.note)
    return {
        "task_id": row.task_id,
        "billing_group_id": row.billing_group_id,
        "operation": row.operation,
        "capability": row.entitlement or None,
        "entitlement": row.entitlement or "",
        "consumed": parsed.get("consumed", "none"),
        "amount_units": int(row.amount_units or 0),
        "state": row.state,
    }


async def _get_operation(
    db: AsyncSession, billing_group_id: str, operation: str
) -> Optional[BillingOperation]:
    result = await db.execute(
        select(BillingOperation).where(
            BillingOperation.billing_group_id == billing_group_id,
            BillingOperation.operation == operation,
        )
    )
    return result.scalar_one_or_none()


async def _count_reserves(db: AsyncSession, billing_group_id: str) -> int:
    value = await db.scalar(
        select(func.count())
        .select_from(BillingOperation)
        .where(
            BillingOperation.billing_group_id == billing_group_id,
            BillingOperation.operation.like(f"{RESERVE_PREFIX}%"),
        )
    )
    return int(value or 0)


async def _active_reservation(
    db: AsyncSession, billing_group_id: str
) -> Optional[BillingOperation]:
    result = await db.execute(
        select(BillingOperation)
        .where(
            BillingOperation.billing_group_id == billing_group_id,
            BillingOperation.state == OP_RESERVED,
            BillingOperation.operation.like(f"{RESERVE_PREFIX}%"),
        )
        .order_by(BillingOperation.created_at.desc(), BillingOperation.id.desc())
        .limit(1)
    )
    return result.scalars().first()


def _entitlement_error(exc: EntitlementError, capability: str) -> Any:
    """把权益服务错误翻译成对外 402，并保留能力名（PRD §8.4）。"""
    details: Dict[str, Any] = {
        "capability": capability,
        "entitlement_code": getattr(exc, "code", "PAYMENT_REQUIRED"),
    }
    return payment_required(getattr(exc, "message", str(exc)), details)


# ── 对外接口（R0_INTERFACE_SPEC §1） ────────────────────────


async def reserve(
    db: AsyncSession,
    actor: Actor,
    task: ResearchTask,
    kind: TaskKind | str,
) -> Dict[str, Any]:
    """为任务原子预留额度；返回可传回 ``settle`` / ``release`` 的预留凭据。

    预留发生在任务行写入之后、同一事务内：额度不足时抛 402，调用方回滚即可
    ——不会出现「先跑模型后扣费」（PRD FR-14）。
    """
    capability = _capability_for(kind)
    billing_group_id = task.billing_group_id

    existing = await _active_reservation(db, billing_group_id)
    if existing is not None and existing.task_id != task.id:
        raise conflict(
            "BILLING_GROUP_ACTIVE",
            "该任务组仍持有未结算的额度预留，请先结束上一个任务。",
            {"billing_group_id": billing_group_id, "active_task_id": existing.task_id},
        )

    # chart / export 不消耗研究额度，也不产生预留行（PRD FR-14）。
    if capability is None:
        _set_task_billing(task, BillingState.RELEASED)
        await db.flush()
        return {
            "task_id": task.id,
            "billing_group_id": billing_group_id,
            "operation": None,
            "capability": None,
            "entitlement": "",
            "consumed": "none",
            "amount_units": 0,
            "state": OP_RELEASED,
        }

    try:
        consumed_result = await EntitlementService.consume_pipeline(
            db, actor.user_id, capability
        )
    except EntitlementError as exc:
        raise _entitlement_error(exc, capability) from exc

    consumed = str(consumed_result.get("consumed") or "none")
    ordinal = await _count_reserves(db, billing_group_id) + 1
    operation = f"{RESERVE_PREFIX}{ordinal}"

    row = BillingOperation(
        id=new_id("bill"),
        owner_id=actor.user_id,
        task_id=task.id,
        billing_group_id=billing_group_id,
        operation=operation,
        entitlement=capability,
        amount_units=1,
        state=OP_RESERVED,
        request_fingerprint=task.request_fingerprint,
        note=_note(task.id, consumed=consumed),
    )
    db.add(row)
    _set_task_billing(task, BillingState.RESERVED)
    await db.flush()

    return {
        "task_id": task.id,
        "billing_group_id": billing_group_id,
        "operation": operation,
        "capability": capability,
        "entitlement": capability,
        "consumed": consumed,
        "amount_units": 1,
        "state": OP_RESERVED,
    }


async def settle(
    db: AsyncSession, task: ResearchTask, reservation: Optional[Dict[str, Any]]
) -> None:
    """结算预留（恰好一次）。质量差但诊断有效也结算；这里只看是否成立。"""
    res = dict(reservation or {})
    operation = res.get("operation")
    billing_group_id = res.get("billing_group_id") or task.billing_group_id

    if not operation:
        # 没有持有任何额度（chart/export）：不产生结算行，状态如实记为 released。
        _set_task_billing(task, BillingState.RELEASED)
        await db.flush()
        return

    settled = await _get_operation(db, billing_group_id, SETTLE_OPERATION)
    if settled is not None:
        _set_task_billing(task, BillingState.SETTLED)
        await db.flush()
        return

    now = utcnow()
    row = BillingOperation(
        id=new_id("bill"),
        owner_id=task.owner_id,
        task_id=task.id,
        billing_group_id=billing_group_id,
        operation=SETTLE_OPERATION,
        entitlement=str(res.get("capability") or ""),
        amount_units=int(res.get("amount_units") or 1),
        state=OP_SETTLED,
        request_fingerprint=task.request_fingerprint,
        note=_note(task.id, consumed=str(res.get("consumed") or "none"), detail="settled"),
        settled_at=now,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        # 并发重复结算：唯一约束已生效，账本不再变化。
        _set_task_billing(task, BillingState.SETTLED)
        await db.flush()
        return

    reserve_row = await _get_operation(db, billing_group_id, str(operation))
    if reserve_row is not None and reserve_row.state != OP_SETTLED:
        reserve_row.state = OP_SETTLED
        reserve_row.settled_at = now
    _set_task_billing(task, BillingState.SETTLED)
    await db.flush()


async def release(
    db: AsyncSession, task: ResearchTask, reservation: Optional[Dict[str, Any]]
) -> None:
    """释放预留并退还额度（每个预留恰好一次）；重复调用不改账本。"""
    res = dict(reservation or {})
    operation = res.get("operation")
    billing_group_id = res.get("billing_group_id") or task.billing_group_id

    if not operation:
        _set_task_billing(task, BillingState.RELEASED)
        await db.flush()
        return

    try:
        ordinal = str(operation).split(":", 1)[1]
    except IndexError:  # pragma: no cover - operation 由本模块生成
        ordinal = str(operation)
    release_operation = f"{RELEASE_PREFIX}{ordinal}"

    already = await _get_operation(db, billing_group_id, release_operation)
    if already is not None:
        _set_task_billing(task, BillingState.RELEASED)
        await db.flush()
        return

    now = utcnow()
    row = BillingOperation(
        id=new_id("bill"),
        owner_id=task.owner_id,
        task_id=task.id,
        billing_group_id=billing_group_id,
        operation=release_operation,
        entitlement=str(res.get("capability") or ""),
        amount_units=0,
        state=OP_RELEASED,
        request_fingerprint=task.request_fingerprint,
        note=_note(task.id, consumed=str(res.get("consumed") or "none"), detail="released"),
        settled_at=now,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        # 并发重复释放：唯一约束已生效，不再退还。
        _set_task_billing(task, BillingState.RELEASED)
        await db.flush()
        return

    # 先落释放行再加回额度：即使退还失败，也不会出现「退两次」。
    await EntitlementService.refund_pipeline(
        db, task.owner_id, {"consumed": str(res.get("consumed") or "none")}
    )

    reserve_row = await _get_operation(db, billing_group_id, str(operation))
    if reserve_row is not None and reserve_row.state == OP_RESERVED:
        reserve_row.state = OP_RELEASED
        reserve_row.settled_at = now

    _set_task_billing(task, BillingState.RELEASED)
    await db.flush()


async def reservation_for_task(
    db: AsyncSession, task: ResearchTask
) -> Optional[Dict[str, Any]]:
    """重建任务的预留凭据（供 cancel / 看门狗在没有内存凭据时使用）。"""
    result = await db.execute(
        select(BillingOperation)
        .where(
            BillingOperation.billing_group_id == task.billing_group_id,
            BillingOperation.task_id == task.id,
            BillingOperation.operation.like(f"{RESERVE_PREFIX}%"),
        )
        .order_by(BillingOperation.created_at.desc(), BillingOperation.id.desc())
        .limit(1)
    )
    row = result.scalars().first()
    if row is None:
        return None
    return _reservation_payload(row)


__all__ = [
    "CAPABILITY_BY_KIND",
    "RESERVE_PREFIX",
    "SETTLE_OPERATION",
    "RELEASE_PREFIX",
    "OP_RESERVED",
    "OP_SETTLED",
    "OP_RELEASED",
    "reserve",
    "settle",
    "release",
    "reservation_for_task",
]
