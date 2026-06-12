"""
ScholarMind DTO 响应映射层
将ORM模型统一转换为API响应字典，解耦内部模型与API契约。
"""
from __future__ import annotations

from typing import Any, Sequence

from ..db.session import Base
from ..models.orm import Conversation, Skill, ChartRecord


class ResponseMapper:
    """统一响应映射：ORM模型 → API响应字典

    集中管理所有数据转换逻辑，遵循单一职责原则。
    前端API契约变更只需修改此类，不影响业务逻辑层。
    """

    # ── 对话映射 ──────────────────────────────────────────

    @staticmethod
    def conversation_to_response(conv: Conversation) -> dict[str, Any]:
        """单条对话消息 → API响应"""
        return {
            "id": conv.id,
            "session_id": conv.session_id,
            "agent_id": conv.agent_id,
            "role": conv.role,
            "content": conv.content,
            "created_at": conv.created_at.isoformat(),
        }

    @staticmethod
    def conversation_list_to_response(
        conversations: Sequence[Conversation],
    ) -> list[dict[str, Any]]:
        """对话消息列表 → API响应"""
        return [
            ResponseMapper.conversation_to_response(c) for c in conversations
        ]

    @staticmethod
    def session_summary(
        session_id: str,
        message_count: int,
        agent_id: str = "",
        last_message_at: str = "",
    ) -> dict[str, Any]:
        """会话摘要 → API响应"""
        result: dict[str, Any] = {
            "session_id": session_id,
            "message_count": message_count,
        }
        if agent_id:
            result["agent_id"] = agent_id
        if last_message_at:
            result["last_message_at"] = last_message_at
        return result

    # ── 技能映射 ──────────────────────────────────────────

    @staticmethod
    def skill_to_response(skill: Skill) -> dict[str, Any]:
        """技能配置 → API响应"""
        return {
            "skill_id": skill.skill_id,
            "display_name": skill.display_name,
            "description": skill.description,
            "category": skill.category,
            "enabled": skill.enabled,
            "agents": skill.agents or [],
            "triggers": skill.triggers or [],
            "rules": skill.rules,
            "is_preset": skill.is_preset,
            "created_at": skill.created_at.isoformat() if skill.created_at else None,
            "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
        }

    @staticmethod
    def skill_list_to_response(
        skills: Sequence[Skill],
    ) -> list[dict[str, Any]]:
        """技能列表 → API响应"""
        return [ResponseMapper.skill_to_response(s) for s in skills]

    # ── 图表记录映射 ─────────────────────────────────────

    @staticmethod
    def chart_to_response(chart: ChartRecord) -> dict[str, Any]:
        """图表记录 → API响应"""
        return {
            "chart_id": chart.chart_id,
            "chart_type": chart.chart_type,
            "title": chart.title,
            "filepath": chart.filepath,
            "session_id": chart.session_id,
            "created_at": chart.created_at.isoformat() if chart.created_at else None,
        }

    @staticmethod
    def chart_list_to_response(
        charts: Sequence[ChartRecord],
    ) -> list[dict[str, Any]]:
        """图表记录列表 → API响应"""
        return [ResponseMapper.chart_to_response(c) for c in charts]

    # ── 统一成功响应 ─────────────────────────────────────

    @staticmethod
    def success_response(
        data: Any = None,
        message: str = "",
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """构建统一成功响应格式

        Args:
            data: 响应数据
            message: 可选的成功消息
            meta: 可选的元数据（如分页信息）

        Returns:
            统一格式的成功响应字典
        """
        result: dict[str, Any] = {"success": True}
        if message:
            result["message"] = message
        if data is not None:
            result["data"] = data
        if meta:
            result["meta"] = meta
        return result

    @staticmethod
    def paginated_response(
        items: list[dict],
        total: int,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        """构建分页响应"""
        return {
            "success": True,
            "data": items,
            "meta": {
                "total": total,
                "offset": offset,
                "limit": limit,
                "has_more": (offset + limit) < total,
            },
        }