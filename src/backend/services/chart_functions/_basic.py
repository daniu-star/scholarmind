"""
ScholarMind 12种高级学术图表实现
Origin 风格（白底黑框、大字体、学术配色）
"""

import structlog
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.colors import LinearSegmentedColormap
from scipy.stats import gaussian_kde
import seaborn as sns
import pandas as pd

from ..chart_style import ACADEMIC_COLORS, _apply_origin_style
from ..chart_data import _safe_array, _make_figure, _finalize

logger = structlog.get_logger(__name__)


# 1. 缎带图
def ribbon_chart(data, title: str, x_label: str, y_label: str, **kwargs) -> Figure:
    """
    缎带图: 多层 fill_between，渐变色 + 阴影效果
    Data: list of (x, [y1, y2, y3...]) series
    """
    width = kwargs.get("width", 1200)
    height = kwargs.get("height", 800)
    dpi = kwargs.get("dpi", 300)

    fig, ax = _make_figure(width, height, dpi)

    n_series = len(data)
    colors = [ACADEMIC_COLORS[i % len(ACADEMIC_COLORS)] for i in range(n_series)]

    for idx, (x_vals, y_layers) in enumerate(data):
        x = _safe_array(x_vals)
        y_layers = _safe_array(y_layers)
        if y_layers.ndim == 1:
            y_layers = y_layers.reshape(1, -1)

        base_color = colors[idx]
        r, g, b = int(base_color[1:3], 16) / 255, int(base_color[3:5], 16) / 255, int(base_color[5:7], 16) / 255

        n_layers = y_layers.shape[0]
        for layer_i in range(n_layers):
            alpha = 0.3 + 0.5 * (layer_i + 1) / n_layers
            y_top = y_layers[layer_i]
            y_bot = np.zeros_like(y_top) if layer_i == 0 else y_layers[layer_i - 1]
            ax.fill_between(x, y_bot, y_top, color=(r, g, b, alpha), linewidth=0)
            # 阴影线
            ax.plot(x, y_top, color=base_color, linewidth=1.5, alpha=0.8)

    _finalize(fig, title, x_label, y_label, ax)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    return fig


# 2. 小提琴图 + 内嵌箱线图
def violin_chart(data, title: str, x_label: str, y_label: str, **kwargs) -> Figure:
    """
    小提琴图 + 内嵌箱线图
    Data: dict of {group_name: [values]}
    """
    width = kwargs.get("width", 1200)
    height = kwargs.get("height", 800)
    dpi = kwargs.get("dpi", 300)

    fig, ax = _make_figure(width, height, dpi)

    groups = list(data.keys())
    values = [data[g] for g in groups]

    parts = ax.violinplot(values, showmeans=False, showmedians=False, showextrema=False)

    for i, pc in enumerate(parts["bodies"]):
        color = ACADEMIC_COLORS[i % len(ACADEMIC_COLORS)]
        pc.set_facecolor(color)
        pc.set_alpha(0.6)
        pc.set_edgecolor("#000000")
        pc.set_linewidth(1.2)

    # 内嵌箱线图
    for i, vals in enumerate(values):
        q1 = np.percentile(vals, 25)
        np.percentile(vals, 50)
        q3 = np.percentile(vals, 75)
        iqr = q3 - q1
        max(np.min(vals), q1 - 1.5 * iqr)
        min(np.max(vals), q3 + 1.5 * iqr)
        pos = i + 1
        ax.boxplot(
            [vals], positions=[pos], widths=0.15,
            showfliers=False, showcaps=False,
            medianprops=dict(color="#000000", linewidth=2),
            whiskerprops=dict(color="#000000", linewidth=1.5),
            boxprops=dict(color="#000000", linewidth=1.5, facecolor="none"),
        )

    ax.set_xticks(range(1, len(groups) + 1))
    ax.set_xticklabels(groups, fontsize=15)

    _finalize(fig, title, x_label, y_label, ax)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    return fig


# 3. 冲积图
def alluvial_chart(data, title: str, x_label: str, y_label: str, **kwargs) -> Figure:
    """
    冲积图: 基于弧线的流向图，渐变色带
    Data: list of (source, target, value) tuples
    """
    width = kwargs.get("width", 1200)
    height = kwargs.get("height", 800)
    dpi = kwargs.get("dpi", 300)

    fig, ax = _make_figure(width, height, dpi)

    sources = list(dict.fromkeys([s for s, t, v in data]))
    targets = list(dict.fromkeys([t for s, t, v in data]))

    n_src = len(sources)

    # 左侧节点位置
    src_y = {}
    src_offset = {}
    sum(v for s, t, v in data if s == sources[0]) if sources else 1
    for i, s in enumerate(sources):
        src_y[s] = i
        src_offset[s] = 0

    # 右侧节点位置
    tgt_y = {}
    tgt_offset = {}
    for i, t in enumerate(targets):
        tgt_y[t] = i
        tgt_offset[t] = 0

    max_val = max((v for s, t, v in data), default=1)

    # 绘制左侧节点块
    for i, s in enumerate(sources):
        total = sum(v for ss, t, v in data if ss == s)
        block_h = total / max_val * 0.7
        y_start = i - block_h / 2
        ax.barh(y_start + block_h / 2, -0.4, height=block_h, left=0.05,
                color=ACADEMIC_COLORS[i % len(ACADEMIC_COLORS)], edgecolor="#000000", linewidth=1.5)
        ax.text(-0.05, i, s, ha="right", va="center", fontsize=15, fontweight="bold")

    # 绘制右侧节点块
    for i, t in enumerate(targets):
        total = sum(v for s, tt, v in data if tt == t)
        block_h = total / max_val * 0.7
        y_start = i - block_h / 2
        ax.barh(y_start + block_h / 2, 0.4, height=block_h, left=0.95,
                color=ACADEMIC_COLORS[(i + n_src) % len(ACADEMIC_COLORS)], edgecolor="#000000", linewidth=1.5)
        ax.text(1.45, i, t, ha="left", va="center", fontsize=15, fontweight="bold")

    # 绘制弧形连接
    for idx, (s, t, v) in enumerate(data):
        si = sources.index(s) if s in sources else 0
        ti = targets.index(t) if t in targets else 0
        flow_h = v / max_val * 0.7

        y_src_start = si - sum(vv for ss, tt, vv in data if ss == s and sources.index(ss) < si) / max_val * 0.7
        y_src_start = si - 0.35 + src_offset[s] / max_val * 0.7
        y_src_end = y_src_start + flow_h

        y_tgt_start = ti - 0.35 + tgt_offset[t] / max_val * 0.7
        y_tgt_end = y_tgt_start + flow_h

        color = ACADEMIC_COLORS[si % len(ACADEMIC_COLORS)]
        r, g, b = int(color[1:3], 16) / 255, int(color[3:5], 16) / 255, int(color[5:7], 16) / 255

        # 用贝塞尔曲线绘制弧形
        n_pts = 50
        xs = np.linspace(0.05, 0.95, n_pts)
        for y_s, y_e in [(y_src_start, y_tgt_start), (y_src_end, y_tgt_end)]:
            ys = (1 - xs) * y_s + xs * y_e + 0.3 * np.sin(np.pi * xs) * (y_e - y_s) * 0.1
            ax.plot(xs, ys, color=color, linewidth=0.8, alpha=0.6)

        # 填充区域
        ys_top = (1 - xs) * y_src_end + xs * y_tgt_end + 0.3 * np.sin(np.pi * xs) * (y_tgt_end - y_src_end) * 0.1
        ys_bot = (1 - xs) * y_src_start + xs * y_tgt_start + 0.3 * np.sin(np.pi * xs) * (y_tgt_start - y_src_start) * 0.1
        ax.fill_between(xs, ys_bot, ys_top, color=(r, g, b, 0.35), linewidth=0)

        src_offset[s] += v
        tgt_offset[t] += v

    ax.set_xlim(-0.3, 1.7)
    ax.axis("off")
    _finalize(fig, title, "", "", ax)
    fig.suptitle(title, fontsize=22, fontweight="bold", y=0.97)
    ax.set_title("")
    return fig


# 4. 气泡散点 + KDE
def bubble_kde_chart(data, title: str, x_label: str, y_label: str, **kwargs) -> Figure:
    """
    气泡散点 + KDE 等高线
    Data: list of (x, y, size) tuples
    """
    width = kwargs.get("width", 1200)
    height = kwargs.get("height", 800)
    dpi = kwargs.get("dpi", 300)

    fig, ax = _make_figure(width, height, dpi)

    arr = _safe_array(data)
    if arr.ndim == 1 or len(arr) == 0:
        _finalize(fig, title, x_label, y_label, ax)
        return fig

    xs = arr[:, 0]
    ys = arr[:, 1]
    sizes = arr[:, 2] if arr.shape[1] > 2 else np.ones(len(xs)) * 50

    # KDE 等高线
    try:
        xmin, xmax = xs.min() - 1, xs.max() + 1
        ymin, ymax = ys.min() - 1, ys.max() + 1
        xx, yy = np.mgrid[xmin:xmax:100j, ymin:ymax:100j]
        positions = np.vstack([xx.ravel(), yy.ravel()])
        kernel = gaussian_kde(np.vstack([xs, ys]))
        f = np.reshape(kernel(positions), xx.shape)
        ax.contourf(xx, yy, f, levels=8, cmap="Blues", alpha=0.3)
        ax.contour(xx, yy, f, levels=8, colors="#2C5F8A", linewidths=0.8, alpha=0.5)
    except Exception as e:
        logger.warning(f"bubble_kde_chart: KDE 计算失败，跳过等高线绘制: {e}")

    # 气泡散点
    size_norm = (sizes - sizes.min()) / (sizes.max() - sizes.min() + 1e-8) * 300 + 30
    ax.scatter(xs, ys, s=size_norm, c=ACADEMIC_COLORS[0], alpha=0.65,
               edgecolors="#000000", linewidths=0.8)

    _finalize(fig, title, x_label, y_label, ax)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    return fig


# 5. 梯度面积图
def gradient_area_chart(data, title: str, x_label: str, y_label: str, **kwargs) -> Figure:
    """
    梯度面积图: fill_between + colormap 渐变填充
    Data: list of (x, y) pairs
    """
    width = kwargs.get("width", 1200)
    height = kwargs.get("height", 800)
    dpi = kwargs.get("dpi", 300)

    fig, ax = _make_figure(width, height, dpi)

    arr = _safe_array(data)
    if arr.ndim == 1 or len(arr) == 0:
        _finalize(fig, title, x_label, y_label, ax)
        return fig

    xs = arr[:, 0]
    ys = arr[:, 1]

    # 渐变填充：将 y 值映射到 colormap
    cmap = LinearSegmentedColormap.from_list("academic", [ACADEMIC_COLORS[0], ACADEMIC_COLORS[2]])
    n_segments = 100
    y_min, y_max = ys.min(), ys.max()
    y_range = y_max - y_min if y_max != y_min else 1

    for i in range(n_segments):
        lo = y_min + i / n_segments * y_range
        hi = y_min + (i + 1) / n_segments * y_range
        color = cmap(i / n_segments)
        ax.fill_between(xs, lo, np.minimum(ys, hi), where=(ys >= lo),
                        color=color, linewidth=0, alpha=0.7)

    ax.plot(xs, ys, color=ACADEMIC_COLORS[0], linewidth=2.5)
    ax.fill_between(xs, 0, ys, color=ACADEMIC_COLORS[0], alpha=0.08)

    _finalize(fig, title, x_label, y_label, ax)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    return fig


# 6. 3D 地形图
def surface3d_chart(data, title: str, x_label: str, y_label: str, **kwargs) -> Figure:
    """
    3D 地形图: Axes3D plot_surface + terrain colormap
    Data: 2D array or list of (x, y, z) tuples
    """
    width = kwargs.get("width", 1200)
    height = kwargs.get("height", 800)
    dpi = kwargs.get("dpi", 300)

    _apply_origin_style()
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    ax = fig.add_subplot(111, projection="3d")

    arr = _safe_array(data)

    if arr.ndim == 2 and arr.shape[1] == 3:
        # (x, y, z) tuples
        xs = arr[:, 0]
        ys = arr[:, 1]
        arr[:, 2]
        # 创建网格
        x_unique = np.unique(xs)
        y_unique = np.unique(ys)
        X, Y = np.meshgrid(x_unique, y_unique)
        Z = np.zeros_like(X)
        for row in arr:
            xi = np.searchsorted(x_unique, row[0])
            yi = np.searchsorted(y_unique, row[1])
            if xi < X.shape[1] and yi < X.shape[0]:
                Z[yi, xi] = row[2]
    elif arr.ndim == 2:
        Z = arr
        x_unique = np.arange(Z.shape[1])
        y_unique = np.arange(Z.shape[0])
        X, Y = np.meshgrid(x_unique, y_unique)
    else:
        Z = np.array([[0]])
        X, Y = np.meshgrid([0], [0])

    surf = ax.plot_surface(X, Y, Z, cmap="terrain", alpha=0.85,
                           edgecolor="none", antialiased=True)
    fig.colorbar(surf, ax=ax, shrink=0.5, aspect=10)

    if title:
        ax.set_title(title, fontsize=22, fontweight="bold")
    if x_label:
        ax.set_xlabel(x_label, fontsize=20, fontweight="bold")
    if y_label:
        ax.set_ylabel(y_label, fontsize=20, fontweight="bold")
    ax.set_zlabel("Z", fontsize=20, fontweight="bold")

    return fig


# 7. 平行坐标图
