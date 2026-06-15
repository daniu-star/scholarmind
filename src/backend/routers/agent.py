from fastapi import APIRouter, Depends
from typing import Optional, Dict, Any

from ..config import settings
from ..services.agent_service import AgentService, VALID_AGENTS
from ..core.exceptions import AppException, AgentNotFoundError, AgentChatFailedError, ValidationError
from ..services.interfaces import IAgentService
from ..models.schemas.agent import (
    ChatRequest,
    ChatResponse,
    AgentInfo,
    AgentListResponse,
    ConversationHistoryResponse,
    ClearConversationResponse,
)
from ..core.dependencies import get_agent_service

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/chat", response_model=ChatResponse)
async def chat_with_agent(
    request: ChatRequest,
    service: IAgentService = Depends(get_agent_service),
):
    """Chat with an AI agent"""
    if not request.message.strip():
        raise ValidationError("消息不能为空")

    if request.agent_id not in VALID_AGENTS:
        raise AgentNotFoundError(request.agent_id)

    try:
        result = await service.chat(
            message=request.message,
            agent_id=request.agent_id,
            session_id=request.session_id,
            context=request.context,
        )
        return ChatResponse(**result)
    except AppException:
        raise
    except Exception as e:
        raise AgentChatFailedError(str(e))


@router.delete("/conversation/{session_id}", response_model=ClearConversationResponse)
async def clear_conversation(
    session_id: str,
    service: IAgentService = Depends(get_agent_service),
):
    """Clear conversation history"""
    cleared = await service.clear_conversation(session_id)
    return {
        "success": True,
        "session_id": session_id,
        "cleared": cleared,
    }


@router.get("/agents", response_model=AgentListResponse)
async def list_agents(
    service: IAgentService = Depends(get_agent_service),
):
    """List all available agents"""
    agents = service.list_agents()
    return {
        "success": True,
        "agents": agents,
    }


@router.get("/conversation/{session_id}", response_model=ConversationHistoryResponse)
async def get_conversation(
    session_id: str,
    service: IAgentService = Depends(get_agent_service),
):
    """Get conversation history for a session"""
    history = await service.get_conversation_history(session_id)
    return {
        "success": True,
        "session_id": session_id,
        "message_count": len(history),
        "history": history,
    }