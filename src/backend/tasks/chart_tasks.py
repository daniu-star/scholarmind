"""
ScholarMind 异步图表生成任务
使用 Celery 或 BackgroundTasks 异步处理图表生成
"""
from __future__ import annotations

import uuid
import logging
from pathlib import Path
from typing import Any

from .celery_app import celery_app
from ..config import settings

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def generate_chart_task(
    self,
    chart_type: str,
    data: Any,
    title: str = "学术研究图表",
    x_label: str = "",
    y_label: str = "",
    width: int = 1200,
    height: int = 800,
    dpi: int = 300,
    session_id: str = "",
) -> dict:
    """异步生成学术图表

    Returns:
        dict with keys: chart_id, chart_type, title, filepath, status
    """
    chart_id = str(uuid.uuid4())
    charts_dir = Path(settings.CHARTS_DIR)
    charts_dir.mkdir(parents=True, exist_ok=True)
    filepath = str(charts_dir / f"{chart_id}.png")

    try:
        from ..services import chart_service

        self.update_state(state="PROCESSING", meta={"chart_id": chart_id})

        png_bytes = chart_service.generate_chart(
            chart_type=chart_type,
            data=data,
            title=title,
            x_label=x_label,
            y_label=y_label,
            width=width,
            height=height,
            dpi=dpi,
        )

        with open(filepath, "wb") as f:
            f.write(png_bytes)

        logger.info(
            "Chart generated asynchronously",
            chart_id=chart_id,
            chart_type=chart_type,
        )

        return {
            "chart_id": chart_id,
            "chart_type": chart_type,
            "title": title,
            "filepath": filepath,
            "status": "success",
        }

    except Exception as exc:
        logger.error(
            f"Async chart generation failed: {exc}",
            chart_id=chart_id,
            chart_type=chart_type,
        )
        # 重试
        raise self.retry(exc=exc, countdown=60)


# ── 同步降级方案（使用 FastAPI BackgroundTasks） ──────────

async def generate_chart_background(
    chart_type: str,
    data: Any,
    title: str = "学术研究图表",
    x_label: str = "",
    y_label: str = "",
    width: int = 1200,
    height: int = 800,
    dpi: int = 300,
) -> bytes:
    """同步生成图表（BackgroundTasks 降级方案）"""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _sync_generate,
        chart_type,
        data,
        title,
        x_label,
        y_label,
        width,
        height,
        dpi,
    )


def _sync_generate(
    chart_type: str,
    data: Any,
    title: str,
    x_label: str,
    y_label: str,
    width: int,
    height: int,
    dpi: int,
) -> bytes:
    """同步图表生成（在线程池中运行）"""
    from ..services import chart_service
    return chart_service.generate_chart(
        chart_type=chart_type,
        data=data,
        title=title,
        x_label=x_label,
        y_label=y_label,
        width=width,
        height=height,
        dpi=dpi,
    )