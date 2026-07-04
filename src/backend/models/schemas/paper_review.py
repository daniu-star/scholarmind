"""
ScholarMind 论文审稿优化 Pipeline Pydantic Schema
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ── 枚举约束 ──────────────────────────────────────────────
ResearchType = Literal[
    "quantitative", "qualitative", "mixed",
    "computational", "theoretical", "interview_report",
]
JournalStyle = Literal["xwycbyj", "gjxwj", "xwdx", "shxyj"]
OutputFormat = Literal["docx", "md", "txt", "word", "markdown"]
RevisionFocus = Literal[
    "全面优化", "针对评审意见修改", "提升理论深度",
    "改善研究方法", "降低AIGC检测率", "格式规范化",
]


class ReviewStartRequest(BaseModel):
    """启动审稿请求"""
    paper_text: str = Field(..., min_length=10, max_length=200000, description="论文全文文本（10 ~ 200000 字符）")
    research_type: Optional[ResearchType] = Field(
        default=None,
        description="研究类型",
    )
    journal_style: Optional[JournalStyle] = Field(
        default=None,
        description="期刊格式",
    )
    output_format: OutputFormat = Field(default="docx", description="输出格式")
    max_rounds: int = Field(default=5, ge=1, le=10, description="最大循环轮次")
    session_id: Optional[str] = Field(default=None, max_length=128, description="关联会话 ID")
    revision_focus: Optional[RevisionFocus] = Field(
        default=None,
        description="修改重点",
    )
    reviewer_comments: Optional[str] = Field(
        default=None, max_length=50000,
        description="评审意见原文(若 revision_focus 为'针对评审意见修改')",
    )
    pipeline_type: Literal["external_review", "modification"] = Field(
        default="modification",
        description="快速通道类型：专家修订或一键修改",
    )

    @field_validator("paper_text")
    @classmethod
    def _validate_paper_text(cls, v: str) -> str:
        """论文文本不能全为空白"""
        if not v.strip():
            raise ValueError("paper_text 不能全为空白字符")
        return v

    @field_validator("reviewer_comments")
    @classmethod
    def _validate_reviewer_comments(cls, v):
        """若 revision_focus 为 '针对评审意见修改'，则 reviewer_comments 必须非空"""
        return v


class ReviewStartResponse(BaseModel):
    """启动审稿响应"""
    success: bool = True
    review_id: str
    status: str
    message: str
    config: dict[str, Any]


class ReviewStatusResponse(BaseModel):
    """审稿状态响应"""
    success: bool = True
    review_id: str
    status: str
    current_round: int = 0
    max_rounds: int = 5
    current_agent: Optional[str] = None
    current_step: Optional[str] = None
    score: Optional[float] = None
    score_history: list[float] = []
    progress: int = 0
    logs: list[str] = []
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class ReviewResultResponse(BaseModel):
    """审稿结果响应"""
    success: bool = True
    review_id: str
    status: str
    result: Optional[dict[str, Any]] = None
    score: Optional[float] = None
    score_history: list[float] = []
    config: Optional[dict[str, Any]] = None
    logs: list[str] = []


class ReviewListResponse(BaseModel):
    """审稿列表响应"""
    success: bool = True
    reviews: list[dict[str, Any]]
    total: int = 0
