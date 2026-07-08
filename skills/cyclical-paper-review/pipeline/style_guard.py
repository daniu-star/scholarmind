"""
循环式论文审稿优化 Pipeline v1.0 - 风格守卫（StyleGuard）

程序化验证论文风格合规性，包括标点规范、字数、禁止模式、句长段落长度，
并★新增语言自然度量化检测（断裂式表达计数 + 机械过渡句检测）。

v1.0 核心新增（相对于 cyclical-paper-generation 的 style_constraints.py）：
- ★新增：语言自然度量化检测（check_language_naturality）
- ★新增：机械过渡句检测（"下文将..."、"值得注意的是"等公式化表达）
- 完整风格审计 run_full_style_audit
- Pipeline 节点入口 style_guard_node
- 违规列表输出，供下一轮 ConstraintInjector 注入

Author: Cyclical Paper Review Pipeline
Version: 1.0.0
"""

import re
import logging
from typing import Dict, List, Tuple, Any, Optional

try:
    from typing import TypedDict
except ImportError:
    # Python 3.7 兼容兜底
    TypedDict = dict  # type: ignore

logger = logging.getLogger(__name__)


# ============================================================================
# 风格规则（单一真实来源）
# ============================================================================

STYLE_RULES: Dict[str, Any] = {
    "global": {
        "total_words": 15000,
        "tolerance": 0.05,  # ★v5.1收紧：从 0.10 改为 0.05
        "max_dash_count": 15,
        "max_colon_per_1000_words": 2,
        "max_semicolon_count": 10,
        "max_ellipsis_in_body": 0,
        "forbidden_patterns": [
            "第一，.*第二，.*第三",
            "首先，.*其次，.*再次",
            "一方面，.*另一方面",
        ],
        "forbidden_phrases": [
            "深刻", "极具", "丰富而多元", "复杂而深刻",
            "不可或缺", "至关重要", "众所周知", "不言而喻", "毋庸置疑",
        ],
        "numeric_formatting": {
            "data_numbers_use_arabic": True,  # 数据数字用阿拉伯数字
            "solemn_numbers_use_chinese": True,  # 严肃数字用汉字数字
            "data_number_contexts": [
                "样本量", "样本数", "受访者", "被试", "问卷份数", "有效问卷",
                "回归系数", "β值", "p值", "F值", "t值", "r值", "标准差", "均值",
                "百分比", "比例", "频次", "次数", "人次", "篇次", "卷", "期",
                "页码", "年份", "月份", "日期", "时间", "时长", "金额",
            ],
            "solemn_number_contexts": [
                "新中国成立", "改革开放", "五四运动", "辛亥革命", "建党",
                "抗战", "解放战争", "新中国成立以来", "改革开放以来",
                "建党以来", "百年", "十年", "数十年", "几个世纪", "千年",
            ],
            "examples": {
                "compliant_data": "研究样本量为 4287 份",
                "compliant_solemn": "改革开放四十余年",
                "violation_solemn_arabic": "新中国成立 70 年来（应改为'七十年'）",
            },
        },
        "max_words_per_sentence": 60,
        "max_words_per_paragraph": 400,
        "min_words_per_paragraph": 100,
    },
    "abstract": {"words": 350, "forbidden": ["分号", "引号", "破折号", "第一", "第二", "第三"]},
    "introduction": {"words": 600},
    "literature_review": {"words": 2000},
    "method": {"words": 800},
    "findings": {"words": 3750, "min_words": 3500, "max_words": 4000},
    "conclusion": {"words": 1750, "min_words": 1500, "max_words": 2000},
}


# ============================================================================
# ★v1.0新增：机械过渡句模式库
# ============================================================================

# 机械过渡句正则模式（命中即视为语言不自然）
MECHANICAL_TRANSITION_PATTERNS: List[str] = [
    r"下文将从[^，。]{1,20}维度展开",
    r"下文将围绕[^，。]{1,20}展开讨论",
    r"下文将主要建议整合如下",
    r"值得注意的是[，,]",
    r"需要指出的是[，,]",
    r"应该看到[，,]",
    r"综上所述[，,]",
    r"总而言之[，,]",
    r"由此可见[，,]",
    r"不难发现[，,]",
    r"毋庸置疑[，,]",
    r"不言而喻[，,]",
    r"众所周知[，,]",
    r"在新时代背景下[，,]",
    r"随着[^，。]{2,15}的(?:发展|进步|推进)[，,]",
    # ★v1.8新增：扩展AI套话检测（基于用户反馈与数据库对照）
    r"也是一个值得注意的现象",
    r"是一个值得注意的[^，。]{0,5}",
    r"值得关注的是[，,]",
    r"不容忽视的是[，,]",
    r"也是一个重要的[^，。]{0,5}",
    r"值得深入探讨的是[，,]",
    r"具有重要的现实意义",
    r"具有重要的理论意义",
    r"亦是一个值得关注的[^，。]{0,5}",
    r"是一个不容忽视的[^，。]{0,5}",
    # ★v1.9新增：AI痕迹词汇检测（基于数据库6篇C刊论文实证，均未发现使用，疑为AI生成痕迹）
    r"凡此种种[，,]",
    r"盖因[^，。]{1,20}",
    r"是以[^，。]{1,20}",
    r"亦或[^，。]{1,20}",
    r"诚如[^，。]{1,20}",
    # ★v7.4新增：与 quality_metrics.py 的 MECHANICAL_TRANSITIONS 对齐
    r"总的来说[，,]",
    r"如上所述[，,]",
    r"正如前文所述[，,]",
]

# 断裂式表达正则模式
BROKEN_EXPRESSION_PATTERNS: List[str] = [
    r"第一[，,][^第]{1,200}第二[，,][^第]{1,200}第三[，,]",
    r"首先[，,][^其]{1,200}其次[，,][^再]{1,200}再次[，,]",
    r"一方面[，,][^一]{1,200}另一方面[，,]",
    r"其一[，,][^其]{1,200}其二[，,][^其]{1,200}其三[，,]",
    r"一是[^二]{1,100}二是[^三]{1,100}三是",
]


# ============================================================================
# ★v1.1新增：节奏与多样性指标（基于真实CSSCI核刊论文实测值校准）
# ============================================================================

RHYTHM_METRICS: Dict[str, Any] = {
    "sentence_length_variance_min": 8.0,   # 句长方差下限（低于则过于单一=僵硬化）
    "sentence_length_variance_max": 25.0,  # 句长方差上限（高于则过于跳跃=散文化）
    "sentence_length_variance_ideal": 15.0,  # 理想句长方差
    "paragraph_opening_diversity_min": 0.6,  # 段落开头类型多样性（0-1）
    "max_consecutive_same_connector": 2,   # 连续相同连接词开头上限
    "mechanical_pattern_threshold": 3,     # 机械模式触发阈值
    "short_sentence_ratio_min": 0.15,      # 短句（≤15字）占比下限
    "long_sentence_ratio_max": 0.40,       # 长句（>50字）占比上限
}

# 段落开头连接词列表（用于检测连续相同连接词）
PARAGRAPH_OPENING_CONNECTORS: List[str] = [
    "然而", "此外", "同时", "另外", "首先", "其次", "因此",
    "综上", "进而", "更进一步", "与之相对", "基于此", "由此",
    "不仅如此", "更重要的是", "换言之", "值得注意的是",
]


# ============================================================================
# PipelineState 定义（与主流程兼容）
# ============================================================================

class PipelineState(TypedDict, total=False):
    """循环式论文审稿优化 Pipeline 状态（与 constraint_injector.py 兼容）"""
    paper_content: str
    paper_version: int
    round_number: int
    full_text_polisher_output: Optional[str]
    findings_reviser_output: Optional[str]
    style_violations: List[str]
    active_constraints: Optional[Dict]
    error_log: List[str]


# ============================================================================
# 标点规范检查函数
# ============================================================================

def check_dash_count(text: str, max_count: int = 15) -> Tuple[int, bool, str]:
    """
    检查破折号（——）数量是否超限。

    参数:
        text: 论文文本
        max_count: 破折号上限（默认 15）

    返回:
        元组 (实际数量, 是否违规, 描述信息)
    """
    count = text.count("——")
    violated = count > max_count
    desc = f"破折号: {count}/{max_count}{'（超限）' if violated else ''}"
    return (count, violated, desc)


def check_semicolon_count(text: str, max_count: int = 10) -> Tuple[int, bool, str]:
    """
    检查分号数量是否超限。

    参数:
        text: 论文文本
        max_count: 分号上限（默认 10）

    返回:
        元组 (实际数量, 是否违规, 描述信息)
    """
    # 全角分号 + 半角分号
    count = text.count("；") + text.count(";")
    violated = count > max_count
    desc = f"分号: {count}/{max_count}{'（超限）' if violated else ''}"
    return (count, violated, desc)


def check_colon_density(text: str, max_per_1000_words: int = 2) -> Tuple[int, bool, str]:
    """
    检查冒号密度（每千字冒号数）。

    参数:
        text: 论文文本
        max_per_1000_words: 每千字冒号上限（默认 2）

    返回:
        元组 (冒号总数, 是否违规, 描述信息)
    """
    colon_count = text.count("：") + text.count(":")
    total_chars = check_chinese_word_count(text)
    if total_chars > 0:
        density = colon_count / (total_chars / 1000)
    else:
        density = 0.0
    violated = density > max_per_1000_words
    desc = (
        f"冒号: {colon_count}处 ({density:.2f}/千字, "
        f"上限{max_per_1000_words}){'（超限）' if violated else ''}"
    )
    return (colon_count, violated, desc)


def check_ellipsis_in_body(text: str) -> Tuple[int, bool, str]:
    """
    检查正文中是否出现省略号（正文禁止省略号）。

    参数:
        text: 论文文本

    返回:
        元组 (省略号数量, 是否违规, 描述信息)
    """
    count = text.count("……") + text.count("...")
    violated = count > 0
    desc = f"省略号: {count}处{'（正文禁止）' if violated else ''}"
    return (count, violated, desc)


# ============================================================================
# 字数检查函数
# ============================================================================

def check_chinese_word_count(text: str) -> int:
    """
    计算中文字数（正则 [一-鿿] 匹配 CJK 统一汉字）。

    参数:
        text: 论文文本

    返回:
        中文字符数
    """
    if not text:
        return 0
    chinese_chars = re.findall(r'[一-鿿]', text)
    return len(chinese_chars)


def check_word_count(
    text: str,
    max_words: int = 15000,
    tolerance: float = 0.05,  # ★v5.1收紧：从 0.10 改为 0.05
) -> Tuple[int, bool, str]:
    """
    检查全文字数是否在容差范围内。

    参数:
        text: 论文文本
        max_words: 目标字数（默认 15000）
        tolerance: 容差比例（默认 0.05，即 ±5%）

    返回:
        元组 (实际字数, 是否违规, 描述信息)
    """
    count = check_chinese_word_count(text)
    upper_limit = int(max_words * (1 + tolerance))
    lower_limit = int(max_words * (1 - tolerance))
    violated = count > upper_limit or count < lower_limit
    desc = (
        f"全文字数: {count}/{max_words} "
        f"(允许范围 {lower_limit}-{upper_limit})"
        f"{'（超限）' if violated else ''}"
    )
    return (count, violated, desc)


def check_section_word_count(
    text: str,
    section: str,
    rules: Optional[Dict] = None,
) -> Optional[Dict[str, Any]]:
    """
    检查指定章节字数是否合规。

    参数:
        text: 章节文本
        section: 章节名（abstract/introduction/literature_review/method/findings/conclusion）
        rules: 风格规则字典（默认使用 STYLE_RULES）

    返回:
        检查报告字典，若章节无规则则返回 None
    """
    if rules is None:
        rules = STYLE_RULES
    section_rules = rules.get(section, {})
    if not isinstance(section_rules, dict) or "words" not in section_rules:
        return None

    expected = section_rules["words"]
    min_words = section_rules.get("min_words", int(expected * 0.9))
    max_words = section_rules.get("max_words", int(expected * 1.1))
    actual = check_chinese_word_count(text)
    violated = actual < min_words or actual > max_words

    return {
        "section": section,
        "expected": expected,
        "min": min_words,
        "max": max_words,
        "actual": actual,
        "violated": violated,
        "desc": (
            f"章节 {section}: {actual}字 "
            f"(允许 {min_words}-{max_words})"
            f"{'（超限）' if violated else ''}"
        ),
    }


# ============================================================================
# 禁止模式与禁止短语检查
# ============================================================================

def check_forbidden_patterns(text: str, patterns: Optional[List[str]] = None) -> List[str]:
    """
    检查禁止的断裂式表达模式。

    参数:
        text: 论文文本
        patterns: 禁止模式正则列表（默认使用 STYLE_RULES["global"]["forbidden_patterns"]）

    返回:
        违规描述列表
    """
    if patterns is None:
        patterns = STYLE_RULES["global"]["forbidden_patterns"]
    violations: List[str] = []
    for pattern in patterns:
        try:
            matches = re.findall(pattern, text, re.DOTALL)
            if matches:
                violations.append(
                    f"发现禁止模式 '{pattern}': {len(matches)} 处"
                )
        except re.error as e:
            # 正则编译失败时跳过该模式
            continue
    return violations


def check_forbidden_phrases(text: str, phrases: Optional[List[str]] = None) -> List[str]:
    """
    检查禁止的空洞修饰语。

    参数:
        text: 论文文本
        phrases: 禁止短语列表（默认使用 STYLE_RULES["global"]["forbidden_phrases"]）

    返回:
        违规描述列表
    """
    if phrases is None:
        phrases = STYLE_RULES["global"]["forbidden_phrases"]
    violations: List[str] = []
    for phrase in phrases:
        count = text.count(phrase)
        if count > 0:
            violations.append(f"禁止用语 '{phrase}': {count} 处")
    return violations


# ============================================================================
# 句长与段落长度检查
# ============================================================================

def check_sentence_lengths(text: str, max_words: int = 60) -> Tuple[int, List[str]]:
    """
    检查句长（按句号/问号/叹号/分号分句）。

    参数:
        text: 论文文本
        max_words: 单句字数上限（默认 60）

    返回:
        元组 (超长句子数, 超长句子预览列表[最多5条])
    """
    if not text:
        return (0, [])
    # 按中英文句末标点切分
    sentences = re.split(r'[。！？；!?;]', text)
    long_sentences = [s.strip() for s in sentences if len(s.strip()) > max_words]
    previews = [s[:50] + "..." for s in long_sentences[:5]]
    return (len(long_sentences), previews)


def check_paragraph_lengths(
    text: str,
    max_words: int = 400,
    min_words: int = 100,
) -> Dict[str, Any]:
    """
    检查段落长度（按空行分段）。

    参数:
        text: 论文文本
        max_words: 段落字数上限（默认 400）
        min_words: 段落字数下限（默认 100）

    返回:
        段落长度报告字典
    """
    if not text:
        return {
            "total_paragraphs": 0,
            "too_long": 0,
            "too_short": 0,
            "long_paragraphs": [],
            "short_paragraphs": [],
        }
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    too_long = [p for p in paragraphs if len(p) > max_words]
    too_short = [p for p in paragraphs if 0 < len(p) < min_words and len(p) > 10]
    return {
        "total_paragraphs": len(paragraphs),
        "too_long": len(too_long),
        "too_short": len(too_short),
        "long_paragraphs": [p[:50] + "..." for p in too_long[:3]],
        "short_paragraphs": [p[:50] + "..." for p in too_short[:3]],
    }


# ============================================================================
# ★v1.0新增：语言自然度量化检测
# ============================================================================

def check_language_naturality(text: str) -> Dict[str, Any]:
    """
    ★新增：语言自然度量化检测。

    检测两类语言不自然现象：
    1. 断裂式表达（"第一，...第二，...第三，"等机械编号）
    2. 机械过渡句（"下文将..."、"值得注意的是"等公式化表达）

    参数:
        text: 论文文本

    返回:
        语言自然度报告字典，包含：
        - broken_expression_count: 断裂式表达计数
        - mechanical_transition_count: 机械过渡句计数
        - broken_expressions: 断裂式表达命中详情
        - mechanical_transitions: 机械过渡句命中详情
        - naturality_score: 自然度评分（0-1，1为完全自然）
        - passed: 是否通过（0处问题即通过）
    """
    broken_hits: List[str] = []
    mechanical_hits: List[str] = []

    # 检测断裂式表达
    for pattern in BROKEN_EXPRESSION_PATTERNS:
        try:
            matches = re.findall(pattern, text, re.DOTALL)
            for m in matches:
                preview = m[:60] + "..." if len(m) > 60 else m
                broken_hits.append(f"断裂式表达: {preview}")
        except re.error:
            continue

    # 检测机械过渡句
    for pattern in MECHANICAL_TRANSITION_PATTERNS:
        try:
            matches = re.findall(pattern, text)
            for m in matches:
                preview = m[:60] + "..." if len(m) > 60 else m
                mechanical_hits.append(f"机械过渡句: {preview}")
        except re.error:
            continue

    broken_count = len(broken_hits)
    mechanical_count = len(mechanical_hits)
    total_issues = broken_count + mechanical_count

    # 自然度评分：每处问题扣 0.1，最低 0
    naturality_score = max(0.0, 1.0 - 0.1 * total_issues)
    passed = total_issues == 0

    return {
        "broken_expression_count": broken_count,
        "mechanical_transition_count": mechanical_count,
        "broken_expressions": broken_hits,
        "mechanical_transitions": mechanical_hits,
        "naturality_score": round(naturality_score, 2),
        "passed": passed,
        "desc": (
            f"语言自然度: {naturality_score:.2f} "
            f"(断裂式 {broken_count} 处, 机械过渡 {mechanical_count} 处)"
        ),
    }


# ============================================================================
# ★v1.1新增：节奏、多样性、机械模式检测
# ============================================================================

def calculate_sentence_rhythm(text: str) -> Dict[str, Any]:
    """
    ★v1.1新增：计算句子节奏（句长方差），判定僵硬化与散文化。

    算法：按句末标点（。！？）切分句子，计算句长方差。
        - 方差过低（<8.0）：句长过于单一，疑似僵硬化（AI痕迹）
        - 方差过高（>25.0）：句长过于跳跃，疑似散文化
        - 理想区间：8.0-25.0，长短句交替有呼吸感

    参数:
        text: 论文文本

    返回:
        节奏检测结果字典，包含：
        - variance: float — 句长方差
        - mean_length: float — 平均句长
        - short_sentence_ratio: float — 短句（≤15字）占比
        - long_sentence_ratio: float — 长句（>50字）占比
        - too_uniform: bool — 是否僵硬化（方差过低）
        - too_jumpy: bool — 是否散文化（方差过高）
        - passed: bool — 是否通过
        - desc: str — 描述信息
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

    too_uniform = variance < RHYTHM_METRICS["sentence_length_variance_min"]
    too_jumpy = variance > RHYTHM_METRICS["sentence_length_variance_max"]
    short_ratio_low = short_ratio < RHYTHM_METRICS["short_sentence_ratio_min"]
    long_ratio_high = long_ratio > RHYTHM_METRICS["long_sentence_ratio_max"]

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

    参数:
        text: 论文文本

    返回:
        多样性检测结果字典，包含：
        - diversity: float — 段落开头多样性（0-1）
        - unique_openings: int — 独特开头数
        - total_paragraphs: int — 总段落数
        - max_consecutive_connector: int — 最大连续相同连接词数
        - passed: bool — 是否通过
        - desc: str — 描述信息
    """
    if not text:
        return {
            "diversity": 1.0, "unique_openings": 0, "total_paragraphs": 0,
            "max_consecutive_connector": 0,
            "passed": True, "desc": "段落开头多样性: 文本为空",
        }

    # 按空行分段，过滤过短段落
    paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]
    if len(paragraphs) < 5:
        return {
            "diversity": 1.0, "unique_openings": 0, "total_paragraphs": len(paragraphs),
            "max_consecutive_connector": 0,
            "passed": True, "desc": "段落开头多样性: 段落数不足（<5）",
        }

    # 计算独特开头占比
    openings = [p[:6] for p in paragraphs]
    unique = len(set(openings))
    diversity = unique / len(openings)

    # 检测连续相同连接词
    consecutive = 0
    max_consecutive = 0
    last_connector = None
    for p in paragraphs:
        first_word = p[:2]
        if first_word in PARAGRAPH_OPENING_CONNECTORS:
            if first_word == last_connector:
                consecutive += 1
                max_consecutive = max(max_consecutive, consecutive)
            else:
                consecutive = 1
                last_connector = first_word
        else:
            consecutive = 0
            last_connector = None

    diversity_low = diversity < RHYTHM_METRICS["paragraph_opening_diversity_min"]
    consecutive_high = max_consecutive > RHYTHM_METRICS["max_consecutive_same_connector"]
    passed = not (diversity_low or consecutive_high)

    issues = []
    if diversity_low:
        issues.append(f"多样性不足({diversity:.2f})")
    if consecutive_high:
        issues.append(f"连续相同连接词{max_consecutive}处")

    desc = (
        f"段落开头多样性: {diversity:.2f} "
        f"(独特{unique}/{len(openings)}, "
        f"最大连续连接词{max_consecutive})"
    )
    if issues:
        desc += "（" + "; ".join(issues) + "）"

    return {
        "diversity": round(diversity, 2),
        "unique_openings": unique,
        "total_paragraphs": len(paragraphs),
        "max_consecutive_connector": max_consecutive,
        "diversity_low": diversity_low,
        "consecutive_high": consecutive_high,
        "passed": passed,
        "desc": desc,
    }


def detect_mechanical_patterns(text: str) -> Dict[str, Any]:
    """
    ★v1.1新增：检测机械式模式（断裂式罗列、模板化套话）。

    检测两类机械模式：
        1. 断裂式罗列：第一/第二/第三、首先/其次/再次、一方面/另一方面
        2. 模板化套话：具有重要的理论意义和实践意义、在新时代背景下、综上所述等

    参数:
        text: 论文文本

    返回:
        机械模式检测结果字典，包含：
        - patterns_found: List[str] — 命中的机械模式列表
        - count: int — 命中数量
        - passed: bool — 是否通过（命中数<阈值）
        - desc: str — 描述信息
    """
    if not text:
        return {
            "patterns_found": [], "count": 0,
            "passed": True, "desc": "机械模式: 文本为空",
        }

    mechanical: List[str] = []

    # 1. 检测断裂式罗列（使用正则）
    broken_patterns = [
        (r'第一[，,].*第二[，,].*第三', "断裂式罗列（第一/第二/第三）"),
        (r'首先[，,].*其次[，,].*再次', "断裂式罗列（首先/其次/再次）"),
        (r'一方面[，,].*另一方面[，,]', "断裂式罗列（一方面/另一方面）"),
        (r'其一[，,].*其二[，,].*其三', "断裂式罗列（其一/其二/其三）"),
    ]
    for pattern, label in broken_patterns:
        try:
            if re.search(pattern, text, re.DOTALL):
                mechanical.append(label)
        except re.error:
            continue

    # 2. 检测模板化套话
    template_phrases = [
        "具有重要的理论意义和实践意义",
        "在新时代背景下",
        "综上所述",
        "众所周知",
        "不言而喻",
        "毋庸置疑",
        "深刻地改变了",
        "产生了深远的影响",
        "具有重要的现实意义",
    ]
    for phrase in template_phrases:
        if phrase in text:
            mechanical.append(f"模板化套话: '{phrase}'")

    count = len(mechanical)
    passed = count < RHYTHM_METRICS["mechanical_pattern_threshold"]

    desc = f"机械模式: {count}处"
    if mechanical:
        desc += "（" + "; ".join(mechanical[:3]) + "）"

    return {
        "patterns_found": mechanical,
        "count": count,
        "passed": passed,
        "desc": desc,
    }


# ============================================================================
# ★v1.4新增：硬转折检测增强
# 来源：基于真实CSSCI论文过渡模式提取结果（5种过渡方式 + 5条反面案例）
# 核心策略：检测并修复"断裂式""硬转折"语言问题，引用真实示例作为修复参考
# ============================================================================

# 硬转折检测模式：无让步的转折词、无递进的递进词、无承接的总结词
HARD_TRANSITION_PATTERNS: List[Dict[str, Any]] = [
    {
        "name": "无让步的'但是'",
        "pattern": r"但是[^尽管虽然固然诚然]{1,30}[，,。]",
        "description": "使用'但是'转折时未先承认对立面或局限，直接转向对立论点",
        "fix_reference": "应改为'尽管...但'让步-推进结构，"
                        "参考：'尽管自我追踪文化被众多研究视为一种\"自我技术\"，"
                        "能够改善人的健康、生活及其他方面...但这种现象模糊了强制与同意，"
                        "以及权力与反抗之间的关系'——雷紫雯《做自己的医生》",
    },
    {
        "name": "无让步的'然而'",
        "pattern": r"然而[^，,。]{0,5}[，,]",
        "description": "使用'然而'转折时未先承认对立面或局限",
        "fix_reference": "应改为'当然...然而'或'尽管...然而'让步-推进结构，"
                        "参考：'当然，我们必须承认，种族、性别在五官、脸型、面部皮肤等层面的"
                        "显著区分某种程度上是生物性差异的客观反映'——黄阳坤《刻板印象》",
    },
    {
        "name": "无递进的'不仅'",
        "pattern": r"不仅[^更还也]{1,20}[，,]",
        "description": "使用'不仅'递进时后项与前项处于同一层次，未实现论证层次的提升",
        "fix_reference": "应改为'不仅...更/还'层次深化结构，"
                        "参考：'生育APP不仅使生理周期可见，其汇总并生成可视化图表的功能"
                        "还为用户提供了一种理解自我的手段'——雷紫雯《做自己的医生》",
    },
    {
        "name": "无承接的'综上'",
        "pattern": r"综上(?:所述)?[，,][^承基]{1,30}",
        "description": "使用'综上'总结时未承接前段核心概念，直接跳转到新结论",
        "fix_reference": "应改为'承前所述'或'基于此'概念承接结构，"
                        "参考：'承前所述，新闻信息的共现与共同可见性是新闻凝聚力的基础，"
                        "更关键的问题是：共现的新闻能否促成以及促成怎样的共同认知、情感与意义'"
                        "——黄阳坤《共现性》",
    },
]

# 机械连接词分类（用于检测连续使用）
MECHANICAL_CONNECTOR_CATEGORIES: Dict[str, List[str]] = {
    "并列连接词": ["此外", "另外", "同时", "除此之外"],
    "序数连接词": ["首先", "其次", "再次", "最后"],
    "因果连接词": ["因此", "所以", "由此", "综上"],
    "转折连接词": ["然而", "但是", "不过"],
    "递进连接词": ["进而", "更进一步", "不仅如此"],
}

# 概念承接标志词（用于检测段落开头是否有概念承接）
CONCEPT_CONTINUATION_MARKERS: List[str] = [
    "承前所述", "基于此", "在此基础上", "由此", "据此",
    "本文希望", "本研究", "面对", "针对", "通过重新",
    "依循", "按照", "正如", "同样",
]


def detect_hard_transitions(text: str) -> Dict[str, Any]:
    """
    ★v1.4新增：检测硬转折（无让步的转折、无递进的递进、无承接的总结）。

    检测以下3类硬转折：
        1. 无让步的"但是"/"然而"：使用转折词时未先承认对立面或局限
        2. 无递进的"不仅"：使用递进词时后项与前项处于同一层次
        3. 无承接的"综上"：使用总结词时未承接前段核心概念

    参数:
        text: 论文文本

    返回:
        硬转折检测结果字典，包含：
        - hard_transitions: List[Dict] — 命中的硬转折列表
        - count: int — 命中数量
        - passed: bool — 是否通过（0处问题即通过）
        - fix_references: List[str] — 修复参考示例
        - desc: str — 描述信息
    """
    if not text:
        return {
            "hard_transitions": [], "count": 0,
            "passed": True, "fix_references": [],
            "desc": "硬转折检测: 文本为空",
        }

    hits: List[Dict[str, str]] = []
    fix_refs: List[str] = []

    for pattern_info in HARD_TRANSITION_PATTERNS:
        try:
            matches = re.findall(pattern_info["pattern"], text)
            if matches:
                for m in matches:
                    preview = m[:60] + "..." if len(m) > 60 else m
                    hits.append({
                        "type": pattern_info["name"],
                        "preview": preview,
                        "description": pattern_info["description"],
                        "fix_reference": pattern_info["fix_reference"],
                    })
                    if pattern_info["fix_reference"] not in fix_refs:
                        fix_refs.append(pattern_info["fix_reference"])
        except re.error:
            continue

    count = len(hits)
    passed = count == 0

    desc = f"硬转折检测: {count}处"
    if hits:
        type_counts: Dict[str, int] = {}
        for h in hits:
            type_counts[h["type"]] = type_counts.get(h["type"], 0) + 1
        type_str = "; ".join(f"{k}{v}处" for k, v in type_counts.items())
        desc += f"（{type_str}）"

    return {
        "hard_transitions": hits,
        "count": count,
        "passed": passed,
        "fix_references": fix_refs,
        "desc": desc,
    }


def detect_mechanical_connectors(text: str, threshold: int = 3) -> Dict[str, Any]:
    """
    ★v1.4新增：检测机械连接词的连续使用（连续≥3段以同类连接词开头）。

    检测以下5类机械连接词的连续使用：
        1. 并列连接词：此外、另外、同时、除此之外
        2. 序数连接词：首先、其次、再次、最后
        3. 因果连接词：因此、所以、由此、综上
        4. 转折连接词：然而、但是、不过
        5. 递进连接词：进而、更进一步、不仅如此

    参数:
        text: 论文文本
        threshold: 连续使用触发阈值（默认3段）

    返回:
        机械连接词检测结果字典，包含：
        - mechanical_sequences: List[Dict] — 命中的机械序列列表
        - count: int — 命中序列数量
        - max_consecutive: int — 最大连续段数
        - passed: bool — 是否通过
        - fix_references: List[str] — 修复参考示例
        - desc: str — 描述信息
    """
    if not text:
        return {
            "mechanical_sequences": [], "count": 0,
            "max_consecutive": 0, "passed": True,
            "fix_references": [],
            "desc": "机械连接词检测: 文本为空",
        }

    # 按空行分段，过滤过短段落
    paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]
    if len(paragraphs) < threshold:
        return {
            "mechanical_sequences": [], "count": 0,
            "max_consecutive": 0, "passed": True,
            "fix_references": [],
            "desc": f"机械连接词检测: 段落数不足（<{threshold}）",
        }

    # 检测每段开头是否为机械连接词
    sequences: List[Dict[str, Any]] = []
    current_category: Optional[str] = None
    current_count = 0
    current_start_idx = 0

    for idx, p in enumerate(paragraphs):
        first_2 = p[:2]
        first_3 = p[:3]
        first_4 = p[:4]

        # 匹配连接词类别
        matched_category = None
        for category, connectors in MECHANICAL_CONNECTOR_CATEGORIES.items():
            for conn in connectors:
                if (len(conn) == 2 and first_2 == conn) or \
                   (len(conn) == 3 and first_3 == conn) or \
                   (len(conn) == 4 and first_4 == conn):
                    matched_category = category
                    break
            if matched_category:
                break

        if matched_category:
            if matched_category == current_category:
                current_count += 1
            else:
                # 保存前一个序列
                if current_count >= threshold:
                    sequences.append({
                        "category": current_category,
                        "start_paragraph": current_start_idx,
                        "consecutive_count": current_count,
                        "connectors_used": [
                            paragraphs[i][:4] for i in range(
                                current_start_idx, current_start_idx + current_count
                            )
                        ],
                    })
                current_category = matched_category
                current_count = 1
                current_start_idx = idx
        else:
            # 非连接词开头，保存前一个序列
            if current_category and current_count >= threshold:
                sequences.append({
                    "category": current_category,
                    "start_paragraph": current_start_idx,
                    "consecutive_count": current_count,
                    "connectors_used": [
                        paragraphs[i][:4] for i in range(
                            current_start_idx, current_start_idx + current_count
                        )
                    ],
                })
            current_category = None
            current_count = 0

    # 保存最后一个序列
    if current_category and current_count >= threshold:
        sequences.append({
            "category": current_category,
            "start_paragraph": current_start_idx,
            "consecutive_count": current_count,
            "connectors_used": [
                paragraphs[i][:4] for i in range(
                    current_start_idx, current_start_idx + current_count
                )
            ],
        })

    count = len(sequences)
    max_consecutive = max((s["consecutive_count"] for s in sequences), default=0)
    passed = count == 0

    # 修复参考
    fix_refs = [
        "概念锚定型：'承前所述，新闻信息的共现与共同可见性是新闻凝聚力的基础，"
        "更关键的问题是：共现的新闻能否促成以及促成怎样的共同认知、情感与意义'——黄阳坤《共现性》",
        "递进深化型：'更为重要的是，随着新闻信息共现性的消逝，"
        "新闻传播作为社会粘合剂的关系性价值便陷入结构性困境'——黄阳坤《共现性》",
        "经验切入型：'三大日系便利店巨头7-11、全家、罗森，在中国开出2000家店，"
        "分别用了15年、16年和23年，N企业只用了3年'——刘战伟《蜂王》",
    ]

    desc = f"机械连接词检测: {count}个序列, 最大连续{max_consecutive}段"
    if sequences:
        seq_str = "; ".join(
            f"{s['category']}连续{s['consecutive_count']}段" for s in sequences[:3]
        )
        desc += f"（{seq_str}）"

    return {
        "mechanical_sequences": sequences,
        "count": count,
        "max_consecutive": max_consecutive,
        "passed": passed,
        "fix_references": fix_refs,
        "desc": desc,
    }


def detect_concept_disconnect(text: str) -> Dict[str, Any]:
    """
    ★v1.4新增：检测段落开头与前段末尾概念无承接的情况。

    检测段落开头是否使用了概念承接标志词（如"承前所述""基于此""在此基础上"等），
    以及段落开头是否为机械连接词（如"此外""另外"等）而无概念承接。

    参数:
        text: 论文文本

    返回:
        概念断裂检测结果字典，包含：
        - disconnected_paragraphs: List[Dict] — 概念断裂段落列表
        - count: int — 断裂数量
        - concept_continuation_count: int — 概念承接段落数量
        - total_paragraphs: int — 总段落数
        - continuation_ratio: float — 概念承接比例
        - passed: bool — 是否通过
        - fix_references: List[str] — 修复参考示例
        - desc: str — 描述信息
    """
    if not text:
        return {
            "disconnected_paragraphs": [], "count": 0,
            "concept_continuation_count": 0, "total_paragraphs": 0,
            "continuation_ratio": 0.0, "passed": True,
            "fix_references": [],
            "desc": "概念断裂检测: 文本为空",
        }

    # 按空行分段，过滤过短段落
    paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]
    if len(paragraphs) < 3:
        return {
            "disconnected_paragraphs": [], "count": 0,
            "concept_continuation_count": 0, "total_paragraphs": len(paragraphs),
            "continuation_ratio": 1.0, "passed": True,
            "fix_references": [],
            "desc": "概念断裂检测: 段落数不足（<3）",
        }

    # 机械连接词列表（无概念承接的标志）
    mechanical_connectors_flat = [
        conn for conns in MECHANICAL_CONNECTOR_CATEGORIES.values() for conn in conns
    ]

    disconnected: List[Dict[str, Any]] = []
    concept_continuation_count = 0

    # 从第2段开始检查（第1段无前段可承接）
    for idx in range(1, len(paragraphs)):
        p = paragraphs[idx]
        first_6 = p[:6]

        # 检查是否有概念承接标志词
        has_continuation = any(
            marker in first_6 for marker in CONCEPT_CONTINUATION_MARKERS
        )

        # 检查是否以机械连接词开头
        is_mechanical = False
        for conn in mechanical_connectors_flat:
            if p.startswith(conn):
                is_mechanical = True
                break

        if has_continuation:
            concept_continuation_count += 1
        elif is_mechanical:
            # 以机械连接词开头且无概念承接
            disconnected.append({
                "paragraph_index": idx,
                "opening": first_6,
                "issue": f"段落以机械连接词'{first_6[:2]}'开头，无概念承接",
                "fix_reference": "应改为概念锚定型：'承前所述，...' 或 '基于此，...'",
            })

    count = len(disconnected)
    total_checkable = len(paragraphs) - 1  # 排除第1段
    continuation_ratio = concept_continuation_count / total_checkable if total_checkable > 0 else 0.0
    # 通过标准：概念断裂≤总段落的30%，且概念承接比例≥20%
    passed = count <= total_checkable * 0.3 and continuation_ratio >= 0.2

    # 修复参考
    fix_refs = [
        "概念锚定型：'承前所述，新闻信息的共现与共同可见性是新闻凝聚力的基础，"
        "更关键的问题是：共现的新闻能否促成以及促成怎样的共同认知、情感与意义'——黄阳坤《共现性》",
        "概念锚定型：'基于此，本研究结合虚拟代理测试（ABT）与时变网络分析（TNA），"
        "在国内某头部算法短视频平台部署了90名新闻兴趣与消费习惯各异的虚拟用户'——黄阳坤《共现性》",
        "概念锚定型：'因此，本研究从福柯的'生命政治'（biopolitics）等相关理论概念出发，"
        "重点关注女性孕产过程中的备孕环节'——雷紫雯《做自己的医生》",
    ]

    desc = (
        f"概念断裂检测: {count}处断裂, 概念承接比例{continuation_ratio:.0%} "
        f"({concept_continuation_count}/{total_checkable})"
    )
    if not passed:
        if count > total_checkable * 0.3:
            desc += f"（断裂比例{count/total_checkable:.0%}超阈值30%）"
        if continuation_ratio < 0.2:
            desc += f"（概念承接比例{continuation_ratio:.0%}低于20%）"

    return {
        "disconnected_paragraphs": disconnected,
        "count": count,
        "concept_continuation_count": concept_continuation_count,
        "total_paragraphs": len(paragraphs),
        "continuation_ratio": round(continuation_ratio, 2),
        "passed": passed,
        "fix_references": fix_refs,
        "desc": desc,
    }


# ============================================================================
# ★v1.8新增：直引号字符检测（宋体弯引号强制）
# 核心策略：检测论文文本中是否包含直引号字符（U+0022, U+0027），
#           所有中文论文必须使用弯引号（""''），禁止直引号
# ============================================================================

# 直引号字符（必须替换为弯引号）
STRAIGHT_DOUBLE_QUOTE = '"'  # U+0022
STRAIGHT_SINGLE_QUOTE = "'"  # U+0027
# 弯引号字符（合规）
CURLY_DOUBLE_OPEN = """  # U+201C
CURLY_DOUBLE_CLOSE = """  # U+201D
CURLY_SINGLE_OPEN = "'"  # U+2018
CURLY_SINGLE_CLOSE = "'"  # U+2019


def detect_straight_quotes(text: str) -> Dict[str, Any]:
    """★v1.8新增：检测论文文本中的直引号字符

    所有中文论文必须使用弯引号（""''），禁止直引号（"'）。
    本函数检测文本中是否包含直引号字符，并返回违规位置与上下文。

    Args:
        text: 待检测的论文文本

    Returns:
        检测结果字典：
            - straight_quote_count: 直引号总数
            - double_straight_count: 直双引号数量
            - single_straight_count: 直单引号数量
            - violations: 违规位置列表（含上下文）
            - passed: 是否通过（无直引号即通过）
            - fix_suggestion: 修复建议
    """
    violations = []
    double_count = 0
    single_count = 0

    for i, char in enumerate(text):
        if char == STRAIGHT_DOUBLE_QUOTE:
            double_count += 1
            start = max(0, i - 20)
            end = min(len(text), i + 21)
            context = text[start:end]
            violations.append({
                "position": i,
                "char": '"',
                "type": "double_straight",
                "context": context,
                "suggestion": "应替换为弯引号 \u201c 或 \u201d",
            })
        elif char == STRAIGHT_SINGLE_QUOTE:
            single_count += 1
            start = max(0, i - 20)
            end = min(len(text), i + 21)
            context = text[start:end]
            violations.append({
                "position": i,
                "char": "'",
                "type": "single_straight",
                "context": context,
                "suggestion": "应替换为弯引号 ' 或 '",
            })

    total = double_count + single_count
    passed = total == 0

    fix_suggestion = ""
    if not passed:
        fix_suggestion = (
            f"检测到{total}处直引号（双引号{double_count}处、单引号{single_count}处）。"
            f"所有引号必须替换为宋体弯引号：双引号使用""（U+201C/U+201D），"
            f"单引号使用''（U+2018/U+2019）。"
        )

    return {
        "straight_quote_count": total,
        "double_straight_count": double_count,
        "single_straight_count": single_count,
        "violations": violations[:20],  # 限制返回数量，避免过长
        "passed": passed,
        "fix_suggestion": fix_suggestion,
    }


# ============================================================================
# ★v7.4新增：段内首句-第二句衔接断裂检测
# 核心策略：基于数据库6篇真实CSSCI论文实证，段内首句与第二句应有自然衔接。
#           综合三维度评分：句长差异 + 词汇重叠度 + 风格匹配
# ============================================================================

# 判断动词列表（用于维度3：首句判断句识别）
JUDGMENT_VERBS = ["是", "乃", "系", "为", "构成", "形成", "属于", "呈现", "表现为"]
# 健康过渡词列表（用于维度3：第二句开头是否有过渡词）
HEALTHY_TRANSITION_WORDS = [
    "具体而言", "数据显示", "例如", "比如", "一方面",
    "具体来说", "换言之", "也就是说", "事实上", "实际上",
    "这是因为", "其原因在于", "更进一步",
]
# 常见停用词（用于维度2：词汇重叠度计算时过滤）
STOP_WORDS = {
    "的", "了", "和", "是", "在", "有", "就", "不", "这", "那",
    "也", "都", "与", "及", "或", "以", "为", "于", "而", "但",
    "则", "其", "之", "所", "被", "把", "让", "使", "给", "对",
    "从", "向", "到", "上", "下", "中", "里", "外", "前", "后",
}


def _tokenize_chinese(text: str) -> List[str]:
    """★v7.4内部函数：中文分词（优先 jieba，回退至 2-gram 字符匹配）

    Args:
        text: 待分词的文本

    Returns:
        实词列表（已过滤停用词和单字符）
    """
    if not text:
        return []
    try:
        import jieba
        tokens = jieba.lcut(text)
        return [t for t in tokens if len(t) >= 2 and t not in STOP_WORDS]
    except ImportError:
        # 回退至 2-gram 字符匹配
        clean = re.sub(r'[^\u4e00-\u9fa5A-Za-z0-9]', '', text)
        return [clean[i:i+2] for i in range(len(clean) - 1)
                if clean[i:i+2] not in STOP_WORDS]


def _detect_intra_paragraph_disconnect_single(
    paragraph: str,
    para_idx: int,
) -> Dict[str, Any]:
    """★v7.4内部函数：检测单个段落的段内首句-第二句断裂

    Returns:
        单段落检测结果字典
    """
    # 句子切分：按句末标点（。！？）切分
    sentences = [s.strip() for s in re.split(r'[。！？]', paragraph) if s.strip()]
    if len(sentences) < 2:
        return {"passed": True, "reason": "段落句子数不足2句"}

    first_sent = sentences[0]
    second_sent = sentences[1]
    len_first = len(first_sent)
    len_second = len(second_sent)

    # 维度1：句长差异（首句>40字且第二句<15字触发）
    dim1_triggered = (len_first > 40 and len_second < 15)

    # 维度2：词汇重叠度（共享实词<2个触发）
    tokens_first = set(_tokenize_chinese(first_sent))
    tokens_second = set(_tokenize_chinese(second_sent))
    shared = tokens_first & tokens_second
    dim2_triggered = (len(shared) < 2)

    # 维度3：风格匹配（首句判断句 + 第二句数据陈述 + 第二句开头无过渡词）
    is_judgment_first = any(verb in first_sent for verb in JUDGMENT_VERBS)
    has_data_in_second = bool(re.search(r'\d+%?|\d+\.\d+', second_sent))
    starts_with_healthy_transition = any(
        second_sent.startswith(word) for word in HEALTHY_TRANSITION_WORDS
    )
    dim3_triggered = (is_judgment_first and has_data_in_second
                      and not starts_with_healthy_transition)

    # 评分：命中1维度=潜在断裂，命中2维度以上=严重断裂
    hit_count = sum([dim1_triggered, dim2_triggered, dim3_triggered])
    if hit_count >= 2:
        severity = "severe"
    elif hit_count == 1:
        severity = "potential"
    else:
        severity = "none"

    return {
        "paragraph_index": para_idx,
        "first_sentence": first_sent[:60] + ("..." if len(first_sent) > 60 else ""),
        "second_sentence": second_sent[:60] + ("..." if len(second_sent) > 60 else ""),
        "len_first": len_first,
        "len_second": len_second,
        "shared_tokens_count": len(shared),
        "dim1_length_diff": dim1_triggered,
        "dim2_vocab_overlap": dim2_triggered,
        "dim3_style_match": dim3_triggered,
        "hit_count": hit_count,
        "severity": severity,
    }


def detect_intra_paragraph_disconnect(
    text: str,
    paragraphs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """★v7.4新增：检测段内首句-第二句风格断裂

    基于数据库6篇CSSCI论文实证，段内首句与第二句应有自然衔接。
    本函数综合三维度评分：
    1. 句长差异：首句>40字且第二句<15字 → 潜在断裂
    2. 词汇重叠度：首句与第二句共享实词<2个 → 潜在断裂
    3. 风格匹配：首句判断句+第二句数据陈述且无过渡词 → 潜在断裂

    Args:
        text: 待检测的论文文本（若提供 paragraphs 则优先使用）
        paragraphs: 已切分的段落列表（可选）

    Returns:
        检测结果字典：
            - total_paragraphs: 段落总数
            - potential_disconnects: 潜在斷裂数量
            - severe_disconnects: 严重斷裂数量（两维度以上命中）
            - violations: 违规详情列表
            - passed: 是否通过（无严重断裂即通过）
            - fix_suggestion: 修复建议
    """
    # 段落切分：优先使用 paragraphs 参数，否则按双换行切分 text
    if paragraphs is None:
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text.strip()) if p.strip()]

    potential_count = 0
    severe_count = 0
    violations = []
    min_para_length = 50  # 跳过短段落

    for idx, para in enumerate(paragraphs):
        if len(para) < min_para_length:
            continue
        result = _detect_intra_paragraph_disconnect_single(para, idx)
        if result.get("severity") == "severe":
            severe_count += 1
            violations.append(result)
        elif result.get("severity") == "potential":
            potential_count += 1
            violations.append(result)

    total = len(paragraphs)
    passed = severe_count == 0

    fix_suggestion = ""
    if not passed:
        fix_suggestion = (
            f"检测到{severe_count}处严重段内断裂（两维度以上命中）、"
            f"{potential_count}处潜在段内断裂。"
            f"修复策略：①抽象-具体断裂插入'具体而言''数据显示'过渡词；"
            f"②场景-理论断裂插入'这一现象指向''这背后是'概念桥接句；"
            f"③长短失衡断裂将短句扩展为长句，或插入逻辑收束句。"
        )

    desc = (
        f"段内衔接检测: 共{total}段, 潜在断裂{potential_count}处, "
        f"严重断裂{severe_count}处"
    )
    if not passed:
        desc += f"（{severe_count}处严重断裂需修复）"

    return {
        "total_paragraphs": total,
        "potential_disconnects": potential_count,
        "severe_disconnects": severe_count,
        "violations": violations[:20],
        "passed": passed,
        "fix_suggestion": fix_suggestion,
        "desc": desc,
    }


# ============================================================================
# ★v7.4新增：段间过渡质量检测（基于数据库6篇C刊实证）
# ★v5.0校准：机械连接词占比 >15% 触发修复（原 >30%，数据库实证正常占比 <15%）
# ============================================================================

# 机械连接词列表（段首出现即视为机械过渡）
MECHANICAL_TRANSITION_WORDS: List[str] = [
    "首先，", "其次，", "再次，", "最后，",
    "第一，", "第二，", "第三，",
    "一方面，", "另一方面，",
    "综上所述，", "总而言之，", "总的来说，",
    "如上所述，", "正如前文所述，",
    # 半角逗号变体
    "首先,", "其次,", "再次,", "最后,",
    "第一,", "第二,", "第三,",
    "一方面,", "另一方面,",
    "综上所述,", "总而言之,", "总的来说,",
    "如上所述,", "正如前文所述,",
]

# 机械连接词占比阈值（超过则触发修复）
# ★v5.0校准：0.30→0.15（基于数据库5篇C刊论文实证，正常占比<15%）
MECHANICAL_TRANSITION_RATIO_THRESHOLD = 0.15


def detect_paragraph_transition_quality(
    text: str,
    paragraphs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """★v7.4新增：检测段间过渡质量（机械连接词占比）

    基于数据库6篇C刊论文实证，机械连接词占段间过渡总数的比例：
        - 正常占比 <15%
        - 触发修复阈值 >15%（★v5.0校准：原 >30% → 现 >15%）

    检测维度：
        1. 段首机械连接词数量
        2. 机械连接词占段间过渡总数的比例
        3. 单一机械连接词全文出现次数（≤2 次）

    Args:
        text: 待检测的论文文本
        paragraphs: 段落列表（用于段间过渡检测）。若为 None，则按双换行切分

    Returns:
        检测结果字典：
            - passed: bool — 是否通过（机械连接词占比 ≤15% 且单一连接词 ≤2 次）
            - mechanical_count: int — 机械连接词段落数
            - total_transitions: int — 段间过渡总数（= 段落数 - 1）
            - mechanical_ratio: float — 机械连接词占比（0-1）
            - single_word_over_limit: List[str] — 单一连接词超限（>2 次）列表
            - violations: List[str] — 违规详情列表
            - desc: str — 描述信息
    """
    if not text:
        logger.warning("段间过渡质量检测：输入文本为空")
        return {
            "passed": True,
            "mechanical_count": 0,
            "total_transitions": 0,
            "mechanical_ratio": 0.0,
            "single_word_over_limit": [],
            "violations": [],
            "desc": "段间过渡质量检测: 文本为空",
        }

    # 段落切分
    if paragraphs is None:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    if len(paragraphs) <= 1:
        return {
            "passed": True,
            "mechanical_count": 0,
            "total_transitions": 0,
            "mechanical_ratio": 0.0,
            "single_word_over_limit": [],
            "violations": [],
            "desc": "段间过渡质量检测: 段落数不足（<2）",
        }

    # 段间过渡总数 = 段落数 - 1（首段无需过渡）
    subsequent_paragraphs = paragraphs[1:]
    total_transitions = len(subsequent_paragraphs)

    # 检测段首机械连接词
    mechanical_count = 0
    single_word_counts: Dict[str, int] = {}
    mechanical_paragraphs: List[int] = []

    for idx, para in enumerate(subsequent_paragraphs, start=1):  # 从第2段开始
        para_head = para[:30]  # 检查段首前30字
        for word in MECHANICAL_TRANSITION_WORDS:
            if word in para_head:
                mechanical_count += 1
                mechanical_paragraphs.append(idx)
                # 统计单一连接词出现次数（统一为全角逗号形式）
                normalized_word = word.replace(",", "，")
                single_word_counts[normalized_word] = single_word_counts.get(normalized_word, 0) + 1
                break  # 每段只计一次

    # 机械连接词占比
    mechanical_ratio = mechanical_count / total_transitions if total_transitions > 0 else 0.0

    # 单一连接词超限检测（>2 次）
    single_word_over_limit = [word for word, count in single_word_counts.items() if count > 2]

    # 违规判定
    violations: List[str] = []

    if mechanical_ratio > MECHANICAL_TRANSITION_RATIO_THRESHOLD:
        violations.append(
            f"机械连接词占比 {mechanical_ratio:.1%} 超过阈值 "
            f"{MECHANICAL_TRANSITION_RATIO_THRESHOLD:.0%}"
            f"（正常占比 <15%）"
        )

    for word, count in single_word_counts.items():
        if count > 2:
            violations.append(
                f"机械连接词 '{word}' 全文出现 {count} 次（上限 2 次）"
            )

    # 列出具体的机械过渡段落
    if mechanical_paragraphs:
        violations.append(
            f"机械过渡段落: 第 {', '.join(str(i) for i in mechanical_paragraphs[:10])} 段"
            + (f" 等 {len(mechanical_paragraphs)} 段" if len(mechanical_paragraphs) > 10 else "")
        )

    passed = len(violations) == 0

    desc = (
        f"段间过渡质量: 机械={mechanical_count}/{total_transitions}"
        f"（{mechanical_ratio:.1%}）, 阈值={MECHANICAL_TRANSITION_RATIO_THRESHOLD:.0%}, "
        f"单一超限={len(single_word_over_limit)}, 通过={passed}"
    )

    logger.info(
        "段间过渡质量检测: mechanical=%d/%d(%.1f%%), single_over=%d, passed=%s",
        mechanical_count, total_transitions, mechanical_ratio * 100,
        len(single_word_over_limit), passed
    )

    return {
        "passed": passed,
        "mechanical_count": mechanical_count,
        "total_transitions": total_transitions,
        "mechanical_ratio": round(mechanical_ratio, 3),
        "single_word_over_limit": single_word_over_limit,
        "violations": violations,
        "desc": desc,
    }


# ============================================================================
# ★v7.4重构：文言词汇三级词表（基于数据库6篇C刊实证）
# 与 gen/kb/human_language_features.md 4.2.1 节对齐
# ============================================================================

# 通用级词表（所有研究类型可用）：词汇 -> 每千字上限
CLASSICAL_VOCAB_UNIVERSAL: Dict[str, int] = {
    "亦": 2, "或": 2, "由此": 2, "然而": 3, "因而": 2,
    "综上": 1, "事实上": 1, "并非": 2, "鉴于": 1, "换言之": 1,
}

# 学科级词表（仅 qualitative/interview_report/theoretical 可用）：词汇 -> 每千字上限
CLASSICAL_VOCAB_ACADEMIC: Dict[str, int] = {
    "诸如": 3, "譬如": 1, "抑或": 1, "诚然": 1, "故": 2,
    "然则": 1, "遑论": 1, "概言之": 1,
}

# 禁用级词表（全部研究类型禁用，疑为AI痕迹）
CLASSICAL_VOCAB_FORBIDDEN: List[str] = [
    "凡此种种", "盖因", "是以", "亦或", "诚如",
]

# 研究类型 -> 可用层级
CLASSICAL_VOCAB_RESEARCH_TYPE_ACCESS: Dict[str, List[str]] = {
    "qualitative": ["universal", "academic"],
    "interview_report": ["universal", "academic"],
    "theoretical": ["universal", "academic"],
    "quantitative": ["universal"],
    "mixed": ["universal"],
    "computational": ["universal"],
}

# 总量控制阈值
CLASSICAL_TOTAL_PER_THOUSAND_MAX = 3       # 每千字文言词汇总数上限
CLASSICAL_SINGLE_PER_THOUSAND_MAX = 1      # 单一文言词汇每千字上限（兜底，预留未来使用）
CLASSICAL_MAX_KINDS_PER_PARAGRAPH = 2      # 同一段落文言词汇种类上限


def detect_classical_vocabulary_overuse(
    text: str,
    research_type: Optional[str] = None,
    paragraphs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """★v1.8新增，★v7.4重构：检测文言词汇过度使用（三级词表+研究类型守卫）

    基于数据库6篇C刊论文实证，将文言词汇按"研究类型"分级：
        - 通用级：所有研究类型可用，有每千字上限
        - 学科级：仅 qualitative/interview_report/theoretical 可用，有每千字上限
        - 禁用级：全部研究类型禁用（疑为AI痕迹）

    检测维度：
        1. 禁用级词汇扫描（出现即违规）
        2. 学科级研究类型守卫（禁用研究类型使用学科级词汇即违规）
        3. 单一词汇每千字上限
        4. 总量每千字上限
        5. 段落种类上限

    Args:
        text: 待检测的论文文本
        research_type: 研究类型（qualitative/quantitative/computational/
                       mixed/interview_report/theoretical）。若为 None，
                       则按最宽松规则检测（允许 universal+academic，但禁用级仍违规）
        paragraphs: 段落列表（用于段落种类检测）。若为 None，则按双换行切分

    Returns:
        检测结果字典：
            - passed: bool — 是否通过（无任何违规）
            - violations: List[str] — 违规详情列表
            - total_count: int — 文言词汇总出现次数
            - total_per_thousand: float — 每千字文言词汇数
            - forbidden_hits: List[str] — 命中的禁用级词汇
            - academic_guard_hits: List[str] — 命中的学科级守卫违规
            - over_threshold_hits: List[str] — 单词超限违规
            - total_over_threshold: bool — 总量超限
            - paragraph_kinds_over: List[int] — 段落种类超限的段落索引
            - desc: str — 描述信息
    """
    if not text:
        logger.warning("文言词汇检测：输入文本为空")
        return {
            "passed": True,
            "violations": [],
            "total_count": 0,
            "total_per_thousand": 0.0,
            "forbidden_hits": [],
            "academic_guard_hits": [],
            "over_threshold_hits": [],
            "total_over_threshold": False,
            "paragraph_kinds_over": [],
            "desc": "文言词汇检测: 文本为空",
        }

    # 计算中文字数
    chinese_chars = len(re.findall(r'[一-鿿]', text))
    thousand_units = max(chinese_chars / 1000, 0.001)  # 避免除零

    # 确定可用层级
    if research_type is None:
        accessible_levels = ["universal", "academic"]
    else:
        accessible_levels = CLASSICAL_VOCAB_RESEARCH_TYPE_ACCESS.get(
            research_type, ["universal"]
        )

    violations: List[str] = []
    forbidden_hits: List[str] = []
    academic_guard_hits: List[str] = []
    over_threshold_hits: List[str] = []
    paragraph_kinds_over: List[int] = []

    # 构建可用词表（词汇 -> 每千字上限）
    accessible_thresholds: Dict[str, int] = {}
    if "universal" in accessible_levels:
        accessible_thresholds.update(CLASSICAL_VOCAB_UNIVERSAL)
    if "academic" in accessible_levels:
        accessible_thresholds.update(CLASSICAL_VOCAB_ACADEMIC)

    # 1. 禁用级词汇扫描
    for word in CLASSICAL_VOCAB_FORBIDDEN:
        count = text.count(word)
        if count > 0:
            forbidden_hits.append(word)
            violations.append(
                f"禁用级文言词汇 '{word}' 出现 {count} 次（疑为AI痕迹，直接禁用）"
            )

    # 2. 学科级研究类型守卫
    if "academic" not in accessible_levels:
        # 当前研究类型禁用学科级
        for word in CLASSICAL_VOCAB_ACADEMIC:
            count = text.count(word)
            if count > 0:
                academic_guard_hits.append(word)
                violations.append(
                    f"学科级文言词汇 '{word}' 出现 {count} 次"
                    f"（research_type={research_type} 禁用学科级词汇）"
                )

    # 3. 单一词汇每千字上限
    total_count = 0
    for word, threshold in accessible_thresholds.items():
        count = text.count(word)
        if count > 0:
            per_thousand = count / thousand_units
            total_count += count
            if per_thousand > threshold:
                over_threshold_hits.append(word)
                violations.append(
                    f"文言词汇 '{word}' 出现 {count} 次"
                    f"（{per_thousand:.2f}/千字, 上限 {threshold}/千字）"
                )

    # 4. 总量每千字上限
    total_per_thousand = total_count / thousand_units
    total_over_threshold = total_per_thousand > CLASSICAL_TOTAL_PER_THOUSAND_MAX
    if total_over_threshold:
        violations.append(
            f"文言词汇总量 {total_count} 次（{total_per_thousand:.2f}/千字, "
            f"上限 {CLASSICAL_TOTAL_PER_THOUSAND_MAX}/千字）"
        )

    # 5. 段落种类上限
    if paragraphs is None:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    all_classical_words = list(accessible_thresholds.keys())
    for idx, para in enumerate(paragraphs):
        kinds_in_para = sum(1 for w in all_classical_words if w in para)
        if kinds_in_para > CLASSICAL_MAX_KINDS_PER_PARAGRAPH:
            paragraph_kinds_over.append(idx)
            violations.append(
                f"第 {idx + 1} 段包含 {kinds_in_para} 种文言词汇"
                f"（上限 {CLASSICAL_MAX_KINDS_PER_PARAGRAPH} 种）"
            )

    passed = len(violations) == 0

    # 拼接描述
    desc_parts = [
        f"文言词汇: 总量={total_count}（{total_per_thousand:.2f}/千字）",
        f"禁用级命中={len(forbidden_hits)}",
        f"学科级守卫违规={len(academic_guard_hits)}",
        f"单词超限={len(over_threshold_hits)}",
        f"段落种类超限={len(paragraph_kinds_over)}",
    ]
    if research_type:
        desc_parts.append(f"research_type={research_type}")
    desc = "文言词汇检测: " + ", ".join(desc_parts) + f", 通过={passed}"

    logger.info(
        "文言词汇检测: total=%d(%.2f/千字), forbidden=%d, guard=%d, "
        "over=%d, para_kinds=%d, research_type=%s, passed=%s",
        total_count, total_per_thousand, len(forbidden_hits),
        len(academic_guard_hits), len(over_threshold_hits),
        len(paragraph_kinds_over), research_type, passed
    )

    return {
        "passed": passed,
        "violations": violations,
        "total_count": total_count,
        "total_per_thousand": round(total_per_thousand, 2),
        "forbidden_hits": forbidden_hits,
        "academic_guard_hits": academic_guard_hits,
        "over_threshold_hits": over_threshold_hits,
        "total_over_threshold": total_over_threshold,
        "paragraph_kinds_over": paragraph_kinds_over,
        "desc": desc,
    }


def detect_numeric_format_violations(text: str) -> Dict[str, Any]:
    """★v5.1新增：检测数字使用规范违规（review pipeline 版）

    规则：数据数字用阿拉伯数字，严肃数字用汉字数字。
    严肃数字语境后若紧跟阿拉伯数字，则判定为违规。
    数据数字语境后若紧跟汉字数字，则判定为违规。

    Args:
        text: 待检测文本

    Returns:
        检测结果字典
    """
    solemn_contexts = [
        "新中国成立", "改革开放", "五四运动", "辛亥革命", "建党",
        "抗战", "解放战争", "新中国成立以来", "改革开放以来",
        "建党以来", "百年", "十年", "数十年", "几个世纪", "千年",
    ]
    data_contexts = [
        "样本量", "样本数", "受访者", "被试", "问卷份数", "有效问卷",
        "回归系数", "百分比", "比例", "频次", "次数", "人次", "篇次",
    ]

    violations: List[str] = []
    violation_count = 0

    for context in solemn_contexts:
        pattern = re.escape(context) + r"[^\d一二三四五六七八九十百千零]{0,3}(\d+)[\s]*[年余载载余]"
        matches = re.findall(pattern, text)
        for match in matches:
            violation_count += 1
            violations.append(
                f"严肃数字语境'{context}'后误用阿拉伯数字'{match}'，应改为汉字数字"
            )

    chinese_num_pattern = r"[一二三四五六七八九十百千零]+"
    for context in data_contexts:
        pattern = re.escape(context) + r"[^\d一二三四五六七八九十百千零]{0,3}(" + chinese_num_pattern + r")"
        matches = re.findall(pattern, text)
        for match in matches:
            if len(match) <= 4 and match not in ["十余", "数余", "若干"]:
                violation_count += 1
                violations.append(
                    f"数据数字语境'{context}'后误用汉字数字'{match}'，应改为阿拉伯数字"
                )

    return {
        "violation_count": violation_count,
        "violations": violations[:10],
        "passed": violation_count == 0,
        "desc": (
            f"数字使用规范违规: {violation_count} 处"
        ) if violation_count > 0 else "数字使用规范通过",
    }


# ============================================================================
# ★v1.5新增：人类语言合规强制检查
# 来源：基于 human_language_features.md 第六章强制人类语言合规检查标准
# 核心策略：基于34篇真实CSSCI论文提取人类语言特征，实现四层合规检查中的
#           微观层面程序化检查（句长方差/段落开头多样性/AI高频词/短句收束）
# ============================================================================

# 人类语言合规检查阈值（基于 human_language_features.md 第6.1节）
HUMAN_LANGUAGE_THRESHOLDS: Dict[str, Any] = {
    # 6.1.1 句长方差检查：全文句长标准差≥10.0
    "sentence_length_std_min": 10.0,
    # 6.1.2 段落开头多样性检查：段落开头句式类型≥5种
    "paragraph_opening_types_min": 5,
    # 6.1.3 AI高频词检测阈值
    "ai_phrase_max_per_1000_words": {
        "值得注意的是": 1,   # ≤1次/千字
        "综上所述": 1,        # ≤1次/千字
    },
    "ai_phrase_forbidden": [
        "总而言之",           # 禁止使用（≤0次）
    ],
    # 作为段落开头时的限制
    "paragraph_opening_connector_max": {
        "此外": 2, "另外": 2,   # "此外""另外"作为段落开头≤2次/全文（合计）
    },
    "paragraph_opening_forbidden": [
        "首先", "其次", "再次", "最后",  # 禁止作为段落开头
    ],
    # 6.1.4 短句收束检查：每段末尾应有短句（≤20字）作判断收束
    "short_sentence_max_length": 20,
    "short_ending_ratio_min": 0.5,  # 至少50%的段落末尾有短句收束
}


def _calculate_sentence_length_std(text: str) -> float:
    """
    ★v1.5内部函数：计算全文句长标准差。

    算法：按句末标点（。！？）切分句子，计算句长的总体标准差。
    标准差≥10.0 表示句长波动较大，符合人类论文"长短交错"的特征。

    参数:
        text: 论文文本

    返回:
        句长标准差（float）。若句子数不足则返回0.0。
    """
    if not text:
        return 0.0
    # 按句末标点切分（保留有意义的句子）
    sentences = [s.strip() for s in re.split(r'[。！？]', text) if len(s.strip()) > 5]
    if len(sentences) < 5:
        return 0.0
    lengths = [len(s) for s in sentences]
    mean = sum(lengths) / len(lengths)
    variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)
    return variance ** 0.5


def _count_paragraph_opening_types(text: str) -> Tuple[int, List[str]]:
    """
    ★v1.5内部函数：统计段落开头句式类型数量。

    算法：按空行分段，取每段前6字符作为开头标识，统计独特开头数量。
    独特开头数≥5种 表示段落开头多样性符合人类论文特征。

    参数:
        text: 论文文本

    返回:
        元组 (独特开头数, 开头列表)
    """
    if not text:
        return (0, [])
    # 按空行分段，过滤过短段落
    paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]
    if len(paragraphs) < 3:
        return (0, [])
    # 取每段前6字符作为开头标识
    openings = [p[:6] for p in paragraphs]
    unique_openings = list(set(openings))
    return (len(unique_openings), unique_openings)


def _check_ai_phrases(text: str) -> List[Dict[str, Any]]:
    """
    ★v1.5内部函数：检测AI高频词。

    检查以下AI高频词的使用频率：
    - "值得注意的是"：≤1次/千字
    - "综上所述"：≤1次/千字
    - "总而言之"：禁止使用（≤0次）
    - "此外""另外"作为段落开头：≤2次/全文（合计）
    - "首先""其次""再次""最后"作为段落开头：禁止使用（≤0次）

    参数:
        text: 论文文本

    返回:
        违规项列表，每项为字典 {phrase, count, threshold, issue, suggestion}
    """
    if not text:
        return []
    violations: List[Dict[str, Any]] = []
    total_chars = check_chinese_word_count(text)
    thousand_words = total_chars / 1000 if total_chars > 0 else 1.0

    # 1. 检查"值得注意的是"频率（≤1次/千字）
    phrase = "值得注意的是"
    count = text.count(phrase)
    per_1000 = count / thousand_words if thousand_words > 0 else count
    if per_1000 > HUMAN_LANGUAGE_THRESHOLDS["ai_phrase_max_per_1000_words"]["值得注意的是"]:
        violations.append({
            "phrase": phrase,
            "count": count,
            "per_1000": round(per_1000, 2),
            "threshold": "≤1次/千字",
            "issue": f"'{phrase}'出现{count}次（{per_1000:.2f}次/千字），超过阈值1次/千字",
            "suggestion": f"删除或替换'{phrase}'，改为直接陈述值得注意的内容",
        })

    # 2. 检查"综上所述"频率（≤1次/千字）
    phrase = "综上所述"
    count = text.count(phrase)
    per_1000 = count / thousand_words if thousand_words > 0 else count
    if per_1000 > HUMAN_LANGUAGE_THRESHOLDS["ai_phrase_max_per_1000_words"]["综上所述"]:
        violations.append({
            "phrase": phrase,
            "count": count,
            "per_1000": round(per_1000, 2),
            "threshold": "≤1次/千字",
            "issue": f"'{phrase}'出现{count}次（{per_1000:.2f}次/千字），超过阈值1次/千字",
            "suggestion": f"删除或替换'{phrase}'，改为实质性归纳表述",
        })

    # 3. 检查"总而言之"（禁止使用）
    phrase = "总而言之"
    count = text.count(phrase)
    if count > 0:
        violations.append({
            "phrase": phrase,
            "count": count,
            "per_1000": None,
            "threshold": "禁止使用（≤0次）",
            "issue": f"'{phrase}'出现{count}次，该词为AI典型高频词，禁止使用",
            "suggestion": f"删除'{phrase}'，改为实质性总结或自然过渡",
        })

    # 4. 检查"此外""另外"作为段落开头（≤2次/全文，合计）
    paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]
    opening_connector_count = 0
    opening_connectors_found: List[str] = []
    for p in paragraphs:
        for conn in ["此外", "另外"]:
            if p.startswith(conn):
                opening_connector_count += 1
                opening_connectors_found.append(conn)
                break
    if opening_connector_count > HUMAN_LANGUAGE_THRESHOLDS["paragraph_opening_connector_max"]["此外"]:
        violations.append({
            "phrase": "此外/另外（段落开头）",
            "count": opening_connector_count,
            "per_1000": None,
            "threshold": "≤2次/全文（合计）",
            "issue": f"'此外''另外'作为段落开头共{opening_connector_count}次（{opening_connectors_found}），超过阈值2次/全文",
            "suggestion": "减少'此外''另外'作为段落开头，改为概念锚定型或经验切入型过渡",
        })

    # 5. 检查"首先""其次""再次""最后"作为段落开头（禁止使用）
    forbidden_openings_found: List[str] = []
    for p in paragraphs:
        for conn in HUMAN_LANGUAGE_THRESHOLDS["paragraph_opening_forbidden"]:
            if p.startswith(conn):
                forbidden_openings_found.append(conn)
                break
    if forbidden_openings_found:
        violations.append({
            "phrase": "首先/其次/再次/最后（段落开头）",
            "count": len(forbidden_openings_found),
            "per_1000": None,
            "threshold": "禁止使用（≤0次）",
            "issue": f"'首先/其次/再次/最后'作为段落开头共{len(forbidden_openings_found)}次（{forbidden_openings_found}），该模式为断裂式叙事，禁止使用",
            "suggestion": "删除'首先/其次/再次/最后'作为段落开头，改为自然逻辑递进或递进深化型过渡",
        })

    return violations


def _check_short_sentence_endings(text: str) -> Dict[str, Any]:
    """
    ★v1.5内部函数：检查短句收束。

    检查每段末尾是否有短句（≤20字）作判断收束。
    人类论文的特征是"每段或每论证单元末尾，以短句作判断收束，形成呼吸感"。

    参数:
        text: 论文文本

    返回:
        短句收束检查结果字典，包含：
        - total_paragraphs: int — 检查的段落数
        - short_ending_count: int — 末尾有短句收束的段落数
        - short_ending_ratio: float — 短句收束比例
        - missing_paragraphs: List[int] — 缺失短句收束的段落索引
        - passed: bool — 是否通过（比例≥50%）
    """
    if not text:
        return {
            "total_paragraphs": 0,
            "short_ending_count": 0,
            "short_ending_ratio": 0.0,
            "missing_paragraphs": [],
            "passed": True,
            "desc": "短句收束检查: 文本为空",
        }

    # 按空行分段，过滤过短段落
    paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]
    if len(paragraphs) < 3:
        return {
            "total_paragraphs": len(paragraphs),
            "short_ending_count": len(paragraphs),
            "short_ending_ratio": 1.0,
            "missing_paragraphs": [],
            "passed": True,
            "desc": "短句收束检查: 段落数不足（<3）",
        }

    max_len = HUMAN_LANGUAGE_THRESHOLDS["short_sentence_max_length"]
    short_ending_count = 0
    missing_paragraphs: List[int] = []

    for idx, p in enumerate(paragraphs):
        # 取段落最后一句（按句末标点切分）
        sentences = [s.strip() for s in re.split(r'[。！？]', p) if s.strip()]
        if not sentences:
            continue
        last_sentence = sentences[-1]
        if len(last_sentence) <= max_len:
            short_ending_count += 1
        else:
            missing_paragraphs.append(idx)

    total = len(paragraphs)
    ratio = short_ending_count / total if total > 0 else 0.0
    passed = ratio >= HUMAN_LANGUAGE_THRESHOLDS["short_ending_ratio_min"]

    desc = (
        f"短句收束检查: {short_ending_count}/{total}段有短句收束（比例{ratio:.0%}），"
        f"阈值≥{HUMAN_LANGUAGE_THRESHOLDS['short_ending_ratio_min']:.0%}"
    )
    if not passed:
        desc += f"（{len(missing_paragraphs)}段缺失短句收束）"

    return {
        "total_paragraphs": total,
        "short_ending_count": short_ending_count,
        "short_ending_ratio": round(ratio, 2),
        "missing_paragraphs": missing_paragraphs,
        "passed": passed,
        "desc": desc,
    }


def check_human_language_compliance(text: str) -> Dict[str, Any]:
    """
    ★v1.5新增：人类语言合规强制检查。

    基于 human_language_features.md 第六章强制人类语言合规检查标准，
    实现微观层面的程序化检查（四项核心检查）：

    1. 句长方差检查（6.1.1）：全文句长标准差≥10.0
    2. 段落开头多样性检查（6.1.2）：段落开头句式类型≥5种
    3. AI高频词检测（6.1.3）：
       - "值得注意的是"≤1次/千字
       - "综上所述"≤1次/千字
       - "总而言之"禁止使用
       - "此外""另外"作为段落开头≤2次/全文
       - "首先""其次""再次""最后"作为段落开头禁止使用
    4. 短句收束检查（6.1.4）：每段末尾应有短句（≤20字）作判断收束

    参数:
        text: 论文文本

    返回:
        人类语言合规检查结果字典，包含：
        - passed: bool — 是否通过（所有检查项均通过）
        - failed_checks: List[str] — 未通过项列表
        - suggestions: List[str] — 修复建议列表
        - sentence_length_std: float — 句长标准差
        - paragraph_opening_types: int — 段落开头类型数
        - ai_phrase_violations: List[Dict] — AI高频词违规详情
        - short_ending_check: Dict — 短句收束检查详情
        - desc: str — 综合描述信息
    """
    if not text:
        return {
            "passed": True,
            "failed_checks": [],
            "suggestions": [],
            "sentence_length_std": 0.0,
            "paragraph_opening_types": 0,
            "ai_phrase_violations": [],
            "short_ending_check": {},
            "desc": "人类语言合规检查: 文本为空",
        }

    failed_checks: List[str] = []
    suggestions: List[str] = []

    # ===== 检查项1：句长方差（6.1.1）=====
    sentence_std = _calculate_sentence_length_std(text)
    std_threshold = HUMAN_LANGUAGE_THRESHOLDS["sentence_length_std_min"]
    if sentence_std < std_threshold:
        failed_checks.append(
            f"6.1.1 句长方差: 标准差={sentence_std:.1f}，低于阈值{std_threshold:.1f}"
        )
        suggestions.append(
            f"句长方差不足（{sentence_std:.1f}<{std_threshold:.1f}）："
            f"注入长短交错要求，增加短句（8-15字）作判断收束，"
            f"偶尔使用超长句（80字以上）承载复杂论证，提升句长波动性"
        )

    # ===== 检查项2：段落开头多样性（6.1.2）=====
    opening_types, openings_list = _count_paragraph_opening_types(text)
    types_threshold = HUMAN_LANGUAGE_THRESHOLDS["paragraph_opening_types_min"]
    if opening_types < types_threshold:
        failed_checks.append(
            f"6.1.2 段落开头多样性: 类型数={opening_types}，低于阈值{types_threshold}"
        )
        suggestions.append(
            f"段落开头多样性不足（{opening_types}<{types_threshold}）："
            f"多样化段落开头方式，避免'本文认为''研究表明''此外'等机械重复，"
            f"使用概念锚定型、经验切入型、理论对话型等过渡方式"
        )

    # ===== 检查项3：AI高频词检测（6.1.3）=====
    ai_phrase_violations = _check_ai_phrases(text)
    if ai_phrase_violations:
        for v in ai_phrase_violations:
            failed_checks.append(f"6.1.3 AI高频词: {v['issue']}")
            suggestions.append(f"AI高频词修复: {v['suggestion']}")

    # ===== 检查项4：短句收束（6.1.4）=====
    short_ending_result = _check_short_sentence_endings(text)
    if not short_ending_result["passed"]:
        failed_checks.append(
            f"6.1.4 短句收束: {short_ending_result['desc']}"
        )
        suggestions.append(
            f"短句收束不足（比例{short_ending_result['short_ending_ratio']:.0%}）："
            f"在段落末尾增加≤20字的短句作判断收束，形成'呼吸感'，"
            f"缺失段落数: {len(short_ending_result['missing_paragraphs'])}"
        )

    # ===== 综合判定 =====
    passed = len(failed_checks) == 0

    # 构建综合描述
    desc_parts = [
        f"句长标准差={sentence_std:.1f}（阈值≥{std_threshold:.1f}）",
        f"段落开头类型={opening_types}（阈值≥{types_threshold}）",
        f"AI高频词违规={len(ai_phrase_violations)}项",
        f"短句收束比例={short_ending_result['short_ending_ratio']:.0%}",
    ]
    desc = "人类语言合规检查: " + ("✅通过" if passed else f"❌未通过（{len(failed_checks)}项）")
    desc += "（" + "; ".join(desc_parts) + "）"

    return {
        "passed": passed,
        "failed_checks": failed_checks,
        "suggestions": suggestions,
        "sentence_length_std": round(sentence_std, 1),
        "paragraph_opening_types": opening_types,
        "paragraph_opening_list": openings_list,
        "ai_phrase_violations": ai_phrase_violations,
        "short_ending_check": short_ending_result,
        "desc": desc,
    }


# ============================================================================
# 完整风格审计
# ============================================================================

def get_dynamic_style_rules(target_words: int = 15000,
                            tolerance: float = 0.10) -> Dict[str, Any]:
    """
    ★v1.2新增：根据用户目标字数动态生成缩放后的 STYLE_RULES 副本。

    以 STYLE_RULES 为基准，按 target_words/15000 等比缩放各章节字数，
    返回一个新的规则字典（不修改原始 STYLE_RULES）。

    参数:
        target_words: 用户指定的全文字数目标（默认 15000）
        tolerance: 字数容忍度（默认 0.10）

    返回:
        缩放后的风格规则字典
    """
    import copy
    rules = copy.deepcopy(STYLE_RULES)
    DEFAULT_TOTAL = 15000
    scale = target_words / DEFAULT_TOTAL

    # 缩放 global
    rules["global"]["total_words"] = target_words
    rules["global"]["tolerance"] = tolerance

    # 缩放各章节
    for section, section_rules in rules.items():
        if section in ("global", "title"):
            continue
        if isinstance(section_rules, dict) and "words" in section_rules:
            section_rules["words"] = max(100, int(section_rules["words"] * scale))
            if "min_words" in section_rules:
                section_rules["min_words"] = max(50, int(section_rules["min_words"] * scale))
            if "max_words" in section_rules:
                section_rules["max_words"] = max(
                    section_rules["words"],
                    int(section_rules["max_words"] * scale),
                )

    return rules


def run_full_style_audit(text: str,
                         target_words: int = 0,
                         tolerance: float = 0.10) -> Dict[str, Any]:
    """
    运行完整风格审计，返回综合报告。

    ★v1.2升级：支持动态字数目标。当 target_words > 0 时，使用缩放后的
    规则进行审计；否则使用 STYLE_RULES 默认值。

    包含以下检查项：
    1. 全文字数
    2. 破折号数量
    3. 分号数量
    4. 冒号密度
    5. 省略号
    6. 句长
    7. 段落长度
    8. 禁止模式
    9. 禁止短语
    10. ★语言自然度

    参数:
        text: 论文文本
        target_words: 用户指定的全文字数目标（0表示使用默认15000）
        tolerance: 字数容忍度

    返回:
        综合审计报告字典
    """
    # ★v1.2：动态选择规则
    if target_words > 0 and target_words != 15000:
        g_rules = get_dynamic_style_rules(target_words, tolerance)
    else:
        g_rules = STYLE_RULES

    g = g_rules["global"]

    # 执行各项检查
    word_count_result = check_word_count(
        text, g["total_words"], g["tolerance"]
    )
    dash_result = check_dash_count(text, g["max_dash_count"])
    semicolon_result = check_semicolon_count(text, g["max_semicolon_count"])
    colon_result = check_colon_density(text, g["max_colon_per_1000_words"])
    ellipsis_result = check_ellipsis_in_body(text)
    sentence_result = check_sentence_lengths(text, g["max_words_per_sentence"])
    paragraph_result = check_paragraph_lengths(
        text, g["max_words_per_paragraph"], g["min_words_per_paragraph"]
    )
    pattern_violations = check_forbidden_patterns(text, g["forbidden_patterns"])
    phrase_violations = check_forbidden_phrases(text, g["forbidden_phrases"])
    naturality_result = check_language_naturality(text)

    # ★v1.1新增：节奏、多样性、机械模式检测
    rhythm_result = calculate_sentence_rhythm(text)
    diversity_result = calculate_paragraph_diversity(text)
    mechanical_result = detect_mechanical_patterns(text)

    # ★v5.0新增：集成 v7.4 的 7 项检测函数
    hard_transitions_result = detect_hard_transitions(text)
    mechanical_connectors_result = detect_mechanical_connectors(text)
    concept_disconnect_result = detect_concept_disconnect(text)
    straight_quotes_result = detect_straight_quotes(text)
    intra_paragraph_result = detect_intra_paragraph_disconnect(text)
    paragraph_transition_result = detect_paragraph_transition_quality(text)
    classical_vocab_result = detect_classical_vocabulary_overuse(text)
    numeric_format_result = detect_numeric_format_violations(text)

    # ★v1.5/v1.6 集成（修复僵尸函数）：人类语言合规 + 脚注格式合规
    human_language_result = check_human_language_compliance(text)
    footnote_compliance_result = check_footnote_format_compliance(text)

    # 汇总违规
    violations: List[str] = []
    if word_count_result[1]:
        violations.append(word_count_result[2])
    if dash_result[1]:
        violations.append(dash_result[2])
    if semicolon_result[1]:
        violations.append(semicolon_result[2])
    if colon_result[1]:
        violations.append(colon_result[2])
    if ellipsis_result[1]:
        violations.append(ellipsis_result[2])
    if sentence_result[0] > 5:
        violations.append(f"长句({sentence_result[0]}处)超标")
    if paragraph_result["too_long"] > 3:
        violations.append(f"过长段落({paragraph_result['too_long']}段)超标")
    if paragraph_result["too_short"] > 5:
        violations.append(f"过短段落({paragraph_result['too_short']}段)超标")
    violations.extend(pattern_violations)
    violations.extend(phrase_violations)
    if not naturality_result["passed"]:
        violations.append(naturality_result["desc"])
        violations.extend(naturality_result["broken_expressions"])
        violations.extend(naturality_result["mechanical_transitions"])

    # ★v1.1新增：节奏、多样性、机械模式违规汇总
    if not rhythm_result["passed"]:
        violations.append(rhythm_result["desc"])
    if not diversity_result["passed"]:
        violations.append(diversity_result["desc"])
    if not mechanical_result["passed"]:
        violations.extend(mechanical_result["patterns_found"])

    # ★v5.0新增：7 项检测违规汇总
    if not hard_transitions_result.get("passed", True):
        violations.append(hard_transitions_result.get("desc", "硬切换检测未通过"))
    if not mechanical_connectors_result.get("passed", True):
        violations.append(mechanical_connectors_result.get("desc", "机械连接词检测未通过"))
    if not concept_disconnect_result.get("passed", True):
        violations.append(concept_disconnect_result.get("desc", "概念断裂检测未通过"))
    if not straight_quotes_result.get("passed", True):
        violations.append(straight_quotes_result.get("fix_suggestion", "直引号检测未通过"))
    if not intra_paragraph_result.get("passed", True):
        violations.append(intra_paragraph_result.get("desc", "段内首句-第二句断裂检测未通过"))
    if not paragraph_transition_result.get("passed", True):
        violations.extend(paragraph_transition_result.get("violations", ["段间过渡质量检测未通过"]))
    if not classical_vocab_result.get("passed", True):
        violations.append(classical_vocab_result.get("desc", "文言词汇过度使用检测未通过"))
    if not numeric_format_result.get("passed", True):
        violations.append(numeric_format_result.get("desc", "数字使用规范检测未通过"))

    # ★v1.5 集成：人类语言合规违规汇总（修复 R10 僵尸函数）
    if not human_language_result.get("passed", True):
        violations.append(human_language_result.get("desc", "人类语言合规检查未通过"))
        violations.extend(human_language_result.get("failed_checks", []))

    # ★v1.6 集成：脚注格式合规违规汇总（修复 R11-R15 僵尸函数）
    if not footnote_compliance_result.get("passed", True):
        violations.extend(footnote_compliance_result.get("violations", []))

    return {
        "word_count": {
            "actual": word_count_result[0],
            "expected": g["total_words"],
            "violated": word_count_result[1],
            "desc": word_count_result[2],
        },
        "dash": {
            "count": dash_result[0],
            "violated": dash_result[1],
            "desc": dash_result[2],
        },
        "semicolon": {
            "count": semicolon_result[0],
            "violated": semicolon_result[1],
            "desc": semicolon_result[2],
        },
        "colon": {
            "count": colon_result[0],
            "violated": colon_result[1],
            "desc": colon_result[2],
        },
        "ellipsis": {
            "count": ellipsis_result[0],
            "violated": ellipsis_result[1],
            "desc": ellipsis_result[2],
        },
        "sentence_lengths": {
            "long_count": sentence_result[0],
            "previews": sentence_result[1],
        },
        "paragraph_lengths": paragraph_result,
        "forbidden_patterns": pattern_violations,
        "forbidden_phrases": phrase_violations,
        "language_naturality": naturality_result,
        # ★v1.1新增：节奏、多样性、机械模式审计结果
        "rhythm": rhythm_result,
        "paragraph_diversity": diversity_result,
        "mechanical_patterns": mechanical_result,
        # ★v5.0新增：7 项检测结果
        "hard_transitions": hard_transitions_result,
        "mechanical_connectors": mechanical_connectors_result,
        "concept_disconnect": concept_disconnect_result,
        "straight_quotes": straight_quotes_result,
        "intra_paragraph_disconnect": intra_paragraph_result,
        "paragraph_transition_quality": paragraph_transition_result,
        "classical_vocabulary": classical_vocab_result,
        "numeric_format": numeric_format_result,
        # ★v1.5/v1.6 集成：人类语言合规 + 脚注格式合规
        "human_language_compliance": human_language_result,
        "footnote_compliance": footnote_compliance_result,
        "violations": violations,
        "passed": len(violations) == 0,
    }


# ============================================================================
# Pipeline 节点入口
# ============================================================================

def style_guard_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    风格守卫节点：在 Agent 输出后验证风格合规。

    作为 LangGraph 节点入口函数，运行程序化风格检查，
    将违规列表写入 state["style_violations"]，供下一轮 ConstraintInjector 注入。

    参数:
        state: 当前 Pipeline 状态

    返回:
        更新后的 Pipeline 状态
    """
    round_num = state.get("round_number", 1)
    error_log = state.get("error_log", [])

    # 获取当前论文内容（优先取最新 Agent 输出）
    paper = (
        state.get("full_text_polisher_output")
        or state.get("findings_reviser_output")
        or state.get("paper_content", "")
    )

    try:
        if not paper:
            error_log.append(
                f"[第{round_num}轮] StyleGuard: ⚠ 无论文内容，跳过风格验证"
            )
            state["error_log"] = error_log
            return state

        # ★v1.2升级：传入用户目标字数，动态缩放审计规则
        target_words = state.get("user_target_words", 0)
        tolerance = state.get("word_count_tolerance", 0.1)
        audit = run_full_style_audit(paper, target_words=target_words, tolerance=tolerance)

        # 写入违规列表（供下一轮 ConstraintInjector 注入）
        state["style_violations"] = audit.get("violations", [])
        state["active_constraints"] = {
            "audit_passed": audit["passed"],
            "violation_count": len(state["style_violations"]),
            "naturality_score": audit["language_naturality"]["naturality_score"],
            "audited_at_round": round_num,
        }

        status = "✅ 通过" if audit["passed"] else f"❌ 违规 {len(state['style_violations'])} 处"
        error_log.append(f"[第{round_num}轮] StyleGuard: {status}")
        error_log.append(
            f"  语言自然度: {audit['language_naturality']['naturality_score']:.2f}"
        )
        state["error_log"] = error_log

    except Exception as e:
        error_log.append(
            f"[第{round_num}轮] StyleGuard 异常: {type(e).__name__}: {e}"
        )
        state["error_log"] = error_log

    return state


# ============================================================================
# v1.6 新增：脚注检测函数
# ============================================================================

# 脚注引用正则模式（如 [1], [2], [3] 等）
FOOTNOTE_REFERENCE_PATTERN = r'\[(\d+)\]'

# 占位符模式（待补充、XXX、...等）
FOOTNOTE_PLACEHOLDER_PATTERNS: List[str] = [
    r'待补充',
    r'XXX',
    r'xxx',
    r'\.\.\.',
    r'……',
    r'TBD',
    r'tbd',
    r'待完善',
    r'待填',
    r'未填',
]

# 脚注必需字段（作者、标题、期刊/出版社、年份、页码）
FOOTNOTE_REQUIRED_FIELDS: List[Dict[str, Any]] = [
    {"name": "author", "patterns": [r'作者[:：]', r'著者[:：]', r'[A-Z][a-z]+,\s[A-Z][a-z]']},
    {"name": "title", "patterns": [r'《[^》]+》', r'"[^"]+"', r'title[:：]']},
    {"name": "journal/publisher", "patterns": [r'期刊[:：]', r'出版社[:：]', r'Press']},
    {"name": "year", "patterns": [r'\b(19|20)\d{2}\b', r'年份[:：]']},
    {"name": "pages", "patterns": [r'pp?\.\s*\d+', r'页\s*\d+']},
]


def detect_manual_footnotes(text: str) -> List[Dict]:
    """
    ★v1.6新增：检测论文文本中的手动上标伪脚注。

    检测形如 [1]、[2] 的上标伪脚注模式，返回位置和编号信息。

    参数:
        text: 论文文本

    返回:
        脚注引用列表，每项为字典：
        - position: int — 在文本中的起始位置
        - end: int — 在文本中的结束位置
        - number: int — 脚注编号
        - matched_text: str — 匹配到的文本
    """
    if not text:
        return []

    results: List[Dict[str, Any]] = []
    for match in re.finditer(FOOTNOTE_REFERENCE_PATTERN, text):
        results.append({
            "position": match.start(),
            "end": match.end(),
            "number": int(match.group(1)),
            "matched_text": match.group(0),
        })

    return results


def check_footnote_completeness(text: str) -> Dict[str, Any]:
    """
    ★v1.6新增：检查脚注引用与脚注内容的完整性。

    检测文本中的脚注引用（如 [1], [2]），并验证是否存在对应的脚注内容区段。
    脚注内容区段通常以"脚注""注释""Notes"等关键词标识。

    参数:
        text: 论文文本

    返回:
        脚注完整性检查结果字典，包含：
        - references: List[Dict] — 检测到的脚注引用列表
        - reference_numbers: List[int] — 脚注引用编号列表
        - footnote_section_found: bool — 是否找到脚注内容区段
        - footnote_content_numbers: List[int] — 脚注内容区段中的编号列表
        - missing_numbers: List[int] — 缺失对应内容的脚注编号
        - passed: bool — 是否通过（所有引用都有对应内容，或无引用）
        - desc: str — 描述信息
    """
    if not text:
        return {
            "references": [],
            "reference_numbers": [],
            "footnote_section_found": False,
            "footnote_content_numbers": [],
            "missing_numbers": [],
            "passed": True,
            "desc": "脚注完整性检查: 文本为空",
        }

    # 检测所有脚注引用
    references = detect_manual_footnotes(text)
    reference_numbers = [r["number"] for r in references]

    if not reference_numbers:
        return {
            "references": [],
            "reference_numbers": [],
            "footnote_section_found": False,
            "footnote_content_numbers": [],
            "missing_numbers": [],
            "passed": True,
            "desc": "脚注完整性检查: 未检测到脚注引用",
        }

    # 查找脚注内容区段（以"脚注""注释""Notes"等关键词标识）
    footnote_section_pattern = r'(?:脚注|注释|Notes|Footnotes|REFERENCES|参考文献)[\s\S]*$'
    section_match = re.search(footnote_section_pattern, text, re.IGNORECASE)
    footnote_section_found = section_match is not None

    footnote_content_numbers: List[int] = []
    if section_match:
        section_text = section_match.group(0)
        # 在脚注区段中查找编号
        for match in re.finditer(FOOTNOTE_REFERENCE_PATTERN, section_text):
            footnote_content_numbers.append(int(match.group(1)))

    # 计算缺失的脚注编号
    missing_numbers = [n for n in reference_numbers if n not in footnote_content_numbers]

    passed = len(missing_numbers) == 0 and footnote_section_found

    desc = (
        f"脚注完整性检查: 引用{len(reference_numbers)}处，"
        f"脚注区段{'存在' if footnote_section_found else '缺失'}，"
        f"缺失{len(missing_numbers)}处"
    )
    if missing_numbers:
        desc += f"（缺失编号: {missing_numbers[:10]}）"

    return {
        "references": references,
        "reference_numbers": reference_numbers,
        "footnote_section_found": footnote_section_found,
        "footnote_content_numbers": footnote_content_numbers,
        "missing_numbers": missing_numbers,
        "passed": passed,
        "desc": desc,
    }


def check_footnote_content_quality(footnote_text: str) -> Dict[str, Any]:
    """
    ★v1.6新增：验证脚注内容质量。

    检查脚注内容的以下质量维度：
    1. 必需字段检查（作者、标题、期刊/出版社、年份、页码）
    2. 占位符检测（"待补充"、"..."、"XXX"等）
    3. 乱码字符检测（U+FFFD）
    4. 最小长度检查（≥10字符）

    参数:
        footnote_text: 单条脚注的文本内容

    返回:
        脚注内容质量检查结果字典，包含：
        - length: int — 脚注文本长度
        - min_length_met: bool — 是否满足最小长度要求
        - required_fields: Dict — 各必需字段的存在情况
        - missing_fields: List[str] — 缺失的必需字段名
        - placeholders_found: List[str] — 检测到的占位符
        - has_garbled: bool — 是否包含乱码字符
        - passed: bool — 是否通过
        - desc: str — 描述信息
    """
    if not footnote_text:
        return {
            "length": 0,
            "min_length_met": False,
            "required_fields": {},
            "missing_fields": [f["name"] for f in FOOTNOTE_REQUIRED_FIELDS],
            "placeholders_found": [],
            "has_garbled": False,
            "passed": False,
            "desc": "脚注内容质量检查: 文本为空",
        }

    length = len(footnote_text)
    min_length_met = length >= 10

    # 1. 必需字段检查
    required_fields: Dict[str, bool] = {}
    missing_fields: List[str] = []
    for field_info in FOOTNOTE_REQUIRED_FIELDS:
        field_name = field_info["name"]
        found = False
        for pattern in field_info["patterns"]:
            try:
                if re.search(pattern, footnote_text, re.IGNORECASE):
                    found = True
                    break
            except re.error:
                continue
        required_fields[field_name] = found
        if not found:
            missing_fields.append(field_name)

    # 2. 占位符检测
    placeholders_found: List[str] = []
    for pattern in FOOTNOTE_PLACEHOLDER_PATTERNS:
        try:
            matches = re.findall(pattern, footnote_text)
            if matches:
                placeholders_found.extend(matches)
        except re.error:
            continue

    # 3. 乱码字符检测（U+FFFD）
    has_garbled = '\ufffd' in footnote_text

    # 综合判定
    passed = (
        min_length_met
        and not missing_fields
        and not placeholders_found
        and not has_garbled
    )

    issues = []
    if not min_length_met:
        issues.append(f"长度不足({length}<10)")
    if missing_fields:
        issues.append(f"缺失字段{missing_fields}")
    if placeholders_found:
        issues.append(f"占位符{placeholders_found[:3]}")
    if has_garbled:
        issues.append("包含乱码字符(U+FFFD)")

    desc = f"脚注内容质量检查: 长度{length}"
    if issues:
        desc += "（" + "; ".join(issues) + "）"

    return {
        "length": length,
        "min_length_met": min_length_met,
        "required_fields": required_fields,
        "missing_fields": missing_fields,
        "placeholders_found": placeholders_found,
        "has_garbled": has_garbled,
        "passed": passed,
        "desc": desc,
    }


def validate_footnote_reference_match(
    footnotes: List[str],
    references: List[str],
) -> Dict[str, Any]:
    """
    ★v1.6新增：验证脚注与参考文献列表的匹配性。

    通过"作者 + 年份 + 标题关键词"三要素匹配，判断脚注是否能在参考文献列表中
    找到对应条目。匹配阈值≥3分（每要素1分，部分匹配按权重计分）。

    参数:
        footnotes: 脚注文本列表
        references: 参考文献文本列表

    返回:
        脚注-参考文献匹配验证结果字典，包含：
        - total_footnotes: int — 脚注总数
        - total_references: int — 参考文献总数
        - matched_count: int — 成功匹配的脚注数
        - unmatched_footnotes: List[Dict] — 未匹配的脚注详情
        - match_details: List[Dict] — 匹配详情（含得分）
        - passed: bool — 是否通过（所有脚注均匹配）
        - desc: str — 描述信息
    """
    if not footnotes:
        return {
            "total_footnotes": 0,
            "total_references": len(references) if references else 0,
            "matched_count": 0,
            "unmatched_footnotes": [],
            "match_details": [],
            "passed": True,
            "desc": "脚注-参考文献匹配: 无脚注",
        }

    if not references:
        return {
            "total_footnotes": len(footnotes),
            "total_references": 0,
            "matched_count": 0,
            "unmatched_footnotes": [
                {"index": i, "footnote": fn, "best_score": 0}
                for i, fn in enumerate(footnotes)
            ],
            "match_details": [],
            "passed": False,
            "desc": f"脚注-参考文献匹配: {len(footnotes)}处脚注，参考文献列表为空",
        }

    # 提取三要素的辅助函数
    def extract_year(text: str) -> Optional[str]:
        match = re.search(r'\b(19|20)\d{2}\b', text)
        return match.group(0) if match else None

    def extract_authors(text: str) -> List[str]:
        # 匹配中文姓名（2-4字）或英文姓名（Last, First）
        authors = []
        # 中文姓名
        cn_matches = re.findall(r'[\u4e00-\u9fa5]{2,4}', text)
        authors.extend(cn_matches[:3])
        # 英文姓名
        en_matches = re.findall(r'[A-Z][a-z]+,\s[A-Z][a-z]+', text)
        authors.extend(en_matches[:3])
        return authors

    def extract_title_keywords(text: str) -> List[str]:
        # 提取书名号内的标题
        titles = re.findall(r'《([^》]+)》', text)
        # 提取引号内的标题
        titles.extend(re.findall(r'"([^"]+)"', text))
        # 提取所有中文词组（≥3字）
        keywords = re.findall(r'[\u4e00-\u9fa5]{3,}', text)
        return titles + keywords[:5]

    match_details: List[Dict[str, Any]] = []
    unmatched_footnotes: List[Dict[str, Any]] = []
    matched_count = 0

    for idx, fn in enumerate(footnotes):
        fn_year = extract_year(fn)
        fn_authors = extract_authors(fn)
        fn_keywords = extract_title_keywords(fn)

        best_score = 0
        best_ref_idx = -1
        best_ref = ""

        for ref_idx, ref in enumerate(references):
            score = 0
            ref_year = extract_year(ref)
            ref_authors = extract_authors(ref)
            ref_keywords = extract_title_keywords(ref)

            # 年份匹配（1分）
            if fn_year and ref_year and fn_year == ref_year:
                score += 1

            # 作者匹配（1分）
            if fn_authors and ref_authors:
                common_authors = set(fn_authors) & set(ref_authors)
                if common_authors:
                    score += 1

            # 标题关键词匹配（1分）
            if fn_keywords and ref_keywords:
                common_keywords = set(fn_keywords) & set(ref_keywords)
                if common_keywords:
                    score += 1

            if score > best_score:
                best_score = score
                best_ref_idx = ref_idx
                best_ref = ref

        is_matched = best_score >= 3
        if is_matched:
            matched_count += 1
        else:
            unmatched_footnotes.append({
                "index": idx,
                "footnote": fn[:80] + ("..." if len(fn) > 80 else ""),
                "best_score": best_score,
                "best_match_reference": best_ref[:80] + ("..." if len(best_ref) > 80 else ""),
            })

        match_details.append({
            "footnote_index": idx,
            "best_match_index": best_ref_idx,
            "best_score": best_score,
            "matched": is_matched,
        })

    passed = matched_count == len(footnotes)

    desc = (
        f"脚注-参考文献匹配: {matched_count}/{len(footnotes)}匹配，"
        f"阈值≥3分，未匹配{len(unmatched_footnotes)}处"
    )

    return {
        "total_footnotes": len(footnotes),
        "total_references": len(references),
        "matched_count": matched_count,
        "unmatched_footnotes": unmatched_footnotes,
        "match_details": match_details,
        "passed": passed,
        "desc": desc,
    }


def check_footnote_format_compliance(
    text: str,
    journal_style: str = "xwycbyj",
) -> Dict[str, Any]:
    """
    ★v1.6新增：脚注格式合规综合检查。

    调用上述脚注检测函数，返回综合合规报告。支持多种期刊风格：
    - xwycbyj: 《新闻与传播研究》风格（默认）
    - guoji: 《国际新闻界》风格
    - 其他: 通用风格

    参数:
        text: 论文文本
        journal_style: 期刊风格标识（默认 xwycbyj）

    返回:
        脚注格式合规综合报告字典，包含：
        - journal_style: str — 期刊风格
        - manual_footnotes: List[Dict] — 检测到的手动脚注引用
        - completeness_check: Dict — 脚注完整性检查结果
        - content_quality_checks: List[Dict] — 各脚注内容质量检查结果
        - reference_match_check: Dict — 脚注-参考文献匹配检查结果
        - passed: bool — 是否通过
        - violations: List[str] — 违规项列表
        - desc: str — 综合描述信息
    """
    if not text:
        return {
            "journal_style": journal_style,
            "manual_footnotes": [],
            "completeness_check": {},
            "content_quality_checks": [],
            "reference_match_check": {},
            "passed": True,
            "violations": [],
            "desc": "脚注格式合规检查: 文本为空",
        }

    violations: List[str] = []

    # 1. 检测手动脚注引用
    manual_footnotes = detect_manual_footnotes(text)
    if manual_footnotes:
        violations.append(
            f"检测到{len(manual_footnotes)}处手动上标伪脚注（[1]、[2]等），"
            f"建议改为期刊规范的脚注格式"
        )

    # 2. 检查脚注完整性
    completeness_check = check_footnote_completeness(text)
    if not completeness_check["passed"]:
        if not completeness_check["footnote_section_found"]:
            violations.append("未找到脚注内容区段（脚注/注释/Notes）")
        if completeness_check["missing_numbers"]:
            violations.append(
                f"脚注引用缺失对应内容: 编号 {completeness_check['missing_numbers'][:10]}"
            )

    # 3. 检查脚注内容质量（针对脚注区段中的每条脚注）
    content_quality_checks: List[Dict[str, Any]] = []
    footnote_texts: List[str] = []
    if completeness_check["footnote_section_found"]:
        # 提取脚注区段
        footnote_section_pattern = r'(?:脚注|注释|Notes|Footnotes|REFERENCES|参考文献)[\s\S]*$'
        section_match = re.search(footnote_section_pattern, text, re.IGNORECASE)
        if section_match:
            section_text = section_match.group(0)
            # 按编号切分脚注条目
            footnote_entries = re.split(r'\[\d+\]', section_text)
            footnote_entries = [e.strip() for e in footnote_entries if e.strip()]

            for entry_idx, entry in enumerate(footnote_entries):
                footnote_texts.append(entry)
                quality = check_footnote_content_quality(entry)
                quality["entry_index"] = entry_idx
                content_quality_checks.append(quality)
                if not quality["passed"]:
                    violations.append(f"脚注条目{entry_idx + 1}质量不合格: {quality['desc']}")

    # 4. 脚注-参考文献匹配验证
    reference_match_check: Dict[str, Any] = {}

    # 从参考文献区段提取参考文献列表
    reference_texts: List[str] = []
    ref_section_pattern = r'(?:参考文献|REFERENCES|References|Bibliography)[\s\S]*$'
    ref_match = re.search(ref_section_pattern, text, re.IGNORECASE)
    if ref_match:
        ref_section = ref_match.group(0)
        # 按行或编号切分参考文献
        ref_lines = [line.strip() for line in re.split(r'[\n\r]+', ref_section) if line.strip()]
        # 过滤掉区段标题行
        reference_texts = [
            line for line in ref_lines
            if not re.match(r'^(?:参考文献|REFERENCES|References|Bibliography)', line, re.IGNORECASE)
        ]

    if footnote_texts or reference_texts:
        reference_match_check = validate_footnote_reference_match(
            footnote_texts, reference_texts
        )
        if not reference_match_check["passed"]:
            violations.append(reference_match_check["desc"])

    # 综合判定
    passed = len(violations) == 0

    # 构建综合描述
    desc_parts = [
        f"期刊风格={journal_style}",
        f"手动脚注={len(manual_footnotes)}处",
        f"完整性={'通过' if completeness_check.get('passed', True) else '未通过'}",
        f"内容质量={len(content_quality_checks)}条检查",
        f"匹配={'通过' if reference_match_check.get('passed', True) else '未通过'}",
    ]
    desc = "脚注格式合规检查: " + ("✅通过" if passed else f"❌未通过（{len(violations)}项）")
    desc += "（" + "; ".join(desc_parts) + "）"

    return {
        "journal_style": journal_style,
        "manual_footnotes": manual_footnotes,
        "completeness_check": completeness_check,
        "content_quality_checks": content_quality_checks,
        "reference_match_check": reference_match_check,
        "passed": passed,
        "violations": violations,
        "desc": desc,
    }


# ============================================================================
# 使用示例
# ============================================================================

if __name__ == "__main__":
    sample_text = (
        "这是一段测试文本。第一，短视频改变了信息获取方式；"
        "第二，算法推荐重塑了内容分发逻辑；第三，青少年价值观受到冲击。"
        "值得注意的是，这一现象具有至关重要的影响。"
        "下文将从算法维度展开讨论——这里使用了破折号——还有一处破折号。"
        "综上所述，短视频算法推荐对青少年价值观塑造具有深刻的影响。"
    )

    print("=== 完整风格审计 ===")
    report = run_full_style_audit(sample_text)
    print(f"通过: {report['passed']}")
    print(f"违规数: {len(report['violations'])}")
    for v in report["violations"]:
        print(f"  - {v}")

    print("\n=== 语言自然度检测 ===")
    nat = report["language_naturality"]
    print(f"自然度评分: {nat['naturality_score']}")
    print(f"断裂式表达: {nat['broken_expression_count']} 处")
    print(f"机械过渡句: {nat['mechanical_transition_count']} 处")
    for hit in nat["broken_expressions"] + nat["mechanical_transitions"]:
        print(f"  - {hit}")


# ============================================================================
# 内参报告格式检测（★v1.7新增）
# ============================================================================

# 内参标题范式正则
NEICAN_TITLE_PATTERNS = {
    "对策建议型": r'关于["""].+?["""].*的若干建议',
    "现状挑战型": r'.+的现状[、，].*挑战.*对策',
    "折射启示型": r'.+折射的.+及其.*启示',
    "动向警示型": r'.+出现.+新动向.*值得重视',
}

# 内参学术残留检测关键词
NEICAN_ACADEMIC_RESIDUE_PATTERNS = [
    r'本研究\s*采用', r'本研究\s*使用', r'本研究\s*基于',
    r'Cohen[\'"]?s?\s*Kappa', r'p\s*[<>]\s*0\.\d+',
    r'F\s*\(.*?\)\s*=', r'χ²\s*=', r't\s*\(.*?\)\s*=',
    r'回归分析', r'方差分析', r'因子分析',
    r'本研究\s*表明', r'本研究\s*发现', r'本研究\s*认为',
    r'笔者认为', r'我认为', r'我们建议',
    r'文献综述', r'理论框架', r'研究假设',
    r'结构方程模型', r'主题模型', r'STM',
    r'编码者间信度', r'编码一致性',
]

# 内参对策抽象表述检测
NEICAN_ABSTRACT_COUNTERMEASURE_PATTERNS = [
    r'加强.{2,10}治理', r'完善.{2,10}法规', r'加大.{2,10}力度',
    r'强化.{2,10}责任', r'提升.{2,10}水平', r'推进.{2,10}建设',
    r'高度重视', r'加强领导', r'统筹推进',
]

# 内参禁止结尾词汇
NEICAN_FORBIDDEN_ENDINGS = ["综上所述", "总而言之", "总之", "结语", "结论"]


def detect_neican_title_pattern(text: str) -> dict:
    """检测内参标题范式（★v1.7新增）

    检测文本开头的标题是否符合内参标题范式。
    """
    import re
    lines = text.strip().split("\n")
    title = ""
    for line in lines[:5]:
        line = line.strip()
        if len(line) > 5 and not line.startswith("作者"):
            title = line
            break

    if not title:
        return {"valid": False, "pattern": None, "issue": "未找到标题"}

    for pattern_name, pattern_regex in NEICAN_TITLE_PATTERNS.items():
        if re.search(pattern_regex, title):
            return {"valid": True, "pattern": pattern_name, "title": title}

    # 检测是否为学术化标题
    if any(kw in title for kw in ["研究", "分析", "探讨", "考察"]):
        return {"valid": False, "pattern": "研究描述型(需转化)",
                "title": title, "issue": "标题偏学术化，需转化为内参标题范式"}

    return {"valid": False, "pattern": None, "title": title,
            "issue": "标题不符合任何内参标题范式"}


def detect_neican_opening_pattern(text: str) -> dict:
    """检测内参开篇范式（★v1.7新增）

    检测开篇是否包含公鸡打鸣段（时机→意义→做什么）。
    """
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    if len(paragraphs) < 2:
        return {"valid": False, "issue": "段落不足，无法判断开篇范式"}

    # 跳过标题和署名，找到第一个正文段落
    first_para = ""
    for p in paragraphs:
        if not p.startswith("作者") and len(p) > 20:
            first_para = p
            break

    if not first_para:
        return {"valid": False, "issue": "未找到正文开篇段"}

    # 检测公鸡打鸣段关键词
    timing_keywords = ["近期", "党的", "会议", "政策", "出台", "事件", "报告提出",
                       "二十届", "十五五", "当前", "近年来"]
    has_timing = any(kw in first_para for kw in timing_keywords)

    # 检测"本文"或"本报告"
    has_action = any(kw in first_para for kw in ["本文", "本报告", "建议", "提出", "分析", "从"])

    if has_timing and has_action:
        return {"valid": True, "pattern": "单段式", "issue": None}

    return {"valid": False, "pattern": None,
            "issue": "开篇缺少公鸡打鸣段（时机→意义→做什么）"}


def detect_neican_hierarchy(text: str) -> dict:
    """检测内参层级编号规范（★v1.7新增）"""
    import re
    lines = text.strip().split("\n")

    level1_pattern = re.compile(r'^[一二三四五六七八九十]+[、．.]')
    level2_pattern = re.compile(r'^（[一二三四五六七八九十]+）')
    level3_pattern = re.compile(r'^\d+[.．]')

    level1_count = sum(1 for l in lines if level1_pattern.match(l.strip()))
    level2_count = sum(1 for l in lines if level2_pattern.match(l.strip()))
    level3_count = sum(1 for l in lines if level3_pattern.match(l.strip()))

    issues = []
    if level1_count < 3:
        issues.append(f"一级标题（一、）数量不足：{level1_count}，建议≥3")
    if level1_count > 5:
        issues.append(f"一级标题（一、）数量过多：{level1_count}，建议≤5")

    return {
        "valid": len(issues) == 0,
        "level1_count": level1_count,
        "level2_count": level2_count,
        "level3_count": level3_count,
        "issues": issues,
    }


def detect_neican_countermeasure_caliber(text: str) -> dict:
    """检测内参对策刻度（★v1.7新增）"""
    import re
    issues = []

    for pattern in NEICAN_ABSTRACT_COUNTERMEASURE_PATTERNS:
        matches = re.findall(pattern, text)
        for match in matches:
            issues.append(f"抽象对策表述：'{match}'，需具体化")

    # 检测责任主体
    responsibility_keywords = ["建议由", "要求", "推动", "牵头", "负责", "主管部门", "网信"]
    has_responsibility = any(kw in text for kw in responsibility_keywords)

    if not has_responsibility:
        issues.append("对策建议缺少明确责任主体")

    return {
        "valid": len(issues) == 0,
        "abstract_count": len([i for i in issues if "抽象" in i]),
        "has_responsibility": has_responsibility,
        "issues": issues,
    }


def detect_neican_ending(text: str) -> dict:
    """检测内参结尾规范（★v1.7新增）"""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    if not paragraphs:
        return {"valid": False, "issue": "文本为空"}

    last_para = paragraphs[-1]

    for ending in NEICAN_FORBIDDEN_ENDINGS:
        if ending in last_para:
            return {"valid": False, "issue": f"结尾包含禁止词汇：'{ending}'，内参不写总结段"}

    return {"valid": True, "issue": None}


def detect_neican_academic_residue(text: str) -> dict:
    """检测内参中的学术残留（★v1.7新增）"""
    import re
    residues = []

    for pattern in NEICAN_ACADEMIC_RESIDUE_PATTERNS:
        matches = re.findall(pattern, text)
        for match in matches:
            residues.append(f"学术残留：'{match}'")

    return {
        "valid": len(residues) == 0,
        "residue_count": len(residues),
        "residues": residues,
    }


def check_neican_format_compliance(text: str, journal_style: str = None) -> dict:
    """综合内参格式合规检查（★v1.7新增）

    仅在用户明确请求内参审稿时调用。
    """
    results = {
        "title": detect_neican_title_pattern(text),
        "opening": detect_neican_opening_pattern(text),
        "hierarchy": detect_neican_hierarchy(text),
        "countermeasure": detect_neican_countermeasure_caliber(text),
        "ending": detect_neican_ending(text),
        "academic_residue": detect_neican_academic_residue(text),
    }

    all_valid = all(r.get("valid", False) for r in results.values())
    results["overall_valid"] = all_valid
    results["total_issues"] = sum(
        len(r.get("issues", [])) if isinstance(r.get("issues"), list)
        else (1 if r.get("issue") else 0)
        for r in results.values()
    )
    return results
