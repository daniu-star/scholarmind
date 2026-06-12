"""
ScholarMind 请求日志中间件
记录每个请求的 method/path/status/duration
"""
from __future__ import annotations

import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class LoggingMiddleware(BaseHTTPMiddleware):
    """请求/响应日志中间件

    记录字段：method, path, status_code, duration_ms, request_id
    """

    def __init__(self, app, log_body: bool = False):
        super().__init__(app)
        self.log_body = log_body

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.monotonic()

        response = await call_next(request)

        duration_ms = round((time.monotonic() - start_time) * 1000, 2)
        request_id = getattr(request.state, "request_id", "-")

        try:
            import structlog
            logger = structlog.get_logger("scholarmind.access")
            logger.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
                request_id=request_id,
            )
        except ImportError:
            # 回退到标准 logging
            import logging
            logger = logging.getLogger("scholarmind.access")
            logger.info(
                f"[{request_id}] {request.method} {request.url.path} "
                f"{response.status_code} ({duration_ms}ms)"
            )

        return response