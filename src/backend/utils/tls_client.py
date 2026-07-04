"""TLS fingerprint impersonation client for ScholarMind backend.

Mirrors cnki-downloader's TLS client but adapted for the backend's
singleton-via-app.state dependency injection pattern.

Uses curl_cffi to impersonate Chrome 124's TLS handshake signature,
preventing CNKI from detecting automated requests via JA3/JA4 fingerprinting.
"""

from __future__ import annotations

import random
import structlog
from typing import Optional

from curl_cffi.requests import AsyncSession, Response

logger = structlog.get_logger(__name__)

IMPERSONATE_TARGETS = ["chrome124", "chrome120", "chrome123", "chrome121"]


class BackendTLSClient:
    """Async HTTP client with Chrome TLS fingerprint for backend use.

    Unlike the cnki-downloader version, this is designed to be stored
    on app.state and reused across requests.
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
        self._request_count = 0
        self._max_requests_per_session = 30  # Rotate session periodically
        self._cookies: list[dict] = []

    @property
    def impersonate(self) -> str:
        return self._impersonate

    async def _get_session(self) -> AsyncSession:
        if (
            self._session is None
            or self._request_count >= self._max_requests_per_session
        ):
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
            self._request_count = 0

        self._request_count += 1
        return self._session

    async def get(
        self,
        url: str,
        headers: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> Response:
        session = await self._get_session()
        return await session.get(url, headers=headers, params=params)

    async def post(
        self,
        url: str,
        data: Optional[dict] = None,
        json: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Response:
        session = await self._get_session()
        return await session.post(url, data=data, json=json, headers=headers)

    def rotate_impersonate(self) -> str:
        current = self._impersonate
        others = [t for t in IMPERSONATE_TARGETS if t != current]
        self._impersonate = random.choice(others)
        self._session = None
        self._request_count = 0
        logger.info(
            "backend_tls_rotated",
            from_fp=current,
            to_fp=self._impersonate,
        )
        return self._impersonate

    def load_cookies(self, cookies: list[dict]) -> None:
        """Pre-load cookies from a persistence store before making requests."""
        self._cookies = cookies

    @property
    def request_count(self) -> int:
        return self._request_count

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
