"""
用户 Agent — 多 Persona 评估

职责:
  让多个用户 Persona(由 LLM 扮演)对每个 UI 变体进行评估,
  输出结构化的评分和反馈。

输入: UI 变体列表、Persona 列表
输出: UserEvaluation 列表
"""

from __future__ import annotations

import asyncio
import structlog

from ..llm_client import get_llm_client
from ..personas import Persona, ALL_PERSONAS
from ..state import UserEvaluation

logger = structlog.get_logger(__name__)

USER_EVAL_SYSTEM_PROMPT = """\
你正在扮演一个特定的用户角色,对 ScholarMind 的 UI 界面进行评估。

评估维度(每项 0-10 分):
1. usability_score (可用性): 界面是否易于操作,流程是否顺畅
2. aesthetics_score (美观度): 视觉设计是否吸引人,色彩搭配是否协调
3. clarity_score (清晰度): 信息层级是否清晰,文字是否易读
4. task_completion_score (任务完成度): 能否顺利完成核心任务
5. overall_score (综合评分): 整体使用体验

请严格按照你扮演的角色性格、技术水平和偏好来评分。
不要给出通用评价,要结合角色的具体痛点和需求。

请以 JSON 格式输出:
{
  "persona_id": "角色ID",
  "persona_name": "角色名",
  "variant_id": "变体ID",
  "usability_score": 0-10,
  "aesthetics_score": 0-10,
  "clarity_score": 0-10,
  "task_completion_score": 0-10,
  "overall_score": 0-10,
  "feedback": "详细的文字反馈(至少100字)",
  "pain_points": ["痛点1", "痛点2", ...],
  "suggestions": ["建议1", "建议2", ...]
}
"""


async def _evaluate_single(llm, persona: Persona, variant) -> UserEvaluation:
    """对单个 persona × variant 进行评估(并行任务单元)"""
    logger.info("User Agent: %s evaluating variant %s",
                persona.name, variant.variant_id)

    user_prompt = (
        f"## 你的角色设定\n"
        f"姓名: {persona.name}\n"
        f"角色: {persona.role}\n"
        f"学科: {persona.discipline}\n"
        f"技术水平: {persona.tech_savviness}\n"
        f"研究阶段: {persona.research_stage}\n"
        f"目标: {', '.join(persona.goals)}\n"
        f"痛点: {', '.join(persona.frustrations)}\n"
        f"偏好: {', '.join(persona.preferences)}\n\n"
        f"## 角色系统提示\n{persona.system_prompt}\n\n"
        f"## 待评估的 UI 变体\n"
        f"变体 ID: {variant.variant_id}\n"
        f"描述: {variant.description}\n"
        f"设计理由: {variant.design_rationale}\n"
        f"HTML 代码:\n{variant.html_snippet[:2000]}\n\n"
        f"请以 {persona.name} 的视角评估这个 UI 变体。"
    )

    result = await llm.chat_completion_json(
        system_prompt=USER_EVAL_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.6,
        max_tokens=2048,
    )

    evaluation = UserEvaluation(
        persona_id=result.get("persona_id", persona.persona_id),
        persona_name=result.get("persona_name", persona.name),
        variant_id=result.get("variant_id", variant.variant_id),
        usability_score=float(result.get("usability_score", 0)),
        aesthetics_score=float(result.get("aesthetics_score", 0)),
        clarity_score=float(result.get("clarity_score", 0)),
        task_completion_score=float(result.get("task_completion_score", 0)),
        overall_score=float(result.get("overall_score", 0)),
        feedback=result.get("feedback", ""),
        pain_points=result.get("pain_points", []),
        suggestions=result.get("suggestions", []),
    )
    return evaluation


async def user_evaluate_variants(
    variants: list,
    personas: list[Persona] | None = None,
) -> list[UserEvaluation]:
    """
    用户 Agent 对所有变体进行评估

    Args:
        variants: UIVariant 列表
        personas: Persona 列表(默认使用全部)

    Returns:
        UserEvaluation 列表(每个 persona × 每个变体)
    """
    if personas is None:
        personas = ALL_PERSONAS

    llm = get_llm_client()

    tasks = [_evaluate_single(llm, p, v) for p in personas for v in variants]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    evaluations = []
    for r in results:
        if isinstance(r, Exception):
            logger.error("Evaluation failed: %s", r)
        else:
            evaluations.append(r)

    logger.info("User Agent completed: %d evaluations", len(evaluations))
    return evaluations


def aggregate_variant_scores(evaluations: list[UserEvaluation]) -> dict[str, float]:
    """
    汇总各变体的平均评分

    Returns:
        {"A": 8.2, "B": 7.5}
    """
    scores: dict[str, list[float]] = {}
    for ev in evaluations:
        scores.setdefault(ev.variant_id, []).append(ev.overall_score)

    return {vid: sum(s) / len(s) for vid, s in scores.items() if s}
