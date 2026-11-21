"""真实数据图表的表格来源（T22 / R2_INTERFACE_SPEC §2.1）。

本模块只做三件事，且全部可复现：

1. 从**已授权**的文档版本正文里识别表格：Markdown 管道表、```csv 代码块、
   以及紧邻的裸 CSV 行（连续、字段数一致、表头为文本）。
2. 把整张表转换成 :class:`TableData`：所有列都是有限浮点数，不插值、不丢行、
   不猜列类型；任何一格不是数值就整体失败。
3. 按调用方给定的显式列映射裁剪出 x/y 子表。

解析失败一律抛 ``ResearchAPIError``（422/413），绝不返回“部分数据”或占位表。
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from .contracts import Actor, text_hash
from .errors import ResearchAPIError, invalid
from .ownership import require_version

__all__ = ["TableData", "load_table", "select_columns"]

#: 三反引号 / 三波浪线围栏（允许最多 3 个前导空格与 info string）
_FENCE_RE = re.compile(r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})[ \t]*(?P<info>[^`~]*)$")
#: GFM 表格分隔行单元格：:---、---:、:---:、---
_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")
#: 用于判定 CSV 块/裸 CSV 是否是“带表头的数值表”
_NUMBER_PROBE_LIMIT = 400


@dataclass(frozen=True)
class TableData:
    """一张已解析、已校验的数值表。

    列顺序固定为调用方选择的 ``(x, *y)``；``rows`` 与 ``columns`` 等长，
    每个值都是有限浮点数（NaN/Inf 在 :func:`load_table` 阶段就被拒绝）。
    """

    columns: Tuple[str, ...]
    rows: Tuple[Tuple[float, ...], ...]
    table_index: int
    source_text_hash: str

    def column_index(self, name: str) -> int:
        try:
            return self.columns.index(name)
        except ValueError:
            raise invalid(
                "CHART_UNKNOWN_COLUMN",
                f"未知列：{name}",
                {"unknown": [name], "available": list(self.columns)},
            ) from None


@dataclass(frozen=True)
class _Candidate:
    """候选表的原始形态（单元格仍是文本，便于逐格报错）。"""

    columns: Tuple[str, ...]
    rows: Tuple[Tuple[str, ...], ...]
    start_line: int
    malformed: Optional[str] = None


# ── 文本切分 ─────────────────────────────────────────────


def _unescaped_tail_pipe(text: str) -> bool:
    """``text`` 末尾的竖线是否未被转义（前面反斜杠为偶数个）。"""
    backslashes = 0
    index = len(text) - 2
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 0


def _split_pipe_row(line: str) -> Optional[Tuple[str, ...]]:
    """把 ``| a | b |`` / ``a | b`` 切成单元格；没有竖线返回 ``None``。

    支持 Markdown 表格转义：``\\|`` 是字面竖线、``\\\\`` 是字面反斜杠，
    这样由 CSV/XLSX 导入生成的表（单元格内 ``|`` 会被转义）能原样读回。
    """
    stripped = line.strip()
    if "|" not in stripped:
        return None
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and _unescaped_tail_pipe(stripped):
        stripped = stripped[:-1]
    cells: list[str] = []
    current: list[str] = []
    index = 0
    length = len(stripped)
    while index < length:
        char = stripped[index]
        if char == "\\" and index + 1 < length:
            following = stripped[index + 1]
            if following in ("|", "\\"):
                current.append(following)
                index += 2
                continue
        if char == "|":
            cells.append("".join(current).strip())
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    cells.append("".join(current).strip())
    return tuple(cells)


def _parse_number(raw: str) -> Optional[float]:
    """严格解析有限浮点数；任何可疑写法都返回 ``None``（交由上层报 422）。"""
    text = (raw or "").strip().replace("\u00a0", "").replace("\u2212", "-")
    if not text:
        return None
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _header_problem(columns: Sequence[str]) -> Optional[str]:
    if any(not column for column in columns):
        return "表头存在空列名，无法按列名做显式映射"
    if len(set(columns)) != len(columns):
        return "表头存在重复列名，无法确定映射到哪一列"
    if len(columns) < 2:
        return f"只有 {len(columns)} 列，至少需要 1 个 x 列与 1 个 y 列"
    return None


def _looks_like_numeric_csv(columns: Sequence[str], rows: Sequence[Sequence[str]]) -> bool:
    """裸 CSV / 无 info 围栏的启发式判定：表头是文本、数据里确实有数。"""
    if not columns or not rows:
        return False
    if _header_problem(columns) is not None:
        return False
    if any(_parse_number(column) is not None for column in columns):
        return False
    probed = list(rows[:_NUMBER_PROBE_LIMIT])
    cells = [cell for row in probed for cell in row]
    if not cells:
        return False
    numeric = sum(1 for cell in cells if _parse_number(cell) is not None)
    return numeric * 2 >= len(cells)


# ── 候选表解析 ───────────────────────────────────────────


def _parse_csv_block(block: Sequence[str]) -> Tuple[Tuple[str, ...], Tuple[Tuple[str, ...], ...], Optional[str]]:
    """解析 CSV 行块，返回 ``(columns, rows, problem)``；空行按空白处理。"""
    if not any(line.strip() for line in block):
        return (), (), None
    records: list[list[str]] = []
    try:
        for record in csv.reader(io.StringIO("\n".join(block))):
            if not record or all(not cell.strip() for cell in record):
                continue
            records.append([cell.strip() for cell in record])
    except csv.Error as exc:  # 引号未闭合等
        return (), (), f"CSV 解析失败：{exc}"
    if not records:
        return (), (), None
    columns = tuple(records[0])
    body = tuple(tuple(record) for record in records[1:])
    for offset, record in enumerate(body):
        if len(record) != len(columns):
            return (
                columns,
                (),
                f"CSV 第 {offset + 2} 条记录的字段数为 {len(record)}，与表头的 {len(columns)} 列不一致",
            )
    problem = _header_problem(columns)
    return columns, body, problem


def _fenced_candidate(block: Sequence[str], info: str, start_line: int) -> Optional[_Candidate]:
    """``info`` 指明 csv 时严格解析；无 info 时仅在像数值表时采纳。"""
    token = (info or "").strip().lower()
    if token:
        head = token.replace(",", " ").split()[0]
        if head not in {"csv", "text/csv"}:
            return None
        explicit = True
    else:
        explicit = False
    columns, rows, problem = _parse_csv_block(block)
    if not explicit:
        if problem is not None or not _looks_like_numeric_csv(columns, rows):
            return None
        return _Candidate(columns=columns, rows=rows, start_line=start_line)
    return _Candidate(columns=columns, rows=rows, start_line=start_line, malformed=problem)


def _pipe_candidate(lines: Sequence[str], start: int) -> Optional[Tuple[_Candidate, int]]:
    """识别 ``表头 + 分隔行 + 数据行`` 的 Markdown 管道表。"""
    header = _split_pipe_row(lines[start])
    if header is None or len(header) < 2:
        return None
    if start + 1 >= len(lines):
        return None
    separator = _split_pipe_row(lines[start + 1])
    if separator is None or len(separator) != len(header):
        return None
    if not all(_SEPARATOR_CELL_RE.match(cell) for cell in separator):
        return None

    body: list[Tuple[str, ...]] = []
    problem = _header_problem(header)
    index = start + 2
    while index < len(lines):
        raw = lines[index]
        if not raw.strip() or _FENCE_RE.match(raw):
            break
        cells = _split_pipe_row(raw)
        if cells is None:
            break
        if len(cells) != len(header):
            problem = (
                f"第 {index + 1} 行的列数为 {len(cells)}，与表头的 {len(header)} 列不一致"
            )
            index += 1
            break
        body.append(cells)
        index += 1
    candidate = _Candidate(
        columns=tuple(header),
        rows=() if problem else tuple(body),
        start_line=start + 1,
        malformed=problem,
    )
    return candidate, index


def _raw_csv_candidate(lines: Sequence[str], start: int) -> Optional[Tuple[_Candidate, int]]:
    """识别表格间隙里连续出现的裸 CSV 行（不带竖线、字段数一致）。"""
    first = lines[start]
    if "," not in first or "|" in first or not first.strip():
        return None
    end = start
    while end < len(lines):
        line = lines[end]
        if not line.strip() or "," not in line or "|" in line or _FENCE_RE.match(line):
            break
        end += 1
    if end - start < 2:
        return None
    columns, rows, problem = _parse_csv_block(lines[start:end])
    if problem is not None or not _looks_like_numeric_csv(columns, rows):
        return None
    return _Candidate(columns=columns, rows=rows, start_line=start + 1), end


def _find_fence_end(lines: Sequence[str], start: int, fence: str) -> Optional[int]:
    character = fence[0]
    needed = len(fence)
    for index in range(start + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith(character * needed) and set(stripped) == {character}:
            return index
    return None


def _extract_candidates(text: str) -> list[_Candidate]:
    """按出现顺序返回文档里的所有候选表（含结构损坏的，用于稳定 table_index）。"""
    lines = (text or "").splitlines()
    candidates: list[_Candidate] = []
    total = len(lines)
    index = 0
    while index < total:
        fence = _FENCE_RE.match(lines[index])
        if fence:
            closing = _find_fence_end(lines, index, fence.group("fence"))
            block = lines[index + 1 : closing] if closing is not None else lines[index + 1 :]
            candidate = _fenced_candidate(block, fence.group("info"), index + 1)
            if candidate is not None:
                candidates.append(candidate)
            index = (closing + 1) if closing is not None else total
            continue

        pipe = _pipe_candidate(lines, index)
        if pipe is not None:
            candidate, index = pipe
            candidates.append(candidate)
            continue

        raw = _raw_csv_candidate(lines, index)
        if raw is not None:
            candidate, index = raw
            candidates.append(candidate)
            continue

        index += 1

    candidates.sort(key=lambda candidate: candidate.start_line)
    return candidates


# ── 对外接口 ─────────────────────────────────────────────


async def load_table(
    db: AsyncSession,
    actor: Actor,
    *,
    document_version_id: str,
    table_index: int = 0,
) -> TableData:
    """读取授权文档版本中的第 ``table_index`` 张数值表（T22）。

    任何结构问题、越界、超行数、非数值都会抛 ``ResearchAPIError``；
    跨用户/不存在的版本由 :func:`require_version` 直接 404，不泄露存在性。
    """
    version = await require_version(db, actor, document_version_id)
    text = version.text or ""
    candidates = _extract_candidates(text)

    try:
        index = int(table_index)
    except (TypeError, ValueError):
        index = -1
    if index < 0:
        raise invalid(
            "CHART_NO_TABLE",
            f"表格序号非法：{table_index!r}。",
            {"table_index": table_index, "tables_found": len(candidates)},
        )
    if not candidates:
        raise invalid(
            "CHART_NO_TABLE",
            "文档版本中没有可用数据表（需 Markdown 管道表或 CSV 块）。",
            {"document_version_id": version.id, "tables_found": 0},
        )
    if index >= len(candidates):
        raise invalid(
            "CHART_NO_TABLE",
            f"表格序号 {index} 超出范围，该版本共有 {len(candidates)} 张表。",
            {"table_index": index, "tables_found": len(candidates)},
        )

    candidate = candidates[index]
    if candidate.malformed:
        raise invalid(
            "CHART_TABLE_INVALID",
            f"第 {index} 张表结构不合法：{candidate.malformed}",
            {"table_index": index, "line": candidate.start_line, "reason": candidate.malformed},
        )
    if not candidate.columns or not candidate.rows:
        raise invalid(
            "CHART_EMPTY_DATA",
            "选中的表格没有数据行，无法出图。",
            {"table_index": index, "columns": list(candidate.columns), "row_count": len(candidate.rows)},
        )

    max_rows = int(getattr(settings, "RESEARCH_CHART_MAX_ROWS", 5_000) or 0)
    if max_rows > 0 and len(candidate.rows) > max_rows:
        raise ResearchAPIError(
            "CHART_TOO_MANY_ROWS",
            413,
            f"表格有 {len(candidate.rows)} 行，超过上限 {max_rows} 行；不支持静默丢行或抽样。",
            details={"table_index": index, "row_count": len(candidate.rows), "max_rows": max_rows},
        )

    converted: list[Tuple[float, ...]] = []
    for offset, raw_row in enumerate(candidate.rows):
        values: list[float] = []
        for column_index, raw in enumerate(raw_row):
            value = _parse_number(raw)
            if value is None:
                column = candidate.columns[column_index]
                raise invalid(
                    "CHART_NON_NUMERIC",
                    f"第 {offset + 1} 行「{column}」列的值 {raw!r} 不是有限数值。",
                    {
                        "table_index": index,
                        "column": column,
                        "row": offset + 1,
                        "value": raw,
                        "hint": (
                            "当前版本只支持全数值表（含 x 列）；分类轴（如变量名、年份文本）"
                            "暂不支持，请改用数值列作为 x 轴或先转换为数值编码。"
                        ),
                    },
                )
            values.append(value)
        converted.append(tuple(values))

    return TableData(
        columns=candidate.columns,
        rows=tuple(converted),
        table_index=index,
        source_text_hash=version.content_hash or text_hash(text),
    )


def select_columns(
    table: TableData,
    *,
    x_column: str,
    y_columns: Sequence[str],
) -> TableData:
    """按显式列映射裁剪出 ``(x, *y)`` 子表；未知列 422，重复列/与 x 重叠的列去重。"""
    available = list(table.columns)
    x_name = (x_column or "").strip()
    requested = [(str(name) or "").strip() for name in (y_columns or ())]
    requested = [name for name in requested if name]

    unknown = [name for name in [x_name, *requested] if name and name not in available]
    if not x_name:
        unknown = [""] + unknown
    deduped_unknown = list(dict.fromkeys(unknown))
    if deduped_unknown:
        raise invalid(
            "CHART_UNKNOWN_COLUMN",
            f"未知列：{'、'.join(deduped_unknown)}",
            {"unknown": deduped_unknown, "available": available},
        )
    if not requested:
        raise invalid(
            "CHART_TABLE_INVALID",
            "至少需要一个 y 列才能定义图表的纵轴。",
            {"x_column": x_name, "available": available},
        )

    plotted: list[str] = []
    for name in requested:
        if name == x_name:
            # x 列同时出现在 y 列表里属于重复选择：去重而不是报错，避免前端把整列清单直传时误 422。
            continue
        if name not in plotted:
            plotted.append(name)
    if not plotted:
        raise invalid(
            "CHART_TABLE_INVALID",
            f"y 列去重后为空（x 列「{x_name}」不能作为唯一纵轴）。",
            {"x_column": x_name, "y_columns": requested, "available": available},
        )

    if not table.rows:
        raise invalid(
            "CHART_EMPTY_DATA",
            "选中的表格没有数据行，无法出图。",
            {"table_index": table.table_index, "columns": available},
        )

    indexes = [table.columns.index(x_name), *(table.columns.index(name) for name in plotted)]
    rows = tuple(tuple(row[position] for position in indexes) for row in table.rows)
    return TableData(
        columns=(x_name, *plotted),
        rows=rows,
        table_index=table.table_index,
        source_text_hash=table.source_text_hash,
    )
