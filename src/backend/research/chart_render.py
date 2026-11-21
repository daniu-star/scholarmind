"""真实数据图表的渲染层（T22 / R2_INTERFACE_SPEC §2.2）。

职责边界：

* **不**调用 ``services.chart_service.generate_chart`` —— 那个入口会吞掉异常并
  返回“图表生成失败”占位图（``src/backend/services/chart_service.py:74-128``）。
  这里直接调用 ``CHART_FUNCTIONS[chart_type]``，异常原样上抛，由服务层转 500。
* 不做任何兜底 / 随机占位：``heatmap_dendro`` 在非二维输入时会 ``np.random.rand``，
  所以本模块永远传真正的二维矩阵；行列数不足以构成二维数据时提前 422。
* 输出只接受带合法 PNG 签名与 IHDR 的字节流，尺寸、哈希都来自这一次真实渲染。

matplotlib 全局状态不是线程安全的，渲染全程持有模块级 ``threading.Lock``，
并在结束后只清理“本次新建”的 figure（seaborn clustermap 会额外建图）。
"""

from __future__ import annotations

import csv
import hashlib
import io
import struct
import threading
from dataclasses import dataclass
from typing import Any, Mapping, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  (必须在 use("Agg") 之后导入)
from matplotlib import font_manager  # noqa: E402

from ..services.chart_service import CHART_FUNCTIONS  # noqa: E402
from .chart_data_source import SeriesTable, TableData  # noqa: E402
from .errors import invalid  # noqa: E402

__all__ = [
    "BASIC_CHART_TYPES",
    "CHART_DPI",
    "CHART_HEIGHT",
    "CHART_WIDTH",
    "ChartPayload",
    "RenderedChart",
    "build_payload",
    "canonical_csv",
    "canonical_series_csv",
    "data_digest",
    "render_chart_png",
    "render_series_png",
    "series_digest",
    "series_value_ranges",
    "value_ranges",
]

#: 与 ``services/chart_service`` 的默认值保持一致（1200x800 像素、dpi=300）
CHART_WIDTH = 1200
CHART_HEIGHT = 800
CHART_DPI = 300

#: 这些图表的语义就是二维标量场，少于两列 y 时渲染器必然失败，提前 422。
_MIN_Y_COLUMNS = {"contour": 2, "heatmap_dendro": 2}

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MIN_PNG_BYTES = 256
_RENDER_LOCK = threading.Lock()

#: 首选 CJK 字体（Windows 默认有雅黑/黑体；Linux 容器可装 Noto）
_CJK_FONT_CANDIDATES = (
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "WenQuanYi Zen Hei",
    "PingFang SC",
)


def _configure_fonts() -> str | None:
    """让中文标题/标签真正能被渲染出来，而不是变成方框（首次调用生效）。

    返回选中的字体名（无可用 CJK 字体时返回 ``None``，此时 matplotlib 告警
    ``Glyph missing`` 属已知环境限制，中文标签会显示为方框）。
    """
    try:
        available = {font.name for font in font_manager.fontManager.ttflist}
    except Exception:  # pragma: no cover - 字体库异常不应影响出图
        return None
    chosen = next((name for name in _CJK_FONT_CANDIDATES if name in available), None)
    if chosen:
        plt.rcParams["font.sans-serif"] = [chosen, "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    return chosen


@dataclass(frozen=True)
class ChartPayload:
    """一次渲染所需的纯数据（不含标题），便于单测与复现。"""

    data: Any
    options: Mapping[str, Any]
    plotted_y_columns: Tuple[str, ...]


@dataclass(frozen=True)
class RenderedChart:
    """真实渲染结果；``png`` 已通过签名/尺寸校验。"""

    png: bytes
    width: int
    height: int

    @property
    def png_sha256(self) -> str:
        return hashlib.sha256(self.png).hexdigest()


def _format_value(value: float) -> str:
    """把数值变成稳定、跨平台一致的标签（整数不带小数点）。"""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(float(value))


def build_payload(chart_type: str, table: TableData) -> ChartPayload:
    """把 ``(x, *y)`` 子表映射成对应图表函数要求的入参形状。

    映射规则（与 ``services/chart_functions`` 的 docstring 一一对应）：

    * ``gradient_area`` / ``scatter_density``：``[(x, y)]``，单系列
    * ``bubble_kde``：``[(x, y, size)]``，只有一个 y 时退化为 ``[(x, y)]``
    * ``ribbon``：``[(x, [y1, y2, ...])]``，多层堆叠
    * ``violin`` / ``swarm``：``{列名: 数值列表}``
    * ``parallel``：``{x: [...], y1: [...]}``，显式 ``class_col=x``
    * ``chord`` / ``alluvial``：``[(x 取值标签, y 列名, 数值)]``
    * ``surface3d`` / ``contour``：``[(行序, 系列序, 数值)]`` 三维点列
    * ``heatmap_dendro``：行 × y 列的二维矩阵
    """
    if not table.columns or not table.rows:
        raise invalid(
            "CHART_EMPTY_DATA",
            "选中的表格没有可用于绘图的数据行。",
            {"table_index": table.table_index, "columns": list(table.columns)},
        )

    x_name = table.columns[0]
    y_names = list(table.columns[1:])
    xs = [row[0] for row in table.rows]
    series = {name: [row[position + 1] for row in table.rows] for position, name in enumerate(y_names)}

    required = _MIN_Y_COLUMNS.get(chart_type, 1)
    if len(y_names) < required:
        raise invalid(
            "CHART_TABLE_INVALID",
            f"{chart_type} 至少需要 {required} 个 y 列才能构成二维数据，当前只有 {len(y_names)} 个。",
            {"chart_type": chart_type, "y_columns": y_names, "required_y_columns": required},
        )

    if chart_type in {"gradient_area", "scatter_density"}:
        first = y_names[0]
        return ChartPayload(
            data=[[x, y] for x, y in zip(xs, series[first])],
            options={},
            plotted_y_columns=(first,),
        )

    if chart_type == "bubble_kde":
        plotted = tuple(y_names[:2])
        if len(plotted) == 2:
            data = [[x, y, size] for x, y, size in zip(xs, series[plotted[0]], series[plotted[1]])]
        else:
            data = [[x, y] for x, y in zip(xs, series[plotted[0]])]
        return ChartPayload(data=data, options={}, plotted_y_columns=plotted)

    if chart_type == "ribbon":
        return ChartPayload(
            data=[(xs, [series[name] for name in y_names])],
            options={},
            plotted_y_columns=tuple(y_names),
        )

    if chart_type in {"violin", "swarm"}:
        return ChartPayload(
            data={name: series[name] for name in y_names},
            options={},
            plotted_y_columns=tuple(y_names),
        )

    if chart_type == "parallel":
        frame: dict[str, list[float]] = {x_name: xs}
        frame.update({name: series[name] for name in y_names})
        return ChartPayload(data=frame, options={"class_col": x_name}, plotted_y_columns=tuple(y_names))

    if chart_type in {"chord", "alluvial"}:
        links: list[Tuple[str, str, float]] = []
        for row in table.rows:
            source = f"{x_name}={_format_value(row[0])}"
            for position, name in enumerate(y_names):
                links.append((source, name, row[position + 1]))
        return ChartPayload(data=links, options={}, plotted_y_columns=tuple(y_names))

    if chart_type == "heatmap_dendro":
        matrix = [[row[position + 1] for position in range(len(y_names))] for row in table.rows]
        return ChartPayload(
            data=matrix,
            options={"col_labels": list(y_names)},
            plotted_y_columns=tuple(y_names),
        )

    if chart_type in {"surface3d", "contour"}:
        # 用 (行序, 系列序, 数值) 三元组重建网格：两个坐标天然唯一，
        # 既不会像矩阵那样被渲染器按 “shape[1] == 3” 误判成 (x, y, z) 坐标表，
        # 也不会因为 x 存在重复值而被 np.unique 折叠掉数据。
        cells = [
            [float(row_index), float(column_index), table.rows[row_index][column_index + 1]]
            for row_index in range(len(table.rows))
            for column_index in range(len(y_names))
        ]
        return ChartPayload(data=cells, options={}, plotted_y_columns=tuple(y_names))

    raise invalid(
        "CHART_UNSUPPORTED_TYPE",
        f"不支持的图表类型：{chart_type}",
        {"supported": sorted(CHART_FUNCTIONS)},
    )


def canonical_csv(table: TableData) -> str:
    """规范化 CSV：列名 + ``repr(float)``，作为 ``data_digest`` 的唯一输入。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(table.columns)
    for row in table.rows:
        writer.writerow([repr(float(value)) for value in row])
    return buffer.getvalue()


def data_digest(table: TableData) -> str:
    """所选子表规范化 CSV 的 sha256（列顺序固定为 x + y1..yn）。"""
    return hashlib.sha256(canonical_csv(table).encode("utf-8")).hexdigest()


def value_ranges(table: TableData) -> dict[str, dict[str, float]]:
    """逐列的 min/max，供 ``validation_json`` 审计。"""
    result: dict[str, dict[str, float]] = {}
    for position, name in enumerate(table.columns):
        values = [row[position] for row in table.rows]
        result[name] = {"min": float(min(values)), "max": float(max(values))}
    return result


def _verify_png(png: bytes) -> Tuple[int, int]:
    """校验 PNG 签名与 IHDR，返回像素宽高；不合法就抛 ValueError。"""
    if not png.startswith(_PNG_SIGNATURE):
        raise ValueError("渲染结果不是 PNG 字节流")
    if len(png) < _MIN_PNG_BYTES:
        raise ValueError(f"渲染结果体积异常（{len(png)} 字节）")
    if png[12:16] != b"IHDR":
        raise ValueError("PNG 缺少 IHDR 头")
    width, height = struct.unpack(">II", png[16:24])
    if width <= 0 or height <= 0:
        raise ValueError(f"PNG 尺寸非法：{width}x{height}")
    return int(width), int(height)


def render_chart_png(
    chart_type: str,
    payload: ChartPayload,
    *,
    title: str,
    x_label: str,
    y_label: str,
) -> RenderedChart:
    """调用真实图表函数渲染 PNG；任何异常原样上抛（服务层转 500）。"""
    _configure_fonts()
    function = CHART_FUNCTIONS.get(chart_type)
    if function is None:
        raise invalid(
            "CHART_UNSUPPORTED_TYPE",
            f"不支持的图表类型：{chart_type}",
            {"supported": sorted(CHART_FUNCTIONS)},
        )

    buffer = io.BytesIO()
    with _RENDER_LOCK:
        existing = set(plt.get_fignums())
        figure = None
        try:
            figure = function(
                payload.data,
                title,
                x_label,
                y_label,
                width=CHART_WIDTH,
                height=CHART_HEIGHT,
                dpi=CHART_DPI,
                **dict(payload.options),
            )
            figure.savefig(
                buffer,
                format="png",
                dpi=CHART_DPI,
                bbox_inches="tight",
                facecolor="#FFFFFF",
            )
            png = buffer.getvalue()
        finally:
            for number in plt.get_fignums():
                if number not in existing:
                    plt.close(number)
            if figure is not None:
                plt.close(figure)
            buffer.close()

    width, height = _verify_png(png)
    return RenderedChart(png=png, width=width, height=height)


# ── 基础图表（bar / line）：分类 x 轴 ─────────────────────

#: 分类轴基础图表的类型集合（与 ``chart_service.BASIC_CHART_TYPES`` 保持一致）
BASIC_CHART_TYPES = frozenset({"bar", "line"})

#: 灰阶学术配色与标记，按系列循环；不引入彩色，保证打印/灰度阅读可分辨
_SERIES_COLORS = ("#2F2F2F", "#5C5C5C", "#8A8A8A", "#B5B5B5")
_SERIES_HATCHES = ("", "//", "..", "xx")
_SERIES_MARKERS = ("o", "s", "^", "D")


def canonical_series_csv(series: "SeriesTable") -> str:
    """分类表的规范化 CSV：分类标签 + ``repr(float)``（``data_digest`` 的唯一输入）。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([series.x_name, *series.y_columns])
    for label, row in zip(series.x_labels, series.rows):
        writer.writerow([label, *(repr(float(value)) for value in row)])
    return buffer.getvalue()


def series_digest(series: "SeriesTable") -> str:
    """分类表规范化 CSV 的 sha256；标签参与摘要，改标签即换摘要。"""
    return hashlib.sha256(canonical_series_csv(series).encode("utf-8")).hexdigest()


def series_value_ranges(series: "SeriesTable") -> dict[str, dict[str, float]]:
    """逐 y 列 min/max；分类轴没有数值域，不出现在结果里（不伪造 0/1 编码）。"""
    result: dict[str, dict[str, float]] = {}
    for position, name in enumerate(series.y_columns):
        values = [row[position] for row in series.rows]
        result[name] = {"min": float(min(values)), "max": float(max(values))}
    return result


def _new_axes(*, title: str, x_label: str, y_label: str):
    """白底黑框、内向刻度的学术风格画布（与 12 种图表保持一致的观感）。"""
    _configure_fonts()
    figure, axes = plt.subplots(
        figsize=(CHART_WIDTH / CHART_DPI, CHART_HEIGHT / CHART_DPI),
        dpi=CHART_DPI,
    )
    figure.patch.set_facecolor("#FFFFFF")
    axes.set_facecolor("#FFFFFF")
    # 中文标题较长时按 24 字换行，避免整行顶到画布边缘被裁切。
    wrapped = "\n".join(
        title[index : index + 24] for index in range(0, len(title), 24)
    ) or title
    axes.set_title(wrapped, fontsize=13, fontweight="bold", pad=12)
    axes.set_xlabel(x_label, fontsize=12, labelpad=10)
    axes.set_ylabel(y_label, fontsize=12, labelpad=10)
    axes.tick_params(axis="both", direction="in", length=4, labelsize=10)
    for spine in axes.spines.values():
        spine.set_edgecolor("#1F1F1F")
        spine.set_linewidth(1.2)
    return figure, axes


def _style_x_axis(axes, labels: Tuple[str, ...]) -> None:
    """分类刻度：超过 8 类就旋转 45°，避免标签互相覆盖。"""
    axes.set_xticks(range(len(labels)))
    rotation = 45 if len(labels) > 8 else 0
    axes.set_xticklabels(labels, rotation=rotation, ha="right" if rotation else "center")


def _bar_figure(series: "SeriesTable", *, title: str, x_label: str, y_label: str):
    figure, axes = _new_axes(title=title, x_label=x_label, y_label=y_label)
    count = len(series.y_columns)
    # 组内留 10% 间隙，避免相邻柱完全贴合被误读成一组。
    slot = 0.8 / max(count, 1)
    width = slot * 0.9
    for position, name in enumerate(series.y_columns):
        offsets = [index + (position - (count - 1) / 2) * slot for index in range(len(series.x_labels))]
        axes.bar(
            offsets,
            [row[position] for row in series.rows],
            width=width,
            label=name,
            color=_SERIES_COLORS[position % len(_SERIES_COLORS)],
            hatch=_SERIES_HATCHES[position % len(_SERIES_HATCHES)],
            edgecolor="#1F1F1F",
            linewidth=0.8,
        )
    _style_x_axis(axes, series.x_labels)
    if count > 1:
        axes.legend(frameon=False, fontsize=10)
    return figure


def _line_figure(series: "SeriesTable", *, title: str, x_label: str, y_label: str):
    figure, axes = _new_axes(title=title, x_label=x_label, y_label=y_label)
    for position, name in enumerate(series.y_columns):
        axes.plot(
            range(len(series.x_labels)),
            [row[position] for row in series.rows],
            label=name,
            color=_SERIES_COLORS[position % len(_SERIES_COLORS)],
            linestyle=("--" if position % 2 else "-"),
            marker=_SERIES_MARKERS[position % len(_SERIES_MARKERS)],
            markersize=5,
            linewidth=1.8,
        )
    _style_x_axis(axes, series.x_labels)
    if len(series.y_columns) > 1:
        axes.legend(frameon=False, fontsize=10)
    return figure


_SERIES_RENDERERS = {"bar": _bar_figure, "line": _line_figure}


def render_series_png(
    chart_type: str,
    series: "SeriesTable",
    *,
    title: str,
    x_label: str,
    y_label: str,
) -> RenderedChart:
    """渲染分类轴基础图表；异常原样上抛（服务层转 500），绝不回退占位图。"""
    renderer = _SERIES_RENDERERS.get(chart_type)
    if renderer is None:
        raise invalid(
            "CHART_UNSUPPORTED_TYPE",
            f"不支持的图表类型：{chart_type}",
            {"supported": sorted(BASIC_CHART_TYPES)},
        )

    buffer = io.BytesIO()
    with _RENDER_LOCK:
        existing = set(plt.get_fignums())
        figure = None
        try:
            figure = renderer(series, title=title, x_label=x_label, y_label=y_label)
            figure.savefig(
                buffer,
                format="png",
                dpi=CHART_DPI,
                bbox_inches="tight",
                facecolor="#FFFFFF",
            )
            png = buffer.getvalue()
        finally:
            for number in plt.get_fignums():
                if number not in existing:
                    plt.close(number)
            if figure is not None:
                plt.close(figure)
            buffer.close()

    width, height = _verify_png(png)
    return RenderedChart(png=png, width=width, height=height)
