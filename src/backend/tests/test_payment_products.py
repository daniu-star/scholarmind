"""四档商品的下单、回调、幂等发放与订单隔离测试。"""
from __future__ import annotations

import base64
import json
import time
from urllib.parse import parse_qs

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ..db.session import (
    create_async_engine_from_url,
    create_async_sessionmaker_from_engine,
    init_db,
)
from ..services.payment_gateway import (
    AlipayGateway,
    PaymentConfigurationError,
    PaymentProviderError,
    WeChatGateway,
    validate_alipay_configuration,
)
from ..config import settings


class FakeGateway:
    calls: list[tuple[str, int, str]] = []

    async def create_payment(self, order_no: str, amount_cents: int, subject: str):
        self.calls.append((order_no, amount_cents, subject))
        return f"https://pay.test/{order_no}"


@pytest_asyncio.fixture
async def billing_client(tmp_path, monkeypatch):
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'billing.db').as_posix()}"
    monkeypatch.setattr("src.backend.config.settings.DATABASE_URL", db_url)
    monkeypatch.setattr("src.backend.config.settings.PAYMENT_ENABLED", True)
    monkeypatch.setattr("src.backend.config.settings.PAYMENT_VERIFY_REQUIRED", True)
    monkeypatch.setattr("src.backend.config.settings.ALIPAY_APP_ID", "app-001")
    monkeypatch.setattr("src.backend.config.settings.ALIPAY_SELLER_ID", "seller-001")
    monkeypatch.setattr("src.backend.config.settings.WECHAT_PAY_APP_ID", "wx-app")
    monkeypatch.setattr("src.backend.config.settings.WECHAT_PAY_MCH_ID", "wx-mch")
    monkeypatch.setattr(
        "src.backend.routers.payment.gateway_for", lambda method: FakeGateway()
    )
    FakeGateway.calls.clear()

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
        yield client
    await engine.dispose()


async def _account(client: AsyncClient, phone: str) -> tuple[dict, dict]:
    response = await client.post(
        "/api/v1/auth/register",
        json={"phone": phone, "password": "SecurePass123"},
    )
    body = response.json()
    return body, {"Authorization": f"Bearer {body['access_token']}"}


async def _order(
    client: AsyncClient, auth: dict, product_id: str, method: str = "alipay"
) -> dict:
    response = await client.post(
        "/api/v1/payment/orders",
        headers=auth,
        json={"product_id": product_id, "payment_method": method},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_server_catalog_price_is_used_when_creating_order(billing_client):
    _, auth = await _account(billing_client, "13900139000")
    order = await _order(billing_client, auth, "paper_once")
    assert order["product"]["amount_cents"] == 499
    assert order["pay_url"] == f"https://pay.test/{order['order_no']}"
    assert FakeGateway.calls[0][1] == 499

    status = await billing_client.get(
        f"/api/v1/payment/orders/{order['order_no']}/status", headers=auth
    )
    assert status.status_code == 200
    assert status.json()["amount_cents"] == 499
    assert status.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_alipay_verified_callback_grants_once_and_is_idempotent(
    billing_client, monkeypatch
):
    _, auth = await _account(billing_client, "13700137000")
    order = await _order(billing_client, auth, "paper_bundle_5")
    monkeypatch.setattr(
        "src.backend.routers.payment.verify_alipay_signature", lambda data: True
    )
    form = {
        "app_id": "app-001",
        "seller_id": "seller-001",
        "out_trade_no": order["order_no"],
        "trade_no": "ALI-TRADE-001",
        "trade_status": "TRADE_SUCCESS",
        "total_amount": "19.99",
        "currency": "CNY",
        "sign": "verified-by-test-double",
    }
    first = await billing_client.post("/api/v1/payment/alipay/notify", data=form)
    second = await billing_client.post("/api/v1/payment/alipay/notify", data=form)
    assert first.text == "success"
    assert second.text == "success"

    status = await billing_client.get(
        f"/api/v1/payment/orders/{order['order_no']}/status", headers=auth
    )
    entitlements = status.json()["entitlements"]
    assert status.json()["status"] == "paid"
    assert entitlements["shared_pipeline_credits"] == 5
    assert entitlements["external_review_active"] is True


@pytest.mark.asyncio
async def test_wechat_verified_and_decrypted_callback_grants_monthly_pro(
    billing_client, monkeypatch
):
    _, auth = await _account(billing_client, "13600136000")
    order = await _order(billing_client, auth, "monthly_pro", "wechat")
    monkeypatch.setattr(
        "src.backend.routers.payment.WeChatGateway.verify_and_decrypt",
        lambda self, body, headers: {
            "event_type": "TRANSACTION.SUCCESS",
            "transaction": {
                "out_trade_no": order["order_no"],
                "transaction_id": "WX-TRADE-001",
                "trade_state": "SUCCESS",
                "appid": "wx-app",
                "mchid": "wx-mch",
                "amount": {"total": 5990, "currency": "CNY"},
                "success_time": "2026-07-02T12:00:00+08:00",
            },
        },
    )
    callback = await billing_client.post(
        "/api/v1/payment/wechat/notify",
        content=b'{"encrypted":"callback"}',
        headers={"Wechatpay-Signature": "verified"},
    )
    assert callback.json()["code"] == "SUCCESS"

    status = await billing_client.get(
        f"/api/v1/payment/orders/{order['order_no']}/status", headers=auth
    )
    entitlements = status.json()["entitlements"]
    assert entitlements["membership_active"] is True
    assert entitlements["unlimited_pipeline"] is True
    assert entitlements["model_tier"] == "pro"


@pytest.mark.asyncio
async def test_user_cannot_read_another_users_order(billing_client):
    _, owner_auth = await _account(billing_client, "13500135000")
    _, other_auth = await _account(billing_client, "13400134000")
    order = await _order(billing_client, owner_auth, "monthly_all")
    response = await billing_client.get(
        f"/api/v1/payment/orders/{order['order_no']}/status", headers=other_auth
    )
    assert response.status_code == 404


def test_real_alipay_rsa2_signature_verification(monkeypatch):
    from alipay import AliPay
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    monkeypatch.setattr(settings, "ALIPAY_APP_ID", "app-rsa")
    monkeypatch.setattr(settings, "ALIPAY_PRIVATE_KEY", private_pem)
    monkeypatch.setattr(settings, "ALIPAY_PUBLIC_KEY", public_pem)

    signer = AliPay(
        appid="app-rsa",
        app_private_key_string=private_pem,
        alipay_public_key_string=public_pem,
        sign_type="RSA2",
    )
    data = {
        "app_id": "app-rsa",
        "out_trade_no": "SM-RSA-1",
        "trade_status": "TRADE_SUCCESS",
        "total_amount": "4.99",
    }
    signed = {
        key: values[0]
        for key, values in parse_qs(signer.sign_data(data)).items()
    }
    signed["sign_type"] = "RSA2"
    assert AlipayGateway().verify_notification(signed) is True
    signed["total_amount"] = "0.01"
    assert AlipayGateway().verify_notification(signed) is False


def test_alipay_production_configuration_is_validated_before_startup(monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    monkeypatch.setattr(settings, "ALIPAY_APP_ID", "app-rsa")
    monkeypatch.setattr(settings, "ALIPAY_SELLER_ID", "seller-rsa")
    monkeypatch.setattr(settings, "ALIPAY_PRIVATE_KEY", private_pem)
    monkeypatch.setattr(settings, "ALIPAY_PUBLIC_KEY", public_pem)
    monkeypatch.setattr(
        settings,
        "ALIPAY_NOTIFY_URL",
        "https://example.com/api/v1/payment/alipay/notify",
    )
    monkeypatch.setattr(settings, "ALIPAY_RETURN_URL", "https://example.com/#payment")
    monkeypatch.setattr(settings, "ALIPAY_SANDBOX", False)

    status = validate_alipay_configuration()
    assert status == {
        "provider": "alipay",
        "mode": "production",
        "rsa_bits": 2048,
        "notify_https": True,
        "return_https": True,
    }

    monkeypatch.setattr(settings, "ALIPAY_PRIVATE_KEY", "invalid-key")
    with pytest.raises(PaymentConfigurationError, match="RSA2"):
        validate_alipay_configuration()


def test_real_wechat_api_v3_signature_and_aesgcm_decryption(monkeypatch):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    platform_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = platform_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    api_v3_key = "0123456789abcdef0123456789abcdef"
    monkeypatch.setattr(settings, "WECHAT_PAY_APP_ID", "wx-app")
    monkeypatch.setattr(settings, "WECHAT_PAY_MCH_ID", "wx-mch")
    monkeypatch.setattr(settings, "WECHAT_PAY_PRIVATE_KEY", "configured")
    monkeypatch.setattr(settings, "WECHAT_PAY_CERT_SERIAL_NO", "serial")
    monkeypatch.setattr(settings, "WECHAT_PAY_APIV3_KEY", api_v3_key)
    monkeypatch.setattr(settings, "WECHAT_PAY_PLATFORM_PUBLIC_KEY", public_pem)

    transaction = {
        "out_trade_no": "SM-WX-1",
        "transaction_id": "WX-TX-1",
        "trade_state": "SUCCESS",
        "amount": {"total": 5990, "currency": "CNY"},
    }
    resource_nonce = b"123456789012"
    associated_data = b"transaction"
    ciphertext = AESGCM(api_v3_key.encode()).encrypt(
        resource_nonce,
        json.dumps(transaction, separators=(",", ":")).encode(),
        associated_data,
    )
    body = json.dumps(
        {
            "event_type": "TRANSACTION.SUCCESS",
            "resource": {
                "nonce": resource_nonce.decode(),
                "associated_data": associated_data.decode(),
                "ciphertext": base64.b64encode(ciphertext).decode(),
            },
        },
        separators=(",", ":"),
    ).encode()
    timestamp = str(int(time.time()))
    nonce = "callback-nonce"
    signature = platform_key.sign(
        f"{timestamp}\n{nonce}\n{body.decode()}\n".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    result = WeChatGateway().verify_and_decrypt(
        body,
        {
            "wechatpay-timestamp": timestamp,
            "wechatpay-nonce": nonce,
            "wechatpay-signature": base64.b64encode(signature).decode(),
        },
    )
    assert result["transaction"] == transaction

    with pytest.raises(PaymentProviderError):
        WeChatGateway().verify_and_decrypt(
            body + b" ",
            {
                "wechatpay-timestamp": timestamp,
                "wechatpay-nonce": nonce,
                "wechatpay-signature": base64.b64encode(signature).decode(),
            },
        )
