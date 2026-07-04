"""
产品教练 Agent — 引导迭代

职责:
  基于用户评估、CoT 分析和规则检查结果,
  给出下一轮迭代的方向性指导。

输入: CoT 分析、规则检查结果、当前迭代次数
输出: 教练指导文本、是否需要继续迭代
"""

from __future__ import annotations

import json
import structlog

from ..llm_client import get_llm_client

logger = structlog.get_logger(__name__)

COACH_SYSTEM_PROMPT = """\
你是一位资深产品教练,正在指导 ScholarMind 的 UI/UX 迭代优化。

你的职责:
1. 分析当前轮次的评估结果和 CoT 推理
2. 判断是否需要继续迭代
3. 如果需要迭代,给出具体的改进方向

判断是否需要迭代的标准:
- 变体评分均低于 7.0 → 需要迭代
- PRD 符合度低于 80% → 需要迭代
- 存在严重 UI 规则违规 → 需要迭代
- 两个变体评分差异过小(<0.5) → 需要迭代以增大差异
- 已达到最大迭代次数 → 停止迭代

请以 JSON 格式输出:
{
  "coach_guidance": "具体的改进指导(如果需要迭代)",
  "iteration_needed": true/false,
  "iteration_count": 当前迭代次数+1(如果需要迭代),
  "priority_fixes": ["优先修复项1", "优先修复项2", ...],
  "encouragement": "对团队的鼓励语"
}
"""


async def coach_guide(
    cot_analysis: dict | object,
    rule_check_results: dict,
    variant_scores: dict[str, float],
    evaluations: list,
    iteration_count: int,
    max_iterations: int = 3,
) -> dict:
    """
    产品教练 Agent 给出迭代指导

    Args:
        cot_analysis: CoT 分析结果
        rule_check_results: 规则检查结果
        variant_scores: 变体评分
        evaluations: 用户评估列表
        iteration_count: 当前迭代次数
        max_iterations: 最大迭代次数

    Returns:
        {
            "coach_guidance": str,
            "iteration_needed": bool,
            "iteration_count": int,
            "priority_fixes": list,
            "encouragement": str,
        }
    """
    llm = get_llm_client()

    # 序列化 CoT 分析
    if hasattr(cot_analysis, "__dict__"):
        cot_data = {
            "root_causes": cot_analysis.root_causes,
            "recommendations": cot_analysis.recommendations,
            "confidence": cot_analysis.confidence,
            "variant_ranking": cot_analysis.variant_ranking,
        }
    else:
        cot_data = cot_analysis or {}

    # 评估摘要
    eval_summary = []
    for ev in evaluations:
        if hasattr(ev, "__dict__"):
            eval_summary.append({
                "persona": ev.persona_name,
                "variant": ev.variant_id,
                "overall": ev.overall_score,
                "pain_points": ev.pain_points[:3],
            })
        elif isinstance(ev, dict):
            eval_summary.append(ev)

    user_prompt = (
        f"## 当前迭代次数: {iteration_count}/{max_iterations}\n\n"
        f"## 变体评分\n{json.dumps(variant_scores, ensure_ascii=False)}\n\n"
        f"## CoT 分析\n{json.dumps(cot_data, ensure_ascii=False, indent=2)}\n\n"
        f"## UI 规则检查\n{json.dumps(rule_check_results, ensure_ascii=False, indent=2)[:2000]}\n\n"
        f"## 用户评估摘要\n{json.dumps(eval_summary, ensure_ascii=False, indent=2)}\n\n"
        f"请给出迭代指导。"
    )

    result = await llm.chat_completion_json(
        system_prompt=COACH_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.5,
        max_tokens=2048,
    )

    # 强制检查最大迭代次数
    if iteration_count >= max_iterations:
        result["iteration_needed"] = False
        result["coach_guidance"] = result.get("coach_guidance", "") + "\n\n(已达最大迭代次数,停止迭代)"

    logger.info(
        f"Coach guidance: iteration_needed={result.get('iteration_needed')}, count={result.get('iteration_count')}"
    )
    return result
