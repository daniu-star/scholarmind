"""
ScholarMind Skills Pydantic Schema
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SkillCreateRequest(BaseModel):
    """创建技能请求"""
    id: str = Field(..., min_length=1, max_length=128, description="技能唯一标识")
    display_name: str = Field(..., min_length=1, max_length=128, description="展示名称")
    description: str = Field(default="", max_length=500, description="技能描述")
    triggers: list[str] = Field(default_factory=list, description="触发关键词")
    agents: list[str] = Field(default_factory=list, description="关联的 Agent")
    rules: str = Field(default="", description="技能规则（Markdown）")


class SkillUpdateRequest(BaseModel):
    """更新技能请求（所有字段可选）"""
    display_name: Optional[str] = Field(default=None, max_length=128)
    description: Optional[str] = Field(default=None, max_length=500)
    triggers: Optional[list[str]] = Field(default=None)
    agents: Optional[list[str]] = Field(default=None)
    rules: Optional[str] = Field(default=None)


class SkillToggleRequest(BaseModel):
    """切换技能启用状态请求"""
    enabled: bool


class SkillInfo(BaseModel):
    """技能信息"""
    id: str
    display_name: str
    description: str = ""
    category: str = "custom"
    enabled: bool = True
    agents: list[str] = []
    triggers: list[str] = []
    rules: str = ""
    is_preset: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SkillListResponse(BaseModel):
    """技能列表响应"""
    skills: list[dict]
    count: int


class SkillTemplateResponse(BaseModel):
    """技能模板响应"""
    template: str
    format: str
    instructions: str