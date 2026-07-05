"""
ScholarMind 结构化日志配置
使用 structlog 输出 JSON 格式，支持上下文绑定

P1 Task 14：增加 RotatingFileHandler 落盘到 logs/app.log，
与 stdout stream handler 并列，便于线上排查与日志归档。
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog


def configure_logging():
    """配置 structlog 结构化日志"""
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if sys.stdout.isatty():
        # 控制台环境：彩色输出
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        # 生产环境：JSON 输出
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.NOTSET),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # 适配标准 Python logging
    structlog.get_logger()

    # P1 Task 14：RotatingFileHandler 落盘到 logs/app.log
    # logs/ 目录由 core/events.py startup 提前创建（configure_logging 调用前）
    log_file_path = Path("logs") / "app.log"
    file_handler = RotatingFileHandler(
        str(log_file_path),
        maxBytes=100 * 1024 * 1024,  # 100MB
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter("%(message)s"))

    # 设置根日志级别：stdout + 文件落盘并列
    # 注意：Python 3.14 起 basicConfig 不允许同时传 stream 和 handlers，
    # 这里只通过 handlers 列表同时挂载 stdout 与文件 handler。
    logging.basicConfig(
        format="%(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout), file_handler],
    )

    # 降低第三方库日志级别
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str = __name__):
    """获取结构化日志记录器"""
    return structlog.get_logger(name)