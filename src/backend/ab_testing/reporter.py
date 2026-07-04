"""
报告生成器 — 将 Pipeline 运行结果输出为 Markdown 报告

生成内容:
- PRD 文档全文
- 各轮迭代历史
- 变体描述与评分
- 用户评估摘要
- CoT 分析
- 教练指导
- PM 验收报告
"""

from __future__ import annotations

import structlog
from datetime import datetime
from pathlib import Path

logger = structlog.get_logger(__name__)


def generate_report(final_state: dict, output_dir: str) -> str:
    """生成 Markdown 报告并保存

    Args:
        final_state: Pipeline 最终状态
        output_dir: 输出目录

    Returns:
        报告文件路径
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = output_path / f"{timestamp}_report.md"

    lines: list[str] = []
    lines.append(f"# ScholarMind A/B 测试报告")
    lines.append(f"\n> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # ── PRD 文档 ──
    prd = final_state.get("prd_document", "")
    if prd:
        lines.append("---")
        lines.append("## 一、PRD 文档(PM Agent 撰写)")
        lines.append("")
        lines.append(prd)
        lines.append("")

    # ── 验收标准 ──
    criteria = final_state.get("acceptance_criteria", [])
    if criteria:
        lines.append("### 验收标准")
        for i, c in enumerate(criteria, 1):
            lines.append(f"{i}. {c}")
        lines.append("")

    # ── 迭代历史 ──
    history = final_state.get("history", [])
    if history:
        lines.append("---")
        lines.append("## 二、迭代历史")
        lines.append("")
        for h in history:
            it = h.get("iteration", "?")
            scores = h.get("variant_scores", {})
            guidance = h.get("coach_guidance", "")
            lines.append(f"### 第 {it} 轮")
            lines.append(f"- 变体评分: {scores}")
            if guidance:
                lines.append(f"- 教练指导: {guidance}")
            lines.append("")

    # ── 变体与评分 ──
    variants = final_state.get("variants", [])
    scores = final_state.get("variant_scores", {})
    if variants:
        lines.append("---")
        lines.append("## 三、UI 变体与评分")
        lines.append("")
        for v in variants:
            vid = getattr(v, "variant_id", "?")
            desc = getattr(v, "description", "")
            rationale = getattr(v, "design_rationale", "")
            score = scores.get(vid, "N/A")
            lines.append(f"### 变体 {vid}(评分: {score})")
            lines.append(f"- 描述: {desc}")
            lines.append(f"- 设计理由: {rationale}")
            lines.append("")

    # ── 用户评估摘要 ──
    evaluations = final_state.get("evaluations", [])
    if evaluations:
        lines.append("---")
        lines.append("## 四、用户评估摘要")
        lines.append("")
        lines.append("| Persona | 变体 | 可用性 | 美观度 | 清晰度 | 完成度 | 综合 |")
        lines.append("|---------|------|--------|--------|--------|--------|------|")
        for ev in evaluations:
            name = getattr(ev, "persona_name", "?")
            vid = getattr(ev, "variant_id", "?")
            lines.append(
                f"| {name} | {vid} | "
                f"{getattr(ev, 'usability_score', 0):.1f} | "
                f"{getattr(ev, 'aesthetics_score', 0):.1f} | "
                f"{getattr(ev, 'clarity_score', 0):.1f} | "
                f"{getattr(ev, 'task_completion_score', 0):.1f} | "
                f"{getattr(ev, 'overall_score', 0):.1f} |"
            )
        lines.append("")

        # 痛点与建议
        lines.append("### 主要痛点与建议")
        for ev in evaluations:
            name = getattr(ev, "persona_name", "?")
            vid = getattr(ev, "variant_id", "?")
            pains = getattr(ev, "pain_points", [])
            suggs = getattr(ev, "suggestions", [])
            if pains or suggs:
                lines.append(f"**{name} (变体{vid}):**")
                for p in pains:
                    lines.append(f"- 痛点: {p}")
                for s in suggs:
                    lines.append(f"- 建议: {s}")
                lines.append("")

    # ── CoT 分析 ──
    cot = final_state.get("cot_analysis")
    if cot:
        lines.append("---")
        lines.append("## 五、CoT 推理分析")
        lines.append("")
        roots = getattr(cot, "root_causes", [])
        if roots:
            lines.append("### 根因分析")
            for r in roots:
                lines.append(f"- {r}")
            lines.append("")
        recs = getattr(cot, "recommendations", [])
        if recs:
            lines.append("### 改进建议")
            for r in recs:
                lines.append(f"- {r}")
            lines.append("")
        ranking = getattr(cot, "variant_ranking", [])
        if ranking:
            lines.append(f"### 变体排名: {' > '.join(ranking)}")
            lines.append("")

    # ── 教练指导 ──
    guidance = final_state.get("coach_guidance", "")
    if guidance:
        lines.append("---")
        lines.append("## 六、产品教练指导")
        lines.append("")
        lines.append(guidance)
        lines.append("")

    # ── PM 验收 ──
    acceptance = final_state.get("acceptance_result")
    if acceptance:
        lines.append("---")
        lines.append("## 七、PM 验收报告")
        lines.append("")
        accepted = getattr(acceptance, "accepted", False)
        score = getattr(acceptance, "prd_compliance_score", 0)
        lines.append(f"- **验收结果**: {'✅ 通过' if accepted else '❌ 未通过'}")
        lines.append(f"- **PRD 符合度**: {score:.1f}/100")
        lines.append("")
        passed = getattr(acceptance, "passed_criteria", [])
        failed = getattr(acceptance, "failed_criteria", [])
        if passed:
            lines.append("### 通过的标准")
            for p in passed:
                lines.append(f"- ✅ {p}")
            lines.append("")
        if failed:
            lines.append("### 未通过的标准")
            for f in failed:
                lines.append(f"- ❌ {f}")
            lines.append("")
        feedback = getattr(acceptance, "feedback", "")
        if feedback:
            lines.append(f"### 反馈: {feedback}")
            lines.append("")
        next_actions = getattr(acceptance, "next_actions", [])
        if next_actions:
            lines.append("### 下一步行动")
            for a in next_actions:
                lines.append(f"- {a}")
            lines.append("")

    # ── 错误信息 ──
    error = final_state.get("error")
    if error:
        lines.append("---")
        lines.append("## ⚠️ 错误信息")
        lines.append(f"```\n{error}\n```")
        lines.append("")

    # 写入文件
    report_content = "\n".join(lines)
    report_file.write_text(report_content, encoding="utf-8")
    logger.info("Report saved to: %s", report_file)
    return str(report_file)


def save_winner_variant(
    variants: list,
    variant_scores: dict,
    output_dir: str,
) -> str:
    """保存得分最高的变体 HTML

    Args:
        variants: UIVariant 列表
        variant_scores: 变体评分 {"A": 8.2, "B": 7.5}
        output_dir: 输出目录

    Returns:
        文件路径
    """
    if not variants:
        return ""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 找到得分最高的变体
    best_variant = None
    best_score = -1
    for v in variants:
        vid = getattr(v, "variant_id", "")
        score = variant_scores.get(vid, 0)
        if score > best_score:
            best_score = score
            best_variant = v

    if not best_variant:
        return ""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    winner_file = output_path / f"{timestamp}_winner_{best_variant.variant_id}.html"

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ScholarMind — 变体 {best_variant.variant_id}(获胜方案)</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 40px; line-height: 1.6; }}
.variant-info {{ background: #f6f8fa; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
.variant-info h2 {{ margin-top: 0; }}
.score {{ color: #2E7D32; font-weight: bold; }}
</style>
</head>
<body>
<div class="variant-info">
<h2>变体 {best_variant.variant_id} — 获胜方案</h2>
<p><strong>评分:</strong> <span class="score">{best_score:.1f}/10</span></p>
<p><strong>描述:</strong> {getattr(best_variant, 'description', '')}</p>
<p><strong>设计理由:</strong> {getattr(best_variant, 'design_rationale', '')}</p>
</div>
<h3>HTML 片段</h3>
<pre><code>{getattr(best_variant, 'html_snippet', '')}</code></pre>
</body>
</html>"""

    winner_file.write_text(html_content, encoding="utf-8")
    logger.info("Winner variant saved to: %s", winner_file)
    return str(winner_file)
