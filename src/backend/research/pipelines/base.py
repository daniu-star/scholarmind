"""流水线公共契约（FR-10）。

本模块只定义：

- ``ModelClient`` 协议：模型依赖由构造参数显式注入，不经全局 bridge；
- 调用/输出预算（PRD §9：诊断 160 次、单任务 100000 tokens）；
- 两个流水线共享的请求/结果 DTO（frozen dataclass）；
- 模型 JSON 输出的**显式**解析与校验辅助。

硬约束：
- 本包不得导入 ``fastapi``、``sqlalchemy``、``AsyncSession`` 或全局 settings 单例；
- 不读写数据库、不发网络请求（网络只发生在注入的 ``ModelClient`` 内）；
- 模型输出不做“猜测字段兜底”：无法按契约解析时抛 ``ModelOutputError``，
  由上层落成失败/部分结果，绝不当成成功。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Protocol, Sequence, Tuple, runtime_checkable

from ..contracts import DIMENSIONS, normalize_text

#: 诊断维度（与 contracts.DIMENSIONS 一致；此处导出便于流水线独立引用）。
DIMENSION_NAMES: Tuple[str, ...] = tuple(DIMENSIONS)

SeverityName = Literal["critical", "major", "minor"]
FindingScopeName = Literal["local", "document"]
ReviewVerdict = Literal["issues_found", "no_major_issues_found", "insufficient_evidence"]

#: 平台版本标记：写入任务快照，便于恢复时校验执行器/提示词版本（PRD §8.3）。
PIPELINE_VERSION = "r0-pipeline-1.0"
REVIEW_PROMPT_VERSION = "review-prompt-1.1"
GENERATION_PROMPT_VERSION = "generation-prompt-1.0"

#: 预算计数器的版本标记（PRD §9：所有消耗必须可核对）。
TOKEN_COUNTER_VERSION = "sm-tok-v1"

#: 诊断调用上限 / 单任务累计输出预算（PRD §9 默认值）。
DEFAULT_MAX_CALLS = 160
DEFAULT_MAX_TOKENS = 100_000

#: 逐块窗口上限（码点）。分块器保证 800—1200，这里预留提示词与输出预算。
DEFAULT_WINDOW_CODEPOINTS = 1200

#: 输出长度上限（按字符截断仅用于防止单条畸形输出撑爆预算，不静默补足）。
MAX_FINDING_PROBLEM = 4000
MAX_FINDING_REASON = 2000
MAX_FINDING_RECOMMENDATION = 2000
MAX_FINDING_QUOTE = 2000


# ── 异常 ────────────────────────────────────────────────────


class PipelineError(Exception):
    """流水线内部错误基类。``code`` 供上层映射为结构化错误。"""

    code = "PIPELINE_ERROR"

    def __init__(self, message: str, *, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class BudgetExceeded(PipelineError):
    """调用次数或 token 预算耗尽（→ 部分结果，不冒充完整）。"""

    code = "BUDGET_EXCEEDED"


class ModelOutputError(PipelineError):
    """模型输出无法按契约解析/校验（→ 失败，不补字段兜底）。"""

    code = "MODEL_OUTPUT_INVALID"


class EmptyInputError(PipelineError):
    """请求没有可分析内容（→ 失败，不能声称已读全文）。"""

    code = "NO_ELIGIBLE_CONTENT"


# ── 模型客户端协议 ──────────────────────────────────────────


@runtime_checkable
class ModelClient(Protocol):
    """模型最小接口。

    实现方（``runtime.LlmClientAdapter`` / 测试用 FakeClient）只负责
    “给定系统提示与用户提示，返回文本”；流式、重试与熔断属于运行时职责。
    """

    async def complete(
        self,
        system: str,
        user: str,
        *,
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> str:  # pragma: no cover - Protocol
        ...


# ── 预算 ────────────────────────────────────────────────────


def estimate_tokens(text: str) -> int:
    """保守估算 token 数：CJK 按 1 token/字，其他字符按 1 token/4 字符。

    这是**预算保护**用的下界估计，不等同真实计费 token；所有流水线结果
    都带 ``token_counter_version`` 便于核对（PRD §9）。
    """
    if not text:
        return 0
    cjk = 0
    for ch in text:
        if ord(ch) > 0x2E80:
            cjk += 1
    other = len(text) - cjk
    return cjk + max(1, other // 4) if other else cjk


class BudgetTracker:
    """单任务执行期的调用/输出预算跟踪（运行期对象，不是全局状态）。

    每次调用前 ``check()``，调用后 ``record()``；预算耗尽抛
    ``BudgetExceeded``，由流水线转成带未覆盖范围的 partial，而不是继续
    “省略后半篇后宣布完成”。
    """

    def __init__(
        self,
        *,
        max_calls: int = DEFAULT_MAX_CALLS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        calls_used: int = 0,
        tokens_used: int = 0,
    ) -> None:
        if max_calls <= 0 or max_tokens <= 0:
            raise ValueError("预算上限必须为正整数")
        self.max_calls = int(max_calls)
        self.max_tokens = int(max_tokens)
        # 续跑时从检查点恢复累计用量：预算按“剩余”计算，避免重试后重复计费。
        self.calls_used = max(0, int(calls_used))
        self.tokens_used = max(0, int(tokens_used))

    @property
    def remaining_calls(self) -> int:
        return max(0, self.max_calls - self.calls_used)

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.max_tokens - self.tokens_used)

    def check(self, *, prompt_text: str, reserved_output: int = 512) -> None:
        """调用前检查剩余预算；不足则抛 ``BudgetExceeded``。"""
        if self.calls_used + 1 > self.max_calls:
            raise BudgetExceeded(
                f"诊断调用次数超出预算（{self.max_calls} 次）",
                details={"calls_used": self.calls_used, "max_calls": self.max_calls},
            )
        needed = estimate_tokens(prompt_text) + max(1, int(reserved_output))
        if self.tokens_used + needed > self.max_tokens:
            raise BudgetExceeded(
                f"单任务模型输出预算不足（{self.max_tokens} tokens）",
                details={"tokens_used": self.tokens_used, "max_tokens": self.max_tokens},
            )

    def record(self, *, prompt_text: str, output_text: str) -> None:
        self.calls_used += 1
        self.tokens_used += estimate_tokens(prompt_text) + estimate_tokens(output_text)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "max_calls": self.max_calls,
            "max_tokens": self.max_tokens,
            "calls_used": self.calls_used,
            "tokens_used": self.tokens_used,
            "token_counter_version": TOKEN_COUNTER_VERSION,
        }

    def usage(self) -> Dict[str, Any]:
        """本流水线认为已消耗的用量（供预算评估读取）。

        ``cost_usd`` 恒为 ``None``：平台没有调用计价器，费用未知必须如实表达，
        不允许用 0 冒充“免费”。
        """
        return {
            "model_calls": self.calls_used,
            "tokens": self.tokens_used,
            "cost_usd": None,
        }


# ── 诊断流水线 DTO ──────────────────────────────────────────


@dataclass(frozen=True)
class ReviewBlock:
    """待诊断的文档块视图（定位为规范化全文的 Unicode 码点偏移）。"""

    ordinal: int
    block_id: str
    text: str
    start: int
    end: int
    section_path: str = ""
    eligible: bool = True
    # 块类型（paragraph/heading/reference…），只用于结构性检查（如参考文献块）。
    kind: str = "paragraph"


@dataclass(frozen=True)
class ReviewRequest:
    """全文诊断请求。``blocks`` 必须包含**全部** eligible 块（不许 top-k）。"""

    document_version_id: str
    blocks: Tuple[ReviewBlock, ...]
    dimensions: Tuple[str, ...] = DIMENSION_NAMES
    objective: str = ""
    mode: str = "default"
    max_window_codepoints: int = DEFAULT_WINDOW_CODEPOINTS
    preserve_sections: Tuple[str, ...] = ()
    # T15 续跑种子：来自检查点的已分析块、窗口游标与累计用量。默认值保持 R0 行为。
    analyzed_ordinals: Tuple[int, ...] = ()
    cursor: int = 0
    model_calls: int = 0
    tokens: int = 0

    def eligible_blocks(self) -> Tuple[ReviewBlock, ...]:
        return tuple(b for b in self.blocks if b.eligible)


@dataclass(frozen=True)
class FindingDraft:
    """流水线产出的诊断项草稿；持久化由工作流负责。"""

    category: str
    severity: SeverityName
    problem: str
    reason: str = ""
    recommendation: str = ""
    scope: FindingScopeName = "document"
    quote: Optional[str] = None
    locator: Optional[Dict[str, Any]] = None
    evidence_refs: Tuple[str, ...] = ()
    checked_sections: Tuple[str, ...] = ()
    required_user_action: Optional[str] = None
    block_ordinal: Optional[int] = None
    verification_method: str = "model"


@dataclass(frozen=True)
class ReviewOutcome:
    """全文诊断结果。

    ``analyzed_ordinals`` 是**实际分析过**的块序号；工作流据此计算 coverage，
    不允许用“调用了模型”代替“读完了全文”。
    """

    verdict: ReviewVerdict
    findings: Tuple[FindingDraft, ...]
    analyzed_ordinals: Tuple[int, ...]
    expected_ordinals: Tuple[int, ...]
    checked_sections: Tuple[str, ...]
    unassessed_objects: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    unresolved_items: Tuple[str, ...] = ()
    truncated: bool = False
    calls: int = 0
    output_tokens: int = 0
    budget: Dict[str, Any] = field(default_factory=dict)
    pipeline_version: str = PIPELINE_VERSION
    prompt_version: str = REVIEW_PROMPT_VERSION

    @property
    def coverage_complete(self) -> bool:
        return (
            not self.truncated
            and len(self.expected_ordinals) > 0
            and set(self.analyzed_ordinals) == set(self.expected_ordinals)
        )


@dataclass(frozen=True)
class ReviewWindow:
    """一个 1200 码点内的诊断窗口。"""

    label: str
    text: str
    blocks: Tuple[ReviewBlock, ...]

    @property
    def ordinals(self) -> Tuple[int, ...]:
        return tuple(b.ordinal for b in self.blocks)


# ── 生成流水线 DTO ──────────────────────────────────────────


@dataclass(frozen=True)
class OutlineSection:
    """提纲中的一个章节。``ordinal`` 为提纲内顺序，用于结果对应关系。"""

    ordinal: int
    heading: str
    outline_text: str


@dataclass(frozen=True)
class GenerationRequest:
    """按提纲起草请求：提纲真实进入输入，目标字数不得被静默忽略。"""

    objective: str
    outline_sections: Tuple[OutlineSection, ...]
    outline_version_id: str = ""
    target_word_count: Optional[int] = None
    research_type: str = ""
    journal_style: str = "generic"
    no_new_empirical_claims: bool = True
    protected_terms: Tuple[str, ...] = ()
    max_calls: int = DEFAULT_MAX_CALLS
    max_tokens: int = DEFAULT_MAX_TOKENS


@dataclass(frozen=True)
class GeneratedSection:
    ordinal: int
    heading: str
    text: str
    status: Literal["generated", "empty", "missing"]


@dataclass(frozen=True)
class GenerationOutcome:
    body: str
    sections: Tuple[GeneratedSection, ...]
    outline_coverage: Tuple[Dict[str, Any], ...]
    word_count: int
    target_word_count: Optional[int]
    within_target_range: bool
    counter_version: str
    warnings: Tuple[str, ...] = ()
    unresolved_items: Tuple[str, ...] = ()
    calls: int = 0
    output_tokens: int = 0
    truncated: bool = False
    budget: Dict[str, Any] = field(default_factory=dict)
    pipeline_version: str = PIPELINE_VERSION
    prompt_version: str = GENERATION_PROMPT_VERSION


# ── 文本与字数工具 ──────────────────────────────────────────

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]*")


def count_visible_words(text: str) -> int:
    """按 PRD FR-10 统计可见正文：CJK 字符数 + 英文词数。

    记录计数器版本 ``sm-wc-v1``；不把空白、标点计入。
    """
    cjk = len(_CJK_RE.findall(text))
    latin = len(_LATIN_WORD_RE.findall(text))
    return cjk + latin


def within_target_range(word_count: int, target: Optional[int]) -> bool:
    """目标 ±10%（PRD FR-10）。没有目标时视为满足。"""
    if target is None:
        return True
    if target <= 0:
        return False
    return int(target * 0.9) <= word_count <= int(target * 1.1)


# ── 模型 JSON 输出的显式解析 ────────────────────────────────

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json_object(raw: str, *, context: str = "模型输出") -> Dict[str, Any]:
    """把模型返回的文本解析为 JSON 对象。

    只接受“纯 JSON”或“单个 ```json 围栏”；不做多字段猜测与兜底。
    解析失败抛 ``ModelOutputError``（上层据此失败，不伪造成功）。
    """
    if raw is None:
        raise ModelOutputError(f"{context}为空")
    text = raw.strip()
    if not text:
        raise ModelOutputError(f"{context}为空")
    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    if not (text.startswith("{") and text.endswith("}")):
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ModelOutputError(f"{context}不是 JSON 对象")
        text = text[start : end + 1]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        # 模型常在字符串值里输出裸换行/制表符（严格 JSON 禁止控制字符）。
        # 用 strict=False 再解析一次；仍失败才算“输出不合契约”，绝不伪造成功。
        try:
            payload = json.loads(text, strict=False)
        except json.JSONDecodeError:
            raise ModelOutputError(f"{context}不是合法 JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ModelOutputError(f"{context}必须是 JSON 对象")
    return payload


def truncate_text(value: Any, limit: int) -> str:
    """把可选值转为不超过 ``limit`` 个码点的文本（空值返回 ""）。"""
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    text = normalize_text(text).strip()
    if len(text) > limit:
        return text[:limit]
    return text


def as_str_list(value: Any, *, limit: int = 100, item_limit: int = 200) -> Tuple[str, ...]:
    """把模型返回的列表字段规范成去重字符串元组；非列表返回空元组。"""
    if not isinstance(value, (list, tuple)):
        return ()
    out: List[str] = []
    for item in value:
        text = truncate_text(item, item_limit)
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return tuple(out)


# ── 章节与窗口 ──────────────────────────────────────────────


def build_review_windows(
    blocks: Sequence[ReviewBlock],
    *,
    max_codepoints: int = DEFAULT_WINDOW_CODEPOINTS,
) -> List[ReviewWindow]:
    """把 eligible 块合并为 ≤ ``max_codepoints`` 的窗口。

    单块本身超限时独立成窗（分块器保证 ≤1200，修订重建的块可能更长），
    不丢弃任何块——丢弃会让 coverage 变成谎报。
    """
    windows: List[ReviewWindow] = []
    current: List[ReviewBlock] = []
    size = 0
    max_cp = max(200, int(max_codepoints))

    def flush() -> None:
        nonlocal current, size
        if not current:
            return
        label = (
            f"块{current[0].ordinal}"
            if len(current) == 1
            else f"块{current[0].ordinal}-{current[-1].ordinal}"
        )
        text = "\n".join(
            f"[块 {b.ordinal}] {normalize_text(b.text)}" for b in current
        )
        windows.append(ReviewWindow(label=label, text=text, blocks=tuple(current)))
        current = []
        size = 0

    for block in blocks:
        if not block.eligible:
            continue
        piece_len = len(normalize_text(block.text)) + 8
        if current and size + piece_len > max_cp:
            flush()
        current.append(block)
        size += piece_len
    flush()
    return windows


_HEADING_LINE_RE = re.compile(
    r"^\s*(?:#{1,6}\s+|第[一二三四五六七八九十百零〇\d]+[章节部分]\s*|"
    r"[一二三四五六七八九十]+[、.．]\s*|\d{1,2}[、.．)]\s*)"
)


def split_outline(outline_text: str) -> List[OutlineSection]:
    """把提纲文本切分为章节。

    识别 Markdown 标题、``第X章/节``、``一、``、``1.`` 等常见提纲行；
    没有任何可识别标题时整篇作为单章节（不丢提纲内容）。
    """
    text = normalize_text(outline_text or "").strip()
    if not text:
        return []
    sections: List[Tuple[str, List[str]]] = []
    preamble: List[str] = []
    for line in text.splitlines():
        if _HEADING_LINE_RE.match(line) and line.strip():
            if sections:
                sections.append((line.strip(), []))
            else:
                if preamble:
                    sections.append((preamble[0].strip(), preamble[1:]))
                sections.append((line.strip(), []))
        elif sections:
            sections[-1][1].append(line)
        else:
            preamble.append(line)
    if not sections:
        first = preamble[0].strip() if preamble else "正文"
        return [OutlineSection(ordinal=1, heading=first[:120], outline_text=text)]
    return [
        OutlineSection(
            ordinal=index + 1,
            heading=heading[:200],
            outline_text="\n".join([heading, *body]).strip(),
        )
        for index, (heading, body) in enumerate(sections)
    ]


__all__ = [
    "BudgetExceeded",
    "BudgetTracker",
    "DIMENSION_NAMES",
    "DEFAULT_MAX_CALLS",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_WINDOW_CODEPOINTS",
    "EmptyInputError",
    "FindingDraft",
    "FindingScopeName",
    "GeneratedSection",
    "GenerationOutcome",
    "GenerationRequest",
    "ModelClient",
    "ModelOutputError",
    "OutlineSection",
    "PIPELINE_VERSION",
    "PipelineError",
    "REVIEW_PROMPT_VERSION",
    "GENERATION_PROMPT_VERSION",
    "ReviewBlock",
    "ReviewOutcome",
    "ReviewRequest",
    "ReviewVerdict",
    "ReviewWindow",
    "SeverityName",
    "TOKEN_COUNTER_VERSION",
    "as_str_list",
    "build_review_windows",
    "count_visible_words",
    "estimate_tokens",
    "parse_json_object",
    "split_outline",
    "truncate_text",
    "within_target_range",
]
