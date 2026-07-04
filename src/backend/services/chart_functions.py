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

from .chart_style import ACADEMIC_COLORS, _apply_origin_style
from .chart_data import _safe_array, _make_figure, _finalize

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
    {g: ACADEMIC_COLORS[i % len(ACADEMIC_COLORS)] for i, g in enumerate(groups)}

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
    len(targets)

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
def parallel_chart(data, title: str, x_label: str, y_label: str, **kwargs) -> Figure:
    """
    平行坐标图: pandas parallel_coordinates 风格
    Data: DataFrame-like dict, e.g. {"class": [...], "feat1": [...], "feat2": [...]}
    """
    width = kwargs.get("width", 1200)
    height = kwargs.get("height", 800)
    dpi = kwargs.get("dpi", 300)

    fig, ax = _make_figure(width, height, dpi)

    df = pd.DataFrame(data)
    class_col = kwargs.get("class_col", None)

    # 自动检测分类列
    if class_col is None:
        for col in df.columns:
            if df[col].dtype == object or df[col].nunique() <= 10:
                class_col = col
                break

    if class_col is None or class_col not in df.columns:
        class_col = df.columns[0]

    classes = df[class_col].unique()
    feature_cols = [c for c in df.columns if c != class_col]

    # 归一化
    df_norm = df.copy()
    for col in feature_cols:
        col_min = df[col].min()
        col_max = df[col].max()
        if col_max != col_min:
            df_norm[col] = (df[col] - col_min) / (col_max - col_min)
        else:
            df_norm[col] = 0.5

    # 绘制
    x_positions = range(len(feature_cols))
    for cls_idx, cls in enumerate(classes):
        cls_data = df_norm[df_norm[class_col] == cls]
        color = ACADEMIC_COLORS[cls_idx % len(ACADEMIC_COLORS)]
        for _, row in cls_data.iterrows():
            ys = [row[c] for c in feature_cols]
            ax.plot(x_positions, ys, color=color, alpha=0.4, linewidth=1.2)

    # 为每个类别画一条粗线作为图例
    for cls_idx, cls in enumerate(classes):
        color = ACADEMIC_COLORS[cls_idx % len(ACADEMIC_COLORS)]
        ax.plot([], [], color=color, linewidth=3, label=str(cls))

    ax.set_xticks(list(x_positions))
    ax.set_xticklabels(feature_cols, fontsize=15, rotation=30, ha="right")
    ax.legend(loc="upper right", fontsize=13)
    ax.set_ylim(-0.05, 1.05)

    _finalize(fig, title, x_label or "特征维度", y_label or "归一化值", ax)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    return fig


# 8. 等高线地形图
def contour_chart(data, title: str, x_label: str, y_label: str, **kwargs) -> Figure:
    """
    等高线地形图: contourf + terrain colormap + contour line labels
    Data: 2D array or (x, y, z) grid
    """
    width = kwargs.get("width", 1200)
    height = kwargs.get("height", 800)
    dpi = kwargs.get("dpi", 300)

    fig, ax = _make_figure(width, height, dpi)

    arr = _safe_array(data)

    if arr.ndim == 2 and arr.shape[1] == 3:
        xs = arr[:, 0]
        ys = arr[:, 1]
        arr[:, 2]
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
        X, Y = np.meshgrid(np.arange(Z.shape[1]), np.arange(Z.shape[0]))
    else:
        Z = np.zeros((10, 10))
        X, Y = np.meshgrid(np.arange(10), np.arange(10))

    cf = ax.contourf(X, Y, Z, levels=15, cmap="terrain", alpha=0.85)
    cs = ax.contour(X, Y, Z, levels=15, colors="#000000", linewidths=0.6, alpha=0.5)
    ax.clabel(cs, inline=True, fontsize=12, fmt="%.1f")
    fig.colorbar(cf, ax=ax, shrink=0.8)

    _finalize(fig, title, x_label, y_label, ax)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    return fig


# 9. 蜂群图
def swarm_chart(data, title: str, x_label: str, y_label: str, **kwargs) -> Figure:
    """
    蜂群图: seaborn swarmplot + 分组着色
    Data: dict of {group: [values]}
    """
    width = kwargs.get("width", 1200)
    height = kwargs.get("height", 800)
    dpi = kwargs.get("dpi", 300)

    fig, ax = _make_figure(width, height, dpi)

    groups = list(data.keys())
    [data[g] for g in groups]
    palette = [ACADEMIC_COLORS[i % len(ACADEMIC_COLORS)] for i in range(len(groups))]

    # 构造 DataFrame
    rows = []
    for i, g in enumerate(groups):
        for v in data[g]:
            rows.append({"group": g, "value": v})
    df = pd.DataFrame(rows)

    sns.swarmplot(data=df, x="group", y="value", palette=palette, ax=ax, size=6,
                  edgecolor="#000000", linewidth=0.5)

    _finalize(fig, title, x_label or "分组", y_label or "数值", ax)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    return fig


# 10. 散点密度图
def scatter_density_chart(data, title: str, x_label: str, y_label: str, **kwargs) -> Figure:
    """
    散点密度图: scatter + 2D histogram density color mapping
    Data: list of (x, y) tuples
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

    # 2D 直方图计算密度
    try:
        x_bins = kwargs.get("x_bins", 50)
        y_bins = kwargs.get("y_bins", 50)
        H, xedges, yedges = np.histogram2d(xs, ys, bins=(x_bins, y_bins))
        # 将每个点映射到对应 bin 的密度
        ix = np.clip(np.digitize(xs, xedges) - 1, 0, H.shape[0] - 1)
        iy = np.clip(np.digitize(ys, yedges) - 1, 0, H.shape[1] - 1)
        density = H[ix, iy]
    except Exception as e:
        logger.warning(f"scatter_density_chart: 2D直方图密度计算失败，使用均匀密度: {e}")
        density = np.ones(len(xs))

    sc = ax.scatter(xs, ys, c=density, cmap="YlOrRd", alpha=0.7,
                    edgecolors="#333333", linewidths=0.3, s=15)
    fig.colorbar(sc, ax=ax, label="密度", shrink=0.8)

    _finalize(fig, title, x_label, y_label, ax)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    return fig


# 11. 和弦图
def chord_chart(data, title: str, x_label: str, y_label: str, **kwargs) -> Figure:
    """
    和弦图: 弧形 + 贝塞尔曲线连接
    Data: list of (source, target, value) tuples
    """
    width = kwargs.get("width", 1200)
    height = kwargs.get("height", 800)
    dpi = kwargs.get("dpi", 300)

    fig, ax = _make_figure(width, height, dpi)
    ax.set_aspect("equal")

    # 收集所有节点
    nodes = list(dict.fromkeys(
        [s for s, t, v in data] + [t for s, t, v in data]
    ))
    n = len(nodes)
    if n == 0:
        _finalize(fig, title, "", "", ax)
        return fig

    # 计算每个节点的总流量
    node_totals = {}
    for node in nodes:
        node_totals[node] = sum(v for s, t, v in data if s == node or t == node)

    total_flow = sum(node_totals.values()) if node_totals else 1

    # 分配弧段角度
    angles = {}
    gap = 0.03  # 弧段之间的间隔（弧度）
    total_gap = gap * n
    available = 2 * np.pi - total_gap
    current_angle = 0

    for node in nodes:
        frac = node_totals[node] / total_flow
        arc_len = frac * available
        angles[node] = (current_angle, current_angle + arc_len)
        current_angle += arc_len + gap

    radius = 1.0

    # 绘制外圈弧段
    for idx, node in enumerate(nodes):
        start_a, end_a = angles[node]
        color = ACADEMIC_COLORS[idx % len(ACADEMIC_COLORS)]
        theta = np.linspace(start_a, end_a, 100)
        x_outer = radius * np.cos(theta)
        y_outer = radius * np.sin(theta)
        x_inner = 0.95 * radius * np.cos(theta)
        y_inner = 0.95 * radius * np.sin(theta)

        # 填充弧段
        verts_x = np.concatenate([x_outer, x_inner[::-1]])
        verts_y = np.concatenate([y_outer, y_inner[::-1]])
        ax.fill(verts_x, verts_y, color=color, edgecolor="#000000", linewidth=1.2, alpha=0.85)

        # 标签
        mid_a = (start_a + end_a) / 2
        lx = 1.15 * radius * np.cos(mid_a)
        ly = 1.15 * radius * np.sin(mid_a)
        ax.text(lx, ly, node, ha="center", va="center", fontsize=13, fontweight="bold")

    # 绘制连接弧线
    for s, t, v in data:
        if s not in angles or t not in angles:
            continue
        s_idx = nodes.index(s)
        nodes.index(t)

        s_mid = sum(angles[s]) / 2
        t_mid = sum(angles[t]) / 2

        # 贝塞尔曲线控制点
        p0 = np.array([radius * np.cos(s_mid), radius * np.sin(s_mid)])
        p3 = np.array([radius * np.cos(t_mid), radius * np.sin(t_mid)])
        ctrl_len = 0.4 * radius
        p1 = np.array([ctrl_len * np.cos(s_mid), ctrl_len * np.sin(s_mid)])
        p2 = np.array([ctrl_len * np.cos(t_mid), ctrl_len * np.sin(t_mid)])

        bezier_t = np.linspace(0, 1, 80)
        bx = (1 - bezier_t) ** 3 * p0[0] + 3 * (1 - bezier_t) ** 2 * bezier_t * p1[0] + \
             3 * (1 - bezier_t) * bezier_t ** 2 * p2[0] + bezier_t ** 3 * p3[0]
        by = (1 - bezier_t) ** 3 * p0[1] + 3 * (1 - bezier_t) ** 2 * bezier_t * p1[1] + \
             3 * (1 - bezier_t) * bezier_t ** 2 * p2[1] + bezier_t ** 3 * p3[1]

        alpha = min(0.6, v / max(node_totals.values()) * 0.8 + 0.15)
        color = ACADEMIC_COLORS[s_idx % len(ACADEMIC_COLORS)]
        r, g, b = int(color[1:3], 16) / 255, int(color[3:5], 16) / 255, int(color[5:7], 16) / 255
        ax.plot(bx, by, color=(r, g, b, alpha), linewidth=max(1, v / total_flow * 20))

    ax.set_xlim(-1.5, 1.5)
    ax.set_ylim(-1.5, 1.5)
    ax.axis("off")

    fig.suptitle(title, fontsize=22, fontweight="bold", y=0.97)
    return fig


# 12. 热力聚类图
def heatmap_dendro_chart(data, title: str, x_label: str, y_label: str, **kwargs) -> Figure:
    """
    热力聚类图: seaborn clustermap with dendrogram
    Data: 2D array (matrix)
    """
    width = kwargs.get("width", 1200)
    height = kwargs.get("height", 800)
    dpi = kwargs.get("dpi", 300)

    _apply_origin_style()

    Z = _safe_array(data)
    if Z.ndim != 2:
        Z = np.random.rand(10, 10)

    row_labels = kwargs.get("row_labels", [f"R{i}" for i in range(Z.shape[0])])
    col_labels = kwargs.get("col_labels", [f"C{i}" for i in range(Z.shape[1])])

    df = pd.DataFrame(Z, index=row_labels[:Z.shape[0]], columns=col_labels[:Z.shape[1]])

    g = sns.clustermap(df, cmap="YlOrRd", linewidths=0.5, linecolor="#FFFFFF",
                       method="ward", figsize=(width / dpi, height / dpi),
                       dendrogram_ratio=0.15, cbar_pos=(0.02, 0.8, 0.03, 0.15),
                       standard_scale=None, z_score=None)

    g.ax_heatmap.set_title(title, fontsize=22, fontweight="bold", pad=20)
    g.ax_heatmap.tick_params(labelsize=13)

    # 设置边框
    for spine in g.ax_heatmap.spines.values():
        spine.set_visible(True)
        spine.set_color("#000000")
        spine.set_linewidth(2)

    return g.figure
