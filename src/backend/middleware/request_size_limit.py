"""研究域请求体大小限制中间件（FR-03）。

背景：`FastAPI(request_body_max_size=...)` 在 FastAPI 0.136.3 中并不是合法参数
（`inspect.signature(FastAPI.__init__)` 无此项，实测被静默忽略），导致「整段请求体
上限 22MiB」从未真正生效（见 docs/reports/R0_VERIFICATION.md 偏差 ③）。

本中间件只对研究域路径生效，保持既有端点的行为不变：

1. `Content-Length` 已知且超过上限 → 直接 413，错误体外壳与 `ResearchAPIError`
   完全一致（`{"error": {"code", "message", "details", "retryable", "request_id"}}`），
   前端可复用同一套错误解析；
2. 分块传输（无 `Content-Length`）→ 不整段缓冲，逐块计数，超限即停止接收并 413；
   单文件 20MiB 的精确校验仍由 `document_service` 在流式读取时执行；
3. 响应已开始发送后不再改写状态码（避免 "response already started"），此时只记录日志。

刻意不覆盖全站：非研究域端点的历史宽容行为不在本任务范围内，贸然收紧属于未评审
的行为变更。
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Iterable, Optional

from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ["RequestSizeLimitMiddleware"]


class _BodyTooLarge(Exception):
    """内部信号：读取请求体时超过上限。"""


def _json_response_body(message: str, max_bytes: int, request_id: Optional[str]) -> bytes:
    error: dict[str, Any] = {
        "code": "FILE_TOO_LARGE",
        "message": message,
        "details": {"max_request_bytes": max_bytes},
        "retryable": False,
    }
    if request_id:
        error["request_id"] = request_id
    return json.dumps({"error": error}, ensure_ascii=False).encode("utf-8")


class RequestSizeLimitMiddleware:
    """对指定路径前缀强制请求体上限的 ASGI 中间件。

    参数
    ----
    app:           下游 ASGI 应用。
    max_bytes:     允许的最大请求体字节数。
    path_prefixes: 生效的路径前缀集合；默认为研究域前缀。
    """

    def __init__(
        self,
        app: ASGIApp,
        max_bytes: int,
        path_prefixes: Iterable[str] = ("/api/v1/research",),
    ) -> None:
        self.app = app
        self.max_bytes = int(max_bytes)
        self.path_prefixes = tuple(path_prefixes)

    # ── 内部工具 ────────────────────────────────────────────────

    def _applies(self, scope: Scope) -> bool:
        if scope.get("type") != "http":
            return False
        path = scope.get("path", "") or ""
        return any(path.startswith(prefix) for prefix in self.path_prefixes)

    @staticmethod
    def _header(scope: Scope, name: bytes) -> Optional[bytes]:
        for key, value in scope.get("headers", ()):
            if key.lower() == name:
                return value
        return None

    @staticmethod
    def _request_id(scope: Scope) -> Optional[str]:
        """取 request_id：优先中间件写入的 state，其次客户端透传的请求头。

        本中间件排在 RequestIDMiddleware 外层（为了在读取请求体之前就能拒绝），
        因此 state 里通常还没有 request_id；此时回落读 `X-Request-ID`，最后才
        生成一个新的 UUIDv4，保证 413 也满足 PRD §8.2「错误体必须带 request_id」。
        """
        state = scope.get("state") or {}
        if isinstance(state, dict) and state.get("request_id"):
            return str(state["request_id"])
        for key, value in scope.get("headers", ()):
            if key.lower() == b"x-request-id" and value:
                return value.decode("latin-1")
        return uuid.uuid4().hex

    async def _send_413(self, send: Send, message: str) -> None:
        request_id = getattr(self, "_current_request_id", None)
        body = _json_response_body(message, self.max_bytes, request_id)
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    # ── ASGI 入口 ──────────────────────────────────────────────

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._applies(scope):
            await self.app(scope, receive, send)
            return

        self._current_request_id = self._request_id(scope)
        limit = self.max_bytes

        # 1) Content-Length 已知：无需读取即可判定
        raw_length = self._header(scope, b"content-length")
        if raw_length is not None:
            try:
                declared = int(raw_length)
            except (TypeError, ValueError):
                declared = -1
            if declared > limit:
                await self._send_413(
                    send,
                    f"请求体超过上限 {limit} 字节，请拆分上传或压缩文件。",
                )
                return

        # 2) 分块/长度缺失：逐块计数，超限即中止
        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"") or b""
                received += len(body)
                if received > limit:
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if response_started:
                # 响应已经开始，无法改写状态码；交由上层连接处理。
                return
            await self._send_413(
                send,
                f"请求体超过上限 {limit} 字节，请拆分上传或压缩文件。",
            )
