"""手机号账户、免费对话额度与付费 Pipeline 权益测试。"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ..db.session import (
    create_async_engine_from_url,
    create_async_sessionmaker_from_engine,
    init_db,
)
from ..services.entitlement_service import EntitlementError, EntitlementService


@pytest_asyncio.fixture
async def account_client(tmp_path, monkeypatch):
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'accounts.db').as_posix()}"
    monkeypatch.setattr("src.backend.config.settings.DATABASE_URL", db_url)
    monkeypatch.setattr("src.backend.config.settings.PAYMENT_ENABLED", False)

    engine = create_async_engine_from_url(db_url)
    await init_db(engine)
    session_factory = create_async_sessionmaker_from_engine(engine)

    from ..app import create_app

    app = create_app()
    app.state.db_engine = engine
    app.state.db_session_factory = session_factory
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        client.session_factory = session_factory  # type: ignore[attr-defined]
        yield client
    await engine.dispose()


async def _register(client: AsyncClient, phone: str = "13800138000") -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={"phone": phone, "password": "SecurePass123", "nickname": "测试用户"},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_phone_register_login_and_initial_20_free_chats(account_client):
    registered = await _register(account_client, "138 0013 8000")
    assert registered["user"]["phone"] == "+86138****00"
    assert registered["entitlements"]["free_chats_remaining"] == 20
    assert registered["entitlements"]["pipeline_access"] == {
        "generation": False,
        "external_review": False,
        "modification": False,
    }

    login = await account_client.post(
        "/api/v1/auth/login",
        json={"phone": "+86 138-0013-8000", "password": "SecurePass123"},
    )
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["user"]["phone"] == "+86138****00"
    assert body["entitlements"]["free_chats_remaining"] == 20

    me = await account_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["entitlements"]["free_chats_remaining"] == 20


@pytest.mark.asyncio
async def test_duplicate_normalized_phone_is_rejected(account_client):
    await _register(account_client, "13800138000")
    duplicate = await account_client.post(
        "/api/v1/auth/register",
        json={
            "phone": "+86 138 0013 8000",
            "password": "AnotherPass123",
        },
    )
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_free_chat_quota_is_atomic_and_stops_at_20(account_client):
    registered = await _register(account_client)
    user_id = registered["user"]["id"]

    async with account_client.session_factory() as db:  # type: ignore[attr-defined]
        for remaining in range(19, -1, -1):
            usage = await EntitlementService.consume_chat(db, user_id)
            assert usage["free_chats_remaining"] == remaining
        with pytest.raises(EntitlementError) as exc:
            await EntitlementService.consume_chat(db, user_id)
        assert exc.value.code == "CHAT_QUOTA_EXHAUSTED"


@pytest.mark.asyncio
async def test_all_three_quick_pipelines_reject_free_user(account_client):
    registered = await _register(account_client)
    auth = {"Authorization": f"Bearer {registered['access_token']}"}

    generation = await account_client.post(
        "/api/v1/paper-pipeline/start",
        headers=auth,
        json={
            "session_id": "s-free",
            "agent_id": "researcher",
            "guidance_data": {"topic": "测试"},
        },
    )
    assert generation.status_code == 402
    assert generation.json()["error"]["code"] == "PAYMENT_REQUIRED"

    for capability in ("external_review", "modification"):
        review = await account_client.post(
            "/api/v1/paper-review/start",
            headers=auth,
            json={
                "paper_text": "这是一段足够长的测试论文正文，用来验证免费用户不能启动付费快速通道。",
                "pipeline_type": capability,
            },
        )
        assert review.status_code == 402
        assert review.json()["error"]["code"] == "PAYMENT_REQUIRED"


@pytest.mark.asyncio
async def test_four_products_grant_exact_entitlements(account_client):
    registered = await _register(account_client)
    user_id = registered["user"]["id"]

    async with account_client.session_factory() as db:  # type: ignore[attr-defined]
        await EntitlementService.grant_product(db, user_id, "paper_once", "test-1")
        snapshot = await EntitlementService.get_snapshot(db, user_id)
        assert snapshot["generation_credits"] == 1
        assert snapshot["modification_credits"] == 0
        await EntitlementService.consume_pipeline(db, user_id, "generation")
        with pytest.raises(EntitlementError):
            await EntitlementService.consume_pipeline(db, user_id, "generation")

        await EntitlementService.grant_product(db, user_id, "paper_bundle_5", "test-2")
        snapshot = await EntitlementService.get_snapshot(db, user_id)
        assert snapshot["shared_pipeline_credits"] == 5
        assert snapshot["external_review_active"] is True
        await EntitlementService.consume_pipeline(db, user_id, "modification")
        assert (await EntitlementService.get_snapshot(db, user_id))[
            "shared_pipeline_credits"
        ] == 4

        await EntitlementService.grant_product(db, user_id, "monthly_all", "test-3")
        snapshot = await EntitlementService.get_snapshot(db, user_id)
        assert snapshot["unlimited_pipeline"] is True
        assert snapshot["unlimited_chat"] is True
        assert snapshot["model_tier"] == "flash"

        await EntitlementService.grant_product(db, user_id, "monthly_pro", "test-4")
        snapshot = await EntitlementService.get_snapshot(db, user_id)
        assert snapshot["unlimited_pipeline"] is True
        assert snapshot["model_tier"] == "pro"


@pytest.mark.asyncio
async def test_payment_catalog_has_the_four_required_prices(account_client):
    response = await account_client.get("/api/v1/payment/packages")
    assert response.status_code == 200, response.text
    assert {
        package["id"]: package["amount_cents"]
        for package in response.json()["packages"]
    } == {
        "paper_once": 499,
        "paper_bundle_5": 1999,
        "monthly_all": 3990,
        "monthly_pro": 5990,
    }
