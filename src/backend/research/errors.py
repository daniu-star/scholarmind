"""研究 API 的统一错误模型。

所有对外错误都通过 ``ResearchAPIError`` 抛出，由 ``routers/research.py`` 的异常
处理器转换为 ``{"error": {"code", "message", "details", "retryable", "request_id"}}``。

规则（PRD §8.4）：
- 401 未认证；404 统一表示“不存在或不属于当前用户”，绝不区分两者；
- 402 权益不足；409 状态/版本冲突；413 体积超限；415 媒体类型不支持；
- 422 语义校验失败；429 并发/排队超限；503 能力不可用（诚实失败）。
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class ResearchAPIError(Exception):
    """带 HTTP 语义的领域错误；message 面向用户，不含内部路径/堆栈。"""

    def __init__(
        self,
        code: str,
        status_code: int,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.message = message
        self.details = details or {}
        self.retryable = retryable

    def to_payload(self, request_id: Optional[str] = None) -> Dict[str, Any]:
        error: Dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "retryable": self.retryable,
        }
        if request_id:
            error["request_id"] = request_id
        return {"error": error}


def unauthorized(message: str = "需要登录后使用研究功能。") -> ResearchAPIError:
    return ResearchAPIError("UNAUTHORIZED", 401, message, retryable=False)


def not_found(resource: str = "资源") -> ResearchAPIError:
    """统一 404：不泄露“存在但不属于你”与“不存在”的差异。"""
    return ResearchAPIError("NOT_FOUND", 404, f"{resource}不存在。")


def payment_required(
    message: str, details: Optional[Dict[str, Any]] = None
) -> ResearchAPIError:
    return ResearchAPIError("PAYMENT_REQUIRED", 402, message, details)


def conflict(code: str, message: str, details: Optional[Dict[str, Any]] = None) -> ResearchAPIError:
    return ResearchAPIError(code, 409, message, details)


def payload_too_large(message: str, details: Optional[Dict[str, Any]] = None) -> ResearchAPIError:
    return ResearchAPIError("FILE_TOO_LARGE", 413, message, details)


def unsupported_media(message: str = "暂不支持该文件类型。") -> ResearchAPIError:
    return ResearchAPIError("UNSUPPORTED_MEDIA_TYPE", 415, message)


def invalid(code: str, message: str, details: Optional[Dict[str, Any]] = None) -> ResearchAPIError:
    return ResearchAPIError(code, 422, message, details)


def too_many(message: str, details: Optional[Dict[str, Any]] = None) -> ResearchAPIError:
    return ResearchAPIError("CONCURRENCY_LIMIT", 429, message, details, retryable=True)


def unavailable(code: str, message: str, details: Optional[Dict[str, Any]] = None) -> ResearchAPIError:
    return ResearchAPIError(code, 503, message, details, retryable=True)


def internal(message: str = "研究服务暂时不可用，请稍后重试。") -> ResearchAPIError:
    return ResearchAPIError("INTERNAL_ERROR", 500, message, retryable=True)


__all__ = [
    "ResearchAPIError",
    "unauthorized",
    "not_found",
    "payment_required",
    "conflict",
    "payload_too_large",
    "unsupported_media",
    "invalid",
    "too_many",
    "unavailable",
    "internal",
]
