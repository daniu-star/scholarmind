"""3-thread pool management for parallel task execution.

Each thread gets its own pipeline, browser context, and event loop.
"""

from __future__ import annotations

import asyncio
import structlog
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Optional, Callable

from models.task import Task

logger = structlog.get_logger()


class WorkerThreadPool:
    """Manages a pool of worker threads for parallel CNKI downloading."""

    def __init__(
        self,
        thread_count: int = 3,
        worker_id: str = "",
        discipline: str = "",
    ):
        self.thread_count = thread_count
        self.worker_id = worker_id
        self.discipline = discipline
        self._executor: Optional[ThreadPoolExecutor] = None
        self._threads: dict[int, dict] = {}
        self._running = False
        # 线程安全：保护 self._threads 的并发读写
        self._lock = threading.Lock()
        # 用 threading.local() 替代 hash() 映射线程到状态槽位
        # hash() 对字符串的结果在不同 Python 进程间不保证一致
        self._thread_index = threading.local()
        self._next_index = 0

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, task_handler: Callable[[Task], object]) -> None:
        """Start the thread pool. task_handler is called per task."""
        if self._running:
            return

        self._executor = ThreadPoolExecutor(
            max_workers=self.thread_count,
            thread_name_prefix=f"cnki-{self.discipline}",
        )
        self._running = True

        with self._lock:
            for i in range(self.thread_count):
                thread_id = i
                self._threads[thread_id] = {
                    "status": "idle",
                    "current_task": "",
                    "tasks_completed": 0,
                    "tasks_failed": 0,
                    "started_at": time.time(),
                }

        logger.info(
            "thread_pool_started",
            worker_id=self.worker_id,
            discipline=self.discipline,
            thread_count=self.thread_count,
        )

    def submit_task(self, task: Task, handler: Callable[[Task], object]) -> Future:
        """Submit a task to the thread pool."""
        if not self._executor:
            raise RuntimeError("Thread pool not started")

        return self._executor.submit(
            self._run_in_thread,
            handler,
            task,
        )

    def _run_in_thread(self, handler: Callable[[Task], object], task: Task) -> object:
        """Run a task in a dedicated thread with its own event loop."""
        # 分配线程索引（thread-local，避免 hash() 不稳定问题）
        if not hasattr(self._thread_index, "value"):
            with self._lock:
                self._thread_index.value = self._next_index
                self._next_index += 1
        idx = self._thread_index.value % self.thread_count
        thread_name = threading.current_thread().name

        with self._lock:
            if idx not in self._threads:
                self._threads[idx] = {
                    "status": "idle",
                    "current_task": "",
                    "tasks_completed": 0,
                    "tasks_failed": 0,
                    "started_at": time.time(),
                }
            self._threads[idx].update({
                "status": "working",
                "current_task": task.task_id,
            })

        try:
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            result = loop.run_until_complete(
                self._execute_with_timeout(handler, task)
            )

            return result

        except Exception as e:
            logger.error("thread_task_failed", thread=thread_name, error=str(e))
            raise

        finally:
            with self._lock:
                if idx in self._threads:
                    self._threads[idx]["status"] = "idle"
                    self._threads[idx]["current_task"] = ""

    async def _execute_with_timeout(
        self, handler: Callable[[Task], object], task: Task
    ) -> object:
        """Execute handler with timeout protection."""
        try:
            return await asyncio.wait_for(
                handler(task),
                timeout=600,  # 10 minute timeout per task
            )
        except asyncio.TimeoutError:
            logger.error("task_timeout", task_id=task.task_id)
            raise

    def get_status(self) -> dict:
        """Get current status of all threads."""
        with self._lock:
            threads_status = {}
            for tid, info in self._threads.items():
                threads_status[str(tid)] = {
                    "status": info.get("status", "unknown"),
                    "current_task": info.get("current_task", ""),
                    "tasks_completed": info.get("tasks_completed", 0),
                    "tasks_failed": info.get("tasks_failed", 0),
                    "uptime_seconds": int(time.time() - info.get("started_at", time.time())),
                }
            return threads_status

    def increment_completed(self, thread_name: str = "") -> None:
        """Increment completed task counter for a thread.

        使用 thread-local 索引而非 hash(thread_name)，确保与 _run_in_thread
        分配的槽位一致。thread_name 参数保留以保持向后兼容。
        """
        try:
            if not hasattr(self._thread_index, "value"):
                return
            idx = self._thread_index.value % self.thread_count
            with self._lock:
                if idx in self._threads:
                    self._threads[idx]["tasks_completed"] += 1
        except Exception:
            pass

    def increment_failed(self, thread_name: str = "") -> None:
        """Increment failed task counter for a thread.

        使用 thread-local 索引而非 hash(thread_name)，确保与 _run_in_thread
        分配的槽位一致。thread_name 参数保留以保持向后兼容。
        """
        try:
            if not hasattr(self._thread_index, "value"):
                return
            idx = self._thread_index.value % self.thread_count
            with self._lock:
                if idx in self._threads:
                    self._threads[idx]["tasks_failed"] += 1
        except Exception:
            pass

    def shutdown(self, wait: bool = True) -> None:
        """Gracefully shutdown the thread pool."""
        self._running = False
        if self._executor:
            self._executor.shutdown(wait=wait, cancel_futures=True)
            self._executor = None
        logger.info("thread_pool_shutdown", worker_id=self.worker_id)
