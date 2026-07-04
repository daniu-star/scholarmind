"""
ScholarMind 速率限制中间件（内存版 fallback）

基于滑动窗口日志算法，按身份（user_id 优先 / 可信代理链 IP 次之）限流。

设计要点（P0 Task 6.5 修复）：
1. 有界 LRU + TTL：使用 OrderedDict，最大 10000 条目，LRU 淘汰 + 过期清理，
   防止攻击者用随机 X-Session-ID 撑爆内存。
2. asyncio.Lock：防止并发请求穿透（原实现先 call_next 后记录，存在竞态窗口）。
3. 请求开始前记录：先占额度再处理，杜绝“已写入但 429”的边界错误。
4. 空 key 删除：TTL 清理后若 key 无记录则删除，防内存增长。
5. 身份提取：优先 user_id（JWT），其次可信代理链 IP，不再接受客户端可控的
   X-Session-ID 作为安全身份（仅作附加维度）。
"""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import settings
from ..core.logging_config import get_logger

logger = get_logger(__name__)

# 有界缓存上限：防随机 session ID 攻击导致内存无限增长
_MAX_BUCKETS = 10_000


class RateLimitMiddleware(BaseHTTPMiddleware):
    """令牌桶/滑动窗口速率限制中间件（内存版，作为 Redis 不可用时的 fallback）

    默认：每个身份每分钟 max_requests 次请求
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
        # {identity: [timestamps]}，OrderedDict 维持 LRU 顺序
        self._buckets: OrderedDict[str, list[float]] = OrderedDict()
        # 并发锁：防止多请求同时检查+记录导致穿透
        self._lock = asyncio.Lock()

    # ── 身份解析 ──────────────────────────────────────────────

    @staticmethod
    def _extract_identity(request: Request) -> str:
        """提取限流身份

        优先级：
        1. request.state.user_id（若上游已注入）
        2. JWT Authorization: Bearer <token> 的 sub
        3. 可信代理链解析后的真实客户端 IP（X-Forwarded-For 最左，仅当直连客户端
           IP 属于受信任代理时才采用）
        4. 直连客户端 IP

        X-Session-ID 不再作为安全身份，仅可作为附加维度（由调用方拼接）。
        """
        # 1) 上游注入
        uid = getattr(request.state, "user_id", None)
        if uid:
            return f"u:{uid}"

        # 2) JWT 解析（仅验签取 sub，不做 DB 查询，保证限流轻量）
        uid = _extract_user_id_from_jwt(request)
        if uid:
            return f"u:{uid}"

        # 3) 可信代理链 IP
        client_ip = _extract_trusted_client_ip(request)
        if client_ip:
            return f"ip:{client_ip}"

        return "ip:unknown"

    # ── 桶操作（线程/协程安全） ────────────────────────────────

    def _clean_expired(self, identity: str, now: float) -> None:
        """清理过期时间戳；空桶则删除（防随机 session ID 撑爆内存）"""
        bucket = self._buckets.get(identity)
        if not bucket:
            # 仍要确保 LRU 顺序（若存在则 move 到末尾）
            self._buckets.pop(identity, None)
            return
        cutoff = now - self.window_seconds
        # 原地过滤，保留顺序
        fresh = [ts for ts in bucket if ts > cutoff]
        if fresh:
            self._buckets[identity] = fresh
        else:
            # 空 key 删除：防内存增长
            self._buckets.pop(identity, None)

    def _get_remaining(self, identity: str, now: float) -> int:
        self._clean_expired(identity, now)
        used = len(self._buckets.get(identity, []))
        return max(0, self.max_requests - used)

    def _consume(
        self, identity: str, now: float, limit: int | None = None
    ) -> tuple[bool, int, int]:
        """原子地检查并消费一个额度。

        Args:
            identity: 桶 key（含 path_class 隔离不同端点额度）
            now: 当前时间戳
            limit: 可选，覆盖 self.max_requests（用于 path 特定限额，避免修改实例属性）

        Returns:
            (allowed, remaining, retry_after_seconds)
        """
        # P1 Task 9：支持调用方传入 path 特定 limit，避免临时切换 self.max_requests
        # 导致并发场景下 self._fallback.max_requests 被互相覆盖（非线程安全）。
        effective_limit = limit if limit is not None else self.max_requests
        self._clean_expired(identity, now)
        bucket = self._buckets.get(identity, [])
        used = len(bucket)
        if used >= effective_limit:
            # 已满，不记录，更新 LRU 顺序
            self._buckets.move_to_end(identity)  # type: ignore[union-attr]
            remaining = 0
            # 计算最早记录的剩余等待时间
            oldest = bucket[0] if bucket else now
            retry_after = max(1, int(oldest + self.window_seconds - now) + 1)
            return False, remaining, retry_after
        # 占用额度（请求开始前记录）
        bucket.append(now)
        self._buckets[identity] = bucket
        self._buckets.move_to_end(identity)  # type: ignore[union-attr]
        # LRU 淘汰
        while len(self._buckets) > _MAX_BUCKETS:
            self._buckets.popitem(last=False)
        remaining = effective_limit - len(bucket)
        return True, remaining, 0

    # ── Task 25: 公开 acquire 方法，封装 _lock + _consume ──

    async def acquire(self, key: str, cost: int = 1) -> bool:
        """原子地检查并消费一个额度（公开接口，供 WebSocket/外部调用方使用）。

        封装内部 `_lock` + `_consume` 逻辑，避免外部直接访问私有属性。

        Args:
            key: 限流身份（如 "u:123" / "ip:1.2.3.4"）
            cost: 本次请求成本权重（当前实现按单次额度消费，cost 仅用于未来扩展）

        Returns:
            True 表示允许通过；False 表示已达限额。
        """
        async with self._lock:
            now = time.time()
            allowed, _remaining, _retry_after = self._consume(key, now)
        return allowed

    # ── 中间件入口 ────────────────────────────────────────────

    async def dispatch(self, request: Request, call_next):
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        identity = self._extract_identity(request)

        # 附加维度：X-Session-ID 仅作为分桶附加维度（不影响安全身份）
        # 这里不拼接，保持身份稳定；仅记录日志便于审计
        async with self._lock:
            now = time.time()
            allowed, remaining, retry_after = self._consume(identity, now)

        if not allowed:
            request_id = getattr(request.state, "request_id", None)
            logger.warning(
                f"rate_limit_exceeded identity={identity} "
                f"remaining={remaining} retry_after={retry_after} "
                f"request_id={request_id}"
            )
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": (
                            f"请求速率超限，每分钟最多 {self.max_requests} 次请求"
                        ),
                        "request_id": request_id,
                    },
                },
                headers={
                    "X-RateLimit-Limit": str(self.max_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time() + retry_after)),
                    "Retry-After": str(retry_after),
                },
            )

        # 正常处理请求（额度已在请求开始前消费）
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(
            int(time.time() + self.window_seconds)
        )
        return response


# ── 工具函数（与 redis_rate_limit 共用） ───────────────────────


def _extract_user_id_from_jwt(request: Request) -> Optional[str]:
    """从 Authorization: Bearer <token> 解析 user_id（仅验签取 sub，无 DB 查询）

    限流场景下无需完整鉴权（DB 查询太重），只要能稳定提取身份即可。
    JWT_SECRET_KEY 为空（开发环境未配置）时跳过，回退到 IP。
    """
    if not settings.JWT_SECRET_KEY:
        return None
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    try:
        import jwt  # PyJWT
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except Exception:
        return None
    # refresh token 不用于限流身份（与业务 API 一致：refresh 不能访问业务端点）
    if payload.get("type") == "refresh":
        return None
    sub = payload.get("sub")
    if sub is None:
        return None
    try:
        uid = int(sub)
    except (TypeError, ValueError):
        return None
    return str(uid) if uid > 0 else None


def _extract_trusted_client_ip(request: Request) -> Optional[str]:
    """提取可信客户端 IP

    仅当直连客户端 IP 属于 RATE_LIMIT_TRUSTED_PROXIES 时，才信任
    X-Forwarded-For 最左值作为真实客户端 IP；否则使用直连客户端 IP。
    """
    direct = request.client.host if request.client else None
    if direct is None:
        return None

    trusted = {
        p.strip().lower() for p in settings.RATE_LIMIT_TRUSTED_PROXIES.split(",")
        if p.strip()
    }
    if direct.lower() in trusted:
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            # 最左为原始客户端；剥空白与可能的端口
            left = xff.split(",")[0].strip()
            if left:
                return left
    return direct
