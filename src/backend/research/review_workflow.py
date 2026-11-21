"""全文诊断工作流（FR-07、FR-15、T06）。

职责：
1. 读取任务的输入版本，遍历**全部** eligible 块（借助 ``retrieval_service.iter_chunks``
   获取已索引文本，索引缺失时回退原文块并显式记录 warning）；
2. 调用实例化的 ``ReviewPipeline`` 逐窗诊断；
3. 持久化 ``FindingRow``、计算精确 ``Coverage``（expected/analyzed），
   生成可读诊断报告成果（``Artifact``）；
4. 结论只能是 ``issues_found`` / ``no_major_issues_found`` / ``insufficient_evidence``。

诚实性：
- 模型不可用→``unavailable`` 向上抛，由执行器落 recoverable/failed，**禁止**
  伪造 ``no_major_issues_found``；
- 覆盖不足时结论强制 ``insufficient_evidence``，并在未解决项中列出未分析块；
- 报告显式声明未执行统计检验、实验复现、查重与外部文献核实。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import artifact_service, budget, task_repository
from .checkpoints import load_checkpoint_payload, save_checkpoint
from .completeness import document_level_findings, section_coverage
from .contracts import (
    DIMENSIONS,
    Actor,
    Coverage,
    EventType,
    ParseStatus,
    QualityVerdict,
    new_id,
    normalize_text,
    utcnow,
)
from .errors import invalid
from .models import DocumentBlock, DocumentVersion, FindingRow, ResearchTask
from .ownership import require_document, require_version
from .pipelines.base import (
    DEFAULT_MAX_CALLS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_WINDOW_CODEPOINTS,
    FindingDraft,
    ReviewBlock,
    ReviewOutcome,
    ReviewRequest,
)
from .pipelines.review.pipeline import ReviewPipeline, finding_payload

#: 报告中的限制声明（FR-07：不得声称做过统计检验/实验复现/外部核实）。
DIAGNOSIS_DISCLAIMER = (
    "本报告仅基于给定版本文本的模型阅读生成：未执行统计检验、实验复现、查重、"
    "数据库检索或外部文献核实；涉及推断的内容已标注为模型判断，需作者自行复核。"
)

_VERDICT_LABELS = {
    "issues_found": "发现问题（issues_found）",
    "no_major_issues_found": "未发现重大问题（no_major_issues_found）",
    "insufficient_evidence": "证据不足，无法下结论（insufficient_evidence）",
}

_SEVERITY_LABELS = {"critical": "致命", "major": "重要", "minor": "次要"}
_SCOPE_LABELS = {"local": "局部", "document": "整体"}


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _input_version_id(task: ResearchTask) -> str:
    for source in (_as_dict(task.input_json), _as_dict(task.scope_json)):
        for key in ("document_version_id", "version_id", "input_version_id"):
            raw = source.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    raise invalid(
        "MISSING_DOCUMENT_VERSION",
        "任务缺少输入文档版本，无法执行全文诊断",
        {"task_id": task.id},
    )


def _accepted_budget(task: ResearchTask) -> Tuple[int, int]:
    """受理上限：constraints 快照优先，旧快照键与进程缺省值兜底。"""
    resolved = budget.accepted_budget(task)
    max_calls = (
        resolved.max_model_calls
        if resolved.max_model_calls is not None
        else DEFAULT_MAX_CALLS
    )
    max_tokens = (
        resolved.max_tokens if resolved.max_tokens is not None else DEFAULT_MAX_TOKENS
    )
    return max(1, int(max_calls)), max(1, int(max_tokens))


def _mode_of(task: ResearchTask) -> str:
    summary = _as_dict(task.snapshot_summary)
    snapshot = _as_dict(summary.get("model_snapshot"))
    mode = snapshot.get("mode") or _as_dict(task.input_json).get("mode") or ""
    return str(mode).strip() or "default"


def _parse_status(value: Any) -> Tuple[ParseStatus, Optional[str]]:
    try:
        return ParseStatus(str(value)), None
    except ValueError:
        return ParseStatus.COMPLETE, f"未知解析状态 {value!r}，按 complete 处理"


async def _load_blocks(
    db: AsyncSession, version: DocumentVersion
) -> List[DocumentBlock]:
    result = await db.execute(
        select(DocumentBlock)
        .where(
            DocumentBlock.version_id == version.id,
            DocumentBlock.eligible.is_(True),
        )
        .order_by(DocumentBlock.ordinal.asc())
    )
    return list(result.scalars().all())


async def _chunk_text_by_block(
    db: AsyncSession, task: ResearchTask, version: DocumentVersion
) -> Tuple[Dict[str, List[Any]], Optional[str]]:
    """取块级文本：优先用检索索引的分块，索引不可用时显式回退原文块。"""
    chunks_by_block: Dict[str, List[Any]] = {}
    try:
        from . import retrieval_service  # 延迟导入：避免模块导入期耦合
    except ImportError:
        return {}, "检索索引模块不可用，已直接使用原文块进行全文分析"

    actor = Actor(user_id=task.owner_id)
    warning: Optional[str] = None
    try:
        chunks = await retrieval_service.iter_chunks(db, actor, version.id)
        if not chunks:
            try:
                await retrieval_service.ensure_index(db, actor, version.id)
                chunks = await retrieval_service.iter_chunks(db, actor, version.id)
            except Exception as exc:  # 建索引失败不阻断诊断，但必须披露
                chunks = []
                warning = f"检索索引建立失败（{type(exc).__name__}），已回退原文块分析"
    except Exception as exc:  # 索引查询异常同样降级，但显式记录
        return {}, f"检索索引读取失败（{type(exc).__name__}），已回退原文块分析"

    for chunk in chunks or ():
        block_id = getattr(chunk, "block_id", None)
        if not block_id:
            continue
        chunks_by_block.setdefault(block_id, []).append(chunk)
    if chunks and not chunks_by_block:
        warning = "检索索引未返回可映射到正文块的分块，已回退原文块分析"
    return chunks_by_block, warning


def _chunk_text_for_block(
    block: DocumentBlock, chunks: Sequence[Any]
) -> Optional[str]:
    """截取索引分块中真正属于本块的文本片段。

    检索分块会把相邻的短块合并进同一个 chunk；若直接把整块 chunk 文本当作单块
    正文，已分析块的原文字就会随相邻块重新进入提示词（重复阅读、重复扣预算）。
    这里按 ``chunk.start/end`` 与 ``block.start/end`` 的交集裁剪，保证每个诊断
    块只带自己的文字。分块缺少可信偏移时返回 ``None``，调用方回退原文块。
    """
    block_start = int(block.start or 0)
    block_end = int(block.end if block.end is not None else block_start)
    if block_end <= block_start:
        return None
    body = str(getattr(block, "text", "") or "")
    if len(body) != block_end - block_start:
        # 块正文必须与块偏移一一对应，否则无法用块内相对位置还原全文片段。
        return None
    intervals: List[Tuple[int, int]] = []
    for chunk in chunks:
        text = str(getattr(chunk, "text", "") or "")
        if not text:
            continue
        try:
            chunk_start = int(getattr(chunk, "start", 0) or 0)
            chunk_end = int(getattr(chunk, "end", 0) or 0)
        except (TypeError, ValueError):
            return None
        if chunk_end <= chunk_start or chunk_end - chunk_start != len(text):
            return None
        lo = max(block_start, chunk_start)
        hi = min(block_end, chunk_end)
        if hi > lo:
            intervals.append((lo, hi))
    if not intervals:
        return None
    # 分块之间允许重叠（≤100 码点）：按区间取并集，避免把重叠部分重复拼进正文
    # ——重复会让窗口文本比块长，进而把引用偏移算错（R2 真实语料 12 条错位）。
    intervals.sort()
    merged: List[Tuple[int, int]] = [intervals[0]]
    for lo, hi in intervals[1:]:
        last_lo, last_hi = merged[-1]
        if lo <= last_hi:
            merged[-1] = (last_lo, max(last_hi, hi))
        else:
            merged.append((lo, hi))
    joined = "".join(
        body[lo - block_start : hi - block_start] for lo, hi in merged
    )
    return joined or None


def _build_review_blocks(
    blocks: Sequence[DocumentBlock],
    chunks_by_block: Dict[str, List[Any]],
) -> Tuple[List[ReviewBlock], List[str]]:
    """按块构建诊断输入；有索引文本时用索引文本，保证“读到的就是要分析的”。"""
    warnings: List[str] = []
    review_blocks: List[ReviewBlock] = []
    for block in blocks:
        chunks = sorted(
            chunks_by_block.get(block.id, []), key=lambda item: getattr(item, "ordinal", 0)
        )
        indexed_text = _chunk_text_for_block(block, chunks) if chunks else None
        if indexed_text is not None:
            text = normalize_text(indexed_text)
            start = int(block.start or 0)
            end = int(block.end if block.end is not None else start + len(text))
        else:
            text = normalize_text(block.text or "")
            start = int(block.start or 0)
            end = int(block.end if block.end is not None else start + len(text))
        if not text.strip():
            warnings.append(f"块 {block.ordinal} 无正文，已跳过")
            continue
        review_blocks.append(
            ReviewBlock(
                ordinal=int(block.ordinal),
                block_id=block.id,
                text=text,
                start=start,
                end=end,
                section_path=block.section_path or "",
                eligible=True,
                kind=str(block.kind or "paragraph"),
            )
        )
    return review_blocks, warnings


def _str_list(value: Any) -> List[str]:
    if not isinstance(value, (list, tuple)):
        return []
    items: List[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            items.append(text)
    return items


def _draft_from_payload(payload: Dict[str, Any]) -> Optional[FindingDraft]:
    """从检查点恢复一条诊断草稿；不合契约或无法核对整体范围的条目直接丢弃。"""
    category = str(payload.get("category") or "").strip()
    severity = str(payload.get("severity") or "").strip()
    problem = str(payload.get("problem") or "").strip()
    if not category or not severity or not problem:
        return None
    scope = str(payload.get("scope") or "document").strip()
    locator = payload.get("locator") if isinstance(payload.get("locator"), dict) else None
    quote = payload.get("quote") if isinstance(payload.get("quote"), str) else None
    checked_sections = _str_list(payload.get("checked_sections"))
    block_ordinal = payload.get("block_ordinal")
    if not isinstance(block_ordinal, int):
        block_ordinal = None
    if scope == "local" and (not quote or not locator):
        # 局部问题必须能回指原文；否则降级为整体问题，且必须有真实检查范围。
        scope = "document"
        quote = None
        locator = None
    if scope == "document" and not checked_sections:
        return None
    return FindingDraft(
        category=category,
        severity=severity,
        problem=problem,
        reason=str(payload.get("reason") or ""),
        recommendation=str(payload.get("recommendation") or ""),
        scope=scope,
        quote=quote,
        locator=locator,
        evidence_refs=_str_list(payload.get("evidence_refs")),
        checked_sections=tuple(checked_sections),
        required_user_action=(
            str(payload.get("required_user_action"))
            if payload.get("required_user_action")
            else None
        ),
        block_ordinal=block_ordinal,
        verification_method=str(payload.get("verification_method") or "model"),
    )


def _finding_key(draft: FindingDraft) -> Tuple[str, str]:
    return (draft.category, normalize_text(draft.problem)[:80])


def _decide_verdict(
    findings: Sequence[FindingDraft],
    *,
    coverage_complete: bool,
    truncated: bool,
    missing: Sequence[int],
    unresolved: Sequence[str],
) -> str:
    if any(draft.severity in {"critical", "major"} for draft in findings):
        return "issues_found"
    # 没读完全文/有未解决项，就不能说“未发现重大问题”。
    if not coverage_complete or truncated or missing or unresolved:
        return "insufficient_evidence"
    if findings:
        return "issues_found"
    return "no_major_issues_found"


def _empty_outcome(
    *,
    analyzed: Sequence[int],
    expected: Sequence[int],
    truncated: bool,
    message: Optional[str],
    calls: int,
    tokens: int,
) -> ReviewOutcome:
    """预算耗尽到无法再调用模型时，用已有覆盖构造诚实的结果（不伪造分析）。"""
    missing = sorted(set(expected) - set(analyzed))
    unresolved = tuple([message] if message else [])
    return ReviewOutcome(
        verdict="insufficient_evidence",
        findings=(),
        analyzed_ordinals=tuple(sorted(set(analyzed))),
        expected_ordinals=tuple(sorted(set(expected))),
        checked_sections=(),
        unassessed_objects=tuple(f"block:{ordinal}（预算已耗尽，未能分析）" for ordinal in missing),
        warnings=tuple([message] if message else []),
        unresolved_items=unresolved,
        truncated=truncated,
        calls=calls,
        output_tokens=tokens,
    )


def _render_report(
    *,
    title: str,
    task: ResearchTask,
    version: DocumentVersion,
    verdict: str,
    coverage: Coverage,
    findings: Sequence[FindingRow],
    warnings: Sequence[str],
    unresolved: Sequence[str],
    pipeline_version: str,
    prompt_version: str,
    section_summary: Optional[Dict[str, List[str]]] = None,
) -> str:
    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- 任务：{task.id}")
    lines.append(f"- 输入版本：{version.id}（v{version.version_no}）")
    lines.append(f"- 生成时间：{utcnow().isoformat()}Z")
    lines.append(f"- 流水线：{pipeline_version} / 提示词：{prompt_version}")
    lines.append("")
    lines.append("## 结论")
    lines.append("")
    lines.append(_VERDICT_LABELS.get(verdict, verdict))
    lines.append("")
    lines.append("## 全文覆盖")
    lines.append("")
    lines.append(f"- 解析状态：{coverage.parse_status.value}")
    lines.append(f"- 预期可分析块：{coverage.expected_eligible_blocks}")
    lines.append(f"- 已分析块：{coverage.analyzed_eligible_blocks}")
    lines.append(f"- 覆盖率：{coverage.analysis_ratio:.0%}")
    if coverage.pages is not None:
        lines.append(f"- 页数：{coverage.pages}")
    if coverage.unassessed_objects:
        lines.append(f"- 未评估对象：{', '.join(coverage.unassessed_objects[:50])}")
    lines.append("")
    if section_summary is not None:
        lines.append("## 章节覆盖")
        lines.append("")
        expected_sections = list(section_summary.get("expected") or [])
        covered_sections = list(section_summary.get("covered") or [])
        missing_sections = list(section_summary.get("missing") or [])
        lines.append(f"- 识别到章节：{len(expected_sections)}")
        lines.append(f"- 已覆盖章节：{len(covered_sections)}")
        if missing_sections:
            lines.append(f"- 未覆盖章节：{'；'.join(missing_sections[:50])}")
        lines.append("")
    lines.append(f"## 诊断项（{len(findings)}）")
    lines.append("")
    if not findings:
        lines.append("本次未记录到诊断项；结论以上方覆盖情况为前提。")
    for index, finding in enumerate(findings, start=1):
        severity = _SEVERITY_LABELS.get(finding.severity, finding.severity)
        scope = _SCOPE_LABELS.get(finding.scope, finding.scope)
        lines.append(f"### {index}. [{severity}][{finding.category}] {finding.problem}")
        lines.append("")
        lines.append(f"- 范围：{scope}")
        locator = _as_dict(finding.locator)
        if locator:
            section = locator.get("section_path") or "未标注章节"
            position = f"块 {locator.get('block_ordinal')}"
            if locator.get("start") is not None:
                position += f"，码点 {locator.get('start')}–{locator.get('end')}"
            lines.append(f"- 定位：{section} / {position}")
        if finding.quote:
            lines.append(f"- 原文：> {finding.quote}")
        if finding.reason:
            lines.append(f"- 原因：{finding.reason}")
        if finding.recommendation:
            lines.append(f"- 建议：{finding.recommendation}")
        if finding.checked_sections:
            lines.append(f"- 已检查章节：{'；'.join(finding.checked_sections)}")
        if finding.verification_method == "structural":
            lines.append("- 检查方式：结构性检查（依据章节结构，非模型推断）")
        else:
            lines.append("- 检查方式：模型阅读推断（未做外部核实）")
        if finding.required_user_action:
            lines.append(f"- 需要作者处理：{finding.required_user_action}")
        lines.append("")
    lines.append("## 未解决项")
    lines.append("")
    if unresolved:
        for item in unresolved:
            lines.append(f"- {item}")
    else:
        lines.append("- 无")
    lines.append("")
    lines.append("## 警告")
    lines.append("")
    if warnings:
        for item in warnings:
            lines.append(f"- {item}")
    else:
        lines.append("- 无")
    lines.append("")
    lines.append("## 限制声明")
    lines.append("")
    lines.append(DIAGNOSIS_DISCLAIMER)
    lines.append("")
    return "\n".join(lines)


async def run_review(
    db: AsyncSession,
    task: ResearchTask,
    *,
    client: Any,
    artifact_kind: str = "review_report",
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """执行一次全文诊断，返回执行器所需的成果与覆盖信息。"""
    if task is None or not isinstance(task, ResearchTask):
        raise invalid("INVALID_TASK", "缺少有效任务")
    actor = Actor(user_id=task.owner_id)
    version_id = _input_version_id(task)
    version = await require_version(db, actor, version_id)
    document = await require_document(db, actor, version.document_id)
    if document.project_id != task.project_id:
        # 版本必须属于任务所在项目，避免跨项目拼接证据（FR-03 / FR-05）。
        raise invalid(
            "PROJECT_DOCUMENT_MISMATCH",
            "任务正文版本不属于任务所在项目，无法执行诊断",
            {"task_id": task.id, "document_version_id": version.id},
        )

    blocks = await _load_blocks(db, version)
    if not blocks:
        raise invalid(
            "DOCUMENT_EMPTY",
            "该版本没有可分析的正文块，无法声称完成全文诊断",
            {"document_version_id": version.id},
        )

    warnings: List[str] = []
    chunks_by_block, chunk_warning = await _chunk_text_by_block(db, task, version)
    if chunk_warning:
        warnings.append(chunk_warning)
    review_blocks, block_warnings = _build_review_blocks(blocks, chunks_by_block)
    warnings.extend(block_warnings)
    if not review_blocks:
        raise invalid(
            "DOCUMENT_EMPTY",
            "该版本没有可分析的正文字块，无法声称完成全文诊断",
            {"document_version_id": version.id},
        )

    max_calls, max_tokens = _accepted_budget(task)
    report_title = title or f"全文诊断报告（v{version.version_no}）"
    expected_ordinals = sorted(int(block.ordinal) for block in review_blocks)
    expected_set = set(expected_ordinals)

    # ── 检查点：只分析剩余块，预算按剩余计算；每窗口成功后落盘 ─────────
    checkpoint = await load_checkpoint_payload(db, task.id)
    checkpoint_version = checkpoint.get("document_version_id")
    if checkpoint_version and checkpoint_version != version.id:
        warnings.append("检查点属于其他文档版本，已忽略（不跨版本复用分析结果）")
        checkpoint = {"analyzed_ordinals": [], "model_calls": 0, "tokens": 0, "findings": []}
    resumed = sorted(
        {ordinal for ordinal in checkpoint.get("analyzed_ordinals") or [] if ordinal in expected_set}
    )
    merged_findings: List[FindingDraft] = []
    seen_finding_keys: set = set()
    if resumed:
        history = checkpoint.get("findings")
        if isinstance(history, list):
            for item in history:
                if not isinstance(item, dict):
                    continue
                draft = _draft_from_payload(item)
                if draft is None:
                    continue
                key = _finding_key(draft)
                if key in seen_finding_keys:
                    continue
                seen_finding_keys.add(key)
                merged_findings.append(draft)
        else:
            warnings.append("检查点来自旧格式（无历史诊断项），仅恢复已分析块的覆盖计数")

    used_calls = int(checkpoint.get("model_calls") or 0) if resumed else 0
    used_tokens = int(checkpoint.get("tokens") or 0) if resumed else 0
    remaining_calls = max(0, max_calls - used_calls)
    remaining_tokens = max(0, max_tokens - used_tokens)

    # 续跑不重置用量（PRD §9）：检查点里已消耗、但尚未落在本次尝试事件中的调用，
    # 先补一条增量事件，否则预算评估会把跨尝试的消耗低估成 0。
    if resumed and (used_calls > 0 or used_tokens > 0):
        try:
            this_attempt = [
                row
                for row in await task_repository.list_events(db, task.id)
                if int(getattr(row, "attempt_no", 0) or 0)
                == int(task.attempt_no or 0)
            ]
            prior = budget.usage_from_events(this_attempt)
            base_calls = max(0, used_calls - prior.model_calls)
            base_tokens = max(0, used_tokens - prior.tokens)
            if base_calls > 0 or base_tokens > 0:
                await task_repository.append_event(
                    db,
                    task,
                    EventType.TASK_PROGRESS.value,
                    payload={
                        "phase": "usage",
                        "usage_mode": "delta",
                        "model_calls": base_calls,
                        "tokens": base_tokens,
                        "source": "review_checkpoint",
                    },
                )
        except Exception:  # noqa: BLE001 - 补记失败不阻断诊断，只降级口径
            warnings.append("续跑用量补记失败（预算评估可能低估已消耗调用）")

    def _merge_drafts(drafts: Iterable[FindingDraft]) -> None:
        for draft in drafts:
            key = _finding_key(draft)
            if key in seen_finding_keys:
                continue
            seen_finding_keys.add(key)
            merged_findings.append(draft)

    # 用量落盘：进度回调携带的是“本次尝试的累计值”（含续跑基数），这里换算成
    # 增量事件，避免续跑时对同一调用重复计数。事件只追加、不推进任务状态。
    usage_state = {"calls": used_calls, "tokens": used_tokens}

    async def _emit_usage(progress: Dict[str, Any]) -> None:
        total_calls = int(progress.get("model_calls") or 0)
        total_tokens = int(progress.get("tokens") or 0)
        prior_calls = usage_state["calls"]
        prior_tokens = usage_state["tokens"]
        delta_calls = max(0, total_calls - prior_calls)
        delta_tokens = max(0, total_tokens - prior_tokens)
        if delta_calls > 0 or delta_tokens > 0:
            await task_repository.append_event(
                db,
                task,
                EventType.TASK_PROGRESS.value,
                payload={
                    "phase": "usage",
                    "usage_mode": "delta",
                    "model_calls": delta_calls,
                    "tokens": delta_tokens,
                    "source": "review_workflow",
                },
            )
        usage_state["calls"] = max(prior_calls, total_calls)
        usage_state["tokens"] = max(prior_tokens, total_tokens)

    async def _on_progress(progress: Dict[str, Any]) -> None:
        _merge_drafts(
            draft
            for draft in (
                _draft_from_payload(item)
                for item in progress.get("findings") or []
                if isinstance(item, dict)
            )
            if draft is not None
        )
        try:
            await _emit_usage(progress)
        except Exception:  # noqa: BLE001 - 记用量失败不能中断诊断
            warnings.append("用量事件写入失败（诊断继续，该窗口用量在预算口径中可能缺失）")
        payload = {
            "document_version_id": version.id,
            "analyzed_ordinals": sorted(set(progress.get("analyzed_ordinals") or []) & expected_set),
            "cursor": int(progress.get("cursor") or 0),
            "model_calls": int(progress.get("model_calls") or 0),
            "tokens": int(progress.get("tokens") or 0),
            "findings": [finding_payload(draft) for draft in merged_findings],
        }
        await save_checkpoint(db, int(task.attempt_no or 0), payload, task_id=task.id)

    pending = expected_set - set(resumed)
    if pending and (remaining_calls <= 0 or remaining_tokens <= 0):
        budget_message = (
            f"任务预算已耗尽（剩余调用 {remaining_calls} 次、剩余 token {remaining_tokens}），"
            f"仍有 {len(pending)} 个块未分析"
        )
        warnings.append(budget_message)
        outcome = _empty_outcome(
            analyzed=resumed,
            expected=expected_ordinals,
            truncated=True,
            message=budget_message,
            calls=used_calls,
            tokens=used_tokens,
        )
    else:
        pipeline = ReviewPipeline(
            client,
            max_calls=max(1, remaining_calls),
            max_tokens=max(1, remaining_tokens),
        )
        request = ReviewRequest(
            document_version_id=version.id,
            blocks=tuple(review_blocks),
            dimensions=tuple(DIMENSIONS),
            objective=(task.objective or "对全文做投稿前诊断"),
            mode=_mode_of(task),
            max_window_codepoints=DEFAULT_WINDOW_CODEPOINTS,
            analyzed_ordinals=tuple(resumed),
            cursor=int(checkpoint.get("cursor") or 0),
            model_calls=used_calls,
            tokens=used_tokens,
        )
        outcome = await pipeline.run(request, on_progress=_on_progress)

    _merge_drafts(outcome.findings)

    # ── 覆盖：只认真正分析过的块，不足即诚实降级 ─────────
    analyzed_set = expected_set & set(outcome.analyzed_ordinals)
    missing = sorted(expected_set - analyzed_set)
    parse_status, status_warning = _parse_status(version.parse_status)
    if status_warning:
        warnings.append(status_warning)

    # 结构性缺失：纯函数只看真实分析范围，不用模型推断补位。
    structural_drafts: List[FindingDraft] = []
    for item in document_level_findings(
        title=report_title,
        blocks=review_blocks,
        analyzed_ordinals=sorted(analyzed_set),
    ):
        draft = _draft_from_payload(item)
        if draft is None:
            continue
        key = _finding_key(draft)
        if key in seen_finding_keys:
            continue
        seen_finding_keys.add(key)
        structural_drafts.append(
            FindingDraft(
                category=draft.category,
                severity=draft.severity,
                problem=draft.problem,
                reason=draft.reason,
                scope="document",
                locator=draft.locator or {"scope": "document"},
                checked_sections=draft.checked_sections,
                verification_method="structural",
            )
        )

    unresolved: List[str] = list(outcome.unresolved_items)
    if missing:
        unresolved.append(f"未分析块（需补充分析）：{missing[:50]}")
    if not analyzed_set:
        unresolved.append("没有可核对的分析范围，不能对全文下质量结论")
    unresolved = list(dict.fromkeys(unresolved))

    unassessed: List[str] = []
    if missing:
        reasons: Dict[int, str] = {}
        for item in outcome.unassessed_objects:
            text = str(item)
            if not text.startswith("block:"):
                continue
            head, _, tail = text.partition("（")
            try:
                ordinal = int(head[len("block:") :])
            except ValueError:
                continue
            reasons[ordinal] = tail[:-1] if tail.endswith("）") else tail
        for ordinal in missing:
            reason = reasons.get(ordinal) or (
                "预算不足，未能分析" if outcome.truncated else "未分析"
            )
            unassessed.append(f"block:{ordinal}（{reason}）")

    section_summary = section_coverage(review_blocks, analyzed_set)
    coverage = Coverage(
        parse_status=parse_status,
        expected_eligible_blocks=len(expected_ordinals),
        analyzed_eligible_blocks=len(analyzed_set),
        unassessed_objects=unassessed,
        pages=version.page_count,
        warnings=list(dict.fromkeys(warnings + list(outcome.warnings))),
    )

    severity_rank = {"critical": 0, "major": 1, "minor": 2}
    final_drafts = list(merged_findings) + structural_drafts
    final_drafts.sort(
        key=lambda draft: (
            severity_rank.get(draft.severity, 3),
            0 if draft.scope == "local" else 1,
            draft.problem,
        )
    )

    coverage_complete = (
        bool(expected_set) and analyzed_set == expected_set and not outcome.truncated
    )
    verdict = _decide_verdict(
        final_drafts,
        coverage_complete=coverage_complete,
        truncated=outcome.truncated,
        missing=missing,
        unresolved=unresolved,
    )
    if verdict == "insufficient_evidence" and not unresolved:
        unresolved.append("证据不足：模型未能给出可核对的分析依据")

    # ── 持久化诊断项（模型 + 结构性，来源可区分）──────────
    finding_rows: List[FindingRow] = []
    for draft in final_drafts:
        row = FindingRow(
            id=new_id("find"),
            task_id=task.id,
            owner_id=task.owner_id,
            version_id=version.id,
            scope=draft.scope,
            category=draft.category,
            severity=draft.severity,
            problem=draft.problem,
            reason=draft.reason or "",
            recommendation=draft.recommendation or "",
            evidence_refs=list(draft.evidence_refs or []),
            locator=dict(draft.locator) if draft.locator else None,
            quote=draft.quote,
            checked_sections=list(draft.checked_sections or []),
            required_user_action=draft.required_user_action,
            verification_method=draft.verification_method or "model",
        )
        db.add(row)
        finding_rows.append(row)
    await db.flush()

    quality_verdict = QualityVerdict(verdict).value
    report = _render_report(
        title=report_title,
        task=task,
        version=version,
        verdict=quality_verdict,
        coverage=coverage,
        findings=finding_rows,
        warnings=coverage.warnings,
        unresolved=unresolved,
        pipeline_version=outcome.pipeline_version,
        prompt_version=outcome.prompt_version,
        section_summary=section_summary,
    )
    artifact = await artifact_service.create_artifact(
        db,
        owner_id=task.owner_id,
        task_id=task.id,
        kind=artifact_kind,
        body=report,
        mime="text/markdown",
        filename=f"review_report_v{version.version_no}.md",
        validation={
            "finding_count": len(finding_rows),
            "model_finding_count": len(merged_findings),
            "structural_finding_count": len(structural_drafts),
            "coverage": coverage.model_dump(mode="json"),
            "section_coverage": section_summary,
            "quality_verdict": quality_verdict,
            "pipeline_version": outcome.pipeline_version,
            "prompt_version": outcome.prompt_version,
            "calls": outcome.calls,
            "output_tokens": outcome.output_tokens,
            "truncated": outcome.truncated,
            "verified_blocks": len(analyzed_set),
            "resumed_blocks": len(resumed),
            "document_version_id": version.id,
            "generated_at": utcnow().isoformat(),
        },
    )

    return {
        "artifact_ids": [artifact.id],
        "artifact_kind": artifact.kind,
        "artifact_version": artifact.version,
        "coverage": coverage.model_dump(mode="json"),
        "quality_verdict": quality_verdict,
        "warnings": coverage.warnings,
        "unresolved_items": list(unresolved),
        "findings": [
            {
                "id": row.id,
                "scope": row.scope,
                "severity": row.severity,
                "category": row.category,
                "problem": row.problem,
                "version_id": row.version_id,
            }
            for row in finding_rows
        ],
        "finding_count": len(finding_rows),
        "model_finding_count": len(merged_findings),
        "structural_finding_count": len(structural_drafts),
        "resumed_blocks": len(resumed),
        "calls": outcome.calls,
        "output_tokens": outcome.output_tokens,
        "pipeline_version": outcome.pipeline_version,
        "prompt_version": outcome.prompt_version,
        "truncated": outcome.truncated,
        "document_version_id": version.id,
    }


__all__ = ["DIAGNOSIS_DISCLAIMER", "run_review"]
