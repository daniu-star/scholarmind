"""
ScholarMind 自定义异常层次
统一错误编码，便于前端统一处理
"""
from __future__ import annotations
from typing import Optional, Any

from ..models.error_codes import ErrorCode


class AppException(Exception):
    """基础应用异常，携带结构化错误码和额外详情"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        status_code: int = 500,
        details: Optional[dict[str, Any]] = None,
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)

    def to_response(self) -> dict:
        """转换为统一错误响应格式"""
        result: dict = {
            "success": False,
            "error": {
                "code": self.code.value,
                "message": self.message,
            },
        }
        if self.details:
            result["error"]["details"] = self.details
        return result


# ── 通用异常 ──

class NotFoundError(AppException):
    """资源未找到"""
    def __init__(self, resource: str, identifier: str):
        super().__init__(
            message=f"{resource} '{identifier}' 不存在",
            code=ErrorCode.NOT_FOUND,
            status_code=404,
            details={"resource": resource, "identifier": identifier},
        )


class ValidationError(AppException):
    """输入验证失败"""
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=message,
            code=ErrorCode.VALIDATION_ERROR,
            status_code=400,
            details=details,
        )


# ── Agent 异常 ──

class AgentNotFoundError(AppException):
    """Agent 不存在"""
    def __init__(self, agent_id: str):
        super().__init__(
            message=f"无效的Agent类型：{agent_id}",
            code=ErrorCode.AGENT_NOT_FOUND,
            status_code=400,
            details={"agent_id": agent_id},
        )


class AgentChatFailedError(AppException):
    """Agent 对话失败"""
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=message,
            code=ErrorCode.AGENT_CHAT_FAILED,
            status_code=500,
            details=details,
        )


# ── CNKI 异常 ──

class CNKISearchFailedError(AppException):
    """CNKI 检索失败"""
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=message,
            code=ErrorCode.CNKI_SEARCH_FAILED,
            status_code=502,
            details=details,
        )


class CNKIConnectionError(AppException):
    """CNKI 连接失败"""
    def __init__(self, message: str = "CNKI服务连接失败"):
        super().__init__(
            message=message,
            code=ErrorCode.CNKI_CONNECTION_FAILED,
            status_code=502,
        )


# ── 图表异常 ──

class ChartGenerationError(AppException):
    """图表生成失败"""
    def __init__(self, message: str, chart_type: str = "", details: Optional[dict] = None):
        d = details or {}
        if chart_type:
            d["chart_type"] = chart_type
        super().__init__(
            message=message,
            code=ErrorCode.CHART_GENERATION_FAILED,
            status_code=500,
            details=d,
        )


class InvalidChartTypeError(AppException):
    """无效图表类型"""
    def __init__(self, chart_type: str):
        super().__init__(
            message=f"无效的图表类型：{chart_type}",
            code=ErrorCode.INVALID_CHART_TYPE,
            status_code=400,
            details={"chart_type": chart_type},
        )


# ── 文件上传异常 ──

class FileTooLargeError(AppException):
    """文件过大"""
    def __init__(self, max_size_mb: int, actual_size_mb: float):
        super().__init__(
            message=f"文件大小 {actual_size_mb:.1f}MB 超过限制 {max_size_mb}MB",
            code=ErrorCode.FILE_TOO_LARGE,
            status_code=413,
            details={"max_size_mb": max_size_mb, "actual_size_mb": actual_size_mb},
        )


class InvalidFileTypeError(AppException):
    """无效文件类型"""
    def __init__(self, filename: str, allowed_extensions: set):
        super().__init__(
            message=f"不支持的文件类型：{filename}",
            code=ErrorCode.INVALID_FILE_TYPE,
            status_code=400,
            details={
                "filename": filename,
                "allowed_extensions": list(allowed_extensions),
            },
        )


class UploadFailedError(AppException):
    """上传失败"""
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=message,
            code=ErrorCode.UPLOAD_FAILED,
            status_code=500,
            details=details,
        )


# ── 技能异常 ──

class SkillNotFoundError(AppException):
    """技能不存在"""
    def __init__(self, skill_id: str):
        super().__init__(
            message=f"技能 '{skill_id}' 不存在",
            code=ErrorCode.SKILL_NOT_FOUND,
            status_code=404,
            details={"skill_id": skill_id},
        )


class SkillAlreadyExistsError(AppException):
    """技能已存在"""
    def __init__(self, skill_id: str):
        super().__init__(
            message=f"技能 '{skill_id}' 已存在",
            code=ErrorCode.SKILL_ALREADY_EXISTS,
            status_code=409,
            details={"skill_id": skill_id},
        )


class SkillValidationError(AppException):
    """技能验证失败"""
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=message,
            code=ErrorCode.SKILL_VALIDATION_FAILED,
            status_code=400,
            details=details,
        )


# ── 外部服务异常 ──

class ExternalServiceError(AppException):
    """外部服务调用失败"""
    def __init__(self, service: str, message: str, details: Optional[dict] = None):
        super().__init__(
            message=f"{service} 调用失败: {message}",
            code=ErrorCode.EXTERNAL_SERVICE_ERROR,
            status_code=502,
            details=details or {"service": service},
        )


class LLMAPIError(AppException):
    """大模型 API 调用失败"""
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=f"AI服务调用失败: {message}",
            code=ErrorCode.LLM_API_FAILED,
            status_code=502,
            details=details,
        )


# ── 速率限制异常 ──

class RateLimitError(AppException):
    """请求速率超限"""
    def __init__(self, limit: int, window_seconds: int = 60):
        super().__init__(
            message=f"请求速率超限，每分钟最多 {limit} 次请求",
            code=ErrorCode.RATE_LIMITED,
            status_code=429,
            details={"limit": limit, "window_seconds": window_seconds},
        )