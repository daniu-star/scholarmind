"""CAPTCHA solving service — capsolver, 2captcha, and local OCR.

CNKI uses NetEase YiDun with blockPuzzle (slider) CAPTCHA at
kns.cnki.net/verify/home and occasionally text/image CAPTCHAs.

This module provides a pluggable solver architecture with automatic
fallback between providers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import aiohttp

from config.settings import settings

logger = logging.getLogger(__name__)


class CaptchaSolver(ABC):
    """Abstract CAPTCHA solver interface."""

    @abstractmethod
    async def solve_slider(
        self,
        captcha_url: str = "",
        site_key: str = "",
        **kwargs,
    ) -> Optional[dict]:
        """Solve a slider/block puzzle CAPTCHA.

        Returns dict with verification token or cookies, or None on failure.
        """
        ...

    @abstractmethod
    async def solve_text(
        self,
        image_base64: str = "",
        **kwargs,
    ) -> Optional[str]:
        """Solve a text-based CAPTCHA from base64-encoded image.

        Returns recognized text string, or None on failure.
        """
        ...

    @abstractmethod
    async def get_balance(self) -> float:
        """Get remaining account balance."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable solver name."""
        ...


class CapsolverSolver(CaptchaSolver):
    """capsolver.com API integration.

    Capsolver has better support for CNKI/YiDun CAPTCHAs than 2captcha.
    Uses DataDomeSliderTask or HCaptchaTask depending on what CNKI serves.
    """

    name = "capsolver"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.capsolver.com"
        self._poll_interval = 2

    async def solve_slider(
        self,
        captcha_url: str = "",
        site_key: str = "",
        **kwargs,
    ) -> Optional[dict]:
        payload = {
            "clientKey": self.api_key,
            "task": {
                "type": "HCaptchaTaskProxyless",
                "websiteURL": captcha_url or "https://kns.cnki.net",
                "websiteKey": site_key or "",
            },
        }

        try:
            return await self._create_and_poll(payload)
        except Exception as e:
            logger.error("capsolver_slider_error: %s", e)
            return None

    async def solve_text(
        self,
        image_base64: str = "",
        **kwargs,
    ) -> Optional[str]:
        if not image_base64:
            return None

        payload = {
            "clientKey": self.api_key,
            "task": {
                "type": "ImageToTextTask",
                "body": image_base64,
            },
        }

        try:
            result = await self._create_and_poll(payload)
            return result.get("text", "") if result else None
        except Exception as e:
            logger.error("capsolver_text_error: %s", e)
            return None

    async def _create_and_poll(self, payload: dict) -> Optional[dict]:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/createTask",
                json=payload,
            ) as resp:
                data = await resp.json()
                if data.get("errorId") != 0:
                    logger.error(
                        "capsolver_create_failed: %s", data.get("errorDescription")
                    )
                    return None
                task_id = data.get("taskId")

            timeout = settings.CAPTCHA_SOLVER_TIMEOUT
            start = time.time()

            while time.time() - start < timeout:
                await asyncio.sleep(self._poll_interval)
                async with session.post(
                    f"{self.base_url}/getTaskResult",
                    json={"clientKey": self.api_key, "taskId": task_id},
                ) as resp:
                    data = await resp.json()
                    if data.get("status") == "ready":
                        return data.get("solution", {})
                    if data.get("errorId") != 0:
                        logger.error(
                            "capsolver_poll_error: %s", data.get("errorDescription")
                        )
                        return None

            logger.error("capsolver_timeout: task_id=%s", task_id)
            return None

    async def get_balance(self) -> float:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/getBalance",
                    json={"clientKey": self.api_key},
                ) as resp:
                    data = await resp.json()
                    return float(data.get("balance", 0))
        except Exception:
            return -1.0


class TwoCaptchaSolver(CaptchaSolver):
    """2captcha.com API integration."""

    name = "2captcha"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.2captcha.com"

    async def solve_slider(
        self,
        captcha_url: str = "",
        site_key: str = "",
        **kwargs,
    ) -> Optional[dict]:
        from urllib.parse import urlparse, parse_qs

        parsed = urlparse(captcha_url)
        params = parse_qs(parsed.query)
        captcha_id = params.get("captchaId", [""])[0]

        payload = {
            "clientKey": self.api_key,
            "task": {
                "type": "GeeTestTask",
                "websiteURL": "https://kns.cnki.net",
                "gt": captcha_id,
                "challenge": captcha_id,
            },
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/createTask",
                    json=payload,
                ) as resp:
                    data = await resp.json()
                    if data.get("errorId") != 0:
                        logger.error("2captcha_create_failed: %s", data.get("errorDescription"))
                        return None
                    task_id = data.get("taskId")

                for _ in range(60):
                    await asyncio.sleep(2)
                    async with session.post(
                        f"{self.base_url}/getTaskResult",
                        json={"clientKey": self.api_key, "taskId": task_id},
                    ) as resp:
                        data = await resp.json()
                        if data.get("status") == "ready":
                            solution = data.get("solution", {})
                            return {
                                "challenge": solution.get("challenge"),
                                "validate": solution.get("validate"),
                                "seccode": solution.get("seccode"),
                                "token": solution.get("challenge"),
                            }

                logger.error("2captcha_timeout: task_id=%s", task_id)
                return None

        except Exception as e:
            logger.error("2captcha_error: %s", e)
            return None

    async def solve_text(self, image_base64: str = "", **kwargs) -> Optional[str]:
        if not image_base64:
            return None
        payload = {
            "clientKey": self.api_key,
            "task": {
                "type": "ImageToTextTask",
                "body": image_base64,
            },
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/createTask",
                    json=payload,
                ) as resp:
                    data = await resp.json()
                    if data.get("errorId") != 0:
                        return None
                    task_id = data.get("taskId")

                for _ in range(30):
                    await asyncio.sleep(2)
                    async with session.post(
                        f"{self.base_url}/getTaskResult",
                        json={"clientKey": self.api_key, "taskId": task_id},
                    ) as resp:
                        data = await resp.json()
                        if data.get("status") == "ready":
                            return data.get("solution", {}).get("text", "")
                return None
        except Exception:
            return None

    async def get_balance(self) -> float:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.2captcha.com/getBalance?key={self.api_key}"
                ) as resp:
                    data = await resp.json()
                    return float(data.get("balance", 0))
        except Exception:
            return -1.0


class ManualCookieSolver(CaptchaSolver):
    """Manual solver — user solves CAPTCHA in browser, exports cookies."""

    name = "manual"

    def __init__(self, session_dir: str = "./sessions"):
        self.session_dir = session_dir

    async def solve_slider(self, **kwargs) -> Optional[dict]:
        session_path = Path(self.session_dir) / "cnki_verified.json"
        if session_path.exists():
            data = json.loads(session_path.read_text("utf-8"))
            return {"cookies": data.get("cookies", [])}
        logger.info("manual_captcha_no_session")
        return None

    async def solve_text(self, **kwargs) -> Optional[str]:
        return None

    async def get_balance(self) -> float:
        return 0.0

    def save_cookies(self, cookies: list[dict]) -> None:
        session_path = Path(self.session_dir) / "cnki_verified.json"
        session_path.parent.mkdir(parents=True, exist_ok=True)
        session_path.write_text(
            json.dumps(
                {"cookies": cookies, "saved_at": time.time()},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        logger.info("manual_cookies_saved: %d", len(cookies))


class SolverRouter:
    """Routes CAPTCHA solving through multiple solvers with fallback.

    Priority order: manual (cached cookies) -> capsolver -> 2captcha -> local OCR

    Manual cookies are tried first because they're free and instant.
    Online solvers are tried in order of cost/reliability.
    """

    def __init__(self):
        self._solvers: list[CaptchaSolver] = []
        self._init_from_config()

    def _init_from_config(self) -> None:
        # Always add manual solver (zero cost, checks cached cookies)
        self._solvers.append(ManualCookieSolver())

        # Add online solvers if configured
        provider = settings.CAPTCHA_SOLVER_PROVIDER.lower()
        api_key = settings.CAPTCHA_SOLVER_API_KEY

        if api_key:
            if provider == "capsolver":
                self._solvers.append(CapsolverSolver(api_key))
            elif provider == "2captcha":
                self._solvers.append(TwoCaptchaSolver(api_key))
            elif provider == "capsolver":
                self._solvers.append(CapsolverSolver(api_key))
            else:
                logger.warning(
                    "unknown_captcha_provider: %s, adding both as fallback", provider
                )
                self._solvers.append(CapsolverSolver(api_key))
                self._solvers.append(TwoCaptchaSolver(api_key))

    async def solve_slider(self, captcha_url: str = "", site_key: str = "", **kwargs) -> Optional[dict]:
        """Try to solve slider CAPTCHA using all available solvers."""
        for solver in self._solvers:
            try:
                result = await solver.solve_slider(
                    captcha_url=captcha_url, site_key=site_key, **kwargs
                )
                if result:
                    logger.info("captcha_solved_by: %s", solver.name)
                    return result
            except Exception as e:
                logger.warning("solver_failed: %s error=%s", solver.name, e)
                continue

        logger.error("all_solvers_failed_for_slider")
        return None

    async def solve_text(self, image_base64: str = "", **kwargs) -> Optional[str]:
        """Try to solve text CAPTCHA using all available solvers."""
        for solver in self._solvers:
            try:
                result = await solver.solve_text(image_base64=image_base64, **kwargs)
                if result:
                    logger.info("text_captcha_solved_by: %s", solver.name)
                    return result
            except Exception as e:
                logger.warning("text_solver_failed: %s error=%s", solver.name, e)
                continue

        logger.error("all_solvers_failed_for_text")
        return None

    @property
    def solver_names(self) -> list[str]:
        return [s.name for s in self._solvers]


# Global singleton
solver_router = SolverRouter()
