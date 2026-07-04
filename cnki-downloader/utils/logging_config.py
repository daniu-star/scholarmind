"""Structured logging configuration."""

from __future__ import annotations

import logging
import structlog
from pathlib import Path

from config.settings import settings


def setup_logging(worker_id: str = "") -> None:
    """Configure structlog with the system's log level and format."""

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # Ensure log directory exists
    log_file = Path(settings.LOG_FILE)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Standard library logging setup — output to both console and file
    logging.basicConfig(
        format="%(message)s",
        level=level,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(str(log_file), encoding="utf-8"),
        ],
    )

    shared_processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.set_exc_info,
    ]

    if worker_id:
        shared_processors.insert(
            0,
            structlog.processors.StackInfoRenderer(),
        )

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logger = structlog.get_logger()
    logger.info("logging_initialized", worker_id=worker_id, level=settings.LOG_LEVEL)


def get_logger(name: str = __name__):
    return structlog.get_logger(name)
