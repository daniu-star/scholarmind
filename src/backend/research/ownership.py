"""所有权隔离（FR-03、问题 06/07）。

一切按 ID 访问都先按 ``owner_id`` 过滤；任何“存在但不属于当前用户”的情况
统一返回 404，避免通过状态码枚举他人资源。仓储层与路由层不得各自实现过滤。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import Actor
from .errors import not_found
from .models import (
    Artifact,
    Document,
    DocumentVersion,
    Project,
    ResearchTask,
    RevisionProposalRow,
)


async def require_project(
    db: AsyncSession, actor: Actor, project_id: str
) -> Project:
    result = await db.execute(
        select(Project).where(
            Project.id == project_id, Project.owner_id == actor.user_id
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise not_found("项目")
    return project


async def require_document(
    db: AsyncSession, actor: Actor, document_id: str
) -> Document:
    result = await db.execute(
        select(Document).where(
            Document.id == document_id, Document.owner_id == actor.user_id
        )
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise not_found("文档")
    return document


async def require_version(
    db: AsyncSession, actor: Actor, version_id: str
) -> DocumentVersion:
    result = await db.execute(
        select(DocumentVersion)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            DocumentVersion.id == version_id,
            Document.owner_id == actor.user_id,
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise not_found("文档版本")
    return version


async def require_task(
    db: AsyncSession, actor: Actor, task_id: str
) -> ResearchTask:
    result = await db.execute(
        select(ResearchTask).where(
            ResearchTask.id == task_id, ResearchTask.owner_id == actor.user_id
        )
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise not_found("任务")
    return task


async def require_artifact(
    db: AsyncSession, actor: Actor, artifact_id: str
) -> Artifact:
    result = await db.execute(
        select(Artifact).where(
            Artifact.id == artifact_id, Artifact.owner_id == actor.user_id
        )
    )
    artifact = result.scalar_one_or_none()
    if artifact is None:
        raise not_found("成果")
    return artifact


async def require_proposal(
    db: AsyncSession, actor: Actor, proposal_id: str
) -> RevisionProposalRow:
    result = await db.execute(
        select(RevisionProposalRow).where(
            RevisionProposalRow.id == proposal_id,
            RevisionProposalRow.owner_id == actor.user_id,
        )
    )
    proposal = result.scalar_one_or_none()
    if proposal is None:
        raise not_found("修改提案")
    return proposal


def owned(owner_id: Optional[int], actor: Actor) -> bool:
    """供需要二次确认的场合使用（例如内容哈希复用）。"""
    return owner_id is not None and owner_id == actor.user_id


__all__ = [
    "require_project",
    "require_document",
    "require_version",
    "require_task",
    "require_artifact",
    "require_proposal",
    "owned",
]
