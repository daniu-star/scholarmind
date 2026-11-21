"""文档解析与分块（FR-04 / FR-05，T03）。

实现约定
=========
- **纯函数**：导入期不做 I/O、不加载模型、不连接数据库；PDF 依赖 ``pypdf``
  在函数内延迟导入，DOCX 只使用标准库 ``zipfile`` + ``ElementTree``（不新增依赖）。
- **偏移语义**：所有 ``start`` / ``end`` 都是*规范化全文*（``ParsedDocument.text``）
  的 Unicode 码点偏移，且满足 ``document.text[start:end] == block.text``。块与块
  之间用两个换行（``"\\n\\n"``）分隔，末块不带尾分隔；因此 ``text`` 就是全部
  ``block.text`` 的顺序拼接，偏移可直接切片核对。
- **诚实失败**：空内容 / 二进制内容 / 加密或损坏文档返回 ``ParseStatus.FAILED``
  （服务层 422），缺少解析器返回 ``ParseStatus.UNSUPPORTED``（服务层 415），仅部分
  页无文本时返回 ``PARTIAL`` 并记录 warnings；不得谎称 ``COMPLETE``。
- **上限判定交给服务层**：``validate_limits`` 只对解析成功的文档调用。PDF 页数
  超过上限时本模块不会真的抽取全部页面，而是返回带 ``page_count`` 的 PARTIAL
  结果，由 ``validate_limits`` 抛 ``DOCUMENT_TOO_LARGE``。
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional, Sequence

from .contracts import (
    MAX_CODEPOINTS,
    MAX_PAGES,
    ParseStatus,
    normalize_text,
)
from .errors import invalid

# ── 分块参数（PRD FR-05：每块 800–1200 码点，重叠 ≤100） ──────────────
CHUNK_MIN_CODEPOINTS = 800
CHUNK_MAX_CODEPOINTS = 1200
CHUNK_OVERLAP = 100
# 单块文本超过该长度时，块内用句末/换行优先的方式切分，避免出现巨型块。
BLOCK_SOFT_LIMIT = 4000

# ── 支持的类型 ────────────────────────────────────────────────────────
SUPPORTED_MIME_FORMATS = {
    "text/plain": "text",
    "text/markdown": "markdown",
    "text/x-markdown": "markdown",
    "text/csv": "csv",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}
EXTENSION_FORMATS = {
    ".txt": "text",
    ".text": "text",
    ".md": "markdown",
    ".markdown": "markdown",
    ".csv": "csv",
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
}
_GENERIC_MIMES = frozenset(
    {
        "",
        "application/octet-stream",
        "binary/octet-stream",
        "application/x-download",
        "application/unknown",
    }
)


@dataclass(frozen=True)
class ParsedBlock:
    """规范化全文中的一个稳定区块。"""

    ordinal: int
    kind: str
    text: str
    start: int
    end: int
    section_path: str
    eligible: bool


@dataclass(frozen=True)
class ParsedDocument:
    """一次解析的完整结果；``text`` 是所有块文本的顺序拼接。"""

    text: str
    blocks: list[ParsedBlock]
    page_count: Optional[int]
    parse_status: ParseStatus
    warnings: list[str]


@dataclass(frozen=True)
class ChunkSpec:
    """检索分块；``start`` / ``end`` 是规范化全文的码点偏移。"""

    ordinal: int
    block_ordinal: int
    text: str
    start: int
    end: int


# ── 通用清洗 ─────────────────────────────────────────────────────────


def _clean_text(raw: str) -> str:
    """统一换行、NFC 规范化、去掉行尾空白与首尾空行。"""

    if not raw:
        return ""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = normalize_text(text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text.strip("\n")


def _decode_utf8(data: bytes) -> Optional[str]:
    """UTF-8（含 BOM）解码；二进制内容返回 ``None``。"""

    try:
        text = data.decode("utf-8-sig")
    except (UnicodeDecodeError, UnicodeError):
        return None
    if "\x00" in text:
        return None
    return text


_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n")


def _split_paragraphs(text: str) -> list[str]:
    """按空行切段；超长段再按行聚合切分，避免出现数万码点的单块。"""

    paragraphs: list[str] = []
    for piece in _BLANK_LINE_RE.split(text):
        piece = piece.strip("\n")
        if not piece.strip():
            continue
        paragraphs.extend(_split_oversize(piece))
    return paragraphs


def _split_oversize(text: str, limit: int = BLOCK_SOFT_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.split("\n"):
        if current and current_len + len(line) + 1 > limit:
            pieces.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        pieces.append("\n".join(current))

    result: list[str] = []
    for piece in pieces:
        while len(piece) > limit:
            result.append(piece[:limit])
            piece = piece[limit:]
        if piece:
            result.append(piece)
    return result


def _assemble(segments: Sequence[dict]) -> tuple[str, list[ParsedBlock]]:
    """把按顺序排列的片段拼成连续全文与块列表。"""

    cleaned: list[tuple[dict, str]] = []
    for segment in segments:
        body = _clean_text(str(segment.get("text") or ""))
        if body:
            cleaned.append((segment, body))

    blocks: list[ParsedBlock] = []
    parts: list[str] = []
    cursor = 0
    for index, (segment, body) in enumerate(cleaned):
        suffix = "\n\n" if index < len(cleaned) - 1 else ""
        text = body + suffix
        start = cursor
        end = start + len(text)
        blocks.append(
            ParsedBlock(
                ordinal=index,
                kind=str(segment.get("kind") or "paragraph")[:24],
                text=text,
                start=start,
                end=end,
                section_path=str(segment.get("section_path") or "")[:400],
                eligible=bool(segment.get("eligible", True)),
            )
        )
        parts.append(text)
        cursor = end
    return "".join(parts), blocks


def _failed(warnings: Sequence[str]) -> ParsedDocument:
    return ParsedDocument(
        text="",
        blocks=[],
        page_count=None,
        parse_status=ParseStatus.FAILED,
        warnings=list(warnings),
    )


def _result(
    segments: Sequence[dict],
    *,
    page_count: Optional[int],
    warnings: Sequence[str],
) -> ParsedDocument:
    text, blocks = _assemble(segments)
    if not text.strip() or not blocks:
        return _failed(list(warnings) + ["no_extractable_text"])
    status = ParseStatus.PARTIAL if warnings else ParseStatus.COMPLETE
    return ParsedDocument(
        text=text,
        blocks=blocks,
        page_count=page_count,
        parse_status=status,
        warnings=list(warnings),
    )


# ── 类型识别 ─────────────────────────────────────────────────────────


def _detect_format(filename: str, mime: str) -> tuple[Optional[str], str]:
    """返回 ``(内部格式, 规范化 mime)``；不支持时格式为 ``None``。

    优先信任显式 mime；``application/octet-stream`` 等泛型 mime 才回退到扩展名。
    这保证“伪装扩展名”（如 image/png 改名 .txt）按 415 拒绝，而不是被静默当文本读。
    """

    mime_norm = (mime or "").split(";")[0].strip().lower()
    if mime_norm in SUPPORTED_MIME_FORMATS:
        return SUPPORTED_MIME_FORMATS[mime_norm], mime_norm
    if mime_norm and mime_norm not in _GENERIC_MIMES:
        return None, mime_norm
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    dot = name.rfind(".")
    extension = name[dot:].lower() if dot >= 0 else ""
    fmt = EXTENSION_FORMATS.get(extension)
    return fmt, mime_norm or "application/octet-stream"


# ── 纯文本 / Markdown ────────────────────────────────────────────────


_ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _parse_plain(data: bytes) -> ParsedDocument:
    raw = _decode_utf8(data)
    if raw is None:
        return _failed(["text_not_utf8_or_binary"])
    segments = [
        {"kind": "paragraph", "text": piece, "section_path": ""}
        for piece in _split_paragraphs(_clean_text(raw))
    ]
    return _result(segments, page_count=None, warnings=[])


def _parse_markdown(data: bytes) -> ParsedDocument:
    raw = _decode_utf8(data)
    if raw is None:
        return _failed(["text_not_utf8_or_binary"])
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    segments: list[dict] = []
    heading_stack: list[str] = []
    paragraph: list[str] = []
    fence: Optional[str] = None
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            segments.append(
                {
                    "kind": "paragraph",
                    "text": "\n".join(paragraph),
                    "section_path": " > ".join(heading_stack),
                }
            )
            paragraph = []

    def flush_code() -> None:
        nonlocal code_lines
        if code_lines:
            segments.append(
                {
                    "kind": "code",
                    "text": "\n".join(code_lines),
                    "section_path": " > ".join(heading_stack),
                }
            )
            code_lines = []

    for line in text.split("\n"):
        stripped = line.strip()
        if fence is not None:
            if stripped.startswith(fence):
                flush_code()
                fence = None
            else:
                code_lines.append(line)
            continue
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            flush_paragraph()
            fence = fence_match.group(1)
            continue
        heading_match = _ATX_HEADING_RE.match(line)
        if heading_match:
            flush_paragraph()
            level = min(len(heading_match.group(1)), 6)
            title = heading_match.group(2).strip()
            if title:
                heading_stack = heading_stack[: level - 1] + [title]
                segments.append(
                    {
                        "kind": "heading",
                        "text": title,
                        "section_path": " > ".join(heading_stack),
                    }
                )
            continue
        if not stripped:
            flush_paragraph()
            continue
        paragraph.append(line)
    flush_paragraph()
    if fence is not None:
        flush_code()
    return _result(segments, page_count=None, warnings=[])


# ── PDF ──────────────────────────────────────────────────────────────


def _parse_pdf(data: bytes) -> ParsedDocument:
    try:
        from pypdf import PdfReader  # 延迟导入：无副作用、无模型加载
    except Exception:  # pragma: no cover - 取决于运行环境
        return ParsedDocument(
            text="",
            blocks=[],
            page_count=None,
            parse_status=ParseStatus.UNSUPPORTED,
            warnings=["pdf_parser_unavailable"],
        )

    try:
        reader = PdfReader(io.BytesIO(data))
        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")
            except Exception:
                return _failed(["pdf_encrypted"])
            if getattr(reader, "is_encrypted", False):
                return _failed(["pdf_encrypted"])
        pages = len(reader.pages)
    except Exception as exc:  # 损坏 / 非 PDF / 解析器内部错误
        return _failed([f"pdf_open_error:{type(exc).__name__}"])

    if pages <= 0:
        return _failed(["pdf_no_pages"])
    if pages > MAX_PAGES:
        # 不真正抽取全部页面：交给服务层 validate_limits 抛 DOCUMENT_TOO_LARGE。
        return ParsedDocument(
            text="",
            blocks=[],
            page_count=pages,
            parse_status=ParseStatus.PARTIAL,
            warnings=["page_count_exceeds_limit"],
        )

    segments: list[dict] = []
    warnings: list[str] = []
    for index in range(pages):
        page_no = index + 1
        try:
            raw = reader.pages[index].extract_text() or ""
        except Exception:
            raw = ""
            warnings.append(f"page_{page_no}_extract_error")
        cleaned = _clean_text(raw)
        if not cleaned.strip():
            warnings.append(f"page_{page_no}_no_extractable_text")
            continue
        section = f"第 {page_no} 页"
        for piece in _split_paragraphs(cleaned):
            segments.append(
                {"kind": "paragraph", "text": piece, "section_path": section}
            )
    return _result(segments, page_count=pages, warnings=warnings)


# ── DOCX（标准库 zipfile + ElementTree） ─────────────────────────────

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _w(local: str) -> str:
    return f"{{{_W_NS}}}{local}"


_HEADING_STYLE_RE = re.compile(r"(?:heading|标题)\s*([1-6])", re.IGNORECASE)


def _docx_paragraph_text(paragraph: ET.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        tag = node.tag
        if tag == _w("t"):
            parts.append(node.text or "")
        elif tag == _w("tab"):
            parts.append("\t")
        elif tag in (_w("br"), _w("cr")):
            parts.append("\n")
    return "".join(parts)


def _docx_paragraph_style(paragraph: ET.Element) -> str:
    properties = paragraph.find(_w("pPr"))
    if properties is None:
        return ""
    style = properties.find(_w("pStyle"))
    if style is None:
        return ""
    return style.get(_w("val")) or ""


def _heading_level(style: str) -> int:
    if not style:
        return 0
    normalized = style.strip()
    if normalized.lower() in {"title", "标题"}:
        return 1
    match = _HEADING_STYLE_RE.search(normalized)
    if match:
        return int(match.group(1))
    if normalized in {"1", "2", "3", "4", "5", "6"}:
        return int(normalized)
    return 0


def _outline_level(paragraph: ET.Element) -> int:
    properties = paragraph.find(_w("pPr"))
    if properties is None:
        return 0
    outline = properties.find(_w("outlineLvl"))
    if outline is None:
        return 0
    value = outline.get(_w("val"))
    try:
        level = int(value) if value is not None else -1
    except (TypeError, ValueError):
        return 0
    return level + 1 if 0 <= level <= 8 else 0


def _handle_docx_paragraph(
    paragraph: ET.Element, stack: list[str], segments: list[dict]
) -> None:
    text = _docx_paragraph_text(paragraph)
    if not text.strip():
        return
    level = _heading_level(_docx_paragraph_style(paragraph)) or _outline_level(paragraph)
    if level:
        title = text.strip()
        stack[:] = stack[: level - 1] + [title]
        segments.append(
            {"kind": "heading", "text": title, "section_path": " > ".join(stack)}
        )
        return
    for piece in _split_paragraphs(text):
        segments.append(
            {"kind": "paragraph", "text": piece, "section_path": " > ".join(stack)}
        )


def _handle_docx_table(
    table: ET.Element, stack: list[str], segments: list[dict]
) -> None:
    rows: list[str] = []
    for row in table.findall(_w("tr")):
        cells: list[str] = []
        for cell in row.findall(_w("tc")):
            cell_text = " ".join(
                part
                for part in (
                    _docx_paragraph_text(p).strip() for p in cell.iter(_w("p"))
                )
                if part
            )
            cells.append(cell_text)
        if any(cells):
            rows.append("\t".join(cells))
    if rows:
        segments.append(
            {
                "kind": "table",
                "text": "\n".join(rows),
                "section_path": " > ".join(stack),
            }
        )


def _walk_docx(
    container: ET.Element, stack: list[str], segments: list[dict]
) -> None:
    for child in list(container):
        tag = child.tag
        if tag == _w("p"):
            _handle_docx_paragraph(child, stack, segments)
        elif tag == _w("tbl"):
            _handle_docx_table(child, stack, segments)
        elif tag in (_w("sdt"), _w("sdtContent"), _w("body")):
            _walk_docx(child, stack, segments)
        elif tag == _w("sectPr"):
            continue


def _parse_docx(data: bytes) -> ParsedDocument:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except Exception:
        return _failed(["docx_open_error"])

    warnings: list[str] = []
    try:
        names = set(archive.namelist())
        if "word/document.xml" not in names:
            return _failed(["docx_missing_document_xml"])
        try:
            document_root = ET.fromstring(archive.read("word/document.xml"))
        except Exception:
            return _failed(["docx_malformed_document_xml"])

        segments: list[dict] = []
        heading_stack: list[str] = []
        _walk_docx(document_root, heading_stack, segments)

        for part, kind in (
            ("word/footnotes.xml", "footnote"),
            ("word/endnotes.xml", "footnote"),
        ):
            if part not in names:
                continue
            try:
                root = ET.fromstring(archive.read(part))
            except Exception:
                warnings.append(f"{kind}_part_unreadable")
                continue
            for note in root:
                if note.tag not in (_w("footnote"), _w("endnote")):
                    continue
                note_type = note.get(_w("type")) or ""
                if note_type in {
                    "separator",
                    "continuationSeparator",
                    "continuationNotice",
                }:
                    continue
                note_text = "\n".join(
                    part_text
                    for part_text in (_docx_paragraph_text(p) for p in note.iter(_w("p")))
                    if part_text.strip()
                )
                if note_text.strip():
                    segments.append(
                        {
                            "kind": kind,
                            "text": note_text,
                            "section_path": "脚注" if kind == "footnote" else "尾注",
                        }
                    )
        return _result(segments, page_count=None, warnings=warnings)
    finally:
        try:
            archive.close()
        except Exception:  # pragma: no cover - 关闭失败不影响结果
            pass


# ── 数据文件（CSV / XLSX）：转成 Markdown 管道表 ──────────────────────
#
# 上传的 .csv / .xlsx 不当作“文档”抽段落，而是转成 Markdown 管道表写进版本
# 正文：图表侧 ``chart_data_source`` 只认 Markdown 管道表与 CSV 块，这样
# 数据文件与正文里的表格走同一条已验证的读表路径，不需要新增契约。
# 行数不在解析期截断（行上限由图表侧 ``RESEARCH_CHART_MAX_ROWS`` 判定 413），
# 只有整篇码点仍受 ``MAX_CODEPOINTS`` 约束：超限时保留已解析部分并记
# ``codepoint_limit_exceeded``，由服务层 ``validate_limits`` 抛 422。

#: 一份 XLSX 最多导入前 5 个 sheet；其余跳过并记 partial。
XLSX_MAX_SHEETS = 5
#: 单行最多保留的列数，防止误设格式把一张表撑成上万列。
XLSX_MAX_COLUMNS = 512
_CSV_DELIMITERS = (",", ";", "\t")
_CSV_SAMPLE_LINES = 20


def _escape_table_cell(value: object) -> str:
    """单元格 → 单行 Markdown 管道表内容：竖线转义、换行压平、去首尾空白。

    反斜杠先转义成 ``\\\\``，这样单元格里原本的 ``\\|`` 不会被读表侧当成
    “转义过的竖线”（:func:`chart_data_source._split_pipe_row` 会把 ``\\\\``
    还原成 ``\\``、``\\|`` 还原成 ``|``）。
    """
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
    return text.replace("\\", "\\\\").replace("|", "\\|").strip()


def _format_excel_number(value: float) -> str:
    """Excel 数值 → 十进制文本，避免 ``str(float)`` 的 e 记数法抖动。"""
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):  # pragma: no cover - 非数值输入
        return str(value)
    if not decimal.is_finite():  # pragma: no cover - openpyxl 不会产出 NaN/Inf
        return ""
    return format(decimal, "f")


def _cell_text(value: object) -> str:
    """把一个单元格值转成文本：空值 → 空串，数值 → 十进制，日期 → ISO。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _format_excel_number(value)
    if not isinstance(value, str):
        isoformat = getattr(value, "isoformat", None)
        if callable(isoformat):
            try:
                return str(isoformat())
            except Exception:  # pragma: no cover - 年份越界等异常日期
                return str(value)
    return str(value)


def _unique_columns(cells: Sequence[str], width: int) -> list[str]:
    """补齐/去重表头：空列名补 ``column_N``，重名加 ``_2`` 后缀。"""
    names: list[str] = []
    for index in range(width):
        raw = cells[index] if index < len(cells) else ""
        names.append(raw or f"column_{index + 1}")
    seen: dict[str, int] = {}
    result: list[str] = []
    for name in names:
        count = seen.get(name, 0)
        seen[name] = count + 1
        result.append(name if count == 0 else f"{name}_{count + 1}")
    return result


def _markdown_table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """表头 + 分隔行 + 数据行；所有行按 ``len(header)`` 补齐，保证结构合法。"""
    width = len(header)
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in range(width)) + " |",
    ]
    for row in rows:
        cells = list(row[:width]) + [""] * (width - len(row))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _detect_csv_delimiter(text: str) -> str:
    """按“字段数一致性”选 ``,`` / ``;`` / tab；都不像时退回 ``,``。"""
    lines = [line for line in text.split("\n") if line.strip()][:_CSV_SAMPLE_LINES]
    if not lines:
        return ","
    sample = "\n".join(lines)
    # (一致性, 众数字段数, -候选顺序, 分隔符)：一致优先，其次字段多，最后先试 ,
    best: tuple[float, int, int, str] = (0.0, 1, 0, ",")
    for index, delimiter in enumerate(_CSV_DELIMITERS):
        try:
            counts = [
                len(record)
                for record in csv.reader(io.StringIO(sample), delimiter=delimiter)
            ]
        except csv.Error:  # 引号未闭合等：该候选不可信
            continue
        counts = [count for count in counts if count > 0]
        if not counts:
            continue
        modal = max(set(counts), key=counts.count)
        if modal < 2:
            continue
        candidate = (counts.count(modal) / len(counts), modal, -index, delimiter)
        if candidate > best:
            best = candidate
    return best[3]


def _parse_csv(data: bytes) -> ParsedDocument:
    """CSV（UTF-8/BOM，``,`` / ``;`` / tab）→ 单张 Markdown 管道表。"""
    raw = _decode_utf8(data)
    if raw is None:
        return _failed(["csv_not_utf8_or_binary"])
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return _failed(["csv_empty"])
    delimiter = _detect_csv_delimiter(text)
    try:
        records = [
            record
            for record in csv.reader(io.StringIO(text), delimiter=delimiter)
            if any(cell.strip() for cell in record)
        ]
    except csv.Error:
        return _failed(["csv_parse_error"])
    if not records:
        return _failed(["csv_empty"])

    width = max(len(record) for record in records)
    header = _unique_columns(
        [_escape_table_cell(cell) for cell in records[0]], width
    )
    rows = [[_escape_table_cell(cell) for cell in record] for record in records[1:]]
    table = _markdown_table(header, rows)
    # 码点上限仍由 validate_limits 判定（超限 422），这里不静默截断。
    return _result(
        [{"kind": "table", "text": table, "section_path": ""}],
        page_count=None,
        warnings=[],
    )


def _xlsx_sheet_table(sheet, limit: int) -> tuple[Optional[str], bool]:
    """把一个 sheet 的“有数据区域”转成 Markdown 管道表。

    只保留首尾之间真正有内容的行/列；累计码点超过 ``limit`` 时停止读取并
    返回 ``truncated=True``（由调用方记 partial 并让服务层抛 422）。
    """
    rows: list[list[str]] = []
    width = 0
    used = 0
    truncated = False
    for raw_row in sheet.iter_rows(values_only=True):
        cells = [_escape_table_cell(_cell_text(value)) for value in raw_row]
        if len(cells) > XLSX_MAX_COLUMNS:
            cells = cells[:XLSX_MAX_COLUMNS]
            truncated = True
        while cells and not cells[-1]:
            cells.pop()
        if not cells or not any(cells):
            continue
        width = max(width, len(cells))
        rows.append(cells)
        used += sum(len(cell) for cell in cells) + 3 * len(cells)
        if used > limit:
            truncated = True
            break
    if not rows:
        return None, truncated
    header = _unique_columns(rows[0], width)
    body = [list(row) + [""] * (width - len(row)) for row in rows[1:]]
    return _markdown_table(header, body), truncated


def _safe_sheet_name(name: object) -> str:
    text = str(name or "").replace("\r", " ").replace("\n", " ")
    return (text.replace("|", "\\|").strip() or "Sheet")[:200]


def _parse_xlsx(data: bytes) -> ParsedDocument:
    """XLSX（openpyxl 只读）→ 每个 sheet 一张 Markdown 管道表 + 标题。"""
    try:
        from openpyxl import load_workbook  # 延迟导入：保持纯函数
    except Exception:  # pragma: no cover - 取决于运行环境
        return ParsedDocument(
            text="",
            blocks=[],
            page_count=None,
            parse_status=ParseStatus.UNSUPPORTED,
            warnings=["xlsx_parser_unavailable"],
        )

    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # 坏 zip / 非工作簿 / 加密工作簿
        return _failed([f"xlsx_open_error:{type(exc).__name__}"])

    warnings: list[str] = []
    segments: list[dict] = []
    used = 0
    try:
        try:
            sheet_names = list(workbook.sheetnames)
        except Exception:  # pragma: no cover - 结构损坏
            return _failed(["xlsx_sheet_list_error"])
        if len(sheet_names) > XLSX_MAX_SHEETS:
            warnings.append(
                f"xlsx_sheets_skipped:{len(sheet_names) - XLSX_MAX_SHEETS}"
            )
        for name in sheet_names[:XLSX_MAX_SHEETS]:
            try:
                table, truncated = _xlsx_sheet_table(
                    workbook[name], MAX_CODEPOINTS - used
                )
            except Exception as exc:  # 单个 sheet 损坏不影响其余 sheet
                warnings.append(f"sheet_unreadable:{type(exc).__name__}")
                continue
            if table is None:
                continue
            section = _safe_sheet_name(name)
            heading = f"## Sheet: {section}"
            segments.append(
                {"kind": "heading", "text": heading, "section_path": section}
            )
            segments.append(
                {"kind": "table", "text": table, "section_path": section}
            )
            used += len(heading) + len(table) + 2
            if truncated:
                warnings.append("xlsx_truncated")
                if used >= MAX_CODEPOINTS:
                    warnings.append("codepoint_limit_exceeded")
                break
    finally:
        try:
            workbook.close()
        except Exception:  # pragma: no cover - 关闭失败不影响结果
            pass
    return _result(segments, page_count=None, warnings=warnings)


# ── 对外入口 ─────────────────────────────────────────────────────────


def parse_document(data: bytes, filename: str, mime: str) -> ParsedDocument:
    """解析上传的原始字节；不会抛异常，失败通过 ``parse_status`` 表达。"""

    if not data:
        return _failed(["empty_file"])
    fmt, _normalized_mime = _detect_format(filename, mime)
    if fmt is None:
        return ParsedDocument(
            text="",
            blocks=[],
            page_count=None,
            parse_status=ParseStatus.UNSUPPORTED,
            warnings=[f"unsupported_media_type:{(mime or 'unknown').strip()[:100]}"],
        )
    try:
        if fmt == "text":
            return _parse_plain(data)
        if fmt == "markdown":
            return _parse_markdown(data)
        if fmt == "csv":
            return _parse_csv(data)
        if fmt == "xlsx":
            return _parse_xlsx(data)
        if fmt == "pdf":
            return _parse_pdf(data)
        return _parse_docx(data)
    except Exception as exc:  # 兜底：解析器内部错误不得变成 500 伪成功
        return _failed([f"parse_error:{type(exc).__name__}"])


def validate_limits(pages: Optional[int], codepoints: int) -> None:
    """校验解析成功文档的页数与码点上限（超限 422 ``DOCUMENT_TOO_LARGE``）。"""

    if pages is not None and pages > MAX_PAGES:
        raise invalid(
            "DOCUMENT_TOO_LARGE",
            f"文档页数不得超过 {MAX_PAGES} 页。",
            {"pages": int(pages), "max_pages": MAX_PAGES},
        )
    if codepoints > MAX_CODEPOINTS:
        raise invalid(
            "DOCUMENT_TOO_LARGE",
            f"文档文本不得超过 {MAX_CODEPOINTS} 码点。",
            {"codepoints": int(codepoints), "max_codepoints": MAX_CODEPOINTS},
        )


# ── 分块 ─────────────────────────────────────────────────────────────


def _split_long_text(text: str, base_start: int) -> list[tuple[str, int, int]]:
    """块内切分：窗口 1200 码点、重叠 100，优先在换行处截断。"""

    pieces: list[tuple[str, int, int]] = []
    length = len(text)
    step = CHUNK_MAX_CODEPOINTS - CHUNK_OVERLAP
    start = 0
    while start < length:
        end = min(start + CHUNK_MAX_CODEPOINTS, length)
        if end < length:
            window = text[start:end]
            newline = window.rfind("\n")
            if newline >= step:
                end = start + newline + 1
        piece = text[start:end]
        if piece:
            pieces.append((piece, base_start + start, base_start + end))
        if end >= length:
            break
        next_start = max(end - CHUNK_OVERLAP, start + 1)
        start = next_start
    return pieces


def build_chunks(blocks: Sequence[ParsedBlock]) -> list[ChunkSpec]:
    """把块组装为 800–1200 码点的检索分块（纯函数，便于测试）。

    规则：
    - 单块超过 1200 码点时必须切分，相邻窗口重叠 100 码点；
    - 相邻短块贪心打包，窗口总长不超过 1200，且累计到 ≥800 后即停止；
    - ``chunk.start`` / ``end`` 始终落在块边界或块内切分点上，可直接在
      规范化全文里切片核对。
    """

    chunks: list[ChunkSpec] = []
    total = len(blocks)
    index = 0
    while index < total:
        block = blocks[index]
        if block.end <= block.start or not block.text.strip():
            index += 1
            continue
        if len(block.text) > CHUNK_MAX_CODEPOINTS:
            for text, start, end in _split_long_text(block.text, block.start):
                chunks.append(
                    ChunkSpec(
                        ordinal=len(chunks),
                        block_ordinal=block.ordinal,
                        text=text,
                        start=start,
                        end=end,
                    )
                )
            index += 1
            continue

        window = [block]
        start = block.start
        end = block.end
        cursor = index + 1
        while cursor < total:
            if end - start >= CHUNK_MIN_CODEPOINTS:
                break
            following = blocks[cursor]
            if following.end <= start or following.end - start > CHUNK_MAX_CODEPOINTS:
                break
            window.append(following)
            end = following.end
            cursor += 1
        text = "".join(item.text for item in window)
        if text:
            chunks.append(
                ChunkSpec(
                    ordinal=len(chunks),
                    block_ordinal=block.ordinal,
                    text=text,
                    start=start,
                    end=end,
                )
            )
        index = cursor
    return chunks


__all__ = [
    "CHUNK_MAX_CODEPOINTS",
    "CHUNK_MIN_CODEPOINTS",
    "CHUNK_OVERLAP",
    "ChunkSpec",
    "ParsedBlock",
    "ParsedDocument",
    "build_chunks",
    "parse_document",
    "validate_limits",
]
