"""
ScholarMind 代码执行沙箱 Pydantic Schema
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class CodeExecuteRequest(BaseModel):
    """执行代码请求"""
    code: str = Field(..., min_length=1, description="要执行的代码内容")
    language: str = Field(default="python", description="编程语言(目前仅支持 python)")
    timeout: int = Field(default=30, ge=1, le=120, description="超时时间(秒)")


class CodeExecuteResponse(BaseModel):
    """执行代码响应"""
    success: bool = True
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: int = 0
    error: Optional[str] = None


class PackageInstallRequest(BaseModel):
    """安装包请求"""
    package: str = Field(..., min_length=1, description="要安装的包名(可带版本号)")


class PackageInstallResponse(BaseModel):
    """安装包响应"""
    success: bool = True
    message: str = ""
    stdout: str = ""
    stderr: str = ""


class PackageListResponse(BaseModel):
    """已安装包列表响应"""
    success: bool = True
    packages: list[dict[str, Any]] = []
    total: int = 0
