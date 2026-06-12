"""
ScholarMind Redis分布式限流中间件
基于Redis Sorted Set实现滑动窗口限流，支持多进程/多服务器部署。

降级策略：Redis不可用时自动回退到内存令牌桶（rate_limit.py）
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import settings

logger = logging.getLogger(__name__)


class RedisRateLimitMiddleware(BaseHTTPMiddleware):
    """基于Redis的分布式滑动窗口限流中间件

    算法：滑动窗口（Sorted Set）
    键：ratelimit:{session_id}
    分数：请求时间戳（Unix秒）
    成员：请求唯一ID（UUID4）

    降级：Redis不可用时自动回退到内存令牌桶（RateLimitMiddleware）

    响应头：
        X-RateLimit-Limit: 最大请求数
        X-RateLimit-Remaining: 剩余请求数
        X-RateLimit-Reset: 重置时间（Unix秒）
        Retry-After: 建议重试等待秒数
    """

    # Redis命令
    LUA_SLIDING_WINDOW = """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        local window = tonumber(ARGV[2])
        local limit = tonumber(ARGV[3])
        local member = ARGV[4]

        -- 移除窗口外的旧记录
        redis.call('ZREMRANGEBYSCORE', key, 0, now - window)

        -- 获取当前窗口内计数
        local count = redis.call('ZCARD', key)

        if count >= limit then
            -- 获取最早的记录时间计算等待时间
            local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
            local wait = 0
            if oldest[2] then
                wait = math.ceil(tonumber(oldest[2]) + window - now)
            end
            return {0, wait}
        end

        -- 添加当前请求记录
        redis.call('ZADD', key, now, member)
        redis.call('EXPIRE', key, window + 1)
        return {limit - count - 1, 0}
    """

    def __init__(
        self,
        app,
        redis_url: str | None = None,
        max_requests: int | None = None,
        window_seconds: int = 60,
    ):
        super().__init__(app)
        self.max_requests = max_requests or settings.RATE_LIMIT_REQUESTS
        self.window_seconds = window_seconds
        self.redis_url = redis_url or settings.REDIS_URL

        # Redis连接（延迟初始化）
        self._redis: Optional[any] = None
        self._lua_sha: Optional[str] = None
        self._available: bool = True
        self._init_lock = asyncio.Lock()

        # 降级：内存令牌桶
        from .rate_limit import RateLimitMiddleware
        self._fallback = RateLimitMiddleware(
            app=None,
            max_requests=self.max_requests,
            window_seconds=self.window_seconds,
        ) if app is None else None

    async def _ensure_redis(self) -> bool:
        """确保Redis连接可用（懒加载 + 重试）"""
        if self._redis is not None:
            return True

        if not self._available:
            return False

        async with self._init_lock:
            if self._redis is not None:
                return True

            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(
                    self.redis_url,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    decode_responses=True,
                )
                await self._redis.ping()

                # 预加载Lua脚本
                self._lua_sha = await self._redis.script_load(
                    self.LUA_SLIDING_WINDOW
                )

                logger.info(
                    "Redis rate limiter initialized",
                    url=self.redis_url.replace("redis://", "redis://***@"),
                )
                return True

            except Exception as e:
                logger.warning(
                    f"Redis unavailable, falling back to memory rate limiter: {e}"
                )
                self._available = False
                self._redis = None
                return False

    def _extract_session_id(self, request: Request) -> str:
        """从请求中提取 session_id"""
        # 优先查询参数
        session_id = request.query_params.get("session_id")
        if session_id:
            return session_id

        # 次选请求头
        session_id = request.headers.get("X-Session-ID")
        if session_id:
            return session_id

        # 回退到客户端IP
        client = request.client
        if client:
            return f"ip:{client.host}"

        return "unknown"

    async def dispatch(self, request: Request, call_next):
        # 如果限流未启用，直接放行
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        session_id = self._extract_session_id(request)

        # 尝试Redis限流
        if await self._ensure_redis():
            try:
                is_limited, wait_time = await self._check_redis(session_id)

                if is_limited:
                    request_id = getattr(request.state, "request_id", None)
                    logger.warning(
                        "Redis rate limit exceeded",
                        session_id=session_id,
                        request_id=request_id,
                    )
                    return JSONResponse(
                        status_code=429,
                        content={
                            "success": False,
                            "error": {
                                "code": "RATE_LIMITED",
                                "message": f"请求速率超限，每分钟最多 {self.max_requests} 次请求",
                                "request_id": request_id,
                            },
                        },
                        headers={
                            "X-RateLimit-Limit": str(self.max_requests),
                            "X-RateLimit-Remaining": "0",
                            "X-RateLimit-Reset": str(int(time.time() + wait_time)),
                            "Retry-After": str(max(1, wait_time)),
                        },
                    )

                # 正常处理请求
                response = await call_next(request)
                response.headers["X-RateLimit-Limit"] = str(self.max_requests)
                response.headers["X-RateLimit-Remaining"] = str(is_limited)
                response.headers["X-RateLimit-Reset"] = str(
                    int(time.time() + self.window_seconds)
                )
                return response

            except Exception as e:
                logger.error(f"Redis rate limit error, falling back: {e}")
                self._available = False
                self._redis = None

        # 降级：使用内存令牌桶
        if self._fallback is not None:
            return await self._fallback.dispatch(request, call_next)

        return await call_next(request)

    async def _check_redis(self, session_id: str) -> tuple[int, int]:
        """执行Redis滑动窗口检查

        Returns:
            (remaining, wait_seconds):
                remaining > 0 → 剩余请求数，请求通过
                remaining == 0 → 被限流，wait_seconds为建议等待秒数
        """
        key = f"ratelimit:{session_id}"
        now = time.time()
        member = str(uuid.uuid4())

        try:
            result = await self._redis.evalsha(
                self._lua_sha,
                1,
                key,
                str(now),
                str(self.window_seconds),
                str(self.max_requests),
                member,
            )

            if result is None:
                return 0, self.window_seconds

            remaining = int(result[0])
            wait = int(result[1]) if len(result) > 1 else 0

            if remaining <= 0:
                return 0, wait
            return remaining, 0

        except Exception:
            raise

    async def close(self) -> None:
        """关闭Redis连接"""
        if self._redis is not None:
            try:
                await self._redis.close()
            except Exception:
                pass
            self._redis = None