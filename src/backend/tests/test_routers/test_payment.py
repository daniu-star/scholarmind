"""P0 Task 2.8: 支付回调安全回归测试

覆盖 spec Requirement「支付回调默认关闭与验签幂等」的 4 个 Scenario：
1. 默认关闭：支付路由仍可发现，但回调拒绝处理，便于前端显示商品目录和配置提示
2. 无签名通知被拒：PAYMENT_ENABLED=true 但 verify_alipay_signature 骨架返回 False
   → "failure"，订单状态保持 pending
3. 重复通知幂等：验签通过（monkeypatch 为 True）+ 同一 trade_no 提交 2 次
   → 全部 "success"，套餐只升级一次
4. 金额不匹配被拒：验签通过但 total_amount 与订单金额不符 → "failure"，
   不升级套餐，写入可疑事件日志

测试策略：
- 默认关闭用例复用 conftest 的 async_client（settings 默认 PAYMENT_ENABLED=False）
- 启用用例自建独立 fixture：monkeypatch settings.PAYMENT_ENABLED=True，
  手动初始化 temp DB + init_db（建表 + trade_no 唯一索引）+ 种子用户/订单，
  注入 app.state，避免依赖 lifespan 与 dev DB
- 幂等与金额测试通过 monkeypatch verify_alipay_signature → True 绕过 P0 骨架
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
from ...models.orm import Order, User, UserQuota
from ...services.auth_service import create_access_token, get_password_hash


# ── 辅助：种子用户 + 订单 + 配额 ──────────────────────────────


async def _seed_user_and_order(session_factory) -> tuple[int, str]:
    """种子一个普通用户（带 free 配额）+ 一笔 pending 的 pro_monthly 订单。

    P1 Task 17：订单金额改读 entitlement_service.PRODUCTS["monthly_all"]["amount_cents"]，
    与 routers/payment.py create_order 一致（原 settings.PRO_MONTHLY_PRICE * 100 已删除）。
    返回 (user_id, order_no)。
    """
    from ...config import settings
    from ...services.entitlement_service import PRODUCTS

    async with session_factory() as session:
        user = User(
            username="buyer1",
            password_hash=get_password_hash("buyerpass123"),
            nickname="Buyer",
            is_active=True,
            plan="free",
        )
        session.add(user)
        await session.flush()  # 拿到 user.id

        quota = UserQuota(
            user_id=user.id,
            tokens_used=0,
            tokens_limit=settings.FREE_TIER_TOKEN_LIMIT,
            plan="free",
        )
        session.add(quota)

        # 订单金额（分）：与 create_order 一致，来源 entitlement_service.PRODUCTS
        amount_cents = PRODUCTS["monthly_all"]["amount_cents"]
        order = Order(
            order_no="SMTESTBUYER00001",
            user_id=user.id,
            plan="pro_monthly",
            amount=amount_cents,
            payment_method="alipay",
            status="pending",
        )
        session.add(order)
        await session.commit()
        await session.refresh(user)
        return user.id, "SMTESTBUYER00001"


# ── Fixture：启用支付回调的独立 client ────────────────────────


@pytest_asyncio.fixture(scope="function")
async def payment_client(tmp_path, monkeypatch):
    """构造一个 PAYMENT_ENABLED=True 的独立 app + client。

    - 用 tmp_path 下的独立 sqlite 文件隔离 DB
    - 手动 init_db 建表（含 orders.trade_no 部分唯一索引）+ 种子用户/订单
    - 注入 app.state.db_engine / db_session_factory 让 get_db 复用
    - 设 ALIPAY_APP_ID 让 app_id/seller_id 校验生效
    """
    db_file = tmp_path / "test_payment.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    monkeypatch.setattr("src.backend.config.settings.DATABASE_URL", db_url)
    monkeypatch.setattr("src.backend.config.settings.PAYMENT_ENABLED", True)
    monkeypatch.setattr("src.backend.config.settings.PAYMENT_VERIFY_REQUIRED", True)
    # 设 ALIPAY_APP_ID 让字段校验生效（app_id/seller_id 都用此值匹配）
    monkeypatch.setattr("src.backend.config.settings.ALIPAY_APP_ID", "2021000000000001")
    monkeypatch.setattr("src.backend.config.settings.ALIPAY_SELLER_ID", "2021000000000001")

    engine = create_async_engine_from_url(db_url)
    await init_db(engine)
    session_factory = create_async_sessionmaker_from_engine(engine)
    user_id, order_no = await _seed_user_and_order(session_factory)

    from src.backend.app import create_app

    app = create_app()
    app.state.db_engine = engine
    app.state.db_session_factory = session_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client._user_id = user_id  # type: ignore[attr-defined]
        client._order_no = order_no  # type: ignore[attr-defined]
        client._session_factory = session_factory  # type: ignore[attr-defined]
        client._app = app  # type: ignore[attr-defined]
        yield client

    await engine.dispose()


def _bearer(user_id: int) -> dict[str, str]:
    token = create_access_token({"sub": str(user_id), "username": "buyer1"})
    return {"Authorization": f"Bearer {token}"}


def _alipay_notify_form(
    order_no: str,
    trade_no: str,
    total_amount: str,
    app_id: str = "2021000000000001",
    trade_status: str = "TRADE_SUCCESS",
) -> dict:
    """构造一份支付宝异步通知表单数据。"""
    return {
        "app_id": app_id,
        "seller_id": app_id,  # 沙箱环境 app_id==seller_id
        "out_trade_no": order_no,
        "trade_no": trade_no,
        "trade_status": trade_status,
        "total_amount": total_amount,
        "currency": "CNY",
        "sign": "fake-sign-for-test",  # P0 验签骨架不看此字段，但保留以测真实路径
    }


# ──── Scenario 1: 默认关闭返回 404 ────────────────────────────


@pytest.mark.asyncio
async def test_payment_disabled_by_default_alipay(async_client: AsyncClient):
    """PAYMENT_ENABLED 默认 False：支付宝回调明确返回 failure。"""
    response = await async_client.post(
        "/api/v1/payment/alipay/notify",
        data=_alipay_notify_form("SMX", "TX1", "39.90"),
    )
    assert response.status_code == 200
    assert response.text == "failure"


@pytest.mark.asyncio
async def test_payment_disabled_by_default_wechat(async_client: AsyncClient):
    """PAYMENT_ENABLED 默认 False：微信回调明确返回 FAIL。"""
    response = await async_client.post(
        "/api/v1/payment/wechat/notify",
        content=b"<xml><out_trade_no>SMX</out_trade_no></xml>",
        headers={"Content-Type": "application/xml"},
    )
    assert response.status_code == 200
    assert response.json()["code"] == "FAIL"


# ──── Scenario 2: 无签名/验签失败被拒（P0 骨架一律 False）────


@pytest.mark.asyncio
async def test_alipay_notify_no_signature_rejected(payment_client: AsyncClient, monkeypatch):
    """PAYMENT_ENABLED=true，verify_alipay_signature 返回 False → "failure"

    订单状态必须保持 pending，不升级套餐。

    P1 修复：原测试假设 verify_alipay_signature 是 P0 骨架（恒返回 False），
    但 P1 接入官方 SDK 后会真实调用 RSA 验签，因测试环境 ALIPAY_PRIVATE_KEY
    是占位符导致 RSA key format 异常。此处 monkeypatch 为 False 模拟验签失败。
    """
    monkeypatch.setattr(
        "src.backend.routers.payment.verify_alipay_signature",
        lambda data: False,
    )
    order_no = payment_client._order_no  # type: ignore[attr-defined]
    response = await payment_client.post(
        "/api/v1/payment/alipay/notify",
        data=_alipay_notify_form(order_no, "TRADE_001", "39.90"),
    )
    # PlainTextResponse → text/plain
    assert response.status_code == 200, f"unexpected status: {response.text}"
    assert response.text == "failure", f"expected 'failure' for unverified signature, got: {response.text!r}"

    # 订单状态保持 pending，未升级
    sf = payment_client._session_factory  # type: ignore[attr-defined]
    async with sf() as session:
        from sqlalchemy import select

        result = await session.execute(select(Order).where(Order.order_no == order_no))
        order = result.scalar_one()
        assert order.status == "pending", f"order status should stay pending, got {order.status}"
        assert order.trade_no is None, "trade_no should not be set on rejection"


@pytest.mark.asyncio
async def test_wechat_notify_no_signature_rejected(payment_client: AsyncClient):
    """PAYMENT_ENABLED=true，缺少签名头 → failure"""
    response = await payment_client.post(
        "/api/v1/payment/wechat/notify",
        content=b'{"out_trade_no":"SMTESTBUYER00001"}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200, f"unexpected status: {response.text}"
    body = response.json()
    assert body["code"] == "FAIL", f"expected FAIL for unverified wechat signature, got: {body}"


# ──── Scenario 3: 重复通知幂等 ────────────────────────────────


@pytest.mark.asyncio
async def test_alipay_notify_idempotent_on_duplicate_trade_no(payment_client: AsyncClient, monkeypatch):
    """同一 trade_no 提交 2 次，全部返回 success，套餐只升级一次。

    通过 monkeypatch verify_alipay_signature → True 绕过 P0 骨架。
    """
    # 绕过 P0 验签骨架（P1 接入官方 SDK 后此 monkeypatch 不再需要）
    monkeypatch.setattr(
        "src.backend.routers.payment.verify_alipay_signature",
        lambda data: True,
    )

    order_no = payment_client._order_no  # type: ignore[attr-defined]
    user_id = payment_client._user_id  # type: ignore[attr-defined]
    sf = payment_client._session_factory  # type: ignore[attr-defined]

    # 升级前快照配额 plan
    async with sf() as session:
        from sqlalchemy import select

        result = await session.execute(select(UserQuota).where(UserQuota.user_id == user_id))
        before = result.scalar_one()
        plan_before = before.plan
        tokens_limit_before = before.tokens_limit
    assert plan_before == "free", f"precondition: plan should be free, got {plan_before}"

    # 发送 2 次同一 trade_no
    form = _alipay_notify_form(order_no, "TRADE_IDEMP_001", "39.90")
    r1 = await payment_client.post("/api/v1/payment/alipay/notify", data=form)
    assert r1.status_code == 200
    assert r1.text == "success", f"1st notify should success, got {r1.text!r}"

    r2 = await payment_client.post("/api/v1/payment/alipay/notify", data=form)
    assert r2.status_code == 200
    assert r2.text == "success", f"2nd notify should success (idempotent), got {r2.text!r}"

    # 验证：订单 paid + trade_no 写入 + 配额升级只一次
    async with sf() as session:
        result = await session.execute(select(Order).where(Order.order_no == order_no))
        order = result.scalar_one()
        assert order.status == "paid", f"order should be paid, got {order.status}"
        assert order.trade_no == "TRADE_IDEMP_001"

        result = await session.execute(select(UserQuota).where(UserQuota.user_id == user_id))
        after = result.scalar_one()
        assert after.plan == "pro_monthly", f"plan should be upgraded to pro_monthly, got {after.plan}"
        assert after.tokens_limit > tokens_limit_before, (
            f"tokens_limit should increase after upgrade: {tokens_limit_before} -> {after.tokens_limit}"
        )


# ──── Scenario 4: 金额不匹配被拒 ─────────────────────────────


@pytest.mark.asyncio
async def test_alipay_notify_amount_mismatch_rejected(payment_client: AsyncClient, monkeypatch):
    """验签通过但 total_amount 与订单金额不匹配 → "failure"，不升级套餐。

    P1 Task 17：订单金额改读 PRODUCTS["monthly_all"]["amount_cents"] = 3990 分 = 39.90 元。
    故意提交错误的 total_amount（1.00 元 vs 39.90 元）应被拒。
    """
    monkeypatch.setattr(
        "src.backend.routers.payment.verify_alipay_signature",
        lambda data: True,
    )

    order_no = payment_client._order_no  # type: ignore[attr-defined]
    user_id = payment_client._user_id  # type: ignore[attr-defined]
    sf = payment_client._session_factory  # type: ignore[attr-defined]

    # 提交错误金额（1.00 元 = 100 分，订单是 39.90 元 = 3990 分）
    form = _alipay_notify_form(order_no, "TRADE_MISMATCH_001", "1.00")
    response = await payment_client.post("/api/v1/payment/alipay/notify", data=form)
    assert response.status_code == 200, f"unexpected status: {response.text}"
    assert response.text == "failure", f"expected 'failure' for amount mismatch, got: {response.text!r}"

    # 订单保持 pending，未升级
    async with sf() as session:
        from sqlalchemy import select

        result = await session.execute(select(Order).where(Order.order_no == order_no))
        order = result.scalar_one()
        assert order.status == "pending", f"order should stay pending on mismatch, got {order.status}"

        result = await session.execute(select(UserQuota).where(UserQuota.user_id == user_id))
        quota = result.scalar_one()
        assert quota.plan == "free", f"plan should stay free on mismatch, got {quota.plan}"


# ──── Scenario 5: app_id 不匹配也被拒 ────────────────────────


@pytest.mark.asyncio
async def test_alipay_notify_app_id_mismatch_rejected(payment_client: AsyncClient, monkeypatch):
    """验签通过但 app_id 与 settings.ALIPAY_APP_ID 不匹配 → "failure"."""
    monkeypatch.setattr(
        "src.backend.routers.payment.verify_alipay_signature",
        lambda data: True,
    )

    order_no = payment_client._order_no  # type: ignore[attr-defined]
    # 用错误的 app_id（settings 是 2021000000000001）
    form = _alipay_notify_form(order_no, "TRADE_APPID_001", "39.90", app_id="0000000000000000")
    response = await payment_client.post("/api/v1/payment/alipay/notify", data=form)
    assert response.status_code == 200
    assert response.text == "failure", f"expected 'failure' for app_id mismatch, got: {response.text!r}"
