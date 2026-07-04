"""论文审稿优化 Pipeline 路由

P0 Task 3.3：所有端点强制鉴权（get_current_user 返回 int user_id），
跨用户访问 review_id 返回 404（不暴露存在性）。
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.paper_review_service import get_paper_review_service, PaperReviewService
from ..core.exceptions import NotFoundError, ValidationError
# P0 Task 3.3：强制鉴权（替代 get_optional_user_id 可选鉴权）
from ..core.dependencies import get_current_user, get_db
from ..services.entitlement_service import EntitlementError, EntitlementService
from ..models.schemas.paper_review import (
    ReviewStartRequest,
    ReviewStartResponse,
    ReviewStatusResponse,
    ReviewResultResponse,
    ReviewListResponse,
)

router = APIRouter(prefix="/paper-review", tags=["paper-review"])


@router.post("/start", response_model=ReviewStartResponse)
async def start_review(
    request: ReviewStartRequest,
    service: PaperReviewService = Depends(get_paper_review_service),
    user_id: int = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """启动论文审稿优化 Pipeline

    P0 Task 3.3：强制鉴权，user_id 写入审稿任务状态用于后续所有权校验。

    基于 cyclical-paper-review 技能,9 Agent 循环式审稿优化:
    约束注入 → 外审专家 → 对抗评分 → 意见路由 → 并行修改 → 风格守卫 → 指令守卫 → 格式输出
    """
    try:
        reservation = await EntitlementService.consume_pipeline(
            db, user_id, request.pipeline_type
        )
    except EntitlementError as exc:
        raise HTTPException(
            status_code=402, detail={"code": exc.code, "message": exc.message}
        ) from exc
    try:
        result = await service.start_review(
            paper_text=request.paper_text,
            research_type=request.research_type,
            journal_style=request.journal_style,
            output_format=request.output_format,
            max_rounds=request.max_rounds,
            session_id=request.session_id,
            revision_focus=request.revision_focus,
            reviewer_comments=request.reviewer_comments,
            user_id=str(user_id),
        )
    except Exception:
        await EntitlementService.refund_pipeline(db, user_id, reservation)
        raise
    return {
        "success": True,
        "review_id": result["review_id"],
        "status": result["status"],
        "message": result["message"],
        "config": result["config"],
    }


@router.get("/{review_id}/status", response_model=ReviewStatusResponse)
async def get_review_status(
    review_id: str,
    service: PaperReviewService = Depends(get_paper_review_service),
    user_id: int = Depends(get_current_user),
):
    """查询审稿状态

    P0 Task 3.3：强制鉴权，跨用户访问返回 404。
    """
    status = await service.get_status(review_id, user_id=str(user_id))
    if not status:
        # 不存在或不属于当前用户 → 404
        raise NotFoundError("审稿任务", review_id)
    return {"success": True, **status}


@router.get("/{review_id}/result", response_model=ReviewResultResponse)
async def get_review_result(
    review_id: str,
    service: PaperReviewService = Depends(get_paper_review_service),
    user_id: int = Depends(get_current_user),
):
    """获取审稿最终结果

    P0 Task 3.3：强制鉴权，跨用户访问返回 404。
    """
    result = await service.get_result(review_id, user_id=str(user_id))
    if not result:
        raise NotFoundError("审稿任务", review_id)
    return {"success": True, **result}


@router.get("", response_model=ReviewListResponse)
async def list_reviews(
    session_id: Optional[str] = Query(default=None, description="按会话 ID 过滤"),
    service: PaperReviewService = Depends(get_paper_review_service),
    user_id: int = Depends(get_current_user),
):
    """列出当前用户的审稿任务

    P0 Task 3.3：强制鉴权，仅返回当前 user_id 名下的审稿任务。
    """
    reviews = await service.list_reviews(session_id=session_id, user_id=str(user_id))
    return {
        "success": True,
        "reviews": reviews,
        "total": len(reviews),
    }


@router.post("/{review_id}/cancel")
async def cancel_review(
    review_id: str,
    service: PaperReviewService = Depends(get_paper_review_service),
    user_id: int = Depends(get_current_user),
):
    """取消运行中的审稿任务

    P0 Task 3.3：强制鉴权，跨用户取消返回 404。
    """
    cancelled = await service.cancel_review(review_id, user_id=str(user_id))
    if not cancelled:
        raise NotFoundError("审稿任务", review_id)
    return {"success": True, "review_id": review_id, "cancelled": cancelled}
