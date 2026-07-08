"""ScholarMind 12 种高级学术图表实现（按类别拆分）

Origin 风格（白底黑框、大字体、学术配色）
"""
from ._basic import (
    ribbon_chart,
    violin_chart,
    alluvial_chart,
    bubble_kde_chart,
    gradient_area_chart,
    surface3d_chart,
)
from ._advanced import (
    parallel_chart,
    contour_chart,
    swarm_chart,
    scatter_density_chart,
    chord_chart,
    heatmap_dendro_chart,
)

__all__ = [
    "ribbon_chart",
    "violin_chart",
    "alluvial_chart",
    "bubble_kde_chart",
    "gradient_area_chart",
    "surface3d_chart",
    "parallel_chart",
    "contour_chart",
    "swarm_chart",
    "scatter_density_chart",
    "chord_chart",
    "heatmap_dendro_chart",
]
