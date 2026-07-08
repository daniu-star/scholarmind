"""
ScholarMind 异步数据库引擎与会话工厂
支持 SQLite（开发）和 PostgreSQL（生产）两种后端
"""
from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from ..config import settings


class Base(DeclarativeBase):
    """SQLAlchemy ORM 基类"""
    pass


def create_async_engine_from_url(url: str | None = None) -> AsyncEngine:
    """创建异步 SQLAlchemy 引擎

    自动将 postgresql:// 转为 postgresql+asyncpg://，兼容 Railway 注入的原始 URL。
    SQLite 引擎设置 busy_timeout=30s，避免并发写入时 database is locked 错误。
    """
    database_url = url or settings.DATABASE_URL
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    connect_args: dict = {}
    if "sqlite" in database_url:
        connect_args["timeout"] = 30  # SQLite 等待锁的最长时间（秒）

    engine = create_async_engine(
        database_url,
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_recycle=3600,
        pool_pre_ping=True,
        connect_args=connect_args if connect_args else None,
    )

    # SQLite: 为每个新连接启用 WAL 模式 + 外键约束
    if "sqlite" in database_url:
        from sqlalchemy import event
        @event.listens_for(engine.sync_engine, "connect")
        def _on_connect(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_async_sessionmaker_from_engine(
    engine: AsyncEngine | None = None,
) -> async_sessionmaker[AsyncSession]:
    """创建异步会话工厂"""
    if engine is None:
        engine = create_async_engine_from_url()
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def get_db(
    engine: AsyncEngine | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：获取数据库会话（上下文管理器）

    优先使用传入的 engine/session_factory（来自 app.state），
    避免每次请求创建新引擎。

    用法：
        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(Item))
            return result.scalars().all()
    """
    if session_factory is None:
        if engine is None:
            engine = create_async_engine_from_url()
        session_factory = create_async_sessionmaker_from_engine(engine)

    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db(engine: AsyncEngine) -> None:
    """创建所有 ORM 表（仅作为 Alembic 不可用时的兜底方案）。

    P0 修复: 所有手动 _migrate_* 函数已转为正规 Alembic 迁移脚本:
      - c4ddc7870a8f_init.py           → conversations, skills, chart_records
      - e7b1a2c3d4f5_accounts_*.py     → users, user_quotas, orders, entitlement_grants
      - m3_verification_email_qr.py    → verification_codes, email, payment QR

    正常情况下 Alembic 在 startup 事件中运行。此函数仅在新安装且 Alembic 失败的
    极端情况下兜底创建完整 schema。
    """
    # 确保所有 ORM 模型已加载到 Base.metadata
    from ..models.orm import (  # noqa: F401
        Conversation, Skill, ChartRecord,
        User, UserQuota, Order, EntitlementGrant, VerificationCode,
        AdminAuditLog, AgentExecutionLog, LoginAttempt,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

