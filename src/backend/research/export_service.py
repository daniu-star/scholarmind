"""成果导出服务（FR-09、FR-15、T07）。

不变量：
- 导出**永远绑定已存版本**（``document_version_id``）：不允许拿客户端传来的正文导出；
- 未知 ``journal_style`` → 422 ``UNSUPPORTED_JOURNAL_STYLE``；未知格式 →
  422 ``UNSUPPORTED_EXPORT_FORMAT``（contracts 是唯一真相，不做静默回退）；
- 空正文不得导出成功（AT-034）；
- DOCX 生成后**重新打开校验**段落数，渲染失败不允许落成“成功导出”；
- 导出不消耗第二次研究额度：这里不调用 ``billing_service``。
"""
from __future__ import annotations

import base64
import io
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from . import artifact_service
from .contracts import (
    SUPPORTED_EXPORT_FORMATS,
    SUPPORTED_JOURNAL_STYLES,
    content_hash,
    new_id,
    normalize_text,
    utcnow,
    validate_idempotency_key,
)
from .errors import ResearchAPIError, conflict, internal, invalid, not_found
from .models import (
    Artifact,
    FindingRow,
    ResearchTask,
    RevisionProposalRow,
)
from .ownership import require_document, require_project, require_version

#: DOCX MIME（python-docx 输出的 OOXML 包）。
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _normalize_format(fmt: Optional[str]) -> str:
    value = (fmt or "").strip().lower()
    if not value:
        raise invalid("UNSUPPORTED_EXPORT_FORMAT", "导出格式不能为空", {
            "supported": sorted(SUPPORTED_EXPORT_FORMATS)
        })
    if value not in SUPPORTED_EXPORT_FORMATS:
        raise invalid(
            "UNSUPPORTED_EXPORT_FORMAT",
            f"暂不支持导出格式：{value}",
            {"supported": sorted(SUPPORTED_EXPORT_FORMATS)},
        )
    return value


def _normalize_style(journal_style: Optional[str]) -> str:
    value = (journal_style or "generic").strip().lower()
    if value not in SUPPORTED_JOURNAL_STYLES:
        raise invalid(
            "UNSUPPORTED_JOURNAL_STYLE",
            f"暂不支持该期刊体例：{value or '空'}",
            {"supported": sorted(SUPPORTED_JOURNAL_STYLES)},
        )
    return value


def _document_title(document: Any) -> str:
    filename = (getattr(document, "filename", "") or "").strip()
    if not filename:
        return (getattr(document, "id", "") or "document")
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if "." in base:
        base = base.rsplit(".", 1)[0]
    return base.strip() or getattr(document, "id", "document")


def _render_markdown(text: str) -> str:
    # 保真导出：正文原样输出（只做 NFC 规范化），不增删内容。
    return normalize_text(text)


def _render_docx(text: str) -> bytes:
    """用 python-docx 生成 DOCX，并重新打开校验，避免“空文件成功”。"""
    try:
        from docx import Document as DocxDocument
    except Exception as exc:  # pragma: no cover - 依赖缺失时给出可诊断错误
        raise internal("文档导出组件不可用，请稍后重试") from exc

    doc = DocxDocument()
    paragraphs = 0
    for raw_line in normalize_text(text).split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            hashes = len(line) - len(line.lstrip("#"))
            heading = line.lstrip("#").strip()
            if heading:
                doc.add_heading(heading, level=max(1, min(4, hashes)))
                paragraphs += 1
            continue
        if line.startswith(("- ", "* ")):
            doc.add_paragraph(line[2:].strip(), style="List Bullet")
            paragraphs += 1
            continue
        doc.add_paragraph(line)
        paragraphs += 1

    if paragraphs == 0:
        raise invalid("EMPTY_EXPORT_CONTENT", "正文为空，无法导出")
    try:
        buffer = io.BytesIO()
        doc.save(buffer)
        data = buffer.getvalue()
    except Exception as exc:  # pragma: no cover - 渲染失败必须显式失败
        raise internal("文档渲染失败，请稍后重试") from exc

    if not data:
        raise internal("文档渲染结果为空，请稍后重试")
    try:
        reopened = DocxDocument(io.BytesIO(data))
        reopened_count = len(reopened.paragraphs)
    except Exception as exc:  # pragma: no cover
        raise internal("导出文件无法重新打开，已中止交付") from exc
    if reopened_count == 0:
        raise internal("导出文件重新打开后无内容，已中止交付")
    # 重新打开后的段落数必须与写入数一致：防止静默丢段落的“假成功”交付。
    if reopened_count != paragraphs:
        raise ResearchAPIError(
            "EXPORT_RENDER_MISMATCH",
            500,
            "导出文件重新打开后段落数不一致，已中止交付",
            details={"expected_paragraphs": paragraphs, "reopened_paragraphs": reopened_count},
            retryable=True,
        )
    return data


#: 诊断摘要的固定免责声明；与 review_workflow 保持一致，但不反向依赖该模块。
_EXPORT_DIAGNOSIS_DISCLAIMER = (
    "诊断摘要由自动流程生成，供投稿前自检参考，不构成期刊评审意见；"
    "引用与事实请以作者核对为准。"
)

_SECTION_UNAVAILABLE = "EXPORT_SECTION_UNAVAILABLE"


def _export_fingerprint(
    *,
    owner_id: int,
    project_id: str,
    version_id: str,
    format_name: str,
    style_name: str,
    include_report: bool,
    include_change_log: bool,
) -> str:
    """同一 Idempotency-Key 下的请求指纹：任何输入变化都必须重算成果。"""

    return content_hash(
        "|".join(
            [
                f"owner:{owner_id}",
                f"project:{project_id}",
                f"version:{version_id}",
                f"format:{format_name}",
                f"style:{style_name}",
                f"report:{int(bool(include_report))}",
                f"change_log:{int(bool(include_change_log))}",
            ]
        )
    )


async def _export_artifact_of_task(db: AsyncSession, task_id: str) -> Optional[Artifact]:
    statement = (
        select(Artifact)
        .where(Artifact.task_id == task_id, Artifact.kind == "export")
        .order_by(Artifact.version.desc())
    )
    return (await db.execute(statement)).scalars().first()


async def _replay_export(
    db: AsyncSession,
    *,
    owner_id: int,
    idempotency_key: str,
    fingerprint: str,
) -> tuple[Optional[Artifact], Optional[str]]:
    """按键查找既有导出：返回 (已完成成果, 可复用的半成品任务 id)。

    同键不同指纹 → 409；同键同指纹且成果已存在 → 直接复用，不重复落库。
    """
    statement = select(ResearchTask).where(
        ResearchTask.owner_id == owner_id,
        ResearchTask.idempotency_key == idempotency_key,
    )
    task = (await db.execute(statement)).scalars().first()
    if task is None:
        return None, None
    stored = dict(task.snapshot_summary or {}).get("export_request_fingerprint")
    if task.kind != "export" or not stored or stored != fingerprint:
        raise conflict(
            "IDEMPOTENCY_CONFLICT",
            "同一 Idempotency-Key 已用于不同的导出请求，请为新请求使用新的键。",
            {"idempotency_key": idempotency_key},
        )
    artifact = await _export_artifact_of_task(db, task.id)
    if artifact is not None:
        return artifact, None
    # 上次请求在“任务行已写、成果未落”之间中断：复用任务行补齐成果。
    return None, task.id


async def _review_tasks_for_version(
    db: AsyncSession, owner_id: int, version_id: str
) -> List[ResearchTask]:
    statement = (
        select(ResearchTask)
        .where(ResearchTask.owner_id == owner_id, ResearchTask.kind == "review")
        .order_by(ResearchTask.created_at.desc())
        .limit(200)
    )
    tasks = list((await db.execute(statement)).scalars().all())
    matched: List[ResearchTask] = []
    for task in tasks:
        payload = dict(task.input_json or {})
        if str(payload.get("document_version_id") or "") == version_id:
            matched.append(task)
    return matched


async def _diagnosis_section(
    db: AsyncSession, owner_id: int, version: Any
) -> tuple[List[str], Dict[str, Any]]:
    """生成“诊断摘要”章节；没有可核对来源时报 422，不凭空写结论。"""

    findings = list(
        (
            await db.execute(
                select(FindingRow)
                .where(
                    FindingRow.owner_id == owner_id,
                    FindingRow.version_id == version.id,
                )
                .order_by(FindingRow.severity, FindingRow.created_at)
            )
        )
        .scalars()
        .all()
    )
    review_tasks = await _review_tasks_for_version(db, owner_id, version.id)
    if not findings and not review_tasks:
        raise ResearchAPIError(
            _SECTION_UNAVAILABLE,
            422,
            "该版本尚无全文诊断结果，无法在导出中附诊断摘要。",
            details={"document_version_id": version.id, "option": "include_report"},
        )
    lines: List[str] = ["", "## 诊断摘要（ScholarMind 自动生成）", ""]
    if not findings:
        lines.append("本次全文诊断未发现需要修改的问题（覆盖范围以对应任务报告为准）。")
    for row in findings:
        method = "结构性检查" if row.verification_method == "structural" else "模型阅读推断"
        line = f"- [{row.severity}/{row.category}] {row.problem}（检查方式：{method}）"
        if row.recommendation:
            line += f" 建议：{row.recommendation}"
        lines.append(line)
    lines.extend(["", f"说明：{_EXPORT_DIAGNOSIS_DISCLAIMER}"])
    return lines, {
        "report_finding_count": len(findings),
        "report_task_count": len(review_tasks),
        "report_disclaimer": _EXPORT_DIAGNOSIS_DISCLAIMER,
    }


async def _change_log_section(
    db: AsyncSession, owner_id: int, version: Any
) -> tuple[List[str], Dict[str, Any]]:
    """生成“修改记录”章节；该版本没有任何已采纳提案时显式拒绝。"""

    proposals = list(
        (
            await db.execute(
                select(RevisionProposalRow)
                .where(
                    RevisionProposalRow.owner_id == owner_id,
                    RevisionProposalRow.applied_version_id == version.id,
                    RevisionProposalRow.status == "applied",
                )
                .order_by(RevisionProposalRow.applied_at)
            )
        )
        .scalars()
        .all()
    )
    if not proposals:
        raise ResearchAPIError(
            _SECTION_UNAVAILABLE,
            422,
            "该版本没有已采纳的修改提案，无法在导出中附修改记录。",
            details={"document_version_id": version.id, "option": "include_change_log"},
        )
    lines: List[str] = ["", "## 修改记录（已采纳）", ""]
    for proposal in proposals:
        hunks = proposal.hunks_json if isinstance(proposal.hunks_json, list) else []
        applied_at = proposal.applied_at.isoformat() if proposal.applied_at else "时间未知"
        lines.append(f"- 提案 {proposal.id}：{len(hunks)} 处修改，采纳时间 {applied_at}")
    return lines, {"change_log_proposal_count": len(proposals)}


async def export(
    db: AsyncSession,
    actor: Any,
    *,
    project_id: str,
    document_version_id: str,
    fmt: str,
    journal_style: str = "generic",
    task_id: Optional[str] = None,
    include_report: bool = False,
    include_change_log: bool = False,
    idempotency_key: Optional[str] = None,
) -> Artifact:
    """把**已存版本**导出为可下载成果，返回持久化后的 ``Artifact``。

    ``task_id`` 由执行器传入时，成果直接挂在该任务下（不再单独建出口任务行）；
    直接调用则不传，服务会为本次导出建立一条已完成的 export 任务用于溯源。

    ``Idempotency-Key`` 对导出同样生效：同键同请求复用同一成果，同键不同请求 409；
    ``include_report`` / ``include_change_log`` 会真实追加章节，缺少可核对来源时 422，
    绝不静默忽略（否则前端勾选项就是假开关）。
    """
    format_name = _normalize_format(fmt)
    style_name = _normalize_style(journal_style)
    key: Optional[str] = None
    if idempotency_key is not None:
        key = validate_idempotency_key(idempotency_key)

    project = await require_project(db, actor, project_id)
    version = await require_version(db, actor, document_version_id)
    document = await require_document(db, actor, version.document_id)
    if document.project_id != project.id:
        # 跨项目取版本按“不存在”处理，不泄露其他项目文档信息。
        raise not_found("文档版本")

    text = normalize_text(version.text or "").strip()
    if not text:
        raise invalid(
            "EMPTY_EXPORT_CONTENT",
            "该版本正文为空，无法导出",
            {"document_version_id": version.id},
        )

    title = _document_title(document)
    owner_id = actor.user_id
    project_pk = project.id
    version_pk = version.id
    fingerprint = _export_fingerprint(
        owner_id=owner_id,
        project_id=project_pk,
        version_id=version_pk,
        format_name=format_name,
        style_name=style_name,
        include_report=bool(include_report),
        include_change_log=bool(include_change_log),
    )
    reusable_task_id: Optional[str] = None
    if key is not None and task_id is None:
        replay_artifact, reusable_task_id = await _replay_export(
            db, owner_id=owner_id, idempotency_key=key, fingerprint=fingerprint
        )
        if replay_artifact is not None:
            return replay_artifact

    validation: Dict[str, Any] = {
        "document_id": document.id,
        "document_version_id": version.id,
        "document_version_no": version.version_no,
        "document_version_hash": version.content_hash,
        "format": format_name,
        "journal_style": style_name,
        "parse_status": version.parse_status,
        "source_codepoints": version.codepoints,
        "exported_at": utcnow().isoformat(),
        "based_on_stored_version": True,
    }
    if version.parse_status in ("partial", "unsupported", "failed"):
        validation["scope_note"] = (
            f"源解析状态为 {version.parse_status}，导出内容仅覆盖已解析部分"
        )
        # 部分解析不得冒充完整导出：成果自身必须能被下游识别为不完整交付。
        validation["partial"] = True
        validation["partial_reason"] = f"PARSE_STATUS_{version.parse_status.upper()}"

    appended_sections: List[str] = []
    if include_report:
        lines, meta = await _diagnosis_section(db, owner_id, version)
        text = text + "\n".join(lines)
        appended_sections.append("diagnosis_report")
        validation.update(meta)
    if include_change_log:
        lines, meta = await _change_log_section(db, owner_id, version)
        text = text + "\n".join(lines)
        appended_sections.append("change_log")
        validation.update(meta)
    if appended_sections:
        validation["appended_sections"] = appended_sections

    if format_name == "md":
        body = _render_markdown(text)
        mime = "text/markdown"
        filename = f"{title}.md"
        validation["encoding"] = "utf-8"
        validation["binary"] = False
    else:
        data = _render_docx(text)
        body = base64.b64encode(data).decode("ascii")
        mime = DOCX_MIME
        filename = f"{title}.docx"
        validation["encoding"] = "base64"
        validation["binary"] = True
        validation["reopen_ok"] = True
        validation["sha256"] = content_hash(data)

    # 导出不消耗研究额度：直接调用时记录一条已完成的 export 任务行用于溯源；
    # 由执行器传入 task_id 时不再新增任务行，成果直接归属该任务。
    if task_id is None:
        if reusable_task_id is not None:
            # 同一幂等键的上次请求已写入任务行但没落成果：沿用该任务补齐。
            task_id = reusable_task_id
        else:
            task_id = new_id("task")
            export_task = ResearchTask(
                id=task_id,
                owner_id=owner_id,
                project_id=project_pk,
                kind="export",
                status="succeeded",
                objective=f"导出《{title}》为 {format_name}",
                input_json={
                    "document_id": document.id,
                    "document_version_id": version_pk,
                    "document_version_no": version.version_no,
                    "format": format_name,
                    "journal_style": style_name,
                    "include_report": bool(include_report),
                    "include_change_log": bool(include_change_log),
                },
                scope_json={"document_version_id": version_pk},
                constraints_json={"journal_style": style_name, "format": format_name},
                state_revision=1,
                billing_group_id=new_id("bg"),
                billing_state=None,
                idempotency_key=key,
                snapshot_summary={
                    "kind": "export",
                    "format": format_name,
                    "journal_style": style_name,
                    "document_version_id": version_pk,
                    "include_report": bool(include_report),
                    "include_change_log": bool(include_change_log),
                    "export_request_fingerprint": fingerprint,
                    "model_snapshot": None,
                },
                ended_at=utcnow(),
            )
            db.add(export_task)
            try:
                await db.flush()
            except IntegrityError:
                # 并发同键请求：回滚本事务后按键复用已成功落库的那一份成果。
                await db.rollback()
                replay_artifact, _ = await _replay_export(
                    db, owner_id=owner_id, idempotency_key=key or "", fingerprint=fingerprint
                )
                if replay_artifact is None:
                    raise conflict(
                        "IDEMPOTENCY_CONFLICT",
                        "同一 Idempotency-Key 的导出正在处理中，请稍后重试。",
                    )
                return replay_artifact


    artifact = await artifact_service.create_artifact(
        db,
        owner_id=actor.user_id,
        task_id=task_id,
        kind="export",
        body=body,
        mime=mime,
        filename=filename,
        validation=validation,
    )
    return artifact


__all__ = ["DOCX_MIME", "export"]
