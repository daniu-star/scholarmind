"""
ScholarMind Celery 任务队列配置
生产环境使用 Redis 作为 broker，开发环境使用 BackgroundTasks 降级
"""
from __future__ import annotations

from celery import Celery

from ..config import settings

celery_app = Celery(
    "scholarmind",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["src.backend.tasks.chart_tasks"],
)

# Celery 配置
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,        # 任务超时 5 分钟
    task_soft_time_limit=240,   # 软超时 4 分钟
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=60,
    task_max_retries=3,
    # 任务路由
    task_routes={
        "src.backend.tasks.chart_tasks.*": {"queue": "charts"},
    },
)

# 开发模式降级检测
def is_available() -> bool:
    """检查 Celery broker 是否可用"""
    try:
        conn = celery_app.connection()
        conn.ensure_connection(max_retries=1, timeout=2)
        conn.release()
        return True
    except Exception:
        return False