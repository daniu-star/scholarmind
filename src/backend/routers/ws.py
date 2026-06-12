"""
ScholarMind WebSocket 路由
提供实时流式对话能力
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Request

from ..core.dependencies import get_agent_service
from ..services.agent_service import AgentService
from ..services.stream_service import StreamService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/chat/{agent_id}")
async def websocket_chat(
    websocket: WebSocket,
    agent_id: str,
    session_id: str = "",
    request: Request = None,
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
    # 获取 AgentService（通过依赖注入）
    try:
        from ..core.dependencies import get_agent_service as _get_agent_service
        # 通过手动调用依赖函数获取 service
        agent_service: AgentService = None

        # 尝试从 app.state 获取
        if request is not None:
            agent_service = getattr(request.app.state, "agent_service", None)

        if agent_service is None:
            # 初始化一个基本的 service
            from ..config import settings
            agent_service = AgentService(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                model=settings.DEEPSEEK_MODEL,
            )
    except Exception as e:
        logger.error(f"Failed to initialize agent service for WebSocket: {e}")
        await websocket.close(code=1011, reason="Service unavailable")
        return

    stream = StreamService(websocket, agent_service)
    await stream.handle(agent_id=agent_id, session_id=session_id)