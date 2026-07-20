"""邮箱验证码发送服务 — 支持 QQ/163/126/Gmail/Outlook 等主流邮箱 SMTP

发件服务器根据 SMTP_USER 的邮箱域名自动检测；也支持手动指定 SMTP_HOST/PORT。
连接方式自适应：465 端口用 SMTP_SSL，其他端口用 STARTTLS。

SMTP 发送使用专用线程池（_smtp_executor），避免阻塞默认 asyncio 线程池。
"""

from __future__ import annotations

import asyncio
import structlog
import smtplib
import time
from concurrent.futures import ThreadPoolExecutor
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

from ..config import settings

logger = structlog.get_logger(__name__)

# 专用 SMTP 线程池（独立于 asyncio 默认线程池，避免邮件发送阻塞其他 to_thread 调用）
_smtp_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="smtp-")

# ── Task 4: 通道健康缓存 ──────────────────────────────────
# 5 分钟内成功过的通道直接复用，避免每次都全通道并发竞速。
# 失败通道不写入缓存；配置变更需重启服务清空缓存。
_channel_health: dict[str, tuple[float, float]] = {}
_HEALTH_TTL = 300.0  # 5 分钟


def _is_channel_healthy(name: str) -> bool:
    rec = _channel_health.get(name)
    if not rec:
        return False
    return (time.monotonic() - rec[0]) < rec[1]


def _mark_channel_healthy(name: str) -> None:
    _channel_health[name] = (time.monotonic(), _HEALTH_TTL)


def _clear_channel_health(name: str) -> None:
    _channel_health.pop(name, None)


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
        async with httpx.AsyncClient(timeout=6.0) as client:
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

    _SMTP_TIMEOUT = 5  # 秒（Task 4: 从 8 降到 5，配合并发竞速缩短整体耗时）

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
        async with httpx.AsyncClient(timeout=6.0) as client:
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


async def _send_via_smtp_safe(target_email: str, code: str) -> None:
    """SMTP 通道包装：统一 asyncio.wait 行为（失败时抛 EmailSendError 而非返回元组）。"""
    await _send_via_smtp(target_email, code)  # 失败时抛 EmailSendError


async def _dispatch_channel(name: str, target_email: str, code: str) -> None:
    """单通道调度（用于健康通道直连路径）。

    不同通道返回类型不一致：
    - SMTP: 成功返回 None，失败抛 EmailSendError
    - Vercel/Resend: 返回 (success: bool, error: str | None) 元组

    本函数统一为"成功返回 None，失败抛 EmailSendError"。
    """
    if name == "smtp":
        await _send_via_smtp(target_email, code)
    elif name == "vercel":
        success, err = await _send_via_vercel_proxy(target_email, code)
        if not success:
            raise EmailSendError(f"Vercel proxy failed: {err}")
    elif name == "resend":
        success, err = await _send_via_resend(target_email, code)
        if not success:
            raise EmailSendError(f"Resend failed: {err}")


async def send_verification_email(target_email: str, code: str) -> None:
    """发送验证码邮件 — 并发竞速 + 健康通道优先。

    策略：
    1. 若有健康通道缓存（5min TTL），直接调用该通道，跳过并发竞速
    2. 否则并发发起所有已配置通道，循环等待任一任务完成：
       - 成功 → cancel 其余任务，返回
       - 失败 → 继续等待下一个任务
       - 全部失败 → 抛 EmailSendError
    3. 成功通道写入健康缓存加速下次发送

    Bug 修复（2026-07）：
    - 旧实现用 `enumerate(done)` + `task_names[i]` 索引，但 `done` 是 set，
      迭代顺序与 tasks 列表顺序不一致，导致任务名误判（如把 resend 失败误判为
      smtp 成功），即使所有通道失败也误报 email_sent:true。
    - 旧实现用 `asyncio.wait(FIRST_COMPLETED)` 在第一个任务完成（无论成败）后
      立即 cancel 所有 pending 任务，导致慢通道（Vercel）没机会成功。
    - 新实现用 `dict[task, name]` 正确映射，循环等待直到有成功或全部失败。

    性能：
    - 健康通道直连：< 2s（无并发开销）
    - 并发竞速：最坏 max(SMTP 5s, Vercel 6s, Resend 6s)，通常 1-3s
    """
    # 1. 健康通道直连
    for name in ("smtp", "vercel", "resend"):
        if _is_channel_healthy(name):
            try:
                await _dispatch_channel(name, target_email, code)
                _mark_channel_healthy(name)  # 刷新 TTL
                logger.info(f"email_sent_via_healthy_channel name={name} to={_mask_email(target_email)}")
                return
            except Exception as e:
                logger.warning(f"healthy_channel_failed name={name} error={e}")
                _clear_channel_health(name)
                # 健康通道失败 → 走并发竞速
                break

    # 2. 并发竞速 — 用 dict[task, name] 正确映射，避免索引错位
    task_to_name: dict[asyncio.Task, str] = {}
    if settings.SMTP_USER and settings.SMTP_PASSWORD:
        t = asyncio.create_task(_send_via_smtp_safe(target_email, code))
        task_to_name[t] = "smtp"
    if settings.VERCEL_EMAIL_PROXY_URL and settings.VERCEL_EMAIL_PROXY_KEY:
        t = asyncio.create_task(_send_via_vercel_proxy(target_email, code))
        task_to_name[t] = "vercel"
    if settings.RESEND_API_KEY:
        t = asyncio.create_task(_send_via_resend(target_email, code))
        task_to_name[t] = "resend"

    if not task_to_name:
        raise EmailSendError(
            "邮件服务未配置。请设置 SMTP_USER/SMTP_PASSWORD 或 VERCEL_EMAIL_PROXY_URL 或 RESEND_API_KEY"
        )

    # 循环等待：直到有任务成功，或所有任务都完成（失败）
    pending: set[asyncio.Task] = set(task_to_name.keys())
    first_success_name: str | None = None
    errors: list[str] = []

    while pending and first_success_name is None:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            name = task_to_name[t]  # 正确映射：从 dict 查询，不依赖迭代顺序
            try:
                result = t.result()
                if name == "smtp":
                    # _send_via_smtp_safe 成功返回 None，失败已抛异常（被 except 捕获）
                    first_success_name = name
                    break
                else:
                    # Vercel/Resend 返回 (success, error) 元组
                    success, err = result
                    if success:
                        first_success_name = name
                        break
                    errors.append(f"{name}: {err}")
            except Exception as e:
                errors.append(f"{name}: {e}")

    # 取消所有尚未完成的任务（有成功通道时，其他通道无需继续）
    for t in pending:
        t.cancel()

    if first_success_name:
        _mark_channel_healthy(first_success_name)
        logger.info(
            f"email_sent_winning_channel={first_success_name} to={_mask_email(target_email)}"
        )
        return

    # 全部失败
    raise EmailSendError(
        f"所有邮件发送方式均失败：{'; '.join(errors)}。最后 Resend 错误：{get_last_resend_error() or 'unknown'}"
    )
