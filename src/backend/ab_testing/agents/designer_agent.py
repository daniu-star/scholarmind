"""
设计师 Agent — 生成 UI 变体

职责:
  根据 PRD 文档和当前 UI,生成两个 UI 变体(A 和 B)供 A/B 测试。
  变体 A:保守优化(微调现有设计)
  变体 B:激进优化(大胆创新设计)

输入: PRD 文档、当前 UI HTML、优化目标
输出: 两个 UIVariant
"""

from __future__ import annotations

import structlog

from ..llm_client import get_llm_client
from ..state import UIVariant

logger = structlog.get_logger(__name__)

DESIGNER_SYSTEM_PROMPT = """\
你是一位资深 UI/UX 设计师,正在为 ScholarMind(智能学术研究助手)设计 UI 变体。

ScholarMind 的设计语言:
- 深色主题(背景 #0D1117,卡片 #161B22)
- 绿色强调(#4A8C50)
- Source Serif 4 + Inter 字体组合
- 三列布局(左侧边栏 + 中央对话 + 右侧信息栏)
- 学术、专业、克制的视觉风格

你的任务:
1. 阅读 PRD 文档和当前 UI 代码
2. 生成两个变体:
   - 变体 A:保守优化 — 在现有设计基础上微调,风险低
   - 变体 B:激进优化 — 大胆创新,可能带来更大提升
3. 每个变体需要包含:HTML 代码片段、设计理由、目标指标

注意:
- 只输出需要修改的 HTML/CSS 代码片段,不要重复整个文件
- 代码必须可直接嵌入现有 HTML 文件
- 保持与现有设计系统的兼容性(使用相同的 CSS 变量)

请以 JSON 格式输出:
{
  "variants": [
    {
      "variant_id": "A",
      "description": "保守优化描述",
      "html_snippet": "HTML/CSS 代码",
      "design_rationale": "设计理由",
      "target_metric": "目标指标",
      "color_scheme": {"primary": "#...", "accent": "#..."},
      "layout_changes": ["变更点1", "变更点2"]
    },
    {
      "variant_id": "B",
      "description": "激进优化描述",
      "html_snippet": "HTML/CSS 代码",
      "design_rationale": "设计理由",
      "target_metric": "目标指标",
      "color_scheme": {"primary": "#...", "accent": "#..."},
      "layout_changes": ["变更点1", "变更点2"]
    }
  ]
}
"""


async def designer_generate_variants(
    prd_document: str,
    current_ui_html: str,
    optimization_goals: list[str],
    coach_guidance: str = "",
    iteration_count: int = 0,
) -> list[UIVariant]:
    """
    设计师 Agent 生成 UI 变体

    Args:
        prd_document: PRD 文档
        current_ui_html: 当前 UI HTML
        optimization_goals: 优化目标
        coach_guidance: 产品教练的指导(迭代时)
        iteration_count: 迭代次数

    Returns:
        UIVariant 列表 [A, B]
    """
    llm = get_llm_client()

    user_prompt = (
        f"## PRD 文档\n{prd_document[:3000]}\n\n"
        f"## 当前 UI 代码(关键部分)\n{current_ui_html[:4000]}\n\n"
        f"## 优化目标\n"
    )
    for i, goal in enumerate(optimization_goals, 1):
        user_prompt += f"{i}. {goal}\n"

    if coach_guidance:
        user_prompt += f"\n## 产品教练指导(第{iteration_count}轮迭代)\n{coach_guidance}\n"

    user_prompt += "\n请生成两个 UI 变体(A:保守, B:激进)。"

    result = await llm.chat_completion_json(
        system_prompt=DESIGNER_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.8,
        max_tokens=4096,
    )

    variants_data = result.get("variants", [])
    variants: list[UIVariant] = []

    for v_data in variants_data:
        variant = UIVariant(
            variant_id=v_data.get("variant_id", "A"),
            description=v_data.get("description", ""),
            html_snippet=v_data.get("html_snippet", ""),
            design_rationale=v_data.get("design_rationale", ""),
            target_metric=v_data.get("target_metric", ""),
            color_scheme=v_data.get("color_scheme", {}),
            layout_changes=v_data.get("layout_changes", []),
        )
        variants.append(variant)
        logger.info("Designer generated variant %s: %s",
                    variant.variant_id, variant.description[:80])

    # 确保至少有两个变体
    if len(variants) < 2:
        logger.warning("Designer generated only %d variants, expected 2", len(variants))

    return variants
