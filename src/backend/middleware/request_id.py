"""
ScholarMind 请求 ID 中间件
为每个请求注入/透传 X-Request-ID
"""
from __future__ import annotations

import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """请求 ID 中间件

    功能：
    1. 从 X-Request-ID 请求头读取（透传）
    2. 不存在则生成 UUID4
    3. 注入到响应头 X-Request-ID
    4. 存储到 request.state.request_id
    """

    HEADER_NAME = "X-Request-ID"

    def __init__(self, app, header_name: str | None = None):
        super().__init__(app)
        if header_name:
            self.HEADER_NAME = header_name

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(self.HEADER_NAME)
        if not request_id:
            request_id = str(uuid.uuid4())

        # 存储到 request.state 供下游使用
        request.state.request_id = request_id

        # 绑定到 structlog 上下文
        try:
            import structlog
            structlog.contextvars.bind_contextvars(request_id=request_id)
        except ImportError:
            pass

        response = await call_next(request)

        # 注入响应头
        response.headers[self.HEADER_NAME] = request_id

        return response