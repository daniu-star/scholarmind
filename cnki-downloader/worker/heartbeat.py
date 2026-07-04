"""10-second heartbeat emitter for worker → master."""

from __future__ import annotations

import asyncio
import json
import structlog
import time
from datetime import datetime, timezone
from typing import Optional

from redis.asyncio import Redis

from utils.system_monitor import get_system_stats
from config.settings import settings

logger = structlog.get_logger()


class HeartbeatEmitter:
    """Sends periodic heartbeat to Redis for master health monitoring."""

    def __init__(
        self,
        redis: Redis,
        worker_id: str,
        discipline: str,
        get_thread_status: callable,
        get_current_task: callable = None,
        get_tasks_completed: callable = None,
    ):
        self._redis = redis
        self.worker_id = worker_id
        self.discipline = discipline
        self._get_thread_status = get_thread_status
        self._get_current_task = get_current_task
        self._get_tasks_completed = get_tasks_completed
        self._running = False
        self._status = "idle"

    @property
    def status(self) -> str:
        return self._status

    @status.setter
    def status(self, value: str) -> None:
        self._status = value

    async def run(self) -> None:
        """Start the heartbeat loop. Publishes every HEARTBEAT_INTERVAL seconds."""
        self._running = True
        interval = settings.HEARTBEAT_INTERVAL

        logger.info(
            "heartbeat_started",
            worker_id=self.worker_id,
            interval=interval,
        )

        while self._running:
            try:
                await self._emit()
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error("heartbeat_error", error=str(e))
                await asyncio.sleep(interval)

    async def _emit(self) -> None:
        """Send a single heartbeat pulse."""
        key = f"cnki:heartbeat:{self.worker_id}"
        channel = "cnki:worker:heartbeat"

        thread_status = {}
        if self._get_thread_status:
            try:
                thread_status = self._get_thread_status()
            except Exception:
                pass

        system_stats = get_system_stats()
        current_task = ""
        tasks_completed = 0

        if self._get_current_task:
            try:
                current_task = await self._get_current_task() or ""
            except Exception:
                pass

        if self._get_tasks_completed:
            try:
                tasks_completed = await self._get_tasks_completed()
            except Exception:
                pass

        payload = json.dumps({
            "worker_id": self.worker_id,
            "discipline": self.discipline,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": self._status,
            "current_task": current_task,
            "tasks_completed": tasks_completed,
            "thread_status": thread_status,
            "cpu_percent": system_stats.cpu_percent,
            "memory_mb": round(system_stats.memory_rss_mb, 1),
        }, ensure_ascii=False)

        # SET with TTL
        await self._redis.set(key, payload, ex=settings.HEARTBEAT_TIMEOUT)

        # Publish for real-time monitoring
        await self._redis.publish(channel, payload)

        logger.debug("heartbeat_sent", worker_id=self.worker_id, status=self._status)

    async def stop(self) -> None:
        self._running = False
        logger.info("heartbeat_stopped", worker_id=self.worker_id)
