"""文档解析、分块与上传服务验收测试（AT-006/AT-007/AT-009/AT-010/AT-011/AT-034）。

覆盖两层：
1. ``document_parser`` 纯函数：偏移语义、状态诚实性（不得把失败/不支持写成 complete）、
   分块 800–1200 + 重叠 ≤100 的硬约束、页数/码点上限；
2. ``document_service`` + ``project_service``：20 MiB 容量、413/415/422、同内容复用、
   版本递增、跨用户统一 404、删除后失效、项目文件数上限按 owner 独立。
"""
from __future__ import annotations

import io
import os
import zipfile
from typing import Optional

import pytest
import pytest_asyncio

from ...research import document_parser as parser
from ...research import document_service as docs
from ...research import project_service as projects
from ...research.contracts import MAX_FILE_BYTES, Actor
from ...research.errors import ResearchAPIError
from ...research.models import Document, DocumentBlock, DocumentVersion

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


# ── 构造素材 ────────────────────────────────────────────────


def _docx_bytes(
    paragraphs: list[tuple[str, str]],
    *,
    media_bytes: Optional[bytes] = None,
    table_rows: Optional[list[list[str]]] = None,
) -> bytes:
    """生成最小 DOCX（仅含解析器需要的 word/document.xml）。"""

    body: list[str] = []
    for style, text in paragraphs:
        xml_text = (
            text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        if style:
            body.append(
                f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
                f"<w:r><w:t>{xml_text}</w:t></w:r></w:p>"
            )
        else:
            body.append(f"<w:r><w:t>{xml_text}</w:t></w:r>")
            body[-1] = f"<w:p>{body[-1]}</w:p>"
    if table_rows:
        rows = "".join(
            "<w:tr>"
            + "".join(
                "<w:tc><w:p><w:r><w:t>"
                + cell.replace("&", "&amp;")
                + "</w:t></w:r></w:p></w:tc>"
                for cell in row
            )
            + "</w:tr>"
            for row in table_rows
        )
        body.append(f"<w:tbl>{rows}</w:tbl>")
    document_xml = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{WORD_NS}"><w:body>'
        + "".join(body)
        + "</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
        if media_bytes is not None:
            archive.writestr("word/media/image1.png", media_bytes)
    return buffer.getvalue()


def _blank_pdf(page_count: int) -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest_asyncio.fixture
async def actor_a(research_store):
    return Actor(research_store.user_ids["a"])


@pytest_asyncio.fixture
async def actor_b(research_store):
    return Actor(research_store.user_ids["b"])


async def _project(db, actor: Actor, title: str = "解析测试项目") -> str:
    payload = await projects.create_project(db, actor, title)
    return payload["id"]


# ── document_parser：纯函数行为 ─────────────────────────────


def test_parse_plain_text_offsets_are_consistent():
    parsed = parser.parse_document(
        "第一段。\n\n第二段更长一些。".encode("utf-8"), "a.txt", "text/plain"
    )
    assert parsed.parse_status is parser.ParseStatus.COMPLETE
    assert parsed.blocks
    assert parsed.text == "".join(block.text for block in parsed.blocks)
    for block in parsed.blocks:
        assert parsed.text[block.start : block.end] == block.text
        assert block.eligible is True


def test_parse_plain_text_normalizes_nfc_and_newlines():
    decomposed = "cafe\u0301\r\n第二行   \r\n\r\n第三段"
    parsed = parser.parse_document(decomposed.encode("utf-8"), "a.txt", "text/plain")
    assert "café" in parsed.text
    assert "\r" not in parsed.text
    assert not any(line.endswith(" ") for line in parsed.text.split("\n"))


def test_parse_empty_file_fails_honestly():
    parsed = parser.parse_document(b"", "a.txt", "text/plain")
    assert parsed.parse_status is parser.ParseStatus.FAILED
    assert parsed.text == ""
    assert "empty_file" in parsed.warnings


def test_parse_binary_as_text_fails():
    parsed = parser.parse_document(b"\xff\xfe\x00\x01binary", "a.txt", "text/plain")
    assert parsed.parse_status is parser.ParseStatus.FAILED
    assert parsed.blocks == []


def test_parse_unsupported_mime_is_unsupported_not_failed():
    parsed = parser.parse_document(b"\x89PNG\r\n", "a.png", "image/png")
    assert parsed.parse_status is parser.ParseStatus.UNSUPPORTED
    assert parsed.text == ""


def test_parse_unknown_extension_without_mime_is_unsupported():
    parsed = parser.parse_document(b"data", "a.xyz", "application/octet-stream")
    assert parsed.parse_status is parser.ParseStatus.UNSUPPORTED


def test_markdown_headings_build_section_paths():
    markdown = "# 总标题\n\n引言段落。\n\n## 方法\n\n方法描述。\n"
    parsed = parser.parse_document(
        markdown.encode("utf-8"), "a.md", "text/markdown"
    )
    assert parsed.parse_status is parser.ParseStatus.COMPLETE
    headings = [b for b in parsed.blocks if b.kind == "heading"]
    assert [b.text.strip() for b in headings] == ["总标题", "方法"]
    method_blocks = [b for b in parsed.blocks if "方法" in b.section_path]
    assert method_blocks, "小节内段落必须带上 section_path"


def test_markdown_code_fence_is_not_parsed_as_heading():
    markdown = "# 标题\n\n```\n# 这是代码不是标题\n```\n"
    parsed = parser.parse_document(
        markdown.encode("utf-8"), "a.md", "text/markdown"
    )
    headings = [b for b in parsed.blocks if b.kind == "heading"]
    assert len(headings) == 1
    code_blocks = [b for b in parsed.blocks if b.kind == "code"]
    assert code_blocks
    assert "这是代码不是标题" in code_blocks[0].text


def test_docx_paragraphs_and_heading_styles():
    data = _docx_bytes(
        [
            ("Heading1", "第一章"),
            ("", "正文第一段。"),
            ("Heading2", "1.1 小节"),
            ("", "小节正文。"),
        ]
    )
    parsed = parser.parse_document(
        data,
        "a.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert parsed.parse_status is parser.ParseStatus.COMPLETE
    assert "第一章" in parsed.text
    heading_paths = [b.section_path for b in parsed.blocks if b.kind == "heading"]
    assert any("第一章" in path for path in heading_paths)
    assert any("第一章" in b.section_path and "1.1 小节" in b.section_path for b in parsed.blocks)


def test_docx_table_rows_are_extracted():
    data = _docx_bytes(
        [("", "表格前说明。")], table_rows=[["指标", "数值"], ["准确率", "91"]]
    )
    parsed = parser.parse_document(data, "a.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert parsed.parse_status is parser.ParseStatus.COMPLETE
    tables = [b for b in parsed.blocks if b.kind == "table"]
    assert tables
    assert "指标\t数值" in tables[0].text
    assert "准确率\t91" in tables[0].text


def test_docx_malformed_zip_fails_without_exception():
    parsed = parser.parse_document(
        b"not a zip",
        "a.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert parsed.parse_status is parser.ParseStatus.FAILED
    assert any("docx" in warning for warning in parsed.warnings)


def test_pdf_without_text_fails_honestly():
    parsed = parser.parse_document(_blank_pdf(2), "a.pdf", "application/pdf")
    assert parsed.parse_status in {
        parser.ParseStatus.FAILED,
        parser.ParseStatus.PARTIAL,
    }
    assert parsed.text == ""
    assert parsed.parse_status is not parser.ParseStatus.COMPLETE


def test_pdf_page_count_over_limit_is_reported_as_partial():
    parsed = parser.parse_document(
        _blank_pdf(parser.__dict__.get("MAX_PAGES", 200) + 1), "a.pdf", "application/pdf"
    )
    assert parsed.page_count is not None and parsed.page_count > 200
    assert parsed.parse_status is parser.ParseStatus.PARTIAL


def test_validate_limits_rejects_too_many_pages():
    for pages, codepoints in ((201, 10), (1, 200_001)):
        with pytest.raises(ResearchAPIError) as excinfo:
            parser.validate_limits(pages, codepoints)
        assert excinfo.value.code == "DOCUMENT_TOO_LARGE"
        assert excinfo.value.status_code == 422


def test_validate_limits_accepts_boundary_values():
    parser.validate_limits(200, 200_000)
    parser.validate_limits(None, 0)


def _make_blocks(texts: list[str]) -> list[parser.ParsedBlock]:
    blocks: list[parser.ParsedBlock] = []
    cursor = 0
    for ordinal, text in enumerate(texts):
        start = cursor
        end = start + len(text)
        blocks.append(
            parser.ParsedBlock(
                ordinal=ordinal,
                kind="paragraph",
                text=text,
                start=start,
                end=end,
                section_path="",
                eligible=True,
            )
        )
        cursor = end
    return blocks


def test_build_chunks_respects_size_and_offsets():
    blocks = _make_blocks(
        ["甲" * 300 + "\n\n", "乙" * 300 + "\n\n", "丙" * 300 + "\n\n", "丁" * 200]
    )
    full_text = "".join(block.text for block in blocks)
    chunks = parser.build_chunks(blocks)
    assert chunks, "必须为可检索文本生成分块"
    for chunk in chunks:
        assert len(chunk.text) <= parser.CHUNK_MAX_CODEPOINTS
        assert full_text[chunk.start : chunk.end] == chunk.text
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))


def test_build_chunks_splits_oversize_block_with_overlap():
    block = parser.ParsedBlock(
        ordinal=0,
        kind="paragraph",
        text="长" * 3000,
        start=0,
        end=3000,
        section_path="",
        eligible=True,
    )
    chunks = parser.build_chunks([block])
    assert len(chunks) >= 2
    assert len(chunks[0].text) <= parser.CHUNK_MAX_CODEPOINTS
    for previous, following in zip(chunks, chunks[1:]):
        overlap = previous.end - following.start
        assert 0 <= overlap <= parser.CHUNK_OVERLAP
    assert chunks[-1].end == 3000


def test_build_chunks_skips_blank_blocks():
    blocks = _make_blocks(["", "有效内容" * 100])
    chunks = parser.build_chunks(blocks)
    assert chunks
    assert all(chunk.text.strip() for chunk in chunks)


# ── document_service：上传/复用/版本/归属/容量 ─────────────


@pytest.mark.asyncio
async def test_upload_persists_document_version_and_blocks(db, actor_a):
    project_id = await _project(db, actor_a)
    text = "# 标题\n\n第一段正文。\n\n第二段正文。\n"
    result = await docs.upload_document(
        db, actor_a, project_id, filename="paper.md", mime="text/markdown", data=text.encode()
    )
    document = result["document"]
    version = result["version"]
    assert document["id"].startswith("rdoc_")
    assert document["current_version_id"] == version["id"]
    assert version["version_no"] == 1
    assert version["parse_status"] == "complete"

    stored_version = await db.get(DocumentVersion, version["id"])
    assert stored_version.text
    assert stored_version.codepoints == len(stored_version.text)
    blocks = (
        await db.execute(
            DocumentBlock.__table__.select().where(
                DocumentBlock.version_id == version["id"]
            )
        )
    ).mappings().all()
    assert blocks
    for block in blocks:
        assert stored_version.text[block["start"] : block["end"]] == block["text"]


@pytest.mark.asyncio
async def test_upload_same_content_is_reused_without_new_rows(db, actor_a):
    project_id = await _project(db, actor_a)
    data = "同一份内容，用于验证复用。\n".encode()
    first = await docs.upload_document(
        db, actor_a, project_id, filename="a.md", mime="text/markdown", data=data
    )
    assert first["reused"] is False
    second = await docs.upload_document(
        db, actor_a, project_id, filename="b.md", mime="text/markdown", data=data
    )
    assert second["reused"] is True
    assert second["document"]["id"] == first["document"]["id"]
    count = len((await db.execute(Document.__table__.select())).all())
    assert count == 1, "同项目同 owner 同内容必须复用同一文档行"


@pytest.mark.asyncio
async def test_same_filename_different_content_bumps_version(db, actor_a):
    project_id = await _project(db, actor_a)
    first = await docs.upload_document(
        db, actor_a, project_id, filename="a.md", mime="text/markdown", data="# 一\n\n版本一。".encode()
    )
    second = await docs.upload_document(
        db, actor_a, project_id, filename="a.md", mime="text/markdown", data="# 一\n\n版本二。".encode()
    )
    assert second["document"]["id"] == first["document"]["id"]
    assert second["version"]["version_no"] == 2
    assert second["document"]["current_version_id"] == second["version"]["id"]
    versions = (
        await db.execute(
            DocumentVersion.__table__.select().where(
                DocumentVersion.document_id == first["document"]["id"]
            )
        )
    ).all()
    assert len(versions) == 2


@pytest.mark.asyncio
async def test_upload_empty_file_is_422(db, actor_a):
    project_id = await _project(db, actor_a)
    with pytest.raises(ResearchAPIError) as excinfo:
        await docs.upload_document(
            db, actor_a, project_id, filename="a.md", mime="text/markdown", data=b""
        )
    assert excinfo.value.code == "EMPTY_FILE"
    assert excinfo.value.status_code == 422


@pytest.mark.asyncio
async def test_upload_over_20mib_is_413_and_persists_nothing(db, actor_a):
    project_id = await _project(db, actor_a)
    oversized = b"x" * (MAX_FILE_BYTES + 1)
    with pytest.raises(ResearchAPIError) as excinfo:
        await docs.upload_document(
            db, actor_a, project_id, filename="big.md", mime="text/markdown", data=oversized
        )
    assert excinfo.value.code == "FILE_TOO_LARGE"
    assert excinfo.value.status_code == 413
    assert (await db.execute(Document.__table__.select())).all() == []


@pytest.mark.asyncio
async def test_upload_20mib_docx_is_accepted(db, actor_a):
    """AT-011：20 MiB 合法文件不能被 10 MiB 之类的隐形门槛误拒。"""

    payload = _docx_bytes(
        [("", "超大附件文档的正文。")],
        media_bytes=os.urandom(MAX_FILE_BYTES - 60_000),
    )
    assert len(payload) <= MAX_FILE_BYTES, len(payload)
    assert len(payload) > 19 * 1024 * 1024, "素材必须真的接近 20 MiB，才能验证上限不被误拒"
    project_id = await _project(db, actor_a)
    result = await docs.upload_document(
        db,
        actor_a,
        project_id,
        filename="big.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        data=payload,
    )
    assert result["document"]["size_bytes"] == len(payload)
    assert result["version"]["parse_status"] == "complete"


@pytest.mark.asyncio
async def test_upload_unsupported_type_is_415(db, actor_a):
    project_id = await _project(db, actor_a)
    with pytest.raises(ResearchAPIError) as excinfo:
        await docs.upload_document(
            db, actor_a, project_id, filename="a.png", mime="image/png", data=b"\x89PNG\r\n"
        )
    assert excinfo.value.code == "UNSUPPORTED_MEDIA_TYPE"
    assert excinfo.value.status_code == 415


@pytest.mark.asyncio
async def test_upload_binary_text_is_422_parse_failed(db, actor_a):
    project_id = await _project(db, actor_a)
    with pytest.raises(ResearchAPIError) as excinfo:
        await docs.upload_document(
            db, actor_a, project_id, filename="a.txt", mime="text/plain", data=b"\xff\xfe\x00"
        )
    assert excinfo.value.code == "PARSE_FAILED"
    assert excinfo.value.status_code == 422


@pytest.mark.asyncio
async def test_upload_over_codepoint_limit_is_document_too_large(db, actor_a):
    project_id = await _project(db, actor_a)
    text = "字" * 200_001
    with pytest.raises(ResearchAPIError) as excinfo:
        await docs.upload_document(
            db, actor_a, project_id, filename="huge.txt", mime="text/plain", data=text.encode()
        )
    assert excinfo.value.code == "DOCUMENT_TOO_LARGE"
    assert excinfo.value.status_code == 422


@pytest.mark.asyncio
async def test_upload_sanitizes_path_traversal_filename(db, actor_a):
    project_id = await _project(db, actor_a)
    result = await docs.upload_document(
        db,
        actor_a,
        project_id,
        filename="../../etc/passwd.md",
        mime="text/markdown",
        data="正文。".encode(),
    )
    assert result["document"]["filename"] == "passwd.md"


@pytest.mark.asyncio
async def test_other_user_cannot_read_document(db, actor_a, actor_b):
    project_id = await _project(db, actor_a)
    result = await docs.upload_document(
        db, actor_a, project_id, filename="a.md", mime="text/markdown", data="私有正文。".encode()
    )
    document_id = result["document"]["id"]
    with pytest.raises(ResearchAPIError) as excinfo:
        await docs.get_document(db, actor_b, document_id)
    assert excinfo.value.code == "NOT_FOUND"
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_other_user_cannot_list_blocks_or_delete(db, actor_a, actor_b):
    project_id = await _project(db, actor_a)
    result = await docs.upload_document(
        db, actor_a, project_id, filename="a.md", mime="text/markdown", data="私有正文。".encode()
    )
    document_id = result["document"]["id"]
    for operation in (
        lambda: docs.list_blocks(db, actor_b, document_id),
        lambda: docs.delete_document(db, actor_b, document_id),
    ):
        with pytest.raises(ResearchAPIError) as excinfo:
            await operation()
        assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_same_content_from_other_user_is_not_reused(db, actor_a, actor_b):
    project_a = await _project(db, actor_a, "A 的项目")
    project_b = await _project(db, actor_b, "B 的项目")
    data = "两个用户上传同样内容，也必须是两条独立记录。".encode()
    result_a = await docs.upload_document(
        db, actor_a, project_a, filename="same.md", mime="text/markdown", data=data
    )
    result_b = await docs.upload_document(
        db, actor_b, project_b, filename="same.md", mime="text/markdown", data=data
    )
    assert result_a["document"]["id"] != result_b["document"]["id"]
    assert result_b["reused"] is False
    with pytest.raises(ResearchAPIError):
        await docs.get_document(db, actor_b, result_a["document"]["id"])


@pytest.mark.asyncio
async def test_list_blocks_ordered_and_owner_only(db, actor_a):
    project_id = await _project(db, actor_a)
    result = await docs.upload_document(
        db,
        actor_a,
        project_id,
        filename="a.md",
        mime="text/markdown",
        data="# 标题\n\n段落一。\n\n段落二。\n".encode(),
    )
    blocks = await docs.list_blocks(db, actor_a, result["document"]["id"])
    assert blocks
    assert [block["ordinal"] for block in blocks] == sorted(
        block["ordinal"] for block in blocks
    )
    assert all(block["text"] for block in blocks)


@pytest.mark.asyncio
async def test_list_blocks_rejects_foreign_version_id(db, actor_a, actor_b):
    project_a = await _project(db, actor_a)
    project_b = await _project(db, actor_b)
    result_a = await docs.upload_document(
        db, actor_a, project_a, filename="a.md", mime="text/markdown", data="A 文档".encode()
    )
    result_b = await docs.upload_document(
        db, actor_b, project_b, filename="b.md", mime="text/markdown", data="B 文档".encode()
    )
    with pytest.raises(ResearchAPIError) as excinfo:
        await docs.list_blocks(
            db,
            actor_a,
            result_a["document"]["id"],
            version_id=result_b["version"]["id"],
        )
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_document_removes_versions_and_blocks(db, actor_a):
    project_id = await _project(db, actor_a)
    result = await docs.upload_document(
        db, actor_a, project_id, filename="a.md", mime="text/markdown", data="将被删除。".encode()
    )
    document_id = result["document"]["id"]
    version_id = result["version"]["id"]
    await docs.delete_document(db, actor_a, document_id)
    assert await db.get(Document, document_id) is None
    assert await db.get(DocumentVersion, version_id) is None
    with pytest.raises(ResearchAPIError) as excinfo:
        await docs.get_document(db, actor_a, document_id)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_project_file_limit_is_per_owner(db, actor_a, actor_b):
    """AT-009：A 的项目塞满 50 个文件，不能阻塞 B 的首次上传。"""

    project_a = await _project(db, actor_a, "A 满项目")
    for index in range(50):
        await docs.upload_document(
            db,
            actor_a,
            project_a,
            filename=f"a{index}.md",
            mime="text/markdown",
            data=f"第 {index} 份唯一内容。".encode(),
        )
    with pytest.raises(ResearchAPIError) as excinfo:
        await docs.upload_document(
            db,
            actor_a,
            project_a,
            filename="overflow.md",
            mime="text/markdown",
            data="第 51 份内容。".encode(),
        )
    assert excinfo.value.code == "RESOURCE_LIMIT"
    assert excinfo.value.status_code == 422

    project_b = await _project(db, actor_b, "B 的新项目")
    result_b = await docs.upload_document(
        db, actor_b, project_b, filename="first.md", mime="text/markdown", data="B 的第一份。".encode()
    )
    assert result_b["version"]["version_no"] == 1


# ── HTTP 层：容量与类型（AT-011） ───────────────────────────


@pytest.mark.asyncio
async def test_http_upload_accepts_twenty_mib_document(client_a):
    """20 MiB 合法文件不得被 10 MiB 代理/全局限制误杀（AT-011）。"""
    from .conftest import create_project, upload_document, version_id_of

    project_id = await create_project(client_a, "大文件项目")
    media = os.urandom(MAX_FILE_BYTES - 80_000)
    data = _docx_bytes(
        [("Heading1", "大文件标题"), ("", "大文件正文内容。")], media_bytes=media
    )
    assert 19 * 1024 * 1024 < len(data) <= MAX_FILE_BYTES, len(data)
    payload = await upload_document(
        client_a,
        project_id,
        filename="big.docx",
        text=data,
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert version_id_of(payload)
    document = payload["document"]
    assert document["size_bytes"] == len(data)
    assert len(data) > 10 * 1024 * 1024  # 确实超过旧的 10 MiB 阈值


@pytest.mark.asyncio
async def test_http_upload_over_limit_returns_413(client_a):
    from .conftest import assert_error, create_project

    project_id = await create_project(client_a, "超限项目")
    oversize = b"x" * (MAX_FILE_BYTES + 1)
    response = await client_a.post(
        f"/api/v1/research/projects/{project_id}/documents",
        files={"file": ("huge.md", oversize, "text/markdown")},
    )
    assert_error(response, 413, "FILE_TOO_LARGE")


@pytest.mark.asyncio
async def test_http_upload_unsupported_type_returns_415(client_a):
    from .conftest import assert_error, create_project

    project_id = await create_project(client_a, "不支持类型项目")
    response = await client_a.post(
        f"/api/v1/research/projects/{project_id}/documents",
        files={"file": ("scan.png", b"\x89PNG\r\n\x1a\nnot-really", "image/png")},
    )
    assert_error(response, 415, "UNSUPPORTED_MEDIA_TYPE")


@pytest.mark.asyncio
async def test_http_document_reads_are_owner_scoped(client_a, client_b):
    """AT-007：跨用户读项目/文档/块统一 404。"""
    from .conftest import assert_error, create_project, upload_document

    project_id = await create_project(client_a, "A 的私有项目")
    payload = await upload_document(client_a, project_id)
    document_id = payload["document"]["id"]

    for path in (
        f"/api/v1/research/projects/{project_id}",
        f"/api/v1/research/documents/{document_id}",
        f"/api/v1/research/documents/{document_id}/blocks",
    ):
        response = await client_b.get(path)
        assert_error(response, 404, "NOT_FOUND")

    # A 自己可读，证明 404 不是“接口没实现”。
    assert (await client_a.get(f"/api/v1/research/documents/{document_id}")).status_code == 200
