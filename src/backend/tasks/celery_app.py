"""
⚠ DEPRECATED: tasks/ 目录已合并到 scheduler/，本文件将在下个版本删除。
新代码请使用: from src.backend.scheduler.celery_app import celery_app, is_available
chart_tasks 已迁移至: from src.backend.scheduler.chart_tasks import generate_chart_task
"""
from __future__ import annotations
import warnings

warnings.warn(
    "tasks.celery_app is deprecated, use scheduler.celery_app instead",
    DeprecationWarning,
    stacklevel=2,
)

from ..scheduler.celery_app import celery_app, is_available  # noqa: E402, F401
