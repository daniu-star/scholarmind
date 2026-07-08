"""
GAN对抗评分融合模块 — cyclical-paper-generation Pipeline

实现Generator评分与Discriminator评分的融合，消除AI自评幻觉。

核心功能：
- fuse_scores(): G评分与D评分的加权融合
- calculate_adversarial_signal(): 对抗信号强度计算
- determine_trust_weight(): 动态信任权重（基于历史对抗信号）
- generate_adversarial_feedback(): 将D的挑刺意见转化为G的改进指令

Author: Cyclical Paper Generation Pipeline
Version: 1.0.0
"""

from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# 评分融合核心函数
# ============================================================================

def fuse_scores(
    g_score: int,
    d_score: int,
    alpha: float = 0.4,
    round_number: int = 1,
    score_history: Optional[List[Dict]] = None,
) -> Dict:
    """融合Generator评分与Discriminator评分

    融合公式：fused_score = α × G_score + (1 - α) × D_score

    参数:
        g_score: Generator侧（Reviewer）的评分
        d_score: Discriminator侧（AdversarialCritic）的挑战评分
        alpha: 信任权重系数（默认0.4，偏向D的挑刺评分）
        round_number: 当前轮次
        score_history: 历史对抗信号记录

    返回:
        Dict包含:
        - fused_score: 融合后的最终评分（整数）
        - alpha: 实际使用的信任权重
        - adversarial_signal: 对抗信号强度
        - overconfidence_penalty: 过度自信惩罚分
        - signal_level: 信号等级 (severe/moderate/consensus)
    """
    signal = calculate_adversarial_signal(g_score, d_score)
    effective_alpha = determine_trust_weight(alpha, round_number, signal, score_history)

    penalty = 0.0
    if signal > 5:
        penalty = (signal - 5) * 0.5

    fused = effective_alpha * g_score + (1 - effective_alpha) * d_score
    fused_after_penalty = max(fused - penalty, d_score)
    fused_int = max(0, min(100, int(round(fused_after_penalty))))

    if signal > 10:
        signal_level = "severe"
    elif signal > 5:
        signal_level = "moderate"
    else:
        signal_level = "consensus"

    return {
        "fused_score": fused_int,
        "alpha": effective_alpha,
        "adversarial_signal": signal,
        "overconfidence_penalty": penalty,
        "signal_level": signal_level,
        "g_score": g_score,
        "d_score": d_score,
        "raw_fused": round(fused, 2),
    }


def calculate_adversarial_signal(g_score: int, d_score: int) -> float:
    """计算对抗信号强度

    对抗信号 = G_score - D_score
    """
    return float(g_score - d_score)


def determine_trust_weight(
    base_alpha: float,
    round_number: int,
    current_signal: float,
    score_history: Optional[List[Dict]] = None,
) -> float:
    """动态信任权重计算

    随着轮次增加，若G和D的评分差距缩小（对抗收敛），α逐步增大。
    若对抗信号持续强烈，α保持低位。
    """
    alpha = base_alpha

    if score_history and len(score_history) >= 2:
        recent_signals = [h.get("adversarial_signal", 0) for h in score_history[-3:]]
        if recent_signals:
            avg_signal = sum(abs(s) for s in recent_signals) / len(recent_signals)
            if avg_signal < 3:
                alpha = min(0.6, base_alpha + 0.05 * round_number)
            elif avg_signal > 10:
                alpha = max(0.2, base_alpha - 0.05)

    if current_signal > 15:
        alpha = max(0.2, alpha - 0.1)
    elif current_signal > 10:
        alpha = max(0.25, alpha - 0.05)

    return max(0.2, min(0.6, alpha))


def generate_adversarial_feedback(
    d_report: str,
    d_dimension_scores: Dict[str, int],
    g_dimension_scores: Dict[str, int],
    adversarial_signal: float,
) -> List[Dict]:
    """将Discriminator的挑刺意见转化为Generator的改进指令

    根据对抗信号强度决定D意见的优先级升级策略。
    """
    feedback_list = []

    dimension_names = {
        "title_impact": "标题冲击力",
        "writing_style": "文笔与文风",
        "academic_depth": "学术深度",
        "theoretical_rigor": "学理性",
        "visual_quality": "图表美观度与专业性",
        "format_standard": "格式标准性",
        "rigor": "严谨性",
        "professionalism": "专业性",
        "innovation": "创新性与启发价值",
    }

    for dim_key, dim_name in dimension_names.items():
        g_dim = g_dimension_scores.get(dim_key, 0)
        d_dim = d_dimension_scores.get(dim_key, 0)
        gap = g_dim - d_dim

        if gap <= 0:
            continue

        if adversarial_signal > 10:
            priority = "critical" if gap >= 3 else "high"
        elif adversarial_signal > 5:
            priority = "high" if gap >= 3 else "medium"
        else:
            priority = "medium"

        feedback_list.append({
            "dimension": dim_key,
            "dimension_name": dim_name,
            "g_score": g_dim,
            "d_score": d_dim,
            "gap": gap,
            "priority": priority,
            "feedback": (
                f"维度'{dim_name}'存在评分分歧：G评{g_dim}分 vs D评{d_dim}分（差值{gap}）。"
                f"D认为该维度存在被G忽视的缺陷，请重点检查并改进。"
            ),
        })

    feedback_list.sort(key=lambda x: x["gap"], reverse=True)
    return feedback_list


def format_gan_score_report(fusion_result: Dict) -> str:
    """格式化GAN评分融合报告"""
    lines = [
        "=== GAN对抗评分融合报告 ===",
        f"G评分（Reviewer）：{fusion_result['g_score']}/100",
        f"D评分（AdversarialCritic）：{fusion_result['d_score']}/100",
        f"对抗信号强度：{fusion_result['adversarial_signal']:.1f}（G-D差值）",
        f"信号等级：{fusion_result['signal_level']}",
        f"信任权重：α={fusion_result['alpha']:.2f}",
        f"过度自信惩罚：{fusion_result['overconfidence_penalty']:.1f}分",
        f"融合评分：{fusion_result['fused_score']}/100",
        f"（原始融合：{fusion_result['raw_fused']:.2f}，惩罚后取整：{fusion_result['fused_score']}）",
    ]
    return "\n".join(lines)
