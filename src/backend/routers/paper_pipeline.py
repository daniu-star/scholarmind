"""
论文生成 Pipeline 路由

提供 cyclical-paper-generation Pipeline 的启动、状态查询、结果获取 API。

P0 Task 3.3：所有端点强制鉴权（get_current_user 返回 int user_id），
跨用户访问 pipeline_id 返回 404（不暴露存在性）。
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from ..services.paper_pipeline_service import get_paper_pipeline_service
from ..models.schemas.paper_pipeline import (
    PipelineStartRequest,
    PipelineStartResponse,
    PipelineStatusResponse,
    PipelineResultResponse,
    PipelineListResponse,
)
from ..config import settings
from ..core.exceptions import NotFoundError
# P0 Task 3.3：强制鉴权（替代 get_optional_user_id 可选鉴权）
from ..core.dependencies import get_current_user, get_db
from ..services.entitlement_service import EntitlementError, EntitlementService
from ..core.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/paper-pipeline", tags=["paper-pipeline"])


@router.post("/start", response_model=PipelineStartResponse)
async def start_pipeline(
    request: PipelineStartRequest,
    user_id: int = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """启动论文生成 Pipeline

    P0 Task 3.3：强制鉴权，user_id 写入 pipeline 状态用于后续所有权校验。

    接收引导流程收集的数据，启动 13 Agent 循环式论文生成 Pipeline。
    Pipeline 在后台异步执行，返回 pipeline_id 用于后续状态查询。
    """
    # 开发模式：PAYMENT_ENABLED=false 时跳过额度检查，允许无限使用
    if settings.PAYMENT_ENABLED:
        try:
            reservation = await EntitlementService.consume_pipeline(
                db, user_id, "generation"
            )
        except EntitlementError as exc:
            raise HTTPException(
                status_code=402, detail={"code": exc.code, "message": exc.message}
            ) from exc
    else:
        reservation = {"consumed": "dev_mode", "capability": "generation"}

    service = get_paper_pipeline_service()
    try:
        result = await service.start_pipeline(
            session_id=request.session_id,
            agent_id=request.agent_id,
            guidance_data=request.guidance_data,
            discipline=request.discipline,
            research_type=request.research_type,
            journal_style=request.journal_style,
            max_rounds=request.max_rounds,
            pass_threshold=request.pass_threshold,
            user_id=str(user_id),
        )
    except Exception as e:
        await EntitlementService.refund_pipeline(db, user_id, reservation)
        logger.exception(f"pipeline_start_failed user_id={user_id} error={e}")
        # Distinguish LLM unavailability from other errors
        error_msg = str(e).lower()
        if any(kw in error_msg for kw in ["timeout", "connection", "unreachable", "refused", "api_key", "authenticate"]):
            raise HTTPException(
                status_code=503,
                detail={"code": "LLM_UNAVAILABLE", "message": "AI服务暂不可用，请稍后重试。Pipeline 依赖大语言模型，当前模型服务无法访问。"},
            ) from e
        raise HTTPException(
            status_code=503,
            detail={"code": "PIPELINE_START_FAILED", "message": f"Pipeline 启动失败: {str(e)}"},
        ) from e

    return PipelineStartResponse(
        pipeline_id=result["pipeline_id"],
        status=result["status"],
        message=result["message"],
        config=result["config"],
    )


@router.get("/{pipeline_id}/status", response_model=PipelineStatusResponse)
async def get_pipeline_status(
    pipeline_id: str,
    user_id: int = Depends(get_current_user),
):
    """查询 Pipeline 执行状态

    P0 Task 3.3：强制鉴权，跨用户访问返回 404。
    """
    service = get_paper_pipeline_service()
    status = await service.get_status(pipeline_id, user_id=str(user_id))
    if status is None:
        # 不存在或不属于当前用户 → 404（不暴露存在性）
        raise NotFoundError("Pipeline", pipeline_id)

    return PipelineStatusResponse(
        success=True,
        pipeline_id=status["pipeline_id"],
        status=status["status"],
        current_round=status["current_round"],
        max_rounds=status["max_rounds"],
        current_agent=status["current_agent"],
        current_step=status["current_step"],
        score=status["score"],
        pass_threshold=status["pass_threshold"],
        score_history=status["score_history"],
        progress=status["progress"],
        logs=status["logs"],
        error=status["error"],
        started_at=status["started_at"],
        completed_at=status["completed_at"],
    )


@router.get("/{pipeline_id}/result", response_model=PipelineResultResponse)
async def get_pipeline_result(
    pipeline_id: str,
    user_id: int = Depends(get_current_user),
):
    """获取 Pipeline 最终结果

    P0 Task 3.3：强制鉴权，跨用户访问返回 404。
    """
    service = get_paper_pipeline_service()
    result = await service.get_result(pipeline_id, user_id=str(user_id))
    if result is None:
        raise NotFoundError("Pipeline", pipeline_id)

    return PipelineResultResponse(
        success=True,
        pipeline_id=result["pipeline_id"],
        status=result["status"],
        final_score=result["final_score"],
        total_rounds=result["total_rounds"],
        paper_title=result["paper_title"],
        paper_content=result["paper_content"],
        dimension_scores=result["dimension_scores"],
        review_report=result["review_report"],
        output_path=result["output_path"],
        version_history=result["version_history"],
        message=result["message"],
    )


@router.get("", response_model=PipelineListResponse)
async def list_pipelines(
    session_id: Optional[str] = Query(default=None, description="按 session_id 过滤"),
    user_id: int = Depends(get_current_user),
):
    """列出当前用户的 Pipeline（可按 session_id 过滤）

    P0 Task 3.3：强制鉴权，仅返回当前 user_id 名下的 Pipeline。
    """
    service = get_paper_pipeline_service()
    pipelines = await service.list_pipelines(session_id=session_id, user_id=str(user_id))
    return PipelineListResponse(
        success=True,
        pipelines=pipelines,
        total=len(pipelines),
    )


@router.post("/{pipeline_id}/cancel")
async def cancel_pipeline(
    pipeline_id: str,
    user_id: int = Depends(get_current_user),
):
    """取消运行中的 Pipeline

    P0 Task 3.3：强制鉴权，跨用户取消返回 404。
    """
    service = get_paper_pipeline_service()
    cancelled = await service.cancel_pipeline(pipeline_id, user_id=str(user_id))
    if not cancelled:
        raise NotFoundError("Pipeline", pipeline_id)
    return {"success": True, "pipeline_id": pipeline_id, "cancelled": cancelled}
