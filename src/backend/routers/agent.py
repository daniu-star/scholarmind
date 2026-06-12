from fastapi import APIRouter, HTTPException, Depends, Request
from typing import Optional, Dict, Any

from ..config import settings
from ..services.agent_service import AgentService
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
    service: AgentService = Depends(get_agent_service),
):
    """Chat with an AI agent"""
    try:
        _validate_agent_service(service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent service init failed: {str(e)}")

    if request.agent_id not in {"researcher", "reviewer", "architect", "synthesizer", "polisher"}:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid agent_id: {request.agent_id}. "
                   f"Valid options: researcher, reviewer, architect, synthesizer, polisher",
        )

    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        result = await service.chat(
            message=request.message,
            agent_id=request.agent_id,
            session_id=request.session_id,
            context=request.context,
        )
        return ChatResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(e)}")


@router.delete("/conversation/{session_id}")
async def clear_conversation(
    session_id: str,
    service: AgentService = Depends(get_agent_service),
):
    """Clear conversation history"""
    cleared = await service.clear_conversation(session_id)
    return {
        "success": True,
        "session_id": session_id,
        "cleared": cleared,
    }


@router.get("/agents")
async def list_agents(
    service: AgentService = Depends(get_agent_service),
):
    """List all available agents"""
    agents = service.list_agents()
    return {
        "success": True,
        "agents": agents,
    }


@router.get("/conversation/{session_id}")
async def get_conversation(
    session_id: str,
    service: AgentService = Depends(get_agent_service),
):
    """Get conversation history for a session"""
    history = await service.get_conversation_history(session_id)
    return {
        "success": True,
        "session_id": session_id,
        "message_count": len(history),
        "history": history,
    }


def _validate_agent_service(service: AgentService) -> None:
    """验证 agent service 可用"""
    if not settings.DEEPSEEK_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="DeepSeek API key not configured. Set DEEPSEEK_API_KEY in .env",
        )