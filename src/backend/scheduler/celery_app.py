"""Celery application configuration."""

import sys
from pathlib import Path
from celery import Celery
from celery.schedules import crontab

# Ensure project root is in sys.path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.config import settings  # noqa: E402

celery_app = Celery(
    "scholarmind",
    include=["src.backend.scheduler.chart_tasks"],
)

celery_app.conf.update(
    broker_url=settings.CELERY_BROKER_URL,
    result_backend=settings.CELERY_RESULT_BACKEND,
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_time_limit=3600,       # 1 hour max per task
    task_soft_time_limit=3000,  # 50 min soft limit
    worker_max_tasks_per_child=100,
    worker_prefetch_multiplier=1,

    # Beat schedule — 24-hour crawling (使用 crontab 对象)
    beat_schedule={
        "crawl-cnki-hot": {
            "task": "src.backend.scheduler.tasks.crawl_source",
            "schedule": crontab(minute=0, hour="*/2"),
            "args": ("cnki", "hot", 50),
        },
        "crawl-crossref-latest": {
            "task": "src.backend.scheduler.tasks.crawl_source",
            "schedule": crontab(minute=30, hour="*/4"),
            "args": ("crossref", "latest", 100),
        },
        "crawl-pubmed-latest": {
            "task": "src.backend.scheduler.tasks.crawl_source",
            "schedule": crontab(minute=0, hour="*/4"),
            "args": ("pubmed", "latest", 100),
        },
        "crawl-wanfang-hot": {
            "task": "src.backend.scheduler.tasks.crawl_source",
            "schedule": crontab(minute=0, hour="*/6"),
            "args": ("wanfang", "hot", 50),
        },
        "crawl-weipu-hot": {
            "task": "src.backend.scheduler.tasks.crawl_source",
            "schedule": crontab(minute=30, hour="*/6"),
            "args": ("weipu", "hot", 50),
        },
        "build-rag-index": {
            "task": "src.backend.scheduler.tasks.build_rag_index",
            "schedule": crontab(minute=0, hour=3),
        },
        "update-hot-keywords": {
            "task": "src.backend.scheduler.tasks.update_hot_keywords",
            "schedule": crontab(minute=0, hour=4),
        },
        "cleanup-old-data": {
            "task": "src.backend.scheduler.tasks.cleanup_old_data",
            "schedule": crontab(minute=0, hour=2, day_of_week="sunday"),
        },
        "expire-stale-orders": {
            "task": "src.backend.scheduler.tasks.expire_stale_orders",
            "schedule": crontab(minute=15, hour="*"),  # 每小时第 15 分钟
        },
    },
)

# P1: 合并 tasks/ 的 chart 任务路由
celery_app.conf.update(
    task_routes={
        "src.backend.scheduler.chart_tasks.*": {"queue": "charts"},
    },
    task_time_limit=300,
    task_soft_time_limit=240,
    task_acks_late=True,
    task_default_retry_delay=60,
    task_max_retries=3,
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["src.backend.scheduler"])


def is_available() -> bool:
    """检查 Celery broker 是否可用"""
    try:
        conn = celery_app.connection()
        conn.ensure_connection(max_retries=1, timeout=2)
        conn.release()
        return True
    except Exception:
        return False
