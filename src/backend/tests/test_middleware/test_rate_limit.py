"""
P0 Task 6.8 — Redis 限流降级与身份伪造回归测试

覆盖：
1. 随机 X-Session-ID 不增额度（身份=user_id/IP，与 X-Session-ID 无关）
2. Redis 断开：高成本端点 fail closed（503）/ 普通端点本地 fallback 限流
3. 第 N 次成功（200），第 N+1 次返回 429（无“已写入但 429”边界错误）
4. 100 并发不突破 limit（asyncio.Lock 防穿透）
5. 中间件依据 Lua 返回的 `allowed` 字段判定（不再用 remaining<=0 推断）
6. 不同端点成本权重生效（高成本端点限额更低）
"""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.backend.config import settings
from src.backend.middleware.rate_limit import RateLimitMiddleware
from src.backend.middleware.redis_rate_limit import RedisRateLimitMiddleware


# ── 测试用 app 工厂 ──────────────────────────────────────────


def _make_memory_app(max_requests: int = 5, window_seconds: int = 60) -> FastAPI:
    """内存令牌桶限流 app（直接用 RateLimitMiddleware，绕过 Redis）"""
    app = FastAPI()

    @app.get("/api/v1/health")
    async def health():
        return {"ok": True}

    @app.get("/api/v1/agent/chat")
    async def agent_chat():
        return {"ok": True}

    app.add_middleware(
        RateLimitMiddleware,
        max_requests=max_requests,
        window_seconds=window_seconds,
    )
    return app


def _make_redis_app(
    max_requests: int = 60,
    redis_url: str = "redis://127.0.0.1:1/0",  # 端口 1 必连不上
) -> FastAPI:
    """Redis 限流 app（Redis 不可用，走 fallback / fail-closed）"""
    app = FastAPI()

    @app.get("/api/v1/health")
    async def health():
        return {"ok": True}

    @app.post("/api/v1/agent/chat")
    async def agent_chat():
        return {"ok": True}

    @app.post("/api/v1/code-execution/run")
    async def code_run():
        return {"ok": True}

    @app.post("/api/v1/payment/notify")
    async def payment_notify():
        return {"ok": True}

    @app.get("/api/v1/paper-pipeline/start")
    async def paper_pipeline_start():
        return {"ok": True}

    app.add_middleware(
        RedisRateLimitMiddleware,
        redis_url=redis_url,
        max_requests=max_requests,
        window_seconds=60,
    )
    return app


# ── 夹具 ────────────────────────────────────────────────────


@pytest.fixture
def enable_rate_limit(monkeypatch):
    """临时开启限流（conftest 默认关闭以避免影响其他测试）"""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    yield


@pytest_asyncio.fixture
async def mem_client(enable_rate_limit):
    """内存限流客户端，限额 5 次/60s"""
    app = _make_memory_app(max_requests=5, window_seconds=60)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def redis_down_client(enable_rate_limit, monkeypatch):
    """Redis 不可用客户端（monkeypatch _ensure_redis 返回 False，免去 2s 超时）"""
    app = _make_redis_app(max_requests=60)

    async def _false(self):  # noqa: ANN001
        return False

    monkeypatch.setattr(RedisRateLimitMiddleware, "_ensure_redis", _false)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ── 测试 1：随机 X-Session-ID 不增额度 ─────────────────────────


@pytest.mark.asyncio
async def test_random_session_id_does_not_increase_quota(mem_client):
    """攻击者每次请求生成新的 X-Session-ID，可用额度不应增加。

    身份 = 客户端 IP（X-Session-ID 不再作为安全身份）。
    """
    # 5 次请求，每次用不同的随机 X-Session-ID —— 都应成功（限额 5）
    for i in range(5):
        r = await mem_client.get(
            "/api/v1/health",
            headers={"X-Session-ID": f"random-session-{i}"},
        )
        assert r.status_code == 200, f"request {i} expected 200 got {r.status_code}"

    # 第 6 次，换一个全新的随机 X-Session-ID —— 仍应被限流（429）
    r = await mem_client.get(
        "/api/v1/health",
        headers={"X-Session-ID": "random-session-999-fresh"},
    )
    assert r.status_code == 429, f"expected 429 got {r.status_code} body={r.text}"


# ── 测试 2：Redis 断开分级降级 ────────────────────────────────


@pytest.mark.asyncio
async def test_redis_down_high_cost_endpoint_fail_closed(redis_down_client):
    """Redis 断开时高成本端点 fail closed（503）"""
    # agent/chat 是 fail-closed 路径
    r = await redis_down_client.post("/api/v1/agent/chat")
    assert r.status_code == 503, f"expected 503 got {r.status_code} body={r.text}"
    assert r.json()["error"]["code"] == "RATE_LIMIT_UNAVAILABLE"


@pytest.mark.asyncio
async def test_redis_down_code_execution_fail_closed(redis_down_client):
    r = await redis_down_client.post("/api/v1/code-execution/run")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_redis_down_payment_fail_closed(redis_down_client):
    r = await redis_down_client.post("/api/v1/payment/notify")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_redis_down_paper_pipeline_fail_closed(redis_down_client):
    r = await redis_down_client.get("/api/v1/paper-pipeline/start")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_redis_down_normal_endpoint_uses_local_fallback(redis_down_client):
    """Redis 断开时普通端点降级到本地 fallback 限制（不直接放行）"""
    # /api/v1/health 是普通端点，limit = base // 1 = 60
    # 先连续打 60 次应成功，第 61 次 429
    for i in range(60):
        r = await redis_down_client.get("/api/v1/health")
        assert r.status_code == 200, (
            f"normal request {i} expected 200 got {r.status_code} body={r.text}"
        )
    r = await redis_down_client.get("/api/v1/health")
    assert r.status_code == 429, (
        f"expected 429 after exceeding local fallback got {r.status_code}"
    )


# ── 测试 3：第 N 次成功，第 N+1 次 429 ────────────────────────


@pytest.mark.asyncio
async def test_nth_success_n_plus_1_returns_429(enable_rate_limit):
    """配额 N 次/窗口：前 N 次 200，第 N+1 次 429，且无“已写入但 429”边界错误"""
    app = _make_memory_app(max_requests=3, window_seconds=60)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for i in range(3):
            r = await client.get("/api/v1/health")
            assert r.status_code == 200, (
                f"request {i+1}/3 expected 200 got {r.status_code}"
            )
        # 第 4 次（N+1）应 429
        r = await client.get("/api/v1/health")
        assert r.status_code == 429, f"expected 429 got {r.status_code} body={r.text}"
        # 响应头含限流信息
        assert r.headers.get("X-RateLimit-Limit") == "3"
        assert r.headers.get("Retry-After") is not None


# ── 测试 4：100 并发不突破 limit ──────────────────────────────


@pytest.mark.asyncio
async def test_100_concurrent_does_not_break_limit(enable_rate_limit):
    """100 并发请求：仅 limit 个成功，其余 429（asyncio.Lock 防穿透）"""
    limit = 5
    app = _make_memory_app(max_requests=limit, window_seconds=60)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:

        async def one():
            r = await client.get("/api/v1/health")
            return r.status_code

        statuses = await asyncio.gather(*[one() for _ in range(100)])

    ok_count = sum(1 for s in statuses if s == 200)
    limited_count = sum(1 for s in statuses if s == 429)
    assert ok_count == limit, (
        f"expected exactly {limit} successes got {ok_count} (statuses={statuses[:10]}...)"
    )
    assert limited_count == 100 - limit, (
        f"expected {100 - limit} limited got {limited_count}"
    )
    # 不应有 5xx 或其他异常状态
    assert ok_count + limited_count == 100


# ── 测试 5：依据 allowed 字段判定（不再用 remaining<=0 推断）────


@pytest.mark.asyncio
async def test_allowed_field_determines_outcome(enable_rate_limit, monkeypatch):
    """中间件依据 Lua 返回的 `allowed` 字段判定，不再用 remaining<=0 推断。

    场景：mock _check_redis 返回 allowed=True 但 remaining=0 —— 仍应放行（200）。
    场景：mock 返回 allowed=False 但 remaining>0 —— 仍应限流（429）。
    """
    app = _make_redis_app(max_requests=60)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:

        # 场景 A：allowed=True, remaining=0 —— 应放行
        async def _allowed_true(self, identity, path_class, limit):  # noqa: ANN001
            return {"allowed": True, "remaining": 0, "retry_after": 0}

        async def _ensure_true(self):  # noqa: ANN001
            return True

        monkeypatch.setattr(RedisRateLimitMiddleware, "_ensure_redis", _ensure_true)
        monkeypatch.setattr(RedisRateLimitMiddleware, "_check_redis", _allowed_true)
        r = await client.get("/api/v1/health")
        assert r.status_code == 200, (
            f"allowed=True remaining=0 should pass got {r.status_code} body={r.text}"
        )

        # 场景 B：allowed=False, remaining=99 —— 应限流
        async def _allowed_false(self, identity, path_class, limit):  # noqa: ANN001
            return {"allowed": False, "remaining": 99, "retry_after": 30}

        monkeypatch.setattr(RedisRateLimitMiddleware, "_check_redis", _allowed_false)
        r = await client.get("/api/v1/health")
        assert r.status_code == 429, (
            f"allowed=False remaining=99 should be limited got {r.status_code}"
        )


# ── 测试 6：不同端点成本权重生效 ─────────────────────────────


def test_high_cost_path_has_lower_limit(enable_rate_limit):
    """高成本端点（agent/chat, cost=10）限额 = base//10，远低于普通端点"""
    from src.backend.middleware.redis_rate_limit import (
        _path_cost,
        _is_fail_closed,
        _path_class,
        PATH_COST_WEIGHTS,
        FAIL_CLOSED_PATHS,
        FAIL_CLOSED_PREFIXES,
    )

    # 模块级常量与函数
    assert _path_cost("/api/v1/agent/chat") == 10
    assert _path_cost("/api/v1/code-execution/run") == 10
    assert _path_cost("/api/v1/paper-pipeline/start") == 5
    assert _path_cost("/api/v1/health") == 1  # 默认
    assert _is_fail_closed("/api/v1/agent/chat") is True
    assert _is_fail_closed("/api/v1/code-execution/run") is True
    assert _is_fail_closed("/api/v1/paper-pipeline/start") is True
    assert _is_fail_closed("/api/v1/payment/notify") is True
    assert _is_fail_closed("/api/v1/payment/wechat/notify") is True
    assert _is_fail_closed("/api/v1/health") is False
    assert _path_class("/api/v1/payment/notify") == "payment"
    assert _path_class("/api/v1/health") == "/api/v1/health"

    # 实例级 _limit_for_path：直接构造实例（不注册为中间件）
    rl = RedisRateLimitMiddleware(app=FastAPI(), max_requests=60, window_seconds=60)
    assert rl._limit_for_path("/api/v1/agent/chat") == 6
    assert rl._limit_for_path("/api/v1/code-execution/run") == 6
    assert rl._limit_for_path("/api/v1/paper-pipeline/start") == 12
    assert rl._limit_for_path("/api/v1/health") == 60
    assert rl._limit_for_path("/api/v1/auth/login") == 30  # cost=2


# ── 测试 7：Lua 返回结构验证 ──────────────────────────────────


@pytest.mark.asyncio
async def test_lua_returns_allowed_structure(enable_rate_limit):
    """验证 _check_redis 返回的 dict 含 allowed/remaining/retry_after 三键"""
    rl = RedisRateLimitMiddleware(app=FastAPI(), max_requests=60, window_seconds=60)

    # mock 一个伪造的 redis.evalsha 返回 [1, 5, 0]（allowed, remaining, retry_after）
    class _FakeRedis:
        async def evalsha(self, sha, numkeys, key, now, window, limit, member):  # noqa: ANN001
            return [1, 5, 0]

    rl._redis = _FakeRedis()
    rl._lua_sha = "fake-sha"
    rl._available = True

    result = await rl._check_redis("u:1", "agent/chat", 6)
    assert result["allowed"] is True
    assert result["remaining"] == 5
    assert result["retry_after"] == 0

    # 再测 allowed=0 的情形
    class _FakeRedisDenied:
        async def evalsha(self, sha, numkeys, key, now, window, limit, member):  # noqa: ANN001
            return [0, 0, 30]

    rl._redis = _FakeRedisDenied()
    result = await rl._check_redis("u:1", "agent/chat", 6)
    assert result["allowed"] is False
    assert result["remaining"] == 0
    assert result["retry_after"] == 30


# ── 测试 8：fallback 始终初始化（Task 6.1）──────────────────


def test_fallback_always_initialized(enable_rate_limit):
    """RedisRateLimitMiddleware 无论 app 是否为 None 都应初始化 fallback"""
    from src.backend.middleware.rate_limit import RateLimitMiddleware

    rl = RedisRateLimitMiddleware(
        app=FastAPI(), max_requests=60, window_seconds=60
    )
    assert rl._fallback is not None
    assert isinstance(rl._fallback, RateLimitMiddleware)
    assert rl._fallback.max_requests == 60
