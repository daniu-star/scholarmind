"""T17 导出加固（R1 / AT-034、AT-011 交付侧）。

覆盖三类“不许假成功”的导出约束：

1. 源版本为 ``partial`` 时，成果 validation 必须自带 ``partial=true`` 与
   ``partial_reason``，下游可识别“仅覆盖已解析部分”，不得冒充完整导出；
2. DOCX 生成后重新打开校验：段落数不一致 → 500 ``EXPORT_RENDER_MISMATCH``
   （可重试），且库里不得留下任何“成功导出”的 Artifact / 任务行；
3. 空正文 / 未知格式 / 未知期刊体例在落盘前被拒绝；
4. ``include_report`` / ``include_change_log`` 是真开关：没有可核对来源时 422，
   绝不在导出里凭空生成“诊断摘要”或“修改记录”；
5. 导出的 ``Idempotency-Key`` 真实生效：同键同请求复用同一成果，同键换请求 409。
"""
from __future__ import annotations

import base64
import io
from typing import Any, Dict

import docx
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from ...research import export_service
from ...research.contracts import content_hash, normalize_text, utcnow
from ...research.errors import ResearchAPIError
from ...research.models import Artifact, Document, DocumentVersion, Project, ResearchTask

pytestmark = pytest.mark.asyncio

COMPLETE_TEXT = "第一段：样本量为 120 人，2023 年收集数据。\n\n第二段：结论仍需谨慎。"
PARTIAL_TEXT = "第一段：样本量为 120 人。\n\n第二段：结论仍在整理中。"


# ── 夹具与工具 ────────────────────────────────────────────────


@pytest_asyncio.fixture
async def export_lab(db, research_store) -> Dict[str, Any]:
    """同一篇文档的三个版本：完整、部分解析、空正文。"""
    owner = research_store.user_ids["a"]
    now = utcnow()
    project = Project(
        id="rproj_export_hardening",
        owner_id=owner,
        title="导出加固测试",
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(project)
    await db.flush()

    document = Document(
        id="rdoc_export_hardening",
        project_id=project.id,
        owner_id=owner,
        filename="hardening.md",
        mime="text/markdown",
        size_bytes=len(COMPLETE_TEXT.encode("utf-8")),
        content_hash=content_hash(COMPLETE_TEXT),
        current_version_id=None,
        created_at=now,
        updated_at=now,
    )
    db.add(document)
    await db.flush()

    versions = {
        "complete": ("rver_export_complete", 1, COMPLETE_TEXT, "complete"),
        "partial": ("rver_export_partial", 2, PARTIAL_TEXT, "partial"),
        "empty": ("rver_export_empty", 3, "   \n\n  ", "complete"),
    }
    created: Dict[str, Any] = {}
    for key, (version_id, number, text, parse_status) in versions.items():
        version = DocumentVersion(
            id=version_id,
            document_id=document.id,
            version_no=number,
            content_hash=content_hash(text),
            text=text,
            codepoints=len(text),
            parse_status=parse_status,
            page_count=1,
            source="upload",
            created_at=now,
        )
        db.add(version)
        await db.flush()
        created[key] = version.id
    document.current_version_id = created["complete"]
    await db.commit()
    return {
        "project_id": project.id,
        "document_id": document.id,
        "owner_id": owner,
        "complete": created["complete"],
        "partial": created["partial"],
        "empty": created["empty"],
    }


async def _count(store, model) -> int:
    async with store.session_factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


def _validation(artifact: Artifact) -> Dict[str, Any]:
    """``Artifact`` 的校验元数据存在 ``validation_json``（模型列名）。"""
    return dict(artifact.validation_json or {})


# ── 1. 完整导出不得带 partial 标记 ───────────────────────────


async def test_complete_markdown_export_has_no_partial_markers(db, research_store, export_lab):
    artifact = await export_service.export(
        db,
        research_store.actor("a"),
        project_id=export_lab["project_id"],
        document_version_id=export_lab["complete"],
        fmt="md",
    )
    validation = _validation(artifact)
    assert validation["parse_status"] == "complete"
    assert validation["based_on_stored_version"] is True
    assert validation["document_version_id"] == export_lab["complete"]
    assert "partial" not in validation
    assert "partial_reason" not in validation
    assert "scope_note" not in validation
    assert validation["encoding"] == "utf-8"
    assert validation["binary"] is False

    assert artifact.kind == "export"
    assert artifact.body == normalize_text(COMPLETE_TEXT).strip()
    assert artifact.size_bytes == len(artifact.body.encode("utf-8"))
    assert artifact.filename.endswith(".md")


# ── 2. 部分解析导出必须自曝 partial ──────────────────────────


async def test_partial_version_export_is_marked_partial(db, research_store, export_lab):
    artifact = await export_service.export(
        db,
        research_store.actor("a"),
        project_id=export_lab["project_id"],
        document_version_id=export_lab["partial"],
        fmt="md",
    )
    validation = _validation(artifact)
    assert validation["parse_status"] == "partial"
    assert validation["partial"] is True
    assert validation["partial_reason"] == "PARSE_STATUS_PARTIAL"
    assert "partial" in validation["scope_note"]
    assert artifact.body  # 有正文，但已标注覆盖范围
    await db.commit()  # 另一 session 统计需要先落盘
    assert await _count(research_store, Artifact) == 1


# ── 3. 空正文在落盘前被拒 ────────────────────────────────────


async def test_empty_version_export_is_rejected_without_artifact(
    db, research_store, export_lab
):
    with pytest.raises(ResearchAPIError) as error:
        await export_service.export(
            db,
            research_store.actor("a"),
            project_id=export_lab["project_id"],
            document_version_id=export_lab["empty"],
            fmt="md",
        )
    assert error.value.code == "EMPTY_EXPORT_CONTENT"
    assert error.value.status_code == 422
    assert await _count(research_store, Artifact) == 0


# ── 4. DOCX 重开校验不一致 → 500，且不留假成果 ───────────────


async def test_docx_render_mismatch_aborts_without_artifact(
    db, research_store, export_lab, monkeypatch
):
    real_document = docx.Document
    calls = {"count": 0}

    class _BrokenReopen:
        def __init__(self, count: int) -> None:
            self.paragraphs = [object()] * count

    def fake_document(*args: Any, **kwargs: Any) -> Any:
        calls["count"] += 1
        if not args and not kwargs:
            return real_document()
        return _BrokenReopen(99)

    monkeypatch.setattr(docx, "Document", fake_document)

    with pytest.raises(ResearchAPIError) as error:
        await export_service.export(
            db,
            research_store.actor("a"),
            project_id=export_lab["project_id"],
            document_version_id=export_lab["complete"],
            fmt="docx",
        )
    assert error.value.code == "EXPORT_RENDER_MISMATCH"
    assert error.value.status_code == 500
    assert error.value.retryable is True
    assert error.value.details["expected_paragraphs"] >= 1
    assert error.value.details["reopened_paragraphs"] == 99
    assert calls["count"] == 2  # 一次生成、一次重开校验

    # 失败导出不得落成成果，也不得留下“已成功”的出口任务行。
    assert await _count(research_store, Artifact) == 0
    assert await _count(research_store, ResearchTask) == 0


# ── 5. 正常 DOCX：可重开、哈希可核 ──────────────────────────


async def test_docx_export_reopens_and_records_sha256(db, research_store, export_lab):
    artifact = await export_service.export(
        db,
        research_store.actor("a"),
        project_id=export_lab["project_id"],
        document_version_id=export_lab["complete"],
        fmt="docx",
    )
    raw = base64.b64decode(artifact.body)
    assert raw.startswith(b"PK\x03\x04")  # OOXML zip 包
    validation = _validation(artifact)
    assert validation["encoding"] == "base64"
    assert validation["binary"] is True
    assert validation["reopen_ok"] is True
    assert validation["sha256"] == content_hash(raw)
    # 二进制成果以 base64 存库，size_bytes 记的是存库正文字节数（与 body 一致）。
    assert artifact.size_bytes == len(artifact.body.encode("ascii"))
    assert artifact.mime == export_service.DOCX_MIME

    reopened = docx.Document(io.BytesIO(raw))
    assert len(reopened.paragraphs) >= 1


# ── 6. HTTP：partial 标记对调用方可见且可下载 ────────────────


async def test_http_export_exposes_partial_and_is_downloadable(
    client_a, db, research_store, export_lab
):
    response = await client_a.post(
        "/api/v1/research/exports",
        json={
            "project_id": export_lab["project_id"],
            "document_version_id": export_lab["partial"],
            "format": "md",
            "journal_style": "generic",
            # 基础导出流程不带“诊断摘要”，附录开关在专门用例里验证。
            "include_report": False,
        },
        headers={"Idempotency-Key": "export-hardening-0001"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["kind"] == "export"
    assert payload["validation"]["partial"] is True
    assert payload["validation"]["partial_reason"] == "PARSE_STATUS_PARTIAL"
    assert payload["downloadable"] is True
    download_url = payload["download_url"]
    assert download_url.endswith("/download")

    download = await client_a.get(download_url)
    assert download.status_code == 200
    assert download.text == normalize_text(PARTIAL_TEXT).strip()


# ── 7. HTTP：未知体例/格式在落盘前被拒 ──────────────────────


async def test_http_export_rejects_unknown_style_and_format(
    client_a, db, research_store, export_lab
):
    base = {
        "project_id": export_lab["project_id"],
        "document_version_id": export_lab["complete"],
        "format": "md",
    }
    headers = {"Idempotency-Key": "export-hardening-0002"}

    bad_style = await client_a.post(
        "/api/v1/research/exports",
        json={**base, "journal_style": "nature"},
        headers=headers,
    )
    assert bad_style.status_code == 422
    assert bad_style.json()["error"]["code"] == "UNSUPPORTED_JOURNAL_STYLE"

    bad_format = await client_a.post(
        "/api/v1/research/exports",
        json={**base, "format": "pdf"},
        headers={**headers, "Idempotency-Key": "export-hardening-0003"},
    )
    assert bad_format.status_code == 422
    assert bad_format.json()["error"]["code"] == "UNSUPPORTED_EXPORT_FORMAT"

    assert await _count(research_store, Artifact) == 0


# ── 8. HTTP 请求体工具 ───────────────────────────────────────


def _plain_export_body(export_lab: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "project_id": export_lab["project_id"],
        "document_version_id": export_lab["complete"],
        "format": "md",
        "journal_style": "generic",
        "include_report": False,
    }
    body.update(overrides)
    return body


# ── 9. HTTP：附录必须来自真实来源，不得凭空生成 ────────────


async def test_http_export_appends_diagnosis_only_from_real_source(
    client_a, db, research_store, export_lab
):
    # 造一条真实 review 任务作为“该版本已诊断”的来源，附录必须来自它而不是模板文案。
    owner = research_store.user_ids["a"]
    now = utcnow()
    db.add(
        ResearchTask(
            id="rtask_export_report_source",
            owner_id=owner,
            project_id=export_lab["project_id"],
            kind="review",
            status="succeeded",
            objective="导出前诊断",
            input_json={"document_version_id": export_lab["complete"]},
            scope_json={},
            constraints_json={},
            state_revision=1,
            billing_group_id="bg_export_report_source",
            billing_state="settled",
            attempt_no=1,
            idempotency_key=None,
            request_fingerprint=None,
            created_at=now,
            updated_at=now,
            ended_at=now,
        )
    )
    await db.commit()

    response = await client_a.post(
        "/api/v1/research/exports",
        json=_plain_export_body(export_lab, include_report=True),
        headers={"Idempotency-Key": "export-report-source-0001"},
    )
    assert response.status_code == 201, response.text
    validation = response.json()["validation"]
    assert validation["appended_sections"] == ["diagnosis_report"]
    assert validation["report_task_count"] == 1
    assert validation["report_disclaimer"]

    download = await client_a.get(response.json()["download_url"])
    assert download.status_code == 200
    assert "诊断摘要" in download.text
