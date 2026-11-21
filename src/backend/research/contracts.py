"""ScholarMind 研究领域契约（PRD v1.0 §8.2 / §8.3 / §6）。

本模块是 TaskInput / TaskResult / 覆盖、诊断项、事件与错误码的唯一导出位置。
只定义跨层 DTO 与不变量，不包含 I/O 与业务编排。

约定：
- 版本化 schema（``SCHEMA_VERSION``），未知受保护字段一律拒绝；
- 所有文本按 NFC 规范化；定位使用规范化文本的 Unicode 码点偏移；
- 客户端不能提供 owner、实际模型、结算状态或服务器路径。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"


# ── 枚举 ────────────────────────────────────────────────────


class TaskKind(str, Enum):
    REVIEW = "review"
    REVISION = "revision"
    DRAFT_FROM_OUTLINE = "draft_from_outline"
    LITERATURE_REVIEW = "literature_review"
    CHART = "chart"
    EXPORT = "export"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    NEEDS_INPUT = "needs_input"
    RECOVERABLE = "recoverable"
    PARTIAL = "partial"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset(
    {TaskStatus.PARTIAL, TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}
)

#: 允许的状态迁移（PRD §7.1）。终态不可原地回到 running。
ALLOWED_TRANSITIONS: Dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.QUEUED: frozenset(
        {TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.NEEDS_INPUT,
            TaskStatus.RECOVERABLE,
            TaskStatus.PARTIAL,
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.NEEDS_INPUT: frozenset(
        {
            TaskStatus.QUEUED,
            TaskStatus.PARTIAL,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.RECOVERABLE: frozenset(
        {
            TaskStatus.QUEUED,
            TaskStatus.PARTIAL,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.PARTIAL: frozenset(),
    TaskStatus.SUCCEEDED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    """判断状态迁移是否合法；相同状态不视为迁移。"""
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


class QualityVerdict(str, Enum):
    ISSUES_FOUND = "issues_found"
    NO_MAJOR_ISSUES_FOUND = "no_major_issues_found"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


#: 需要质量结论的任务（纯图表/导出等为 None，不强行计算论文质量分）。
QUALITY_VERDICT_KINDS = frozenset(
    {TaskKind.REVIEW, TaskKind.REVISION, TaskKind.LITERATURE_REVIEW}
)


class ParseStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class Severity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class FindingScope(str, Enum):
    LOCAL = "local"
    DOCUMENT = "document"


class MetadataStatus(str, Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    USER_SUPPLIED = "user_supplied"


class MaterialLevel(str, Enum):
    METADATA = "metadata"
    ABSTRACT = "abstract"
    FULL_TEXT = "full_text"


class SupportStatus(str, Enum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient"
    UNASSESSED = "unassessed"


class VerificationMethod(str, Enum):
    TOOL = "tool"
    MODEL = "model"
    HUMAN = "human"
    NONE = "none"


class BillingState(str, Enum):
    RESERVED = "reserved"
    SETTLED = "settled"
    RELEASED = "released"
    HELD = "held"


class CapabilityStatus(str, Enum):
    READY = "ready"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    UNAUTHORIZED = "unauthorized"
    UNKNOWN = "unknown"


class EventType(str, Enum):
    TASK_ACCEPTED = "task.accepted"
    TASK_STARTED = "task.started"
    TASK_PROGRESS = "task.progress"
    TASK_NEEDS_INPUT = "task.needs_input"
    TASK_RECOVERABLE = "task.recoverable"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    ARTIFACT_CREATED = "artifact.created"
    TASK_COMPLETED = "task.completed"
    TASK_PARTIAL = "task.partial"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"


#: 事件类型 → 对应任务状态（终态事件）。
EVENT_TERMINAL_STATUS: Dict[EventType, TaskStatus] = {
    EventType.TASK_COMPLETED: TaskStatus.SUCCEEDED,
    EventType.TASK_PARTIAL: TaskStatus.PARTIAL,
    EventType.TASK_FAILED: TaskStatus.FAILED,
    EventType.TASK_CANCELLED: TaskStatus.CANCELLED,
}

DIMENSIONS = ("argument", "method", "evidence", "expression", "format")
PRESERVE_DEFAULTS = ("numbers", "dates", "names", "direct_quotes", "citations")
SUPPORTED_JOURNAL_STYLES = frozenset({"generic"})
SUPPORTED_EXPORT_FORMATS = frozenset({"md", "docx"})
MAX_SKILL_IDS = 8
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_PAGES = 200
MAX_CODEPOINTS = 200_000
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


# ── 基础工具 ────────────────────────────────────────────────


def utcnow() -> datetime:
    """UTC 当前时间（naive，与 PostgreSQL TIMESTAMP WITHOUT TIME ZONE 一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_text(text: str) -> str:
    """按 NFC 规范化研究文本（PRD §6）。"""
    return unicodedata.normalize("NFC", text)


def text_hash(text: str) -> str:
    """规范化文本的 SHA-256（十六进制）。"""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def content_hash(data: bytes | str) -> str:
    payload = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(payload).hexdigest()


def new_id(prefix: str) -> str:
    """服务端生成的不可预测标识，带可读前缀便于排查。"""
    return f"{prefix}_{uuid.uuid4().hex}"


def validate_idempotency_key(key: str) -> str:
    if not isinstance(key, str) or not IDEMPOTENCY_KEY_RE.match(key):
        raise ValueError("Idempotency-Key 必须是 8—128 个允许的 ASCII 字符")
    return key


# ── 认证主体 ────────────────────────────────────────────────


@dataclass(frozen=True)
class Actor:
    """认证主体。只能由认证层构建；请求体里的 user_id/owner_id 不产生授权。"""

    user_id: int

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, int) or self.user_id <= 0:
            raise ValueError("Actor.user_id 必须是正整数")


@dataclass(frozen=True)
class DocumentRef:
    id: str
    version_id: str
    owner_id: int
    project_id: str


# ── 任务输入 ────────────────────────────────────────────────


class TaskInputRefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_version_id: str = Field(min_length=1, max_length=128)
    outline_document_version_id: Optional[str] = Field(default=None, max_length=128)
    reviewer_comments_document_version_id: Optional[str] = Field(
        default=None, max_length=128
    )
    source_ids: List[str] = Field(default_factory=list, max_length=200)


class TaskScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_ids: List[str] = Field(default_factory=list, max_length=500)
    dimensions: List[str] = Field(default_factory=lambda: list(DIMENSIONS))
    finding_ids: List[str] = Field(default_factory=list, max_length=500)

    @field_validator("dimensions")
    @classmethod
    def _validate_dimensions(cls, value: List[str]) -> List[str]:
        if not value:
            raise ValueError("dimensions 不能为空")
        unknown = [d for d in value if d not in DIMENSIONS]
        if unknown:
            raise ValueError(f"未知诊断维度: {unknown}")
        return list(dict.fromkeys(value))


class TaskConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protected_block_ids: List[str] = Field(default_factory=list, max_length=2000)
    preserve: List[str] = Field(default_factory=lambda: list(PRESERVE_DEFAULTS))
    target_word_count: Optional[int] = Field(default=None, ge=1, le=1_000_000)
    journal_style: str = Field(default="generic", max_length=64)
    no_new_empirical_claims: bool = True
    # 诊断流程：single=单遍通用审稿；multi_role=通用审稿 + 方法/证据核查员两遍全文，
    # 结果按（引文，问题）去重合并。默认 single，保持既有行为不变。
    review_mode: str = Field(default="single", max_length=32)

    @field_validator("review_mode")
    @classmethod
    def _validate_review_mode(cls, value: str) -> str:
        normalized = str(value or "single").strip().lower()
        if normalized not in {"single", "multi_role"}:
            raise ValueError(f"未知诊断流程: {value!r}（只支持 single / multi_role）")
        return normalized

    @field_validator("preserve")
    @classmethod
    def _validate_preserve(cls, value: List[str]) -> List[str]:
        allowed = {"numbers", "dates", "names", "direct_quotes", "citations"}
        unknown = [v for v in value if v not in allowed]
        if unknown:
            raise ValueError(f"未知保护类别: {unknown}")
        return list(dict.fromkeys(value))


class ResearchTaskInput(BaseModel):
    """规范 TaskInput v1（PRD §8.2）。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    project_id: str = Field(min_length=1, max_length=128)
    kind: TaskKind
    objective: str = Field(min_length=1, max_length=4000)
    input: TaskInputRefs
    scope: TaskScope = Field(default_factory=TaskScope)
    constraints: TaskConstraints = Field(default_factory=TaskConstraints)
    mode: Optional[Literal["flash", "pro"]] = None
    skill_ids: List[str] = Field(default_factory=list, max_length=MAX_SKILL_IDS)

    @field_validator("objective")
    @classmethod
    def _strip_objective(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("objective 不能为空")
        return value

    @field_validator("skill_ids")
    @classmethod
    def _unique_skills(cls, value: List[str]) -> List[str]:
        if len(set(value)) != len(value):
            raise ValueError("skill_ids 不能重复")
        return value

    @model_validator(mode="after")
    def _kind_rules(self) -> "ResearchTaskInput":
        if self.kind is TaskKind.REVISION:
            if not self.scope.finding_ids and not self.scope.section_ids:
                raise ValueError("revision 必须提供 finding_ids 或明确的 section_ids")
        if self.constraints.target_word_count is not None and self.kind not in {
            TaskKind.DRAFT_FROM_OUTLINE,
            TaskKind.REVISION,
        }:
            raise ValueError("target_word_count 仅对起草或明确长度修改生效")
        if self.kind is TaskKind.DRAFT_FROM_OUTLINE:
            if not self.input.outline_document_version_id:
                raise ValueError("draft_from_outline 必须提供提纲版本")
        return self


class ResumeInput(BaseModel):
    """resume 补充输入（PRD §8.2）。"""

    model_config = ConfigDict(extra="forbid")

    expected_state_revision: int = Field(ge=1)
    answers: Dict[str, str] = Field(default_factory=dict)
    supplemental_source_ids: List[str] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def _limit_answers(self) -> "ResumeInput":
        total = sum(len(v) for v in self.answers.values())
        if total > 50_000:
            raise ValueError("answers 总长度不能超过 50000 个码点")
        return self


# ── 覆盖与成果 ──────────────────────────────────────────────


class Coverage(BaseModel):
    """解析状态与全文分析覆盖是两项独立数据（PRD §4.1、FR-04）。"""

    model_config = ConfigDict(extra="forbid")

    parse_status: ParseStatus = ParseStatus.COMPLETE
    expected_eligible_blocks: int = Field(default=0, ge=0)
    analyzed_eligible_blocks: int = Field(default=0, ge=0)
    unassessed_objects: List[str] = Field(default_factory=list)
    pages: Optional[int] = Field(default=None, ge=0)
    warnings: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent_ratio(self) -> "Coverage":
        if self.analyzed_eligible_blocks > self.expected_eligible_blocks:
            raise ValueError("已分析块不能超过预期块")
        return self

    @property
    def analysis_ratio(self) -> float:
        if self.expected_eligible_blocks == 0:
            return 1.0 if self.parse_status is ParseStatus.COMPLETE else 0.0
        return self.analyzed_eligible_blocks / self.expected_eligible_blocks

    @property
    def full_coverage(self) -> bool:
        return (
            self.parse_status in {ParseStatus.COMPLETE, ParseStatus.PARTIAL}
            and self.expected_eligible_blocks > 0
            and self.analysis_ratio == 1.0
        )


class TaskResult(BaseModel):
    """规范 Result v1（PRD §8.3）。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    task_id: str
    status: TaskStatus
    artifact_ids: List[str] = Field(default_factory=list)
    coverage: Optional[Coverage] = None
    quality_verdict: Optional[QualityVerdict] = None
    warnings: List[str] = Field(default_factory=list)
    unresolved_items: List[str] = Field(default_factory=list)
    billing_state: Optional[BillingState] = None

    @model_validator(mode="after")
    def _verdict_rules(self) -> "TaskResult":
        if self.status is not TaskStatus.SUCCEEDED and self.quality_verdict is not None:
            raise ValueError("仅 succeeded 任务可携带质量结论")
        if (
            self.quality_verdict is QualityVerdict.INSUFFICIENT_EVIDENCE
            and not self.unresolved_items
        ):
            raise ValueError("insufficient_evidence 必须列出缺失项")
        return self


class Finding(BaseModel):
    """有依据的诊断项（PRD FR-07）。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    version_id: str = Field(min_length=1, max_length=128)
    scope: FindingScope
    category: str = Field(min_length=1, max_length=64)
    severity: Severity
    problem: str = Field(min_length=1, max_length=4000)
    reason: str = Field(default="", max_length=4000)
    recommendation: str = Field(default="", max_length=4000)
    evidence_refs: List[str] = Field(default_factory=list, max_length=100)
    locator: Optional[Dict[str, Any]] = None
    quote: Optional[str] = Field(default=None, max_length=2000)
    checked_sections: List[str] = Field(default_factory=list, max_length=500)
    required_user_action: Optional[str] = Field(default=None, max_length=500)
    verification_method: VerificationMethod = VerificationMethod.MODEL

    @model_validator(mode="after")
    def _anchor_rules(self) -> "Finding":
        if self.scope is FindingScope.LOCAL:
            if not self.locator:
                raise ValueError("局部问题必须有版本内定位")
            if not self.quote or not self.quote.strip():
                raise ValueError("局部问题必须有原文引用")
        else:
            if not self.checked_sections:
                raise ValueError("整体问题必须给出已检查章节集合")
        return self


class RevisionHunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    finding_id: str = Field(min_length=1, max_length=128)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    original_text: str
    original_hash: str = Field(min_length=64, max_length=64)
    replacement_text: str
    reason: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _range_rules(self) -> "RevisionHunk":
        if self.end < self.start:
            raise ValueError("补丁区间 end 不能小于 start")
        if self.original_hash != text_hash(self.original_text):
            raise ValueError("补丁原文哈希与原文不一致")
        return self


class RevisionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    task_id: str
    base_version_id: str
    selected_findings: List[str] = Field(default_factory=list, max_length=500)
    hunks: List[RevisionHunk] = Field(default_factory=list)
    validation_report: Dict[str, Any] = Field(default_factory=dict)
    status: str = "proposed"


class ApplyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    document_id: str
    new_version_id: str
    applied_hunk_ids: List[str]
    change_log_artifact_id: Optional[str] = None
    state_revision: int = Field(ge=1)


# ── 任务快照、事件、成果引用与错误 ──────────────────────────


class TaskSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    owner_id: int
    project_id: str
    kind: TaskKind
    status: TaskStatus
    objective: str
    state_revision: int = Field(ge=1)
    billing_group_id: str
    billing_state: Optional[BillingState] = None
    attempt_no: int = Field(default=0, ge=0)
    snapshot_summary: Dict[str, Any] = Field(default_factory=dict)
    coverage: Optional[Coverage] = None
    quality_verdict: Optional[QualityVerdict] = None
    artifact_ids: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    unresolved_items: List[str] = Field(default_factory=list)
    retry_of: Optional[str] = None
    can_resume: bool = False
    can_retry: bool = False
    error: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    ended_at: Optional[datetime] = None


class TaskEventDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    task_id: str
    sequence: int = Field(ge=1)
    attempt_no: int = Field(ge=0)
    created_at: datetime
    type: EventType
    payload: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _payload_rules(self) -> "TaskEventDTO":
        if self.type is EventType.TOOL_COMPLETED:
            if not (self.payload.get("artifact_id") or self.payload.get("evidence_id")):
                raise ValueError("tool.completed 必须携带持久化 artifact/evidence ID")
        if self.type is EventType.TASK_COMPLETED and not self.payload.get("artifact_ids"):
            raise ValueError("task.completed 必须引用成果 ID")
        return self


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    owner_id: int
    task_id: str
    kind: str
    version: int = Field(default=1, ge=1)
    content_hash: str
    mime: str
    filename: str
    size_bytes: int = Field(ge=0)
    validation: Dict[str, Any] = Field(default_factory=dict)
    downloadable: bool = True


class ResearchError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    retryable: bool = False
    request_id: Optional[str] = None
    task_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class TaskAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    status: TaskStatus = TaskStatus.QUEUED
    state_revision: int = Field(default=1, ge=1)
    billing_state: BillingState = BillingState.RESERVED
    snapshot_summary: Dict[str, Any] = Field(default_factory=dict)


# ── 能力描述（FR-01） ───────────────────────────────────────


class CapabilityInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: CapabilityStatus
    checked_at: datetime
    reason: str = ""
    granularity: str = ""
    detail: Dict[str, Any] = Field(default_factory=dict)


class CapabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    user_id: int
    capabilities: List[CapabilityInfo]
    disclaimer: str = (
        "能力状态来自服务端实际检查；来源可查询不等于有全文权限；"
        "研究结论不构成发表保证。"
    )


#: 最小交付检查所需的成果种类（PRD §7.2）。
REQUIRED_ARTIFACT_KINDS: Dict[TaskKind, frozenset[str]] = {
    TaskKind.REVIEW: frozenset({"review_report"}),
    TaskKind.REVISION: frozenset({"revision_proposal"}),
    TaskKind.DRAFT_FROM_OUTLINE: frozenset({"draft"}),
    TaskKind.LITERATURE_REVIEW: frozenset({"literature_review"}),
    TaskKind.CHART: frozenset({"chart"}),
    TaskKind.EXPORT: frozenset({"export"}),
}


def completion_errors(
    kind: TaskKind,
    result: TaskResult,
    artifact_kinds: Optional[set[str]] = None,
) -> List[str]:
    """基于 kind 的最小交付检查（PRD §7.2、§8.3、FR-15）。

    只检查“是否有可读取的必需成果、范围是否覆盖、结构是否自洽”，
    不判断论文质量。返回空列表才允许 succeeded。
    """
    errors: List[str] = []
    if result.status is not TaskStatus.SUCCEEDED:
        return errors

    required = REQUIRED_ARTIFACT_KINDS.get(kind, frozenset())
    available = artifact_kinds or set()
    if required and not required.intersection(available):
        errors.append(f"{kind.value} 任务缺少必需成果: {sorted(required)}")

    if kind is TaskKind.REVIEW:
        coverage = result.coverage
        if coverage is None:
            errors.append("全文诊断缺少覆盖记录")
        elif coverage.expected_eligible_blocks <= 0:
            errors.append("全文诊断的预期块为 0，不能证明已读全文")
        elif coverage.analysis_ratio != 1.0:
            errors.append(
                f"全文诊断覆盖不足: {coverage.analyzed_eligible_blocks}/"
                f"{coverage.expected_eligible_blocks}"
            )
        if result.quality_verdict is None:
            errors.append("诊断任务缺少质量结论")

    if kind in QUALITY_VERDICT_KINDS and result.quality_verdict is None:
        errors.append(f"{kind.value} 任务缺少质量结论")

    return errors
