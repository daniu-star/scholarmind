"""
LLM Client 单元测试

覆盖：
- 正常 chat / stream_chat / chat_json 调用
- tenacity 重试机制（对可重试异常重试，对不可重试异常不重试）
- 熔断器集成（成功记录 / 失败记录 / 熔断打开时拒绝）
- 缺失 API Key 时抛 RuntimeError
- chat_json JSON 解析（含 markdown 代码块兜底）
"""
from __future__ import annotations

import time

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock

from openai import (
    APIConnectionError,
    RateLimitError,
    AuthenticationError,
)

from src.backend.utils.circuit_breaker import (
    CircuitBreakerOpenError,
    CircuitState,
    deepseek_circuit_breaker,
)
from src.backend.utils.llm_client import LLMClient, LLMResponse


# ── 辅助函数 ──────────────────────────────────────────────

def _make_request() -> httpx.Request:
    """构造一个 httpx.Request 用于异常构造"""
    return httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions")


def _make_response(status_code: int = 429) -> httpx.Response:
    """构造一个 httpx.Response 用于异常构造"""
    return httpx.Response(status_code=status_code, request=_make_request())


def _make_completion(content: str = "hello"):
    """构造一个模拟的 chat completion 响应"""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_circuit_breaker():
    """每个测试前后重置熔断器状态，避免测试间互相污染"""
    cb = deepseek_circuit_breaker
    cb._state = CircuitState.CLOSED
    cb._failure_count = 0
    cb._last_failure_time = 0
    cb._half_open_count = 0
    yield
    cb._state = CircuitState.CLOSED
    cb._failure_count = 0
    cb._last_failure_time = 0
    cb._half_open_count = 0


@pytest.fixture
def llm(monkeypatch):
    """创建一个新鲜的 LLMClient 实例（不走单例），并 mock 底层 OpenAI 客户端

    - monkeypatch DEEPSEEK_API_KEY / LLM_MAX_RETRIES / LLM_RETRY_INITIAL_DELAY
    - 预填 _client 跳过 _get_client() 中真实的 AsyncOpenAI 创建
    """
    monkeypatch.setattr("src.backend.config.settings.DEEPSEEK_API_KEY", "test-key-123")
    monkeypatch.setattr("src.backend.config.settings.DEEPSEEK_MODEL", "deepseek-chat")
    monkeypatch.setattr("src.backend.config.settings.LLM_MAX_RETRIES", 2)
    monkeypatch.setattr("src.backend.config.settings.LLM_RETRY_INITIAL_DELAY", 0.1)
    monkeypatch.setattr("src.backend.config.settings.LLM_TIMEOUT", 5)

    client = LLMClient()
    client._client = MagicMock()  # 跳过 _get_client()
    return client


# ── LLMResponse 基础测试 ─────────────────────────────────

def test_llm_response_str():
    """LLMResponse.__str__ 返回 content"""
    resp = LLMResponse(content="你好")
    assert str(resp) == "你好"
    assert resp.thought is None


def test_llm_response_with_thought():
    """LLMResponse 携带 thought 字段"""
    resp = LLMResponse(content="答案", thought="思考过程")
    assert resp.content == "答案"
    assert resp.thought == "思考过程"


# ── chat() 测试 ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_success(llm):
    """正常调用返回 LLMResponse"""
    llm._client.chat.completions.create = AsyncMock(
        return_value=_make_completion("你好世界")
    )

    resp = await llm.chat(system="sys", user="usr")

    assert isinstance(resp, LLMResponse)
    assert resp.content == "你好世界"


@pytest.mark.asyncio
async def test_chat_retries_on_connection_error(llm):
    """对 APIConnectionError 进行重试，最终成功"""
    llm._client.chat.completions.create = AsyncMock(
        side_effect=[
            APIConnectionError(request=_make_request()),
            APIConnectionError(request=_make_request()),
            _make_completion("重试后成功"),
        ]
    )

    resp = await llm.chat(system="sys", user="usr")

    assert resp.content == "重试后成功"
    assert llm._client.chat.completions.create.await_count == 3  # 2 重试 + 1 成功


@pytest.mark.asyncio
async def test_chat_retries_on_rate_limit(llm):
    """对 RateLimitError 进行重试"""
    llm._client.chat.completions.create = AsyncMock(
        side_effect=[
            RateLimitError(
                message="rate limited",
                response=_make_response(429),
                body=None,
            ),
            _make_completion("ok"),
        ]
    )

    resp = await llm.chat(system="sys", user="usr")

    assert resp.content == "ok"
    assert llm._client.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_chat_no_retry_on_auth_error(llm):
    """对 AuthenticationError 不进行重试，直接抛出"""
    llm._client.chat.completions.create = AsyncMock(
        side_effect=AuthenticationError(
            message="invalid api key",
            response=_make_response(401),
            body=None,
        )
    )

    with pytest.raises(AuthenticationError):
        await llm.chat(system="sys", user="usr")

    assert llm._client.chat.completions.create.await_count == 1  # 无重试


@pytest.mark.asyncio
async def test_chat_records_success_on_completion(llm):
    """成功完成后，熔断器 failure_count 保持 0"""
    llm._client.chat.completions.create = AsyncMock(
        return_value=_make_completion()
    )

    await llm.chat(system="sys", user="usr")

    assert deepseek_circuit_breaker._failure_count == 0


@pytest.mark.asyncio
async def test_chat_records_failure_on_exhausted_retries(llm):
    """可重试异常耗尽重试后，熔断器记录失败"""
    llm._client.chat.completions.create = AsyncMock(
        side_effect=APIConnectionError(request=_make_request())
    )

    with pytest.raises(APIConnectionError):
        await llm.chat(system="sys", user="usr")

    assert deepseek_circuit_breaker._failure_count >= 1


@pytest.mark.asyncio
async def test_chat_raises_when_circuit_open(llm):
    """熔断器打开时，chat 直接抛出 CircuitBreakerOpenError，不调用底层 API"""
    deepseek_circuit_breaker._state = CircuitState.OPEN
    deepseek_circuit_breaker._failure_count = 100
    deepseek_circuit_breaker._last_failure_time = time.time()  # 刚刚熔断，不会自动恢复

    llm._client.chat.completions.create = AsyncMock(return_value=_make_completion())

    with pytest.raises(CircuitBreakerOpenError):
        await llm.chat(system="sys", user="usr")

    llm._client.chat.completions.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_raises_without_api_key(monkeypatch):
    """未配置 API Key 时抛出 RuntimeError"""
    monkeypatch.setattr("src.backend.config.settings.DEEPSEEK_API_KEY", "")
    client = LLMClient()

    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        await client.chat(system="sys", user="usr")


# ── stream_chat() 测试 ────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_chat_yields_chunks(llm):
    """stream_chat 逐 chunk 产出文本"""
    async def mock_stream():
        for text in ["Hello", " ", "World"]:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = text
            yield chunk

    llm._client.chat.completions.create = AsyncMock(return_value=mock_stream())

    chunks = []
    async for text in llm.stream_chat(system="sys", user="usr"):
        chunks.append(text)

    assert "".join(chunks) == "Hello World"


@pytest.mark.asyncio
async def test_stream_chat_records_failure_on_error(llm):
    """流式调用遇到可重试异常时，熔断器记录失败"""
    llm._client.chat.completions.create = AsyncMock(
        side_effect=APIConnectionError(request=_make_request())
    )

    with pytest.raises(APIConnectionError):
        async for _ in llm.stream_chat(system="sys", user="usr"):
            pass

    assert deepseek_circuit_breaker._failure_count >= 1


# ── chat_json() 测试 ──────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_json_parses_valid_json(llm):
    """chat_json 正确解析合法 JSON"""
    llm._client.chat.completions.create = AsyncMock(
        return_value=_make_completion('{"key": "value", "num": 42}')
    )

    result = await llm.chat_json(system="sys", user="usr")

    assert result == {"key": "value", "num": 42}


@pytest.mark.asyncio
async def test_chat_json_extracts_from_markdown_code_block(llm):
    """chat_json 从 ```json ... ``` 代码块中提取 JSON"""
    content = '```json\n{"key": "value"}\n```'
    llm._client.chat.completions.create = AsyncMock(
        return_value=_make_completion(content)
    )

    result = await llm.chat_json(system="sys", user="usr")

    assert result == {"key": "value"}


@pytest.mark.asyncio
async def test_chat_json_raises_on_invalid_json(llm):
    """chat_json 在无法解析 JSON 时抛出 ValueError"""
    llm._client.chat.completions.create = AsyncMock(
        return_value=_make_completion("this is not json at all")
    )

    with pytest.raises(ValueError):
        await llm.chat_json(system="sys", user="usr")
