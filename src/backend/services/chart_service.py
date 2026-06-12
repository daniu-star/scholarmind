"""
ScholarMind 学术图表生成服务
支持12种高级学术图表，Origin风格（白底黑框、大字体、学术配色）

重构后的入口模块：仅包含图表类型映射、主入口函数和向后兼容的 re-exports
"""

import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from typing import Any

# ── 向后兼容 re-exports ───────────────────────────────────
from .chart_style import ACADEMIC_COLORS, get_origin_style, _apply_origin_style
from .chart_data import parse_data_input, _safe_array, _make_figure, _finalize
from .chart_functions import (
    ribbon_chart, violin_chart, alluvial_chart, bubble_kde_chart,
    gradient_area_chart, surface3d_chart, parallel_chart, contour_chart,
    swarm_chart, scatter_density_chart, chord_chart, heatmap_dendro_chart,
)


# ── 图表类型映射 ──────────────────────────────────────────

CHART_FUNCTIONS = {
    "ribbon": ribbon_chart,
    "violin": violin_chart,
    "alluvial": alluvial_chart,
    "bubble_kde": bubble_kde_chart,
    "gradient_area": gradient_area_chart,
    "surface3d": surface3d_chart,
    "parallel": parallel_chart,
    "contour": contour_chart,
    "swarm": swarm_chart,
    "scatter_density": scatter_density_chart,
    "chord": chord_chart,
    "heatmap_dendro": heatmap_dendro_chart,
}

CHART_NAMES = {
    "ribbon": "缎带图",
    "violin": "小提琴图",
    "alluvial": "冲积图",
    "bubble_kde": "气泡散点+KDE图",
    "gradient_area": "梯度面积图",
    "surface3d": "3D地形图",
    "parallel": "平行坐标图",
    "contour": "等高线地形图",
    "swarm": "蜂群图",
    "scatter_density": "散点密度图",
    "chord": "和弦图",
    "heatmap_dendro": "热力聚类图",
}

CHART_DESCRIPTIONS = {
    "ribbon": "多层填充区域图，渐变色与阴影效果，适合展示多系列数据范围",
    "violin": "小提琴图结合内嵌箱线图，展示数据分布与统计特征",
    "alluvial": "冲积流向图，展示分类之间的流量与关联关系",
    "bubble_kde": "气泡散点图叠加核密度等高线，展示数据分布与密度",
    "gradient_area": "渐变填充面积图，colormap渐变填充效果",
    "surface3d": "三维地形表面图，适合展示空间数据与高程信息",
    "parallel": "平行坐标图，多维度数据对比分析",
    "contour": "等高线地形图，带标注的填充等高线",
    "swarm": "蜂群图，分组散点分布展示，避免重叠",
    "scatter_density": "散点密度图，颜色映射2D密度分布",
    "chord": "和弦图，弧形与贝塞尔曲线展示节点间关联",
    "heatmap_dendro": "热力聚类图，热力图与树状图聚类分析",
}


# ── 主入口 ────────────────────────────────────────────────

def generate_chart(
    chart_type: str,
    data: Any,
    title: str = "学术研究图表",
    x_label: str = "",
    y_label: str = "",
    width: int = 1200,
    height: int = 800,
    dpi: int = 300,
    **kwargs,
) -> bytes:
    """
    主入口：根据图表类型生成图表，返回 PNG 字节数据

    Args:
        chart_type: 图表类型（ribbon/violin/alluvial/...）
        data: 图表数据
        title: 图表标题
        x_label: X轴标签
        y_label: Y轴标签
        width: 图像宽度（像素）
        height: 图像高度（像素）
        dpi: 分辨率
        **kwargs: 其他参数传递给具体图表函数

    Returns:
        PNG 图像字节数据
    """
    try:
        if chart_type not in CHART_FUNCTIONS:
            raise ValueError(f"不支持的图表类型: {chart_type}，支持类型: {list(CHART_FUNCTIONS.keys())}")

        chart_func = CHART_FUNCTIONS[chart_type]
        parsed_data = parse_data_input(data)

        fig = chart_func(
            data=parsed_data,
            title=title,
            x_label=x_label,
            y_label=y_label,
            width=width,
            height=height,
            dpi=dpi,
            **kwargs,
        )

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="#FFFFFF")
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    except Exception as e:
        # 生成错误回退图表
        return _generate_fallback_chart(str(e), title, width, height, dpi)


def _generate_fallback_chart(error_msg: str, title: str, width: int, height: int, dpi: int) -> bytes:
    """生成错误回退图表"""
    _apply_origin_style()
    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)
    ax.text(0.5, 0.55, "图表生成失败", ha="center", va="center",
            fontsize=24, fontweight="bold", color="#D4573B",
            transform=ax.transAxes)
    ax.text(0.5, 0.40, error_msg, ha="center", va="center",
            fontsize=15, color="#666666", transform=ax.transAxes,
            wrap=True)
    ax.text(0.5, 0.25, "请检查数据格式是否正确", ha="center", va="center",
            fontsize=15, color="#999999", transform=ax.transAxes)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    if title:
        fig.suptitle(title, fontsize=22, fontweight="bold")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)
    buf.seek(0)
    return buf.read()
