"""
ScholarMind Agent Pydantic Schema
Chat 请求/响应 DTO
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ChatRequest(BaseModel):
    """Agent 对话请求

    P0 Task 4.1/4.5：移除客户端可任意指定的 ``model`` 字符串字段，改为受控
    ``mode: Literal["flash","pro"] | None``。服务端按用户套餐映射实际模型 ID，
    客户端传入任意 ``model`` 字符串将返回 422（提示已废弃，请使用 ``mode``）。
    """
    message: str = Field(..., min_length=1, max_length=10000, description="用户消息")
    agent_id: str = Field(
        ..., description="Agent 类型: researcher/reviewer/architect/synthesizer/polisher/external_reviewer/custom"
    )
    session_id: str = Field(..., description="会话唯一标识")
    context: Optional[dict[str, Any]] = Field(
        default=None, description="上下文信息（discipline/research_type/readiness/guidance_step/guidance_data）"
    )
    # P0 Task 4.1：mode 枚举替代 model 字符串。
    #   - None：使用套餐默认模型（免费→Flash，Pro→Pro）
    #   - "flash"：任意套餐可用 Flash 模型
    #   - "pro"：仅 Pro 套餐可用，免费用户返回 403
    mode: Optional[Literal["flash", "pro"]] = Field(
        default=None,
        description="模型模式：flash(快速) / pro(深度)。不传则使用套餐默认模型。pro 仅 Pro 套餐可用。",
    )

    @model_validator(mode="before")
    @classmethod
    def reject_deprecated_model_field(cls, data: Any) -> Any:
        """P0 Task 4.5：拒绝已废弃的 ``model`` 字段。

        客户端若仍提交 ``model`` 字符串（任意值，包括旧值 ``deepseek-v4-flash`` 等），
        一律返回 422 并提示 ``model field is deprecated, use mode (flash|pro)``。
        这避免客户端绕过套餐控制任意指定模型 ID。
        """
        if isinstance(data, dict) and data.get("model") is not None:
            raise ValueError("model field is deprecated, use mode (flash|pro)")
        return data


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


class SessionItem(BaseModel):
    """会话列表项(含元数据)"""
    session_id: str
    agent_id: str
    title: str
    message_count: int = 0
    last_message_at: Optional[str] = None
    created_at: Optional[str] = None


class SessionListResponse(BaseModel):
    """会话列表响应"""
    success: bool = True
    sessions: list[SessionItem]
    total: int = 0


class SessionRenameRequest(BaseModel):
    """会话重命名请求"""
    title: str = Field(..., min_length=1, max_length=128, description="新标题")


class SessionRenameResponse(BaseModel):
    """会话重命名响应"""
    success: bool = True
    session_id: str
    title: str


class SessionDeleteResponse(BaseModel):
    """会话删除响应"""
    success: bool = True
    session_id: str
    deleted: int = 0