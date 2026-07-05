"""P0 Task 4.6: Agent 模型策略安全回归测试

覆盖 spec Requirement「客户端模型选择受控枚举」的 3 个 Scenario：
1. 非法 model 字符串被拒：请求体包含 ``model: "deepseek-arbitrary-string"`` → 422
2. 免费用户请求 Pro 被拒：免费套餐用户提交 ``mode: "pro"`` → 403
3. 合法 mode 映射：Pro 用户提交 ``mode: "pro"`` → 服务端调用 PRO 模型 ID

补充场景：
- ``mode=None``（不传）→ 免费用户调用 FLASH 模型，Pro 用户调用 PRO 模型
- ``mode="flash"`` → 任意套餐用户调用 FLASH 模型
- 非法 mode 值（``mode="invalid"``）→ 422（Pydantic Literal 校验）
- 流式端点 ``/agent/stream`` 免费用户 ``mode="pro"`` → 403

测试策略：
- 自建独立 fixture：tmp_path 隔离 SQLite + init_db + 种子 free/pro 两个用户
- monkeypatch ``settings.DEEPSEEK_API_KEY`` 为非占位符值，使 AgentService 走真实 LLM
  路径（而非 mock 模式），从而能验证 ``llm_client.chat()`` 实际收到的 ``model`` 参数
- monkeypatch ``llm_client.chat`` 为 AsyncMock，避免真实网络调用，捕获 ``model`` kwarg
- 所有 logger 调用使用 f-string（project_memory 硬约束）
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ...db.session import (
    create_async_engine_from_url,
    create_async_sessionmaker_from_engine,
    init_db,
)
from ...models.orm import User, UserQuota
from ...services.auth_service import create_access_token, get_password_hash


# ── 辅助：种子 free / pro 两个用户 ──────────────────────────────


async def _seed_users(session_factory) -> tuple[int, int]:
    """种子 free_user 与 pro_user，返回 (free_user_id, pro_user_id)。"""
    async with session_factory() as session:
        free_user = User(
            username="free_user",
            password_hash=get_password_hash("free_pass_123"),
            nickname="FreeUser",
            is_active=True,
            plan="free",
        )
        pro_user = User(
            username="pro_user",
            password_hash=get_password_hash("pro_pass_123"),
            nickname="ProUser",
            is_active=True,
            plan="pro",
        )
        session.add_all([free_user, pro_user])
        await session.flush()

        # 配额：free_user 走免费额度，pro_user 走 pro 额度
        session.add_all([
            UserQuota(
                user_id=free_user.id,
                tokens_used=0,
                tokens_limit=1_000_000,
                plan="free",
            ),
            UserQuota(
                user_id=pro_user.id,
                tokens_used=0,
                tokens_limit=10_000_000,
                plan="pro",
            ),
        ])
        await session.commit()
        await session.refresh(free_user)
        await session.refresh(pro_user)

    return free_user.id, pro_user.id


# ── Fixture：独立 app + client + 捕获 llm_client.chat 的 model 参数 ──


@pytest_asyncio.fixture(scope="function")
async def policy_client(tmp_path, monkeypatch):
    """构造独立 app + client，种子 free/pro 用户，mock llm_client.chat 捕获 model。

    - tmp_path 隔离 SQLite
    - monkeypatch DEEPSEEK_API_KEY 为非占位符值 → AgentService 走真实 LLM 路径
    - monkeypatch llm_client.chat 为 AsyncMock → 捕获传入的 model kwarg，不触发真实网络
    - client._captured_models 记录每次 chat 调用的 model 参数，供断言
    """
    db_file = tmp_path / "test_model_policy.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"

    from src.backend.config import settings as _settings

    monkeypatch.setattr(_settings, "DATABASE_URL", db_url)
    # 非占位符 API key，使 _is_api_key_valid() 返回 True（避免走 mock 回复路径）
    monkeypatch.setattr(_settings, "DEEPSEEK_API_KEY", "test-key-valid-for-model-policy")
    monkeypatch.setattr(_settings, "ADMIN_USERNAMES", "admin")
    # JWT_SECRET_KEY 已在 tests/conftest.py 顶部通过 os.environ.setdefault 注入

    engine = create_async_engine_from_url(db_url)
    await init_db(engine)
    session_factory = create_async_sessionmaker_from_engine(engine)
    free_user_id, pro_user_id = await _seed_users(session_factory)

    # 捕获 llm_client.chat_messages 的 model 参数
    captured: list[str] = []

    async def _mock_chat_messages(messages, *, temperature=0.7, max_tokens=2048,
                                  response_format=None, model=None, stream=False):
        captured.append(model)
        # 返回最小可用的 LLMResponse；内容不含 chart/cnki 触发词，避免技能副作用
        from src.backend.utils.llm_client import LLMResponse
        return LLMResponse(content="已收到您的消息，这是模拟回复。")

    # patch 全局 llm_client 单例的 chat_messages 方法（AgentService.chat 实际调用此方法）
    from src.backend.utils.llm_client import llm_client as _llm_client_singleton
    monkeypatch.setattr(_llm_client_singleton, "chat_messages", _mock_chat_messages)

    from src.backend.app import create_app

    app = create_app()
    app.state.db_engine = engine
    app.state.db_session_factory = session_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client._free_user_id = free_user_id  # type: ignore[attr-defined]
        client._pro_user_id = pro_user_id  # type: ignore[attr-defined]
        client._captured_models = captured  # type: ignore[attr-defined]
        client._app = app  # type: ignore[attr-defined]
        yield client

    await engine.dispose()


def _bearer_access(user_id: int) -> dict[str, str]:
    """构造 access token（type=access）的 Authorization 头"""
    token = create_access_token({"sub": str(user_id), "username": f"user_{user_id}"})
    return {"Authorization": f"Bearer {token}"}


# ──── Scenario 1: 非法 model 字符串被拒（422）──────────────────


@pytest.mark.asyncio
async def test_request_with_deprecated_model_field_returns_422(
    policy_client: AsyncClient,
):
    """请求体包含 ``model: "deepseek-arbitrary-string"`` → 422

    P0 Task 4.5：ChatRequest.reject_deprecated_model_field validator 拒绝已废弃的
    model 字段，返回 422 并提示 ``model field is deprecated, use mode (flash|pro)``。
    """
    headers = _bearer_access(policy_client._free_user_id)  # type: ignore[attr-defined]
    response = await policy_client.post(
        "/api/v1/agent/chat",
        json={
            "message": "测试消息",
            "agent_id": "researcher",
            "session_id": "deprecated-model-test",
            "model": "deepseek-arbitrary-string",
        },
        headers=headers,
    )
    assert response.status_code == 422, (
        f"expected 422 for deprecated model field, got {response.status_code}: {response.text}"
    )
    # 错误信息提示使用 mode
    body = response.text
    assert "model field is deprecated" in body or "use mode" in body, (
        f"expected deprecation hint in error, got: {body}"
    )


@pytest.mark.asyncio
async def test_request_with_legacy_full_model_name_returns_422(
    policy_client: AsyncClient,
):
    """请求体包含旧的全名 ``model: "deepseek-v4-flash"`` 也应被拒（422）

    防止旧前端绕过：即使是合法的旧模型全名，也必须改为 mode 枚举提交。
    """
    headers = _bearer_access(policy_client._free_user_id)  # type: ignore[attr-defined]
    response = await policy_client.post(
        "/api/v1/agent/chat",
        json={
            "message": "测试消息",
            "agent_id": "researcher",
            "session_id": "legacy-model-name-test",
            "model": "deepseek-v4-flash",
        },
        headers=headers,
    )
    assert response.status_code == 422, (
        f"expected 422 for legacy model name, got {response.status_code}: {response.text}"
    )


# ──── Scenario 2: 免费用户请求 Pro 被拒（403）─────────────────


@pytest.mark.asyncio
async def test_free_user_request_pro_mode_returns_403(
    policy_client: AsyncClient,
):
    """免费套餐用户提交 ``mode: "pro"`` → 403（需升级套餐）"""
    headers = _bearer_access(policy_client._free_user_id)  # type: ignore[attr-defined]
    response = await policy_client.post(
        "/api/v1/agent/chat",
        json={
            "message": "测试 Pro 模式",
            "agent_id": "researcher",
            "session_id": "free-pro-mode-test",
            "mode": "pro",
        },
        headers=headers,
    )
    assert response.status_code == 403, (
        f"expected 403 for free user requesting pro, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_free_user_stream_pro_mode_returns_403(
    policy_client: AsyncClient,
):
    """流式端点：免费用户 ``mode: "pro"`` → 403"""
    headers = _bearer_access(policy_client._free_user_id)  # type: ignore[attr-defined]
    response = await policy_client.post(
        "/api/v1/agent/stream",
        json={
            "message": "测试 Pro 流式",
            "agent_id": "researcher",
            "session_id": "free-pro-stream-test",
            "mode": "pro",
        },
        headers=headers,
    )
    assert response.status_code == 403, (
        f"expected 403 for free user streaming pro, got {response.status_code}: {response.text}"
    )


# ──── Scenario 3: 合法 mode 映射（Pro 用户 → PRO 模型）──────────


@pytest.mark.asyncio
async def test_pro_user_request_pro_mode_calls_pro_model(
    policy_client: AsyncClient,
):
    """Pro 用户提交 ``mode: "pro"`` → 200 且 llm_client.chat 收到 PRO_MODEL"""
    from src.backend.config import settings

    headers = _bearer_access(policy_client._pro_user_id)  # type: ignore[attr-defined]
    captured: list = policy_client._captured_models  # type: ignore[attr-defined]
    captured.clear()

    response = await policy_client.post(
        "/api/v1/agent/chat",
        json={
            "message": "测试 Pro 模式",
            "agent_id": "researcher",
            "session_id": "pro-pro-mode-test",
            "mode": "pro",
        },
        headers=headers,
    )
    assert response.status_code == 200, (
        f"expected 200 for pro user, got {response.status_code}: {response.text}"
    )
    assert len(captured) >= 1, "llm_client.chat should be called at least once"
    assert captured[0] == settings.DEEPSEEK_MODEL_PRO, (
        f"expected model={settings.DEEPSEEK_MODEL_PRO}, got {captured[0]}"
    )


# ──── mode=None 套餐默认模型 ─────────────────────────────────


@pytest.mark.asyncio
async def test_free_user_mode_none_calls_flash_model(
    policy_client: AsyncClient,
):
    """免费用户不传 mode → 默认调用 FLASH_MODEL"""
    from src.backend.config import settings

    headers = _bearer_access(policy_client._free_user_id)  # type: ignore[attr-defined]
    captured: list = policy_client._captured_models  # type: ignore[attr-defined]
    captured.clear()

    response = await policy_client.post(
        "/api/v1/agent/chat",
        json={
            "message": "测试默认模式",
            "agent_id": "researcher",
            "session_id": "free-none-mode-test",
        },
        headers=headers,
    )
    assert response.status_code == 200, (
        f"expected 200, got {response.status_code}: {response.text}"
    )
    assert len(captured) >= 1, "llm_client.chat should be called"
    assert captured[0] == settings.DEEPSEEK_MODEL_FLASH, (
        f"expected model={settings.DEEPSEEK_MODEL_FLASH}, got {captured[0]}"
    )


@pytest.mark.asyncio
async def test_pro_user_mode_none_calls_pro_model(
    policy_client: AsyncClient,
):
    """Pro 用户不传 mode → 默认调用 PRO_MODEL（套餐默认）"""
    from src.backend.config import settings

    headers = _bearer_access(policy_client._pro_user_id)  # type: ignore[attr-defined]
    captured: list = policy_client._captured_models  # type: ignore[attr-defined]
    captured.clear()

    response = await policy_client.post(
        "/api/v1/agent/chat",
        json={
            "message": "测试默认模式",
            "agent_id": "researcher",
            "session_id": "pro-none-mode-test",
        },
        headers=headers,
    )
    assert response.status_code == 200, (
        f"expected 200, got {response.status_code}: {response.text}"
    )
    assert len(captured) >= 1, "llm_client.chat should be called"
    assert captured[0] == settings.DEEPSEEK_MODEL_PRO, (
        f"expected model={settings.DEEPSEEK_MODEL_PRO}, got {captured[0]}"
    )


# ──── mode="flash" 任意套餐可用 ───────────────────────────────


@pytest.mark.asyncio
async def test_pro_user_mode_flash_calls_flash_model(
    policy_client: AsyncClient,
):
    """Pro 用户 ``mode="flash"`` → 调用 FLASH_MODEL（flash 任意套餐可用）"""
    from src.backend.config import settings

    headers = _bearer_access(policy_client._pro_user_id)  # type: ignore[attr-defined]
    captured: list = policy_client._captured_models  # type: ignore[attr-defined]
    captured.clear()

    response = await policy_client.post(
        "/api/v1/agent/chat",
        json={
            "message": "测试 Flash 模式",
            "agent_id": "researcher",
            "session_id": "pro-flash-mode-test",
            "mode": "flash",
        },
        headers=headers,
    )
    assert response.status_code == 200, (
        f"expected 200, got {response.status_code}: {response.text}"
    )
    assert len(captured) >= 1, "llm_client.chat should be called"
    assert captured[0] == settings.DEEPSEEK_MODEL_FLASH, (
        f"expected model={settings.DEEPSEEK_MODEL_FLASH}, got {captured[0]}"
    )


@pytest.mark.asyncio
async def test_free_user_mode_flash_calls_flash_model(
    policy_client: AsyncClient,
):
    """免费用户 ``mode="flash"`` → 调用 FLASH_MODEL"""
    from src.backend.config import settings

    headers = _bearer_access(policy_client._free_user_id)  # type: ignore[attr-defined]
    captured: list = policy_client._captured_models  # type: ignore[attr-defined]
    captured.clear()

    response = await policy_client.post(
        "/api/v1/agent/chat",
        json={
            "message": "测试 Flash 模式",
            "agent_id": "researcher",
            "session_id": "free-flash-mode-test",
            "mode": "flash",
        },
        headers=headers,
    )
    assert response.status_code == 200, (
        f"expected 200, got {response.status_code}: {response.text}"
    )
    assert len(captured) >= 1, "llm_client.chat should be called"
    assert captured[0] == settings.DEEPSEEK_MODEL_FLASH, (
        f"expected model={settings.DEEPSEEK_MODEL_FLASH}, got {captured[0]}"
    )


# ──── 非法 mode 值（422）──────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_mode_value_returns_422(
    policy_client: AsyncClient,
):
    """``mode: "invalid"`` → 422（Pydantic Literal["flash","pro"] 校验）"""
    headers = _bearer_access(policy_client._free_user_id)  # type: ignore[attr-defined]
    response = await policy_client.post(
        "/api/v1/agent/chat",
        json={
            "message": "测试非法 mode",
            "agent_id": "researcher",
            "session_id": "invalid-mode-test",
            "mode": "invalid",
        },
        headers=headers,
    )
    assert response.status_code == 422, (
        f"expected 422 for invalid mode, got {response.status_code}: {response.text}"
    )


# ──── 匿名请求仍被鉴权拦截（401）──────────────────────────────


@pytest.mark.asyncio
async def test_anonymous_chat_rejected(policy_client: AsyncClient):
    """无 token 访问 /agent/chat → 401（与 Task 3 鉴权一致，不因 mode 改动而退步）"""
    response = await policy_client.post(
        "/api/v1/agent/chat",
        json={
            "message": "匿名测试",
            "agent_id": "researcher",
            "session_id": "anon-test",
            "mode": "flash",
        },
    )
    assert response.status_code == 401, (
        f"expected 401 for anonymous, got {response.status_code}: {response.text}"
    )
