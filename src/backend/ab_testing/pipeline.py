"""
LangGraph Pipeline 定义 — A/B 测试多 Agent 协作流程

Pipeline 流程图:

  ┌─────────────────────────────────────────────────────────┐
  │                                                         │
  │  START → pm_write_prd → designer_generate               │
  │                              ↓                          │
  │                         user_evaluate                   │
  │                              ↓                          │
  │                         cot_analyze                     │
  │                              ↓                          │
  │                         rule_check                      │
  │                              ↓                          │
  │                         coach_guide                     │
  │                              ↓                          │
  │                    ┌── iteration? ──┐                   │
  │                    │                │                   │
  │                   YES              NO                   │
  │                    │                │                   │
  │                    ↓                ↓                   │
  │             designer_generate   pm_acceptance           │
  │                    │                │                   │
  │                    ↑                ↓                   │
  │                    └────────    END                    │
  │                                                         │
  └─────────────────────────────────────────────────────────┘

使用 LangGraph StateGraph 实现:
- 每个节点是一个 async 函数,接收并返回 PipelineState
- 条件边根据 state 中的字段决定路由
- 支持最大迭代次数限制
"""

from __future__ import annotations

import structlog
from typing import Any

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from .state import PipelineState
from .agents.pm_agent import pm_write_prd, pm_acceptance
from .agents.designer_agent import designer_generate_variants
from .agents.user_agent import user_evaluate_variants, aggregate_variant_scores
from .agents.cot_agent import cot_analyze
from .agents.coach_agent import coach_guide
from .validators.ui_rules import check_all_variants

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════════════
#  Pipeline 节点定义
# ═══════════════════════════════════════════════════════════

async def node_pm_write_prd(state: PipelineState) -> dict[str, Any]:
    """节点:PM 撰写 PRD"""
    logger.info("Pipeline → PM Agent: writing PRD")
    try:
        result = await pm_write_prd(
            product_context=state.get("product_context", ""),
            current_ui_html=state.get("current_ui_html", ""),
            optimization_goals=state.get("optimization_goals", []),
        )
        return {
            "prd_document": result.get("prd_document", ""),
            "acceptance_criteria": result.get("acceptance_criteria", []),
            "current_phase": "designer",
        }
    except Exception as e:
        logger.error(f"PM write PRD failed: {e}", exc_info=True)
        return {"error": str(e), "current_phase": "error"}


async def node_designer_generate(state: PipelineState) -> dict[str, Any]:
    """节点:设计师生成变体"""
    iteration = state.get("iteration_count", 0)
    logger.info(f"Pipeline → Designer Agent: generating variants (iteration {iteration})")
    try:
        variants = await designer_generate_variants(
            prd_document=state.get("prd_document", ""),
            current_ui_html=state.get("current_ui_html", ""),
            optimization_goals=state.get("optimization_goals", []),
            coach_guidance=state.get("coach_guidance", ""),
            iteration_count=iteration,
        )
        return {
            "variants": variants,
            "current_phase": "user_eval",
        }
    except Exception as e:
        logger.error(f"Designer generate failed: {e}", exc_info=True)
        return {"error": str(e), "current_phase": "error"}


async def node_user_evaluate(state: PipelineState) -> dict[str, Any]:
    """节点:用户评估"""
    logger.info("Pipeline → User Agent: evaluating variants")
    try:
        variants = state.get("variants", [])
        evaluations = await user_evaluate_variants(variants)
        variant_scores = aggregate_variant_scores(evaluations)
        return {
            "evaluations": evaluations,
            "variant_scores": variant_scores,
            "current_phase": "cot_analysis",
        }
    except Exception as e:
        logger.error(f"User evaluate failed: {e}", exc_info=True)
        return {"error": str(e), "current_phase": "error"}


async def node_cot_analyze(state: PipelineState) -> dict[str, Any]:
    """节点:CoT 推理分析"""
    logger.info("Pipeline → CoT Agent: analyzing")
    try:
        analysis = await cot_analyze(
            evaluations=state.get("evaluations", []),
            variant_scores=state.get("variant_scores", {}),
            variants=state.get("variants", []),
        )
        return {
            "cot_analysis": analysis,
            "current_phase": "rule_check",
        }
    except Exception as e:
        logger.error(f"CoT analyze failed: {e}", exc_info=True)
        return {"error": str(e), "current_phase": "error"}


async def node_rule_check(state: PipelineState) -> dict[str, Any]:
    """节点:UI 规则检查"""
    logger.info("Pipeline → Rule Checker: checking UI rules")
    try:
        variants = state.get("variants", [])
        results = check_all_variants(variants)
        return {
            "rule_check_results": results.get("results", {}),
            "rule_violations": results.get("violations", {}),
            "current_phase": "coach",
        }
    except Exception as e:
        logger.error(f"Rule check failed: {e}", exc_info=True)
        return {"error": str(e), "current_phase": "error"}


async def node_coach_guide(state: PipelineState) -> dict[str, Any]:
    """节点:产品教练引导"""
    logger.info("Pipeline → Coach Agent: guiding iteration")
    try:
        result = await coach_guide(
            cot_analysis=state.get("cot_analysis"),
            rule_check_results=state.get("rule_check_results", {}),
            variant_scores=state.get("variant_scores", {}),
            evaluations=state.get("evaluations", []),
            iteration_count=state.get("iteration_count", 0),
            max_iterations=state.get("max_iterations", 3),
        )
        history = list(state.get("history", []))
        history.append({
            "iteration": result.get("iteration_count", state.get("iteration_count", 0) + 1),
            "variant_scores": state.get("variant_scores", {}),
            "coach_guidance": result.get("coach_guidance", "")[:200],
        })
        return {
            "coach_guidance": result.get("coach_guidance", ""),
            "iteration_needed": result.get("iteration_needed", False),
            "iteration_count": result.get("iteration_count", state.get("iteration_count", 0) + 1),
            "current_phase": "pm_acceptance" if not result.get("iteration_needed") else "designer",
            "history": history,
        }
    except Exception as e:
        logger.error(f"Coach guide failed: {e}", exc_info=True)
        return {"error": str(e), "current_phase": "error"}


async def node_pm_acceptance(state: PipelineState) -> dict[str, Any]:
    """节点:PM 验收"""
    logger.info("Pipeline → PM Agent: acceptance check")
    try:
        acceptance = await pm_acceptance(
            prd_document=state.get("prd_document", ""),
            acceptance_criteria=state.get("acceptance_criteria", []),
            variant_scores=state.get("variant_scores", {}),
            cot_analysis=state.get("cot_analysis"),
            rule_check_results=state.get("rule_check_results", {}),
            evaluations=state.get("evaluations", []),
            iteration_count=state.get("iteration_count", 0),
        )
        return {
            "acceptance_result": acceptance,
            "current_phase": "done",
        }
    except Exception as e:
        logger.error(f"PM acceptance failed: {e}", exc_info=True)
        return {"error": str(e), "current_phase": "error"}


# ═══════════════════════════════════════════════════════════
#  条件路由函数
# ═══════════════════════════════════════════════════════════

def route_after_coach(state: PipelineState) -> str:
    """
    教练节点后的条件路由:
    - 需要迭代 → 回到设计师节点
    - 不需要迭代 → PM 验收
    - 出错 → 结束
    """
    if state.get("error"):
        return "end"
    if state.get("iteration_needed", False):
        iteration = state.get("iteration_count", 0)
        max_iter = state.get("max_iterations", 3)
        if iteration < max_iter:
            logger.info("Routing: iteration %d/%d → designer", iteration, max_iter)
            return "designer"
        else:
            logger.info("Routing: max iterations reached → pm_acceptance")
            return "pm_acceptance"
    return "pm_acceptance"


def route_on_error(state: PipelineState) -> str:
    """错误路由"""
    if state.get("error"):
        return "end"
    return "continue"


# ═══════════════════════════════════════════════════════════
#  Pipeline 构建
# ═══════════════════════════════════════════════════════════

def build_pipeline():
    """
    构建 LangGraph A/B 测试 Pipeline

    Returns:
        编译后的 LangGraph 可执行图
    """
    workflow = StateGraph(PipelineState)

    # ── 添加节点 ──
    workflow.add_node("pm_write_prd", node_pm_write_prd)
    workflow.add_node("designer", node_designer_generate)
    workflow.add_node("user_eval", node_user_evaluate)
    workflow.add_node("cot_analysis", node_cot_analyze)
    workflow.add_node("rule_check", node_rule_check)
    workflow.add_node("coach", node_coach_guide)
    workflow.add_node("pm_acceptance", node_pm_acceptance)

    # ── 设置入口 ──
    workflow.set_entry_point("pm_write_prd")

    # ── 添加边 ──
    workflow.add_edge("pm_write_prd", "designer")
    workflow.add_edge("designer", "user_eval")
    workflow.add_edge("user_eval", "cot_analysis")
    workflow.add_edge("cot_analysis", "rule_check")
    workflow.add_edge("rule_check", "coach")

    # ── 条件边:教练后路由 ──
    workflow.add_conditional_edges(
        "coach",
        route_after_coach,
        {
            "designer": "designer",        # 迭代 → 回到设计师
            "pm_acceptance": "pm_acceptance",  # 不迭代 → PM 验收
            "end": END,                    # 出错 → 结束
        },
    )

    # ── PM 验收 → 结束 ──
    workflow.add_edge("pm_acceptance", END)

    # ── 编译 ──
    checkpointer = MemorySaver()
    app = workflow.compile(checkpointer=checkpointer)
    logger.info("A/B testing pipeline compiled successfully")
    return app


# ── 全局 Pipeline 实例 ──
_pipeline = None


def get_pipeline():
    """获取全局 Pipeline 实例(延迟初始化)"""
    global _pipeline
    if _pipeline is None:
        _pipeline = build_pipeline()
    return _pipeline
