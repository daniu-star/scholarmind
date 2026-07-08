"""
循环式论文审稿优化 Pipeline — 质量量化检测 v1.0

实现 4 维质量量化标准：
    1. 语言自然度量化检测（断裂式表达、机械过渡句、公式化辞藻）
    2. 逻辑缜密度量化检测（过渡平滑度算法）
    3. 外审评分检查（9 维度综合评分 ≥ 95）
    4. 指令一致性检查（幻觉检测、初始指令偏离度）

★ 新增模块，对应用户 4 维质量量化标准。

Author: Cyclical Paper Review Pipeline
Version: 1.0.0
"""

from typing import Dict, List, Any, Optional, Tuple
import logging
import re

logger = logging.getLogger(__name__)


# ============================================================================
# 过渡词库（用于过渡平滑度算法）
# ============================================================================

# 段落间过渡词/句（出现即视为有过渡）
# ★v5.0清理：删除"值得注意的是""由此可见"（数据库实证为AI痕迹，与FORMULAIC_PHRASES矛盾）
TRANSITION_PHRASES: List[str] = [
    "在这一基础上",
    "更深一层看",
    "然而",
    "与之相对",
    "伴随着",
    "随之而来的是",
    "进一步而言",
    "与此相应",
    "问题在于",
    "回到本研究",
    "如果说",
    "那么",
    "换言之",
    "正是在这一意义上",
    "由此",
    "这并不意味着",
    "需要追问的是",
    "从这一视角出发",
    "与此同时",
    "不仅如此",
    "更重要的是",
    "究其根本",
    "溯其源头",
    "正是在这里",
    "由此观之",
    "耐人寻味的是",
    "进一步看",
    "在此基础上",
]

# 机械过渡句（公式化、应避免的过渡）
MECHANICAL_TRANSITIONS: List[str] = [
    "首先，",
    "其次，",
    "再次，",
    "最后，",
    "第一，",
    "第二，",
    "第三，",
    "一方面，",
    "另一方面，",
    "综上所述，",
    "总而言之，",
    "总的来说，",
    "如上所述，",
    "正如前文所述，",
]

# 断裂式表达模式（正则）
BROKEN_EXPRESSION_PATTERNS: List[str] = [
    r"[^。！？]{80,}。",          # 单句过长（>80字无标点断句）
    r"（[^）]{50,}）",            # 括号内内容过长
    r"[；;][^。！？；;]{60,}",    # 分号后超长无断句
]

# 公式化辞藻（应避免的空洞修饰语）
FORMULAIC_PHRASES: List[str] = [
    "深刻", "极具", "丰富而多元", "复杂而深刻",
    "不可或缺", "至关重要", "众所周知", "不言而喻",
    "毋庸置疑", "在新时代背景下",
    "具有重要的理论意义和实践意义",
    "随着……的发展",
    "日益",
    "愈发",
    "越来越",
    # ★v1.8新增：扩展AI套话检测（基于用户反馈与数据库对照）
    "也是一个值得注意的现象",
    "值得关注的是",
    "不容忽视的是",
    "具有重要的现实意义",
    "具有重要的理论意义",
    "值得深入探讨的是",
    # ★v1.9新增：AI痕迹词汇（基于数据库6篇C刊论文实证，均未发现使用）
    "凡此种种", "盖因", "是以", "亦或", "诚如",
    # ★v7.4新增：与 style_guard.py 的 MECHANICAL_TRANSITION_PATTERNS 对齐
    "总的来说",
    "如上所述",
    "正如前文所述",
    "下文将从",
    "下文将围绕",
    "下文将主要建议整合如下",
    "应该看到",
    "不难发现",
]


# ============================================================================
# 1. 语言自然度量化检测
# ============================================================================

def calculate_language_naturality(text: str) -> Dict[str, Any]:
    """
    计算语言自然度。

    检测三类问题：
        - 断裂式表达（单句过长、括号内容过长、分号后超长）
        - 机械过渡句（首先/其次/再次等公式化过渡）
        - 公式化辞藻（深刻/极具/至关重要等空洞修饰语）

    Args:
        text: 待检测的论文文本。

    Returns:
        检测结果字典：
            - broken_expressions: int — 断裂式表达数
            - mechanical_transitions: int — 机械过渡句数
            - formulaic_phrases: int — 公式化辞藻数
            - details: List[str] — 具体问题详情
            - passed: bool — 是否通过（三类问题均为 0）
    """
    if not text:
        logger.warning("语言自然度检测：输入文本为空")
        return {
            "broken_expressions": 0,
            "mechanical_transitions": 0,
            "formulaic_phrases": 0,
            "details": [],
            "passed": True,
        }

    details: List[str] = []
    broken_count = 0
    mechanical_count = 0
    formulaic_count = 0

    # 1. 检测断裂式表达
    for pattern in BROKEN_EXPRESSION_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            broken_count += len(matches)
            for m in matches[:5]:  # 限制详情数量
                preview = m[:40] + "..." if len(m) > 40 else m
                details.append(f"断裂式表达: {preview}")

    # 2. 检测机械过渡句
    for phrase in MECHANICAL_TRANSITIONS:
        count = text.count(phrase)
        if count > 0:
            mechanical_count += count
            details.append(f"机械过渡句 '{phrase}' 出现 {count} 次")

    # 3. 检测公式化辞藻
    for phrase in FORMULAIC_PHRASES:
        if "……" in phrase:
            # 处理通配模式 "随着……的发展"
            wildcard_pattern = phrase.replace("……", ".{1,15}")
            matches = re.findall(wildcard_pattern, text)
            if matches:
                formulaic_count += len(matches)
                details.append(f"公式化辞藻 '{phrase}' 出现 {len(matches)} 次")
        else:
            count = text.count(phrase)
            if count > 0:
                formulaic_count += count
                details.append(f"公式化辞藻 '{phrase}' 出现 {count} 次")

    passed = (broken_count == 0 and mechanical_count == 0
              and formulaic_count == 0)

    logger.info(
        "语言自然度检测: 断裂=%d, 机械=%d, 公式化=%d, 通过=%s",
        broken_count, mechanical_count, formulaic_count, passed
    )

    return {
        "broken_expressions": broken_count,
        "mechanical_transitions": mechanical_count,
        "formulaic_phrases": formulaic_count,
        "details": details,
        "passed": passed,
    }


# ============================================================================
# 2. 逻辑缜密度量化检测
# ============================================================================

def _split_paragraphs(text: str) -> List[str]:
    """
    将文本切分为段落。

    以空行或换行符作为段落分隔符，过滤空段落。

    Args:
        text: 论文文本。

    Returns:
        段落列表。
    """
    if not text:
        return []
    # 优先按空行分段，其次按单换行
    paragraphs = re.split(r"\n\s*\n", text)
    if len(paragraphs) <= 1:
        paragraphs = text.split("\n")
    return [p.strip() for p in paragraphs if p.strip()]


def _has_transition(paragraph: str) -> bool:
    """
    检查段落开头是否包含过渡词/句。

    Args:
        paragraph: 段落文本。

    Returns:
        若段落前 30 字内包含过渡词则返回 True。
    """
    if not paragraph:
        return False
    head = paragraph[:30]
    for phrase in TRANSITION_PHRASES:
        if phrase in head:
            return True
    return False


def calculate_transition_smoothness(text: str) -> float:
    """
    计算过渡平滑度（0-1）。

    算法：检查每个相邻段落对是否有过渡词/句。
        - 首段默认视为有过渡（无需过渡词）
        - 后续段落若开头包含过渡词/句，则视为"平滑过渡"
        - 平滑度 = 平滑过渡的段落数 / 总段落数（不含首段）

    Args:
        text: 论文文本。

    Returns:
        过渡平滑度，取值 [0, 1]。1.0 表示所有段落均有过渡。
        若段落数 ≤ 1，返回 1.0。
    """
    paragraphs = _split_paragraphs(text)
    if len(paragraphs) <= 1:
        return 1.0

    # 首段无需过渡词，从第二段开始检查
    subsequent = paragraphs[1:]
    if not subsequent:
        return 1.0

    smooth_count = sum(1 for p in subsequent if _has_transition(p))
    smoothness = smooth_count / len(subsequent)

    logger.debug(
        "过渡平滑度: %d/%d = %.3f", smooth_count, len(subsequent), smoothness
    )
    return round(smoothness, 3)


def _count_intra_paragraph_breaks(paragraphs: List[str]) -> Tuple[int, int]:
    """★v7.4新增：统计段内首句-第二句斷裂数量

    调用 style_guard.py 中的 detect_intra_paragraph_disconnect() 函数，
    统计段内潜在断裂和严重斷裂数量。若该函数不可导入，则返回 (0, 0) 不影响主流程。

    Args:
        paragraphs: 段落列表

    Returns:
        (potential_breaks, severe_breaks) 元组
    """
    try:
        from .style_guard import detect_intra_paragraph_disconnect
    except ImportError:
        logger.debug("detect_intra_paragraph_disconnect 不可用，跳过段内衔接度计算")
        return (0, 0)
    result = detect_intra_paragraph_disconnect("\n\n".join(paragraphs), paragraphs)
    return (result.get("potential_disconnects", 0),
            result.get("severe_disconnects", 0))


def _count_paragraph_transition_quality(paragraphs: List[str]) -> Dict[str, Any]:
    """★v5.0新增：调用 style_guard.py 的 detect_paragraph_transition_quality

    将段间过渡质量检测纳入逻辑缜密度评分。若函数不可导入则返回通过态。

    Args:
        paragraphs: 段落列表

    Returns:
        段间过渡质量检测结果字典；若函数不可导入则返回通过态
    """
    try:
        from .style_guard import detect_paragraph_transition_quality
    except ImportError:
        logger.debug("detect_paragraph_transition_quality 不可用，跳过段间过渡质量计算")
        return {"passed": True, "mechanical_ratio": 0.0, "violations": []}
    return detect_paragraph_transition_quality("\n\n".join(paragraphs), paragraphs)


def _count_hard_switches(text: str) -> int:
    """
    统计生硬切换数。

    生硬切换定义：相邻段落间既无过渡词，又存在主题跳跃（以小节标题
    如"一、""（一）""1."开头且无过渡词的情况视为潜在生硬切换）。

    Args:
        text: 论文文本。

    Returns:
        生硬切换数。
    """
    paragraphs = _split_paragraphs(text)
    if len(paragraphs) <= 1:
        return 0

    hard_switches = 0
    title_pattern = re.compile(r"^[一二三四五六七八九十]+、|^（[一二三四五六七八九十]+）|^[\d]+[.．]")

    for p in paragraphs[1:]:
        if not _has_transition(p) and title_pattern.match(p):
            hard_switches += 1

    return hard_switches


def calculate_logic_rigor(text: str) -> Dict[str, Any]:
    """
    计算逻辑缜密度。

    通过过渡平滑度算法检测句子生硬切换、段落过渡呼吸感。
    ★v7.4新增：段内首句-第二句衔接度计算（基于数据库6篇C刊实证）。
    ★v5.0新增：段间过渡质量检测纳入评分（基于数据库C刊实证，机械连接词占比≤15%）。

    Args:
        text: 待检测的论文文本。

    Returns:
        检测结果字典：
            - transition_smoothness: float — 过渡平滑度（0-1）
            - hard_switches: int — 生硬切换数
            - paragraph_count: int — 段落总数
            - logic_score: int — 逻辑评分（0-10，基于平滑度推算）
            - passed: bool — 是否通过（平滑度≥0.85 且 logic_score≥9 且段间过渡通过）
            - intra_paragraph_potential_breaks: int — 潜在段内斷裂数（★v7.4新增）
            - intra_paragraph_severe_breaks: int — 严重段内斷裂数（★v7.4新增）
            - intra_paragraph_smoothness_score: int — 段内衔接度评分（0-100，★v7.4新增）
            - paragraph_transition_quality: Dict — 段间过渡质量检测结果（★v5.0新增）
    """
    if not text:
        logger.warning("逻辑缜密度检测：输入文本为空")
        return {
            "transition_smoothness": 1.0,
            "hard_switches": 0,
            "paragraph_count": 0,
            "logic_score": 10,
            "passed": True,
            "intra_paragraph_potential_breaks": 0,
            "intra_paragraph_severe_breaks": 0,
            "intra_paragraph_smoothness_score": 100,
            "paragraph_transition_quality": {"passed": True, "mechanical_ratio": 0.0, "violations": []},
        }

    paragraphs = _split_paragraphs(text)
    smoothness = calculate_transition_smoothness(text)
    hard_switches = _count_hard_switches(text)

    # ★v7.4新增：段内首句-第二句衔接度计算
    potential_breaks, severe_breaks = _count_intra_paragraph_breaks(paragraphs)
    # 段内衔接度评分：100 - severe×10 - potential×3，下限0
    intra_smoothness_score = max(0, 100 - severe_breaks * 10 - potential_breaks * 3)

    # ★v5.0新增：段间过渡质量检测
    transition_quality = _count_paragraph_transition_quality(paragraphs)

    # 基于平滑度推算逻辑评分（0-10）
    # 平滑度 1.0 → 10 分；0.85 → 9 分；0.5 → 5 分
    logic_score = int(round(smoothness * 10))
    # 生硬切换扣分
    logic_score = max(0, logic_score - hard_switches)
    # ★v7.4新增：段内严重断裂扣分（每处严重断裂扣1分）
    logic_score = max(0, logic_score - severe_breaks)

    # ★v5.0新增：段间过渡质量纳入 passed 判定
    passed = (smoothness >= 0.85 and logic_score >= 9
              and severe_breaks == 0
              and transition_quality.get("passed", True))

    logger.info(
        "逻辑缜密度检测: 平滑度=%.3f, 生硬切换=%d, 逻辑分=%d, "
        "段内断裂(潜在=%d, 严重=%d), 段内衔接度=%d, "
        "段间过渡质量(通过=%s), 通过=%s",
        smoothness, hard_switches, logic_score,
        potential_breaks, severe_breaks, intra_smoothness_score,
        transition_quality.get("passed", True), passed
    )

    return {
        "transition_smoothness": smoothness,
        "hard_switches": hard_switches,
        "paragraph_count": len(paragraphs),
        "logic_score": logic_score,
        "passed": passed,
        "intra_paragraph_potential_breaks": potential_breaks,
        "intra_paragraph_severe_breaks": severe_breaks,
        "intra_paragraph_smoothness_score": intra_smoothness_score,
        # ★v5.0新增：段间过渡质量
        "paragraph_transition_quality": transition_quality,
    }


# ============================================================================
# ★v1.1新增：节奏与多样性量化检测
# ============================================================================

# 节奏指标阈值（与 style_guard.py 的 RHYTHM_METRICS 保持一致）
RHYTHM_METRICS_QM: Dict[str, Any] = {
    "sentence_length_variance_min": 8.0,
    "sentence_length_variance_max": 25.0,
    "sentence_length_variance_ideal": 15.0,
    "paragraph_opening_diversity_min": 0.6,
    "short_sentence_ratio_min": 0.15,
    "long_sentence_ratio_max": 0.40,
}

# 段落开头连接词库（用于检测连续相同连接词）
PARAGRAPH_OPENING_CONNECTORS_QM: List[str] = [
    "首先", "其次", "再次", "最后", "此外", "另外", "然而", "因此",
    "所以", "但是", "不过", "同时", "与此同时", "在此基础上",
    "进一步", "更进一步", "不仅如此", "更重要的是", "值得注意的是",
    "综上所述", "总而言之", "一方面", "另一方面", "其一", "其二",
]


def calculate_sentence_rhythm(text: str) -> Dict[str, Any]:
    """
    ★v1.1新增：计算句子节奏（句长方差），判定僵硬化与散文化。

    算法：按句末标点（。！？）切分句子，计算句长方差。
        - 方差过低（<8.0）：句长过于单一，疑似僵硬化（AI痕迹）
        - 方差过高（>25.0）：句长过于跳跃，疑似散文化
        - 理想区间：8.0-25.0，长短句交替有呼吸感

    Args:
        text: 论文文本。

    Returns:
        节奏检测结果字典。
    """
    if not text:
        return {
            "variance": 0.0, "mean_length": 0.0,
            "short_sentence_ratio": 0.0, "long_sentence_ratio": 0.0,
            "too_uniform": False, "too_jumpy": False,
            "passed": True, "desc": "句长节奏: 文本为空",
        }

    # 按句末标点切分（保留有意义的句子）
    sentences = [s.strip() for s in re.split(r'[。！？]', text) if len(s.strip()) > 5]
    if len(sentences) < 5:
        return {
            "variance": 0.0, "mean_length": 0.0,
            "short_sentence_ratio": 0.0, "long_sentence_ratio": 0.0,
            "too_uniform": False, "too_jumpy": False,
            "passed": True, "desc": "句长节奏: 句子数不足（<5）",
        }

    lengths = [len(s) for s in sentences]
    mean = sum(lengths) / len(lengths)
    variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)

    # 短句/长句占比
    short_count = sum(1 for l in lengths if l <= 15)
    long_count = sum(1 for l in lengths if l > 50)
    short_ratio = short_count / len(lengths)
    long_ratio = long_count / len(lengths)

    too_uniform = variance < RHYTHM_METRICS_QM["sentence_length_variance_min"]
    too_jumpy = variance > RHYTHM_METRICS_QM["sentence_length_variance_max"]
    short_ratio_low = short_ratio < RHYTHM_METRICS_QM["short_sentence_ratio_min"]
    long_ratio_high = long_ratio > RHYTHM_METRICS_QM["long_sentence_ratio_max"]

    passed = not (too_uniform or too_jumpy or short_ratio_low or long_ratio_high)

    # 构建描述
    issues = []
    if too_uniform:
        issues.append(f"句长方差过低({variance:.1f})，疑似僵硬化")
    if too_jumpy:
        issues.append(f"句长方差过高({variance:.1f})，疑似散文化")
    if short_ratio_low:
        issues.append(f"短句占比不足({short_ratio:.2%})")
    if long_ratio_high:
        issues.append(f"长句占比过高({long_ratio:.2%})")

    desc = (
        f"句长节奏: 方差={variance:.1f}, 均长={mean:.1f}字, "
        f"短句={short_ratio:.0%}, 长句={long_ratio:.0%}"
    )
    if issues:
        desc += "（" + "; ".join(issues) + "）"

    return {
        "variance": round(variance, 1),
        "mean_length": round(mean, 1),
        "short_sentence_ratio": round(short_ratio, 3),
        "long_sentence_ratio": round(long_ratio, 3),
        "too_uniform": too_uniform,
        "too_jumpy": too_jumpy,
        "short_ratio_low": short_ratio_low,
        "long_ratio_high": long_ratio_high,
        "passed": passed,
        "desc": desc,
    }


def calculate_paragraph_diversity(text: str) -> Dict[str, Any]:
    """
    ★v1.1新增：计算段落开头多样性，检测机械式开头。

    算法：
        1. 按空行分段，取每段前6字符作为开头标识
        2. 计算独特开头占比（diversity = unique_openings / total_paragraphs）
        3. 检测连续相同连接词开头

    Args:
        text: 论文文本。

    Returns:
        多样性检测结果字典。
    """
    if not text:
        return {
            "diversity": 0.0, "unique_openings": 0, "total_paragraphs": 0,
            "max_consecutive_connector": 0,
            "passed": True, "desc": "段落多样性: 文本为空",
        }

    # 按空行分段
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip() and len(p.strip()) > 10]
    if len(paragraphs) < 3:
        return {
            "diversity": 1.0, "unique_openings": len(paragraphs),
            "total_paragraphs": len(paragraphs),
            "max_consecutive_connector": 0,
            "passed": True, "desc": "段落多样性: 段落数不足（<3）",
        }

    # 取每段前6字符作为开头标识
    openings = [p[:6] for p in paragraphs]
    unique_openings = len(set(openings))
    diversity = unique_openings / len(paragraphs)

    # 检测连续相同连接词开头
    max_consecutive = 0
    current_consecutive = 1
    for i in range(1, len(paragraphs)):
        prev_start = paragraphs[i - 1][:4]
        curr_start = paragraphs[i][:4]
        # 检查是否以相同连接词开头
        prev_connector = ""
        curr_connector = ""
        for conn in PARAGRAPH_OPENING_CONNECTORS_QM:
            if paragraphs[i - 1].startswith(conn):
                prev_connector = conn
            if paragraphs[i].startswith(conn):
                curr_connector = conn
        if prev_connector and curr_connector and prev_connector == curr_connector:
            current_consecutive += 1
            max_consecutive = max(max_consecutive, current_consecutive)
        else:
            current_consecutive = 1

    diversity_low = diversity < RHYTHM_METRICS_QM["paragraph_opening_diversity_min"]
    consecutive_high = max_consecutive > 2

    passed = not (diversity_low or consecutive_high)

    # 构建描述
    issues = []
    if diversity_low:
        issues.append(f"段落开头多样性过低({diversity:.2f})")
    if consecutive_high:
        issues.append(f"连续{max_consecutive}段以相同连接词开头")

    desc = (
        f"段落多样性: diversity={diversity:.2f}, "
        f"独特开头={unique_openings}/{len(paragraphs)}, "
        f"最大连续相同连接词={max_consecutive}"
    )
    if issues:
        desc += "（" + "; ".join(issues) + "）"

    return {
        "diversity": round(diversity, 3),
        "unique_openings": unique_openings,
        "total_paragraphs": len(paragraphs),
        "max_consecutive_connector": max_consecutive,
        "diversity_low": diversity_low,
        "consecutive_high": consecutive_high,
        "passed": passed,
        "desc": desc,
    }


# ============================================================================
# 3. 外审评分检查
# ============================================================================

def check_review_score(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    检查外审评分是否达标（≥ 95）。

    Args:
        state: Pipeline 状态字典，需包含 review_score 字段。

    Returns:
        检查结果字典：
            - score: int — 当前外审评分
            - min_score: int — 达标阈值（95）
            - passed: bool — 是否达标
    """
    score = state.get("review_score", 0)
    min_score = 95

    passed = score >= min_score
    logger.info("外审评分检查: %d/%d, 通过=%s", score, min_score, passed)

    return {
        "score": score,
        "min_score": min_score,
        "passed": passed,
    }


# ============================================================================
# 4. 指令一致性检查
# ============================================================================

def check_instruction_consistency(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    检查指令一致性（幻觉检测、初始指令偏离度）。

    通过对比初始指令快照与当前论文内容，检测是否存在：
        - 幻觉（捏造的文献、数据、概念）
        - 指令偏离（论文内容与用户初始指令的偏离度）

    Args:
        state: Pipeline 状态字典，需包含：
            - initial_instruction_snapshot: str — 初始指令快照
            - instruction_consistency_report: Dict — 指令守卫报告
            - paper_content: str — 当前论文内容

    Returns:
        检查结果字典：
            - hallucinations: int — 幻觉数
            - deviation_score: float — 指令偏离度（0-1）
            - passed: bool — 是否通过（幻觉=0 且偏离度<0.05）
    """
    snapshot = state.get("initial_instruction_snapshot", "")
    report = state.get("instruction_consistency_report", {})
    paper = state.get("paper_content", "")

    # 从指令守卫报告中提取幻觉数与偏离度
    hallucinations = report.get("hallucinations", 0)
    deviation_score = report.get("deviation_score", 0.0)

    # 若无守卫报告，进行简单启发式检测
    if not report and snapshot and paper:
        # 简单偏离度估算：初始指令关键词在论文中的覆盖率
        keywords = [w for w in re.split(r"[，。、；：\s]+", snapshot) if len(w) >= 2]
        if keywords:
            covered = sum(1 for kw in keywords if kw in paper)
            coverage = covered / len(keywords)
            deviation_score = round(1.0 - coverage, 3)
        else:
            deviation_score = 0.0

    passed = (hallucinations == 0 and deviation_score < 0.05)

    logger.info(
        "指令一致性检查: 幻觉=%d, 偏离度=%.3f, 通过=%s",
        hallucinations, deviation_score, passed
    )

    return {
        "hallucinations": hallucinations,
        "deviation_score": deviation_score,
        "passed": passed,
    }


# ============================================================================
# 4 维质量量化综合检查
# ============================================================================

def check_quality_metrics(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    检查 4 维质量量化标准。

    综合执行语言自然度、逻辑缜密度、外审评分、指令一致性四项检测，
    判定论文是否全面达标。

    Args:
        state: Pipeline 状态字典，需包含：
            - paper_content: str — 当前论文内容
            - review_score: int — 外审评分
            - initial_instruction_snapshot: str — 初始指令快照
            - instruction_consistency_report: Dict — 指令守卫报告

    Returns:
        综合检测结果字典：
            - language_naturality: Dict — 语言自然度结果
            - logic_rigor: Dict — 逻辑缜密度结果
            - review_score: Dict — 外审评分结果
            - instruction_consistency: Dict — 指令一致性结果
            - all_passed: bool — 四维是否全部通过
            - summary: str — 可读摘要
    """
    paper = state.get("paper_content", "")

    # 1. 语言自然度
    try:
        language_result = calculate_language_naturality(paper)
    except Exception as e:
        logger.exception("语言自然度检测失败")
        language_result = {
            "broken_expressions": -1, "mechanical_transitions": -1,
            "formulaic_phrases": -1, "details": [f"检测异常: {e}"],
            "passed": False,
        }

    # 2. 逻辑缜密度
    try:
        logic_result = calculate_logic_rigor(paper)
    except Exception as e:
        logger.exception("逻辑缜密度检测失败")
        logic_result = {
            "transition_smoothness": 0.0, "hard_switches": -1,
            "paragraph_count": 0, "logic_score": 0,
            "passed": False,
        }

    # ★v1.1新增：2.5 节奏与多样性
    try:
        rhythm_result = calculate_sentence_rhythm(paper)
    except Exception as e:
        logger.exception("节奏检测失败")
        rhythm_result = {
            "variance": 0.0, "mean_length": 0.0,
            "short_sentence_ratio": 0.0, "long_sentence_ratio": 0.0,
            "too_uniform": False, "too_jumpy": False,
            "passed": False, "desc": f"检测异常: {e}",
        }

    try:
        diversity_result = calculate_paragraph_diversity(paper)
    except Exception as e:
        logger.exception("段落多样性检测失败")
        diversity_result = {
            "diversity": 0.0, "unique_openings": 0, "total_paragraphs": 0,
            "max_consecutive_connector": 0,
            "passed": False, "desc": f"检测异常: {e}",
        }

    # 3. 外审评分
    try:
        score_result = check_review_score(state)
    except Exception as e:
        logger.exception("外审评分检查失败")
        score_result = {"score": 0, "min_score": 95, "passed": False}

    # 4. 指令一致性
    try:
        consistency_result = check_instruction_consistency(state)
    except Exception as e:
        logger.exception("指令一致性检查失败")
        consistency_result = {
            "hallucinations": -1, "deviation_score": 1.0, "passed": False,
        }

    all_passed = (
        language_result.get("passed", False)
        and logic_result.get("passed", False)
        and score_result.get("passed", False)
        and consistency_result.get("passed", False)
        and rhythm_result.get("passed", False)  # ★v1.1新增
        and diversity_result.get("passed", False)  # ★v1.1新增
    )

    # 生成摘要
    summary_lines = ["=== 4 维质量量化检测结果 ==="]
    summary_lines.append(
        f"  语言自然度: {'✅通过' if language_result.get('passed') else '❌未通过'} "
        f"(断裂={language_result.get('broken_expressions', 0)}, "
        f"机械={language_result.get('mechanical_transitions', 0)}, "
        f"公式化={language_result.get('formulaic_phrases', 0)})"
    )
    summary_lines.append(
        f"  逻辑缜密度: {'✅通过' if logic_result.get('passed') else '❌未通过'} "
        f"(平滑度={logic_result.get('transition_smoothness', 0)}, "
        f"逻辑分={logic_result.get('logic_score', 0)}/10)"
    )
    # ★v1.1新增：节奏与多样性摘要
    summary_lines.append(
        f"  句长节奏:   {'✅通过' if rhythm_result.get('passed') else '❌未通过'} "
        f"(方差={rhythm_result.get('variance', 0)}, "
        f"短句={rhythm_result.get('short_sentence_ratio', 0)}, "
        f"长句={rhythm_result.get('long_sentence_ratio', 0)})"
    )
    summary_lines.append(
        f"  段落多样性: {'✅通过' if diversity_result.get('passed') else '❌未通过'} "
        f"(diversity={diversity_result.get('diversity', 0)}, "
        f"连续连接词={diversity_result.get('max_consecutive_connector', 0)})"
    )
    summary_lines.append(
        f"  外审评分:   {'✅通过' if score_result.get('passed') else '❌未通过'} "
        f"({score_result.get('score', 0)}/{score_result.get('min_score', 95)})"
    )
    summary_lines.append(
        f"  指令一致性: {'✅通过' if consistency_result.get('passed') else '❌未通过'} "
        f"(幻觉={consistency_result.get('hallucinations', 0)}, "
        f"偏离度={consistency_result.get('deviation_score', 0)})"
    )
    summary_lines.append(
        f"  综合结论: {'✅全部通过' if all_passed else '❌存在未达标项'}"
    )

    result = {
        "language_naturality": language_result,
        "logic_rigor": logic_result,
        "rhythm": rhythm_result,  # ★v1.1新增
        "paragraph_diversity": diversity_result,  # ★v1.1新增
        "review_score": score_result,
        "instruction_consistency": consistency_result,
        "all_passed": all_passed,
        "summary": "\n".join(summary_lines),
    }

    logger.info("4 维质量量化检测完成: all_passed=%s", all_passed)
    return result


# ============================================================================
# 模块自检
# ============================================================================

if __name__ == "__main__":
    sample_text = """本研究聚焦于数字时代的社区参与问题。在这一基础上，我们考察了老年群体的媒介使用行为。

然而，现有研究多关注青年群体，忽视了老年群体的特殊性。更深一层看，这种忽视反映了学术研究的年龄偏见。

首先，我们梳理了相关文献。其次，提出了研究框架。最后，进行了实证分析。

数字时代的社区参与具有重要的理论意义和实践意义。"""

    print("=== 语言自然度 ===")
    lang = calculate_language_naturality(sample_text)
    for k, v in lang.items():
        print(f"  {k}: {v}")

    print("\n=== 逻辑缜密度 ===")
    logic = calculate_logic_rigor(sample_text)
    for k, v in logic.items():
        print(f"  {k}: {v}")

    print("\n=== 过渡平滑度 ===")
    print(f"  {calculate_transition_smoothness(sample_text)}")

    print("\n=== 综合检测 ===")
    state = {
        "paper_content": sample_text,
        "review_score": 96,
        "initial_instruction_snapshot": "数字时代 社区参与 老年群体",
        "instruction_consistency_report": {"hallucinations": 0, "deviation_score": 0.02},
    }
    metrics = check_quality_metrics(state)
    print(metrics["summary"])
