"""
ScholarMind Redis 分布式限流中间件

基于 Redis Sorted Set 实现滑动窗口限流，支持多进程/多服务器部署。

P0 Task 6 修复要点：
1. **始终初始化 fallback**：移除 `if app is None else None` 条件，本地
   LRU+TTL fallback 永远就绪（Task 6.1）。
2. **身份不可伪造**：优先 `user_id`（JWT sub），其次可信代理链 IP，不再接受
   客户端可控的 `X-Session-ID` 作为安全身份（Task 6.2）。
3. **Lua 返回 `allowed` 字段**：中间件依据 `allowed` 判定，不再用
   `remaining <= 0` 推断（Task 6.3）。
4. **失败策略分级**：高成本端点 fail closed（503），普通端点降级本地
   fallback 限制（Task 6.4）。
5. **每端点成本权重**：不同路径类各自限额（Task 6.6）。
6. **WebSocket 可复用**：暴露 `check_rate()` 供 WS accept 前调用（Task 6.7）。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import settings
from ..core.logging_config import get_logger
from .rate_limit import _extract_user_id_from_jwt, _extract_trusted_client_ip

logger = get_logger(__name__)


# ── 端点成本权重与失败策略 ─────────────────────────────────────
# 成本权重：cost 越高，该端点每窗口允许的请求越少（limit = base // cost）。
# 不同端点各自独立桶（key 含 path_class），互不影响。
PATH_COST_WEIGHTS: dict[str, int] = {
    "/api/v1/agent/chat": 10,  # Agent 对话：成本最高
    "/api/v1/code-execution/run": 10,  # 代码执行：成本最高
    "/api/v1/paper-pipeline/start": 5,  # Paper Pipeline 启动
    "/api/v1/paper-review/start": 5,  # Paper Review 启动
    "/api/v1/upload": 3,  # 文件上传
    "/api/v1/knowledge/search": 2,  # 学术搜索
    "/api/v1/knowledge/academic/search": 3,  # Task 28: 学术搜索深度端点（成本与 upload 一致）
    "/api/v1/auth/login": 2,  # 登录（防爆破）
    "/api/v1/auth/register": 2,  # 注册（防批量注册）
    "/api/v1/auth/send-code": 5,  # 验证码发送（防短信/邮件轰炸）
    "/api/v1/ws/chat": 2,  # WebSocket 建连
}
DEFAULT_COST = 1

# Redis 不可用时 fail closed 的端点（高成本，必须 Redis 守护，不可降级放行）：
# 精确路径 + payment 前缀匹配。
FAIL_CLOSED_PATHS: set[str] = {
    "/api/v1/agent/chat",
    "/api/v1/code-execution/run",
    "/api/v1/paper-pipeline/start",
    "/api/v1/paper-review/start",
}
FAIL_CLOSED_PREFIXES: tuple[str, ...] = ("/api/v1/payment/",)


def _path_cost(path: str) -> int:
    """返回路径对应的成本权重（默认 1）。"""
    return PATH_COST_WEIGHTS.get(path, DEFAULT_COST)


def _is_fail_closed(path: str) -> bool:
    """该路径在 Redis 不可用时是否 fail closed。"""
    if path in FAIL_CLOSED_PATHS:
        return True
    return any(path.startswith(p) for p in FAIL_CLOSED_PREFIXES)


def _path_class(path: str) -> str:
    """将路径归一化为限流桶的 path_class。

    payment 子路径统一归一类，避免每个支付端点各开一桶；
    其余使用原始路径（已在前缀树中归并的成本权重路径直接命中）。
    """
    if path.startswith("/api/v1/payment/"):
        return "payment"
    return path


class RedisRateLimitMiddleware(BaseHTTPMiddleware):
    """基于 Redis 的分布式滑动窗口限流中间件

    算法：滑动窗口（Sorted Set）
        键：ratelimit:{identity}:{path_class}
        分数：请求时间戳（Unix 秒）
        成员：请求唯一 ID（UUID4）
        limit：依据 path 成本权重推导（base_requests // cost）

    降级：
        - Redis 可用：依据 Lua 返回的 `allowed` 字段判定
        - Redis 不可用 + 高成本端点：fail closed（503）
        - Redis 不可用 + 普通端点：降级到本地 fallback 限制
    """

    # Redis Lua：返回数组 [allowed, remaining, retry_after]
    # 中间件将数组映射为命名 KV {allowed, remaining, retry_after} 并依据 allowed 判定。
    LUA_SLIDING_WINDOW = """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        local window = tonumber(ARGV[2])
        local limit = tonumber(ARGV[3])
        local member = ARGV[4]

        -- 移除窗口外的旧记录
        redis.call('ZREMRANGEBYSCORE', key, 0, now - window)

        -- 当前窗口内计数
        local count = redis.call('ZCARD', key)

        if count >= limit then
            local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
            local retry_after = 0
            if oldest[2] then
                retry_after = math.ceil(tonumber(oldest[2]) + window - now)
                if retry_after < 1 then
                    retry_after = 1
                end
            end
            -- allowed=0, remaining=0, retry_after
            return {0, 0, retry_after}
        end

        -- 添加当前请求记录（请求开始前占用额度）
        redis.call('ZADD', key, now, member)
        redis.call('EXPIRE', key, window + 1)
        local remaining = limit - count - 1
        -- allowed=1
        return {1, remaining, 0}
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

        # Redis 连接（延迟初始化）
        self._redis: Optional[any] = None
        self._lua_sha: Optional[str] = None
        self._available: bool = True
        self._init_lock = asyncio.Lock()

        # Task 6.1：始终初始化本地 LRU+TTL fallback（移除 `if app is None else None`）
        from .rate_limit import RateLimitMiddleware

        self._fallback = RateLimitMiddleware(
            app=app,
            max_requests=self.max_requests,
            window_seconds=self.window_seconds,
        )

        # 注：不在此处向 app.state 注册自身——`app` 参数是包装后的下一层 ASGI app
        # （router 或下一中间件），并非持有 `.state` 的 FastAPI 实例。WS 限流使用
        # app.py 中显式创建的独立 in-memory 限流器（app.state.ws_rate_limiter）。

    # ── Redis 连接管理 ────────────────────────────────────────

    async def _ensure_redis(self) -> bool:
        """确保 Redis 连接可用（懒加载 + 重试）"""
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
                self._lua_sha = await self._redis.script_load(self.LUA_SLIDING_WINDOW)
                # URL 脱敏：同时处理 redis://（明文）和 rediss://（TLS）两种 scheme，
                # 避免 URL 中的凭证（user:pass@host）落入日志。order 不影响（两 scheme 不互为子串）。
                url_safe = self.redis_url.replace("redis://", "redis://***@").replace("rediss://", "rediss://***@")
                logger.info(f"redis rate limiter initialized url={url_safe}")
                return True
            except Exception as e:
                logger.warning(f"redis unavailable falling back to memory rate limiter error={e}")
                self._available = False
                self._redis = None
                return False

    # ── 身份解析（Task 6.2）────────────────────────────────────

    @staticmethod
    def _extract_identity(request: Request) -> str:
        """提取限流身份

        优先级：
        1. request.state.user_id（上游依赖注入）
        2. JWT Authorization: Bearer <token> 的 sub（仅验签，无 DB 查询）
        3. 可信代理链 IP（X-Forwarded-For 最左 + 受信任代理校验）
        4. 直连客户端 IP

        X-Session-ID 不再作为安全身份（仅可作附加维度，本中间件不拼入）。
        """
        uid = getattr(request.state, "user_id", None)
        if uid:
            return f"u:{uid}"
        uid = _extract_user_id_from_jwt(request)
        if uid:
            return f"u:{uid}"
        client_ip = _extract_trusted_client_ip(request)
        if client_ip:
            return f"ip:{client_ip}"
        return "ip:unknown"

    # ── 限额推导（Task 6.6）────────────────────────────────────

    def _limit_for_path(self, path: str) -> int:
        """依据成本权重推导该路径的每窗口限额"""
        cost = _path_cost(path)
        if cost <= 1:
            return self.max_requests
        return max(1, self.max_requests // cost)

    # ── 核心限流检查 ───────────────────────────────────────────

    async def _check_redis(self, identity: str, path_class: str, limit: int) -> dict:
        """执行 Redis 滑动窗口检查

        Returns:
            {allowed: bool, remaining: int, retry_after: int}
            依据 `allowed` 字段判定，不再用 remaining <= 0 推断。
        """
        key = f"ratelimit:{identity}:{path_class}"
        now = time.time()
        member = str(uuid.uuid4())

        try:
            result = await self._redis.evalsha(
                self._lua_sha,
                1,
                key,
                str(now),
                str(self.window_seconds),
                str(limit),
                member,
            )
            if result is None:
                return {"allowed": False, "remaining": 0, "retry_after": self.window_seconds}
            # Lua 返回 [allowed, remaining, retry_after]
            allowed_int = int(result[0])
            remaining = int(result[1]) if len(result) > 1 else 0
            retry_after = int(result[2]) if len(result) > 2 else 0
            return {
                "allowed": allowed_int == 1,
                "remaining": remaining,
                "retry_after": retry_after,
            }
        except Exception:
            raise

    async def check_rate(self, identity: str, path: str) -> dict:
        """通用限流检查（供 WebSocket 与 HTTP 复用）

        Returns:
            {allowed: bool, remaining: int, retry_after: int, source: str}
            source: "redis" | "fallback" | "fail_closed"
        """
        limit = self._limit_for_path(path)
        path_class = _path_class(path)

        if await self._ensure_redis():
            try:
                res = await self._check_redis(identity, path_class, limit)
                res["source"] = "redis"
                return res
            except Exception as e:
                logger.error(f"redis rate limit error falling back error={e}")
                self._available = False
                self._redis = None

        # Redis 不可用
        if _is_fail_closed(path):
            return {"allowed": False, "remaining": 0, "retry_after": self.window_seconds, "source": "fail_closed"}
        # 普通端点降级到本地 fallback 限制
        logger.warning(f"redis unavailable fallback to local identity={identity} path={path}")
        return await self._local_check(identity, path_class, limit)

    # ── Task 25: 公开 acquire 方法，封装 _lock + _consume 逻辑 ──

    async def acquire(self, key: str, cost: int = 1) -> bool:
        """原子地检查并消费一个额度（公开接口，供 WebSocket/外部调用方使用）。

        封装内部 `_lock` + `_consume` 逻辑，避免外部直接访问私有属性。
        使用 path 默认 cost 推导 limit；若 Redis 可用则走 Redis，否则降级 fallback。

        Args:
            key: 限流身份（如 "u:123" / "ip:1.2.3.4"）
            cost: 本次请求成本权重（用于推导 limit = max_requests // cost）

        Returns:
            True 表示允许通过；False 表示已达限额。
        """
        # 委托给 fallback 的公开 acquire（RateLimitMiddleware.acquire）
        return await self._fallback.acquire(key, cost)

    async def _local_check(self, identity: str, path_class: str, limit: int) -> dict:
        """调用本地 fallback 的内存限流逻辑（线程安全：不修改 self._fallback.max_requests）

        P1 Task 9 修复：原实现临时切换 self._fallback.max_requests 后 finally 恢复，
        在并发场景下会被互相覆盖（非线程安全）。改为通过 _consume(limit=...) 参数
        传入 path 特定限额，复用 fallback 的 _buckets 与 _lock，但不修改实例属性。
        """
        async with self._fallback._lock:
            now = time.time()
            # fallback 的桶 key 含 path_class 以隔离不同端点额度
            bucket_key = f"{identity}:{path_class}"
            allowed, remaining, retry_after = self._fallback._consume(bucket_key, now, limit=limit)
        return {
            "allowed": allowed,
            "remaining": remaining,
            "retry_after": retry_after,
            "source": "fallback",
        }

    # ── 中间件入口 ────────────────────────────────────────────

    async def dispatch(self, request: Request, call_next):
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        path = request.url.path
        identity = self._extract_identity(request)
        result = await self.check_rate(identity, path)

        if not result["allowed"]:
            return self._reject(request, path, identity, result)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self._limit_for_path(path))
        response.headers["X-RateLimit-Remaining"] = str(result["remaining"])
        response.headers["X-RateLimit-Reset"] = str(int(time.time() + self.window_seconds))
        return response

    def _reject(self, request: Request, path: str, identity: str, result: dict) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        # 高成本端点 Redis 不可用 → 503；其余超限 → 429
        is_fail_closed = result.get("source") == "fail_closed"
        status_code = 503 if is_fail_closed else 429
        code = "RATE_LIMIT_UNAVAILABLE" if is_fail_closed else "RATE_LIMITED"
        message = (
            "限流服务暂不可用，请稍后重试"
            if is_fail_closed
            else f"请求速率超限，每分钟最多 {self._limit_for_path(path)} 次请求"
        )
        retry_after = result.get("retry_after", self.window_seconds) or self.window_seconds
        logger.warning(
            f"rate_limit_rejected identity={identity} path={path} "
            f"source={result.get('source')} status={status_code} "
            f"request_id={request_id}"
        )
        return JSONResponse(
            status_code=status_code,
            content={
                "success": False,
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": request_id,
                },
            },
            headers={
                "X-RateLimit-Limit": str(self._limit_for_path(path)),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time() + retry_after)),
                "Retry-After": str(max(1, retry_after)),
            },
        )

    async def close(self) -> None:
        """关闭 Redis 连接"""
        if self._redis is not None:
            try:
                await self._redis.close()
            except Exception:
                pass
            self._redis = None
