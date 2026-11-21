"""全文诊断流水线（FR-07、FR-10、FR-15）。

职责边界：
- 只接收已经解析好的**全部** eligible 块（``ReviewRequest.blocks``），
  合并为 ≤1200 码点窗口后逐窗诊断；
- 返回 ``ReviewOutcome``：真正的分析块序号、诊断项草稿、覆盖缺口、warning；
- 不读写数据库、不读取全局配置、不发事件（工作流与执行器负责）。

诚实性约束：
- 模型不可用时 ``ModelClient`` 抛 ``unavailable``，本模块**不捕获**；
- 模型输出无法解析时抛 ``ModelOutputError`` / 记为未分析块，
  绝不返回 ``no_major_issues_found`` 掩盖失败；
- 预算耗尽 → ``truncated=True`` 且列出未分析块（转 partial）。
"""
from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ...contracts import DIMENSIONS, normalize_text
from ..base import (
    DEFAULT_MAX_CALLS,
    DEFAULT_MAX_TOKENS,
    MAX_FINDING_PROBLEM,
    MAX_FINDING_QUOTE,
    MAX_FINDING_REASON,
    MAX_FINDING_RECOMMENDATION,
    REVIEW_PROMPT_VERSION,
    BudgetExceeded,
    BudgetTracker,
    EmptyInputError,
    FindingDraft,
    ModelClient,
    ModelOutputError,
    ReviewBlock,
    ReviewOutcome,
    ReviewRequest,
    ReviewWindow,
    as_str_list,
    build_review_windows,
    estimate_tokens,
    parse_json_object,
    truncate_text,
)

#: 单窗最多接受的诊断项（防止畸形输出撑爆结果；不静默截断正文分析）。
MAX_FINDINGS_PER_WINDOW = 40

#: 严重度别名（显式映射，不做猜测式兜底）。
_SEVERITY_ALIASES: Dict[str, str] = {
    "critical": "critical",
    "major": "major",
    "minor": "minor",
    "high": "critical",
    "medium": "major",
    "low": "minor",
}

#: 诊断类别别名 → contracts.DIMENSIONS。
_CATEGORY_ALIASES: Dict[str, str] = {
    "argument": "argument",
    "logic": "argument",
    "structure": "argument",
    "method": "method",
    "methodology": "method",
    "theory": "method",
    "method_fit": "method",
    "evidence": "evidence",
    "citation": "evidence",
    "citations": "evidence",
    "reference": "evidence",
    "references": "evidence",
    "expression": "expression",
    "language": "expression",
    "writing": "expression",
    "style": "expression",
    "format": "format",
    "formatting": "format",
    "layout": "format",
}

#: 模型必须返回的 JSON 顶层结构（用于提示词与校验，不做多字段猜测）。
REVIEW_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["findings"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["category", "severity", "problem"],
                "properties": {
                    "category": {"type": "string", "enum": list(DIMENSIONS)},
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "major", "minor"],
                    },
                    "problem": {"type": "string"},
                    "reason": {"type": "string"},
                    "recommendation": {"type": "string"},
                    "quote": {"type": ["string", "null"]},
                    "checked_sections": {"type": "array", "items": {"type": "string"}},
                    "required_user_action": {"type": "string"},
                },
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}},
        "unresolved": {"type": "array", "items": {"type": "string"}},
    },
}

_REVIEW_SYSTEM_PROMPT = """你是学术论文的严格审稿编辑。请只根据给出的文档原文做诊断，禁止臆造。

硬性规则：
1. 只报告你能在给定文本中直接指出依据的问题；引用必须逐字摘自原文（不要改标点、不要改写）。
2. 不要声称执行了统计检验、实验复现、查重或外部文献核实——你没有这些工具。
3. 不要编造不存在的章节、数据、图表或参考文献。
4. 局部问题给出 quote（原文逐字引用）；只有确实无法定位到具体句子的整体问题才
   省略 quote，并给出 checked_sections（你实际检查过的章节路径）。
5. 按严重度排序：critical（结论不可信/方法不成立）、major（影响说服力）、minor（表达/格式）。
6. 只输出 JSON 对象，不要输出解释文字或 Markdown 围栏。
7. 每个窗口最多给出 6 条诊断，按严重度排序，只保留最需要作者修改的问题；
   输出过长会被截断，宁可少报也不要输出半截 JSON。

JSON 结构：
{"findings":[{"category":"argument|method|evidence|expression|format",
  "severity":"critical|major|minor","problem":"...","reason":"...",
  "recommendation":"...","quote":"原文逐字引用或 null",
  "checked_sections":["章节路径"],"required_user_action":"..."}],
 "notes":["本次检查的范围说明"],"unresolved":["无法判断、需要作者补充的信息"]}
"""

_BLOCK_KIND_LABEL = {
    "paragraph": "段落",
    "heading": "标题",
    "table": "表格",
    "figure": "图注",
    "reference": "参考文献",
}


def finding_payload(item: FindingDraft) -> Dict[str, Any]:
    """把诊断草稿转成检查点可序列化的 dict（与工作流恢复格式一致）。"""
    return {
        "category": item.category,
        "severity": item.severity,
        "problem": item.problem,
        "reason": item.reason,
        "recommendation": item.recommendation,
        "scope": item.scope,
        "quote": item.quote,
        "locator": dict(item.locator) if item.locator else None,
        "evidence_refs": list(item.evidence_refs),
        "checked_sections": list(item.checked_sections),
        "required_user_action": item.required_user_action,
        "block_ordinal": item.block_ordinal,
        "verification_method": item.verification_method,
    }


class ReviewPipeline:
    """全文诊断流水线：逐窗调用注入的 ``ModelClient``，返回可核对的覆盖与诊断。

    用法::

        pipeline = ReviewPipeline(client, max_calls=160, max_tokens=100_000)
        outcome = await pipeline.run(request)
    """

    def __init__(
        self,
        client: ModelClient,
        *,
        max_calls: int = DEFAULT_MAX_CALLS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        if client is None:
            raise ValueError("ReviewPipeline 必须注入 ModelClient 实例")
        self._client = client
        self._max_calls = int(max_calls)
        self._max_tokens = int(max_tokens)

    # ── 入口 ─────────────────────────────────────────────

    async def run(
        self,
        request: ReviewRequest,
        *,
        on_progress: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> ReviewOutcome:
        eligible = request.eligible_blocks()
        if not eligible:
            raise EmptyInputError("没有可诊断的正文块，不能声称已读全文")

        # 块序号升序是“尾部保证”的前提：最后一个块 = 最大 ordinal。
        eligible = tuple(sorted(eligible, key=lambda block: block.ordinal))
        expected = tuple(block.ordinal for block in eligible)
        expected_set = set(expected)

        # 检查点续跑：只信任当前请求里仍存在的块序号，避免旧版本/旧切分的覆盖虚报。
        seed: List[int] = []
        for raw in request.analyzed_ordinals or ():
            try:
                ordinal = int(raw)
            except (TypeError, ValueError):
                continue
            if ordinal in expected_set and ordinal not in seed:
                seed.append(ordinal)
        analyzed: List[int] = list(seed)
        analyzed_set: set[int] = set(seed)
        pending = [block for block in eligible if block.ordinal not in analyzed_set]

        windows = (
            build_review_windows(pending, max_codepoints=request.max_window_codepoints)
            if pending
            else []
        )
        if pending and not windows:
            raise EmptyInputError("没有可诊断的正文块，不能声称已读全文")

        budget = BudgetTracker(
            max_calls=self._max_calls,
            max_tokens=self._max_tokens,
            calls_used=request.model_calls,
            tokens_used=request.tokens,
        )
        findings: List[FindingDraft] = []
        warnings: List[str] = []
        unresolved: List[str] = []
        notes: List[str] = []
        seen: set[Tuple[str, str]] = set()
        truncated = False
        failure_streak = 0
        parse_failures = 0
        last_error: Optional[str] = None
        cursor = max(0, int(request.cursor))

        async def analyze(window: ReviewWindow) -> str:
            """诊断一个窗口；返回 ok/budget/parse_error，模型不可用仍向上抛。"""
            nonlocal truncated, failure_streak, parse_failures, last_error, cursor
            prompt = self._build_prompt(request, window)
            try:
                budget.check(prompt_text=prompt, reserved_output=1024)
            except BudgetExceeded as exc:
                truncated = True
                warnings.append(str(exc))
                unresolved.append(f"预算耗尽，未分析窗口：{window.label}")
                return "budget"

            try:
                raw = await self._client.complete(
                    _REVIEW_SYSTEM_PROMPT, prompt, json_schema=REVIEW_JSON_SCHEMA
                )
            except BudgetExceeded:
                truncated = True
                warnings.append(f"窗口 {window.label} 预算耗尽，未分析")
                unresolved.append(f"预算耗尽，未分析窗口：{window.label}")
                return "budget"
            # 注意：模型不可用（503 unavailable）必须向上抛出，由执行器决定
            # recoverable/failed；这里不吞异常、不伪造“无重大问题”。

            budget.record(prompt_text=prompt, output_text=raw or "")

            try:
                payload = parse_json_object(
                    raw, context=f"窗口 {window.label} 诊断输出"
                )
                window_findings = self._parse_findings(
                    payload, request, window, warnings
                )
            except ModelOutputError as exc:
                failure_streak += 1
                parse_failures += 1
                last_error = str(exc)
                warnings.append(f"窗口 {window.label} 输出无法解析：{exc.message}")
                unresolved.append(
                    f"窗口 {window.label} 未完成诊断（模型输出不合契约）"
                )
                # 连续两个窗口解析失败 → 视为模型/协议级故障，整体失败，
                # 避免“部分乱码输出 + 全部未覆盖”被包装成成功。
                if failure_streak >= 2:
                    raise ModelOutputError(
                        f"连续窗口模型输出无法解析：{last_error}"
                    ) from exc
                return "parse_error"
            failure_streak = 0

            # 只有成功解析的窗口才计入“已分析块”，coverage 不允许虚报。
            analyzed.extend(window.ordinals)
            analyzed_set.update(window.ordinals)
            cursor += 1
            for item in window_findings:
                key = (item.category, normalize_text(item.problem)[:80])
                if key in seen:
                    continue
                seen.add(key)
                findings.append(item)
            notes.extend(as_str_list(payload.get("notes"), limit=20, item_limit=400))
            unresolved.extend(
                as_str_list(payload.get("unresolved"), limit=20, item_limit=400)
            )

            # 每窗口成功后立即回调工作流写检查点；回调失败不中断诊断，
            # 但必须留下 warning（否则会静默失去续跑能力）。
            if on_progress is not None:
                progress = {
                    "analyzed_ordinals": sorted(analyzed_set),
                    "cursor": cursor,
                    "model_calls": budget.calls_used,
                    "tokens": budget.tokens_used,
                    "findings": [finding_payload(item) for item in findings],
                }
                try:
                    result = on_progress(progress)
                    if inspect.isawaitable(result):
                        await result
                except Exception as exc:  # pragma: no cover - 取决于注入的持久化实现
                    warnings.append(f"检查点写入失败（诊断继续）：{exc}")
            return "ok"

        # 尾部保证：先为“最后一个块的单块窗口”预留预算，再逐窗分析。
        tail_window: Optional[ReviewWindow] = None
        tail_estimate = 0
        if windows:
            tail_window = windows[-1]
            tail_prompt = self._build_prompt(request, tail_window)
            tail_estimate = estimate_tokens(tail_prompt) + 1024

        head_windows = windows[:-1] if windows else []
        for index, window in enumerate(head_windows):
            prompt_estimate = (
                estimate_tokens(self._build_prompt(request, window)) + 1024
            )
            if (
                budget.remaining_calls < 2
                or budget.remaining_tokens < prompt_estimate + tail_estimate
            ):
                truncated = True
                warnings.append(
                    "为保留最后一个块（常含结论/声明）的诊断预算，暂缓部分窗口"
                )
                for skipped in head_windows[index:]:
                    unresolved.append(
                        f"为保证尾部块分析，未分析窗口：{skipped.label}"
                    )
                break
            status = await analyze(window)
            if status == "budget":
                for skipped in head_windows[index + 1 :]:
                    unresolved.append(
                        f"为保证尾部块分析，未分析窗口：{skipped.label}"
                    )
                break

        if windows:
            last = windows[-1]
            last_prompt = self._build_prompt(request, last)
            last_estimate = estimate_tokens(last_prompt) + 1024
            if budget.remaining_calls >= 1 and budget.remaining_tokens >= last_estimate:
                await analyze(last)
            elif len(last.blocks) > 1:
                # 整窗放不下时，单独补一个尾部单块窗口；同窗前部块如实记为未分析。
                tail_ordinal = last.blocks[-1].ordinal
                skipped_ordinals = [
                    block.ordinal
                    for block in last.blocks
                    if block.ordinal != tail_ordinal
                ]
                truncated = True
                unresolved.append(
                    "为保留尾部块 "
                    f"{tail_ordinal} 的诊断预算，未分析块：{skipped_ordinals}"
                )
                assert tail_window is not None  # windows 非空时必已赋值
                await analyze(tail_window)
            else:
                await analyze(last)

            # 整窗解析失败时，尾部块仍要用单块窗口补一次（尾部保证）。
            tail_ordinal = last.blocks[-1].ordinal if last.blocks else None
            if (
                tail_ordinal is not None
                and tail_ordinal not in analyzed_set
                and len(last.blocks) > 1
                and budget.remaining_calls >= 1
            ):
                assert tail_window is not None
                await analyze(tail_window)

        # 诊断项排序：严重度优先，其次类别与块序号，保证展示稳定。
        findings.sort(
            key=lambda f: (
                {"critical": 0, "major": 1, "minor": 2}.get(f.severity, 3),
                f.block_ordinal if f.block_ordinal is not None else 10**9,
                f.category,
            )
        )

        analyzed_unique = tuple(sorted(analyzed_set))
        coverage_complete = set(analyzed_unique) == set(expected) and not truncated
        verdict = self._verdict(
            findings, coverage_complete, unresolved, truncated, warnings
        )
        missing = sorted(set(expected) - set(analyzed_unique))
        if missing:
            if truncated:
                reason = "预算不足，未能分析"
            elif parse_failures:
                reason = "模型输出无法解析，未计入覆盖"
            else:
                reason = "未分析"
            unassessed = tuple(f"block:{ordinal}（{reason}）" for ordinal in missing)
            unresolved.append(f"未分析块：{missing[:20]}（{reason}）")
        else:
            unassessed = ()

        # 真实分析范围：只声明确实分析过的块所属章节。
        checked_sections = tuple(
            sorted(
                {
                    block.section_path
                    for block in eligible
                    if block.ordinal in analyzed_set and block.section_path
                }
            )
        )
        for note in notes:
            if note and note not in warnings:
                warnings.append(note)

        return ReviewOutcome(
            verdict=verdict,
            findings=tuple(findings),
            analyzed_ordinals=analyzed_unique,
            expected_ordinals=expected,
            checked_sections=checked_sections,
            unassessed_objects=unassessed,
            warnings=tuple(dict.fromkeys(warnings)),
            unresolved_items=tuple(dict.fromkeys(unresolved)),
            truncated=truncated,
            calls=budget.calls_used,
            output_tokens=budget.tokens_used,
            budget=budget.snapshot(),
            prompt_version=REVIEW_PROMPT_VERSION,
        )

    # ── 提示词 ───────────────────────────────────────────

    def _build_prompt(self, request: ReviewRequest, window: ReviewWindow) -> str:
        dimensions = "、".join(request.dimensions or DIMENSIONS)
        sections = sorted({b.section_path for b in window.blocks if b.section_path})
        section_hint = "；".join(sections) if sections else "（未标注章节）"
        kinds = sorted(
            {
                _BLOCK_KIND_LABEL.get(block.kind or "paragraph", "段落")
                for block in window.blocks
            }
        )
        return (
            f"【任务目标】{request.objective or '对全文做投稿前诊断'}\n"
            f"【诊断维度】{dimensions}\n"
            f"【窗口】{window.label}；涉及章节：{section_hint}\n"
            f"【内容类型】{'、'.join(kinds)}\n"
            f"【待诊断原文】\n{window.text}\n\n"
            "请依据上述原文输出 JSON：每条诊断必须可在上述文本中核对；"
            "quote 必须是原文中逐字出现的片段（否则请置为 null 并给 checked_sections）。"
        )

    # ── 解析与校验 ───────────────────────────────────────

    def _parse_findings(
        self,
        payload: Dict[str, Any],
        request: ReviewRequest,
        window: ReviewWindow,
        warnings: List[str],
    ) -> List[FindingDraft]:
        raw_items = payload.get("findings")
        if raw_items is None:
            return []
        if not isinstance(raw_items, list):
            raise ModelOutputError("findings 必须是数组")

        out: List[FindingDraft] = []
        for raw in raw_items[:MAX_FINDINGS_PER_WINDOW]:
            if not isinstance(raw, dict):
                warnings.append("跳过非对象形式的诊断项")
                continue
            category_raw = truncate_text(raw.get("category"), 64).lower()
            category = _CATEGORY_ALIASES.get(category_raw)
            if category is None:
                warnings.append(f"跳过未知诊断类别：{category_raw or '空'}")
                continue
            severity_raw = truncate_text(raw.get("severity"), 16).lower()
            severity = _SEVERITY_ALIASES.get(severity_raw)
            if severity is None:
                warnings.append(f"跳过未知严重度：{severity_raw or '空'}")
                continue
            problem = truncate_text(raw.get("problem"), MAX_FINDING_PROBLEM)
            if not problem:
                warnings.append("跳过缺少问题描述的诊断项")
                continue
            reason = truncate_text(raw.get("reason"), MAX_FINDING_REASON)
            recommendation = truncate_text(
                raw.get("recommendation"), MAX_FINDING_RECOMMENDATION
            )
            quote = truncate_text(raw.get("quote"), MAX_FINDING_QUOTE) or None
            checked = as_str_list(
                raw.get("checked_sections"), limit=200, item_limit=400
            )
            action = truncate_text(raw.get("required_user_action"), 500) or None

            if quote:
                located = self._locate_quote(quote, window)
                if located is not None:
                    block, start, end = located
                    out.append(
                        FindingDraft(
                            category=category,
                            severity=severity,  # type: ignore[arg-type]
                            problem=problem,
                            reason=reason,
                            recommendation=recommendation,
                            scope="local",
                            quote=quote,
                            locator={
                                "version_id": request.document_version_id,
                                "block_ordinal": block.ordinal,
                                "block_id": block.block_id,
                                "block_start": block.start,
                                "block_end": block.end,
                                "start": start,
                                "end": end,
                                "section_path": block.section_path,
                            },
                            checked_sections=checked or (block.section_path,),
                            required_user_action=action,
                            block_ordinal=block.ordinal,
                        )
                    )
                    continue
                warnings.append(
                    f"跳过无法定位引用的诊断项（引用不在原文中）：{problem[:40]}"
                )
                if not checked:
                    continue
                out.append(
                    FindingDraft(
                        category=category,
                        severity=severity,  # type: ignore[arg-type]
                        problem=problem,
                        reason=reason,
                        recommendation=recommendation,
                        scope="document",
                        quote=None,
                        locator=None,
                        checked_sections=checked,
                        required_user_action=action,
                    )
                )
                continue

            # 整体问题：必须给出检查过的章节集合（contracts.Finding 不变量）。
            if not checked:
                checked = tuple(
                    sorted({b.section_path for b in window.blocks if b.section_path})
                )
            if not checked:
                warnings.append(f"跳过缺少已检查章节的整体问题：{problem[:40]}")
                continue
            out.append(
                FindingDraft(
                    category=category,
                    severity=severity,  # type: ignore[arg-type]
                    problem=problem,
                    reason=reason,
                    recommendation=recommendation,
                    scope="document",
                    quote=None,
                    locator=None,
                    checked_sections=checked,
                    required_user_action=action,
                )
            )
        return out

    @staticmethod
    def _locate_quote(
        quote: str, window: ReviewWindow
    ) -> Optional[Tuple[ReviewBlock, int, int]]:
        """在窗口块内逐字定位引用，返回 (块, 全文起点, 全文终点)。

        定位使用规范化文本的 Unicode 码点偏移；找不到返回 None。
        """
        needle = normalize_text(quote)
        if not needle:
            return None
        for block in window.blocks:
            haystack = normalize_text(block.text)
            index = haystack.find(needle)
            if index >= 0:
                start = block.start + index
                return block, start, start + len(needle)
        return None

    @staticmethod
    def _verdict(
        findings: Sequence[FindingDraft],
        coverage_complete: bool,
        unresolved: Sequence[str],
        truncated: bool,
        warnings: Sequence[str],
    ) -> str:
        """只允许三种结论；覆盖不全时绝不说“无重大问题”。"""
        severe = any(f.severity in ("critical", "major") for f in findings)
        if severe:
            return "issues_found"
        if not coverage_complete or truncated or unresolved:
            return "insufficient_evidence"
        if findings:
            return "issues_found"
        return "no_major_issues_found"


__all__ = [
    "MAX_FINDINGS_PER_WINDOW",
    "REVIEW_JSON_SCHEMA",
    "ReviewPipeline",
    "finding_payload",
]
