"""
ScholarMind 依赖注入
FastAPI Depends 依赖注入中心，管理所有服务的生命周期
"""
from __future__ import annotations

from typing import AsyncGenerator, Optional

from fastapi import Request, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.exceptions import AgentChatFailedError
from ..db.session import get_db as _get_db
from ..db.unit_of_work import UnitOfWork
from ..services.interfaces import IAgentService


# ── 数据库依赖 ──────────────────────────────────────────────

async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """获取异步数据库会话（从 app.state 获取引擎和会话工厂）"""
    engine = getattr(request.app.state, "db_engine", None)
    session_factory = getattr(request.app.state, "db_session_factory", None)
    async for session in _get_db(engine=engine, session_factory=session_factory):
        yield session


# ── 用户鉴权依赖 ────────────────────────────────────────────
# 自包含 JWT 解析逻辑，避免与 routers.auth 产生循环依赖。
# routers.auth.get_current_user 返回完整 user 对象（用于 /auth/me 等）；
# 此处 get_current_user_id 仅返回 user_id 字符串，供业务路由使用。

_bearer_security = HTTPBearer(auto_error=False)


async def get_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_security),
    db: AsyncSession = Depends(get_db),
) -> str:
    """获取当前登录用户 ID（强制鉴权）

    从请求头 Authorization: Bearer <token> 中解析 JWT，
    返回 user_id 字符串。无凭证或凭证无效时抛 401。
    """
    from ..services.auth_service import decode_token, get_user_by_id

    if not credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未提供认证凭证")
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "认证凭证无效或已过期")
    try:
        user_id = int(payload.get("sub", 0))
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "认证凭证格式错误")
    if user_id <= 0:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "认证凭证无效")

    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return str(user.id)


async def get_optional_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_security),
    db: AsyncSession = Depends(get_db),
) -> Optional[str]:
    """获取当前登录用户 ID（可选鉴权）

    与 get_current_user_id 相似，但未携带凭证或凭证无效时返回 None
    而非抛 401。用于兼容旧前端或匿名可访问的端点。
    """
    from ..services.auth_service import decode_token, get_user_by_id

    if not credentials:
        return None
    payload = decode_token(credentials.credentials)
    if not payload:
        return None
    try:
        user_id = int(payload.get("sub", 0))
    except (TypeError, ValueError):
        return None
    if user_id <= 0:
        return None
    user = await get_user_by_id(db, user_id)
    return str(user.id) if user else None


# ── P0 Task 3.1：强制鉴权依赖（业务端点专用）──────────────────
# 与 get_optional_user_id 并存，但区别：
# - 无有效 token → 401（不返回 None）
# - refresh token（type=refresh）访问业务端点 → 401（仅 access token 可用）
# - 用户不存在或被禁用（is_active=False）→ 401
# - 返回 user.id (int)，供 Repository 按 user_id 过滤使用


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_security),
    db: AsyncSession = Depends(get_db),
) -> int:
    """强制鉴权依赖：返回当前登录用户 ID（int）

    用于所有业务端点（Agent 写操作、会话读写、Paper Pipeline/Review）。
    匿名/无效/refresh-token/禁用用户一律返回 401。

    P0 Task 3.1/3.7：阻断匿名访问与 refresh token 混用攻击。
    """
    from ..services.auth_service import decode_token, get_user_by_id

    if not credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未提供认证凭证")
    # 仅接受 type=access 的 token；refresh token 一律拒绝
    payload = decode_token(credentials.credentials, expected_type="access")
    if not payload:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "认证凭证无效、已过期或为 refresh token（业务 API 需要 access token）",
        )
    try:
        user_id = int(payload.get("sub", 0))
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "认证凭证格式错误")
    if user_id <= 0:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "认证凭证无效")

    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    # 禁用用户立即失效（即使 token 未过期）
    if not getattr(user, "is_active", True):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户已被禁用")
    return int(user.id)


# ── P0 Task 1.3：管理员鉴权依赖 ──────────────────────────────
# 代码执行端点即便在 CODE_EXECUTION_ENABLED=true 时也强制要求管理员角色。
# 当前 User 模型无 role/is_superuser 字段，先以 settings.ADMIN_USERNAMES
# 白名单为准（逗号分隔的 username 列表）；后续 P1 阶段可扩展为 role 字段。


async def require_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_security),
    db: AsyncSession = Depends(get_db),
) -> int:
    """强制管理员鉴权，返回 user_id（int）

    - 未携带凭证或凭证无效 → 401
    - 凭证有效但非管理员 → 403
    - 管理员 → 返回 user.id

    管理员判定：User.username 在 settings.ADMIN_USERNAMES 白名单内。
    """
    from ..services.auth_service import decode_token, get_user_by_id

    if not credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未提供认证凭证")
    payload = decode_token(credentials.credentials, expected_type="access")
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "认证凭证无效或已过期")
    try:
        user_id = int(payload.get("sub", 0))
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "认证凭证格式错误")
    if user_id <= 0:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "认证凭证无效")

    user = await get_user_by_id(db, user_id)
    if not user or not getattr(user, "is_active", True):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")

    admin_names = {
        name.strip()
        for name in settings.ADMIN_USERNAMES.split(",")
        if name.strip()
    }
    # P0 修复: 优先使用 role 字段判定管理员（RBAC），白名单为过渡期兼容
    user_role = getattr(user, "role", "user") or "user"
    if user_role != "admin" and user.username not in admin_names:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return int(user.id)


# ── Agent 服务依赖 ──────────────────────────────────────────

async def get_agent_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> IAgentService:
    """获取 AgentService 实例（按请求创建，注入 ConversationRepository + SkillsService + CNKIService + ChartRepository）

    注意：不再使用单例模式，每次请求创建新的 service 实例，
    确保数据库 session 与请求生命周期一致，避免 closed session 错误。
    """
    from ..services.agent_service import AgentService
    from ..db.repository.conversation import ConversationRepository
    from ..db.repository.skill import SkillRepository
    from ..db.repository.chart import ChartRepository
    from ..services.skills_service import SkillsService

    # API Key check moved to agent_service.chat() — only needed for LLM calls
    conversation_repo = ConversationRepository(db)
    skills_service = SkillsService(repository=SkillRepository(db))
    chart_repo = ChartRepository(db)
    cnki_service = getattr(request.app.state, "cnki_service", None)

    return AgentService(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        model=settings.DEEPSEEK_MODEL,
        conversation_repo=conversation_repo,
        skills_service=skills_service,
        cnki_service=cnki_service,
        chart_repo=chart_repo,
    )


# ── CNKI 服务依赖 ───────────────────────────────────────────

async def get_cnki_service(request: Request):
    """获取 CNKIService 单例（注入 CacheManager + CircuitBreaker）

    如果配置了 CNKI_MASTER_ENABLED，自动将 MCP 工具指向
    cnki-downloader Master 的 /search 端点。
    """
    from ..services.cnki_service import CNKIService
    from ..utils.cache import CacheManager
    from ..utils.circuit_breaker import cnki_circuit_breaker
    import structlog

    _logger = structlog.get_logger(__name__)

    if not hasattr(request.app.state, "cnki_service"):
        service = CNKIService(
            cache=CacheManager(default_ttl=1800),
            circuit_breaker=cnki_circuit_breaker,
        )

        # Auto-configure MCP bridge to cnki-downloader Master
        if settings.CNKI_MASTER_ENABLED:
            service.configure_mcp({
                "cnki_search": {
                    "endpoint": f"{settings.CNKI_MASTER_URL}/search",
                }
            })
            _logger.info(
                "CNKI MCP bridge configured → %s/search", settings.CNKI_MASTER_URL
            )

        request.app.state.cnki_service = service

    return request.app.state.cnki_service


# ── 多源学术搜索服务依赖 ─────────────────────────────────────

async def get_academic_search_service(request: Request):
    """获取 AcademicSearchService 单例

    组合 CNKIService / SemanticScholarService / ArxivService 三个底层服务，
    缓存在 app.state 上以避免重复创建。
    """
    if not hasattr(request.app.state, "academic_search_service"):
        from ..services.cnki_service import AcademicSearchService
        from ..services.semantic_scholar_service import SemanticScholarService
        from ..services.arxiv_service import ArxivService

        cnki_service = await get_cnki_service(request)
        request.app.state.academic_search_service = AcademicSearchService(
            cnki_service=cnki_service,
            semantic_scholar_service=SemanticScholarService(),
            arxiv_service=ArxivService(),
        )
    return request.app.state.academic_search_service


# ── 技能服务依赖 ────────────────────────────────────────────

async def get_skills_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """获取 SkillsService 实例（按请求创建，注入 repository）

    注意：不再使用单例模式，每次请求创建新的 service 实例。
    """
    from ..services.skills_service import SkillsService
    from ..db.repository.skill import SkillRepository

    repo = SkillRepository(db)
    return SkillsService(repository=repo)


# ── 图表服务依赖 ────────────────────────────────────────────

async def get_chart_service(request: Request):
    """获取图表服务（已有完善的静态服务，无需特殊注入）"""
    from ..services import chart_service
    return chart_service


# ── UnitOfWork 事务管理依赖 ─────────────────────────────────

async def get_uow(request: Request) -> AsyncGenerator[UnitOfWork, None]:
    """获取 UnitOfWork 实例（事务管理器）

    用法：
        @router.post("/example")
        async def example(uow: UnitOfWork = Depends(get_uow)):
            uow.conversations.add_message(...)
            uow.charts.save_record(...)
            await uow.commit()
    """
    session_factory = getattr(request.app.state, "db_session_factory", None)
    if session_factory is None:
        raise RuntimeError("Database session factory not initialized")
    async with UnitOfWork(session_factory) as uow:
        yield uow