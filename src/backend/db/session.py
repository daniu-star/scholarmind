"""
ScholarMind 异步数据库引擎与会话工厂
支持 SQLite（开发）和 PostgreSQL（生产）两种后端
"""
from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy import create_engine as _create_sync_engine
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
    """创建异步 SQLAlchemy 引擎"""
    database_url = url or settings.DATABASE_URL
    return create_async_engine(
        database_url,
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_recycle=3600,
        pool_pre_ping=True,
    )


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
    """创建所有 ORM 表（开发用，生产用 Alembic）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)