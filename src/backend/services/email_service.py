"""邮箱验证码发送服务 — 支持 QQ/163/126/Gmail/Outlook 等主流邮箱 SMTP

发件服务器根据 SMTP_USER 的邮箱域名自动检测；也支持手动指定 SMTP_HOST/PORT。
连接方式自适应：465 端口用 SMTP_SSL，其他端口用 STARTTLS。

SMTP 发送使用专用线程池（_smtp_executor），避免阻塞默认 asyncio 线程池。
"""

from __future__ import annotations

import asyncio
import structlog
import smtplib
from concurrent.futures import ThreadPoolExecutor
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

from ..config import settings

logger = structlog.get_logger(__name__)

# 专用 SMTP 线程池（独立于 asyncio 默认线程池，避免邮件发送阻塞其他 to_thread 调用）
_smtp_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="smtp-")


def _mask_email(email: str) -> str:
    if "@" not in email:
        return "***"
    local, domain = email.rsplit("@", 1)
    return f"{local[:2]}***@{domain}"

# ── 主流邮箱 SMTP 服务器自动检测表 ──────────────────────────
# 注：Railway 等云平台通常封锁 465 端口出站，统一改用 587（STARTTLS）
SMTP_SERVERS: dict[str, tuple[str, int]] = {
    "qq.com":       ("smtp.qq.com",       587),
    "vip.qq.com":   ("smtp.qq.com",       587),
    "foxmail.com":  ("smtp.qq.com",       587),
    "163.com":      ("smtp.163.com",      587),
    "126.com":      ("smtp.126.com",      587),
    "yeah.net":     ("smtp.yeah.net",     587),
    "gmail.com":    ("smtp.gmail.com",    587),
    "outlook.com":  ("smtp-mail.outlook.com", 587),
    "hotmail.com":  ("smtp-mail.outlook.com", 587),
    "live.com":     ("smtp-mail.outlook.com", 587),
    "sina.com":     ("smtp.sina.com",     465),
    "sina.cn":      ("smtp.sina.com",     465),
    "sohu.com":     ("smtp.sohu.com",     465),
    "aliyun.com":   ("smtp.aliyun.com",   465),
    "icloud.com":   ("smtp.mail.me.com",  587),
    "zoho.com":     ("smtp.zoho.com",     587),
    "proton.me":    ("smtp.proton.me",    587),
    "mail.ru":      ("smtp.mail.ru",      465),
}

_PROVIDER_NAMES: dict[str, str] = {
    "qq.com": "QQ邮箱", "vip.qq.com": "QQ邮箱", "foxmail.com": "Foxmail",
    "163.com": "网易163", "126.com": "网易126", "yeah.net": "网易Yeah",
    "gmail.com": "Gmail", "outlook.com": "Outlook", "hotmail.com": "Outlook",
    "live.com": "Outlook", "sina.com": "新浪邮箱", "sina.cn": "新浪邮箱",
    "sohu.com": "搜狐邮箱", "aliyun.com": "阿里云邮箱",
    "icloud.com": "iCloud", "zoho.com": "Zoho", "proton.me": "ProtonMail",
    "mail.ru": "Mail.ru",
}


class EmailSendError(RuntimeError):
    pass


_last_resend_error: str | None = None


def get_last_resend_error() -> str | None:
    return _last_resend_error


async def _send_via_resend(to_email: str, code: str) -> tuple[bool, str | None]:
    """通过 Resend HTTP API 发送邮件（绕过 Railway SMTP 封锁，走 HTTPS 443）。

    Returns:
        (success, error_message) 元组：
        - (True, None) 表示发送成功
        - (False, "DOMAIN_NOT_VERIFIED") 表示域名未验证，应回退 SMTP
        - (False, "其他错误信息") 表示其他失败
    """
    global _last_resend_error
    if not settings.RESEND_API_KEY:
        _last_resend_error = "RESEND_API_KEY not configured"
        return False, "RESEND_NOT_CONFIGURED"

    import httpx
    # 🔴 P0 修复：移除硬编码的免费模式限制，发送到用户实际邮箱
    # 原代码：send_to = "muc18229499131@gmail.com" 导致所有邮件都发到账户邮箱
    # 修复后：发送到用户填写的实际邮箱地址
    send_to = to_email  # 发送到用户实际邮箱

    # 使用已验证的发件域名（优先使用配置的域名，否则使用 resend.dev）
    from_domain = settings.RESEND_FROM_DOMAIN or "resend.dev"
    from_email = f"{settings.SMTP_FROM_NAME} <noreply@{from_domain}>"

    payload = {
        "from": from_email,
        "to": [send_to],
        "subject": f"[ScholarMind] 验证码：{code}",
        "html": f"""<div style="max-width:480px;margin:0 auto;font-family:Arial,sans-serif;color:#1a1a1a;background:#f0f7f1;border-radius:16px;padding:36px 28px">
<div style="text-align:center;margin-bottom:24px">
<div style="display:inline-block;background:linear-gradient(135deg,#2E7D32,#1B5E20);color:#fff;font-size:28px;font-weight:700;padding:8px 20px;border-radius:10px">ScholarMind</div>
<div style="font-size:13px;color:#6b8e6f;margin-top:8px">智能学术研究助手 · 验证码</div>
</div>
<div style="background:#fff;border-radius:14px;padding:28px 24px;text-align:center">
<div style="font-size:15px;color:#4a5b4c;margin-bottom:18px">您的验证码是</div>
<div style="font-size:42px;font-weight:700;letter-spacing:10px;color:#2E7D32;margin-bottom:18px">{code}</div>
<div style="display:inline-block;background:#f0f7f1;color:#5a8a5e;font-size:12px;padding:6px 14px;border-radius:20px">{settings.VERIFICATION_CODE_EXPIRE_MINUTES} 分钟内有效</div>
</div>
</div>""",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code in (200, 201):
                _last_resend_error = None
                logger.info(f"resend_email_sent to={_mask_email(to_email)}")
                return True, None

            # 检测域名未验证错误（需要回退 SMTP）
            resp_text = resp.text
            if "domain" in resp_text.lower() and ("not verified" in resp_text.lower() or "unverified" in resp_text.lower()):
                _last_resend_error = f"Resend 域名未验证: {resp_text[:200]}"
                logger.warning(f"resend_domain_not_verified to={_mask_email(to_email)}")
                return False, "DOMAIN_NOT_VERIFIED"

            if "free mode" in resp_text.lower() or "restricted" in resp_text.lower():
                _last_resend_error = f"Resend 免费模式限制: {resp_text[:200]}"
                logger.warning(f"resend_free_mode_restricted to={_mask_email(to_email)}")
                return False, "FREE_MODE_RESTRICTED"

            _last_resend_error = f"Resend HTTP {resp.status_code}: {resp_text[:200]}"
            logger.warning(f"resend_api_failed status={resp.status_code} body={resp_text[:200]}")
            return False, f"HTTP_{resp.status_code}"
    except Exception as e:
        _last_resend_error = f"Resend network: {e}"
        logger.warning(f"resend_network_error error={e}")
        return False, "NETWORK_ERROR"


def _detect_smtp(email: str) -> tuple[str, int, str]:
    """从发件邮箱域名自动检测 SMTP 服务器、端口和提供商名。

    Returns:
        (host, port, provider_name)
    """
    domain = email.rsplit("@", 1)[-1].lower()
    host, port = SMTP_SERVERS.get(domain, ("smtp.qq.com", 587))
    provider = _PROVIDER_NAMES.get(domain, domain)
    return host, port, provider


async def _send_via_smtp(target_email: str, code: str) -> None:
    """通过 SMTP 发送验证码邮件（无收件人限制）。

    Raises:
        EmailSendError: SMTP 发送失败时抛出
    """
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        raise EmailSendError(
            "邮件服务未配置。请在 .env 中设置 SMTP_USER 和 SMTP_PASSWORD"
        )

    # 自动检测或使用手动配置
    if settings.SMTP_HOST and settings.SMTP_PORT > 0:
        host, port = settings.SMTP_HOST, settings.SMTP_PORT
        provider = "自定义"
    else:
        host, port, provider = _detect_smtp(settings.SMTP_USER)
        logger.info(f"smtp_auto_detected provider={provider} host={host} port={port}")

    html = f"""\
<div style="max-width:480px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;color:#1a1a1a;background:#f0f7f1;border-radius:16px;padding:36px 28px">
  <div style="text-align:center;margin-bottom:24px">
    <div style="display:inline-block;background:linear-gradient(135deg,#2E7D32,#1B5E20);color:#fff;font-size:28px;font-weight:700;padding:8px 20px;border-radius:10px;letter-spacing:1px">ScholarMind</div>
    <div style="font-size:13px;color:#6b8e6f;margin-top:8px">智能学术研究助手 · 验证码</div>
  </div>
  <div style="background:#fff;border-radius:14px;padding:28px 24px;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,.06)">
    <div style="font-size:15px;color:#4a5b4c;margin-bottom:18px">您的验证码是</div>
    <div style="font-size:42px;font-weight:700;letter-spacing:10px;color:#2E7D32;margin-bottom:18px;font-family:'SF Mono','Consolas','Courier New',monospace">{code}</div>
    <div style="display:inline-block;background:#f0f7f1;color:#5a8a5e;font-size:12px;padding:6px 14px;border-radius:20px;margin-bottom:8px">{settings.VERIFICATION_CODE_EXPIRE_MINUTES} 分钟内有效，请勿泄露</div>
  </div>
  <div style="text-align:center;margin-top:20px;font-size:11px;color:#a0b8a2;line-height:1.6">
    此邮件由 ScholarMind 通过 {provider} 自动发送<br>如非本人操作，请忽略
  </div>
</div>"""

    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = Header(f"[ScholarMind] 验证码：{code}", "utf-8")
    msg["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_USER))
    msg["To"] = target_email
    msg["Reply-To"] = settings.SMTP_USER

    _SMTP_TIMEOUT = 8  # 秒（从 10 降到 8，避免请求总耗时过长）

    def _send_sync():
        # 端口 465 使用 SSL 直连，其他端口使用 STARTTLS
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=_SMTP_TIMEOUT) as server:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=_SMTP_TIMEOUT) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(_smtp_executor, _send_sync)
        logger.info(f"verification_email_sent to={_mask_email(target_email)} via={host}:{port}")
    except smtplib.SMTPAuthenticationError as e:
        raise EmailSendError(
            f"{provider} 登录失败：用户名或授权码错误。请检查 SMTP_USER 和 SMTP_PASSWORD。原错误：{e}"
        ) from e
    except smtplib.SMTPConnectError as e:
        raise EmailSendError(
            f"无法连接 {provider} 服务器（{host}:{port}）：{e}。如持续失败，可在 .env 中手动指定 SMTP_HOST 和 SMTP_PORT。"
        ) from e
    except smtplib.SMTPException as e:
        raise EmailSendError(f"邮件发送失败（{provider}）：{e}") from e
    except OSError as e:
        raise EmailSendError(
            f"无法连接 {provider} 服务器（{host}:{port}）：网络不可达（{e}）。请检查网络连接或防火墙设置。"
        ) from e


async def _send_via_vercel_proxy(target_email: str, code: str) -> tuple[bool, str | None]:
    """通过 Vercel Serverless Function 发送邮件（绕过 Railway SMTP 封锁）。

    Vercel 运行在 AWS Lambda 上，不封锁 SMTP 465/587 端口。
    后端通过 HTTPS 443 调用此函数，函数内部用 nodemailer+SMTP 发送邮件。
    SMTP 凭据从后端 .env 读取，通过 HTTPS 请求体加密传输给 Vercel function。

    Returns:
        (success, error_message) 元组
    """
    global _last_resend_error

    if not settings.VERCEL_EMAIL_PROXY_URL or not settings.VERCEL_EMAIL_PROXY_KEY:
        return False, "VERCEL_EMAIL_PROXY_URL or VERCEL_EMAIL_PROXY_KEY not configured"

    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        return False, "SMTP_USER or SMTP_PASSWORD not configured for Vercel proxy"

    # 解析 SMTP 主机端口 — Vercel 不封锁端口，优先 465（SSL 直连，nodemailer 更可靠）
    if settings.SMTP_HOST and settings.SMTP_PORT > 0:
        smtp_host = settings.SMTP_HOST
        smtp_port = settings.SMTP_PORT
    else:
        smtp_host, smtp_port, _ = _detect_smtp(settings.SMTP_USER)
        # Vercel 不封锁 465，将 587 改为 465 以获得更可靠的 SSL 直连
        if smtp_port == 587:
            smtp_port = 465

    import httpx

    payload = {
        "to_email": target_email,
        "code": code,
        "smtp_host": smtp_host,
        "smtp_port": str(smtp_port),
        "smtp_user": settings.SMTP_USER,
        "smtp_password": settings.SMTP_PASSWORD,
        "smtp_from_name": settings.SMTP_FROM_NAME,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                settings.VERCEL_EMAIL_PROXY_URL,
                json=payload,
                headers={
                    "X-API-Key": settings.VERCEL_EMAIL_PROXY_KEY,
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    logger.info(f"vercel_proxy_email_sent to={_mask_email(target_email)} host={smtp_host}:{smtp_port}")
                    return True, None
                err = data.get("error", "unknown")
                _last_resend_error = f"Vercel proxy: {err}"
                return False, err
            _last_resend_error = f"Vercel proxy HTTP {resp.status_code}: {resp.text[:200]}"
            logger.warning(f"vercel_proxy_failed status={resp.status_code} body={resp.text[:200]}")
            return False, f"HTTP_{resp.status_code}"
    except Exception as e:
        _last_resend_error = f"Vercel proxy network: {e}"
        logger.warning(f"vercel_proxy_network_error error={e}")
        return False, "NETWORK_ERROR"


async def send_verification_email(target_email: str, code: str) -> None:
    """发送验证码邮件 — 优先 SMTP 直连，失败走 Vercel 代理，最后 Resend

    策略：
    1. SMTP 直连（本地开发可用，Railway 不可用因端口封锁）
    2. Vercel Serverless Function 代理（绕过 Railway SMTP 封锁，走 HTTPS 443）
    3. Resend HTTP API（需要域名验证，作为最后兜底）
    """
    # 1. 优先 SMTP 直连
    if settings.SMTP_USER and settings.SMTP_PASSWORD:
        try:
            await _send_via_smtp(target_email, code)
            return
        except EmailSendError as e:
            logger.warning(f"smtp_failed_attempting_vercel_proxy error={e}")

    # 2. SMTP 失败（如 Railway 封锁端口），走 Vercel 代理
    if settings.VERCEL_EMAIL_PROXY_URL and settings.VERCEL_EMAIL_PROXY_KEY:
        success, error = await _send_via_vercel_proxy(target_email, code)
        if success:
            return
        logger.warning(f"vercel_proxy_failed_attempting_resend error={error}")

    # 3. Vercel 代理也失败，尝试 Resend
    if settings.RESEND_API_KEY:
        success, _error_type = await _send_via_resend(target_email, code)
        if success:
            return
        raise EmailSendError(
            f"所有邮件发送方式均失败。SMTP + Vercel代理 + Resend 错误：{get_last_resend_error() or 'unknown'}"
        )

    raise EmailSendError(
        "邮件服务未配置。请设置 SMTP_USER/SMTP_PASSWORD 或 VERCEL_EMAIL_PROXY_URL 或 RESEND_API_KEY"
    )
