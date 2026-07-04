"""
A/B 测试 Pipeline — 基于 LangGraph 的多 Agent 协作评估系统

Pipeline 流程:
  PM Agent (撰写PRD) → 设计师 Agent (生成UI变体A/B)
    → 用户 Agent (多persona评估) → CoT Agent (推理分析)
    → UI规则检查器 → 产品教练 Agent (引导迭代)
    → [条件循环] → PM Agent (验收)

所有 Agent 由 LLM 扮演,纯模拟评估,不涉及真实用户。
"""

from __future__ import annotations

import structlog
import re
from datetime import datetime
from pathlib import Path

from .pipeline import build_pipeline as build_pipeline, get_pipeline
from .state import PipelineState

logger = structlog.get_logger(__name__)


def _extract_prototype_summary(html: str) -> str:
    """从原型 HTML 提取关键摘要(CSS 变量 + 1个 Agent 页面结构)"""
    root_match = re.search(r":root\s*\{([^}]+)\}", html)
    css_vars = root_match.group(1)[:1500] if root_match else ""
    agent_match = re.search(
        r'<div[^>]*id="researcherPage".*?</div>\s*</div>\s*</div>',
        html,
        re.DOTALL,
    )
    agent_html = agent_match.group(0)[:2000] if agent_match else html[:2000]
    return (
        f"/* CSS 变量 */\n:root {{{css_vars}}}\n\n"
        f"<!-- Agent 页面结构 -->\n{agent_html}"
    )


async def run_ab_testing_pipeline(
    prototype_html_path: str = "prototypes/interactive-prototype.html",
    max_iterations: int = 3,
    target_score: float = 7.0,
    output_dir: str = ".trae/documents/ab-testing-reports",
) -> dict:
    """运行 A/B 测试 Pipeline(Mock 演示模式)

    Args:
        prototype_html_path: 原型 HTML 文件路径
        max_iterations: 最大迭代轮次
        target_score: 目标评分阈值
        output_dir: 报告输出目录

    Returns:
        运行结果摘要
    """
    from .reporter import generate_report, save_winner_variant

    # 1. 读取原型 HTML
    html_path = Path(prototype_html_path)
    if html_path.exists():
        html = html_path.read_text(encoding="utf-8")
        ui_summary = _extract_prototype_summary(html)
        logger.info("Loaded prototype: %s (%d chars)", prototype_html_path, len(html))
    else:
        ui_summary = "<!-- 原型文件未找到,使用占位 -->"
        logger.warning("Prototype file not found: %s", prototype_html_path)

    # 2. 构建 initial state
    initial_state: PipelineState = {
        "product_context": (
            "ScholarMind 智能学术研究助手 — 基于 RAG + LangGraph + DeepSeek 的"
            "学术研究助手,包含6个Agent(研究员/审查员/架构师/综述员/润色员/自定义),"
            "三列布局,深色主题,绿色强调色"
        ),
        "current_ui_html": ui_summary,
        "optimization_goals": [
            "提升 UI 美观度",
            "改善移动端体验",
            "增强可访问性(WCAG AA)",
            "优化交互反馈",
        ],
        "max_iterations": max_iterations,
        "iteration_count": 0,
        "history": [],
    }

    # 3. 运行 Pipeline
    app = get_pipeline()
    config = {
        "configurable": {
            "thread_id": f"ab-test-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        }
    }

    final_state: dict = dict(initial_state)
    async for event in app.astream(initial_state, config=config):
        for node_name, node_output in event.items():
            if isinstance(node_output, dict):
                final_state.update(node_output)
            logger.info("Pipeline node completed: %s", node_name)

    # 4. 生成报告
    report_path = generate_report(final_state, output_dir)
    if final_state.get("variants"):
        save_winner_variant(
            final_state["variants"],
            final_state.get("variant_scores", {}),
            output_dir,
        )

    return {
        "acceptance_result": final_state.get("acceptance_result"),
        "variant_scores": final_state.get("variant_scores", {}),
        "report_path": report_path,
        "iterations": final_state.get("iteration_count", 0),
    }
