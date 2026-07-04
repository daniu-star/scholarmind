"""Redis task queue management and lifecycle operations."""

from __future__ import annotations

import json
import structlog
from datetime import datetime, timezone
from typing import Optional

from redis.asyncio import Redis

from models.task import Task
from models.enums import TaskStatus

logger = structlog.get_logger()


class TaskManager:
    """Manages task lifecycle in Redis queues."""

    def __init__(self, redis: Redis):
        self._redis = redis

    # ── Task Enqueue ──────────────────────────────────────

    async def enqueue(self, task: Task) -> str:
        """Push a task to its discipline queue."""
        queue_key = f"cnki:task:queue:{task.discipline}"

        task.status = TaskStatus.QUEUED
        task.created_at = datetime.now(timezone.utc).isoformat()

        await self._redis.lpush(queue_key, task.to_json())
        await self._redis.hset(
            f"cnki:task:data:{task.task_id}",
            mapping=task.to_redis_hash(),
        )
        await self._redis.hincrby(
            f"cnki:stats:{task.discipline}", "pending", 1
        )
        await self._redis.hincrby("cnki:stats:global", "pending", 1)

        logger.debug("task_enqueued", task_id=task.task_id, discipline=task.discipline)
        return task.task_id

    async def enqueue_batch(self, tasks: list[Task]) -> int:
        """Enqueue multiple tasks at once."""
        if not tasks:
            return 0

        pipe = self._redis.pipeline()
        for task in tasks:
            task.status = TaskStatus.QUEUED
            task.created_at = datetime.now(timezone.utc).isoformat()
            queue_key = f"cnki:task:queue:{task.discipline}"
            pipe.lpush(queue_key, task.to_json())
            pipe.hset(f"cnki:task:data:{task.task_id}", mapping=task.to_redis_hash())

        await pipe.execute()

        # Update stats
        for discipline in set(t.discipline for t in tasks):
            count = sum(1 for t in tasks if t.discipline == discipline)
            await self._redis.hincrby(f"cnki:stats:{discipline}", "pending", count)
        await self._redis.hincrby("cnki:stats:global", "pending", len(tasks))

        logger.info("tasks_enqueued_batch", count=len(tasks))
        return len(tasks)

    # ── Task Requeue (for failed/stalled tasks) ────────────

    async def requeue(self, task_id: str, priority: int = 5) -> bool:
        """Re-queue a failed or stalled task with higher priority."""
        task_data = await self._redis.hgetall(f"cnki:task:data:{task_id}")
        if not task_data:
            return False

        task = Task.from_redis_hash(task_data)
        task.status = TaskStatus.QUEUED
        task.priority = priority
        task.retry_count += 1

        # LPUSH for higher priority (front of queue)
        queue_key = f"cnki:task:queue:{task.discipline}"
        await self._redis.lpush(queue_key, task.to_json())
        await self._redis.hset(f"cnki:task:data:{task_id}", mapping=task.to_redis_hash())
        await self._redis.delete(f"cnki:lock:task:{task_id}")

        logger.info("task_requeued", task_id=task_id, priority=priority)
        return True

    async def requeue_all_failed(self, discipline: str = "") -> int:
        """Re-queue all failed tasks for a discipline (or all)."""
        count = 0
        disciplines = [discipline] if discipline else await self._list_disciplines()

        for disc in disciplines:
            retry_key = f"cnki:task:queue:{disc}:retry"
            while True:
                task_json = await self._redis.lpop(retry_key)
                if not task_json:
                    break
                task = Task.from_dict(json.loads(task_json))
                task.priority = 5
                await self.enqueue(task)
                count += 1

        logger.info("failed_tasks_requeued", count=count)
        return count

    # ── Task Query ───────────────────────────────────────

    async def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve a task by ID."""
        data = await self._redis.hgetall(f"cnki:task:data:{task_id}")
        if not data:
            return None
        return Task.from_redis_hash(data)

    async def get_tasks_by_status(
        self, status: str, discipline: str = "", limit: int = 50
    ) -> list[Task]:
        """Get tasks by status (scans all task data)."""
        tasks: list[Task] = []
        cursor = 0
        pattern = f"cnki:task:data:*"

        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
            for key in keys:
                data = await self._redis.hgetall(key)
                if data:
                    task = Task.from_redis_hash(data)
                    if task.status.value == status:
                        if not discipline or task.discipline == discipline:
                            tasks.append(task)
                if len(tasks) >= limit:
                    break
            if cursor == 0 or len(tasks) >= limit:
                break

        return tasks

    async def get_queue_size(self, discipline: str) -> int:
        """Get the current queue size for a discipline."""
        return await self._redis.llen(f"cnki:task:queue:{discipline}")

    async def get_all_queue_sizes(self) -> dict[str, int]:
        """Get queue sizes for all disciplines."""
        sizes = {}
        for disc in await self._list_disciplines():
            sizes[disc] = await self.get_queue_size(disc)
            retry_count = await self._redis.llen(f"cnki:task:queue:{disc}:retry")
            sizes[f"{disc}:retry"] = retry_count
        return sizes

    # ── Stats ────────────────────────────────────────────

    async def get_stats(self, discipline: str = "") -> dict:
        """Get task statistics."""
        key = f"cnki:stats:{discipline}" if discipline else "cnki:stats:global"
        data = await self._redis.hgetall(key)
        if not data:
            return {"total": 0, "completed": 0, "failed": 0, "pending": 0}

        return {
            k.decode() if isinstance(k, bytes) else k:
            int(v.decode() if isinstance(v, bytes) else v)
            for k, v in data.items()
        }

    # ── Cleanup ──────────────────────────────────────────

    async def cleanup_stale(self, older_than_hours: int = 48) -> int:
        """Remove task data older than the specified hours."""
        count = 0
        cutoff = datetime.now(timezone.utc).timestamp() - older_than_hours * 3600

        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(cursor, match="cnki:task:data:*", count=200)
            for key in keys:
                data = await self._redis.hgetall(key)
                created = data.get(b"created_at", b"").decode()
                try:
                    ts = datetime.fromisoformat(created).timestamp()
                    if ts < cutoff:
                        await self._redis.delete(key)
                        count += 1
                except Exception:
                    pass
            if cursor == 0:
                break

        logger.info("stale_tasks_cleaned", count=count, older_than_hours=older_than_hours)
        return count

    async def _list_disciplines(self) -> list[str]:
        from config.journals import VALID_DISCIPLINES
        return VALID_DISCIPLINES
