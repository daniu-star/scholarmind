"""
ScholarMind 学术图表数据解析与辅助函数
"""

import io
import json
import csv
import structlog
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
import pandas as pd
from typing import Any

from .chart_style import get_origin_style, _apply_origin_style

logger = structlog.get_logger(__name__)

# ── 数据解析 ──────────────────────────────────────────────

def parse_data_input(data_input: Any) -> Any:
    """
    解析多种格式的输入数据
    支持: JSON 数组/对象, CSV 字符串, Python dict/list, 已解析的数据
    """
    if data_input is None:
        return None

    # 已经是 Python 对象（list / dict / np.ndarray / pd.DataFrame）
    if isinstance(data_input, (list, dict, np.ndarray, pd.DataFrame)):
        return data_input

    # 字符串类型需要解析
    if isinstance(data_input, str):
        s = data_input.strip()
        # 尝试 JSON
        try:
            return json.loads(s)
        except (json.JSONDecodeError, ValueError):
            pass
        # 尝试 CSV
        try:
            reader = csv.reader(io.StringIO(s))
            rows = list(reader)
            if len(rows) > 1:
                # 首行可能是表头
                header = rows[0]
                data_rows = rows[1:]
                try:
                    data_rows = [[float(v) for v in row] for row in data_rows]
                except ValueError:
                    pass
                return {"headers": header, "rows": data_rows}
            elif len(rows) == 1:
                try:
                    return [float(v) for v in rows[0]]
                except ValueError:
                    return rows[0]
        except Exception:
            pass
        return s

    return data_input


# ── 辅助函数 ──────────────────────────────────────────────

def _safe_array(obj):
    """安全转换为 numpy 数组，非数值数据返回空数组并记录警告"""
    if obj is None:
        return np.array([])
    try:
        return np.asarray(obj, dtype=float)
    except (ValueError, TypeError) as e:
        logger.warning(f"无法将数据转换为数值数组: {e}")
        return np.array([])


def _make_figure(width: int, height: int, dpi: int) -> tuple:
    """创建 Origin 风格的 Figure 和 Axes"""
    _apply_origin_style()
    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)
    return fig, ax


def _finalize(fig: Figure, title: str, x_label: str, y_label: str, ax=None) -> Figure:
    """统一设置标题和轴标签"""
    if ax is not None:
        if title:
            ax.set_title(title, fontsize=22, fontweight="bold")
        if x_label:
            ax.set_xlabel(x_label, fontsize=20, fontweight="bold")
        if y_label:
            ax.set_ylabel(y_label, fontsize=20, fontweight="bold")
    return fig
