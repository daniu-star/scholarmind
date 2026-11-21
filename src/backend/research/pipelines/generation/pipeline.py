"""提纲扩写/草稿生成流水线（FR-10、FR-14、FR-15）。

边界与约束：
- 提纲（``GenerationRequest.outline_sections``）**真实进入**输入，逐节生成，
  不得把整篇全文 + 默认 4096 tokens 当作通用处理；
- 字数按 ``count_visible_words``（CJK 字数 + 英文词数）统计并记录计数器版本
  （``TOKEN_COUNTER_VERSION``），目标字数默认 ±10%；
- 禁止新增未提供的实证结论（``no_new_empirical_claims``）；``protected_terms``
  必须原样保留；
- 截断（预算耗尽）是显式状态：``truncated=True`` 且逐节列出 ``missing``；
- 空输出记 ``empty``，不伪造正文；全部失败时抛 ``ModelOutputError``，
  由执行器落 failed/partial，禁止把空草稿当成功（AT-034）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ...contracts import normalize_text
from ..base import (
    DEFAULT_MAX_CALLS,
    DEFAULT_MAX_TOKENS,
    GENERATION_PROMPT_VERSION,
    TOKEN_COUNTER_VERSION,
    BudgetExceeded,
    BudgetTracker,
    EmptyInputError,
    GeneratedSection,
    GenerationOutcome,
    GenerationRequest,
    ModelClient,
    ModelOutputError,
    OutlineSection,
    as_str_list,
    count_visible_words,
    parse_json_object,
    truncate_text,
    within_target_range,
)

#: 单节输出上限（码点），防止畸形超长输出撑爆存储；超限截断并记 warning。
MAX_SECTION_CODEPOINTS = 20_000

#: 模型必须返回的 JSON 结构：只要正文与未解决项，不做多字段猜测。
GENERATION_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["text"],
    "properties": {
        "text": {"type": "string"},
        "unresolved": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
}

_GENERATION_SYSTEM_PROMPT = """你是中文学术写作助手，按给定提纲逐节撰写论文正文。

硬性规则：
1. 只能使用提纲与任务目标中给出的信息；不得编造数据、实验结果、统计量、
   参考文献、作者或机构。
2. 不得声称做过问卷、访谈、实验、统计检验或文献检索；需要外部材料时，
   用“待补充/需要作者提供”明确标出，并写入 unresolved。
3. 必须保持给定章节标题与顺序，不擅自增加新章节。
4. 保留任务中列出的受保护术语、数字、人名与直接引语原样不变。
5. 正文使用 Markdown 段落；不要输出“以下是……”之类的对话性说明。
6. 只输出 JSON 对象，不要输出解释文字或 Markdown 围栏。

JSON 结构：{"text":"本节正文（Markdown）","unresolved":["需要作者补充的材料"],"warnings":["限制说明"]}
"""


class GenerationPipeline:
    """按提纲逐节生成草稿，返回可核对的结果对象。

    用法::

        pipeline = GenerationPipeline(client)
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
            raise ValueError("GenerationPipeline 必须注入 ModelClient 实例")
        self._client = client
        self._max_calls = int(max_calls)
        self._max_tokens = int(max_tokens)

    async def run(self, request: GenerationRequest) -> GenerationOutcome:
        sections = tuple(request.outline_sections)
        if not sections:
            raise EmptyInputError("缺少提纲，不能生成草稿")

        budget = BudgetTracker(
            max_calls=min(int(request.max_calls), self._max_calls),
            max_tokens=min(int(request.max_tokens), self._max_tokens),
        )
        per_section_target = self._per_section_target(
            request.target_word_count, len(sections)
        )

        generated: List[GeneratedSection] = []
        warnings: List[str] = []
        unresolved: List[str] = []
        body_parts: List[str] = []
        truncated = False
        failure_streak = 0

        for section in sections:
            prompt = self._build_prompt(request, section, per_section_target)
            try:
                budget.check(prompt_text=prompt, reserved_output=1024)
            except BudgetExceeded as exc:
                truncated = True
                warnings.append(str(exc))
                generated.append(
                    GeneratedSection(
                        ordinal=section.ordinal,
                        heading=section.heading,
                        text="",
                        status="missing",
                    )
                )
                unresolved.append(f"预算耗尽，章节未生成：{section.heading}")
                continue
            # 模型不可用（503）不捕获：必须由执行器落 recoverable/failed。

            try:
                raw = await self._client.complete(
                    _GENERATION_SYSTEM_PROMPT, prompt, json_schema=GENERATION_JSON_SCHEMA
                )
            except BudgetExceeded:
                truncated = True
                warnings.append(f"章节 {section.heading} 预算耗尽，未生成")
                generated.append(
                    GeneratedSection(
                        ordinal=section.ordinal,
                        heading=section.heading,
                        text="",
                        status="missing",
                    )
                )
                unresolved.append(f"预算耗尽，章节未生成：{section.heading}")
                continue

            budget.record(prompt_text=prompt, output_text=raw or "")

            try:
                payload = parse_json_object(raw, context=f"章节 {section.heading} 生成输出")
            except ModelOutputError as exc:
                failure_streak += 1
                warnings.append(f"章节 {section.heading} 输出无法解析：{exc.message}")
                generated.append(
                    GeneratedSection(
                        ordinal=section.ordinal,
                        heading=section.heading,
                        text="",
                        status="empty",
                    )
                )
                unresolved.append(f"章节未生成（模型输出不合契约）：{section.heading}")
                if failure_streak >= 2:
                    raise ModelOutputError(
                        f"连续章节模型输出无法解析：{exc.message}"
                    ) from exc
                continue
            failure_streak = 0

            text = truncate_text(payload.get("text"), MAX_SECTION_CODEPOINTS)
            text = normalize_text(text).strip()
            if not text:
                warnings.append(f"章节 {section.heading} 返回空正文")
                unresolved.append(f"章节正文为空：{section.heading}")
                generated.append(
                    GeneratedSection(
                        ordinal=section.ordinal,
                        heading=section.heading,
                        text="",
                        status="empty",
                    )
                )
                continue

            self._check_protected_terms(text, request.protected_terms, section, warnings)
            generated.append(
                GeneratedSection(
                    ordinal=section.ordinal,
                    heading=section.heading,
                    text=text,
                    status="generated",
                )
            )
            heading = section.heading.strip() or f"第{section.ordinal}节"
            body_parts.append(f"## {heading}\n\n{text}")
            unresolved.extend(
                as_str_list(payload.get("unresolved"), limit=20, item_limit=400)
            )
            warnings.extend(
                as_str_list(payload.get("warnings"), limit=20, item_limit=300)
            )

        body = normalize_text("\n\n".join(body_parts)).strip()
        if not body:
            # 空草稿不是成果：抛错让执行器落 failed/partial，绝不“成功但无内容”。
            raise ModelOutputError("草稿正文为空，未生成任何有效章节")

        produced = sum(1 for section in generated if section.status == "generated")
        if produced < len(sections):
            truncated = True
            unresolved.append(
                f"提纲 {len(sections)} 节中仅 {produced} 节生成成功（部分交付）"
            )

        word_count = count_visible_words(body)
        coverage = tuple(
            {
                "ordinal": section.ordinal,
                "heading": section.heading,
                "status": section.status,
            }
            for section in generated
        )
        in_range = within_target_range(word_count, request.target_word_count)
        if request.target_word_count and not in_range:
            warnings.append(
                f"字数 {word_count} 未落在目标 {request.target_word_count} 的 ±10% 区间"
            )

        return GenerationOutcome(
            body=body,
            sections=tuple(generated),
            outline_coverage=coverage,
            word_count=word_count,
            target_word_count=request.target_word_count,
            within_target_range=in_range,
            counter_version=TOKEN_COUNTER_VERSION,
            warnings=tuple(dict.fromkeys(warnings)),
            unresolved_items=tuple(dict.fromkeys(unresolved)),
            calls=budget.calls_used,
            output_tokens=budget.tokens_used,
            truncated=truncated,
            budget=budget.snapshot(),
            prompt_version=GENERATION_PROMPT_VERSION,
        )

    # ── 内部工具 ─────────────────────────────────────────

    @staticmethod
    def _per_section_target(total: Optional[int], count: int) -> Optional[int]:
        if not total or count <= 0:
            return None
        return max(1, int(round(total / count)))

    def _build_prompt(
        self,
        request: GenerationRequest,
        section: OutlineSection,
        per_section_target: Optional[int],
    ) -> str:
        constraints: List[str] = []
        if request.no_new_empirical_claims:
            constraints.append("禁止新增任务未提供的实证结论、数据或统计结果")
        if request.protected_terms:
            constraints.append(
                "必须原样保留以下术语：" + "、".join(request.protected_terms[:40])
            )
        if request.research_type:
            constraints.append(f"研究类型：{request.research_type}")
        if request.journal_style:
            constraints.append(f"目标期刊体例：{request.journal_style}")
        target_hint = (
            f"本节建议 {per_section_target} 字左右（全文目标 {request.target_word_count} 字）"
            if per_section_target
            else "本节长度由内容需要决定"
        )
        return (
            f"【全文目标】{request.objective}\n"
            f"【当前章节】{section.heading}\n"
            f"【章节提纲】\n{section.outline_text}\n\n"
            f"【写作约束】\n- " + "\n- ".join(constraints) + f"\n- {target_hint}\n\n"
            "请只写当前章节正文，输出 JSON："
            '{"text":"...","unresolved":[],"warnings":[]}'
        )

    @staticmethod
    def _check_protected_terms(
        text: str,
        protected_terms: Tuple[str, ...],
        section: OutlineSection,
        warnings: List[str],
    ) -> None:
        """受保护术语缺失要显式披露，不能悄悄丢失（FR-10、AT-024）。"""
        haystack = normalize_text(text)
        missing = [
            term
            for term in (protected_terms or ())
            if term and normalize_text(term) not in haystack
        ]
        if missing:
            warnings.append(
                f"章节 {section.heading} 未包含受保护术语：{missing[:10]}"
            )


__all__ = ["GENERATION_JSON_SCHEMA", "MAX_SECTION_CODEPOINTS", "GenerationPipeline"]
