"""
ScholarMind WebSocket 路由
提供实时流式对话能力
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import settings
from ..services.agent_service import AgentService
from ..services.stream_service import StreamService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/chat/{agent_id}")
async def websocket_chat(
    websocket: WebSocket,
    agent_id: str,
    session_id: str = "",
):
    """WebSocket 流式对话端点

    连接: ws://host:port/api/v1/ws/chat/{agent_id}?session_id=xxx

    客户端→服务端:
        {"type": "chat", "message": "用户消息", "context": {...}}
        {"type": "cancel"}

    服务端→客户端:
        {"type": "token", "content": "文字", "index": 0}
        {"type": "done", "skills_used": [...], "options": [...], ...}
        {"type": "error", "message": "错误描述"}
        {"type": "ping"}
    """
    session_factory = getattr(websocket.app.state, "db_session_factory", None)

    if session_factory is not None:
        # DB 模式：使用 session factory 创建独立的 session
        from ..db.repository.conversation import ConversationRepository
        from ..db.repository.skill import SkillRepository
        from ..db.repository.chart import ChartRepository
        from ..services.skills_service import SkillsService

        async with session_factory() as db:
            agent_service = AgentService(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                model=settings.DEEPSEEK_MODEL,
                conversation_repo=ConversationRepository(db),
                skills_service=SkillsService(repository=SkillRepository(db)),
                chart_repo=ChartRepository(db),
            )
            stream = StreamService(websocket, agent_service)
            await stream.handle(agent_id=agent_id, session_id=session_id)
    else:
        # 文件模式回退：无数据库持久化
        agent_service = AgentService(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            model=settings.DEEPSEEK_MODEL,
        )
        stream = StreamService(websocket, agent_service)
        await stream.handle(agent_id=agent_id, session_id=session_id)