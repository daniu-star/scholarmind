"""Master node FastAPI application — health dashboard and control API.

Provides:
- GET /health — overall system health
- GET /workers — worker status list
- GET /stats/{discipline} — per-discipline statistics
- GET /tasks — task query
- POST /tasks/requeue — requeue failed tasks
- POST /workers/{id}/pause|resume — worker control
"""

from __future__ import annotations

import asyncio
import structlog
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from utils.redis_client import RedisClient, get_redis
from utils.logging_config import setup_logging
from config.settings import settings
from config.journals import VALID_DISCIPLINES

from master.task_manager import TaskManager
from master.scheduler import TaskScheduler
from master.health_monitor import HealthMonitor

logger = structlog.get_logger()

# ── Globals ──────────────────────────────────────────────

_task_manager: Optional[TaskManager] = None
_scheduler: Optional[TaskScheduler] = None
_health_monitor: Optional[HealthMonitor] = None
_start_time = time.time()


# ── Lifespan ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    global _task_manager, _scheduler, _health_monitor

    setup_logging(worker_id="master")

    # Connect to Redis
    redis = await get_redis()
    logger.info("master_redis_connected")

    # Initialize components
    _task_manager = TaskManager(redis)
    _scheduler = TaskScheduler(redis)
    _health_monitor = HealthMonitor(redis)

    # Start health monitor in background
    asyncio.create_task(_health_monitor.run())

    # Start scheduler in background
    asyncio.create_task(_scheduler.run_scheduler_loop(interval_hours=1.0))

    logger.info("master_started", port=settings.MASTER_PORT)

    yield

    # Shutdown
    if _health_monitor:
        await _health_monitor.stop()
    if _scheduler:
        await _scheduler.stop()
    await RedisClient.close()
    logger.info("master_stopped")


# ── App ──────────────────────────────────────────────────

app = FastAPI(
    title="CNKI Downloader Master",
    description="Distributed anti-anti-crawl CNKI paper download system",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Health ───────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Overall system health."""
    redis_healthy = await RedisClient.health_check()
    health_summary = await _health_monitor.get_health_summary() if _health_monitor else {}

    uptime = int(time.time() - _start_time)
    return {
        "status": "healthy" if redis_healthy else "degraded",
        "uptime_seconds": uptime,
        "redis": "connected" if redis_healthy else "disconnected",
        **health_summary,
        "version": "1.0.0",
    }


# ── Workers ──────────────────────────────────────────────

@app.get("/workers")
async def list_workers():
    """List all worker nodes with status."""
    if not _health_monitor:
        raise HTTPException(503, "Health monitor not ready")
    return await _health_monitor.get_workers_status()


@app.post("/workers/{worker_id}/pause")
async def pause_worker(worker_id: str):
    """Send pause command to a worker.

    Task 4.3: 在 Pub/Sub 消息中加入 worker_id 字段实现精确定向。
    worker_id="all" 时广播给所有 Worker；否则仅匹配的 Worker 响应。
    """
    import json
    redis = await get_redis()
    await redis.publish(
        "cnki:master:commands",
        json.dumps({
            "command": "pause",
            "discipline": "all",
            "worker_id": worker_id,
        }),
    )
    return {"status": "ok", "command": "pause", "worker_id": worker_id}


@app.post("/workers/{worker_id}/resume")
async def resume_worker(worker_id: str):
    """Send resume command to a worker.

    Task 4.3: 在 Pub/Sub 消息中加入 worker_id 字段实现精确定向。
    worker_id="all" 时广播给所有 Worker；否则仅匹配的 Worker 响应。
    """
    import json
    redis = await get_redis()
    await redis.publish(
        "cnki:master:commands",
        json.dumps({
            "command": "resume",
            "discipline": "all",
            "worker_id": worker_id,
        }),
    )
    return {"status": "ok", "command": "resume", "worker_id": worker_id}


# ── Stats ────────────────────────────────────────────────

@app.get("/stats/{discipline}")
async def discipline_stats(discipline: str):
    """Get statistics for a specific discipline."""
    if discipline not in VALID_DISCIPLINES and discipline != "global":
        raise HTTPException(404, f"Unknown discipline: {discipline}")

    stats = await _task_manager.get_stats(discipline)
    queue_size = await _task_manager.get_queue_size(discipline) if discipline != "global" else 0

    return {
        "discipline": discipline,
        "stats": stats,
        "queue_size": queue_size,
    }


@app.get("/stats")
async def all_stats():
    """Get statistics for all disciplines."""
    result = {}
    for disc in VALID_DISCIPLINES:
        stats = await _task_manager.get_stats(disc)
        queue_size = await _task_manager.get_queue_size(disc)
        result[disc] = {**stats, "queue_size": queue_size}

    global_stats = await _task_manager.get_stats()
    result["global"] = global_stats

    return result


# ── Tasks ────────────────────────────────────────────────

@app.get("/tasks")
async def list_tasks(
    status: str = "failed",
    discipline: str = "",
    limit: int = Query(default=50, le=200),
):
    """Query tasks by status."""
    if not _task_manager:
        raise HTTPException(503, "Task manager not ready")
    return await _task_manager.get_tasks_by_status(status, discipline, limit)


@app.post("/tasks/requeue")
async def requeue_failed(body: dict):
    """Re-queue all failed tasks."""
    discipline = body.get("discipline", "")
    count = await _task_manager.requeue_all_failed(discipline)
    return {"status": "ok", "requeued_count": count}


@app.post("/tasks/generate")
async def generate_tasks(body: dict):
    """Manually trigger task generation."""
    discipline = body.get("discipline", "")
    year_start = body.get("year_start", 2016)
    year_end = body.get("year_end", 2026)

    if discipline:
        count = await _scheduler.generate_discipline_tasks(discipline, year_start, year_end)
    else:
        count = await _scheduler.generate_all_tasks(year_start, year_end)

    return {"status": "ok", "tasks_generated": count}


@app.get("/tasks/queue-sizes")
async def queue_sizes():
    """Get current queue sizes for all disciplines."""
    return await _task_manager.get_all_queue_sizes()


# ── Scheduler ────────────────────────────────────────────

@app.get("/scheduler/status")
async def scheduler_status():
    """Get scheduler status."""
    if not _scheduler:
        raise HTTPException(503, "Scheduler not ready")
    return await _scheduler.get_scheduler_status()


# ── Proxy ────────────────────────────────────────────────

@app.get("/proxy/status")
async def proxy_status():
    """Get proxy health status."""
    from anti_anti_crawl.proxy_manager import proxy_manager
    return await proxy_manager.get_stats()


# ── Search (Playwright-based CNKI search bridge) ─────────

@app.post("/search")
async def cnki_search(body: dict):
    """Perform a CNKI search using Playwright with full anti-detection.

    This is the bridge endpoint for the ScholarMind backend — it provides
    real CNKI search results obtained through browser automation.

    Request: {"query": "...", "year_filter": "", "count": 20}
    Response: {"success": true, "query": "...", "count": N, "results": [...], "source": "playwright"}
    """
    query = body.get("query", "")
    year_filter = body.get("year_filter", "")
    count = min(body.get("count", 20), 50)

    if not query or not query.strip():
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "query is required"},
        )

    try:
        from crawler.search_executor import search_executor

        result = await search_executor.search(
            query=query.strip(),
            year_filter=year_filter,
            count=count,
        )
        return result
    except Exception as e:
        logger.error("search_endpoint_error", error=str(e))
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "query": query,
                "count": 0,
                "results": [],
                "source": "playwright",
                "error": f"Internal error: {str(e)}",
            },
        )


# ── Metrics / Monitoring ─────────────────────────────────

@app.get("/metrics/captcha")
async def captcha_metrics():
    """CAPTCHA solve rate and rhythm state metrics."""
    from anti_anti_crawl.captcha_bypass import captcha_bypass
    from anti_anti_crawl.rhythm_detector import rhythm_detector
    from crawler.search_executor import search_executor

    return {
        "captcha": {
            "solve_rate": round(captcha_bypass.success_rate, 3),
            "total_solved": captcha_bypass._solved_count,
            "total_failed": captcha_bypass._fail_count,
        },
        "rhythm": rhythm_detector.get_stats(),
        "search": search_executor.stats,
    }


@app.get("/metrics/tls")
async def tls_metrics():
    """TLS client status."""
    from anti_anti_crawl.tls_client import TLSClient
    # Report what fingerprint version is configured
    return {
        "tls_impersonate": settings.TLS_IMPERSONATE,
        "available_targets": ["chrome124", "chrome120", "chrome123", "chrome121"],
    }


# ── Main ─────────────────────────────────────────────────

def main():
    import uvicorn
    uvicorn.run(
        "master.app:app",
        host=settings.MASTER_HOST,
        port=settings.MASTER_PORT,
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
