"""
GAN对抗评分融合模块 — cyclical-paper-review Pipeline

实现Generator评分与Discriminator评分的融合，消除AI自评幻觉。

核心功能：
- fuse_scores(): G评分与D评分的加权融合
- calculate_adversarial_signal(): 对抗信号强度计算
- determine_trust_weight(): 动态信任权重（基于历史对抗信号）
- generate_adversarial_feedback(): 将D的挑刺意见转化为G的改进指令

Author: Cyclical Paper Review Pipeline
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
        g_score: Generator侧（ExternalReviewer）的评分
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
    # 计算对抗信号
    signal = calculate_adversarial_signal(g_score, d_score)

    # 动态调整信任权重
    effective_alpha = determine_trust_weight(
        alpha, round_number, signal, score_history
    )

    # 计算过度自信惩罚
    penalty = 0.0
    if signal > 5:
        penalty = (signal - 5) * 0.5  # 每超1分扣0.5分

    # 融合评分
    fused = effective_alpha * g_score + (1 - effective_alpha) * d_score

    # 应用过度自信惩罚（不超过D评分）
    fused_after_penalty = max(fused - penalty, d_score)

    # 四舍五入为整数
    fused_int = int(round(fused_after_penalty))

    # 确保在0-100范围内
    fused_int = max(0, min(100, fused_int))

    # 判断信号等级
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
    - 信号 > 10: Generator严重过度自信
    - 信号 5-10: 中度过度自信
    - 信号 < 5: 评分基本一致，论文质量可靠
    - 信号 < 0: Discriminator评分更高（罕见，可能D过于宽松）

    参数:
        g_score: Generator侧评分
        d_score: Discriminator侧评分

    返回:
        对抗信号强度（浮点数）
    """
    return float(g_score - d_score)


def determine_trust_weight(
    base_alpha: float,
    round_number: int,
    current_signal: float,
    score_history: Optional[List[Dict]] = None,
) -> float:
    """动态信任权重计算

    随着轮次增加，若G和D的评分差距缩小（对抗收敛），α逐步增大（信任G更多）。
    若对抗信号持续强烈，α保持低位（持续偏向D的挑刺）。

    参数:
        base_alpha: 基础信任权重（默认0.4）
        round_number: 当前轮次
        current_signal: 当前对抗信号强度
        score_history: 历史对抗信号记录

    返回:
        动态调整后的信任权重
    """
    alpha = base_alpha

    # 策略1：对抗收敛时增大α
    if score_history and len(score_history) >= 2:
        recent_signals = [
            h.get("adversarial_signal", 0) for h in score_history[-3:]
        ]
        if recent_signals:
            avg_signal = sum(abs(s) for s in recent_signals) / len(recent_signals)
            # 信号逐步缩小 → 对抗收敛 → 信任G更多
            if avg_signal < 3:
                alpha = min(0.6, base_alpha + 0.05 * round_number)
            elif avg_signal > 10:
                # 信号持续强烈 → 保持偏向D
                alpha = max(0.2, base_alpha - 0.05)

    # 策略2：当前信号过强时降低α
    if current_signal > 15:
        alpha = max(0.2, alpha - 0.1)
    elif current_signal > 10:
        alpha = max(0.25, alpha - 0.05)

    # 确保α在[0.2, 0.6]范围内
    alpha = max(0.2, min(0.6, alpha))

    return alpha


def generate_adversarial_feedback(
    d_report: str,
    d_dimension_scores: Dict[str, int],
    g_dimension_scores: Dict[str, int],
    adversarial_signal: float,
) -> List[Dict]:
    """将Discriminator的挑刺意见转化为Generator的改进指令

    根据对抗信号强度，决定D意见的优先级升级策略：
    - 信号 > 10: D的所有意见升级为HIGH
    - 信号 5-10: D意见按原优先级处理
    - 信号 < 5: D意见降级为建议性

    参数:
        d_report: D的挑刺报告文本
        d_dimension_scores: D的维度评分
        g_dimension_scores: G的维度评分
        adversarial_signal: 对抗信号强度

    返回:
        改进指令列表，每条包含:
        - dimension: 维度名称
        - g_score: G评分
        - d_score: D评分
        - gap: 分差
        - priority: 优先级 (critical/high/medium)
        - feedback: 改进指令文本
    """
    feedback_list = []

    # 维度名称映射
    dimension_names = {
        "topic_question": "选题与问题意识",
        "theory_literature": "理论框架与文献",
        "research_design": "研究设计与方法",
        "findings": "研究发现与结果",
        "discussion": "讨论与理论对话",
        "writing_style": "文笔与文风",
        "logic_rigor": "逻辑缜密度",
        "rigor_norm": "严谨性与规范性",
        "innovation": "创新性与启发价值",
    }

    for dim_key, dim_name in dimension_names.items():
        g_dim = g_dimension_scores.get(dim_key, 0)
        d_dim = d_dimension_scores.get(dim_key, 0)
        gap = g_dim - d_dim

        if gap <= 0:
            continue  # D评分不低于G，无需反馈

        # 根据对抗信号强度决定优先级
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

    # 按gap降序排列
    feedback_list.sort(key=lambda x: x["gap"], reverse=True)

    return feedback_list


def format_gan_score_report(fusion_result: Dict) -> str:
    """格式化GAN评分融合报告

    参数:
        fusion_result: fuse_scores()的返回值

    返回:
        格式化的报告文本
    """
    lines = [
        "=== GAN对抗评分融合报告 ===",
        f"G评分（ExternalReviewer）：{fusion_result['g_score']}/100",
        f"D评分（AdversarialCritic）：{fusion_result['d_score']}/100",
        f"对抗信号强度：{fusion_result['adversarial_signal']:.1f}（G-D差值）",
        f"信号等级：{fusion_result['signal_level']}",
        f"信任权重：α={fusion_result['alpha']:.2f}",
        f"过度自信惩罚：{fusion_result['overconfidence_penalty']:.1f}分",
        f"融合评分：{fusion_result['fused_score']}/100",
        f"（原始融合：{fusion_result['raw_fused']:.2f}，惩罚后取整：{fusion_result['fused_score']}）",
    ]
    return "\n".join(lines)
