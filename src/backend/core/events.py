"""
ScholarMind 应用生命周期事件管理
提供 async startup/shutdown 函数供 app.py 的 lifespan 调用
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ..config import settings
from .logging_config import configure_logging, get_logger

logger = get_logger(__name__)

# 项目根目录（alembic.ini 所在位置）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


async def startup(app: FastAPI) -> None:
    """应用启动初始化

    在 app.py 的 lifespan 中调用：
        async with asynccontextmanager(lifespan)(app):
            await startup(app)
            yield
            await shutdown(app)
    """
    configure_logging()
    logger.info("ScholarMind API starting up", version="3.0.0")

    # 确保目录存在
    settings.ensure_dirs()

    # 创建异步数据库引擎和会话工厂
    from ..db.session import create_async_engine_from_url, create_async_sessionmaker_from_engine

    engine = create_async_engine_from_url()
    session_factory = create_async_sessionmaker_from_engine(engine)

    # 存储到 app.state
    app.state.db_engine = engine
    app.state.db_session_factory = session_factory

    # 开发环境：使用 Alembic 迁移（替代 Base.metadata.create_all）
    try:
        from alembic.config import Config as AlembicConfig
        from alembic import command

        alembic_cfg = AlembicConfig(PROJECT_ROOT / "alembic.ini")
        command.upgrade(alembic_cfg, "head")
        logger.info("Alembic migration applied successfully")
    except Exception as e:
        logger.warning(f"Alembic migration failed, falling back to create_all: {e}")
        from ..db.session import init_db
        await init_db(engine)
        logger.info("ORM tables created/verified (fallback)")

    # 初始化预设技能（seeder）
    await _seed_preset_skills(session_factory)

    # 初始化现有的 DatabaseService（爬虫相关）
    from ..services.db_service import get_db_service
    db = get_db_service()
    logger.info("Database service (legacy SQLite) initialized")

    # 初始化 VectorService
    from ..services.vector_service import get_vector_service
    vector = get_vector_service()
    if vector.is_ready:
        logger.info("ChromaDB vector service initialized")
    else:
        logger.warning("ChromaDB vector service not available")

    logger.info(
        "ScholarMind startup complete",
        database=settings.DATABASE_URL.split("://")[0],
    )


async def shutdown(app: FastAPI) -> None:
    """应用优雅关闭"""
    logger.info("ScholarMind API shutting down")

    # 关闭 CNKI 服务（通过 app.state 访问）
    cnki = getattr(app.state, "cnki_service", None)
    if cnki is not None:
        try:
            await cnki.close()
        except Exception as e:
            logger.warning(f"Failed to close CNKI service: {e}")

    # 关闭旧版 DB 服务
    try:
        from ..services.db_service import get_db_service
        get_db_service().close()
    except Exception:
        pass

    # 关闭异步数据库连接池
    if hasattr(app.state, "db_engine") and app.state.db_engine is not None:
        await app.state.db_engine.dispose()
        logger.debug("ORM database engine disposed")

    logger.info("ScholarMind shutdown complete")


async def _seed_preset_skills(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """初始化预设技能数据（幂等）"""
    try:
        from ..db.repository.skill import SkillRepository
        from ..services.skills_service import PRESET_SKILLS

        async with session_factory() as session:
            repo = SkillRepository(session)

            # 将 PRESET_SKILLS 转换为 ORM 兼容格式
            presets = []
            for s in PRESET_SKILLS:
                presets.append({
                    "skill_id": s["id"],
                    "display_name": s["display_name"],
                    "description": s.get("description", ""),
                    "category": s.get("category", "custom"),
                    "enabled": s.get("enabled", True),
                    "agents": s.get("agents", []),
                    "triggers": s.get("triggers", []),
                    "rules": s.get("rules", ""),
                    "is_preset": True,
                })

            inserted = await repo.seed_preset_skills(presets)
            if inserted > 0:
                logger.info("Preset skills seeded", count=inserted)
            await session.commit()
    except Exception as e:
        logger.warning(f"Failed to seed preset skills: {e}")