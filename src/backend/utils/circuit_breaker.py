"""
ScholarMind 熔断器
保护外部 API 调用，当连续失败达到阈值时自动熔断
"""
from __future__ import annotations

import time
import functools
import logging
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"          # 正常，请求通过
    OPEN = "open"             # 熔断，拒绝请求
    HALF_OPEN = "half_open"   # 半开，允许探测请求


class CircuitBreakerOpenError(Exception):
    """熔断器打开时抛出的异常"""
    def __init__(self, service: str):
        super().__init__(f"熔断器已打开：{service} 服务暂不可用，请稍后重试")


class CircuitBreaker:
    """熔断器

    用法：
        cnki_cb = CircuitBreaker(
            name="cnki",
            failure_threshold=3,
            recovery_timeout=30,
        )

        @cnki_cb
        async def search_cnki(query):
            ...

        # 或手动使用
        async with cnki_cb:
            result = await external_api_call()
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: int = 30,
        half_open_max: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout  # 熔断后等待的秒数
        self.half_open_max = half_open_max

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0
        self._half_open_count = 0

    @property
    def state(self) -> CircuitState:
        """当前状态"""
        self._transition_state()
        return self._state

    def _transition_state(self) -> None:
        """自动状态转换"""
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_count = 0
                logger.info(
                    "Circuit breaker transitioning to HALF_OPEN",
                    service=self.name,
                )

    def record_failure(self) -> None:
        """记录失败"""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            logger.warning(
                "Circuit breaker opened (half-open failure)",
                service=self.name,
                failures=self._failure_count,
            )
        elif self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "Circuit breaker opened",
                service=self.name,
                failures=self._failure_count,
            )

    def record_success(self) -> None:
        """记录成功"""
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_count += 1
            if self._half_open_count >= self.half_open_max:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                logger.info(
                    "Circuit breaker closed (recovery)",
                    service=self.name,
                )
        else:
            # 正常状态下重置计数器
            self._failure_count = 0

    def allow_request(self) -> bool:
        """检查是否允许请求通过"""
        self._transition_state()
        return self._state != CircuitState.OPEN

    async def __aenter__(self):
        if not self.allow_request():
            raise CircuitBreakerOpenError(self.name)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.record_success()
        elif exc_type is not CircuitBreakerOpenError:
            self.record_failure()
        return False  # 不吞异常

    def __call__(self, func: Callable):
        """装饰器模式"""
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not self.allow_request():
                raise CircuitBreakerOpenError(self.name)
            try:
                result = await func(*args, **kwargs)
                self.record_success()
                return result
            except Exception:
                self.record_failure()
                raise

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not self.allow_request():
                raise CircuitBreakerOpenError(self.name)
            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception:
                self.record_failure()
                raise

        return async_wrapper


# 全局熔断器实例
cnki_circuit_breaker = CircuitBreaker(
    name="cnki",
    failure_threshold=3,
    recovery_timeout=30,
)

deepseek_circuit_breaker = CircuitBreaker(
    name="deepseek",
    failure_threshold=5,
    recovery_timeout=60,
)