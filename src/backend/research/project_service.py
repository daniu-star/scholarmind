"""项目与容量（FR-03、PRD §6；T03）。

- 项目是研究状态的统一容器：文档必须挂在项目下，按 ``owner_id`` 隔离；
- 一切读取先走 ``ownership.require_project``（不存在与无权统一 404）；
- 容量常量与 422 ``RESOURCE_LIMIT`` 校验放在这里，供 ``document_service`` 复用：
  每项目 50 文件、每用户 1 GiB；容量用尽只拒绝新增，不自动删除既有资产。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import Actor, new_id, normalize_text, utcnow
from .errors import invalid
from .models import Document, DocumentVersion, Project
from .ownership import require_project

# ── 容量上限（PRD FR-03 / §6：R1 每项目 50 文件、每用户 1 GiB） ─────────
MAX_FILES_PER_PROJECT = 50
USER_STORAGE_BYTES = 1024**3

PROJECT_STATUSES = frozenset({"active", "archived"})


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _clean_title(title: object) -> str:
    if not isinstance(title, str):
        raise invalid("INVALID_TITLE", "项目标题必须是字符串。")
    clean = normalize_text(title).strip()
    if not clean:
        raise invalid("INVALID_TITLE", "项目标题不能为空。")
    if len(clean) > 200:
        raise invalid(
            "INVALID_TITLE",
            "项目标题不得超过 200 个字符。",
            {"max_length": 200},
        )
    return clean


def _clean_status(status: object) -> str:
    if not isinstance(status, str) or not status.strip():
        raise invalid("INVALID_STATUS", "项目状态必须是字符串。")
    value = status.strip().lower()
    if value not in PROJECT_STATUSES:
        raise invalid(
            "INVALID_STATUS",
            "未知的项目状态。",
            {"allowed": sorted(PROJECT_STATUSES)},
        )
    return value


def _project_payload(
    project: Project,
    *,
    documents: Optional[list[dict]] = None,
    storage_bytes: Optional[int] = None,
) -> dict:
    document_summaries = documents or []
    payload = {
        "id": project.id,
        "title": project.title,
        "status": project.status,
        "created_at": _iso(project.created_at),
        "updated_at": _iso(project.updated_at),
        "document_count": len(document_summaries),
        "storage_bytes": int(storage_bytes or 0),
        "documents": document_summaries,
        "limits": {
            "max_files_per_project": MAX_FILES_PER_PROJECT,
            "max_user_storage_bytes": USER_STORAGE_BYTES,
        },
    }
    return payload


def document_summary(document: Document, version: Optional[DocumentVersion] = None) -> dict:
    """文档摘要（含当前版本解析状态），用于项目详情与列表。"""

    return {
        "id": document.id,
        "project_id": document.project_id,
        "filename": document.filename,
        "mime": document.mime,
        "size_bytes": int(document.size_bytes or 0),
        "content_hash": document.content_hash,
        "current_version_id": document.current_version_id,
        "parse_status": version.parse_status if version is not None else None,
        "codepoints": int(version.codepoints) if version is not None else None,
        "page_count": version.page_count if version is not None else None,
        "created_at": _iso(document.created_at),
        "updated_at": _iso(document.updated_at),
    }


async def user_storage_bytes(db: AsyncSession, owner_id: int) -> int:
    """当前用户已占用的文档字节数（按 Document.size_bytes 汇总）。"""

    result = await db.execute(
        select(func.coalesce(func.sum(Document.size_bytes), 0)).where(
            Document.owner_id == owner_id
        )
    )
    return int(result.scalar_one() or 0)


async def project_document_count(
    db: AsyncSession, owner_id: int, project_id: str
) -> int:
    result = await db.execute(
        select(func.count(Document.id)).where(
            Document.owner_id == owner_id, Document.project_id == project_id
        )
    )
    return int(result.scalar_one() or 0)


async def enforce_upload_capacity(
    db: AsyncSession,
    actor: Actor,
    project_id: str,
    *,
    counts_as_new_file: bool,
    added_bytes: int,
) -> None:
    """上传前的容量校验：超限抛 422 ``RESOURCE_LIMIT``（不静默丢弃旧数据）。"""

    if counts_as_new_file:
        current = await project_document_count(db, actor.user_id, project_id)
        if current >= MAX_FILES_PER_PROJECT:
            raise invalid(
                "RESOURCE_LIMIT",
                f"每个项目最多容纳 {MAX_FILES_PER_PROJECT} 个文件。",
                {
                    "scope": "project_files",
                    "limit": MAX_FILES_PER_PROJECT,
                    "current": current,
                },
            )
    if added_bytes > 0:
        used = await user_storage_bytes(db, actor.user_id)
        if used + added_bytes > USER_STORAGE_BYTES:
            raise invalid(
                "RESOURCE_LIMIT",
                "用户文档存储空间不足，无法新增该文件。",
                {
                    "scope": "user_storage",
                    "limit": USER_STORAGE_BYTES,
                    "used": used,
                    "requested": added_bytes,
                },
            )


async def _document_summaries(
    db: AsyncSession, owner_id: int, project_id: str
) -> list[dict]:
    result = await db.execute(
        select(Document)
        .where(Document.owner_id == owner_id, Document.project_id == project_id)
        .order_by(Document.created_at.asc(), Document.id.asc())
    )
    documents = list(result.scalars().all())
    version_ids = [d.current_version_id for d in documents if d.current_version_id]
    versions: dict[str, DocumentVersion] = {}
    if version_ids:
        version_result = await db.execute(
            select(DocumentVersion).where(DocumentVersion.id.in_(version_ids))
        )
        versions = {v.id: v for v in version_result.scalars().all()}
    return [
        document_summary(document, versions.get(document.current_version_id or ""))
        for document in documents
    ]


async def create_project(db: AsyncSession, actor: Actor, title: str) -> dict:
    clean_title = _clean_title(title)
    now = utcnow()
    project = Project(
        id=new_id("rproj"),
        owner_id=actor.user_id,
        title=clean_title,
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(project)
    await db.flush()
    return _project_payload(project, documents=[], storage_bytes=0)


async def get_project(db: AsyncSession, actor: Actor, project_id: str) -> dict:
    project = await require_project(db, actor, project_id)
    documents = await _document_summaries(db, actor.user_id, project.id)
    storage = sum(int(item["size_bytes"] or 0) for item in documents)
    return _project_payload(project, documents=documents, storage_bytes=storage)


async def update_project(
    db: AsyncSession,
    actor: Actor,
    project_id: str,
    *,
    title: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    project = await require_project(db, actor, project_id)
    if title is None and status is None:
        raise invalid("NO_UPDATE_FIELDS", "没有需要更新的项目字段。")
    if title is not None:
        project.title = _clean_title(title)
    if status is not None:
        project.status = _clean_status(status)
    project.updated_at = utcnow()
    await db.flush()
    documents = await _document_summaries(db, actor.user_id, project.id)
    storage = sum(int(item["size_bytes"] or 0) for item in documents)
    return _project_payload(project, documents=documents, storage_bytes=storage)


__all__ = [
    "MAX_FILES_PER_PROJECT",
    "PROJECT_STATUSES",
    "USER_STORAGE_BYTES",
    "create_project",
    "document_summary",
    "enforce_upload_capacity",
    "get_project",
    "project_document_count",
    "update_project",
    "user_storage_bytes",
]
