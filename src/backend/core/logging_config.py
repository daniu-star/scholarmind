"""
ScholarMind 结构化日志配置
使用 structlog 输出 JSON 格式，支持上下文绑定
"""
import logging
import sys

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

    # 设置根日志级别
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )

    # 降低第三方库日志级别
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str = __name__):
    """获取结构化日志记录器"""
    return structlog.get_logger(name)