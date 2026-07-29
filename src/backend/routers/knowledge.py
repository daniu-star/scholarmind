"""
ScholarMind 知识库 API 路由
多源学术搜索聚合、状态检查、热门关键词
"""

import asyncio
import structlog
from datetime import datetime

from fastapi import APIRouter, Depends

from ..services.cnki_service import AcademicSearchService
from ..models.schemas.knowledge import AcademicSearchRequest
from ..core.dependencies import get_academic_search_service
from ..core.exceptions import (
    AppException,
    CNKISearchFailedError,
    CNKIConnectionError,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("/academic/search")
async def academic_search(
    request: AcademicSearchRequest,
    academic_service: AcademicSearchService = Depends(get_academic_search_service),
):
    """多源学术搜索聚合检索

    并行查询 CNKI / Semantic Scholar / arXiv / CrossRef / PubMed，
    聚合去重后返回结果。
    """
    try:
        result = await academic_service.search_multi_source(
            query=request.query,
            count=request.count,
            source_filter=request.source_filter,
            year_filter=request.year_filter,
        )
        return result
    except AppException:
        raise
    except Exception as e:
        logger.exception("academic/search 端点调用失败")
        raise CNKISearchFailedError(str(e))


@router.get("/status")
async def get_knowledge_status(
    academic_service: AcademicSearchService = Depends(get_academic_search_service),
):
    """Get connection status of all knowledge bases

    调用 ``AcademicSearchService.check_status()`` 返回 5 个数据源的真实连通状态，
    不再返回假数据。聚合状态 ``status`` 取值：
    - ``connected``：全部数据源连通
    - ``partial``：部分数据源连通
    - ``disconnected``：全部数据源断开
    """
    try:
        status_payload = await academic_service.check_status()
        sources = status_payload.get("sources", status_payload)
        if not isinstance(sources, dict):
            sources = {}

        # 根据各数据源状态聚合出整体状态
        connected_count = sum(
            1 for info in sources.values() if isinstance(info, dict) and info.get("status") == "connected"
        )
        total = len(sources)
        if connected_count == total and total > 0:
            overall = "connected"
        elif connected_count == 0:
            overall = "disconnected"
        else:
            overall = "partial"

        return {
            "success": True,
            "status": overall,
            "sources": sources,
            "timestamp": datetime.now().isoformat(),
        }
    except AppException:
        raise
    except Exception as e:
        logger.exception("status 端点调用失败")
        raise CNKIConnectionError(f"状态检查失败: {str(e)}")


# ── 热门关键词端点 ────────────────────────────────────────


@router.get("/keywords/hot")
async def get_hot_keywords(limit: int = 20):
    """获取热门关键词"""
    try:
        from ..services.db_service import get_db_service

        db = get_db_service()
        safe_limit = max(1, min(limit, 200))
        keywords = await asyncio.to_thread(db.get_hot_keywords, limit=safe_limit)
        return {"success": True, "count": len(keywords), "keywords": keywords}
    except Exception as e:
        raise CNKIConnectionError(f"获取热门关键词失败: {str(e)}")
