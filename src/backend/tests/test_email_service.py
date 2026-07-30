from __future__ import annotations

import asyncio
import time

import pytest

from ..services import email_service


@pytest.mark.asyncio
async def test_delivery_channels_have_one_total_deadline(monkeypatch):
    async def slow_smtp(target: str, code: str) -> None:
        await asyncio.sleep(10)

    async def rejected_vercel(target: str, code: str) -> tuple[bool, str]:
        return False, "HTTP_401"

    monkeypatch.setattr(email_service, "_send_via_smtp", slow_smtp)
    monkeypatch.setattr(email_service, "_send_via_vercel_proxy", rejected_vercel)
    monkeypatch.setattr(email_service.settings, "SMTP_USER", "sender@example.invalid")
    monkeypatch.setattr(email_service.settings, "SMTP_PASSWORD", "configured-secret")
    monkeypatch.setattr(email_service.settings, "VERCEL_EMAIL_PROXY_URL", "https://example.invalid")
    monkeypatch.setattr(email_service.settings, "VERCEL_EMAIL_PROXY_KEY", "configured-key")
    monkeypatch.setattr(email_service.settings, "RESEND_API_KEY", "")
    monkeypatch.setattr(email_service, "_EMAIL_CHANNEL_TIMEOUT_SECONDS", 0.05)
    email_service._channel_health.clear()
    email_service._channel_backoff_until.clear()

    started = time.monotonic()
    with pytest.raises(email_service.EmailSendError):
        await email_service.send_verification_email(
            "recipient@example.invalid", "123456"
        )

    assert time.monotonic() - started < 0.5
    assert email_service._is_channel_backed_off("smtp")
    assert email_service._is_channel_backed_off("vercel")
