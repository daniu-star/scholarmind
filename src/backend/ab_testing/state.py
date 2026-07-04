"""
Pipeline 状态定义 — 所有 Agent 共享的状态容器

使用 TypedDict 定义 LangGraph StateGraph 的共享状态,
每个 Agent 节点读取并更新其中的字段。
"""

from __future__ import annotations

from typing import TypedDict, Literal, Optional
from dataclasses import dataclass, field


# ── 数据类:UI 变体 ──
@dataclass
class UIVariant:
    """一个 UI 变体(A 或 B)"""
    variant_id: str                          # "A" | "B"
    description: str                         # 变体描述
    html_snippet: str                        # HTML 代码片段
    design_rationale: str                    # 设计理由
    target_metric: str                       # 目标指标(如"任务完成率")
    color_scheme: dict = field(default_factory=dict)   # 色彩方案
    layout_changes: list = field(default_factory=list)  # 布局变更点


# ── 数据类:用户评估结果 ──
@dataclass
class UserEvaluation:
    """单个 persona 对单个变体的评估"""
    persona_id: str                          # persona 标识
    persona_name: str                        # persona 名称
    variant_id: str                          # 评估的变体
    usability_score: float                   # 可用性评分 0-10
    aesthetics_score: float                  # 美观度评分 0-10
    clarity_score: float                     # 清晰度评分 0-10
    task_completion_score: float             # 任务完成度 0-10
    overall_score: float                     # 综合评分 0-10
    feedback: str                            # 文字反馈
    pain_points: list = field(default_factory=list)    # 痛点
    suggestions: list = field(default_factory=list)    # 建议


# ── 数据类:CoT 推理结果 ──
@dataclass
class CoTAnalysis:
    """CoT Agent 的推理分析结果"""
    reasoning_chain: list                    # 推理链(步骤列表)
    root_causes: list                        # 根因分析
    recommendations: list                    # 推荐改进
    confidence: float                        # 置信度 0-1
    variant_ranking: list                    # 变体排名 ["A", "B"]


# ── 数据类:PM 验收结果 ──
@dataclass
class AcceptanceResult:
    """PM Agent 的验收结果"""
    accepted: bool                           # 是否通过验收
    prd_compliance_score: float              # PRD 符合度 0-100
    passed_criteria: list                    # 通过的验收标准
    failed_criteria: list                    # 未通过的验收标准
    feedback: str                            # 验收反馈
    next_actions: list                       # 下一步行动


# ── 主状态容器 ──
class PipelineState(TypedDict, total=False):
    """LangGraph 共享状态"""

    # ── 输入 ──
    product_context: str                     # 产品背景描述
    current_ui_html: str                     # 当前 UI 的 HTML
    optimization_goals: list                 # 优化目标列表

    # ── PM Agent 输出 ──
    prd_document: str                        # PRD 文档(Markdown)
    acceptance_criteria: list                # 验收标准列表

    # ── 设计师 Agent 输出 ──
    variants: list                           # UIVariant 列表 [A, B]

    # ── 用户 Agent 输出 ──
    evaluations: list                        # UserEvaluation 列表
    variant_scores: dict                     # {"A": 8.2, "B": 7.5}

    # ── CoT Agent 输出 ──
    cot_analysis: Optional[CoTAnalysis]      # 推理分析结果

    # ── UI 规则检查器输出 ──
    rule_check_results: dict                 # {"A": {...}, "B": {...}}
    rule_violations: dict                    # {"A": [...], "B": [...]}

    # ── 产品教练 Agent 输出 ──
    coach_guidance: str                      # 教练指导
    iteration_needed: bool                   # 是否需要迭代
    iteration_count: int                     # 当前迭代次数

    # ── PM 验收输出 ──
    acceptance_result: Optional[AcceptanceResult]  # 验收结果

    # ── Pipeline 控制 ──
    max_iterations: int                      # 最大迭代次数(默认3)
    current_phase: str                       # 当前阶段
    error: Optional[str]                     # 错误信息
    history: list                            # 历史记录(每轮的摘要)


# ── 阶段标识 ──
Phase = Literal[
    "pm_prd",           # PM 撰写 PRD
    "designer",         # 设计师生成变体
    "user_eval",        # 用户评估
    "cot_analysis",     # CoT 推理
    "rule_check",       # 规则检查
    "coach",            # 教练引导
    "pm_acceptance",    # PM 验收
    "done",             # 完成
    "error",            # 错误
]
