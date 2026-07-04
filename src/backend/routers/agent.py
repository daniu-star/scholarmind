import json
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..services.agent_service import AgentService, VALID_AGENTS
from ..core.exceptions import AppException, AgentNotFoundError, AgentChatFailedError, ValidationError, NotFoundError
from ..services.interfaces import IAgentService
from ..models.schemas.agent import (
    ChatRequest,
    ChatResponse,
    AgentInfo,
    AgentListResponse,
    ConversationHistoryResponse,
    ClearConversationResponse,
    SessionItem,
    SessionListResponse,
    SessionRenameRequest,
    SessionRenameResponse,
    SessionDeleteResponse,
)
# P0 Task 3.2：所有写操作与会话接口改为强制鉴权 get_current_user（返回 int user_id）。
# 不再使用 get_optional_user_id（匿名可读写持久化会话导致 IDOR）。
from ..core.dependencies import get_agent_service, get_current_user, get_db
# P0 Task 4.2/4.4：服务端 mode → 实际模型 ID 映射，禁止客户端任意指定 model 字符串
from ..services.model_policy import resolve_model, ModelPolicyError
from ..services.entitlement_service import EntitlementError, EntitlementService

router = APIRouter(prefix="/agent", tags=["agent"])


async def _reserve_chat(
    db: AsyncSession, user_id: int, agent_id: str, context: Optional[dict] = None
) -> dict:
    try:
        if agent_id == "external_reviewer":
            await EntitlementService.require_external_reviewer(db, user_id)
        # P1 Task 6：移除 greeting 去重逻辑（曾导致全局 set 内存泄漏）。
        # 问候配额由前端控制 UX，后端每次都正常走 consume_chat / external_subscription 流程。
        if agent_id == "external_reviewer":
            return {"consumed": "external_subscription"}
        return await EntitlementService.consume_chat(db, user_id)
    except EntitlementError as exc:
        status_code = (
            status.HTTP_402_PAYMENT_REQUIRED
            if exc.code in {"PAYMENT_REQUIRED", "CHAT_QUOTA_EXHAUSTED"}
            else status.HTTP_403_FORBIDDEN
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post("/chat", response_model=ChatResponse)
async def chat_with_agent(
    request: ChatRequest,
    service: IAgentService = Depends(get_agent_service),
    user_id: int = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Chat with an AI agent

    P0 Task 3.2：强制鉴权，user_id 透传到 AgentService.chat() 隔离会话。
    P0 Task 4.2/4.4：移除客户端 ``model`` 直指定逻辑，改为服务端按套餐映射
    ``request.mode`` 为实际模型 ID 并透传给 AgentService.chat()。
    免费用户请求 ``mode="pro"`` → 403。
    """
    if not request.message.strip():
        raise ValidationError("消息不能为空")

    if request.agent_id not in VALID_AGENTS:
        raise AgentNotFoundError(request.agent_id)

    # P0 Task 4.4：服务端解析实际模型 ID（按套餐 + mode），禁止客户端直指定
    try:
        model = await resolve_model(db, user_id, request.mode)
    except ModelPolicyError as e:
        # 免费用户请求 pro 模型 → 403
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    reservation = await _reserve_chat(db, user_id, request.agent_id, request.context)
    try:
        result = await service.chat(
            message=request.message,
            agent_id=request.agent_id,
            session_id=request.session_id,
            context=request.context,
            user_id=user_id,
            model=model,
        )
        return ChatResponse(**result)
    except AppException:
        await EntitlementService.refund_chat(
            db, user_id, reservation.get("consumed", "")
        )
        raise
    except Exception as e:
        await EntitlementService.refund_chat(
            db, user_id, reservation.get("consumed", "")
        )
        raise AgentChatFailedError(str(e))


@router.post("/stream")
async def stream_chat_with_agent(
    request: ChatRequest,
    service: IAgentService = Depends(get_agent_service),
    user_id: int = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE 流式对话：逐 token 返回 LLM 响应

    P0 Task 3.2：强制鉴权，user_id 透传到 AgentService.stream_chat() 隔离会话。
    P0 Task 4.2/4.4：服务端按套餐映射 ``request.mode`` 为实际模型 ID 并透传。
    免费用户请求 ``mode="pro"`` → 403。

    复用 service.stream_chat()，事件类型：
      - token: 逐 token 内容
      - thought: CoT 思考块（仅 external_reviewer）
      - options: 选项卡片
      - done: 完成 + 元数据（skills_used/chart_info/cnki_results/skill_hint）
      - error: 错误信息

    前端通过 fetch + ReadableStream 消费，按 `data: {json}\\n\\n` 分隔事件。
    """
    if not request.message.strip():
        raise ValidationError("消息不能为空")

    if request.agent_id not in VALID_AGENTS:
        raise AgentNotFoundError(request.agent_id)

    # P0 Task 4.4：服务端解析实际模型 ID（按套餐 + mode），禁止客户端直指定
    try:
        model = await resolve_model(db, user_id, request.mode)
    except ModelPolicyError as e:
        # 免费用户请求 pro 模型 → 403
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    reservation = await _reserve_chat(db, user_id, request.agent_id, request.context)

    async def event_generator():
        try:
            async for chunk in service.stream_chat(
                message=request.message,
                agent_id=request.agent_id,
                session_id=request.session_id,
                context=request.context,
                user_id=user_id,
                model=model,
            ):
                # SSE 格式：data: {json}\n\n
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        except Exception as e:
            await EntitlementService.refund_chat(
                db, user_id, reservation.get("consumed", "")
            )
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲，确保 token 实时推送
        },
    )


@router.delete("/conversation/{session_id}", response_model=ClearConversationResponse)
async def clear_conversation(
    session_id: str,
    service: IAgentService = Depends(get_agent_service),
    user_id: int = Depends(get_current_user),
):
    """Clear conversation history

    P0 Task 3.2：强制鉴权，仅清空当前 user_id 名下的会话；跨用户返回 success=True
    但 cleared=0（不存在的对象不暴露存在性）。
    """
    cleared = await service.clear_conversation(session_id, user_id=user_id)
    return {
        "success": True,
        "session_id": session_id,
        "cleared": cleared,
    }


@router.get("/agents", response_model=AgentListResponse)
async def list_agents(
    service: IAgentService = Depends(get_agent_service),
    user_id: int = Depends(get_current_user),
):
    """List all available agents

    P0 Task 3.2：强制鉴权（即便只读列表也要求登录，避免匿名探测可用 Agent）。
    """
    agents = service.list_agents()
    return {
        "success": True,
        "agents": agents,
    }


@router.get("/topics/{discipline_id}")
async def get_topics_by_discipline(
    discipline_id: str,
    service: IAgentService = Depends(get_agent_service),
    user_id: int = Depends(get_current_user),
):
    """获取指定学科的热门选题列表（4 大学科各 15 个 Top 议题）

    P0 Task 3.2：强制鉴权。

    discipline_id 支持：
    - 4 大学科 ID：engineering / science / humanities / interdisciplinary
    - 子学科 ID：communication / computer_science / mathematics 等（自动映射回大学科）
    """
    valid_disciplines = {"engineering", "science", "humanities", "interdisciplinary",
                         # 人文社科子学科
                         "communication", "sociology", "psychology", "education",
                         "journalism", "ethnology", "anthropology", "literature",
                         "history", "management", "economics",
                         # 工科子学科
                         "computer_science", "electronic_engineering", "mechanical_engineering",
                         "civil_engineering", "materials_science", "automation",
                         # 理科子学科
                         "mathematics", "physics", "chemistry", "biology", "astronomy", "earth_science",
                         # 交叉学科子学科
                         "computational_social_science", "digital_humanities",
                         "bioinformatics", "cognitive_science", "environmental_studies", "complex_systems"}
    if discipline_id not in valid_disciplines:
        raise ValidationError(f"无效的学科 ID: {discipline_id}")

    topics = service.get_topics_for_discipline(discipline_id)
    # 映射回大学科标签
    major_id = service._map_to_major_discipline(discipline_id)
    label_map = {"engineering": "工科", "science": "理科",
                 "humanities": "人文社科", "interdisciplinary": "交叉学科"}
    return {
        "success": True,
        "discipline_id": major_id,
        "discipline_label": label_map.get(major_id, major_id),
        "count": len(topics),
        "topics": topics,
    }


@router.get("/conversation/{session_id}", response_model=ConversationHistoryResponse)
async def get_conversation(
    session_id: str,
    service: IAgentService = Depends(get_agent_service),
    user_id: int = Depends(get_current_user),
):
    """Get conversation history for a session

    P0 Task 3.2/3.9：强制鉴权，仅返回当前 user_id 名下的会话历史；
    跨用户访问或会话不存在 → 404（不暴露对象是否存在，不返回任何数据）。
    前端可将 404 视为"新会话/无历史"。
    """
    history = await service.get_conversation_history(session_id, user_id=user_id)
    if not history:
        # 跨用户访问或会话尚无消息 → 404（不暴露存在性）
        raise NotFoundError("会话", session_id)
    return {
        "success": True,
        "session_id": session_id,
        "message_count": len(history),
        "history": history,
    }


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    agent_id: Optional[str] = Query(default=None, description="按 Agent ID 过滤"),
    limit: int = Query(default=50, ge=1, le=200, description="返回数量上限"),
    service: IAgentService = Depends(get_agent_service),
    user_id: int = Depends(get_current_user),
):
    """列出会话(含元数据: title/message_count/last_message_at)

    P0 Task 3.2：强制鉴权，仅返回当前 user_id 名下的会话。
    """
    sessions = await service.list_sessions_with_meta(user_id=user_id, agent_id=agent_id, limit=limit)
    return {
        "success": True,
        "sessions": sessions,
        "total": len(sessions),
    }


@router.patch("/sessions/{session_id}", response_model=SessionRenameResponse)
async def rename_session(
    session_id: str,
    request: SessionRenameRequest,
    service: IAgentService = Depends(get_agent_service),
    user_id: int = Depends(get_current_user),
):
    """重命名会话标题

    P0 Task 3.2：强制鉴权，跨用户重命名返回 404（不暴露存在性）。
    """
    success = await service.rename_session(session_id, request.title, user_id=user_id)
    if not success:
        # 修复 NotFoundError 构造签名：需 (resource, identifier) 两参数
        raise NotFoundError("会话", session_id)
    return {
        "success": True,
        "session_id": session_id,
        "title": request.title,
    }


@router.delete("/sessions/{session_id}", response_model=SessionDeleteResponse)
async def delete_session(
    session_id: str,
    service: IAgentService = Depends(get_agent_service),
    user_id: int = Depends(get_current_user),
):
    """物理删除整个会话(所有消息)

    P0 Task 3.2：强制鉴权，跨用户删除返回 404（不暴露存在性）。

    区别于 DELETE /agent/conversation/{session_id}(仅清空消息保留 session_id),
    此端点完全删除会话记录。
    """
    deleted = await service.delete_session(session_id, user_id=user_id)
    if deleted == 0:
        # 跨用户或不存在 → 404
        raise NotFoundError("会话", session_id)
    return {
        "success": True,
        "session_id": session_id,
        "deleted": deleted,
    }
