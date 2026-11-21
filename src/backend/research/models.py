"""研究领域 ORM 模型（PRD v1.0 §6）。

SQLAlchemy 2.0 异步 ORM；与现有 ``models/orm.py`` 保持同一风格：
- 主键使用服务端生成的字符串（``*_<uuid4hex>``），不使用自增 ID；
- 时间统一 UTC naive；
- 文本在写入前按 NFC 规范化（由服务层负责，模型只负责存储）；
- 不存客户端可控的 owner/结算/路径字段的“信任值”。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Project(Base):
    __tablename__ = "research_projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (Index("idx_research_projects_owner", "owner_id", "created_at"),)


class Document(Base):
    __tablename__ = "research_documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("research_projects.id"), nullable=False, index=True
    )
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    mime: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    current_version_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        Index("idx_research_documents_project", "project_id", "created_at"),
    )


class DocumentVersion(Base):
    __tablename__ = "research_document_versions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("research_documents.id"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    codepoints: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parse_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="complete"
    )
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="upload")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("document_id", "version_no", name="uq_doc_version_no"),
    )


class DocumentBlock(Base):
    __tablename__ = "research_document_blocks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("research_document_versions.id"),
        nullable=False, index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="paragraph")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    start: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    section_path: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("version_id", "ordinal", name="uq_block_version_ordinal"),
    )


class DocumentChunk(Base):
    __tablename__ = "research_document_chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("research_document_versions.id"),
        nullable=False, index=True,
    )
    block_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("research_document_blocks.id"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("version_id", "ordinal", name="uq_chunk_version_ordinal"),
    )


class SourceRecord(Base):
    __tablename__ = "research_source_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    authors: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    doi: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(800), nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    metadata_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="unresolved"
    )
    material_level: Mapped[str] = mapped_column(
        String(24), nullable=False, default="metadata"
    )
    license: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow
    )


class Evidence(Base):
    __tablename__ = "research_evidences"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("research_source_records.id"), nullable=False
    )
    locator: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    quote: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="resolved"
    )
    material_level: Mapped[str] = mapped_column(
        String(24), nullable=False, default="metadata"
    )
    support_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="unassessed"
    )
    verification_method: Mapped[str] = mapped_column(
        String(24), nullable=False, default="none"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class ResearchTask(Base):
    __tablename__ = "research_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scope_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    constraints_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    state_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    billing_group_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    billing_state: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    coverage_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    quality_verdict: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    retry_of: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, index=True
    )
    request_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "owner_id", "idempotency_key", name="uq_task_owner_idempotency"
        ),
        Index("idx_research_tasks_owner_status", "owner_id", "status"),
        Index("idx_research_tasks_project", "project_id", "created_at"),
    )


class TaskAttempt(Base):
    __tablename__ = "research_task_attempts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("research_tasks.id"), nullable=False, index=True
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    lease_holder: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # T15：逐分析单元的检查点（已分析块序号、窗口游标、累计模型调用/令牌）。
    # 重试时从检查点继续，避免"读了一半又从零开始"导致重复计费与覆盖虚报。
    checkpoint_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("task_id", "attempt_no", name="uq_attempt_task_no"),
    )


class TaskEvent(Base):
    __tablename__ = "research_task_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("research_tasks.id"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("task_id", "sequence", name="uq_event_task_sequence"),
    )


class FindingRow(Base):
    __tablename__ = "research_findings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("research_tasks.id"), nullable=False, index=True
    )
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    version_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="minor")
    problem: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recommendation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    locator: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    quote: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checked_sections: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    required_user_action: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    verification_method: Mapped[str] = mapped_column(
        String(16), nullable=False, default="model"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class RevisionProposalRow(Base):
    __tablename__ = "research_revision_proposals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    base_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_findings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    hunks_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    validation_report: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="proposed")
    applied_version_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Artifact(Base):
    __tablename__ = "research_artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False, default="text/markdown")
    filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validation_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("task_id", "kind", "version", name="uq_artifact_task_kind_ver"),
    )


class BillingOperation(Base):
    __tablename__ = "research_billing_operations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    billing_group_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    entitlement: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    amount_units: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="reserved")
    request_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    note: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    settled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "billing_group_id", "operation", name="uq_billing_group_operation"
        ),
    )


class OutboxMessage(Base):
    __tablename__ = "research_outbox_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)

    __table_args__ = (
        Index("idx_outbox_unpublished", "published_at", "created_at"),
    )


__all__ = [
    "Project",
    "Document",
    "DocumentVersion",
    "DocumentBlock",
    "DocumentChunk",
    "SourceRecord",
    "Evidence",
    "ResearchTask",
    "TaskAttempt",
    "TaskEvent",
    "FindingRow",
    "RevisionProposalRow",
    "Artifact",
    "BillingOperation",
    "OutboxMessage",
]
