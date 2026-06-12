"""
ScholarMind Upload Pydantic Schema
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class UploadedFileInfo(BaseModel):
    """上传文件信息"""
    file_id: str
    filename: str
    stored_name: str
    extension: str
    size: int
    tag: str
    type_label: str = "文档"


class UploadResponse(BaseModel):
    """文件上传响应"""
    session_id: str
    uploaded: list[dict]
    count: int


class FileListResponse(BaseModel):
    """文件列表响应"""
    session_id: str
    files: list[dict]
    count: int


class FileDeleteResponse(BaseModel):
    """文件删除响应"""
    session_id: str
    deleted: str
    success: bool = True