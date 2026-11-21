"""任务登记、快照、恢复、取消与重试（PRD FR-11 / FR-14 / §7.1 / §8.1）。

事务边界在本层：**一次受理 = 校验 + 额度预留 + 任务行 + task.accepted 事件 +
outbox 消息**，全部写在同一个事务里，任何一步失败整体回滚（PRD FR-11）；
只有提交之后，待投递消息才可见，执行器才允许派发。

并发与排队上限集中定义在下方常量，来源为 PRD §9：
每用户同时 1 个研究长任务、系统总并发 3、队列等待 300 秒、任务累计运行 1200 秒。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.orm import Skill
from . import billing_service, budget, outbox, task_repository
from .contracts import (
    Actor,
    BillingState,
    Coverage,
    EventType,
    Finding,
    QualityVerdict,
    ResearchTaskInput,
    ResumeInput,
    TaskAccepted,
    TaskKind,
    TaskSnapshot,
    TaskStatus,
    TERMINAL_STATUSES,
    content_hash,
    text_hash,
    utcnow,
    validate_idempotency_key,
)
from .errors import conflict, invalid, too_many
from .models import Artifact, FindingRow, ResearchTask
from .ownership import require_project, require_task, require_version

# ── 并发与期限（PRD §9，逐条固定，禁止按请求放宽） ──────────
#: 每用户最多同时执行一个研究长任务。
MAX_ACTIVE_TASKS_PER_USER = 1
#: 系统总并发（running）上限。
MAX_SYSTEM_RUNNING_TASKS = 3
#: 排队等待上限；超过则拒绝受理（429，可重试）。
MAX_QUEUE_WAIT_SECONDS = 300
#: 单个任务累计运行期限（与默认租约一致）。
TASK_MAX_RUNTIME_SECONDS = 1200
#: needs_input / recoverable 暂不结算的最长持有时间（FR-14：24 小时）。
MAX_RESUME_HOLD_SECONDS = 24 * 60 * 60

RESUMABLE_STATUSES = frozenset({TaskStatus.NEEDS_INPUT, TaskStatus.RECOVERABLE})
RETRYABLE_STATUSES = frozenset({TaskStatus.FAILED, TaskStatus.PARTIAL})

#: 数据库内部用 ``structural`` 标记「依据章节结构的确定性检查」（不是模型推断），
#: 便于导出文案与内部统计区分；但 PRD FR-06 / §8 只允许
#: ``tool/model/human/none``，因此对外 DTO 统一映射为 ``tool``（确定性工具核查），
#: 既不丢「非模型判断」的语义，也不引入 PRD 未定义的新枚举值。
_EXPOSED_VERIFICATION_METHOD = {"structural": "tool"}


# ── 请求指纹与幂等 ──────────────────────────────────────────


def compute_request_fingerprint(payload: ResearchTaskInput) -> str:
    """规范请求的指纹：相同语义请求得到相同哈希（PRD §8.2）。"""
    canonical = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return content_hash(canonical)


def _require_idempotency_key(key: Optional[str]) -> None:
    if key is None:
        return
    try:
        validate_idempotency_key(key)
    except ValueError as exc:
        raise invalid(
            "INVALID_IDEMPOTENCY_KEY",
            "Idempotency-Key 必须是 8—128 个允许的 ASCII 字符。",
        ) from exc


# ── Skill 选择 ──────────────────────────────────────────────


def resolve_skill_ids(
    *,
    skill_ids: Optional[List[str]],
    legacy_skill_ids: Optional[List[str]] = None,
) -> List[str]:
    """区分「未提供」与「显式空列表」（PRD §8.2）。

    ``None`` 表示请求里没有该字段；``[]`` 表示用户明确要求“不用任何 Skill”
    ——后者绝不能被当成前者而回落到默认 Skill 集。
    """
    if skill_ids is None and legacy_skill_ids is None:
        return []
    if skill_ids is not None and legacy_skill_ids is not None:
        if [str(s) for s in skill_ids] != [str(s) for s in legacy_skill_ids]:
            raise invalid(
                "SKILL_SELECTION_CONFLICT",
                "skill_ids 与旧字段同时提供且不一致。",
                {"skill_ids": list(skill_ids), "legacy_skill_ids": list(legacy_skill_ids)},
            )
    chosen = skill_ids if skill_ids is not None else legacy_skill_ids
    return [str(s) for s in (chosen or [])]


async def _skill_enabled(db: AsyncSession, skill_id: str) -> Optional[bool]:
    """返回 Skill 是否启用；``None`` 表示目录里没有这个 Skill。"""
    result = await db.execute(select(Skill).where(Skill.skill_id == skill_id))
    row = result.scalars().first()
    if row is not None:
        return bool(row.enabled)
    # 兜底：数据库尚未种子化时读预置目录的启用状态（延迟导入，避免导入期 I/O）。
    try:
        from ..services.skills_service import PRESET_SKILLS
    except Exception:  # pragma: no cover - 环境缺少技能目录时按未知处理
        return None
    for item in PRESET_SKILLS:
        if not isinstance(item, dict):
            continue
        # PRESET_SKILLS 的主键字段是 ``id``（见 services/skills_service.py:26
        # 的 PRESET_IDS）；兼容 ``skill_id`` 是为了旧目录格式，不要只认其中一个。
        preset_id = item.get("id") or item.get("skill_id")
        if preset_id == skill_id:
            return bool(item.get("enabled", True))
    return None


async def validate_skill_ids(db: AsyncSession, skill_ids: List[str]) -> List[str]:
    """扣额前校验 Skill：未知或禁用一律 422，绝不先扣费再报错。"""
    if not skill_ids:
        return []
    seen: List[str] = []
    for raw in skill_ids:
        skill_id = str(raw).strip()
        if not skill_id:
            raise invalid("SKILL_UNAVAILABLE", "Skill 标识不能为空。")
        if skill_id in seen:
            raise invalid("INVALID_SKILL_SELECTION", "skill_ids 不能重复。", {"skill_id": skill_id})
        enabled = await _skill_enabled(db, skill_id)
        if enabled is None:
            raise invalid(
                "SKILL_UNAVAILABLE",
                "指定的 Skill 不存在或不可用。",
                {"skill_id": skill_id},
            )
        if not enabled:
            raise invalid(
                "SKILL_UNAVAILABLE",
                "指定的 Skill 当前未启用。",
                {"skill_id": skill_id},
            )
        seen.append(skill_id)
    return seen


# ── 并发与排队闸门 ──────────────────────────────────────────


async def _count_tasks(
    db: AsyncSession, *, owner_id: Optional[int] = None, status: Optional[TaskStatus] = None
) -> int:
    stmt = select(func.count()).select_from(ResearchTask)
    if owner_id is not None:
        stmt = stmt.where(ResearchTask.owner_id == owner_id)
    if status is not None:
        stmt = stmt.where(ResearchTask.status == status.value)
    return int(await db.scalar(stmt) or 0)


async def _enforce_limits(db: AsyncSession, actor: Actor, *, now: datetime) -> None:
    active = await db.scalar(
        select(func.count())
        .select_from(ResearchTask)
        .where(
            ResearchTask.owner_id == actor.user_id,
            ResearchTask.status.not_in([s.value for s in TERMINAL_STATUSES]),
        )
    )
    if int(active or 0) >= MAX_ACTIVE_TASKS_PER_USER:
        raise too_many(
            "你已有进行中的研究任务，请等待其结束后再提交。",
            {
                "limit": MAX_ACTIVE_TASKS_PER_USER,
                "scope": "user",
                "active_tasks": int(active or 0),
            },
        )

    running = await _count_tasks(db, status=TaskStatus.RUNNING)
    if running < MAX_SYSTEM_RUNNING_TASKS:
        return

    # 系统已满：允许排队，但排队超过上限就诚实拒绝（PRD §9 / FR-11）。
    oldest = await db.scalar(
        select(func.min(ResearchTask.created_at)).where(
            ResearchTask.status == TaskStatus.QUEUED.value
        )
    )
    if oldest is not None:
        waited = (now - oldest).total_seconds()
        if waited > MAX_QUEUE_WAIT_SECONDS:
            raise too_many(
                "研究服务当前排队过长，请稍后重试。",
                {
                    "limit": MAX_SYSTEM_RUNNING_TASKS,
                    "scope": "system",
                    "queue_wait_seconds": int(waited),
                    "max_queue_wait_seconds": MAX_QUEUE_WAIT_SECONDS,
                },
            )


# ── 快照 ────────────────────────────────────────────────────


async def _artifact_ids(db: AsyncSession, task: ResearchTask) -> List[str]:
    result = await db.execute(
        select(Artifact.id)
        .where(Artifact.task_id == task.id, Artifact.owner_id == task.owner_id)
        .order_by(Artifact.created_at, Artifact.id)
    )
    return [str(value) for value in result.scalars().all()]


def _result_payload(task: ResearchTask) -> Dict[str, Any]:
    value = task.result_json
    return dict(value) if isinstance(value, dict) else {}


def _can_resume(task: ResearchTask, *, now: datetime) -> bool:
    try:
        status = TaskStatus(task.status)
    except ValueError:  # pragma: no cover
        return False
    if status not in RESUMABLE_STATUSES:
        return False
    updated = task.updated_at or task.created_at
    if updated is None:  # pragma: no cover
        return False
    return (now - updated) <= timedelta(seconds=MAX_RESUME_HOLD_SECONDS)


def _can_retry(task: ResearchTask) -> bool:
    try:
        return TaskStatus(task.status) in RETRYABLE_STATUSES
    except ValueError:  # pragma: no cover
        return False


async def _snapshot(db: AsyncSession, task: ResearchTask) -> TaskSnapshot:
    now = utcnow()
    result = _result_payload(task)
    artifact_ids = result.get("artifact_ids")
    if not isinstance(artifact_ids, list) or not artifact_ids:
        artifact_ids = await _artifact_ids(db, task)

    coverage: Optional[Coverage] = None
    raw_coverage = task.coverage_json or result.get("coverage")
    if raw_coverage:
        try:
            coverage = Coverage.model_validate(raw_coverage)
        except ValidationError:  # pragma: no cover - 行数据应已校验
            coverage = None

    quality_verdict: Optional[QualityVerdict] = None
    raw_verdict = task.quality_verdict or result.get("quality_verdict")
    if raw_verdict:
        try:
            quality_verdict = QualityVerdict(str(raw_verdict))
        except ValueError:  # pragma: no cover
            quality_verdict = None

    billing_state: Optional[BillingState] = None
    if task.billing_state:
        try:
            billing_state = BillingState(str(task.billing_state))
        except ValueError:  # pragma: no cover
            billing_state = None

    return TaskSnapshot(
        id=task.id,
        owner_id=task.owner_id,
        project_id=task.project_id,
        kind=TaskKind(task.kind),
        status=TaskStatus(task.status),
        objective=task.objective or "",
        state_revision=int(task.state_revision or 1),
        billing_group_id=task.billing_group_id,
        billing_state=billing_state,
        attempt_no=int(task.attempt_no or 0),
        snapshot_summary=dict(task.snapshot_summary or {}),
        coverage=coverage,
        quality_verdict=quality_verdict,
        artifact_ids=[str(value) for value in artifact_ids],
        warnings=[str(w) for w in result.get("warnings") or []],
        unresolved_items=[str(u) for u in result.get("unresolved_items") or []],
        retry_of=task.retry_of,
        can_resume=_can_resume(task, now=now),
        can_retry=_can_retry(task),
        error=dict(task.error_json) if isinstance(task.error_json, dict) else None,
        created_at=task.created_at,
        updated_at=task.updated_at or task.created_at,
        ended_at=task.ended_at,
    )


def _accepted(task: ResearchTask, billing_state: BillingState) -> TaskAccepted:
    return TaskAccepted(
        task_id=task.id,
        status=TaskStatus(task.status),
        state_revision=int(task.state_revision or 1),
        billing_state=billing_state,
        snapshot_summary=dict(task.snapshot_summary or {}),
    )


# ── 受理 ────────────────────────────────────────────────────


def _coerce_payload(payload: Any) -> ResearchTaskInput:
    if isinstance(payload, ResearchTaskInput):
        return payload
    if isinstance(payload, dict):
        try:
            return ResearchTaskInput.model_validate(payload)
        except ValidationError as exc:
            raise invalid(
                "INVALID_TASK_INPUT",
                "任务请求参数不合法。",
                {"errors": [
                    {"loc": [str(p) for p in e.get("loc", ())], "msg": str(e.get("msg", ""))}
                    for e in exc.errors()[:20]
                ]},
            ) from exc
    raise invalid("INVALID_TASK_INPUT", "任务请求参数不合法。")


async def _require_owned_inputs(
    db: AsyncSession, actor: Actor, data: ResearchTaskInput
) -> None:
    """受理前校验输入归属（FR-03 / AT-006）。

    任务引用的项目、正文版本、提纲版本、审阅意见版本都必须属于当前用户；
    他人资源统一 404，且必须在**扣额之前**拒绝（PRD FR-12「未知 Skill 扣额前
    拒绝」的同一条原则）。项目与文档版本不属于同一项目时按 422 拒绝。
    """
    project = await require_project(db, actor, data.project_id)
    version = await require_version(db, actor, data.input.document_version_id)
    document = await _document_of_version(db, version)
    if document.project_id != project.id:
        raise invalid(
            "PROJECT_DOCUMENT_MISMATCH",
            "任务正文版本不属于该项目。",
            {"project_id": project.id, "document_version_id": version.id},
        )
    for ref in (
        data.input.outline_document_version_id,
        data.input.reviewer_comments_document_version_id,
    ):
        if ref:
            await require_version(db, actor, ref)
    # FR-03 / T16：修改任务引用的诊断项必须属于本人、同一项目与同一版本。
    # 他人或伪造的 id 与不存在等价（统一 422），既避免泄露存在性，也保证扣额前拒绝。
    selected = [item for item in (data.scope.finding_ids or []) if isinstance(item, str)]
    if selected:
        result = await db.execute(
            select(FindingRow.id, FindingRow.version_id).where(
                FindingRow.owner_id == actor.user_id,
                FindingRow.id.in_(selected),
            )
        )
        found = {row.id: row.version_id for row in result.all()}
        missing = [item for item in selected if item not in found]
        if missing:
            raise invalid(
                "FINDING_NOT_FOUND",
                "选定的诊断项不存在或不属于当前用户。",
                {"missing": missing[:50]},
            )
        mismatched = [
            item for item in selected if found.get(item) != version.id
        ]
        if mismatched:
            raise invalid(
                "PROJECT_DOCUMENT_MISMATCH",
                "选定的诊断项与该任务正文版本不一致。",
                {
                    "project_id": project.id,
                    "document_version_id": version.id,
                    "finding_ids": mismatched[:50],
                },
            )


async def _document_of_version(db: AsyncSession, version: Any) -> Any:
    """取版本所属文档（仅用于项目归属校验，不额外暴露给调用方）。"""
    from .models import Document

    result = await db.execute(select(Document).where(Document.id == version.document_id))
    document = result.scalar_one_or_none()
    if document is None:
        raise invalid(
            "PROJECT_DOCUMENT_MISMATCH",
            "任务引用的文档不存在。",
            {"document_version_id": getattr(version, "id", None)},
        )
    return document


async def create_task(
    db: AsyncSession,
    actor: Actor,
    payload: ResearchTaskInput,
    *,
    idempotency_key: Optional[str] = None,
) -> TaskAccepted:
    """受理任务：校验 → 预留 → 任务行 + 事件 + outbox，单事务提交。"""
    _require_idempotency_key(idempotency_key)
    data = _coerce_payload(payload)
    # FR-03：引用的项目/版本必须属于当前用户，且在任何扣额之前拒绝（404）。
    await _require_owned_inputs(db, actor, data)
    fingerprint = compute_request_fingerprint(data)

    if idempotency_key:
        existing = await task_repository.find_by_idempotency(
            db, actor.user_id, idempotency_key
        )
        if existing is not None:
            return _replay(existing, fingerprint)

    now = utcnow()
    try:
        skills = await validate_skill_ids(db, list(data.skill_ids))
        await expire_stale_queued_tasks(db, now=now, commit=False)
        await _enforce_limits(db, actor, now=now)

        billing_group_id = f"bg_{content_hash(f'{actor.user_id}:{fingerprint}:{now.isoformat()}')[:32]}"
        task = await task_repository.create_task(
            db,
            actor,
            data,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            billing_group_id=billing_group_id,
        )
        # FR-10 / §9：受理时冻结预算上限（缺省取当期配置），随 constraints 落盘，
        # 事后核对不受配置变更影响；费用上限未知时为 null，不写 0。
        accepted = budget.default_accepted_budget(data.kind)
        task.constraints_json = {
            **dict(task.constraints_json or {}),
            budget.ACCEPTED_BUDGET_KEY: budget.budget_payload(accepted),
        }
        task.snapshot_summary = {
            **dict(task.snapshot_summary or {}),
            "skill_ids": skills,
            "billing_capability": billing_service.CAPABILITY_BY_KIND.get(data.kind),
            "billing_group_id": billing_group_id,
            "queue_deadline_seconds": MAX_QUEUE_WAIT_SECONDS,
            "task_runtime_limit_seconds": TASK_MAX_RUNTIME_SECONDS,
            "request_fingerprint": fingerprint,
            # 兼容 R1 读取方：快照侧保留 max_calls 旧键。
            budget.ACCEPTED_BUDGET_KEY: budget.budget_payload(
                accepted, legacy_aliases=True
            ),
        }

        reservation = await billing_service.reserve(db, actor, task, data.kind)
        task.billing_state = (
            BillingState.RESERVED.value
            if reservation.get("operation")
            else BillingState.RELEASED.value
        )
        await db.flush()

        await task_repository.append_event(
            db,
            task,
            EventType.TASK_ACCEPTED.value,
            payload={
                "kind": data.kind.value,
                "objective_hash": text_hash(data.objective),
                "skill_ids": skills,
                "billing_group_id": billing_group_id,
                "billing_state": task.billing_state,
            },
        )
        outbox.enqueue(
            db,
            outbox.TOPIC_TASK_ACCEPTED,
            {
                "task_id": task.id,
                "owner_id": actor.user_id,
                "kind": data.kind.value,
                "billing_group_id": billing_group_id,
                "attempt_no": int(task.attempt_no or 0),
            },
            task_id=task.id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if idempotency_key:
            existing = await task_repository.find_by_idempotency(
                db, actor.user_id, idempotency_key
            )
            if existing is not None:
                return _replay(existing, fingerprint)
        raise conflict(
            "TASK_CONFLICT",
            "任务登记冲突，请重试。",
            {"reason": "concurrent_write"},
        ) from exc
    except Exception:
        await db.rollback()
        raise

    return _accepted(task, BillingState(task.billing_state))


def _replay(existing: ResearchTask, fingerprint: str) -> TaskAccepted:
    """同一 Idempotency-Key 的重放：等价请求返回原任务，不同请求 409。

    PRD §8.2：「相同键和等价规范请求返回原结果，不同请求返回 409
    ``IDEMPOTENCY_CONFLICT``」。422 只用于键本身缺失/格式非法。
    """
    if existing.request_fingerprint and existing.request_fingerprint != fingerprint:
        raise conflict(
            "IDEMPOTENCY_CONFLICT",
            "该 Idempotency-Key 已用于不同的请求。",
            {"task_id": existing.id},
        )
    state = BillingState(existing.billing_state) if existing.billing_state else BillingState.RESERVED
    return _accepted(existing, state)


# ── 读取 / 恢复 / 取消 / 重试 ──────────────────────────────


async def get_task_snapshot(db: AsyncSession, actor: Actor, task_id: str) -> TaskSnapshot:
    task = await require_task(db, actor, task_id)
    return await _snapshot(db, task)


async def resume_task(
    db: AsyncSession,
    actor: Actor,
    task_id: str,
    payload: ResumeInput,
    *,
    idempotency_key: Optional[str] = None,
) -> TaskSnapshot:
    """补充输入后重新排队；必须匹配 state_revision（否则 409 STATE_CONFLICT）。

    ``idempotency_key`` 由路由层透传（PRD §8.1 要求 /resume 带键）；真正的并发
    保护是 ``expected_state_revision``，同一键重放会因版本已变而 409，不会重复受理。
    """
    _require_idempotency_key(idempotency_key)
    task = await require_task(db, actor, task_id)
    data = payload if isinstance(payload, ResumeInput) else ResumeInput.model_validate(payload)

    if int(task.state_revision or 1) != int(data.expected_state_revision):
        raise conflict(
            "STATE_CONFLICT",
            "任务已被其他操作更新，请刷新后重试。",
            {
                "expected_state_revision": data.expected_state_revision,
                "state_revision": int(task.state_revision or 1),
            },
        )
    if TaskStatus(task.status) not in RESUMABLE_STATUSES:
        raise conflict(
            "STATE_CONFLICT",
            "当前任务状态不允许补充输入。",
            {"status": task.status},
        )

    summary = {
        "resumed_at": utcnow().isoformat(),
        "answers_count": len(data.answers),
        "supplemental_source_ids_count": len(data.supplemental_source_ids),
    }
    await task_repository.transition(
        db,
        task,
        TaskStatus.QUEUED,
        snapshot_summary={"last_resume": summary},
    )
    await task_repository.append_event(
        db,
        task,
        EventType.TASK_PROGRESS.value,
        payload={"phase": "resumed", **summary},
    )
    outbox.enqueue(
        db,
        outbox.TOPIC_TASK_DISPATCH,
        {"task_id": task.id, "owner_id": actor.user_id, "reason": "resumed"},
        task_id=task.id,
    )
    await db.commit()
    return await _snapshot(db, task)


async def cancel_task(db: AsyncSession, actor: Actor, task_id: str) -> TaskSnapshot:
    """显式取消（幂等）：非终态 → 释放额度并转 cancelled。"""
    task = await require_task(db, actor, task_id)
    status = TaskStatus(task.status)

    if status is TaskStatus.CANCELLED:
        return await _snapshot(db, task)
    if status in TERMINAL_STATUSES:
        raise conflict(
            "STATE_CONFLICT",
            "任务已结束，不能取消。",
            {"status": status.value},
        )

    try:
        reservation = await billing_service.reservation_for_task(db, task)
        # 取消也要留预算口径：用已落盘事件重算，超限只记录、不改取消语义。
        usage = budget.usage_from_events(
            await task_repository.list_events(db, task.id)
        )
        evaluation = budget.evaluate_budget(budget.accepted_budget(task), usage)
        await task_repository.transition(
            db,
            task,
            TaskStatus.CANCELLED,
            snapshot_summary={
                "cancelled_at": utcnow().isoformat(),
                "budget_evaluation": evaluation,
            },
        )
        # 释放失败（如账本行缺失）不应阻断取消：取消优先，额度按无持有处理。
        await billing_service.release(db, task, reservation)
        await task_repository.append_event(
            db,
            task,
            EventType.TASK_CANCELLED.value,
            payload={"cancelled_by": "user"},
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return await _snapshot(db, task)


def _payload_from_row(task: ResearchTask) -> ResearchTaskInput:
    summary = dict(task.snapshot_summary or {})
    mode = summary.get("mode_requested")
    skill_ids = summary.get("skill_ids")
    # accepted_budget 是平台侧快照，不属于用户可提交的 TaskConstraints
    # （该模型 extra="forbid"），重试重建载荷时必须剔除，否则校验失败。
    constraints = dict(task.constraints_json or {})
    constraints.pop(budget.ACCEPTED_BUDGET_KEY, None)
    raw = {
        "project_id": task.project_id,
        "kind": task.kind,
        "objective": task.objective,
        "input": dict(task.input_json or {}),
        "scope": dict(task.scope_json or {}),
        "constraints": constraints,
    }
    if mode in {"flash", "pro"}:
        raw["mode"] = mode
    if isinstance(skill_ids, list):
        raw["skill_ids"] = [str(s) for s in skill_ids]
    return ResearchTaskInput.model_validate(raw)


async def retry_task(
    db: AsyncSession,
    actor: Actor,
    task_id: str,
    *,
    idempotency_key: Optional[str] = None,
) -> TaskAccepted:
    """手动重试：创建新任务，沿用 billing_group_id，不原地回到 running。

    同一 Idempotency-Key 的重放返回首次创建的重试任务，不会重复扣减额度。
    """
    if idempotency_key is not None:
        _require_idempotency_key(idempotency_key)

    previous = await require_task(db, actor, task_id)
    status = TaskStatus(previous.status)
    if status not in RETRYABLE_STATUSES:
        raise conflict(
            "STATE_CONFLICT",
            "只有失败或部分完成的任务可以重试。",
            {"status": status.value},
        )

    data = _payload_from_row(previous)
    fingerprint = compute_request_fingerprint(data)
    now = utcnow()

    if idempotency_key:
        existing = await task_repository.find_by_idempotency(
            db, actor.user_id, idempotency_key
        )
        if existing is not None:
            return _replay(existing, fingerprint)

    try:
        await validate_skill_ids(db, list(data.skill_ids))
        await _enforce_limits(db, actor, now=now)

        task = await task_repository.create_task(
            db,
            actor,
            data,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            billing_group_id=previous.billing_group_id,
        )
        task.retry_of = previous.id
        # 重试沿用原任务的受理预算（不因重试扩额），避免同一目标被重复放大额度。
        accepted = budget.accepted_budget(previous)
        task.constraints_json = {
            **dict(task.constraints_json or {}),
            budget.ACCEPTED_BUDGET_KEY: budget.budget_payload(accepted),
        }
        task.snapshot_summary = {
            **dict(task.snapshot_summary or {}),
            "retry_of": previous.id,
            "billing_group_id": previous.billing_group_id,
            "billing_capability": billing_service.CAPABILITY_BY_KIND.get(data.kind),
            "request_fingerprint": fingerprint,
            budget.ACCEPTED_BUDGET_KEY: budget.budget_payload(
                accepted, legacy_aliases=True
            ),
        }

        # 重新校验当期权益：24h 窗口外的重试必须被明确拒绝（FR-14）。
        reservation = await billing_service.reserve(db, actor, task, data.kind)
        task.billing_state = (
            BillingState.RESERVED.value
            if reservation.get("operation")
            else BillingState.RELEASED.value
        )
        await db.flush()

        await task_repository.append_event(
            db,
            task,
            EventType.TASK_ACCEPTED.value,
            payload={
                "kind": data.kind.value,
                "retry_of": previous.id,
                "billing_group_id": previous.billing_group_id,
                "billing_state": task.billing_state,
            },
        )
        outbox.enqueue(
            db,
            outbox.TOPIC_TASK_ACCEPTED,
            {
                "task_id": task.id,
                "owner_id": actor.user_id,
                "kind": data.kind.value,
                "billing_group_id": previous.billing_group_id,
                "retry_of": previous.id,
                "attempt_no": int(task.attempt_no or 0),
            },
            task_id=task.id,
        )
        await db.commit()
    except IntegrityError:
        # 同键并发双击：另一事务已落地同键任务，回读后按重放返回（不重复扣额度）。
        await db.rollback()
        if idempotency_key:
            existing = await task_repository.find_by_idempotency(
                db, actor.user_id, idempotency_key
            )
            if existing is not None:
                return _replay(existing, fingerprint)
        raise conflict(
            "TASK_CONFLICT",
            "任务创建冲突，请重新获取任务状态。",
            {"task_id": previous.id},
        )
    except Exception:
        await db.rollback()
        raise

    return _accepted(task, BillingState(task.billing_state))


async def list_findings(db: AsyncSession, actor: Actor, task_id: str) -> List[Finding]:
    """按任务列出诊断项（先校验任务归属，避免枚举他人任务）。"""
    task = await require_task(db, actor, task_id)
    result = await db.execute(
        select(FindingRow)
        .where(FindingRow.task_id == task.id, FindingRow.owner_id == actor.user_id)
        .order_by(FindingRow.created_at, FindingRow.id)
    )
    findings: List[Finding] = []
    for row in result.scalars().all():
        findings.append(
            Finding(
                id=row.id,
                task_id=row.task_id,
                version_id=row.version_id,
                scope=row.scope,
                category=row.category,
                severity=row.severity,
                problem=row.problem,
                reason=row.reason or "",
                recommendation=row.recommendation or "",
                evidence_refs=list(row.evidence_refs or []),
                locator=row.locator,
                quote=row.quote,
                checked_sections=list(row.checked_sections or []),
                required_user_action=row.required_user_action,
                verification_method=_EXPOSED_VERIFICATION_METHOD.get(
                    str(row.verification_method), row.verification_method
                ),
            )
        )
    return findings


async def enqueue_task(db: AsyncSession, actor: Actor, task_id: str) -> None:
    """把任务重新挂到派发队列（运维/恢复用，不改变任务状态）。"""
    task = await require_task(db, actor, task_id)
    outbox.enqueue(
        db,
        outbox.TOPIC_TASK_DISPATCH,
        {
            "task_id": task.id,
            "owner_id": actor.user_id,
            "status": task.status,
            "reason": "manual_enqueue",
        },
        task_id=task.id,
    )
    await db.commit()


# ── 排队超时清理（FR-11：排队超过 300 秒则结束并释放） ──────


async def expire_stale_queued_tasks(
    db: AsyncSession,
    *,
    now: Optional[datetime] = None,
    limit: int = 50,
    commit: bool = True,
) -> int:
    """结束排队过久的任务并释放额度；返回处理数量。

    系统级清理（不限单个用户）：任务卡在 queued 超过 ``MAX_QUEUE_WAIT_SECONDS``
    说明执行器已不可用，此时诚实失败比无限排队更有用，且必须归还额度。
    """
    moment = now or utcnow()
    cutoff = moment - timedelta(seconds=MAX_QUEUE_WAIT_SECONDS)
    result = await db.execute(
        select(ResearchTask)
        .where(
            ResearchTask.status == TaskStatus.QUEUED.value,
            ResearchTask.created_at < cutoff,
        )
        .order_by(ResearchTask.created_at)
        .limit(max(1, int(limit)))
    )
    stale = list(result.scalars().all())
    if not stale:
        return 0

    expired = 0
    for task in stale:
        try:
            # 用 savepoint 隔离单条失败：调用方（如受理流程）可能正处在事务里，
            # 这里绝不能 rollback 掉它尚未提交的工作。
            async with db.begin_nested():
                reservation = await billing_service.reservation_for_task(db, task)
                await task_repository.transition(
                    db,
                    task,
                    TaskStatus.FAILED,
                    error={
                        "code": "QUEUE_TIMEOUT",
                        "message": "排队超时，任务未能开始执行。",
                        "retryable": True,
                    },
                    snapshot_summary={"queue_timeout_seconds": MAX_QUEUE_WAIT_SECONDS},
                )
                await billing_service.release(db, task, reservation)
                await task_repository.append_event(
                    db,
                    task,
                    EventType.TASK_FAILED.value,
                    payload={"code": "QUEUE_TIMEOUT", "retryable": True},
                )
                await db.flush()
        except Exception:  # pragma: no cover - 单条失败不阻断其它任务
            # savepoint 已回滚；重新同步内存对象，避免脏属性在后续 commit 时被写回。
            try:
                await db.refresh(task)
            except Exception:
                db.expunge(task)
            continue
        expired += 1

    if expired and commit:
        await db.commit()
    return expired


__all__ = [
    "MAX_ACTIVE_TASKS_PER_USER",
    "MAX_SYSTEM_RUNNING_TASKS",
    "MAX_QUEUE_WAIT_SECONDS",
    "TASK_MAX_RUNTIME_SECONDS",
    "MAX_RESUME_HOLD_SECONDS",
    "RESUMABLE_STATUSES",
    "RETRYABLE_STATUSES",
    "compute_request_fingerprint",
    "resolve_skill_ids",
    "validate_skill_ids",
    "create_task",
    "get_task_snapshot",
    "resume_task",
    "cancel_task",
    "retry_task",
    "list_findings",
    "enqueue_task",
    "expire_stale_queued_tasks",
]
