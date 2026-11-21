"""文档上传、读取、删除与块列表（FR-03 / FR-04；T03）。

关键行为
========
- 上传大小上限 20 MiB（413），空文件 422，未知类型 415，解析失败/为空 422；
  200 页 / 200000 码点上限只在**解析成功**后判定（422 ``DOCUMENT_TOO_LARGE``）。
- 同项目内同 ``owner`` 且 ``content_hash`` 相同的文件直接复用既有文档（不新建行，
  不消耗配额）；查询始终带 ``owner_id``，他人命中按新建处理且不泄露其内容。
- 同项目内文件名相同但内容不同 → 版本号自增，``Document.current_version_id``
  指向最新版本；所有块随版本落库，偏移为规范化全文的码点偏移。
- 所有读取走 ``ownership.require_*``（统一 404）；删除为硬删除并同步清掉
  版本/块/分块，删除后立即失去授权。
- 事务边界：服务只 ``flush`` 不 ``commit``，由调用方（路由依赖 ``get_db``）提交。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import (
    MAX_FILE_BYTES,
    Actor,
    ParseStatus,
    content_hash,
    new_id,
    text_hash,
    utcnow,
)
from .document_parser import ParsedDocument, parse_document, validate_limits
from .errors import invalid, not_found, payload_too_large, unsupported_media
from .models import Document, DocumentBlock, DocumentChunk, DocumentVersion
from .ownership import require_document, require_project
from .project_service import enforce_upload_capacity

MIB = 1024 * 1024


def _iso(value) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _safe_filename(filename: object) -> str:
    """只保留展示用文件名；路径由服务端生成，客户端路径一律丢弃。"""

    raw = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(ch for ch in raw if ch >= " " and ch != "\x7f").strip()
    return (cleaned or "untitled")[:255]


def _document_payload(document: Document) -> dict:
    return {
        "id": document.id,
        "project_id": document.project_id,
        "filename": document.filename,
        "mime": document.mime,
        "size_bytes": int(document.size_bytes or 0),
        "content_hash": document.content_hash,
        "current_version_id": document.current_version_id,
        "created_at": _iso(document.created_at),
        "updated_at": _iso(document.updated_at),
    }


def _version_payload(version: DocumentVersion, *, include_text: bool = False) -> dict:
    payload = {
        "id": version.id,
        "document_id": version.document_id,
        "version_no": int(version.version_no),
        "content_hash": version.content_hash,
        "codepoints": int(version.codepoints),
        "parse_status": version.parse_status,
        "page_count": version.page_count,
        "source": version.source,
        "created_at": _iso(version.created_at),
    }
    if include_text:
        payload["text"] = version.text
    return payload


async def _current_version(
    db: AsyncSession, document: Document
) -> Optional[DocumentVersion]:
    if not document.current_version_id:
        return None
    return await db.get(DocumentVersion, document.current_version_id)


async def _max_version_no(db: AsyncSession, document_id: str) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(DocumentVersion.version_no), 0)).where(
            DocumentVersion.document_id == document_id
        )
    )
    return int(result.scalar_one() or 0)


async def _find_document_by_hash(
    db: AsyncSession, actor: Actor, project_id: str, digest: str
) -> Optional[Document]:
    """仅在同项目、同 owner 内按内容哈希查找，绝不跨用户复用。"""

    result = await db.execute(
        select(Document)
        .where(
            Document.project_id == project_id,
            Document.owner_id == actor.user_id,
            Document.content_hash == digest,
        )
        .order_by(Document.created_at.asc(), Document.id.asc())
    )
    return result.scalars().first()


async def _find_document_by_name(
    db: AsyncSession, actor: Actor, project_id: str, filename: str
) -> Optional[Document]:
    result = await db.execute(
        select(Document)
        .where(
            Document.project_id == project_id,
            Document.owner_id == actor.user_id,
            Document.filename == filename,
        )
        .order_by(Document.created_at.asc(), Document.id.asc())
    )
    return result.scalars().first()


def _parse_or_raise(data: bytes, filename: str, mime: str) -> ParsedDocument:
    parsed = parse_document(data, filename, mime)
    if parsed.parse_status is ParseStatus.UNSUPPORTED:
        raise unsupported_media(
            "暂不支持该文件类型；当前支持 TXT、Markdown、CSV、XLSX、PDF、DOCX。"
        )
    if parsed.parse_status is ParseStatus.FAILED:
        raise invalid(
            "PARSE_FAILED",
            "文档无法解析或未提取到可用文本，未保存任何内容。",
            {"warnings": list(parsed.warnings)[:8]},
        )
    validate_limits(parsed.page_count, len(parsed.text))
    if not parsed.blocks or not parsed.text.strip():
        raise invalid(
            "PARSE_FAILED",
            "文档未提取到可用文本，未保存任何内容。",
            {"warnings": list(parsed.warnings)[:8]},
        )
    return parsed


async def _create_version(
    db: AsyncSession,
    document: Document,
    parsed: ParsedDocument,
    *,
    version_no: int,
) -> DocumentVersion:
    now = utcnow()
    version = DocumentVersion(
        id=new_id("rver"),
        document_id=document.id,
        version_no=version_no,
        content_hash=text_hash(parsed.text),
        text=parsed.text,
        codepoints=len(parsed.text),
        parse_status=parsed.parse_status.value,
        page_count=parsed.page_count,
        source="upload",
        created_at=now,
    )
    db.add(version)
    await db.flush()
    for block in parsed.blocks:
        db.add(
            DocumentBlock(
                id=new_id("rblk"),
                version_id=version.id,
                ordinal=block.ordinal,
                kind=block.kind,
                text=block.text,
                start=block.start,
                end=block.end,
                section_path=block.section_path,
                eligible=block.eligible,
                created_at=now,
            )
        )
    await db.flush()
    return version


def _attach_version(document: Document, version: DocumentVersion, *, size_bytes: int,
                    mime: str) -> None:
    document.current_version_id = version.id
    document.size_bytes = int(size_bytes)
    document.mime = mime
    document.updated_at = utcnow()


async def upload_document(
    db: AsyncSession,
    actor: Actor,
    project_id: str,
    *,
    filename: str,
    mime: str,
    data: bytes,
) -> dict:
    """上传一份文档；返回 ``{document, version, reused}``。"""

    project = await require_project(db, actor, project_id)

    if isinstance(data, (bytearray, memoryview)):
        data = bytes(data)
    if not isinstance(data, bytes):
        raise invalid("EMPTY_FILE", "上传内容必须是字节流。")
    if not data:
        raise invalid("EMPTY_FILE", "上传文件为空。")
    if len(data) > MAX_FILE_BYTES:
        raise payload_too_large(
            f"单个文件不得超过 {MAX_FILE_BYTES // MIB} MiB。",
            {"max_bytes": MAX_FILE_BYTES, "size_bytes": len(data)},
        )

    safe_name = _safe_filename(filename)
    normalized_mime = (mime or "").split(";")[0].strip().lower()[:128]
    digest = content_hash(data)

    reusable = await _find_document_by_hash(db, actor, project.id, digest)
    if reusable is not None:
        reusable_version = await _current_version(db, reusable)
        if reusable_version is not None:
            return {
                "document": _document_payload(reusable),
                "version": _version_payload(reusable_version),
                "reused": True,
            }

    same_named = None
    if reusable is None:
        same_named = await _find_document_by_name(db, actor, project.id, safe_name)

    counts_as_new_file = reusable is None and same_named is None
    if same_named is not None:
        added_bytes = len(data) - int(same_named.size_bytes or 0)
    else:
        added_bytes = len(data)
    await enforce_upload_capacity(
        db,
        actor,
        project.id,
        counts_as_new_file=counts_as_new_file,
        added_bytes=max(0, added_bytes),
    )

    parsed = _parse_or_raise(data, safe_name, normalized_mime)

    if reusable is not None:
        document = reusable
        version = await _create_version(
            db, document, parsed, version_no=await _max_version_no(db, document.id) + 1
        )
        _attach_version(document, version, size_bytes=len(data), mime=normalized_mime)
        await db.flush()
        return {
            "document": _document_payload(document),
            "version": _version_payload(version),
            "reused": False,
        }

    if same_named is not None:
        document = same_named
        version = await _create_version(
            db, document, parsed, version_no=await _max_version_no(db, document.id) + 1
        )
        _attach_version(document, version, size_bytes=len(data), mime=normalized_mime)
        document.content_hash = digest
        await db.flush()
        return {
            "document": _document_payload(document),
            "version": _version_payload(version),
            "reused": False,
        }

    now = utcnow()
    document = Document(
        id=new_id("rdoc"),
        project_id=project.id,
        owner_id=actor.user_id,
        filename=safe_name,
        mime=normalized_mime,
        size_bytes=len(data),
        content_hash=digest,
        current_version_id=None,
        created_at=now,
        updated_at=now,
    )
    db.add(document)
    await db.flush()
    version = await _create_version(db, document, parsed, version_no=1)
    _attach_version(document, version, size_bytes=len(data), mime=normalized_mime)
    await db.flush()
    return {
        "document": _document_payload(document),
        "version": _version_payload(version),
        "reused": False,
    }


async def get_document(db: AsyncSession, actor: Actor, document_id: str) -> dict:
    document = await require_document(db, actor, document_id)
    version = await _current_version(db, document)
    payload = _document_payload(document)
    payload["version"] = (
        _version_payload(version, include_text=True) if version is not None else None
    )
    return payload


async def delete_document(db: AsyncSession, actor: Actor, document_id: str) -> None:
    """硬删除文档及其版本/块/分块；删除后立刻失去授权。"""

    document = await require_document(db, actor, document_id)
    version_ids = list(
        (
            await db.execute(
                select(DocumentVersion.id).where(
                    DocumentVersion.document_id == document.id
                )
            )
        )
        .scalars()
        .all()
    )
    if version_ids:
        await db.execute(
            delete(DocumentChunk).where(DocumentChunk.version_id.in_(version_ids))
        )
        await db.execute(
            delete(DocumentBlock).where(DocumentBlock.version_id.in_(version_ids))
        )
        await db.execute(
            delete(DocumentVersion).where(DocumentVersion.id.in_(version_ids))
        )
    await db.delete(document)
    await db.flush()


async def list_blocks(
    db: AsyncSession,
    actor: Actor,
    document_id: str,
    *,
    version_id: Optional[str] = None,
) -> list[dict]:
    document = await require_document(db, actor, document_id)
    if version_id is not None:
        version = await db.get(DocumentVersion, version_id)
        if version is None or version.document_id != document.id:
            raise not_found("文档版本")
    else:
        version = await _current_version(db, document)
    if version is None:
        return []
    result = await db.execute(
        select(DocumentBlock)
        .where(DocumentBlock.version_id == version.id)
        .order_by(DocumentBlock.ordinal.asc())
    )
    return [
        {
            "id": block.id,
            "version_id": block.version_id,
            "ordinal": int(block.ordinal),
            "kind": block.kind,
            "text": block.text,
            "start": int(block.start),
            "end": int(block.end),
            "section_path": block.section_path,
            "eligible": bool(block.eligible),
        }
        for block in result.scalars().all()
    ]


__all__ = [
    "delete_document",
    "get_document",
    "list_blocks",
    "upload_document",
]
