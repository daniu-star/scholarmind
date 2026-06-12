"""
ScholarMind Knowledge (CNKI) Pydantic Schema
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CNKISearchRequest(BaseModel):
    """CNKI 检索请求"""
    query: str = Field(..., min_length=1, max_length=200, description="搜索词")
    year_filter: str = Field(default="", description="年份过滤")
    source_filter: str = Field(default="", description="来源过滤（如 CJFQ 表示期刊）")
    count: int = Field(default=20, ge=1, le=50, description="返回结果数量")


class CNKIConfigRequest(BaseModel):
    """CNKI 配置请求"""
    proxy_url: Optional[str] = Field(default=None, description="代理 URL")
    api_key: Optional[str] = Field(default=None, description="API 密钥")
    mcp_tools: Optional[dict] = Field(default=None, description="MCP 工具配置")


class CNKISearchResult(BaseModel):
    """CNKI 搜索结果"""
    title: str
    author: str
    year: str
    source: str
    citations: int = 0
    core: bool = False
    abstract: str = ""
    doi: str = ""


class CNKISearchResponse(BaseModel):
    """CNKI 检索响应"""
    success: bool = True
    query: str
    count: int
    results: list[dict]


class KnowledgeStatusResponse(BaseModel):
    """知识库状态响应"""
    success: bool = True
    services: dict