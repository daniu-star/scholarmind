"""Exponential backoff retry with jitter and error categories.

Reuses pattern from existing ScholarMind base.py lines 49-68.
"""

from __future__ import annotations

import asyncio
import structlog
import random
import time
import functools
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Optional, Any

from models.enums import ErrorCategory

logger = structlog.get_logger()


# ── Retry Configuration ──

@dataclass
class RetryConfig:
    base_delay: float = 3.0
    max_delay: float = 600.0
    backoff_multiplier: float = 2.0
    jitter: float = 0.25
    max_retries: int = 5

    CATEGORY_CONFIGS: dict[ErrorCategory, dict] = field(default_factory=lambda: {
        ErrorCategory.NETWORK:        {"base_delay": 5.0,  "max_delay": 120,  "max_retries": 5},
        ErrorCategory.RATE_LIMIT:     {"base_delay": 30.0, "max_delay": 900,  "max_retries": 3},
        ErrorCategory.CAPTCHA:        {"base_delay": 60.0, "max_delay": 1800, "max_retries": 3},
        ErrorCategory.PARSE:          {"base_delay": 10.0, "max_delay": 60,   "max_retries": 2},
        ErrorCategory.PDF_UNAVAILABLE: {"max_retries": 0},
        ErrorCategory.AUTH:           {"base_delay": 120.0, "max_delay": 600, "max_retries": 2},
        ErrorCategory.UNKNOWN:        {"base_delay": 5.0,  "max_delay": 120,  "max_retries": 3},
    })

    def get_config(self, category: ErrorCategory) -> dict:
        return self.CATEGORY_CONFIGS.get(category, {})


DEFAULT_RETRY_CONFIG = RetryConfig()


# ── Backoff Calculation ──

def compute_backoff(
    retry_count: int,
    category: ErrorCategory = ErrorCategory.UNKNOWN,
    config: RetryConfig = DEFAULT_RETRY_CONFIG,
) -> float:
    """Calculate backoff delay with exponential growth + jitter."""
    cat_cfg = config.get_config(category)
    base = cat_cfg.get("base_delay", config.base_delay)
    max_d = cat_cfg.get("max_delay", config.max_delay)
    multiplier = cat_cfg.get("backoff_multiplier", config.backoff_multiplier)

    delay = base * (multiplier ** retry_count)
    jitter_amount = delay * random.uniform(-config.jitter, config.jitter)
    return min(delay + jitter_amount, max_d)


def max_retries_for(category: ErrorCategory, config: RetryConfig = DEFAULT_RETRY_CONFIG) -> int:
    cat_cfg = config.get_config(category)
    return cat_cfg.get("max_retries", config.max_retries)


# ── Retry Decorator ──

def retry_with_backoff(
    max_retries: Optional[int] = None,
    category: ErrorCategory = ErrorCategory.UNKNOWN,
    config: RetryConfig = DEFAULT_RETRY_CONFIG,
    on_retry: Optional[Callable] = None,
):
    """Decorator for async functions with exponential backoff retry."""
    limit = max_retries if max_retries is not None else max_retries_for(category)

    def decorator(func: Callable[..., Awaitable]):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(limit + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt >= limit:
                        logger.error(
                            "retry_exhausted",
                            function=func.__name__,
                            attempts=attempt + 1,
                            category=category.value,
                            error=str(e),
                        )
                        raise

                    delay = compute_backoff(attempt, category, config)
                    logger.warning(
                        "retry_attempt",
                        function=func.__name__,
                        attempt=attempt + 1,
                        max_retries=limit,
                        delay=round(delay, 2),
                        category=category.value,
                        error=str(e),
                    )
                    if on_retry:
                        await on_retry(attempt + 1, e)
                    await asyncio.sleep(delay)
            raise last_exception  # type: ignore[misc]
        return wrapper
    return decorator


# ── Retry Context Manager ──

class RetryManager:
    """Async context manager for retry logic."""

    def __init__(
        self,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        config: RetryConfig = DEFAULT_RETRY_CONFIG,
        on_retry: Optional[Callable] = None,
    ):
        self.category = category
        self.config = config
        self.on_retry = on_retry
        self.max_retries = max_retries_for(category, config)

    async def execute(self, coro_factory: Callable[[], Awaitable]) -> Any:
        last_exception = None
        for attempt in range(self.max_retries + 1):
            try:
                return await coro_factory()
            except Exception as e:
                last_exception = e
                if attempt >= self.max_retries:
                    raise

                delay = compute_backoff(attempt, self.category, self.config)
                logger.warning(
                    "retry_manager_attempt",
                    attempt=attempt + 1,
                    max_retries=self.max_retries,
                    delay=round(delay, 2),
                    category=self.category.value,
                )
                if self.on_retry:
                    await self.on_retry(attempt + 1, e)
                await asyncio.sleep(delay)
        raise last_exception  # type: ignore[misc]


# ── Circuit Breaker ──

class CircuitBreaker:
    """Circuit breaker to prevent hammering blocked endpoints.

    Reuses pattern from existing ScholarMind utils/circuit_breaker.py.
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        timeout: float = 300.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self._failures = 0
        self._last_failure_time = 0.0
        self._state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    @property
    def is_open(self) -> bool:
        if self._state == "CLOSED":
            return False
        if self._state == "OPEN":
            if time.monotonic() - self._last_failure_time >= self.timeout:
                self._state = "HALF_OPEN"
                logger.info("circuit_breaker_half_open", name=self.name)
                return False
            return True
        return False  # HALF_OPEN

    def success(self) -> None:
        if self._state == "HALF_OPEN":
            self._state = "CLOSED"
            self._failures = 0
            logger.info("circuit_breaker_closed", name=self.name)
        self._failures = 0

    def failure(self) -> None:
        self._failures += 1
        self._last_failure_time = time.monotonic()
        if self._failures >= self.failure_threshold:
            self._state = "OPEN"
            logger.warning(
                "circuit_breaker_opened: name=%s failures=%d timeout=%d",
                self.name, self._failures, self.timeout,
            )

    async def __aenter__(self):
        if self.is_open:
            raise CircuitBreakerOpenError(self.name, self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.success()
        elif exc_type is not None and not isinstance(exc_val, CircuitBreakerOpenError):
            self.failure()
        return False


class CircuitBreakerOpenError(Exception):
    def __init__(self, name: str, timeout: float):
        self.name = name
        self.timeout = timeout
        super().__init__(f"Circuit breaker '{name}' is OPEN (timeout={timeout}s)")
