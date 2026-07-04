"""TLS fingerprint impersonation using curl_cffi.

Provides Chrome 120/124 TLS handshake impersonation so CNKI's anti-bot
system cannot detect the request as automated via JA3/JA4 fingerprinting.

curl_cffi impersonates the full TLS handshake: cipher suites, extensions,
elliptic curves, and HTTP/2 settings — all matching real Chrome.
"""

from __future__ import annotations

import structlog
import random
from typing import Optional

from curl_cffi.requests import AsyncSession, Response

from config.settings import settings

logger = structlog.get_logger()

# 统一使用 config/settings.py 中的 settings.TLS_FINGERPRINT_POOL


class TLSClient:
    """Async HTTP client with Chrome TLS fingerprint impersonation.

    Unlike aiohttp/httpx (which have distinctive Python TLS fingerprints),
    this client's JA3/JA4 hash matches real Chrome browsers.
    """

    def __init__(
        self,
        impersonate: str = "chrome124",
        proxy_url: Optional[str] = None,
        timeout: int = 30,
    ):
        self._impersonate = impersonate
        self._proxy_url = proxy_url
        self._timeout = timeout
        self._session: Optional[AsyncSession] = None
        self._session_used_count = 0
        self._max_session_uses = 50  # Rotate session periodically

    @property
    def impersonate(self) -> str:
        return self._impersonate

    async def _get_session(self) -> AsyncSession:
        """Get or create a TLS-aware AsyncSession."""
        if self._session is None or self._session_used_count >= self._max_session_uses:
            if self._session is not None:
                try:
                    await self._session.close()
                except Exception:
                    pass

            self._session = AsyncSession(
                impersonate=self._impersonate,
                proxy=self._proxy_url,
                timeout=self._timeout,
                verify=True,
            )
            self._session_used_count = 0
            logger.debug(
                "tls_session_created",
                impersonate=self._impersonate,
                proxy=bool(self._proxy_url),
            )

        self._session_used_count += 1
        return self._session

    async def get(
        self,
        url: str,
        headers: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> Response:
        """GET request with TLS impersonation."""
        session = await self._get_session()
        logger.debug("tls_get", url=url[:80])
        return await session.get(url, headers=headers, params=params)

    async def post(
        self,
        url: str,
        data: Optional[dict] = None,
        json: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Response:
        """POST request with TLS impersonation."""
        session = await self._get_session()
        logger.debug("tls_post", url=url[:80])
        return await session.post(url, data=data, json=json, headers=headers)

    def rotate_impersonate(self) -> str:
        """Rotate to next TLS fingerprint after a block is detected."""
        current = self._impersonate
        others = [t for t in settings.TLS_FINGERPRINT_POOL if t != current]
        self._impersonate = random.choice(others)
        self._session = None  # Force recreation with new fingerprint
        self._session_used_count = 0
        logger.info(
            "tls_impersonate_rotated",
            from_fingerprint=current,
            to_fingerprint=self._impersonate,
        )
        return self._impersonate

    @property
    def cookies(self) -> dict:
        """Access the underlying session's cookie jar."""
        return self._session.cookies if self._session else {}

    async def close(self) -> None:
        """Close the underlying session."""
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None
            self._session_used_count = 0
