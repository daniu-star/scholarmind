"""Worker node entry point.

Starts the worker's thread pool, heartbeat, and task consumption loop.
One worker Docker container runs one instance of this for a single discipline.
"""

from __future__ import annotations

import asyncio
import json
import structlog
import os
import signal
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from redis.asyncio import Redis

from config.settings import settings
from config.journals import get_journals_for, JournalConfig
from models.task import Task
from models.enums import TaskStatus, ErrorCategory
from utils.redis_client import RedisClient, get_redis
from utils.logging_config import setup_logging
from worker.pipeline import DownloadPipeline
from worker.thread_pool import WorkerThreadPool
from worker.heartbeat import HeartbeatEmitter
from master.protocols.redis_protocol import RedisProtocol

logger = structlog.get_logger()


class CNKIWorker:
    """Main CNKI downloader worker node."""

    def __init__(self):
        self.worker_id = f"worker-{settings.DISCIPLINE}-{uuid.uuid4().hex[:6]}"
        self.discipline = settings.DISCIPLINE
        self.thread_count = settings.THREAD_COUNT
        self.storage_base = Path(settings.STORAGE_BASE)

        self._redis: Optional[Redis] = None
        self._pool: Optional[WorkerThreadPool] = None
        self._heartbeat: Optional[HeartbeatEmitter] = None
        self._pipeline: Optional[DownloadPipeline] = None
        self._protocol: Optional[RedisProtocol] = None
        self._running = False
        self._pause = False

        self._tasks_completed = 0
        self._tasks_failed = 0

    async def start(self) -> None:
        """Initialize and start the worker."""
        setup_logging(worker_id=self.worker_id)

        # Connect to Redis
        self._redis = await get_redis()

        # Load Lua scripts for atomic task operations
        self._protocol = RedisProtocol(self._redis)
        await self._protocol.load_scripts()
        logger.info("lua_scripts_loaded")

        # Register worker
        await self._redis.hset(
            f"cnki:worker:{self.worker_id}",
            mapping={
                "worker_id": self.worker_id,
                "discipline": self.discipline,
                "thread_count": str(self.thread_count),
                "status": "starting",
                "started_at": str(time.time()),
            },
        )

        # Initialize components
        self._pipeline = DownloadPipeline(
            self.worker_id, self.discipline, self.storage_base
        )

        self._pool = WorkerThreadPool(
            thread_count=self.thread_count,
            worker_id=self.worker_id,
            discipline=self.discipline,
        )

        self._heartbeat = HeartbeatEmitter(
            redis=self._redis,
            worker_id=self.worker_id,
            discipline=self.discipline,
            get_thread_status=self._pool.get_status,
            get_tasks_completed=self._get_tasks_completed,
        )

        # Start thread pool
        self._pool.start(self._handle_task)

        # Start heartbeat
        asyncio.create_task(self._heartbeat.run())

        # Listen for master commands
        asyncio.create_task(self._listen_commands())

        # Start task consumption loop
        self._running = True
        self._heartbeat.status = "idle"

        logger.info(
            "worker_started",
            worker_id=self.worker_id,
            discipline=self.discipline,
            thread_count=self.thread_count,
        )

        # Publish worker started event
        await self._redis.publish(
            "cnki:worker:events",
            json.dumps({
                "event": "worker_started",
                "worker_id": self.worker_id,
                "discipline": self.discipline,
                "thread_count": self.thread_count,
            }),
        )

        # Main consumption loop
        await self._task_loop()

    async def _task_loop(self) -> None:
        """Main loop: continuously pull tasks from Redis queue."""
        queue_key = f"cnki:task:queue:{self.discipline}"
        retry_key = f"cnki:task:queue:{self.discipline}:retry"
        assigned_key = f"cnki:task:assigned:{self.worker_id}"

        while self._running:
            if self._pause:
                self._heartbeat.status = "paused"
                await asyncio.sleep(5)
                continue

            try:
                # Atomically acquire task from main queue via Lua script.
                # The script does RPOP + HSET + SET(lock) + SADD in one atomic step.
                result = await self._protocol.evalsha(
                    "task_acquire",
                    keys=[queue_key, assigned_key],
                    args=[self.worker_id, str(time.time())],
                )

                # Fall back to retry queue if main queue is empty
                if not result:
                    result = await self._protocol.evalsha(
                        "task_acquire",
                        keys=[retry_key, assigned_key],
                        args=[self.worker_id, str(time.time())],
                    )

                if result:
                    # Lua script returns updated task JSON
                    task_json = result.decode() if isinstance(result, bytes) else result
                    task_data = json.loads(task_json)
                    task = Task.from_dict(task_data)

                    self._heartbeat.status = "working"
                    logger.info(
                        "task_acquired",
                        task_id=task.task_id,
                        journal=task.journal_name,
                        year=task.year,
                    )

                    # Submit to thread pool
                    future = self._pool.submit_task(task, self._handle_task)
                    # Don't await — thread pool handles execution

                    # Future 异常安全网：捕获 _handle_task 未处理的异常
                    def _on_future_done(fut, _task_id=task.task_id):
                        try:
                            fut.result()  # 触发异常（如有）
                        except Exception as e:
                            logger.error(
                                "task_future_exception",
                                error=str(e),
                                task_id=_task_id,
                            )
                            self._pool.increment_failed(threading.current_thread().name)

                    future.add_done_callback(_on_future_done)
                else:
                    self._heartbeat.status = "idle"
                    await asyncio.sleep(2)

            except Exception as e:
                logger.error("task_loop_error", error=str(e))
                await asyncio.sleep(5)

    async def _handle_task(self, task: Task) -> None:
        """Handle a single task — called in worker thread."""
        import redis.asyncio as aioredis
        from datetime import datetime, timezone

        # Create a thread-local Redis client bound to this thread's event loop.
        # self._redis is bound to the main event loop and cannot be safely used
        # from a worker thread (connection pool would be attached to the wrong loop).
        thread_redis = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
        try:
            paper = await self._pipeline.execute_task(task)

            if paper:
                # Success
                self._tasks_completed += 1

                # Clean up Redis
                await thread_redis.delete(f"cnki:task:data:{task.task_id}")
                await thread_redis.delete(f"cnki:lock:task:{task.task_id}")
                await thread_redis.srem(
                    f"cnki:task:assigned:{self.worker_id}",
                    task.task_id,
                )

                # Update stats
                await thread_redis.hincrby(
                    f"cnki:stats:{self.discipline}", "completed", 1
                )
                await thread_redis.hincrby("cnki:stats:global", "completed", 1)

                # Publish event
                await thread_redis.publish(
                    "cnki:worker:events",
                    json.dumps({
                        "event": "task_completed",
                        "task_id": task.task_id,
                        "worker_id": self.worker_id,
                        "paper": paper.to_dict(),
                    }),
                )

                logger.info("task_completed", task_id=task.task_id)
                # 更新线程池级别的完成计数
                self._pool.increment_completed(threading.current_thread().name)

            else:
                self._pool.increment_failed(threading.current_thread().name)
                await self._handle_failed_task(task, thread_redis)

        except Exception as e:
            logger.error("task_handler_error", task_id=task.task_id, error=str(e))
            self._pool.increment_failed(threading.current_thread().name)
            await self._handle_failed_task(task, thread_redis)
        finally:
            await thread_redis.close()

    async def _handle_failed_task(self, task: Task, redis_client: Optional[Redis] = None) -> None:
        """Handle a failed task with retry logic."""
        r = redis_client if redis_client is not None else self._redis
        self._tasks_failed += 1

        if task.retry_count < task.max_retries:
            task.retry_count += 1
            task.status = TaskStatus.RETRYING

            # Push to retry queue with updated retry count
            await r.lpush(
                f"cnki:task:queue:{self.discipline}:retry",
                task.to_json(),
            )

            # Update stats
            await r.hincrby(
                f"cnki:stats:{self.discipline}", "failed", 1
            )

            logger.warning(
                "task_retrying",
                task_id=task.task_id,
                retry=task.retry_count,
                max_retries=task.max_retries,
            )
        else:
            task.status = TaskStatus.FAILED

            # Publish failed event
            await r.publish(
                "cnki:worker:events",
                json.dumps({
                    "event": "task_failed",
                    "task_id": task.task_id,
                    "worker_id": self.worker_id,
                    "error": task.error_message,
                    "error_type": task.error_type,
                    "retries": task.retry_count,
                }),
            )

            logger.error(
                "task_permanently_failed",
                task_id=task.task_id,
                error=task.error_message,
                retries=task.retry_count,
            )

        # Clean up lock and assignment
        await r.delete(f"cnki:lock:task:{task.task_id}")
        await r.srem(
            f"cnki:task:assigned:{self.worker_id}",
            task.task_id,
        )

    async def _listen_commands(self) -> None:
        """Listen for master commands on Pub/Sub channel.

        Task 4.3: 支持 worker_id 精确定向。消息中 worker_id="all" 或缺失时
        广播给所有 Worker；否则仅 worker_id 匹配自身的 Worker 响应。
        """
        pubsub = self._redis.pubsub()
        await pubsub.subscribe("cnki:master:commands")

        logger.info("command_listener_started")

        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                data = json.loads(message["data"])
                cmd = data.get("command", "")
                target = data.get("discipline", "all")

                if target not in ("all", self.discipline):
                    continue

                # Task 4.3: worker_id 精确定向 — 不匹配则忽略
                target_worker = data.get("worker_id", "all")
                if target_worker not in ("all", self.worker_id):
                    continue

                if cmd == "pause":
                    self._pause = True
                    logger.info("worker_paused")
                elif cmd == "resume":
                    self._pause = False
                    logger.info("worker_resumed")
                elif cmd == "shutdown":
                    logger.info("worker_shutdown_command")
                    await self.stop()
                    break
                elif cmd == "reconfigure":
                    await self._reconfigure(data)

            except Exception as e:
                logger.error("command_parse_error", error=str(e))

    async def _reconfigure(self, data: dict) -> None:
        """Reload configuration from master command."""
        logger.info("worker_reconfigured", config=data)

    async def _get_tasks_completed(self) -> int:
        return self._tasks_completed

    async def stop(self) -> None:
        """Gracefully shutdown the worker."""
        self._running = False
        self._heartbeat.status = "stopped"

        if self._heartbeat:
            await self._heartbeat.stop()

        if self._pool:
            self._pool.shutdown(wait=False)

        if self._redis:
            await self._redis.delete(f"cnki:worker:{self.worker_id}")
            await self._redis.delete(f"cnki:heartbeat:{self.worker_id}")
            await self._redis.publish(
                "cnki:worker:events",
                json.dumps({
                    "event": "worker_stopped",
                    "worker_id": self.worker_id,
                }),
            )

        logger.info("worker_stopped")


async def main():
    """Entry point for worker."""
    worker = CNKIWorker()

    # Handle graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.stop()))
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        await worker.start()
    except Exception as e:
        logger.error("worker_fatal_error", error=str(e))
    finally:
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
