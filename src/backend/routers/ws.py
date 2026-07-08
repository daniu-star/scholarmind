"""
ScholarMind WebSocket 路由
提供实时流式对话能力

⚠ DEV-ONLY: 此端点仅在本地开发环境可用（Vite 代理 ws://localhost:8000）。
生产环境 Vercel Serverless Functions 不支持 WebSocket 长连接，
请使用 SSE 端点 /agent/stream 替代。
"""
from __future__ import annotations

import structlog

from fastapi import APIRouter, WebSocket

from ..config import settings
from ..middleware.rate_limit import _extract_user_id_from_jwt, _extract_trusted_client_ip
from ..services.agent_service import AgentService
from ..services.stream_service import StreamService

logger = structlog.get_logger(__name__)

router = APIRouter()


async def _check_ws_rate_limit(websocket: WebSocket) -> bool:
    """WebSocket 建连前限流检查（P0 Task 6.7）

    在 websocket.accept() 之前做 IP/user_id 级计数：
    使用 app.state.ws_rate_limiter（独立内存令牌桶，限额 = base // 2）。

    身份解析与 HTTP 中间件一致：user_id 优先，其次可信代理链 IP，
    不接受客户端可控的 X-Session-ID 作为安全身份。

    Returns:
        True 表示允许建连；False 表示超限（调用方应 close(1013)）。
    """
    if not settings.RATE_LIMIT_ENABLED:
        return True

    ws_limiter = getattr(websocket.app.state, "ws_rate_limiter", None)
    if ws_limiter is None:
        # 未配置限流器（如 RATE_LIMIT_ENABLED=false）：放行
        return True

    # 提取身份（WebSocket 与 Request 同样具备 .headers / .client，鸭子类型复用）
    uid = getattr(websocket, "user_id", None)
    if uid:
        identity = f"u:{uid}"
    else:
        uid = _extract_user_id_from_jwt(websocket)  # type: ignore[arg-type]
        if uid:
            identity = f"u:{uid}"
        else:
            client_ip = _extract_trusted_client_ip(websocket)  # type: ignore[arg-type]
            identity = f"ip:{client_ip}" if client_ip else "ip:unknown"

    # Task 25: 通过公开 acquire 方法消费一个额度（不再访问 _lock/_consume 私有属性）
    allowed = await ws_limiter.acquire(key=identity, cost=1)
    if not allowed:
        logger.warning(
            f"ws rate limit exceeded identity={identity}"
        )
    return allowed


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
    # P1 修复: 优先使用 Sec-WebSocket-Protocol 子协议头传递 token（不入 URL 日志），
    # 兼容查询参数模式作为降级方案。
    from ..services.auth_service import decode_token, get_user_by_id

    token = ""
    # 方式 1: Sec-WebSocket-Protocol header（推荐，token 不入 access log）
    protocols = websocket.headers.get("Sec-WebSocket-Protocol", "")
    if protocols.startswith("access_token."):
        token = protocols[len("access_token."):]
    # 方式 2: 查询参数（兼容降级）
    if not token:
        token = websocket.query_params.get("access_token", "")
    payload = decode_token(token, expected_type="access") if token else None
    try:
        token_user_id = int((payload or {}).get("sub", 0))
    except (TypeError, ValueError):
        token_user_id = 0
    session_factory = getattr(websocket.app.state, "db_session_factory", None)
    if not token_user_id or session_factory is None:
        await websocket.close(code=4401, reason="authentication required")
        return
    async with session_factory() as auth_db:
        user = await get_user_by_id(auth_db, token_user_id)
        if not user or not user.is_active:
            await websocket.close(code=4401, reason="invalid account")
            return
    websocket.user_id = token_user_id

    # Task 6.7：accept 前做限流；超限关闭 1013 Try Again Later
    allowed = await _check_ws_rate_limit(websocket)
    if not allowed:
        await websocket.close(code=1013)  # Try Again Later
        return

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
            stream = StreamService(
                websocket, agent_service, user_id=token_user_id, db=db
            )
            await stream.handle(agent_id=agent_id, session_id=session_id)
