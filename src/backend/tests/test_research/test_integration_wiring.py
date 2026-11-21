"""R0 集成层回归：研究域统一错误外壳 + 请求体上限真实生效（FR-03 / FR-15）。

这两个行为都曾"看起来实现了但实际没有"：
1. `FastAPI(request_body_max_size=...)` 不是合法参数，被静默忽略 → 22MiB 上限失效；
2. 研究域鉴权失败走全局 HTTPException 处理器，错误外壳是 `{"success": false}`，
   与研究域约定的 `{"error": {code, ...}}` 不一致。
"""

from __future__ import annotations


import httpx
import pytest

from src.backend.app import create_app
from src.backend.config import settings

RESEARCH_PREFIX = "/api/v1/research"


@pytest.fixture()
def bare_client() -> httpx.AsyncClient:
    """无鉴权客户端：不需要数据库，只验证协议层行为。"""
    app = create_app()
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )


def _error_of(response: httpx.Response) -> dict:
    payload = response.json()
    assert "error" in payload, payload
    return payload["error"]


@pytest.mark.asyncio
async def test_research_auth_error_uses_unified_envelope(bare_client: httpx.AsyncClient) -> None:
    async with bare_client as client:
        response = await client.post(
            f"{RESEARCH_PREFIX}/tasks", json={"kind": "full_text_review"}
        )
    assert response.status_code == 401
    error = _error_of(response)
    assert error["code"] == "AUTHENTICATION_FAILED"
    assert error["retryable"] is False
    assert error.get("request_id"), "研究域错误体必须带 request_id（PRD §8.2）"
    # 旧前端外壳不应出现在研究域
    assert "success" not in response.json()


@pytest.mark.asyncio
async def test_research_body_limit_rejects_oversized_request(bare_client: httpx.AsyncClient) -> None:
    max_bytes = settings.RESEARCH_MAX_MULTIPART_BYTES
    oversized = b"a" * (max_bytes + 1024)
    async with bare_client as client:
        response = await client.post(
            f"{RESEARCH_PREFIX}/tasks",
            content=oversized,
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 413
    error = _error_of(response)
    assert error["code"] == "FILE_TOO_LARGE"
    assert error["details"]["max_request_bytes"] == max_bytes
    assert error["request_id"]


@pytest.mark.asyncio
async def test_non_research_endpoints_keep_previous_limit_behavior(
    bare_client: httpx.AsyncClient,
) -> None:
    """非研究域端点不受新中间件影响：大 body 依然进入业务鉴权流程（401 而非 413）。"""
    max_bytes = settings.RESEARCH_MAX_MULTIPART_BYTES
    oversized = b"a" * (max_bytes + 1024)
    async with bare_client as client:
        response = await client.post(
            "/api/v1/agent/chat",
            content=oversized,
            headers={"content-type": "application/json"},
        )
    assert response.status_code != 413
    assert response.status_code in {401, 422}
