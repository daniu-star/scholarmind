"""
P1 修复: 统一 Celery 实例到 scheduler/celery_app.py，本文件为向后兼容的 re-export。
新代码请直接使用: from src.backend.scheduler.celery_app import celery_app, is_available
"""
from __future__ import annotations

from ..scheduler.celery_app import celery_app, is_available  # noqa: F401
