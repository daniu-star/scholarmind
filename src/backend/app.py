"""
ScholarMind API 应用入口（v2.0 工厂函数模式）
使用企业级 6 层分层架构：
  middleware → core → models → db → routes → services
"""
from __future__ import annotations

import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.config import settings


def create_app() -> FastAPI:
    """应用工厂函数：组装全部中间件、路由、异常处理器"""

    # ── 核心基础设施 ──────────────────────────────────────────
    from src.backend.core.logging_config import configure_logging
    configure_logging()

    # ── 生命周期事件 ─────────────────────────────────────────
    from src.backend.core.events import startup, shutdown

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await startup(app)
        yield
        await shutdown(app)

    # ── 创建应用 ──────────────────────────────────────────────
    app = FastAPI(
        title="ScholarMind API",
        description="基于 RAG + Langgraph + 6层企业架构的智能学术研究助手",
        version="3.0.0",
        lifespan=lifespan,
    )
    app.debug = settings.DEBUG

    # ── 中间件层（按优先级顺序注册） ──────────────────────────
    from src.backend.middleware.request_id import RequestIDMiddleware
    from src.backend.middleware.logging import LoggingMiddleware
    from src.backend.middleware.rate_limit import RateLimitMiddleware
    from src.backend.middleware.redis_rate_limit import RedisRateLimitMiddleware
    from src.backend.middleware.error_handler import register_error_handlers
    from src.backend.core.logging_config import get_logger

    logger = get_logger(__name__)

    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(LoggingMiddleware)

    # 条件注册速率限制：优先使用 Redis 分布式限流，不可用时降级到内存令牌桶
    if settings.RATE_LIMIT_ENABLED:
        try:
            import redis
            r = redis.from_url(settings.REDIS_URL, socket_connect_timeout=1)
            r.ping()
            r.close()
            app.add_middleware(
                RedisRateLimitMiddleware,
                redis_url=settings.REDIS_URL,
                max_requests=settings.RATE_LIMIT_REQUESTS,
                window_seconds=60,
            )
            logger.info("redis_rate_limiter", status="enabled")
        except Exception:
            app.add_middleware(RateLimitMiddleware)
            logger.warning("redis_rate_limiter", status="unavailable", fallback="in_memory")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── 异常处理器 ───────────────────────────────────────────
    register_error_handlers(app)

    # ── 健康检查 ──────────────────────────────────────────────
    @app.get("/api/v1/health")
    async def health_check(request: Request):
        engine = getattr(request.app.state, "db_engine", None)
        pool_stats = {}
        if engine is not None:
            pool = engine.pool
            pool_stats = {
                "size": pool.size(),
                "checked_in": pool.checkedin(),
                "overflow": pool.overflow(),
                "total": pool.size() + pool.overflow(),
            }
        return {
            "status": "ok",
            "service": "ScholarMind API",
            "version": "3.0.0",
            "deepseek_connected": bool(settings.DEEPSEEK_API_KEY),
            "database": {"pool": pool_stats},
            "rate_limit_enabled": settings.RATE_LIMIT_ENABLED,
            "task_backend": settings.TASK_BACKEND,
        }

    # ── 路由注册 ──────────────────────────────────────────────
    from src.backend.routers import chart, upload, skills, knowledge, agent, ws
    from src.backend.core.metrics import get_metrics, set_app_info

    app.include_router(chart.router, prefix="/api/v1")
    app.include_router(upload.router, prefix="/api/v1")
    app.include_router(skills.router, prefix="/api/v1")
    app.include_router(knowledge.router, prefix="/api/v1")
    app.include_router(agent.router, prefix="/api/v1")
    app.include_router(ws.router, prefix="/api/v1")

    # ── Prometheus 监控指标端点 ──────────────────────────────
    @app.get("/metrics")
    async def metrics():
        return Response(content=get_metrics(), media_type="text/plain")

    # 设置应用信息
    set_app_info(version="3.0.0", environment="development")

    # ── 静态文件服务（原型预览） ──────────────────────────────
    prototypes_dir = PROJECT_ROOT / "prototypes"
    if prototypes_dir.exists():
        app.mount(
            "/app",
            StaticFiles(directory=str(prototypes_dir), html=True),
            name="prototypes",
        )

    return app


# 模块级 app 实例（uvicorn 入口）
app = create_app()