"""产品指标聚合（T19 / FR-14、FR-16；契约见 R1_INTERFACE_SPEC §2.5）。

本模块**只读聚合**：不写库、不建表、不调用模型/网络，只从既有研究域表聚合数字，
供运营与验收审计使用。绝不返回论文正文、引文原文、联系方式或任何逐条文本。

统计口径（审计基线，改动需同步更新本节与 R1 验证报告）
------------------------------------------------------
1. **任务口径**：``task_metrics`` 以 ``research_tasks`` 行（一个 task_id 一行）为单位，
   同一任务的重试/重复终态事件**不会**把任务数放大。``funnel_metrics`` 中与任务
   关联的计数（发现/提案/成果/导出）先按 ``task_id`` 归属到任务，再套用同一任务
   过滤条件，避免断线重放或重复回调造成重复计数。
2. **成功率**：``success_rate = succeeded / (succeeded + partial + failed)``。
   分母**显式排除** ``cancelled``（用户主动取消）与仍在途状态（``queued``、
   ``running``、``recoverable``、``needs_input``）；平台失败与 partial **必须**
   留在分母内（PRD §10「平台错误/partial 不从分母剔除」）。分母为 0 时返回
   ``None``，不返回 0 或 NaN。
3. **重放去重**：``replay_events_deduped`` 统计本时间窗内、被任务级去重折叠掉的
   终态事件条数，即每个任务除第一条终态事件外多余的事件行数之和
   （``sum(max(0, 该任务终态事件数 - 1))``）。它说明“按事件条数统计会虚增多少”，
   而不是把事件条数当任务数。
4. **重试**：``retried_tasks`` = 本窗口内 ``retry_of`` 非空**或** ``attempt_no > 1``
   的任务数（按 task_id 去重，重试产生的新任务各计一次）。
5. **耗时**：``p50/p95_duration_seconds`` 只在**已结束的终态任务**（有 ``ended_at``
   且状态属于 succeeded/partial/failed/cancelled）上计算，耗时 = ``ended_at -
   created_at``（秒）；用户取消的耗时同样是真实墙钟时间，保留在样本中。分位数用
   纯 Python 线性插值（与 numpy 默认线性分位一致），不引入第三方依赖。样本为空
   返回 ``None``。
6. **模型消耗**：``avg_model_calls`` / ``avg_tokens`` 来自
   ``research_artifacts.validation_json`` 中已留痕的 ``calls`` / ``output_tokens``
   （兼容 ``tokens`` 键），按 task_id 汇总后取平均；**仅对该字段有留痕的任务**
   计算均值，未测量不等于 0（PRD §10「无法准确换算费用时显示未知而非 0」），
   无任何留痕时返回 ``None``。
7. **时间窗**：所有实体按其自身 ``created_at``（UTC naive）做 ``>= since`` 过滤；
   ``since`` 为空表示全量。任务关联实体（事件/发现/提案/成果）采用**任务队列口径**：
   先按任务的 ``created_at`` 选定任务，再统计这些任务下的实体，保证同一队列口径
   内分子分母一致。项目与文档按各自 ``created_at`` 过滤。
8. **空分母**：``success_rate``、``first_finding_rate``、``apply_rate`` 及两个
   耗时/消耗均值在样本为 0 时一律返回 ``None``；计数类字段返回 0。
9. **所有者隔离**：``owner_id`` 非空时只统计该用户的数据；任务关联表通过
   ``research_tasks.owner_id`` 判定归属，不信任关联表里可被伪造的冗余列。
10. **不泄露正文**：查询只选择计数列、状态列、时间列与数值型消耗字段；返回值
    只含聚合数，不含 objective/problem/quote/body 等文本列。

返回字段严格按契约 §2.5，不额外添加字段，避免下游把未知字段当稳定接口。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import EventType, TaskStatus
from .models import (
    Artifact,
    Document,
    FindingRow,
    Project,
    ResearchTask,
    RevisionProposalRow,
    TaskEvent,
)

#: 计入“终态事件”的事件类型；重复的同类事件会被任务级去重折叠。
_TERMINAL_EVENT_TYPES: Tuple[str, ...] = (
    EventType.TASK_COMPLETED.value,
    EventType.TASK_PARTIAL.value,
    EventType.TASK_FAILED.value,
    EventType.TASK_CANCELLED.value,
)

#: 已结束且可计入耗时样本的状态。
_DURATION_STATUSES: Tuple[str, ...] = (
    TaskStatus.SUCCEEDED.value,
    TaskStatus.PARTIAL.value,
    TaskStatus.FAILED.value,
    TaskStatus.CANCELLED.value,
)

#: 提案“已采纳”的状态值（revision_service.apply 写入）。
_APPLIED_PROPOSAL_STATUS = "applied"

#: 导出成果的 artifact kind（export_service 写入）。
_EXPORT_ARTIFACT_KIND = "export"


def _naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    """把 ``since`` 统一成 UTC naive；带时区的输入先换算到 UTC。"""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    """安全除法：分母为 0 返回 ``None``（不返回 0/NaN，避免“未测量”被当成 0）。"""
    if denominator <= 0:
        return None
    return numerator / denominator


def _percentile(values: Sequence[float], fraction: float) -> Optional[float]:
    """纯 Python 线性插值分位数（0 <= fraction <= 1）；空序列返回 ``None``。"""
    if not values:
        return None
    ordered = sorted(float(item) for item in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * fraction
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _non_negative_int(value: Any) -> Optional[int]:
    """把留痕字段解析成非负整数；缺失/非法一律视为“未留痕”。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    return None


def _task_filters(
    owner_id: Optional[int], since: Optional[datetime]
) -> List[Any]:
    """任务队列过滤条件：owner 与任务创建时间窗。"""
    filters: List[Any] = []
    if owner_id is not None:
        filters.append(ResearchTask.owner_id == owner_id)
    if since is not None:
        filters.append(ResearchTask.created_at >= since)
    return filters


def _usage_by_task(
    rows: Sequence[Any],
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """按 task_id 汇总成果里留痕的 calls / output_tokens。"""
    calls: Dict[str, int] = {}
    tokens: Dict[str, int] = {}
    for task_id, validation in rows:
        if not isinstance(validation, dict):
            continue
        call_value = _non_negative_int(validation.get("calls"))
        token_value = _non_negative_int(
            validation.get("output_tokens", validation.get("tokens"))
        )
        if call_value is not None:
            calls[task_id] = calls.get(task_id, 0) + call_value
        if token_value is not None:
            tokens[task_id] = tokens.get(task_id, 0) + token_value
    return calls, tokens


async def task_metrics(
    db: AsyncSession,
    *,
    owner_id: Optional[int] = None,
    since: Optional[datetime] = None,
) -> Dict[str, Any]:
    """任务结果指标（契约 §2.5）。

    返回字段：``total``、``succeeded``、``partial``、``failed``、``cancelled``、
    ``needs_input``、``success_rate``、``retried_tasks``、``replay_events_deduped``、
    ``p50_duration_seconds``、``p95_duration_seconds``、``avg_model_calls``、
    ``avg_tokens``。

    口径见模块文档：成功率分母为 succeeded+partial+failed（排除 cancelled 与在途）；
    事件按 task_id 去重；空分母返回 ``None``；时间窗按任务 ``created_at`` 过滤。
    ``owner_id`` 为空表示全平台聚合。
    """
    window = _naive_utc(since)
    filters = _task_filters(owner_id, window)

    status_rows = await db.execute(
        select(ResearchTask.status, func.count())
        .where(*filters)
        .group_by(ResearchTask.status)
    )
    status_counts: Dict[str, int] = {
        str(status): int(count) for status, count in status_rows.all()
    }
    total = sum(status_counts.values())
    succeeded = status_counts.get(TaskStatus.SUCCEEDED.value, 0)
    partial = status_counts.get(TaskStatus.PARTIAL.value, 0)
    failed = status_counts.get(TaskStatus.FAILED.value, 0)
    cancelled = status_counts.get(TaskStatus.CANCELLED.value, 0)
    needs_input = status_counts.get(TaskStatus.NEEDS_INPUT.value, 0)

    success_rate = _ratio(
        succeeded, succeeded + partial + failed
    )

    retried_tasks = int(
        await db.scalar(
            select(func.count())
            .select_from(ResearchTask)
            .where(
                *filters,
                or_(
                    ResearchTask.retry_of.is_not(None),
                    ResearchTask.attempt_no > 1,
                ),
            )
        )
        or 0
    )

    # 终态事件按任务分组：每任务第一条是状态本身，多余的是重放/重复终态事件。
    event_rows = await db.execute(
        select(TaskEvent.task_id, func.count())
        .join(ResearchTask, ResearchTask.id == TaskEvent.task_id)
        .where(*filters, TaskEvent.type.in_(_TERMINAL_EVENT_TYPES))
        .group_by(TaskEvent.task_id)
    )
    replay_events_deduped = sum(
        max(0, int(count) - 1) for _, count in event_rows.all()
    )

    duration_rows = await db.execute(
        select(ResearchTask.created_at, ResearchTask.ended_at)
        .where(
            *filters,
            ResearchTask.ended_at.is_not(None),
            ResearchTask.status.in_(_DURATION_STATUSES),
        )
    )
    durations: List[float] = []
    for created_at, ended_at in duration_rows.all():
        if created_at is None or ended_at is None:
            continue
        seconds = (ended_at - created_at).total_seconds()
        if seconds >= 0:
            durations.append(seconds)

    usage_rows = await db.execute(
        select(Artifact.task_id, Artifact.validation_json)
        .join(ResearchTask, ResearchTask.id == Artifact.task_id)
        .where(*filters)
    )
    calls_by_task, tokens_by_task = _usage_by_task(usage_rows.all())

    avg_model_calls: Optional[float] = None
    if calls_by_task:
        avg_model_calls = sum(calls_by_task.values()) / len(calls_by_task)

    avg_tokens: Optional[float] = None
    if tokens_by_task:
        avg_tokens = sum(tokens_by_task.values()) / len(tokens_by_task)

    return {
        "total": total,
        "succeeded": succeeded,
        "partial": partial,
        "failed": failed,
        "cancelled": cancelled,
        "needs_input": needs_input,
        "success_rate": success_rate,
        "retried_tasks": retried_tasks,
        "replay_events_deduped": replay_events_deduped,
        "p50_duration_seconds": _percentile(durations, 0.5),
        "p95_duration_seconds": _percentile(durations, 0.95),
        "avg_model_calls": avg_model_calls,
        "avg_tokens": avg_tokens,
    }


async def funnel_metrics(
    db: AsyncSession,
    *,
    owner_id: Optional[int] = None,
    since: Optional[datetime] = None,
) -> Dict[str, Any]:
    """产品漏斗指标（契约 §2.5）。

    返回字段：``projects``、``documents``、``tasks_by_kind``、
    ``tasks_with_findings``、``findings_total``、``proposals_created``、
    ``proposals_applied``、``artifacts_created``、``exports``、
    ``first_finding_rate``、``apply_rate``。

    口径见模块文档：任务关联实体按任务队列归属；``first_finding_rate`` 分母为
    窗口内任务总数；``apply_rate`` 分母为提案创建数；空分母一律返回 ``None``。
    ``exports`` 只统计 kind 为 ``export`` 的成果，不把导出任务数当导出次数。
    """
    window = _naive_utc(since)
    task_filters = _task_filters(owner_id, window)

    project_filters: List[Any] = []
    if owner_id is not None:
        project_filters.append(Project.owner_id == owner_id)
    if window is not None:
        project_filters.append(Project.created_at >= window)

    document_filters: List[Any] = []
    if owner_id is not None:
        document_filters.append(Document.owner_id == owner_id)
    if window is not None:
        document_filters.append(Document.created_at >= window)

    projects = int(
        await db.scalar(
            select(func.count()).select_from(Project).where(*project_filters)
        )
        or 0
    )
    documents = int(
        await db.scalar(
            select(func.count()).select_from(Document).where(*document_filters)
        )
        or 0
    )

    kind_rows = await db.execute(
        select(ResearchTask.kind, func.count())
        .where(*task_filters)
        .group_by(ResearchTask.kind)
    )
    tasks_by_kind: Dict[str, int] = {
        str(kind): int(count) for kind, count in kind_rows.all()
    }
    total_tasks = sum(tasks_by_kind.values())

    finding_rows = await db.execute(
        select(FindingRow.task_id, func.count())
        .join(ResearchTask, ResearchTask.id == FindingRow.task_id)
        .where(*task_filters)
        .group_by(FindingRow.task_id)
    )
    findings_by_task = {
        str(task_id): int(count) for task_id, count in finding_rows.all()
    }
    tasks_with_findings = len(findings_by_task)
    findings_total = sum(findings_by_task.values())

    proposals_created = int(
        await db.scalar(
            select(func.count())
            .select_from(RevisionProposalRow)
            .join(ResearchTask, ResearchTask.id == RevisionProposalRow.task_id)
            .where(*task_filters)
        )
        or 0
    )
    proposals_applied = int(
        await db.scalar(
            select(func.count())
            .select_from(RevisionProposalRow)
            .join(ResearchTask, ResearchTask.id == RevisionProposalRow.task_id)
            .where(
                *task_filters,
                RevisionProposalRow.status == _APPLIED_PROPOSAL_STATUS,
            )
        )
        or 0
    )

    artifacts_created = int(
        await db.scalar(
            select(func.count())
            .select_from(Artifact)
            .join(ResearchTask, ResearchTask.id == Artifact.task_id)
            .where(*task_filters)
        )
        or 0
    )
    exports = int(
        await db.scalar(
            select(func.count())
            .select_from(Artifact)
            .join(ResearchTask, ResearchTask.id == Artifact.task_id)
            .where(*task_filters, Artifact.kind == _EXPORT_ARTIFACT_KIND)
        )
        or 0
    )

    return {
        "projects": projects,
        "documents": documents,
        "tasks_by_kind": tasks_by_kind,
        "tasks_with_findings": tasks_with_findings,
        "findings_total": findings_total,
        "proposals_created": proposals_created,
        "proposals_applied": proposals_applied,
        "artifacts_created": artifacts_created,
        "exports": exports,
        "first_finding_rate": _ratio(tasks_with_findings, total_tasks),
        "apply_rate": _ratio(proposals_applied, proposals_created),
    }


__all__ = ["task_metrics", "funnel_metrics"]
