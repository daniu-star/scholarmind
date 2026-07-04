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
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.config import settings  # noqa: E402


def _is_placeholder_key(key: str) -> bool:
    """判断 API key 是否为占位符（未配置真实密钥）

    占位符特征：含 YOUR_ / _HERE / REPLACE / xxxx / 全 x / 明显的示例 key
    """
    if not key:
        return True
    k = key.strip()
    if not k:
        return True
    upper = k.upper()
    if "YOUR_" in upper or "_HERE" in upper or "REPLACE" in upper or "XXXX" in upper:
        return True
    # 全 x（如 xxxxxxxxxxxxxx）
    if set(k.replace("-", "").replace("_", "")) == {"x"}:
        return True
    return False


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
        version=settings.VERSION,
        lifespan=lifespan,
    )
    app.debug = settings.DEBUG

    # ── 中间件层（按优先级顺序注册） ──────────────────────────
    from src.backend.middleware.request_id import RequestIDMiddleware
    from src.backend.middleware.logging import LoggingMiddleware
    from src.backend.middleware.redis_rate_limit import RedisRateLimitMiddleware
    from src.backend.middleware.rate_limit import RateLimitMiddleware
    from src.backend.middleware.error_handler import register_error_handlers
    from src.backend.core.logging_config import get_logger

    logger = get_logger(__name__)

    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(LoggingMiddleware)

    # 速率限制中间件（P0 Task 6.6）：
    # 统一注册 RedisRateLimitMiddleware，其内部始终持有本地 LRU+TTL fallback
    # （Task 6.1），Redis 不可用时按端点成本分级降级（Task 6.4）。
    # 不同端点成本权重在 redis_rate_limit.PATH_COST_WEIGHTS 中定义：
    #   /agent/chat、/code-execution/run          cost=10（限额 = base // 10）
    #   /paper-pipeline/start、/paper-review/start cost=5
    #   /upload                                    cost=3
    #   /knowledge/search、/auth/login、/ws/chat   cost=2
    #   其余端点                                   cost=1（即 base）
    # 高成本端点（agent/chat、code-execution/run、paper-pipeline/start、payment/*）
    # 在 Redis 断开时 fail closed（503）；普通端点降级本地限流。
    if settings.RATE_LIMIT_ENABLED:
        app.add_middleware(
            RedisRateLimitMiddleware,
            redis_url=settings.REDIS_URL,
            max_requests=settings.RATE_LIMIT_REQUESTS,
            window_seconds=60,
        )
        # Task 6.7：WebSocket accept 前限流使用独立的内存令牌桶
        # （P0 阶段 WS 建连做 IP/user_id 级计数；与 HTTP Redis 限流器分离，
        # 互不影响；限额 = base // 2 以匹配 /ws/chat 的 cost=2 权重）
        ws_limit = max(1, settings.RATE_LIMIT_REQUESTS // 2)
        app.state.ws_rate_limiter = RateLimitMiddleware(
            app=app,
            max_requests=ws_limit,
            window_seconds=60,
        )
        logger.info(
            f"rate_limiter registered backend=redis fallback=memory "
            f"base_requests={settings.RATE_LIMIT_REQUESTS} "
            f"ws_limit={ws_limit}"
        )

    cors_origins = settings.get_cors_origins()
    cors_credentials = settings.get_cors_allow_credentials()
    # P2 修复: HTTP 响应压缩 (JSON/Text)，减少传输体积 60-85%
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=cors_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # CORS 配置日志警告
    if cors_origins == ["*"]:
        logger.warning(
            "cors_wildcard_enabled",
            environment=settings.ENVIRONMENT,
            credentials=cors_credentials,
            message="CORS 允许所有来源(*) 且 credentials=False，仅应在本地开发使用",
        )
    else:
        logger.info(
            "cors_configured",
            origins_count=len(cors_origins),
            credentials=cors_credentials,
            environment=settings.ENVIRONMENT,
        )

    # ── 异常处理器 ───────────────────────────────────────────
    register_error_handlers(app)

    # ── 健康检查与就绪探测 ──────────────────────────────────
    # P1 修复: 分离 liveness（进程存活）和 readiness（DB/Redis 可用）
    @app.get("/api/v1/health")
    @app.get("/api/v1/healthz")  # liveness: 仅检查进程存活
    async def health_check(request: Request):
        return {
            "status": "ok",
            "service": "ScholarMind API",
            "version": settings.VERSION,
            "environment": settings.ENVIRONMENT,
        }

    @app.get("/api/v1/readyz")  # readiness: 检查 DB 连通性
    async def readiness_check(request: Request):
        engine = getattr(request.app.state, "db_engine", None)
        session_factory = getattr(request.app.state, "db_session_factory", None)
        db_ok = False
        pool_stats = {}
        if engine is not None:
            pool = engine.pool
            pool_stats = {
                "size": pool.size(),
                "checked_in": pool.checkedin(),
                "overflow": pool.overflow(),
                "total": pool.size() + pool.overflow(),
            }
        if session_factory is not None:
            try:
                from sqlalchemy import text as sa_text
                async with session_factory() as session:
                    await session.execute(sa_text("SELECT 1"))
                db_ok = True
            except Exception:
                pass
        return {
            "status": "ok" if db_ok else "degraded",
            "service": "ScholarMind API",
            "version": settings.VERSION,
            "environment": settings.ENVIRONMENT,
            "llm_reachable": getattr(request.app.state, "llm_reachable", False),
            "database": {"connected": db_ok, "pool": pool_stats},
            "rate_limit_enabled": settings.RATE_LIMIT_ENABLED,
            "task_backend": settings.TASK_BACKEND,
        }

    # ── 路由注册 ──────────────────────────────────────────────
    # P2-T2 死路由清理时误删了 upload 路由，但前端仍在调用 /api/v1/upload，
    # 导致 404 被前端统一报为"后端未启动"。现已恢复（routers/upload.py）。
    from src.backend.routers import knowledge, agent, ws, paper_pipeline, paper_review, code_execution, auth, payment, export, writing, upload
    from src.backend.core.metrics import get_metrics, set_app_info

    app.include_router(knowledge.router, prefix="/api/v1")
    app.include_router(agent.router, prefix="/api/v1")
    app.include_router(ws.router, prefix="/api/v1")
    app.include_router(paper_pipeline.router, prefix="/api/v1")
    app.include_router(paper_review.router, prefix="/api/v1")
    # P0 Task 1.2: 代码执行 Router 默认关闭（CODE_EXECUTION_ENABLED=False），
    # 仅当显式启用时注册；即便启用，路由内部仍强制 require_admin 鉴权。
    if settings.CODE_EXECUTION_ENABLED:
        app.include_router(code_execution.router, prefix="/api/v1")
        logger.info(f"code execution enabled={settings.CODE_EXECUTION_ENABLED}")
    else:
        logger.info(f"code execution enabled={settings.CODE_EXECUTION_ENABLED}")
    app.include_router(auth.router, prefix="/api/v1")
    # 产品目录与订单状态始终可见；未配置商户凭证时，下单返回明确的 503。
    # 回调端点始终存在但在 PAYMENT_ENABLED=false 时拒绝处理。
    app.include_router(payment.router, prefix="/api/v1")
    logger.info(f"payment enabled={settings.PAYMENT_ENABLED}")
    app.include_router(export.router, prefix="/api/v1")
    app.include_router(writing.router, prefix="/api/v1")
    app.include_router(upload.router, prefix="/api/v1")

    # ── Prometheus 监控指标端点 ──────────────────────────────
    @app.get("/metrics")
    async def metrics():
        return Response(content=get_metrics(), media_type="text/plain")

    # 设置应用信息
    set_app_info(version=settings.VERSION, environment=settings.ENVIRONMENT)

    # ── 静态文件服务（原型预览） ──────────────────────────────
    prototypes_dir = PROJECT_ROOT / "prototypes"
    if prototypes_dir.exists():
        app.mount(
            "/app",
            StaticFiles(directory=str(prototypes_dir), html=True),
            name="prototypes",
        )

    # ── 个人收款码静态文件 ────────────────────────────────────
    qr_dir = Path(__file__).resolve().parent / "data" / "personal_qr"
    if qr_dir.exists():
        app.mount(
            "/static/qr",
            StaticFiles(directory=str(qr_dir)),
            name="personal_qr",
        )

    return app


# P0 修复: 移除模块级 app 单例（避免导入副作用），改用 uvicorn --factory 模式。
# 启动方式: uvicorn src.backend.app:create_app --factory --host 0.0.0.0 --port 8000
# 或: python -m src.backend.main（详见 src/backend/main.py）
# P0 Task 29: __main__ 块已删除以避免与 main.py 出现 reload 配置分叉；main.py 为唯一入口。
