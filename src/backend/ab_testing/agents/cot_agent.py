"""
CoT Agent — 链式推理分析

职责:
  基于用户评估结果,进行 Chain-of-Thought 推理分析,
  找出评分差异的根因,给出推荐和变体排名。

输入: 用户评估列表、变体评分、变体列表
输出: CoTAnalysis
"""

from __future__ import annotations

import json
import structlog

from ..llm_client import get_llm_client
from ..state import CoTAnalysis

logger = structlog.get_logger(__name__)

COT_SYSTEM_PROMPT = """\
你是一位数据分析专家,使用 Chain-of-Thought(链式推理)方法分析 A/B 测试结果。

你的任务:
1. 逐步推理分析用户评估数据
2. 找出变体间评分差异的根因
3. 给出数据驱动的推荐
4. 对变体进行排名

推理步骤:
Step 1: 数据概览 — 各变体的评分分布
Step 2: 维度分析 — 哪些维度差异最大
Step 3: Persona 分析 — 不同用户群体的偏好差异
Step 4: 根因分析 — 为什么某个变体表现更好/更差
Step 5: 置信度评估 — 数据是否足以支撑结论
Step 6: 推荐与排名 — 基于推理给出最终推荐

请以 JSON 格式输出:
{
  "reasoning_chain": ["Step 1: ...", "Step 2: ...", ...],
  "root_causes": ["根因1", "根因2", ...],
  "recommendations": ["推荐1", "推荐2", ...],
  "confidence": 0.0-1.0,
  "variant_ranking": ["A", "B"]
}
"""


async def cot_analyze(
    evaluations: list,
    variant_scores: dict[str, float],
    variants: list,
) -> CoTAnalysis:
    """
    CoT Agent 进行推理分析

    Args:
        evaluations: UserEvaluation 列表
        variant_scores: 变体评分汇总
        variants: UIVariant 列表

    Returns:
        CoTAnalysis
    """
    llm = get_llm_client()

    # 构建评估数据摘要
    eval_data = []
    for ev in evaluations:
        if hasattr(ev, "__dict__"):
            eval_data.append({
                "persona": ev.persona_name,
                "variant": ev.variant_id,
                "usability": ev.usability_score,
                "aesthetics": ev.aesthetics_score,
                "clarity": ev.clarity_score,
                "task_completion": ev.task_completion_score,
                "overall": ev.overall_score,
                "pain_points": ev.pain_points,
                "suggestions": ev.suggestions,
            })
        elif isinstance(ev, dict):
            eval_data.append(ev)

    variant_info = []
    for v in variants:
        if hasattr(v, "__dict__"):
            variant_info.append({
                "id": v.variant_id,
                "description": v.description,
                "rationale": v.design_rationale,
                "changes": v.layout_changes,
            })
        elif isinstance(v, dict):
            variant_info.append(v)

    user_prompt = (
        f"## 变体评分汇总\n{json.dumps(variant_scores, ensure_ascii=False)}\n\n"
        f"## 变体信息\n{json.dumps(variant_info, ensure_ascii=False, indent=2)}\n\n"
        f"## 用户评估详情\n{json.dumps(eval_data, ensure_ascii=False, indent=2)}\n\n"
        f"请使用 Chain-of-Thought 方法分析以上 A/B 测试结果。"
    )

    result = await llm.chat_completion_json(
        system_prompt=COT_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.3,
        max_tokens=2048,
    )

    analysis = CoTAnalysis(
        reasoning_chain=result.get("reasoning_chain", []),
        root_causes=result.get("root_causes", []),
        recommendations=result.get("recommendations", []),
        confidence=float(result.get("confidence", 0.5)),
        variant_ranking=result.get("variant_ranking", []),
    )

    logger.info(
        f"CoT analysis complete: confidence={analysis.confidence:.2f}, ranking={analysis.variant_ranking}"
    )
    return analysis
