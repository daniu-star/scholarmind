"""
ScholarMind 依赖注入
FastAPI Depends 依赖注入中心，管理所有服务的生命周期
"""
from __future__ import annotations

from typing import AsyncGenerator

from fastapi import Request, Depends
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
    """获取 CNKIService 单例（注入 CacheManager + CircuitBreaker）"""
    from ..services.cnki_service import CNKIService
    from ..utils.cache import CacheManager
    from ..utils.circuit_breaker import cnki_circuit_breaker

    if not hasattr(request.app.state, "cnki_service"):
        request.app.state.cnki_service = CNKIService(
            cache=CacheManager(default_ttl=1800),
            circuit_breaker=cnki_circuit_breaker,
        )
    return request.app.state.cnki_service


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