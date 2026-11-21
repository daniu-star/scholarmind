"""任务执行器：租约抢占 → 分派 → 最小交付校验 → 结算/释放 → 终态事件。

设计约束（R0_INTERFACE_SPEC §3、PRD FR-15、Playbook T06/T07）：

- **重入不重复执行**：先经 ``task_repository.open_attempt`` 抢占租约（带 fencing），
  抢不到直接返回；终态任务直接跳过；
- **模型快照捕获一次**：任务开始时写入 ``snapshot_summary``，此后整条链路复用，
  不中途换模型；
- **成果先落库再发事件**：所有 service 先 flush，再 ``artifact.created``；
- **completed 只由校验决定**：``contracts.completion_errors`` 逐 kind 检查最小交付，
  不通过则落 partial/failed 并释放额度，绝不把空成果当成功；
- 任何异常都收敛为任务终态，不向调用方抛（调度器可以安全重试）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from . import artifact_service, budget
from .contracts import (
    BillingState,
    Coverage,
    EventType,
    QualityVerdict,
    TaskKind,
    TaskResult,
    TaskStatus,
    TERMINAL_STATUSES,
    completion_errors,
    utcnow,
)
from .errors import ResearchAPIError, internal, invalid, unavailable
from .models import ResearchTask
from .ownership import require_document, require_version
from .pipelines.base import (
    DEFAULT_MAX_CALLS,
    DEFAULT_MAX_TOKENS,
    PIPELINE_VERSION,
    REVIEW_PROMPT_VERSION,
    GenerationRequest,
    split_outline,
)
from .pipelines.generation.pipeline import GenerationPipeline
from .runtime import (
    ModelSnapshot,
    SUPPORTED_MODES,
    capture_snapshot,
    get_client,
    snapshot_from_dict,
)

logger = logging.getLogger(__name__)

#: 单次尝试的租约时长（秒），与 PRD §9 的累计运行期限一致。
LEASE_SECONDS = 1200

_TERMINAL_VALUES = {status.value for status in TERMINAL_STATUSES}


# ── 模块级工具 ────────────────────────────────────────────────


def _status_of(task: ResearchTask) -> str:
    return str(getattr(task, "status", "") or "")


def _kind_of(task: ResearchTask) -> str:
    return str(getattr(task, "kind", "") or "")


def _input_json(task: ResearchTask) -> Dict[str, Any]:
    data = getattr(task, "input_json", None)
    return dict(data) if isinstance(data, dict) else {}


def _constraints_json(task: ResearchTask) -> Dict[str, Any]:
    data = getattr(task, "constraints_json", None)
    return dict(data) if isinstance(data, dict) else {}


def _snapshot_summary_dict(task: ResearchTask) -> Dict[str, Any]:
    data = getattr(task, "snapshot_summary", None)
    return dict(data) if isinstance(data, dict) else {}


def _mode_of(task: ResearchTask) -> Optional[str]:
    summary = _snapshot_summary_dict(task)
    for raw in (
        summary.get("mode"),
        _input_json(task).get("mode"),
    ):
        value = str(raw or "").strip().lower()
        if value in SUPPORTED_MODES:
            return value
    return None


def _budget(summary: Dict[str, Any]) -> Tuple[int, int]:
    """执行期上限：快照里的 max_model_calls（兼容旧键 max_calls）优先。"""
    raw = summary.get("accepted_budget")
    accepted = budget.accepted_budget_from_mapping(raw if isinstance(raw, dict) else {})
    max_calls = (
        accepted.max_model_calls
        if accepted.max_model_calls is not None
        else DEFAULT_MAX_CALLS
    )
    max_tokens = (
        accepted.max_tokens if accepted.max_tokens is not None else DEFAULT_MAX_TOKENS
    )
    return max(1, int(max_calls)), max(1, int(max_tokens))


def _coverage_of(value: Any) -> Optional[Coverage]:
    if value is None:
        return None
    if isinstance(value, Coverage):
        return value
    if isinstance(value, dict):
        try:
            return Coverage.model_validate(value)
        except Exception:  # noqa: BLE001 - 覆盖记录不合法按缺失处理，不阻断终态
            logger.warning("覆盖记录无法解析，按缺失处理", exc_info=True)
            return None
    return None


def _verdict_of(value: Any) -> Optional[QualityVerdict]:
    if value is None:
        return None
    if isinstance(value, QualityVerdict):
        return value
    try:
        return QualityVerdict(str(value))
    except ValueError:
        logger.warning("未知质量结论，按缺失处理: %r", value)
        return None


def _str_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    try:
        return [str(item) for item in value if str(item).strip()]
    except TypeError:
        return []


def _error_payload(exc: ResearchAPIError) -> Dict[str, Any]:
    return {
        "code": exc.code,
        "message": exc.message,
        "retryable": exc.retryable,
        "details": dict(exc.details or {}),
    }


async def _reservation_of(db: Any, task: ResearchTask, billing: Any) -> Optional[Dict[str, Any]]:
    """重建任务的额度预留凭据（无预留的 chart/export 返回 None）。"""
    try:
        return await billing.reservation_for_task(db, task)
    except Exception:  # noqa: BLE001 - 凭据缺失按“未持有额度”处理
        logger.warning("任务 %s 预留凭据读取失败", getattr(task, "id", "?"), exc_info=True)
        return None


def _billing_state_of(task: ResearchTask) -> Optional[BillingState]:
    raw = str(getattr(task, "billing_state", "") or "")
    try:
        return BillingState(raw) if raw else None
    except ValueError:
        return None


def _model_snapshot(task: ResearchTask) -> Tuple[Dict[str, Any], ModelSnapshot]:
    """复用任务开始时捕获的快照；缺失则捕获一次并写回摘要。"""
    summary = _snapshot_summary_dict(task)
    snapshot: Optional[ModelSnapshot] = None
    raw = summary.get("model_snapshot")
    if isinstance(raw, dict):
        try:
            snapshot = snapshot_from_dict(raw)
        except (ValueError, TypeError, KeyError):
            snapshot = None
    if snapshot is None:
        snapshot = capture_snapshot(mode=_mode_of(task))

    summary["model_snapshot"] = snapshot.to_dict()
    summary.setdefault("actual_model", snapshot.model)
    summary.setdefault("provider", snapshot.provider)
    summary.setdefault("mode", snapshot.mode)
    summary.setdefault("captured_at", snapshot.captured_at.isoformat())
    summary.setdefault("pipeline_version", PIPELINE_VERSION)
    summary.setdefault("prompt_version", REVIEW_PROMPT_VERSION)
    if not isinstance(summary.get("accepted_budget"), dict):
        # 受理预算已由 task_service 冻结；历史任务缺失时用同一解析器补齐
        # （保留 max_calls 旧键供 R1 读取方复用），不再写死常量。
        summary["accepted_budget"] = budget.budget_payload(
            budget.accepted_budget(task), legacy_aliases=True
        )
    return summary, snapshot


def _lazy_repository():
    from . import task_repository

    return task_repository


def _lazy_billing():
    from . import billing_service

    return billing_service


def _usage_pair(result: Any) -> Tuple[int, int]:
    """从服务返回体提取真实模型用量（调用数、输出 tokens）。

    修改链路的用量在 ``validation_report.calls`` 里；生成链路在顶层
    ``calls`` / ``output_tokens``。取不到就是 0，不做按字数估算。
    """
    data = result if isinstance(result, dict) else {}
    report = data.get("validation_report")
    report = report if isinstance(report, dict) else {}
    calls: Any = data.get("calls")
    if calls is None:
        calls = report.get("calls")
    if calls is None:
        calls = data.get("model_calls")
    tokens: Any = data.get("output_tokens")
    if tokens is None:
        tokens = data.get("tokens")
    if tokens is None:
        tokens = report.get("output_tokens")
    try:
        return max(0, int(calls or 0)), max(0, int(tokens or 0))
    except (TypeError, ValueError):
        return 0, 0


async def _record_usage(db: Any, task: ResearchTask, repository: Any, result: Any) -> None:
    """给“只在本尝试结束时才可知”的用量补一条任务累计事件。

    诊断链路（review_workflow）已按窗口写增量事件；导出没有模型调用；生成与
    修改链路只在结果里带总量，因此这里落 ``usage_mode="cumulative"``，按
    attempt 取最大值，重入不会把同一次调用算两遍。
    """
    kind = _kind_of(task)
    if kind not in {"draft_from_outline", "revision"}:
        return
    calls, tokens = _usage_pair(result)
    if calls <= 0 and tokens <= 0:
        return
    await repository.append_event(
        db,
        task,
        EventType.TASK_PROGRESS.value,
        payload={
            "phase": "usage",
            "usage_mode": "cumulative",
            "model_calls": calls,
            "tokens": tokens,
            "source": kind,
        },
    )


async def _refresh_budget_evaluation(
    db: Any, task: ResearchTask, repository: Any
) -> Dict[str, Any]:
    """按已落盘事件重算预算，并写进快照（不推进任务状态）。

    口径只认事件：检查点里跨尝试的基数由 review_workflow 补记，未落盘的用量
    不会被假装已知；费用未知时 ``cost_usd`` 为 None，绝不写 0。
    """
    usage = budget.usage_from_events(await repository.list_events(db, task.id))
    evaluation = budget.evaluate_budget(budget.accepted_budget(task), usage)
    summary = dict(task.snapshot_summary or {})
    summary["budget_evaluation"] = evaluation
    task.snapshot_summary = summary
    await db.flush()
    return evaluation


# ── 对外入口 ──────────────────────────────────────────────────


async def execute_task(
    db: Any,
    task: ResearchTask,
    *,
    holder: str,
    client: Any = None,
) -> None:
    """执行一个已排队任务；异常收敛为任务终态，不向调用方抛出。"""
    if task is None or not isinstance(task, ResearchTask):
        return
    if _status_of(task) in _TERMINAL_VALUES:
        return
    if not str(holder or "").strip():
        raise ValueError("execute_task 需要非空 lease holder")

    repository = _lazy_repository()
    billing = _lazy_billing()

    try:
        attempt = await repository.open_attempt(
            db, task, lease_holder=holder, lease_seconds=LEASE_SECONDS
        )
    except ResearchAPIError as exc:
        # 租约已被其他执行器持有 / 任务状态已变化：安全放弃，重入不重复执行。
        logger.info("任务 %s 抢占失败，跳过：%s", task.id, exc.code)
        return
    except Exception:  # noqa: BLE001 - 抢占失败同样安全放弃
        logger.warning("任务 %s 抢占异常，跳过", task.id, exc_info=True)
        return

    # 把本次领取的 fencing token 绑到上下文：租约被接管后，本次执行的任何
    # 事件/状态写入都会被 repository 以 STALE_ATTEMPT 拒绝（PRD FR-11）。
    lease_handle = repository.set_lease_scope(getattr(attempt, "fencing_token", None))
    try:
        try:
            await _execute_claimed(
                db,
                task,
                holder=holder,
                client=client,
                attempt=attempt,
                repository=repository,
                billing=billing,
            )
        except ResearchAPIError as exc:
            await _finalize_exception(
                db, task, attempt, exc, repository=repository, billing=billing
            )
        except Exception as exc:  # noqa: BLE001 - 收敛为 failed，不向调度器抛
            logger.exception("任务 %s 执行异常", task.id)
            await _finalize_exception(
                db,
                task,
                attempt,
                internal(f"任务执行异常：{type(exc).__name__}"),
                repository=repository,
                billing=billing,
            )
    finally:
        repository.reset_lease_scope(lease_handle)


# ── 主流程 ────────────────────────────────────────────────────


async def _execute_claimed(
    db: Any,
    task: ResearchTask,
    *,
    holder: str,
    client: Any,
    attempt: Any,
    repository: Any,
    billing: Any,
) -> None:
    summary, snapshot = _model_snapshot(task)

    current = _status_of(task)
    if current in (TaskStatus.RECOVERABLE.value, TaskStatus.NEEDS_INPUT.value):
        # 终态迁移规则要求先回 queued，不能 recoverable→running。
        task = await repository.transition(db, task, TaskStatus.QUEUED)
        current = _status_of(task)
    if current != TaskStatus.RUNNING.value:
        task = await repository.transition(
            db, task, TaskStatus.RUNNING, snapshot_summary=summary
        )
    else:
        # open_attempt 已把任务置为 running：仅补齐快照字段，不重复迁移。
        task.snapshot_summary = summary
        await db.flush()

    await repository.append_event(
        db,
        task,
        EventType.TASK_STARTED.value,
        payload={
            "kind": _kind_of(task),
            "attempt_no": getattr(attempt, "attempt_no", None),
            "holder": holder,
            "model": snapshot.model,
            "provider": snapshot.provider,
            "mode": snapshot.mode,
            "captured_at": snapshot.captured_at.isoformat(),
            "pipeline_version": summary.get("pipeline_version"),
            "prompt_version": summary.get("prompt_version"),
        },
    )

    model_client = (
        client
        if client is not None
        # 同一任务的所有窗口共享压缩会话，代理才能折叠已分析窗口的历史。
        else get_client(snapshot, session_key=f"research:{task.id}")
    )
    result = await _dispatch(db, task, client=model_client, summary=summary)

    # 用量先落事件，再算预算评估：终态事件必须排在用量事件之后。
    await _record_usage(db, task, repository, result)
    evaluation = await _refresh_budget_evaluation(db, task, repository)
    budget_overruns = budget.overrun_messages(evaluation)

    artifact_ids = _str_list(result.get("artifact_ids"))
    rows = await artifact_service.list_artifact_rows(db, task.id)
    kind_by_id = {row.id: row.kind for row in rows}

    # T07：成果已经 flush 落库，才发 artifact.created。
    for artifact_id in artifact_ids:
        await repository.append_event(
            db,
            task,
            EventType.ARTIFACT_CREATED.value,
            payload={
                "artifact_id": artifact_id,
                "kind": kind_by_id.get(artifact_id, result.get("artifact_kind", "")),
            },
        )

    coverage = _coverage_of(result.get("coverage"))
    verdict = _verdict_of(result.get("quality_verdict"))
    warnings = _str_list(result.get("warnings"))
    unresolved = _str_list(result.get("unresolved_items"))

    check_result = TaskResult(
        task_id=task.id,
        status=TaskStatus.SUCCEEDED,
        artifact_ids=artifact_ids,
        coverage=coverage,
        quality_verdict=verdict,
        warnings=warnings,
        unresolved_items=unresolved,
        billing_state=None,
    )
    # 超预算与最小交付校验并列：任一不通过都不能落 succeeded，但已覆盖范围与
    # 已产出成果照常交付（partial），reason 里写明 overruns。
    errors = budget_overruns + completion_errors(
        TaskKind(_kind_of(task)), check_result, set(kind_by_id.values())
    )
    if errors:
        await _finalize_incomplete(
            db,
            task,
            attempt,
            errors,
            artifact_ids=artifact_ids,
            coverage=coverage,
            warnings=warnings,
            unresolved=unresolved,
            repository=repository,
            billing=billing,
            budget_evaluation=evaluation,
        )
        return

    # 结算额度：只有通过最小交付检查的成功任务才结算。
    reservation = await _reservation_of(db, task, billing)
    await billing.settle(db, task, reservation)

    succeeded = TaskResult(
        task_id=task.id,
        status=TaskStatus.SUCCEEDED,
        artifact_ids=artifact_ids,
        coverage=coverage,
        quality_verdict=verdict,
        warnings=warnings,
        unresolved_items=unresolved,
        billing_state=_billing_state_of(task),
    )
    task = await repository.transition(
        db,
        task,
        TaskStatus.SUCCEEDED,
        result=succeeded.model_dump(mode="json"),
        coverage=coverage.model_dump(mode="json") if coverage else None,
        quality_verdict=verdict.value if verdict else None,
    )
    await repository.append_event(
        db,
        task,
        EventType.TASK_COMPLETED.value,
        payload={
            "artifact_ids": artifact_ids,
            "billing_state": str(getattr(task, "billing_state", "") or ""),
            "quality_verdict": verdict.value if verdict else None,
            "coverage": coverage.model_dump(mode="json") if coverage else None,
        },
    )
    await repository.close_attempt(db, attempt, "succeeded")
    await db.commit()


# ── 分派 ──────────────────────────────────────────────────────


async def _dispatch(
    db: Any,
    task: ResearchTask,
    *,
    client: Any,
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    kind = _kind_of(task)
    if kind == TaskKind.REVIEW.value:
        from . import review_workflow

        return await review_workflow.run_review(
            db, task, client=client, artifact_kind="review_report"
        )
    if kind == TaskKind.LITERATURE_REVIEW.value:
        from . import review_workflow

        return await review_workflow.run_review(
            db, task, client=client, artifact_kind="literature_review"
        )
    if kind == TaskKind.REVISION.value:
        from . import revision_service

        return await revision_service.run_revision_task(db, task, client=client)
    if kind == TaskKind.DRAFT_FROM_OUTLINE.value:
        return await _run_generation(db, task, client=client, summary=summary)
    if kind == TaskKind.EXPORT.value:
        return await _run_export(db, task, summary=summary)
    if kind == TaskKind.CHART.value:
        raise unavailable(
            "CHART_DISABLED",
            "图表生成能力当前版本尚未开放，请改用导出或稍后重试",
            {"kind": kind},
        )
    raise invalid("UNSUPPORTED_TASK_KIND", f"不支持的任务类型：{kind}", {"kind": kind})


# ── 草稿生成 ──────────────────────────────────────────────────


async def _run_generation(
    db: Any,
    task: ResearchTask,
    *,
    client: Any,
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    from .contracts import Actor

    actor = Actor(user_id=task.owner_id)
    input_json = _input_json(task)
    constraints = _constraints_json(task)

    version_id = (
        input_json.get("outline_document_version_id")
        or input_json.get("outline_version_id")
        or input_json.get("document_version_id")
        or input_json.get("version_id")
        or input_json.get("input_version_id")
        or summary.get("outline_document_version_id")
    )
    if not version_id:
        raise invalid(
            "MISSING_OUTLINE_VERSION",
            "草稿任务缺少提纲版本，无法生成",
            {"task_id": task.id},
        )

    version = await require_version(db, actor, str(version_id))
    outline_text = str(version.text or "")
    sections = split_outline(outline_text)
    if not sections:
        raise invalid(
            "EMPTY_OUTLINE",
            "提纲正文为空，未生成任何草稿",
            {"document_version_id": version.id},
        )

    target_raw = (
        input_json.get("target_word_count")
        or constraints.get("target_word_count")
        or input_json.get("target_words")
    )
    try:
        target_word_count = int(target_raw) if target_raw else None
    except (TypeError, ValueError):
        target_word_count = None
    if target_word_count is not None and target_word_count <= 0:
        target_word_count = None

    protected_raw = constraints.get("protected_terms") or input_json.get(
        "protected_terms"
    )
    protected_terms = tuple(_str_list(protected_raw))

    request = GenerationRequest(
        objective=str(task.objective or ""),
        outline_sections=tuple(sections),
        outline_version_id=version.id,
        target_word_count=target_word_count,
        research_type=str(
            constraints.get("research_type") or input_json.get("research_type") or ""
        ),
        journal_style=str(
            constraints.get("journal_style")
            or input_json.get("journal_style")
            or "generic"
        ),
        no_new_empirical_claims=bool(
            constraints.get("no_new_empirical_claims", True)
        ),
        protected_terms=protected_terms,
        max_calls=_budget(summary)[0],
        max_tokens=_budget(summary)[1],
    )

    pipeline = GenerationPipeline(
        client, max_calls=request.max_calls, max_tokens=request.max_tokens
    )
    outcome = await pipeline.run(request)

    body = str(outcome.body or "").strip()
    if not body:
        raise invalid(
            "EMPTY_DRAFT",
            "草稿正文为空，不能作为交付",
            {"document_version_id": version.id},
        )

    warnings = list(outcome.warnings)
    if (
        outcome.target_word_count
        and not outcome.within_target_range
        and "目标字数" not in " ".join(warnings)
    ):
        warnings.append(
            f"草稿字数 {outcome.word_count} 不在目标 "
            f"{outcome.target_word_count} 的 ±10% 范围内"
        )

    notes = list(outcome.unresolved_items) + [
        item for item in warnings if item not in outcome.unresolved_items
    ]
    if notes:
        body = body + "\n\n## 待补充与限制\n\n" + "\n".join(
            f"- {item}" for item in notes
        )

    validation = {
        "outline_version_id": version.id,
        "outline_section_count": len(sections),
        "outline_coverage": list(outcome.outline_coverage),
        "word_count": outcome.word_count,
        "target_word_count": outcome.target_word_count,
        "within_target_range": outcome.within_target_range,
        "counter_version": outcome.counter_version,
        "truncated": outcome.truncated,
        "calls": outcome.calls,
        "output_tokens": outcome.output_tokens,
        "pipeline_version": outcome.pipeline_version,
        "prompt_version": outcome.prompt_version,
        "generated_at": utcnow().isoformat(),
    }
    artifact = await artifact_service.create_artifact(
        db,
        owner_id=task.owner_id,
        task_id=task.id,
        kind="draft",
        body=body,
        mime="text/markdown",
        filename=f"draft_v{version.version_no}.md",
        validation=validation,
    )
    return {
        "artifact_ids": [artifact.id],
        "artifact_kind": "draft",
        "coverage": None,
        "quality_verdict": None,
        "warnings": warnings,
        "unresolved_items": list(outcome.unresolved_items),
        # 预算评估需要真实用量；缺失时宁可为 0（确实未记录），不估算。
        "calls": int(getattr(outcome, "calls", 0) or 0),
        "output_tokens": int(getattr(outcome, "output_tokens", 0) or 0),
    }


# ── 导出 ──────────────────────────────────────────────────────


async def _run_export(
    db: Any, task: ResearchTask, *, summary: Dict[str, Any]
) -> Dict[str, Any]:
    from . import export_service
    from .contracts import Actor

    actor = Actor(user_id=task.owner_id)
    input_json = _input_json(task)
    constraints = _constraints_json(task)

    version_id = (
        input_json.get("document_version_id")
        or input_json.get("version_id")
        or input_json.get("input_version_id")
        or summary.get("document_version_id")
    )
    if not version_id:
        raise invalid(
            "MISSING_DOCUMENT_VERSION", "导出任务缺少文档版本", {"task_id": task.id}
        )

    fmt = str(
        input_json.get("format") or constraints.get("format") or summary.get("format") or "md"
    )
    journal_style = str(
        input_json.get("journal_style")
        or constraints.get("journal_style")
        or summary.get("journal_style")
        or "generic"
    )

    project_id = getattr(task, "project_id", None)
    if not project_id:
        version = await require_version(db, actor, str(version_id))
        document = await require_document(db, actor, version.document_id)
        project_id = document.project_id

    artifact = await export_service.export(
        db,
        actor,
        project_id=project_id,
        document_version_id=str(version_id),
        fmt=fmt,
        journal_style=journal_style,
        task_id=task.id,
    )
    return {
        "artifact_ids": [artifact.id],
        "artifact_kind": "export",
        "coverage": None,
        "quality_verdict": None,
        "warnings": [],
        "unresolved_items": [],
    }


# ── 终态收敛 ──────────────────────────────────────────────────


async def _finalize_incomplete(
    db: Any,
    task: ResearchTask,
    attempt: Any,
    errors: List[str],
    *,
    artifact_ids: List[str],
    coverage: Optional[Coverage],
    warnings: List[str],
    unresolved: List[str],
    repository: Any,
    billing: Any,
    budget_evaluation: Optional[Dict[str, Any]] = None,
) -> None:
    """最小交付检查未通过 / 超预算：既不结算，也不把空成果当成功。"""
    exceeded = bool(budget_evaluation) and budget_evaluation.get("state") == "exceeded"
    payload = {
        # 超预算与交付不合格是两种诚实失败原因，错误码必须可区分。
        "code": "BUDGET_EXCEEDED" if exceeded else "INCOMPLETE_DELIVERABLE",
        "message": (
            "任务超出受理预算，已交付已覆盖范围内的成果"
            if exceeded
            else "成果未通过最小交付校验"
        ),
        "errors": errors,
    }
    if budget_evaluation:
        payload["budget_evaluation"] = budget_evaluation
    await _release_quota(db, task, billing)
    if artifact_ids:
        partial = TaskResult(
            task_id=task.id,
            status=TaskStatus.PARTIAL,
            artifact_ids=artifact_ids,
            coverage=coverage,
            quality_verdict=None,
            warnings=warnings + errors,
            unresolved_items=unresolved + errors,
            billing_state=BillingState.RELEASED,
        )
        task = await repository.transition(
            db,
            task,
            TaskStatus.PARTIAL,
            result=partial.model_dump(mode="json"),
            error=payload,
        )
        await repository.append_event(
            db,
            task,
            EventType.TASK_PARTIAL.value,
            payload={"artifact_ids": artifact_ids, "errors": errors},
        )
        await repository.close_attempt(db, attempt, "partial", error=payload)
    else:
        task = await repository.transition(
            db, task, TaskStatus.FAILED, error=payload
        )
        await repository.append_event(
            db,
            task,
            EventType.TASK_FAILED.value,
            payload={"error": payload},
        )
        await repository.close_attempt(db, attempt, "failed", error=payload)
    await db.commit()


async def _finalize_exception(
    db: Any,
    task: ResearchTask,
    attempt: Any,
    exc: ResearchAPIError,
    *,
    repository: Any,
    billing: Any,
) -> None:
    """异常收敛：可重试 → recoverable（不结算不释放）；否则 failed/partial。"""
    payload = _error_payload(exc)
    retryable = exc.status_code == 503 or exc.retryable

    try:
        artifact_rows = await artifact_service.list_artifact_rows(db, task.id)
        artifact_ids = [row.id for row in artifact_rows]
        if retryable:
            task = await repository.transition(
                db, task, TaskStatus.RECOVERABLE, error=payload
            )
            await repository.append_event(
                db,
                task,
                EventType.TASK_RECOVERABLE.value,
                payload={"error": payload, "artifact_ids": artifact_ids},
            )
            await repository.close_attempt(
                db, attempt, "recoverable", error=payload
            )
        else:
            await _release_quota(db, task, billing)
            # 失败/部分完成也要留下预算口径：已 failed 的终态不变，只记录用量。
            try:
                evaluation = await _refresh_budget_evaluation(db, task, repository)
                if evaluation.get("state") == "exceeded":
                    payload["budget_evaluation"] = evaluation
                    payload["budget_overruns"] = list(evaluation.get("overruns") or [])
            except Exception:  # noqa: BLE001 - 评估失败不能改变失败终态的语义
                logger.warning("任务 %s 预算评估失败", task.id, exc_info=True)
            if artifact_ids:
                partial = TaskResult(
                    task_id=task.id,
                    status=TaskStatus.PARTIAL,
                    artifact_ids=artifact_ids,
                    coverage=None,
                    quality_verdict=None,
                    warnings=[exc.message],
                    unresolved_items=[exc.message],
                    billing_state=BillingState.RELEASED,
                )
                task = await repository.transition(
                    db,
                    task,
                    TaskStatus.PARTIAL,
                    result=partial.model_dump(mode="json"),
                    error=payload,
                )
                await repository.append_event(
                    db,
                    task,
                    EventType.TASK_PARTIAL.value,
                    payload={"artifact_ids": artifact_ids, "error": payload},
                )
                await repository.close_attempt(
                    db, attempt, "partial", error=payload
                )
            else:
                task = await repository.transition(
                    db, task, TaskStatus.FAILED, error=payload
                )
                await repository.append_event(
                    db,
                    task,
                    EventType.TASK_FAILED.value,
                    payload={"error": payload},
                )
                await repository.close_attempt(
                    db, attempt, "failed", error=payload
                )
        await db.commit()
    except Exception:  # noqa: BLE001 - 收敛失败不向调度器抛，留给租约过期重试
        logger.exception("任务 %s 终态收敛失败", getattr(task, "id", "?"))
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass


async def _release_quota(db: Any, task: ResearchTask, billing: Any) -> None:
    try:
        reservation = await _reservation_of(db, task, billing)
        await billing.release(db, task, reservation)
    except Exception:  # noqa: BLE001 - 释放失败不应掩盖真实失败原因
        logger.warning("任务 %s 额度释放失败", getattr(task, "id", "?"), exc_info=True)


__all__ = ["LEASE_SECONDS", "execute_task"]
