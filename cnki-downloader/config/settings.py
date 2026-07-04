"""Global configuration via Pydantic BaseSettings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration for CNKI downloader system."""

    # ── Redis ──
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Master ──
    MASTER_PORT: int = 8100
    MASTER_HOST: str = "0.0.0.0"

    # ── Worker ──
    DISCIPLINE: str = "新闻传播学"
    THREAD_COUNT: int = 3

    # ── Proxy (Clash for Windows) ──
    PROXY_URL: str = "http://127.0.0.1:7890"
    PROXY_ENABLED: bool = True

    # ── CNKI ──
    CNKI_BASE_URL: str = "https://kns.cnki.net"
    CNKI_NAVI_URL: str = "https://navi.cnki.net/knavi"

    # ── Storage ──
    STORAGE_BASE: str = "../数据库/cnki"

    # ── HuggingFace Models ──
    HF_MODELS_DIR: str = "./models"

    # ── Logging ──
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "./logs/cnki-downloader.log"

    # ── Health Check ──
    HEARTBEAT_INTERVAL: int = 10
    HEARTBEAT_TIMEOUT: int = 30
    TASK_STALL_TIMEOUT: int = 900

    # ── Rate Limiting ──
    DEFAULT_DELAY_MIN: float = 0.5
    DEFAULT_DELAY_MAX: float = 3.0
    SUSPICIOUS_DELAY_MULTIPLIER: float = 2.0
    BLOCKED_COOLDOWN_MINUTES: int = 15

    # ── Retry ──
    MAX_RETRIES_DEFAULT: int = 5
    BASE_DELAY_SECONDS: float = 3.0
    MAX_DELAY_SECONDS: float = 600.0

    # ── Circuit Breaker ──
    CB_FAILURE_THRESHOLD: int = 5
    CB_TIMEOUT_SECONDS: float = 300.0

    # ── Browser ──
    BROWSER_HEADLESS: bool = True
    BROWSER_CONTEXT_POOL_SIZE: int = 3
    BROWSER_MAX_PAGES_PER_CONTEXT: int = 50

    # ── CAPTCHA Solver ──
    CAPTCHA_SOLVER_PROVIDER: str = ""  # "capsolver" | "2captcha" | "" (local only)
    CAPTCHA_SOLVER_API_KEY: str = ""
    CAPTCHA_SOLVER_TIMEOUT: int = 120
    CAPTCHA_MAX_RETRIES_LOCAL: int = 3

    # ── TLS Fingerprint ──
    TLS_IMPERSONATE: str = "chrome124"
    TLS_FINGERPRINT_POOL: list[str] = [
        "chrome124", "chrome120", "chrome123", "chrome121",
        "chrome116", "edge99", "safari17_0",
    ]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


# Global settings instance
settings = Settings()

# Ensure storage path is absolute
_storage_path = Path(settings.STORAGE_BASE)
if not _storage_path.is_absolute():
    _storage_path = Path(__file__).resolve().parent.parent / settings.STORAGE_BASE
STORAGE_BASE_PATH = _storage_path.resolve()
