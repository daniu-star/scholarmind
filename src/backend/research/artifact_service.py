"""研究成果持久化服务（FR-09、T07、AT-034）。

不变量：
- 成果必须持久化正文（``Artifact.body`` 进库），**空成果不允许创建**——
  空文件不是成果，不能把“没产出”包装成成功；
- 每个 ``(task_id, kind)`` 的 ``version`` 单调递增，重复创建得到新版本而非覆盖；
- 二进制成果（DOCX 等）以 base64 存入 ``body`` 并在 ``validation`` 标注
  ``encoding="base64"``，下载时由 :func:`decode_artifact_body` 还原；
- 读取/列表必须按 ``actor.user_id`` 过滤所有权（T07：不泄露他人成果）。
"""
from __future__ import annotations

import base64
import binascii
import os
from typing import Any, Dict, Iterable, List, Optional, Set

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import content_hash, new_id, normalize_text
from .errors import invalid
from .models import Artifact
from .ownership import require_artifact, require_task

#: 文件名上限（与 ``Artifact.filename`` 列宽一致）。
MAX_FILENAME_LENGTH = 200

#: 允许的成果类型（未知类型拒绝，避免脏数据进入下载链路）。
ALLOWED_ARTIFACT_KINDS = frozenset(
    {
        "review_report",
        "revision_proposal",
        "change_log",
        "draft",
        "literature_review",
        "chart",
        "export",
        "outline",
        "evidence_table",
        "quality_report",
    }
)


def _clean_filename(filename: Optional[str], kind: str, mime: str) -> str:
    """只保留安全文件名（去路径、去控制字符），不泄露本机路径（T07）。"""
    raw = (filename or "").strip()
    raw = raw.replace("\\", "/")
    base = os.path.basename(raw)
    cleaned = "".join(
        ch for ch in base if ch.isprintable() and ch not in '"/:*?"<>|'
    ).strip(" .")
    if not cleaned:
        ext = ".md" if "markdown" in mime else ""
        cleaned = f"{kind}{ext}"
    return cleaned[:MAX_FILENAME_LENGTH]


def _normalize_body(body: str, mime: str) -> str:
    if not isinstance(body, str):
        raise invalid("INVALID_ARTIFACT_BODY", "成果正文必须是字符串")
    text = body.strip()
    if not text:
        raise invalid("EMPTY_ARTIFACT", "成果正文为空，不能作为成果保存")
    if mime.startswith("text/") or mime.endswith("+json"):
        return normalize_text(body)
    return body


async def create_artifact(
    db: AsyncSession,
    *,
    owner_id: int,
    task_id: str,
    kind: str,
    body: str,
    mime: str,
    filename: str,
    validation: Optional[Dict[str, Any]] = None,
) -> Artifact:
    """持久化一条成果；``body`` 为空直接 422（AT-034）。"""
    if not isinstance(owner_id, int) or owner_id <= 0:
        raise invalid("INVALID_OWNER", "成果必须绑定有效所有者")
    if not isinstance(task_id, str) or not task_id.strip():
        raise invalid("INVALID_TASK_ID", "成果必须绑定任务")
    kind_name = (kind or "").strip()
    if not kind_name:
        raise invalid("INVALID_ARTIFACT_KIND", "成果类型不能为空")
    if kind_name not in ALLOWED_ARTIFACT_KINDS:
        raise invalid(
            "INVALID_ARTIFACT_KIND",
            f"未知的成果类型：{kind_name}",
            {"supported": sorted(ALLOWED_ARTIFACT_KINDS)},
        )
    mime_name = (mime or "text/markdown").strip() or "text/markdown"
    if validation is not None and not isinstance(validation, dict):
        raise invalid("INVALID_ARTIFACT_VALIDATION", "validation 必须是对象")

    stored_body = _normalize_body(body, mime_name)
    encoded = stored_body.encode("utf-8")

    result = await db.execute(
        select(func.max(Artifact.version)).where(
            Artifact.task_id == task_id, Artifact.kind == kind_name
        )
    )
    current_max = result.scalar_one_or_none() or 0
    artifact = Artifact(
        id=new_id("art"),
        owner_id=owner_id,
        task_id=task_id,
        kind=kind_name,
        version=int(current_max) + 1,
        content_hash=content_hash(encoded),
        mime=mime_name,
        filename=_clean_filename(filename, kind_name, mime_name),
        body=stored_body,
        size_bytes=len(encoded),
        validation_json=dict(validation or {}),
    )
    db.add(artifact)
    await db.flush()
    return artifact


async def list_artifacts(
    db: AsyncSession, actor: Any, task_id: str
) -> List[Dict[str, Any]]:
    """列出任务下的成果（按类型、版本排序）；任务不存在/非本人 → 404。"""
    await require_task(db, actor, task_id)
    result = await db.execute(
        select(Artifact)
        .where(Artifact.task_id == task_id, Artifact.owner_id == actor.user_id)
        .order_by(Artifact.kind.asc(), Artifact.version.asc())
    )
    return [_artifact_dict(item) for item in result.scalars().all()]


async def read_artifact(db: AsyncSession, actor: Any, artifact_id: str) -> Artifact:
    """读取成果全文（含 body），用于受控下载。"""
    return await require_artifact(db, actor, artifact_id)


async def list_artifact_rows(
    db: AsyncSession, task_id: str, owner_id: Optional[int] = None
) -> List[Artifact]:
    """内部使用：按任务取成果行（执行器/结算统计），可限定 owner。"""
    stmt = select(Artifact).where(Artifact.task_id == task_id)
    if owner_id is not None:
        stmt = stmt.where(Artifact.owner_id == owner_id)
    stmt = stmt.order_by(Artifact.kind.asc(), Artifact.version.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def artifact_kinds_for_task(db: AsyncSession, task_id: str) -> Set[str]:
    """任务已有成果的类型集合（供 ``completion_errors`` 做最小交付检查）。"""
    result = await db.execute(
        select(Artifact.kind).where(Artifact.task_id == task_id).distinct()
    )
    return {str(kind) for kind in result.scalars().all() if kind}


def decode_artifact_body(artifact: Artifact) -> bytes:
    """把存库的 base64/文本正文还原为字节，供下载响应使用。"""
    validation = artifact.validation_json or {}
    body = artifact.body or ""
    if validation.get("encoding") == "base64":
        try:
            return base64.b64decode(body.encode("ascii"), validate=False)
        except (binascii.Error, UnicodeEncodeError) as exc:
            raise invalid(
                "ARTIFACT_DECODE_FAILED",
                "成果二进制内容损坏，无法下载",
                {"artifact_id": artifact.id},
            ) from exc
    return body.encode("utf-8")


def _artifact_dict(artifact: Artifact) -> Dict[str, Any]:
    return {
        "id": artifact.id,
        "task_id": artifact.task_id,
        "owner_id": artifact.owner_id,
        "kind": artifact.kind,
        "version": artifact.version,
        "content_hash": artifact.content_hash,
        "mime": artifact.mime,
        "filename": artifact.filename,
        "size_bytes": artifact.size_bytes,
        "validation": dict(artifact.validation_json or {}),
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        "downloadable": True,
    }


def summarize_artifacts(artifacts: Iterable[Artifact]) -> Dict[str, Any]:
    """给事件载荷/快照用的轻量摘要（只含 id/kind/版本，不含正文）。"""
    items = [
        {
            "artifact_id": item.id,
            "kind": item.kind,
            "version": item.version,
            "filename": item.filename,
            "mime": item.mime,
        }
        for item in artifacts
    ]
    return {"artifact_ids": [item["artifact_id"] for item in items], "artifacts": items}


__all__ = [
    "ALLOWED_ARTIFACT_KINDS",
    "MAX_FILENAME_LENGTH",
    "artifact_kinds_for_task",
    "create_artifact",
    "decode_artifact_body",
    "list_artifact_rows",
    "list_artifacts",
    "read_artifact",
    "summarize_artifacts",
]
