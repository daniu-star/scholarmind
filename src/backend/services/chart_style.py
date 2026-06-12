"""
ScholarMind 学术图表样式配置
Origin 风格（白底黑框、大字体、学术配色）
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── 学术配色 ──────────────────────────────────────────────
ACADEMIC_COLORS = [
    "#2C5F8A",  # 深蓝
    "#D4573B",  # 砖红
    "#3A8A5C",  # 墨绿
    "#8E6BB5",  # 紫
    "#C4943D",  # 金棕
    "#4A9B8E",  # 青绿
    "#B8546A",  # 玫红
    "#5B7DB1",  # 灰蓝
    "#D4883D",  # 橙
    "#6B8E4E",  # 橄榄绿
]

# ── Origin 风格配置 ───────────────────────────────────────

def get_origin_style() -> dict:
    """返回 Origin 风格的 matplotlib rcParams 字典"""
    return {
        "figure.facecolor": "#FFFFFF",
        "axes.facecolor": "#FFFFFF",
        "axes.edgecolor": "#000000",
        "axes.linewidth": 2.0,
        "axes.labelsize": 20,
        "axes.titlesize": 22,
        "axes.titleweight": "bold",
        "axes.labelweight": "bold",
        "axes.grid": False,
        "xtick.labelsize": 15,
        "ytick.labelsize": 15,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.major.width": 1.5,
        "ytick.major.width": 1.5,
        "xtick.major.size": 6,
        "ytick.major.size": 6,
        "font.family": ["SimHei", "Arial", "sans-serif"],
        "font.size": 15,
        "legend.fontsize": 15,
        "legend.frameon": True,
        "legend.edgecolor": "#000000",
        "legend.fancybox": False,
        "savefig.dpi": 300,
        "savefig.facecolor": "#FFFFFF",
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.15,
        "lines.linewidth": 2.0,
        "lines.markersize": 7,
    }


def _apply_origin_style():
    """应用 Origin 风格到当前 matplotlib 全局设置"""
    plt.rcParams.update(get_origin_style())
