"""P0 Task 3.9: IDOR 安全回归测试

覆盖 spec Requirement「阻断匿名访问会话/Pipeline/Review/Agent 写操作」的 3 个 Scenario：
1. 匿名请求被拒：未携带 token 访问业务端点 → 401
2. 跨用户访问返回 404：用户 A 读取/删除用户 B 的会话与 pipeline → 404
3. refresh token 不能访问业务 API：携带 type=refresh 的 token → 401

测试策略：
- 自建独立 fixture：tmp_path 隔离 SQLite + init_db（建表含 conversations.user_id）
  + 种子两个用户 A/B（均 is_active=True）
- 用户 A 通过 ConversationRepository 直接种子一条会话消息（user_id=A.id）
- 用户 A 通过 PipelineStateRepo 直接种子一个 pipeline 状态（user_id=str(A.id)）
- 用 A、B 各自的 access token 访问对方资源 → 断言 404
- 匿名（无 Authorization 头）→ 断言 401
- 用 create_refresh_token 生成 refresh token 访问业务 API → 断言 401
- 所有 logger 调用使用 f-string（project_memory 硬约束）
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ..db.session import (
    create_async_engine_from_url,
    create_async_sessionmaker_from_engine,
    init_db,
)
from ..db.repository.conversation import ConversationRepository
from ..db.pipeline_state_repo import get_pipeline_state_repo
from ..models.orm import User, UserQuota
from ..services.auth_service import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
)


# ── 辅助：种子两个用户 + 用户 A 的会话与 pipeline ──────────────


async def _seed_users_and_resources(session_factory) -> tuple[int, int, str, str]:
    """种子用户 A、B，并为用户 A 创建一条会话与一个 pipeline 状态。

    返回 (user_a_id, user_b_id, session_id_a, pipeline_id_a)。
    """
    async with session_factory() as session:
        user_a = User(
            username="user_a",
            password_hash=get_password_hash("pass_a_123"),
            nickname="UserA",
            is_active=True,
            plan="free",
        )
        user_b = User(
            username="user_b",
            password_hash=get_password_hash("pass_b_123"),
            nickname="UserB",
            is_active=True,
            plan="free",
        )
        session.add_all([user_a, user_b])
        await session.flush()

        # 配额（避免 NULL 外键）
        session.add_all([
            UserQuota(user_id=user_a.id, tokens_used=0, tokens_limit=1000000, plan="free"),
            UserQuota(user_id=user_b.id, tokens_used=0, tokens_limit=1000000, plan="free"),
        ])
        await session.commit()
        await session.refresh(user_a)
        await session.refresh(user_b)

    session_id_a = "idor-session-a-1234567890"
    pipeline_id_a = "idor-pipeline-a-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    # 种子用户 A 的会话消息（直接走 repository，绑定 user_id=A.id）
    async with session_factory() as session:
        repo = ConversationRepository(session)
        await repo.add_message(
            session_id=session_id_a,
            agent_id="researcher",
            role="user",
            content="用户 A 的私密消息",
            user_id=user_a.id,
            title="用户 A 的会话",
        )
        await session.commit()

    # 种子用户 A 的 pipeline 状态（走单例 get_pipeline_state_repo()，
    # 确保与 Router/Service 共用同一实例，否则跨实例查询不到数据）
    # 注意：项目中存在 backend.* 与 src.backend.* 两条并行导入路径
    # （app.py 的 sys.path.insert 导致 backend 可作为顶层包导入），
    # 两套模块各自持有独立的 _repo 单例。测试需同时种子两套单例，
    # 否则 Router 使用的 service 实例可能查到空仓库。
    import sys as _sys
    initial_state = {
        "pipeline_id": pipeline_id_a,
        "user_id": str(user_a.id),
        "session_id": session_id_a,
        "status": "pending",
        "config": {
            "pipeline_id": pipeline_id_a,
            "session_id": session_id_a,
            "agent_id": "researcher",
            "user_id": str(user_a.id),
            "max_rounds": 5,
            "pass_threshold": 90,
        },
        "current_round": 0,
        "current_agent": None,
        "current_step": "初始化中",
        "score": None,
        "score_history": [],
        "logs": ["Pipeline 已创建"],
        "error": None,
        "started_at": "2026-07-01T00:00:00",
        "completed_at": None,
        "result": None,
    }
    # 遍历所有已加载的 pipeline_state_repo 模块，清空并种子每个单例
    _seeded_count = 0
    for _mod_name, _mod in list(_sys.modules.items()):
        if _mod_name.endswith("pipeline_state_repo") and _mod is not None:
            _singleton_repo = _mod.get_pipeline_state_repo()
            _singleton_repo._memory_store.clear()
            _singleton_repo._memory_user_index.clear()
            await _singleton_repo.save(pipeline_id_a, initial_state, user_id=str(user_a.id))
            _seeded_count += 1
    # 兜底：若循环未命中（模块尚未加载），至少种子当前包的单例
    if _seeded_count == 0:
        _fallback_repo = get_pipeline_state_repo()
        _fallback_repo._memory_store.clear()
        _fallback_repo._memory_user_index.clear()
        await _fallback_repo.save(pipeline_id_a, initial_state, user_id=str(user_a.id))

    return user_a.id, user_b.id, session_id_a, pipeline_id_a


# ── Fixture：独立 app + client（带种子用户与资源）──────────────


@pytest_asyncio.fixture(scope="function")
async def idor_client(tmp_path, monkeypatch):
    """构造独立 app + client，种子用户 A/B 与 A 的会话/pipeline。

    - tmp_path 隔离 SQLite
    - monkeypatch DEEPSEEK_API_KEY="" 强制 AgentService 走 mock 路径（不调真实 LLM）
    - 注入 app.state.db_engine / db_session_factory 让 get_db 复用
    """
    db_file = tmp_path / "test_idor.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"

    # 直接引用 settings 对象，避免字符串路径解析歧义（settings 是模块变量非子模块）
    from src.backend.config import settings as _settings

    monkeypatch.setattr(_settings, "DATABASE_URL", db_url)
    # 强制 mock 模式，避免 /agent/chat 真实调用 LLM
    monkeypatch.setattr(_settings, "DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(_settings, "ADMIN_USERNAMES", "admin")
    # JWT_SECRET_KEY 已在 tests/conftest.py 顶部通过 os.environ.setdefault 注入，
    # settings 在模块导入时即读取该 env var，所有测试共用同一密钥，
    # 确保 create_access_token 与 decode_token 使用一致的 HMAC key。

    engine = create_async_engine_from_url(db_url)
    await init_db(engine)
    session_factory = create_async_sessionmaker_from_engine(engine)
    user_a_id, user_b_id, session_id_a, pipeline_id_a = await _seed_users_and_resources(
        session_factory
    )

    from src.backend.app import create_app

    app = create_app()
    app.state.db_engine = engine
    app.state.db_session_factory = session_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client._user_a_id = user_a_id  # type: ignore[attr-defined]
        client._user_b_id = user_b_id  # type: ignore[attr-defined]
        client._session_id_a = session_id_a  # type: ignore[attr-defined]
        client._pipeline_id_a = pipeline_id_a  # type: ignore[attr-defined]
        client._app = app  # type: ignore[attr-defined]
        yield client

    await engine.dispose()


def _bearer_access(user_id: int) -> dict[str, str]:
    """构造 access token（type=access）的 Authorization 头"""
    token = create_access_token({"sub": str(user_id), "username": f"user_{user_id}"})
    return {"Authorization": f"Bearer {token}"}


def _bearer_refresh(user_id: int) -> dict[str, str]:
    """构造 refresh token（type=refresh）的 Authorization 头"""
    token = create_refresh_token({"sub": str(user_id), "username": f"user_{user_id}"})
    return {"Authorization": f"Bearer {token}"}


# ──── Scenario 1: 匿名请求全部返回 401 ────────────────────────


@pytest.mark.asyncio
async def test_anonymous_agent_chat_rejected(idor_client: AsyncClient):
    """匿名 POST /agent/chat → 401"""
    response = await idor_client.post(
        "/api/v1/agent/chat",
        json={"message": "hi", "agent_id": "researcher", "session_id": "anon-1"},
    )
    assert response.status_code == 401, (
        f"expected 401, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_anonymous_list_sessions_rejected(idor_client: AsyncClient):
    """匿名 GET /agent/sessions → 401"""
    response = await idor_client.get("/api/v1/agent/sessions")
    assert response.status_code == 401, (
        f"expected 401, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_anonymous_get_conversation_rejected(idor_client: AsyncClient):
    """匿名 GET /agent/conversation/{session_id} → 401"""
    response = await idor_client.get(
        f"/api/v1/agent/conversation/{idor_client._session_id_a}"  # type: ignore[attr-defined]
    )
    assert response.status_code == 401, (
        f"expected 401, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_anonymous_delete_session_rejected(idor_client: AsyncClient):
    """匿名 DELETE /agent/sessions/{session_id} → 401"""
    response = await idor_client.delete(
        f"/api/v1/agent/sessions/{idor_client._session_id_a}"  # type: ignore[attr-defined]
    )
    assert response.status_code == 401, (
        f"expected 401, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_anonymous_pipeline_status_rejected(idor_client: AsyncClient):
    """匿名 GET /paper-pipeline/{id}/status → 401"""
    response = await idor_client.get(
        f"/api/v1/paper-pipeline/{idor_client._pipeline_id_a}/status"  # type: ignore[attr-defined]
    )
    assert response.status_code == 401, (
        f"expected 401, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_anonymous_pipeline_start_rejected(idor_client: AsyncClient):
    """匿名 POST /paper-pipeline/start → 401"""
    response = await idor_client.post(
        "/api/v1/paper-pipeline/start",
        json={
            "session_id": "anon-pipeline",
            "agent_id": "researcher",
            "guidance_data": {},
        },
    )
    assert response.status_code == 401, (
        f"expected 401, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_anonymous_review_status_rejected(idor_client: AsyncClient):
    """匿名 GET /paper-review/{id}/status → 401"""
    response = await idor_client.get(
        "/api/v1/paper-review/idor-review-a/status"
    )
    assert response.status_code == 401, (
        f"expected 401, got {response.status_code}: {response.text}"
    )


# ──── Scenario 2: 跨用户访问返回 404 ───────────────────────────


@pytest.mark.asyncio
async def test_cross_user_get_conversation_returns_404(idor_client: AsyncClient):
    """用户 B 读取用户 A 的 session_id → 404（不暴露存在性，不返回数据）"""
    headers = _bearer_access(idor_client._user_b_id)  # type: ignore[attr-defined]
    response = await idor_client.get(
        f"/api/v1/agent/conversation/{idor_client._session_id_a}",  # type: ignore[attr-defined]
        headers=headers,
    )
    assert response.status_code == 404, (
        f"expected 404 for cross-user read, got {response.status_code}: {response.text}"
    )
    # 确保不返回任何 A 的数据
    assert "用户 A 的私密消息" not in response.text


@pytest.mark.asyncio
async def test_cross_user_delete_session_returns_404(idor_client: AsyncClient):
    """用户 B 删除用户 A 的 session_id → 404"""
    headers = _bearer_access(idor_client._user_b_id)  # type: ignore[attr-defined]
    response = await idor_client.delete(
        f"/api/v1/agent/sessions/{idor_client._session_id_a}",  # type: ignore[attr-defined]
        headers=headers,
    )
    assert response.status_code == 404, (
        f"expected 404 for cross-user delete, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_cross_user_rename_session_returns_404(idor_client: AsyncClient):
    """用户 B 重命名用户 A 的 session_id → 404"""
    headers = _bearer_access(idor_client._user_b_id)  # type: ignore[attr-defined]
    response = await idor_client.patch(
        f"/api/v1/agent/sessions/{idor_client._session_id_a}",  # type: ignore[attr-defined]
        headers=headers,
        json={"title": "hijacked by B"},
    )
    assert response.status_code == 404, (
        f"expected 404 for cross-user rename, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_cross_user_clear_conversation_no_data_deleted(idor_client: AsyncClient):
    """用户 B 清空用户 A 的 session_id → cleared=0（不删除任何数据）

    DELETE /agent/conversation/{session_id} 返回 200 cleared=0（幂等语义），
    但必须确保用户 A 的消息未被删除。这是 IDOR 防护的核心：跨用户写操作
    不影响对方数据。
    """
    headers = _bearer_access(idor_client._user_b_id)  # type: ignore[attr-defined]
    response = await idor_client.delete(
        f"/api/v1/agent/conversation/{idor_client._session_id_a}",  # type: ignore[attr-defined]
        headers=headers,
    )
    # clear 返回 200（幂等），但 cleared 必须 = 0（未删除任何 A 的消息）
    assert response.status_code == 200, (
        f"expected 200 for clear (idempotent), got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["cleared"] == 0, (
        f"expected cleared=0 for cross-user clear, got {body.get('cleared')}"
    )

    # 验证用户 A 的消息仍然存在（B 未删除任何）
    headers_a = _bearer_access(idor_client._user_a_id)  # type: ignore[attr-defined]
    resp_a = await idor_client.get(
        f"/api/v1/agent/conversation/{idor_client._session_id_a}",  # type: ignore[attr-defined]
        headers=headers_a,
    )
    assert resp_a.status_code == 200, f"A should still see own session: {resp_a.text}"
    assert resp_a.json()["message_count"] >= 1, "A's messages should still exist"


@pytest.mark.asyncio
async def test_cross_user_list_sessions_no_leak(idor_client: AsyncClient):
    """用户 B 列出自己的会话 → 不应包含用户 A 的 session_id"""
    headers = _bearer_access(idor_client._user_b_id)  # type: ignore[attr-defined]
    response = await idor_client.get("/api/v1/agent/sessions", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    session_ids = [s["session_id"] for s in body["sessions"]]
    assert idor_client._session_id_a not in session_ids, (  # type: ignore[attr-defined]
        f"A's session leaked to B: {session_ids}"
    )


@pytest.mark.asyncio
async def test_cross_user_pipeline_status_returns_404(idor_client: AsyncClient):
    """用户 B 查询用户 A 的 pipeline_id 状态 → 404"""
    headers = _bearer_access(idor_client._user_b_id)  # type: ignore[attr-defined]
    response = await idor_client.get(
        f"/api/v1/paper-pipeline/{idor_client._pipeline_id_a}/status",  # type: ignore[attr-defined]
        headers=headers,
    )
    assert response.status_code == 404, (
        f"expected 404 for cross-user pipeline status, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_cross_user_pipeline_result_returns_404(idor_client: AsyncClient):
    """用户 B 获取用户 A 的 pipeline 结果 → 404"""
    headers = _bearer_access(idor_client._user_b_id)  # type: ignore[attr-defined]
    response = await idor_client.get(
        f"/api/v1/paper-pipeline/{idor_client._pipeline_id_a}/result",  # type: ignore[attr-defined]
        headers=headers,
    )
    assert response.status_code == 404, (
        f"expected 404 for cross-user pipeline result, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_cross_user_pipeline_cancel_returns_404(idor_client: AsyncClient):
    """用户 B 取消用户 A 的 pipeline → 404"""
    headers = _bearer_access(idor_client._user_b_id)  # type: ignore[attr-defined]
    response = await idor_client.post(
        f"/api/v1/paper-pipeline/{idor_client._pipeline_id_a}/cancel",  # type: ignore[attr-defined]
        headers=headers,
    )
    assert response.status_code == 404, (
        f"expected 404 for cross-user pipeline cancel, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_cross_user_pipeline_list_no_leak(idor_client: AsyncClient):
    """用户 B 列出自己的 pipeline → 不应包含用户 A 的 pipeline_id"""
    headers = _bearer_access(idor_client._user_b_id)  # type: ignore[attr-defined]
    response = await idor_client.get("/api/v1/paper-pipeline", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    pipeline_ids = [p["pipeline_id"] for p in body["pipelines"]]
    assert idor_client._pipeline_id_a not in pipeline_ids, (  # type: ignore[attr-defined]
        f"A's pipeline leaked to B: {pipeline_ids}"
    )


# ──── Scenario 3: refresh token 访问业务 API 返回 401 ──────────


@pytest.mark.asyncio
async def test_refresh_token_agent_chat_rejected(idor_client: AsyncClient):
    """refresh token 访问 POST /agent/chat → 401（需要 access token）"""
    headers = _bearer_refresh(idor_client._user_a_id)  # type: ignore[attr-defined]
    response = await idor_client.post(
        "/api/v1/agent/chat",
        json={"message": "hi", "agent_id": "researcher", "session_id": "refresh-test"},
        headers=headers,
    )
    assert response.status_code == 401, (
        f"expected 401 for refresh token, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_refresh_token_list_sessions_rejected(idor_client: AsyncClient):
    """refresh token 访问 GET /agent/sessions → 401"""
    headers = _bearer_refresh(idor_client._user_a_id)  # type: ignore[attr-defined]
    response = await idor_client.get("/api/v1/agent/sessions", headers=headers)
    assert response.status_code == 401, (
        f"expected 401 for refresh token, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_refresh_token_pipeline_status_rejected(idor_client: AsyncClient):
    """refresh token 访问 GET /paper-pipeline/{id}/status → 401"""
    headers = _bearer_refresh(idor_client._user_a_id)  # type: ignore[attr-defined]
    response = await idor_client.get(
        f"/api/v1/paper-pipeline/{idor_client._pipeline_id_a}/status",  # type: ignore[attr-defined]
        headers=headers,
    )
    assert response.status_code == 401, (
        f"expected 401 for refresh token, got {response.status_code}: {response.text}"
    )


# ──── 补充：用户 A 能正常访问自己的资源（正向回归）────────────


@pytest.mark.asyncio
async def test_owner_can_read_own_conversation(idor_client: AsyncClient):
    """用户 A 读取自己的 session_id → 200（正向回归，确保鉴权未误伤）"""
    headers = _bearer_access(idor_client._user_a_id)  # type: ignore[attr-defined]
    response = await idor_client.get(
        f"/api/v1/agent/conversation/{idor_client._session_id_a}",  # type: ignore[attr-defined]
        headers=headers,
    )
    assert response.status_code == 200, (
        f"owner should read own session, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["message_count"] >= 1
    assert any("用户 A 的私密消息" in m["content"] for m in body["history"])


@pytest.mark.asyncio
async def test_owner_can_list_own_pipeline(idor_client: AsyncClient):
    """用户 A 列出自己的 pipeline → 包含自己的 pipeline_id"""
    headers = _bearer_access(idor_client._user_a_id)  # type: ignore[attr-defined]
    response = await idor_client.get("/api/v1/paper-pipeline", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    pipeline_ids = [p["pipeline_id"] for p in body["pipelines"]]
    assert idor_client._pipeline_id_a in pipeline_ids, (  # type: ignore[attr-defined]
        f"A's pipeline missing from own list: {pipeline_ids}"
    )
