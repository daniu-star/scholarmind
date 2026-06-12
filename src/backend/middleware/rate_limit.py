"""
ScholarMind 速率限制中间件
基于令牌桶算法，按 session_id 限流
"""
from __future__ import annotations

import time
import logging
from collections import defaultdict
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import settings

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """令牌桶速率限制中间件

    默认：每个 session_id 每分钟 60 次请求
    响应头：X-RateLimit-Remaining / X-RateLimit-Limit / X-RateLimit-Reset
    """

    def __init__(
        self,
        app,
        max_requests: int | None = None,
        window_seconds: int = 60,
    ):
        super().__init__(app)
        self.max_requests = max_requests or settings.RATE_LIMIT_REQUESTS
        self.window_seconds = window_seconds
        # {session_id: [timestamps]}
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def _clean_expired(self, session_id: str, now: float) -> None:
        """清理过期的时间戳"""
        if session_id in self._buckets:
            cutoff = now - self.window_seconds
            self._buckets[session_id] = [
                ts for ts in self._buckets[session_id] if ts > cutoff
            ]

    def _get_remaining(self, session_id: str) -> int:
        """获取剩余请求配额"""
        now = time.time()
        self._clean_expired(session_id, now)
        used = len(self._buckets.get(session_id, []))
        return max(0, self.max_requests - used)

    def _should_limit(self, session_id: str) -> bool:
        """检查是否应该限流"""
        if not settings.RATE_LIMIT_ENABLED:
            return False
        return self._get_remaining(session_id) <= 0

    async def dispatch(self, request: Request, call_next):
        # 从请求中提取 session_id
        session_id = self._extract_session_id(request)

        if session_id and self._should_limit(session_id):
            request_id = getattr(request.state, "request_id", None)
            wait_time = self.window_seconds

            logger.warning(
                "Rate limit exceeded",
                session_id=session_id,
                request_id=request_id,
            )

            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": f"请求速率超限，每分钟最多 {self.max_requests} 次请求",
                        "request_id": request_id,
                    }
                },
                headers={
                    "X-RateLimit-Limit": str(self.max_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time() + wait_time)),
                    "Retry-After": str(wait_time),
                },
            )

        response = await call_next(request)

        # 记录本次请求
        if session_id:
            now = time.time()
            self._buckets[session_id].append(now)
            remaining = self._get_remaining(session_id)
            response.headers["X-RateLimit-Limit"] = str(self.max_requests)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(
                int(now + self.window_seconds)
            )

        return response

    @staticmethod
    def _extract_session_id(request: Request) -> str | None:
        """从请求中提取 session_id"""
        # 优先从请求体 JSON 中提取
        # 次选从查询参数中提取
        # 最后从请求头中提取
        session_id = request.query_params.get("session_id")
        if session_id:
            return session_id
        session_id = request.headers.get("X-Session-ID")
        if session_id:
            return session_id
        # 回退到客户端 IP
        client = request.client
        if client:
            return client.host
        return "unknown"