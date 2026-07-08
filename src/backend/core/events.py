"""
ScholarMind 应用生命周期事件管理
提供 async startup/shutdown 函数供 app.py 的 lifespan 调用
"""
from __future__ import annotations

import secrets
from pathlib import Path
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import settings
from .logging_config import configure_logging, get_logger

logger = get_logger(__name__)

# 项目根目录与 Alembic 配置位置
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


async def _ensure_schema_columns(engine) -> None:
    """自动补全数据库中缺失的列。

    使用原始 SQL 直接执行 ALTER TABLE，避免 SQLAlchemy inspector 兼容性问题。
    任何异常都被静默捕获，不阻止应用启动。
    """
    from sqlalchemy import text as sa_text

    # 列定义：(表名, 列名, SQL类型, 默认值)
    migrations = [
        ("users", "email", "VARCHAR(128)", None),
        ("users", "email_verified", "BOOLEAN", "FALSE"),
        ("users", "failed_login_attempts", "INTEGER", "0"),
        ("users", "locked_until", "TIMESTAMP WITH TIME ZONE", None),
    ]

    try:
        async with engine.connect() as conn:
            for table, col, col_type, default_val in migrations:
                default_clause = f" DEFAULT {default_val}" if default_val else ""
                try:
                    sql = f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}{default_clause}'
                    await conn.execute(sa_text(sql))
                    await conn.commit()
                    logger.info(f"schema_auto_fix: ensured {table}.{col} exists")
                except Exception:
                    # PostgreSQL 旧版不支持 IF NOT EXISTS，回退标准语法
                    try:
                        sql2 = f'ALTER TABLE {table} ADD COLUMN {col} {col_type}{default_clause}'
                        await conn.execute(sa_text(sql2))
                        await conn.commit()
                        logger.info(f"schema_auto_fix: added {table}.{col}")
                    except Exception:
                        pass  # 列已存在或其他非致命错误
    except Exception as e:
        logger.warning(f"schema_auto_fix non-fatal failure: {e}")


async def startup(app: FastAPI) -> None:
    """应用启动初始化

    在 app.py 的 lifespan 中调用：
        async with asynccontextmanager(lifespan)(app):
            await startup(app)
            yield
            await shutdown(app)
    """
    # P1 Task 14：在 configure_logging 前创建 logs/ 目录，供 RotatingFileHandler 落盘
    Path("logs").mkdir(parents=True, exist_ok=True)
    configure_logging()
    # Task 16.3: dev 环境自动生成临时 JWT 密钥（生产环境已由 validate_production 拦截）
    # 必须在 validate_production() 之前执行：dev 环境填充空值，生产环境留空触发校验失败。
    if not settings.JWT_SECRET_KEY:
        if settings.ENVIRONMENT != "production":
            settings.JWT_SECRET_KEY = secrets.token_urlsafe(32)
            logger.warning("JWT_SECRET_KEY not set, generated temporary key for dev environment")
        # 生产环境落入下方 validate_production() 抛 RuntimeError
    # P0 修复：生产环境安全校验移至 startup 事件（避免模块导入时副作用）
    settings.validate_production()
    logger.info(f"ScholarMind API starting up version={settings.VERSION} environment={settings.ENVIRONMENT}")

    # 确保目录存在
    settings.ensure_dirs()

    # 创建异步数据库引擎和会话工厂
    from ..db.session import create_async_engine_from_url, create_async_sessionmaker_from_engine

    engine = create_async_engine_from_url()
    session_factory = create_async_sessionmaker_from_engine(engine)

    # 存储到 app.state
    app.state.db_engine = engine
    app.state.db_session_factory = session_factory
    # LLM 连通性标志：由后台探测线程设置，默认 False（健康检查读取此字段）
    app.state.llm_reachable = False

    # 开发环境：使用 Alembic 迁移（替代 Base.metadata.create_all）
    try:
        from alembic.config import Config as AlembicConfig
        from alembic import command

        alembic_cfg = AlembicConfig(str(ALEMBIC_INI))
        command.upgrade(alembic_cfg, "head")
        logger.info("Alembic migration applied successfully")
    except Exception as e:
        logger.warning(f"Alembic migration failed, falling back to create_all: {e}")
        from ..db.session import init_db
        await init_db(engine)
        logger.info("ORM tables created/verified (fallback)")

    # 自动修复缺失的数据库列（Alembic 不可用时，create_all 不会修改已有表）
    await _ensure_schema_columns(engine)

    # 初始化预设技能（seeder）
    await _seed_preset_skills(session_factory)

    # 初始化现有的 DatabaseService（爬虫相关）
    from ..services.db_service import get_db_service
    get_db_service()
    logger.info("Database service (legacy SQLite) initialized")

    # VectorService 后台预热（fire-and-forget，不阻塞 startup）
    # 首次启动需下载 paraphrase-multilingual-MiniLM-L12-v2 (~470MB)，
    # 即便走 hf-mirror.com 镜像仍需 30-60s。改为后台线程预热：
    # startup 立即完成 → 端口秒级监听 → 对话功能立即可用；
    # RAG 检索在模型加载完后自动可用（首次 RAG 调用若未就绪会触发懒加载）。
    import threading
    from ..services.vector_service import get_vector_service

    def _prewarm_vector() -> None:
        try:
            vector = get_vector_service()
            if vector.is_ready:
                logger.info("ChromaDB vector service initialized (background prewarm)")
            else:
                logger.warning("ChromaDB vector service not available (degraded mode)")
        except Exception as e:
            logger.warning(f"VectorService prewarm failed: {e}. RAG will lazy-init on first use.")

    threading.Thread(target=_prewarm_vector, daemon=True, name="vector-prewarm").start()
    logger.info("VectorService prewarm dispatched to background thread")

    # 安装 Pipeline LLM Bridge（将后端 llm_client 注入到两个技能的 Pipeline）
    try:
        from ..utils.pipeline_llm_bridge import install_bridge_to_skills
        install_bridge_to_skills()
    except Exception as e:
        logger.warning(f"Failed to install pipeline LLM bridge: {e}")

    # ── DeepSeek LLM 连通性后台探测（fire-and-forget，不阻塞 startup）──
    # 健康检查的 llm_reachable 字段依赖此探测结果。探测用 1-token 请求，
    # 10s 超时；成功则置 app.state.llm_reachable = True。
    import asyncio
    from ..utils.llm_client import llm_client

    async def _probe_deepseek() -> None:
        try:
            resp = await asyncio.wait_for(
                llm_client.chat(
                    system="ok",
                    user="ping",
                    temperature=0.0,
                    max_tokens=1,
                    model=settings.DEEPSEEK_MODEL,
                ),
                timeout=10.0,
            )
            # 能拿到响应即视为可达
            app.state.llm_reachable = bool(resp and (resp.content or resp))
            logger.info(f"deepseek_probe_ok model={settings.DEEPSEEK_MODEL} reachable={app.state.llm_reachable}")
        except asyncio.TimeoutError:
            logger.warning("deepseek_probe_timeout (>10s), llm_reachable stays False")
        except Exception as e:
            logger.warning(f"deepseek_probe_failed type={type(e).__name__} err={e} llm_reachable stays False")

    asyncio.create_task(_probe_deepseek())
    logger.info("DeepSeek connectivity probe dispatched to background task")

    # ── PaymentPoller 启动（后台 24/7 订单追踪） ──
    try:
        from ..services.payment_poller import init_payment_poller
        poller = init_payment_poller(session_factory)
        await poller.start()
        app.state.payment_poller = poller
        logger.info("PaymentPoller started (background order tracking)")
    except Exception as e:
        logger.warning(f"Failed to start PaymentPoller: {e}")

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

    # 关闭 Redis 连接
    try:
        from ..utils.redis_client import close_redis
        await close_redis()
    except Exception as e:
        logger.warning(f"Failed to close Redis: {e}")

    # 卸载 Pipeline LLM Bridge
    try:
        from ..utils.pipeline_llm_bridge import uninstall_bridge_from_skills
        uninstall_bridge_from_skills()
    except Exception as e:
        logger.warning(f"Failed to uninstall pipeline LLM bridge: {e}")

    # 关闭旧版 DB 服务
    try:
        from ..services.db_service import get_db_service
        get_db_service().close()
    except Exception:
        pass

    # 关闭 PaymentPoller
    poller = getattr(app.state, "payment_poller", None)
    if poller is not None:
        try:
            await poller.stop()
            logger.info("PaymentPoller stopped")
        except Exception as e:
            logger.warning(f"Failed to stop PaymentPoller: {e}")

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
                logger.info(f"Preset skills seeded count={inserted}")
            await session.commit()
    except Exception as e:
        logger.warning(f"Failed to seed preset skills: {e}")
