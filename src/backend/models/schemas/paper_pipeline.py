"""
ScholarMind 论文生成 Pipeline Pydantic Schema
循环式论文生成 Pipeline 的请求/响应 DTO
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
Discipline = Literal[
    "communication", "journalism", "sociology", "psychology",
    "education", "literature", "history", "management", "economics",
]


class PipelineStartRequest(BaseModel):
    """启动论文生成 Pipeline 请求"""
    session_id: str = Field(..., min_length=1, max_length=128, description="会话唯一标识")
    agent_id: str = Field(
        default="researcher",
        min_length=1, max_length=64,
        description="发起 Pipeline 的 Agent ID（通常为 researcher）",
    )
    guidance_data: dict[str, Any] = Field(
        default_factory=dict,
        description="引导流程收集的数据（topic/angle/subject/method/discipline/research_type 等）",
    )
    discipline: Optional[Discipline] = Field(
        default=None, description="学科领域 ID"
    )
    research_type: Optional[ResearchType] = Field(
        default=None,
        description="研究类型",
    )
    journal_style: Optional[JournalStyle] = Field(
        default=None,
        description="目标期刊格式。不传则根据 discipline 自动映射。",
    )
    max_rounds: int = Field(default=5, ge=1, le=10, description="最大循环轮次")
    pass_threshold: int = Field(default=90, ge=60, le=100, description="通过分数阈值")

    @field_validator("guidance_data")
    @classmethod
    def _validate_guidance_data(cls, v: dict[str, Any]) -> dict[str, Any]:
        """引导数据至少需包含 topic 字段（非空字符串）"""
        if not isinstance(v, dict):
            raise ValueError("guidance_data 必须是对象")
        topic = v.get("topic")
        if not topic or not isinstance(topic, str) or not topic.strip():
            raise ValueError("guidance_data.topic 必须是非空字符串")
        if len(topic) > 200:
            raise ValueError("guidance_data.topic 长度不能超过 200 字符")
        return v

    @field_validator("session_id")
    @classmethod
    def _validate_session_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("session_id 不能为空白字符")
        return v.strip()


class PipelineStartResponse(BaseModel):
    """启动 Pipeline 响应"""
    success: bool = True
    pipeline_id: str = Field(..., description="Pipeline 实例唯一标识")
    status: str = Field(default="pending", description="初始状态")
    message: str = Field(default="Pipeline 已启动", description="提示消息")
    config: dict[str, Any] = Field(default_factory=dict, description="实际使用的配置")


class PipelineStatusResponse(BaseModel):
    """Pipeline 状态查询响应"""
    success: bool = True
    pipeline_id: str
    status: str = Field(..., description="pending/running/completed/failed")
    current_round: int = Field(default=0, description="当前轮次")
    max_rounds: int = Field(default=5, description="最大轮次")
    current_agent: Optional[str] = Field(default=None, description="当前执行的 Agent")
    current_step: Optional[str] = Field(default=None, description="当前步骤描述")
    score: Optional[int] = Field(default=None, description="当前评分")
    pass_threshold: int = Field(default=90, description="通过阈值")
    score_history: list[int] = Field(default_factory=list, description="历史评分")
    progress: float = Field(default=0.0, description="进度比例 0.0-1.0")
    logs: list[str] = Field(default_factory=list, description="执行日志")
    error: Optional[str] = Field(default=None, description="错误信息")
    started_at: Optional[str] = Field(default=None, description="开始时间 ISO")
    completed_at: Optional[str] = Field(default=None, description="完成时间 ISO")


class PipelineResultResponse(BaseModel):
    """Pipeline 结果响应"""
    success: bool = True
    pipeline_id: str
    status: str
    final_score: Optional[int] = Field(default=None, description="最终评分")
    total_rounds: int = Field(default=0, description="实际执行轮次")
    paper_title: Optional[str] = Field(default=None, description="论文标题")
    paper_content: Optional[str] = Field(default=None, description="论文最终内容（Markdown）")
    dimension_scores: dict[str, int] = Field(default_factory=dict, description="各维度评分")
    review_report: Optional[str] = Field(default=None, description="审稿报告")
    output_path: Optional[str] = Field(default=None, description="Word 文件路径（若生成）")
    version_history: list[dict] = Field(default_factory=list, description="版本历史")
    message: str = Field(default="Pipeline 结果获取成功")


class PipelineListResponse(BaseModel):
    """Pipeline 列表响应"""
    success: bool = True
    pipelines: list[dict[str, Any]]
    total: int
