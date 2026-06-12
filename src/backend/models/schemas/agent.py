"""
ScholarMind Agent Pydantic Schema
Chat 请求/响应 DTO
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Agent 对话请求"""
    message: str = Field(..., min_length=1, max_length=10000, description="用户消息")
    agent_id: str = Field(
        ..., description="Agent 类型: researcher/reviewer/architect/synthesizer/polisher"
    )
    session_id: str = Field(..., description="会话唯一标识")
    context: Optional[dict[str, Any]] = Field(
        default=None, description="上下文信息（discipline/research_type/readiness）"
    )


class ChatResponse(BaseModel):
    """Agent 对话响应"""
    reply: str = Field(..., description="AI 回复内容")
    options: list[str] = Field(default_factory=list, description="建议选项列表")
    skills_used: list[str] = Field(default_factory=list, description="使用的技能列表")
    chart_info: Optional[dict] = Field(default=None, description="图表信息")
    cnki_results: Optional[list] = Field(default=None, description="CNKI 检索结果")
    skill_hint: Optional[str] = Field(default=None, description="技能推荐提示")


class AgentInfo(BaseModel):
    """Agent 信息"""
    id: str
    name: str
    icon: str
    description: str
    skills: list[str] = []


class AgentListResponse(BaseModel):
    """Agent 列表响应"""
    success: bool = True
    agents: list[AgentInfo]


class ConversationHistoryResponse(BaseModel):
    """对话历史响应"""
    success: bool = True
    session_id: str
    message_count: int
    history: list[dict]


class ClearConversationResponse(BaseModel):
    """清空对话响应"""
    success: bool = True
    session_id: str
    cleared: bool