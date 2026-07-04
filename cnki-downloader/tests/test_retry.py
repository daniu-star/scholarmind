"""Tests for retry and circuit breaker utilities."""

import asyncio
import pytest

from models.enums import ErrorCategory
from utils.retry import (
    RetryConfig,
    compute_backoff,
    max_retries_for,
    CircuitBreaker,
    CircuitBreakerOpenError,
    retry_with_backoff,
)


class TestBackoff:
    """Tests for backoff calculation."""

    def test_network_backoff(self):
        delay = compute_backoff(0, ErrorCategory.NETWORK)
        assert 1.0 <= delay <= 10.0

    def test_rate_limit_backoff_longer(self):
        delay_0 = compute_backoff(0, ErrorCategory.RATE_LIMIT)
        delay_2 = compute_backoff(2, ErrorCategory.RATE_LIMIT)
        assert delay_0 >= 15  # base 30s with jitter
        assert delay_2 > delay_0  # exponential growth

    def test_captcha_has_fewer_retries(self):
        assert max_retries_for(ErrorCategory.CAPTCHA) == 3
        assert max_retries_for(ErrorCategory.NETWORK) == 5

    def test_pdf_unavailable_no_retries(self):
        assert max_retries_for(ErrorCategory.PDF_UNAVAILABLE) == 0

    def test_backoff_capped_at_max(self):
        delay = compute_backoff(10, ErrorCategory.NETWORK)
        assert delay <= 120  # max_delay for network

    def test_jitter_adds_variation(self):
        delays = [compute_backoff(1, ErrorCategory.NETWORK) for _ in range(10)]
        # Not all identical due to jitter
        assert len(set(round(d, 2) for d in delays)) > 1


class TestCircuitBreaker:
    """Tests for circuit breaker."""

    @pytest.mark.asyncio
    async def test_initial_state_closed(self):
        cb = CircuitBreaker("test")
        assert not cb.is_open
        assert cb._state == "CLOSED"

    @pytest.mark.asyncio
    async def test_opens_after_failures(self):
        cb = CircuitBreaker("test", failure_threshold=3, timeout=300)
        for _ in range(3):
            await cb.__aenter__()
            await cb.__aexit__(Exception, Exception("fail"), None)
        assert cb.is_open

    @pytest.mark.asyncio
    async def test_closed_stays_closed_on_success(self):
        cb = CircuitBreaker("test", failure_threshold=3, timeout=300)
        for _ in range(2):
            await cb.__aenter__()
            await cb.__aexit__(Exception, Exception("fail"), None)
        # Success on third
        await cb.__aenter__()
        await cb.__aexit__(None, None, None)
        assert not cb.is_open

    @pytest.mark.asyncio
    async def test_raises_when_open(self):
        cb = CircuitBreaker("test", failure_threshold=1, timeout=300)
        await cb.__aenter__()
        await cb.__aexit__(Exception, Exception("fail"), None)

        with pytest.raises(CircuitBreakerOpenError):
            await cb.__aenter__()
