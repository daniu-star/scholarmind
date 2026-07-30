"""支付宝当面/网页支付与微信支付 API v3 适配器。

密钥配置既可直接填写 PEM，也可填写 PEM 文件的绝对路径。模块采用可选导入，
未安装支付依赖或未配置商户凭证时不会影响应用启动，而是在创建订单时返回明确
的配置错误。
"""
from __future__ import annotations

import base64
import json
import secrets
import time
from pathlib import Path

import httpx

from ..config import settings

# ── 可选依赖 detect ──
try:
    from alipay import AliPay  # noqa: F401
    _HAS_ALIPAY = True
except ImportError:
    _HAS_ALIPAY = False

try:
    from cryptography.hazmat.primitives import hashes, serialization  # noqa: F401
    from cryptography.hazmat.primitives.asymmetric import padding  # noqa: F401
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False


class PaymentConfigurationError(RuntimeError):
    pass


class PaymentProviderError(RuntimeError):
    pass


def validate_alipay_configuration() -> dict[str, object]:
    """Validate Alipay credentials and RSA2 signing without a network request."""
    required = {
        "ALIPAY_APP_ID": settings.ALIPAY_APP_ID,
        "ALIPAY_PRIVATE_KEY": settings.ALIPAY_PRIVATE_KEY,
        "ALIPAY_PUBLIC_KEY": settings.ALIPAY_PUBLIC_KEY,
        "ALIPAY_SELLER_ID": settings.ALIPAY_SELLER_ID,
        "ALIPAY_NOTIFY_URL": settings.ALIPAY_NOTIFY_URL,
        "ALIPAY_RETURN_URL": settings.ALIPAY_RETURN_URL,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise PaymentConfigurationError(f"支付宝配置不完整：{', '.join(missing)}")
    if not settings.ALIPAY_NOTIFY_URL.startswith("https://"):
        raise PaymentConfigurationError("支付宝异步回调地址必须使用 HTTPS")
    if not settings.ALIPAY_RETURN_URL.startswith("https://"):
        raise PaymentConfigurationError("支付宝同步返回地址必须使用 HTTPS")
    if not _HAS_ALIPAY:
        raise PaymentConfigurationError("缺少 python-alipay-sdk")

    try:
        try:
            from Crypto.PublicKey import RSA
        except ImportError:
            from Cryptodome.PublicKey import RSA

        private_key = RSA.import_key(_load_secret(settings.ALIPAY_PRIVATE_KEY))
        public_key = RSA.import_key(_load_secret(settings.ALIPAY_PUBLIC_KEY))
    except Exception as exc:
        raise PaymentConfigurationError("支付宝 RSA2 密钥格式无效") from exc

    if not private_key.has_private() or private_key.size_in_bits() < 2048:
        raise PaymentConfigurationError("支付宝应用私钥必须是至少 2048 位的 RSA 私钥")
    if public_key.has_private() or public_key.size_in_bits() < 2048:
        raise PaymentConfigurationError("支付宝公钥必须是至少 2048 位的 RSA 公钥")

    try:
        order_string = AlipayGateway()._client().api_alipay_trade_page_pay(
            out_trade_no="CONFIGURATIONCHECK000000000001",
            total_amount="0.01",
            subject="ScholarMind configuration check",
            return_url=settings.ALIPAY_RETURN_URL,
            notify_url=settings.ALIPAY_NOTIFY_URL,
        )
    except Exception as exc:
        raise PaymentConfigurationError("支付宝 RSA2 签名初始化失败") from exc
    if "sign=" not in order_string:
        raise PaymentConfigurationError("支付宝 RSA2 签名生成失败")

    return {
        "provider": "alipay",
        "mode": "sandbox" if settings.ALIPAY_SANDBOX else "production",
        "rsa_bits": private_key.size_in_bits(),
        "notify_https": True,
        "return_https": True,
    }


def _load_secret(value: str) -> str:
    """加载密钥/证书，自动处理多种格式。

    支持的格式：
    1. 空字符串 — 返回空字符串
    2. 文件路径 — 如果字符串是存在的文件路径，读出内容
    3. PEM 格式（含 -----BEGIN ...----- 头尾）— 直接返回
    4. 裸 base64（无 PEM 头尾、无换行）— 自动补全 PEM 头尾
    """
    value = (value or "").strip()
    if not value:
        return ""

    # 有时密钥存储为文件路径（优先检测，路径通常含目录分隔符）
    path = Path(value)
    if "-----BEGIN" not in value and path.is_file():
        return path.read_text(encoding="utf-8").strip()

    # 修复被 .env / dotenv 转义的换行符
    value = value.replace("\\n", "\n").strip()

    # 已经有 PEM 头尾 → 直接返回
    if "-----BEGIN" in value:
        return value

    # 裸 base64 密钥（无 PEM 头尾、无真实换行、不是已有文件）→ 自动补全 PEM 头尾
    # 注意：base64 可含 / + = 字符，不能用 / 来区分文件路径
    if "\n" not in value:
        # 尝试通过 base64 前缀判断密钥类型
        # PKCS#1 私钥 DER 以 0x30 0x82 → base64 "MII" 开头
        if value.startswith("MII"):
            wrapped = (
                "-----BEGIN RSA PRIVATE KEY-----\n"
                + "\n".join(value[i:i + 64] for i in range(0, len(value), 64))
                + "\n-----END RSA PRIVATE KEY-----"
            )
            return wrapped
        # 公钥 SPKI DER 通常较短，以 MIGf / MIIB 开头；统一用 PUBLIC KEY 包裹
        wrapped = (
            "-----BEGIN PUBLIC KEY-----\n"
            + "\n".join(value[i:i + 64] for i in range(0, len(value), 64))
            + "\n-----END PUBLIC KEY-----"
        )
        return wrapped

    return value


class AlipayGateway:
    def _client(self):
        if not all(
            [
                settings.ALIPAY_APP_ID,
                settings.ALIPAY_PRIVATE_KEY,
                settings.ALIPAY_PUBLIC_KEY,
            ]
        ):
            raise PaymentConfigurationError("支付宝商户凭证未完整配置")
        if not _HAS_ALIPAY:
            raise PaymentConfigurationError(
                "缺少 python-alipay-sdk，请先安装后端依赖"
            )
        return AliPay(
            appid=settings.ALIPAY_APP_ID,
            app_notify_url=settings.ALIPAY_NOTIFY_URL,
            app_private_key_string=_load_secret(settings.ALIPAY_PRIVATE_KEY),
            alipay_public_key_string=_load_secret(settings.ALIPAY_PUBLIC_KEY),
            sign_type="RSA2",
            debug=settings.ALIPAY_SANDBOX,
        )

    async def create_payment(
        self, order_no: str, amount_cents: int, subject: str
    ) -> str:
        try:
            client = self._client()
        except PaymentConfigurationError:
            raise
        except Exception as exc:
            raise PaymentConfigurationError(
                f"支付宝客户端初始化失败（请检查密钥格式）: {exc}"
            ) from exc
        order_string = client.api_alipay_trade_page_pay(
            out_trade_no=order_no,
            total_amount=f"{amount_cents / 100:.2f}",
            subject=subject,
            return_url=settings.ALIPAY_RETURN_URL,
            notify_url=settings.ALIPAY_NOTIFY_URL,
        )
        gateway = (
            "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
            if settings.ALIPAY_SANDBOX
            else "https://openapi.alipay.com/gateway.do"
        )
        return f"{gateway}?{order_string}"

    async def query_payment(self, order_no: str) -> dict | None:
        """主动查询支付宝订单状态（alipay.trade.query）。

        用于回调丢失时的兜底轮询。返回 None 表示查询失败（非终态），
        返回 dict 包含 trade_no / trade_status / total_amount 等字段。
        """
        try:
            client = self._client()
        except PaymentConfigurationError:
            raise
        except Exception as exc:
            raise PaymentProviderError(f"支付宝客户端初始化失败: {exc}") from exc
        try:
            result = client.api_alipay_trade_query(out_trade_no=order_no)
        except Exception as e:
            raise PaymentProviderError(f"支付宝订单查询失败: {e}") from e

        code = result.get("code", "")
        if code != "10000":
            return None
        trade_status = result.get("trade_status", "")
        return {
            "order_no": order_no,
            "trade_no": result.get("trade_no"),
            "trade_status": trade_status,
            "total_amount": result.get("total_amount"),
            "buyer_logon_id": result.get("buyer_logon_id"),
            "is_paid": trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED"),
        }

    def verify_notification(self, data: dict) -> bool:
        try:
            client = self._client()
        except PaymentConfigurationError:
            return False
        signature = data.get("sign", "")
        unsigned = {key: value for key, value in data.items() if key not in {"sign", "sign_type"}}
        try:
            return bool(client.verify(unsigned, signature))
        except Exception:
            return False


class WeChatGateway:
    api_base = "https://api.mch.weixin.qq.com"

    def _validate_config(self) -> None:
        required = {
            "WECHAT_PAY_APP_ID": settings.WECHAT_PAY_APP_ID,
            "WECHAT_PAY_MCH_ID": settings.WECHAT_PAY_MCH_ID,
            "WECHAT_PAY_PRIVATE_KEY": settings.WECHAT_PAY_PRIVATE_KEY,
            "WECHAT_PAY_CERT_SERIAL_NO": settings.WECHAT_PAY_CERT_SERIAL_NO,
            "WECHAT_PAY_APIV3_KEY": settings.WECHAT_PAY_APIV3_KEY,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise PaymentConfigurationError(
                f"微信支付商户凭证未完整配置：{', '.join(missing)}"
            )

    @staticmethod
    def _crypto():
        if not _HAS_CRYPTO:
            raise PaymentConfigurationError(
                "缺少 cryptography，无法签名或验签微信支付 API v3"
            )
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return hashes, serialization, padding, AESGCM

    def _sign(self, message: str) -> str:
        _, serialization, padding, _ = self._crypto()
        from cryptography.hazmat.primitives import hashes

        key = serialization.load_pem_private_key(
            _load_secret(settings.WECHAT_PAY_PRIVATE_KEY).encode(), password=None
        )
        signature = key.sign(
            message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256()
        )
        return base64.b64encode(signature).decode()

    def _authorization(self, method: str, path_and_query: str, body: str) -> str:
        timestamp = str(int(time.time()))
        nonce = secrets.token_hex(16)
        message = f"{method}\n{path_and_query}\n{timestamp}\n{nonce}\n{body}\n"
        signature = self._sign(message)
        return (
            'WECHATPAY2-SHA256-RSA2048 '
            f'mchid="{settings.WECHAT_PAY_MCH_ID}",'
            f'nonce_str="{nonce}",'
            f'signature="{signature}",'
            f'timestamp="{timestamp}",'
            f'serial_no="{settings.WECHAT_PAY_CERT_SERIAL_NO}"'
        )

    async def create_payment(
        self, order_no: str, amount_cents: int, subject: str
    ) -> str:
        self._validate_config()
        path = "/v3/pay/transactions/native"
        payload = {
            "appid": settings.WECHAT_PAY_APP_ID,
            "mchid": settings.WECHAT_PAY_MCH_ID,
            "description": subject[:127],
            "out_trade_no": order_no,
            "notify_url": settings.WECHAT_PAY_NOTIFY_URL,
            "amount": {"total": amount_cents, "currency": "CNY"},
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        headers = {
            "Authorization": self._authorization("POST", path, body),
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "ScholarMind/1.0",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{self.api_base}{path}", content=body.encode(), headers=headers)
        if response.status_code != 200:
            raise PaymentProviderError(
                f"微信支付下单失败 ({response.status_code})：{response.text[:300]}"
            )
        try:
            data = response.json()
        except Exception as exc:
            raise PaymentProviderError(
                f"微信支付响应解析失败：{exc}"
            ) from exc
        code_url = data.get("code_url")
        if not code_url:
            raise PaymentProviderError("微信支付响应缺少 code_url")
        return code_url

    async def query_payment(self, order_no: str) -> dict | None:
        """主动查询微信支付订单状态（GET /v3/pay/transactions/out-trade-no/{out_trade_no}）。

        用于回调丢失时的兜底轮询。
        """
        self._validate_config()
        path = f"/v3/pay/transactions/out-trade-no/{order_no}"
        query = f"?mchid={settings.WECHAT_PAY_MCH_ID}"
        full_path = path + query
        body = ""
        headers = {
            "Authorization": self._authorization("GET", full_path, body),
            "Accept": "application/json",
            "User-Agent": "ScholarMind/1.0",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{self.api_base}{full_path}", headers=headers)
        if response.status_code != 200:
            return None
        try:
            data = response.json()
        except Exception:
            return None
        trade_state = data.get("trade_state", "")
        amount_info = data.get("amount") or {}
        return {
            "order_no": order_no,
            "trade_no": data.get("transaction_id"),
            "trade_state": trade_state,
            "total_amount": amount_info.get("total"),
            "is_paid": trade_state == "SUCCESS",
        }

    def verify_and_decrypt(self, body: bytes, headers: dict) -> dict:
        self._validate_config()
        timestamp = headers.get("wechatpay-timestamp", "")
        nonce = headers.get("wechatpay-nonce", "")
        signature = headers.get("wechatpay-signature", "")
        if not timestamp or not nonce or not signature:
            raise PaymentProviderError("微信支付回调缺少验签请求头")
        try:
            if abs(int(time.time()) - int(timestamp)) > 300:
                raise PaymentProviderError("微信支付回调时间戳已过期")
        except ValueError as exc:
            raise PaymentProviderError("微信支付回调时间戳无效") from exc

        public_key_value = (
            settings.WECHAT_PAY_PLATFORM_PUBLIC_KEY
            or settings.WECHAT_PAY_PLATFORM_CERT
        )
        if not public_key_value:
            raise PaymentConfigurationError("未配置微信支付平台公钥或平台证书")
        hashes, serialization, padding, AESGCM = self._crypto()
        pem = _load_secret(public_key_value).encode()
        try:
            public_key = serialization.load_pem_public_key(pem)
        except ValueError:
            from cryptography import x509

            public_key = x509.load_pem_x509_certificate(pem).public_key()
        message = f"{timestamp}\n{nonce}\n{body.decode('utf-8')}\n"
        try:
            public_key.verify(
                base64.b64decode(signature),
                message.encode(),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except Exception as exc:
            raise PaymentProviderError("微信支付回调签名无效") from exc

        envelope = json.loads(body)
        resource = envelope.get("resource") or {}
        try:
            aes = AESGCM(settings.WECHAT_PAY_APIV3_KEY.encode())
            plaintext = aes.decrypt(
                resource["nonce"].encode(),
                base64.b64decode(resource["ciphertext"]),
                (resource.get("associated_data") or "").encode(),
            )
            transaction = json.loads(plaintext)
        except Exception as exc:
            raise PaymentProviderError("微信支付回调报文解密失败") from exc
        return {"event_type": envelope.get("event_type"), "transaction": transaction}


def gateway_for(method: str):
    """根据支付方式返回对应的支付网关。

    个人收款码模式已移除。所有支付均通过官方 API + 实时回调 + 主动轮询完成。
    """
    if method == "alipay":
        return AlipayGateway()
    if method == "wechat":
        return WeChatGateway()
    raise ValueError(f"unsupported payment method: {method}")
