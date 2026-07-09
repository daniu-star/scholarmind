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
SMTP_SERVERS: dict[str, tuple[str, int]] = {
    "qq.com":       ("smtp.qq.com",       587),
    "vip.qq.com":   ("smtp.qq.com",       587),
    "foxmail.com":  ("smtp.qq.com",       587),
    "163.com":      ("smtp.163.com",      465),
    "126.com":      ("smtp.126.com",      465),
    "yeah.net":     ("smtp.yeah.net",     465),
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


async def _send_via_resend(to_email: str, code: str) -> bool:
    """通过 Resend HTTP API 发送邮件（绕过 Railway SMTP 封锁，走 HTTPS 443）。

    Returns:
        True 表示发送成功，False 表示不可用（未配置 API Key 或发送失败）
    """
    global _last_resend_error
    if not settings.RESEND_API_KEY:
        _last_resend_error = "RESEND_API_KEY not configured"
        return False

    import httpx
    payload = {
        "from": f"{settings.SMTP_FROM_NAME} <onboarding@resend.dev>",
        "to": [to_email],
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
                return True
            _last_resend_error = f"Resend HTTP {resp.status_code}: {resp.text[:200]}"
            logger.warning(f"resend_api_failed status={resp.status_code} body={resp.text[:200]}")
            return False
    except Exception as e:
        _last_resend_error = f"Resend network: {e}"
        logger.warning(f"resend_network_error error={e}")
        return False


def _detect_smtp(email: str) -> tuple[str, int, str]:
    """从发件邮箱域名自动检测 SMTP 服务器、端口和提供商名。

    Returns:
        (host, port, provider_name)
    """
    domain = email.rsplit("@", 1)[-1].lower()
    host, port = SMTP_SERVERS.get(domain, ("smtp.qq.com", 587))
    provider = _PROVIDER_NAMES.get(domain, domain)
    return host, port, provider


async def send_verification_email(target_email: str, code: str) -> None:
    """发送验证码邮件 — 优先 Resend API，回退 SMTP"""

    # 优先尝试 Resend HTTP API（绕过 Railway SMTP 封锁）
    if settings.RESEND_API_KEY:
        if await _send_via_resend(target_email, code):
            return
        # Resend 失败，继续尝试 SMTP

    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        raise EmailSendError(
            "邮件服务未配置。请在 .env 中设置 SMTP_USER（您的邮箱地址）和 SMTP_PASSWORD（邮箱授权码）。\n"
            "示例：SMTP_USER=your@163.com  SMTP_PASSWORD=您的授权码"
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
    # 使用 formataddr 避免 Header 编码导致 QQ 等收件服务器拒收
    msg["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_USER))
    msg["To"] = target_email
    msg["Reply-To"] = settings.SMTP_USER

    _SMTP_TIMEOUT = 10  # 秒，足够完成 SMTP 握手 + 登录 + 发送

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
            f"{provider} 登录失败：用户名或授权码错误。\n请检查 SMTP_USER 和 SMTP_PASSWORD（注意：需要使用邮箱授权码，而非登录密码）。\n原错误：{e}"
        ) from e
    except smtplib.SMTPConnectError as e:
        raise EmailSendError(
            f"无法连接 {provider} 服务器（{host}:{port}）：{e}。\n如持续失败，可在 .env 中手动指定 SMTP_HOST 和 SMTP_PORT。"
        ) from e
    except smtplib.SMTPException as e:
        raise EmailSendError(f"邮件发送失败（{provider}）：{e}") from e
    except OSError as e:
        raise EmailSendError(
            f"无法连接 {provider} 服务器（{host}:{port}）：网络不可达（{e}）。\n请检查网络连接或防火墙设置。"
        ) from e
