"""LLM 上下文压缩代理（billion-context / ACP）接线的无网络单测。

只验证三件事：
1. 未配置 ``LLM_PROXY_BASE_URL`` 时行为与历史完全一致（直连、无额外头）；
2. 配置后客户端 base_url 指向代理、超时被抬高、请求带上会话头；
3. 会话头取自 ``LLM_PROXY_SESSION_HEADER``，且没有会话键时不发头。

不联网、不启动代理，也不校验代理自身的压缩行为（那属于代理侧能力，
见 docs/reports/BILLION_CONTEXT.md 的实测记录与 scripts/bili_payload_probe.py）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ..utils import llm_client
from ..utils.llm_client import LLMClient, proxy_base_url, proxy_session_headers


@pytest.fixture(autouse=True)
def _reset_client_singleton(monkeypatch):
    """每个用例前后清掉单例，避免 base_url 缓存污染。"""
    monkeypatch.setattr(LLMClient, "_instance", None, raising=False)
    monkeypatch.setattr(LLMClient, "_client", None, raising=False)
    monkeypatch.setattr(llm_client.settings, "LLM_PROXY_BASE_URL", None, raising=False)
    yield
    monkeypatch.setattr(LLMClient, "_instance", None, raising=False)
    monkeypatch.setattr(LLMClient, "_client", None, raising=False)


class _RecordingCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])


def _fake_client(completions: _RecordingCompletions) -> SimpleNamespace:
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def test_proxy_disabled_by_default():
    assert proxy_base_url() is None
    assert proxy_session_headers("chat:1:abc") is None


def test_proxy_base_url_is_stripped_and_blank_is_none(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "LLM_PROXY_BASE_URL", "  http://127.0.0.1:8790/bili/x  ", raising=False)
    assert proxy_base_url() == "http://127.0.0.1:8790/bili/x"

    monkeypatch.setattr(llm_client.settings, "LLM_PROXY_BASE_URL", "   ", raising=False)
    assert proxy_base_url() is None


def test_session_headers_use_configured_header(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "LLM_PROXY_BASE_URL", "http://127.0.0.1:8790/bili/x", raising=False)
    assert proxy_session_headers("research:rtask_1") == {"x-acp-session": "research:rtask_1"}

    monkeypatch.setattr(llm_client.settings, "LLM_PROXY_SESSION_HEADER", "x-session-custom", raising=False)
    assert proxy_session_headers("research:rtask_1") == {"x-session-custom": "research:rtask_1"}

    # 启用代理但没有会话键：不发头，仍然直连代理
    assert proxy_session_headers(None) is None


def test_client_base_url_switches_to_proxy_and_raises_timeout(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "DEEPSEEK_API_KEY", "sk-test", raising=False)
    direct = LLMClient()._get_client()
    assert "api.deepseek.com" in str(direct.base_url) or str(direct.base_url).startswith("https://")

    monkeypatch.setattr(LLMClient, "_client", None, raising=False)
    monkeypatch.setattr(llm_client.settings, "LLM_PROXY_BASE_URL", "http://127.0.0.1:8790/bili/https://api.deepseek.com/v1", raising=False)
    monkeypatch.setattr(llm_client.settings, "LLM_PROXY_TIMEOUT_SECONDS", 180.0, raising=False)
    proxied = LLMClient()._get_client()

    assert str(proxied.base_url).startswith("http://127.0.0.1:8790/bili/")
    assert proxied.timeout.read >= 180.0 - 1e-6


@pytest.mark.asyncio
async def test_chat_sends_session_header_only_when_proxy_enabled(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "DEEPSEEK_API_KEY", "sk-test", raising=False)

    # 未启用代理：不带 extra_headers
    completions = _RecordingCompletions()
    monkeypatch.setattr(LLMClient, "_get_client", lambda self: _fake_client(completions))
    await LLMClient().chat("sys", "user", session_key="research:rtask_1")
    assert "extra_headers" not in completions.calls[0]

    # 启用代理：带会话头，且不覆盖调用方传入的其它参数
    monkeypatch.setattr(llm_client.settings, "LLM_PROXY_BASE_URL", "http://127.0.0.1:8790/bili/x", raising=False)
    completions2 = _RecordingCompletions()
    monkeypatch.setattr(LLMClient, "_get_client", lambda self: _fake_client(completions2))
    await LLMClient().chat("sys", "user", session_key="research:rtask_2", extra_body={"thinking": {"type": "disabled"}})
    kwargs = completions2.calls[0]
    assert kwargs["extra_headers"] == {"x-acp-session": "research:rtask_2"}
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


@pytest.mark.asyncio
async def test_research_runtime_passes_session_key(monkeypatch):
    """研究流水线的适配器把 session_key 透传给 llm.chat。"""
    from ..research import runtime

    seen: dict = {}
    snapshot = runtime.ModelSnapshot(
        provider="deepseek",
        model="deepseek-v4-flash",
        mode="default",
        captured_at=runtime.utcnow(),
    )

    class _FakeLLM:
        async def chat(self, system, user, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(content='{"findings": []}', raw=None)

    adapter = runtime.LlmClientAdapter(snapshot, llm=_FakeLLM(), session_key="research:rtask_9")
    await adapter.complete("sys", "user", json_schema={"type": "object"})
    assert seen.get("session_key") == "research:rtask_9"

    seen.clear()
    adapter_no_key = runtime.LlmClientAdapter(snapshot, llm=_FakeLLM())
    await adapter_no_key.complete("sys", "user", json_schema={"type": "object"})
    assert "session_key" not in seen or seen.get("session_key") is None
