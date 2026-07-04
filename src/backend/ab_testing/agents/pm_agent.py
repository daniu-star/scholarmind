"""
PM Agent — 产品经理 Agent

职责:
  1. 撰写 PRD 文档(产品需求文档),定义优化目标和验收标准
  2. 在 Pipeline 末端进行验收,检查是否符合 PRD

输入: 产品背景、当前 UI、优化目标
输出: PRD 文档(Markdown)、验收标准列表
验收输出: AcceptanceResult
"""

from __future__ import annotations

import json
import structlog
from datetime import datetime, timezone

from ..llm_client import get_llm_client
from ..state import AcceptanceResult

logger = structlog.get_logger(__name__)

# ── 系统提示词:撰写 PRD ──
PRD_SYSTEM_PROMPT = """\
你是一位资深产品经理,正在为 ScholarMind(智能学术研究助手)撰写 PRD 文档。

ScholarMind 是一款基于 RAG + LangGraph + DeepSeek 的学术研究助手产品,包含:
- 6个Agent(研究员、审查员、架构师、综述员、润色员、自定义 Agent)
- 三列布局(左侧边栏 + 中央对话 + 右侧信息栏)
- 深色主题,绿色(#4A8C50)为强调色
- 支持文献检索、图表生成、论文润色等功能

你的任务:
1. 分析当前 UI/UX 问题(基于提供的背景信息)
2. 定义本次优化的产品目标
3. 制定详细的验收标准(可量化)
4. 输出结构化的 PRD 文档(Markdown 格式)

PRD 文档结构:
## 1. 产品背景
## 2. 问题分析
## 3. 优化目标
## 4. 用户场景
## 5. 功能需求
## 6. 非功能需求
## 7. 验收标准(必须可量化,如"任务完成率≥85%")
## 8. 优先级排序

请以 JSON 格式输出:
{
  "prd_document": "完整的 PRD Markdown 文档",
  "acceptance_criteria": ["标准1", "标准2", ...]
}
"""


# ── 系统提示词:验收 ──
ACCEPTANCE_SYSTEM_PROMPT = """\
你是一位资深产品经理,正在对 ScholarMind 的 UI/UX 优化结果进行验收。

你需要对照 PRD 文档中的验收标准,检查优化结果是否达标。

验收流程:
1. 逐条检查验收标准
2. 评估 PRD 符合度(0-100分)
3. 列出通过和未通过的标准
4. 给出下一步行动建议

请以 JSON 格式输出:
{
  "accepted": true/false,
  "prd_compliance_score": 0-100,
  "passed_criteria": ["通过的标准1", ...],
  "failed_criteria": ["未通过的标准1", ...],
  "feedback": "验收反馈",
  "next_actions": ["行动1", ...]
}
"""


async def pm_write_prd(
    product_context: str,
    current_ui_html: str,
    optimization_goals: list[str],
) -> dict:
    """
    PM Agent 撰写 PRD 文档

    Args:
        product_context: 产品背景描述
        current_ui_html: 当前 UI 的 HTML 代码
        optimization_goals: 优化目标列表

    Returns:
        {"prd_document": str, "acceptance_criteria": list}
    """
    llm = get_llm_client()

    user_prompt = (
        f"## 产品背景\n{product_context}\n\n"
        f"## 当前 UI 代码(摘要)\n{current_ui_html[:3000]}\n\n"
        f"## 优化目标\n"
    )
    for i, goal in enumerate(optimization_goals, 1):
        user_prompt += f"{i}. {goal}\n"

    user_prompt += f"\n\n请基于以上信息撰写 PRD 文档。当前时间: {datetime.now(timezone.utc).isoformat()}"

    result = await llm.chat_completion_json(
        system_prompt=PRD_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.4,
        max_tokens=4096,
    )

    logger.info("PM Agent completed PRD writing, criteria count: %d",
                len(result.get("acceptance_criteria", [])))
    return result


async def pm_acceptance(
    prd_document: str,
    acceptance_criteria: list[str],
    variant_scores: dict,
    cot_analysis: dict | None,
    rule_check_results: dict,
    evaluations: list,
    iteration_count: int,
) -> AcceptanceResult:
    """
    PM Agent 进行验收

    Args:
        prd_document: PRD 文档
        acceptance_criteria: 验收标准列表
        variant_scores: 变体评分 {"A": 8.2, "B": 7.5}
        cot_analysis: CoT 分析结果
        rule_check_results: 规则检查结果
        evaluations: 用户评估列表
        iteration_count: 当前迭代次数

    Returns:
        AcceptanceResult
    """
    llm = get_llm_client()

    # 构建验收摘要
    eval_summary = _summarize_evaluations(evaluations)
    rule_summary = _summarize_rule_checks(rule_check_results)

    user_prompt = (
        f"## PRD 文档\n{prd_document[:3000]}\n\n"
        f"## 验收标准\n"
    )
    for i, criteria in enumerate(acceptance_criteria, 1):
        user_prompt += f"{i}. {criteria}\n"

    user_prompt += (
        f"\n## 变体评分\n{json.dumps(variant_scores, ensure_ascii=False)}\n\n"
        f"## 用户评估摘要\n{eval_summary}\n\n"
        f"## CoT 分析\n{json.dumps(cot_analysis, ensure_ascii=False, default=str)[:2000]}\n\n"
        f"## UI 规则检查\n{rule_summary}\n\n"
        f"## 当前迭代次数\n{iteration_count}\n\n"
        f"请进行验收评估。"
    )

    result = await llm.chat_completion_json(
        system_prompt=ACCEPTANCE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.3,
        max_tokens=2048,
    )

    logger.info(
        f"PM Agent acceptance: accepted={result.get('accepted')}, score={result.get('prd_compliance_score')}"
    )

    return AcceptanceResult(
        accepted=bool(result.get("accepted", False)),
        prd_compliance_score=float(result.get("prd_compliance_score", 0)),
        passed_criteria=result.get("passed_criteria", []),
        failed_criteria=result.get("failed_criteria", []),
        feedback=result.get("feedback", ""),
        next_actions=result.get("next_actions", []),
    )


# ── 辅助函数 ──
def _summarize_evaluations(evaluations: list) -> str:
    """汇总用户评估结果"""
    if not evaluations:
        return "无评估数据"

    lines = []
    for ev in evaluations:
        if isinstance(ev, dict):
            lines.append(
                f"- {ev.get('persona_name', '?')} → 变体{ev.get('variant_id', '?')}: "
                f"综合{ev.get('overall_score', '?')}/10 "
                f"(可用{ev.get('usability_score', '?')}, 美观{ev.get('aesthetics_score', '?')}, "
                f"清晰{ev.get('clarity_score', '?')}, 完成{ev.get('task_completion_score', '?')})"
            )
        else:
            lines.append(f"- {ev}")
    return "\n".join(lines)


def _summarize_rule_checks(rule_check_results: dict) -> str:
    """汇总规则检查结果"""
    if not rule_check_results:
        return "无规则检查数据"

    lines = []
    for variant_id, result in rule_check_results.items():
        if isinstance(result, dict):
            passed = result.get("passed_count", 0)
            total = result.get("total_count", 0)
            violations = result.get("violations", [])
            lines.append(f"- 变体{variant_id}: {passed}/{total} 规则通过, {len(violations)}项违规")
        else:
            lines.append(f"- 变体{variant_id}: {result}")
    return "\n".join(lines)
