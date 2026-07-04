"""Master health monitor — watches worker heartbeats, reaps zombies.

- Scans all cnki:heartbeat:* keys every 15 seconds
- Marks workers as DEAD if no heartbeat for 30 seconds
- Re-queues stalled tasks (>15 min without progress)
- Cleans up dead worker assignments
"""

from __future__ import annotations

import asyncio
import json
import structlog
import time
from typing import Optional, Any

from redis.asyncio import Redis

from config.settings import settings
from master.task_manager import TaskManager
from models.enums import TaskStatus

logger = structlog.get_logger()


class HealthMonitor:
    """Monitors worker health and task liveness."""

    CHECK_INTERVAL = 15  # seconds
    HEARTBEAT_TIMEOUT = settings.HEARTBEAT_TIMEOUT  # 30s
    TASK_STALL_TIMEOUT = settings.TASK_STALL_TIMEOUT  # 900s (15 min)

    def __init__(self, redis: Redis):
        self._redis = redis
        self._task_manager = TaskManager(redis)
        self._running = False
        self._dead_workers: set[str] = set()
        self._zombie_tasks: set[str] = set()

    async def run(self) -> None:
        """Start health monitoring loop."""
        self._running = True
        logger.info("health_monitor_started", check_interval=self.CHECK_INTERVAL)

        while self._running:
            try:
                await self._scan_workers()
                await self._scan_stalled_tasks()
                await asyncio.sleep(self.CHECK_INTERVAL)
            except Exception as e:
                logger.error("health_monitor_error", error=str(e))
                await asyncio.sleep(self.CHECK_INTERVAL)

    async def _scan_workers(self) -> None:
        """Scan all worker heartbeats and detect dead workers."""
        cursor = 0
        alive_workers: list[str] = []

        while True:
            cursor, keys = await self._redis.scan(
                cursor, match="cnki:heartbeat:*", count=50
            )
            for key in keys:
                try:
                    worker_id = key.decode().replace("cnki:heartbeat:", "")
                    hb_data = await self._redis.get(key)

                    if hb_data is None:
                        # Heartbeat expired — worker is dead
                        await self._handle_dead_worker(worker_id)
                    else:
                        alive_workers.append(worker_id)
                        # Update worker info
                        hb = json.loads(hb_data)
                        await self._redis.hset(
                            f"cnki:worker:{worker_id}",
                            mapping={
                                "status": hb.get("status", "unknown"),
                                "last_heartbeat": str(time.time()),
                                "cpu_percent": str(hb.get("cpu_percent", 0)),
                                "memory_mb": str(hb.get("memory_mb", 0)),
                                "tasks_completed": str(hb.get("tasks_completed", 0)),
                            },
                        )
                except Exception as e:
                    logger.warning("worker_scan_error", key=str(key), error=str(e))
            if cursor == 0:
                break

        logger.debug("health_scan_complete", alive_workers=len(alive_workers))

    async def _handle_dead_worker(self, worker_id: str) -> None:
        """Handle a dead worker — re-queue its tasks."""
        if worker_id in self._dead_workers:
            return  # Already handled

        self._dead_workers.add(worker_id)
        logger.error("worker_dead", worker_id=worker_id)

        # Get all tasks assigned to dead worker
        assigned_key = f"cnki:task:assigned:{worker_id}"
        task_ids = await self._redis.smembers(assigned_key)

        if task_ids:
            for task_id in task_ids:
                tid = task_id.decode() if isinstance(task_id, bytes) else task_id
                success = await self._task_manager.requeue(tid, priority=10)
                if success:
                    self._zombie_tasks.add(tid)
                    logger.info("task_recovered_from_dead_worker", task_id=tid)

        # Clean up dead worker data
        await self._redis.delete(assigned_key)
        await self._redis.delete(f"cnki:worker:{worker_id}")
        await self._redis.delete(f"cnki:heartbeat:{worker_id}")

        # Publish alert
        await self._redis.publish(
            "cnki:worker:events",
            json.dumps({
                "event": "worker_died",
                "worker_id": worker_id,
                "orphaned_tasks": len(task_ids),
            }),
        )

    async def _scan_stalled_tasks(self) -> None:
        """Scan for tasks that have been processing too long (zombie tasks)."""
        now = time.time()

        for discipline in self._get_disciplines():
            cursor = 0
            pattern = f"cnki:task:data:*"

            while True:
                cursor, keys = await self._redis.scan(
                    cursor, match=pattern, count=100
                )
                for key in keys:
                    try:
                        data = await self._redis.hgetall(key)
                        status = data.get(b"status", b"").decode()
                        if status not in ("assigned", "processing"):
                            continue

                        started = data.get(b"started_at", b"").decode()
                        try:
                            # Parse timestamp and check staleness
                            started_ts = _parse_iso_timestamp(started)
                            if now - started_ts > self.TASK_STALL_TIMEOUT:
                                task_id = key.decode().replace("cnki:task:data:", "")
                                if task_id not in self._zombie_tasks:
                                    self._zombie_tasks.add(task_id)
                                    await self._task_manager.requeue(task_id, priority=10)
                                    logger.warning("zombie_task_recovered", task_id=task_id)
                        except Exception:
                            pass
                    except Exception:
                        continue
                if cursor == 0:
                    break

    @staticmethod
    def _get_disciplines() -> list[str]:
        from config.journals import VALID_DISCIPLINES
        return VALID_DISCIPLINES

    async def get_workers_status(self) -> list[dict]:
        """Get status of all registered workers."""
        workers = []
        cursor = 0

        while True:
            cursor, keys = await self._redis.scan(
                cursor, match="cnki:worker:*", count=50
            )
            for key in keys:
                data = await self._redis.hgetall(key)
                if data:
                    worker_id = key.decode().replace("cnki:worker:", "")
                    decoded = {
                        (k.decode() if isinstance(k, bytes) else k):
                        (v.decode() if isinstance(v, bytes) else v)
                        for k, v in data.items()
                    }

                    # Check if alive
                    hb = await self._redis.get(f"cnki:heartbeat:{worker_id}")
                    decoded["alive"] = hb is not None
                    decoded["worker_id"] = worker_id

                    workers.append(decoded)
            if cursor == 0:
                break

        return sorted(workers, key=lambda w: w.get("discipline", ""))

    async def get_health_summary(self) -> dict:
        """Get overall health summary."""
        workers = await self.get_workers_status()
        alive = sum(1 for w in workers if w.get("alive"))
        dead = len(workers) - alive

        stats = await self._task_manager.get_stats()

        return {
            "status": "healthy" if alive > 0 else "critical",
            "workers": {"total": len(workers), "alive": alive, "dead": dead},
            "tasks": stats,
            "zombie_tasks_recovered": len(self._zombie_tasks),
            "dead_workers_detected": len(self._dead_workers),
        }

    async def stop(self) -> None:
        self._running = False
        logger.info("health_monitor_stopped")


def _parse_iso_timestamp(ts_str: str) -> float:
    """Parse a timestamp to Unix time. Supports ISO 8601 and epoch numbers."""
    if not ts_str:
        return 0.0
    try:
        # Python 3.7+ fromisoformat
        from datetime import datetime
        return datetime.fromisoformat(ts_str).timestamp()
    except (ValueError, TypeError):
        pass
    # Fallback: try epoch number (e.g. str(time.time()) from worker)
    try:
        return float(ts_str)
    except (ValueError, TypeError):
        return 0.0
