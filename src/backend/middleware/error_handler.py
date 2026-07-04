"""
ScholarMind 统一异常处理
注册异常处理器，返回统一 JSON 错误响应格式：
  {"success": false, "error": {"code": "...", "message": "...", "details": {...}}}
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from ..core.exceptions import AppException
from ..core.logging_config import get_logger
from ..models.error_codes import ErrorCode

logger = get_logger(__name__)


def error_response(
    code: ErrorCode,
    message: str,
    status_code: int,
    details: dict | None = None,
    request_id: str | None = None,
) -> dict:
    """构建统一错误响应"""
    resp: dict = {
        "success": False,
        "error": {
            "code": code.value,
            "message": message,
        },
    }
    if details:
        resp["error"]["details"] = details
    if request_id:
        resp["error"]["request_id"] = request_id
    return resp


def register_error_handlers(app: FastAPI) -> None:
    """注册统一异常处理器到 FastAPI 应用"""

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        """处理自定义应用异常（使用 to_response 格式）"""
        request_id = getattr(request.state, "request_id", None)
        logger.warning(
            f"AppException: [{exc.code.value}] {exc.message}",
            extra={"request_id": request_id},
        )
        body = exc.to_response()
        if request_id:
            body["error"]["request_id"] = request_id
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        """处理 Pydantic 请求验证错误"""
        request_id = getattr(request.state, "request_id", None)
        errors = []
        for error in exc.errors():
            field = ".".join(str(loc) for loc in error["loc"])
            msg = error["msg"]
            errors.append(f"{field}: {msg}")

        return JSONResponse(
            status_code=422,
            content=error_response(
                code=ErrorCode.VALIDATION_ERROR,
                message="; ".join(errors),
                status_code=422,
                details={"fields": errors},
                request_id=request_id,
            ),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """处理标准 HTTP 异常（转换为统一格式）"""
        request_id = getattr(request.state, "request_id", None)

        # 映射 HTTP 状态码到错误码
        code_map = {
            404: ErrorCode.NOT_FOUND,
            400: ErrorCode.VALIDATION_ERROR,
            401: ErrorCode.AUTHENTICATION_FAILED,
            403: ErrorCode.PERMISSION_DENIED,
            429: ErrorCode.RATE_LIMITED,
            402: ErrorCode.PAYMENT_REQUIRED,
        }
        code = code_map.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        message = str(exc.detail)
        details = None
        if isinstance(exc.detail, dict):
            requested_code = exc.detail.get("code")
            if requested_code in ErrorCode._value2member_map_:
                code = ErrorCode(requested_code)
            message = exc.detail.get("message", message)
            details = {
                key: value
                for key, value in exc.detail.items()
                if key not in {"code", "message"}
            } or None

        return JSONResponse(
            status_code=exc.status_code,
            content=error_response(
                code=code,
                message=message,
                status_code=exc.status_code,
                details=details,
                request_id=request_id,
            ),
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """处理未捕获的通用异常（含 asyncio.CancelledError 降级）"""
        request_id = getattr(request.state, "request_id", None)
        # CancelledError 是 BaseException 子类，不会被此 handler 捕获
        # 但某些框架包装后可能变为 Exception，需做类型检查
        import asyncio as _asyncio
        if isinstance(exc, _asyncio.CancelledError):
            logger.debug(f"Request cancelled by client request_id={request_id}")
            # P1 Task 10：客户端断开时返回 499 而非触发 500（原 return 不返回 Response
            # 会导致 Starlette 抛 RuntimeError:Caught handled exception）
            return PlainTextResponse("client disconnected", status_code=499)
        logger.exception(
            f"Unhandled exception: {exc} request_id={request_id}"
        )
        from ...config import settings
        is_dev = settings.DEBUG
        details = {
            "type": type(exc).__name__,
            "message": str(exc),
        } if is_dev else {"type": type(exc).__name__}
        return JSONResponse(
            status_code=500,
            content=error_response(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"服务器内部错误: {exc}" if is_dev else "服务器内部错误，请稍后重试",
                status_code=500,
                details=details,
                request_id=request_id,
            ),
        )
