"""真实数据图表服务（T22 / R2_INTERFACE_SPEC §2.2）。

契约要点：

* 只接受**已授权文档版本**中的数值表，跨项目/跨用户一律 404，不泄露存在性；
* 开关 ``ENABLE_VERIFIED_CHARTS`` 关闭时直接 503 ``CHART_CAPABILITY_DISABLED``，
  绝不做占位图兜底；
* 渲染异常转 500 ``CHART_RENDER_FAILED``（retryable），且**不落任何 Artifact**；
* 成果为 ``kind="chart"`` 的 PNG（base64 正文 + ``encoding="base64"``），
  ``validation_json`` 完整记录来源、行数、列映射、逐列值域、数据摘要与 PNG 摘要，
  保证同一份数据可以复算、比对。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..services.chart_service import CHART_FUNCTIONS, CHART_NAMES
from . import artifact_service
from .chart_data_source import (
    SeriesTable,
    TableData,
    load_series_table,
    load_table,
    select_columns,
    select_series,
)
from .chart_render import (
    BASIC_CHART_TYPES,
    CHART_DPI,
    CHART_HEIGHT,
    CHART_WIDTH,
    build_payload,
    data_digest,
    render_chart_png,
    render_series_png,
    series_digest,
    series_value_ranges,
    value_ranges,
)
from .contracts import Actor
from .errors import ResearchAPIError, invalid, not_found, unavailable
from .models import Artifact, Document
from .ownership import require_project, require_task, require_version

__all__ = ["BASIC_CHART_TYPES", "CHART_TYPES", "chart_capability", "create_chart"]

#: 12 种灰阶学术图 + 2 种支持分类 x 轴的基础图（bar/line）
CHART_TYPES = frozenset(CHART_FUNCTIONS) | frozenset(BASIC_CHART_TYPES)

#: 基础图的展示名（``CHART_NAMES`` 里没有这两个键）
BASIC_CHART_NAMES = {"bar": "分类柱状图", "line": "分类折线图"}

#: 与路由层 ChartRequest.title 的上限保持一致
_MAX_TITLE_LENGTH = 200


def chart_capability() -> dict:
    """返回 ``{"enabled": bool, "reason": str}``，供 capabilities/路由前置判断。"""
    enabled = bool(getattr(settings, "ENABLE_VERIFIED_CHARTS", False))
    if not enabled:
        return {
            "enabled": False,
            "reason": (
                "ENABLE_VERIFIED_CHARTS 未开启（FR-13/T22：图表能力已收敛到真实数据图表），"
                "当前不提供任何图表生成或占位图兜底。"
            ),
        }
    return {
        "enabled": True,
        "reason": "ENABLE_VERIFIED_CHARTS 已开启：仅对授权文档版本中的数值表按显式列映射出图。",
    }


def _normalize_type(chart_type: str) -> str:
    normalized = (chart_type or "").strip().lower()
    if normalized not in CHART_TYPES:
        raise invalid(
            "CHART_UNSUPPORTED_TYPE",
            f"不支持的图表类型：{chart_type!r}",
            {"chart_type": chart_type, "supported": sorted(CHART_TYPES)},
        )
    return normalized


def _normalize_columns(x_column: str, y_columns: Sequence[str]) -> tuple[str, list[str]]:
    x_name = (x_column or "").strip()
    y_names = [str(name).strip() for name in (y_columns or ()) if str(name).strip()]
    if not x_name or not y_names:
        raise invalid(
            "CHART_TABLE_INVALID",
            "必须显式指定 x 列与至少一个 y 列（本能力不做自动猜列）。",
            {"x_column": x_column, "y_columns": list(y_columns or ())},
        )
    return x_name, y_names


def _pseudo_task_id(owner_id: int, document_version_id: str) -> str:
    """路由未携带 task_id 时生成稳定伪任务号，保证同一版本可重复出图并累积版本。"""
    seed = f"{owner_id}:{document_version_id}".encode("utf-8")
    return "chart_" + hashlib.sha256(seed).hexdigest()[:24]


async def _resolve_task_id(
    db: AsyncSession,
    actor: Actor,
    *,
    task_id: str | None,
    project_id: str,
    document_version_id: str,
) -> str:
    if not task_id:
        return _pseudo_task_id(actor.user_id, document_version_id)
    task = await require_task(db, actor, task_id)
    if task.project_id != project_id:
        raise not_found("任务")
    return str(task.id)


async def create_chart(
    db: AsyncSession,
    actor: Actor,
    *,
    project_id: str,
    document_version_id: str,
    chart_type: str,
    x_column: str,
    y_columns: Sequence[str],
    title: str | None = None,
    table_index: int = 0,
    task_id: str | None = None,
) -> Artifact:
    """从授权文档版本的数值表渲染真实图表并落成 ``kind="chart"`` 成果。

    错误码：503 CHART_CAPABILITY_DISABLED、422 CHART_UNSUPPORTED_TYPE /
    CHART_NO_TABLE / CHART_TABLE_INVALID / CHART_UNKNOWN_COLUMN /
    CHART_NON_NUMERIC / CHART_EMPTY_DATA、413 CHART_TOO_MANY_ROWS、
    500 CHART_RENDER_FAILED，以及 404 越权/不存在。
    """
    capability = chart_capability()
    if not capability["enabled"]:
        raise unavailable(
            "CHART_CAPABILITY_DISABLED",
            "图表能力未开启：" + capability["reason"],
            {"capability": "chart_generation", "setting": "ENABLE_VERIFIED_CHARTS"},
        )

    normalized_type = _normalize_type(chart_type)
    x_name, y_names = _normalize_columns(x_column, y_columns)

    project = await require_project(db, actor, project_id)
    version = await require_version(db, actor, document_version_id)
    document = await db.get(Document, version.document_id)
    if document is None or document.project_id != project.id:
        raise not_found("文档版本")
    resolved_task_id = await _resolve_task_id(
        db,
        actor,
        task_id=task_id,
        project_id=project.id,
        document_version_id=version.id,
    )

    chart_label = CHART_NAMES.get(normalized_type) or BASIC_CHART_NAMES.get(normalized_type, normalized_type)
    basic = normalized_type in BASIC_CHART_TYPES
    extra_validation: dict = {}

    if basic:
        series: SeriesTable = await load_series_table(
            db,
            actor,
            document_version_id=version.id,
            table_index=table_index,
        )
        selected_series = select_series(series, x_column=x_name, y_columns=y_names)
        x_label = selected_series.x_name
        stacked = "、".join(selected_series.y_columns)
        title_text = (title or "").strip() or f"{chart_label}：{x_label} 对 {stacked}"
        title_text = title_text[:_MAX_TITLE_LENGTH]
        try:
            rendered = await asyncio.to_thread(
                render_series_png,
                normalized_type,
                selected_series,
                title=title_text,
                x_label=x_label,
                y_label=stacked,
            )
        except ResearchAPIError:
            raise
        except Exception as exc:  # 真实渲染器的任何异常都不允许变成占位图
            raise ResearchAPIError(
                "CHART_RENDER_FAILED",
                500,
                "图表渲染失败，未生成任何成果文件。",
                {"chart_type": normalized_type, "reason": f"{type(exc).__name__}: {exc}"[:300]},
                retryable=True,
            ) from exc
        digest = series_digest(selected_series)
        source_text_hash = selected_series.source_text_hash
        table_index_used = selected_series.table_index
        row_count = len(selected_series.x_labels)
        column_count = len(selected_series.y_columns) + 1
        x_column_used = selected_series.x_name
        y_columns_used = list(selected_series.y_columns)
        plotted_y = list(selected_series.y_columns)
        ranges = series_value_ranges(selected_series)
        cleaning_note = "x 列为分类标签（原样保留），y 列必须全数值；不插值、不丢弃行，非数值直接 422"
        extra_validation = {
            "x_mode": "categorical",
            "x_labels": list(selected_series.x_labels)[:200],
            "x_label_count": len(selected_series.x_labels),
        }
        renderer_entry = "src.backend.research.chart_render.render_series_png"
    else:
        table: TableData = await load_table(
            db,
            actor,
            document_version_id=version.id,
            table_index=table_index,
        )
        selected = select_columns(table, x_column=x_name, y_columns=y_names)
        payload = build_payload(normalized_type, selected)
        stacked = "、".join(payload.plotted_y_columns)
        title_text = (title or "").strip() or f"{chart_label}：{selected.columns[0]} 对 {stacked}"
        title_text = title_text[:_MAX_TITLE_LENGTH]
        try:
            rendered = await asyncio.to_thread(
                render_chart_png,
                normalized_type,
                payload,
                title=title_text,
                x_label=selected.columns[0],
                y_label=stacked,
            )
        except ResearchAPIError:
            raise
        except Exception as exc:  # 真实渲染器的任何异常都不允许变成占位图
            raise ResearchAPIError(
                "CHART_RENDER_FAILED",
                500,
                "图表渲染失败，未生成任何成果文件。",
                {"chart_type": normalized_type, "reason": f"{type(exc).__name__}: {exc}"[:300]},
                retryable=True,
            ) from exc
        digest = data_digest(selected)
        source_text_hash = table.source_text_hash
        table_index_used = selected.table_index
        row_count = len(selected.rows)
        column_count = len(selected.columns)
        x_column_used = selected.columns[0]
        y_columns_used = list(selected.columns[1:])
        plotted_y = list(payload.plotted_y_columns)
        ranges = value_ranges(selected)
        cleaning_note = "只接受全数值列；不插值、不丢弃行，非数值直接 422"
        renderer_entry = "src.backend.research.chart_render.render_chart_png"

    validation = {
        "chart_type": normalized_type,
        "chart_title": title_text,
        "encoding": "base64",
        "source_document_version_id": version.id,
        "source_document_id": version.document_id,
        "source_content_hash": version.content_hash or source_text_hash,
        "table_index": table_index_used,
        "row_count": row_count,
        "column_count": column_count,
        "x_column": x_column_used,
        "y_columns": y_columns_used,
        "plotted_y_columns": plotted_y,
        "value_ranges": ranges,
        "data_digest": digest,
        "data_digest_scope": "selected_table",
        # FR-13：清洗/缺失值策略必须显式留痕，哪怕策略就是"不清洗、非数值即拒绝"。
        "cleaning": {
            "steps": [],
            "missing_value_policy": "reject",
            "filtered_rows": 0,
            "note": cleaning_note,
        },
        "render_verified": True,
        "png_sha256": rendered.png_sha256,
        "png_width": rendered.width,
        "png_height": rendered.height,
        "renderer": {
            "entry": renderer_entry,
            "chart_type": normalized_type,
            "width": CHART_WIDTH,
            "height": CHART_HEIGHT,
            "dpi": CHART_DPI,
        },
        **extra_validation,
    }

    body = base64.b64encode(rendered.png).decode("ascii")
    return await artifact_service.create_artifact(
        db,
        owner_id=actor.user_id,
        task_id=resolved_task_id,
        kind="chart",
        body=body,
        mime="image/png",
        filename=f"{normalized_type}-{digest[:8]}.png",
        validation=validation,
    )
