"""
循环式论文审稿优化 Pipeline — 配置文件 v1.0

定义 Pipeline 的所有可配置参数，包括期刊格式、研究类型、9 维度评分体系、
4 维质量量化标准、风格约束、Agent 映射等。

本文件是 cyclical-paper-review skill 的单一配置真实来源（Single Source of
Truth），与 style_guard.py 中的 STYLE_RULES 保持一致。

参考来源：
- cyclical-paper-generation/pipeline/config.py（精简优化）
- waishenyijian-skills 的 8 维度评审（升级为 9 维度）
- cyclical-paper-review/SKILL.md 的 v1.0 设计

Author: Cyclical Paper Review Pipeline
Version: 1.0.0
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# 期刊格式配置（4 种 CSSCI 期刊）
# ============================================================================

JOURNAL_CONFIGS: Dict[str, Dict[str, Any]] = {
    "xwycbyj": {
        "name": "新闻与传播研究",
        "name_en": "Journalism & Communication",
        "page_layout": {"lines_per_page": 34, "chars_per_line": 36},
        "title_hierarchy": ["一、", "（一）", "1．", "（1）"],
        "citation_style": "footnote",
        "footnote_format": "per_page",
        "footnote_marker": "[1][2][3]",
        "table_style": "three_line",
        "word_template": {
            "font_body": "宋体",
            "font_title_1": "黑体",
            "font_title_2": "黑体",
            "font_title_3": "黑体",
            "size_body": 10.5,
            "size_title_1": 16,
            "size_title_2": 14,
            "size_title_3": 12,
            "size_footnote": 9,
            "line_spacing": 1.5,
        },
    },
    "gjxwj": {
        "name": "国际新闻界",
        "name_en": "Chinese Journal of Journalism & Communication",
        "page_layout": {"lines_per_page": 34, "chars_per_line": 36},
        "title_hierarchy": ["一、", "（一）", "1.", "（1）"],
        "citation_style": "footnote",
        "footnote_format": "per_page",
        "footnote_marker": "[1][2][3]",
        "table_style": "three_line",
        "word_template": {
            "font_body": "宋体",
            "font_title_1": "黑体",
            "font_title_2": "黑体",
            "font_title_3": "楷体",
            "size_body": 10.5,
            "size_title_1": 16,
            "size_title_2": 14,
            "size_title_3": 12,
            "size_footnote": 9,
            "line_spacing": 1.5,
        },
    },
    "xwdx": {
        "name": "新闻大学",
        "name_en": "Journalism Bimonthly",
        "page_layout": {"lines_per_page": 34, "chars_per_line": 36},
        "title_hierarchy": ["一、", "（一）", "1．", "（1）"],
        "citation_style": "footnote",
        "footnote_format": "per_page",
        "footnote_marker": "[1][2][3]",
        "table_style": "three_line",
        "word_template": {
            "font_body": "宋体",
            "font_title_1": "黑体",
            "font_title_2": "黑体",
            "font_title_3": "黑体",
            "size_body": 10.5,
            "size_title_1": 16,
            "size_title_2": 14,
            "size_title_3": 12,
            "size_footnote": 9,
            "line_spacing": 1.5,
        },
    },
    "shxyj": {
        "name": "社会学研究",
        "name_en": "Sociological Studies",
        "page_layout": {"lines_per_page": 34, "chars_per_line": 36},
        "title_hierarchy": ["一、", "（一）", "1.", "（1）"],
        "citation_style": "footnote",
        "footnote_format": "per_page",
        "footnote_marker": "[1][2][3]",
        "table_style": "three_line",
        "word_template": {
            "font_body": "宋体",
            "font_title_1": "黑体",
            "font_title_2": "黑体",
            "font_title_3": "楷体",
            "size_body": 10.5,
            "size_title_1": 16,
            "size_title_2": 14,
            "size_title_3": 12,
            "size_footnote": 9,
            "line_spacing": 1.5,
        },
    },
}


# ============================================================================
# 研究类型配置（6 种研究类型）
# ============================================================================

RESEARCH_TYPE_CONFIGS: Dict[str, Dict[str, Any]] = {
    "qualitative": {
        "name": "定性研究",
        "name_en": "Qualitative Research",
        "key_methods": ["深度访谈", "焦点小组", "参与观察", "扎根理论", "主题分析", "叙事分析"],
        "codebook_required": True,
        "verification_points": [
            "编码一致性检查",
            "理论饱和验证",
            "受访者引语比例检查",
            "备忘录质量评估",
        ],
        "review_focus": [
            "编码数据充分利用",
            "理论命题对照验证",
            "分析深度（超越描述）",
            "反直觉发现挖掘",
        ],
        "dimension_weights": {
            "discussion": 1.2,   # 讨论与理论对话加权
            "logic_rigor": 1.1,  # 逻辑缜密度加权
            "innovation": 1.2,   # 创新性加权
        },
    },
    "quantitative": {
        "name": "定量研究",
        "name_en": "Quantitative Research",
        "key_methods": ["问卷调查", "实验设计", "内容分析", "二次数据分析", "计量模型"],
        "codebook_required": False,
        "verification_points": [
            "统计方法适当性检查",
            "样本代表性验证",
            "信效度检验复核",
            "效应量报告完整性",
        ],
        "review_focus": [
            "假设推导逻辑",
            "变量操作化合理性",
            "统计结果解释准确性",
            "稳健性检验完整性",
        ],
        "dimension_weights": {
            "research_design": 1.2,  # 研究设计加权
            "rigor_norm": 1.2,       # 严谨性加权
            "findings": 1.1,         # 发现加权
        },
    },
    "computational": {
        "name": "计算社会科学",
        "name_en": "Computational Social Science",
        "key_methods": ["自然语言处理", "社会网络分析", "机器学习", "仿真模拟", "大数据分析"],
        "codebook_required": False,
        "verification_points": [
            "算法可复现性",
            "数据预处理透明度",
            "模型选择合理性",
            "伦理与偏差声明",
        ],
        "review_focus": [
            "方法创新性说明",
            "计算范式与社科学理的桥接",
            "结果可解释性",
            "数据伦理与隐私",
        ],
        "dimension_weights": {
            "innovation": 1.3,            # 创新性加权
            "theory_literature": 1.1,     # 理论框架加权
            "rigor_norm": 1.1,            # 严谨性加权
        },
    },
    "mixed": {
        "name": "混合方法",
        "name_en": "Mixed Methods Research",
        "key_methods": ["顺序解释设计", "顺序探索设计", "聚合并行设计", "多层设计"],
        "codebook_required": True,
        "verification_points": [
            "定性与定量整合逻辑",
            "方法优先级说明",
            "结果三角验证",
            "整合点明确性",
        ],
        "review_focus": [
            "方法整合的学理性",
            "两类证据的对话",
            "整合结果的理论贡献",
            "方法局限的坦诚",
        ],
        "dimension_weights": {
            "research_design": 1.3,   # 研究设计加权（混合方法核心）
            "discussion": 1.1,        # 讨论加权
        },
    },
    "interview_report": {
        "name": "访谈报告",
        "name_en": "Interview Report",
        "key_methods": ["半结构化访谈", "深度访谈", "口述史", "生命史"],
        "codebook_required": True,
        "verification_points": [
            "受访者信息匿名化",
            "引语上下文完整性",
            "访谈饱和度说明",
            "反身性声明",
        ],
        "review_focus": [
            "引语与分析的比例",
            "受访者声音的呈现",
            "情境化描述质量",
            "理论提升程度",
        ],
        "dimension_weights": {
            "findings": 1.2,          # 发现加权（引语处理核心）
            "writing_style": 1.1,     # 文笔加权
        },
    },
    "theoretical": {
        "name": "理论论文",
        "name_en": "Theoretical Paper",
        "key_methods": ["概念分析", "理论建构", "元分析", "思想史梳理"],
        "codebook_required": False,
        "verification_points": [
            "概念谱系清晰度",
            "论证逻辑自洽性",
            "理论对话深度",
            "新概念界定严谨性",
        ],
        "review_focus": [
            "理论建构的原创性",
            "概念界定的精确性",
            "与既有理论的对话",
            "理论适用边界",
        ],
        "dimension_weights": {
            "theory_literature": 1.3,   # 理论框架加权（理论论文核心）
            "discussion": 1.2,          # 讨论加权
            "innovation": 1.2,          # 创新性加权
        },
    },
}


# ============================================================================
# 研究类型 → Agent 映射（全部 7 个 Agent）
# ============================================================================

# 7 个核心 Agent 标识符
AGENT_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "external_reviewer": {
        "name": "外审专家", "order": 0, "enabled": True,
        "file": "agents/external_reviewer.md", "category": "review",
    },
    "abstract_reviser": {
        "name": "摘要修改者", "order": 1, "enabled": True,
        "file": "agents/abstract_reviser.md", "category": "section",
    },
    "introduction_reviser": {
        "name": "引言修改者", "order": 2, "enabled": True,
        "file": "agents/introduction_reviser.md", "category": "section",
    },
    "literature_review_reviser": {
        "name": "研究综述修改者", "order": 3, "enabled": True,
        "file": "agents/literature_review_reviser.md", "category": "section",
    },
    "findings_reviser": {
        "name": "研究发现修改者", "order": 4, "enabled": True,
        "file": "agents/findings_reviser.md", "category": "section",
    },
    "literature_auditor": {
        "name": "文献审计者", "order": 5, "enabled": True,
        "file": "agents/literature_auditor.md", "category": "audit",
    },
    "full_text_polisher": {
        "name": "全文润色者", "order": 6, "enabled": True,
        "file": "agents/full_text_polisher.md", "category": "polish",
    },
}

# 程序化节点（非 Agent）
PROGRAM_NODES = ["constraint_injector", "style_guard", "instruction_guard",
                 "opinion_router", "format_output"]

# 研究类型 → 必执行 Agent 映射（全部 7 个 Agent，按研究类型调整侧重）
RESEARCH_TYPE_AGENT_MAP: Dict[str, Dict[str, Any]] = {
    "qualitative": {
        "required": ["external_reviewer", "abstract_reviser", "introduction_reviser",
                     "literature_review_reviser", "findings_reviser",
                     "literature_auditor", "full_text_polisher"],
        "emphasis": "findings_reviser",  # 侧重 Agent
        "extra": {"findings_focus": "编码数据利用与理论命题对照"},
    },
    "quantitative": {
        "required": ["external_reviewer", "abstract_reviser", "introduction_reviser",
                     "literature_review_reviser", "findings_reviser",
                     "literature_auditor", "full_text_polisher"],
        "emphasis": "findings_reviser",
        "extra": {"findings_focus": "统计指标完整性与效应量报告"},
    },
    "computational": {
        "required": ["external_reviewer", "abstract_reviser", "introduction_reviser",
                     "literature_review_reviser", "findings_reviser",
                     "literature_auditor", "full_text_polisher"],
        "emphasis": "literature_auditor",
        "extra": {"audit_focus": "算法可复现性与数据伦理"},
    },
    "mixed": {
        "required": ["external_reviewer", "abstract_reviser", "introduction_reviser",
                     "literature_review_reviser", "findings_reviser",
                     "literature_auditor", "full_text_polisher"],
        "emphasis": "findings_reviser",
        "extra": {"findings_focus": "定性定量整合逻辑与三角验证"},
    },
    "interview_report": {
        "required": ["external_reviewer", "abstract_reviser", "introduction_reviser",
                     "literature_review_reviser", "findings_reviser",
                     "literature_auditor", "full_text_polisher"],
        "emphasis": "findings_reviser",
        "extra": {"findings_focus": "引语处理与受访者声音呈现"},
    },
    "theoretical": {
        "required": ["external_reviewer", "abstract_reviser", "introduction_reviser",
                     "literature_review_reviser", "findings_reviser",
                     "literature_auditor", "full_text_polisher"],
        "emphasis": "literature_review_reviser",
        "extra": {"review_focus": "理论建构原创性与概念界定精确性"},
    },
}


# ============================================================================
# 中央风格约束（与 style_guard.py 一致，单一真实来源）
# ============================================================================

STYLE_RULES: Dict[str, Any] = {
    "global": {
        "total_words": 15000,
        "tolerance": 0.10,
        "max_dash_count": 15,
        "max_colon_per_1000_words": 2,
        "max_quote_pairs_non_interview": 0,
        "max_semicolon_count": 10,
        "max_ellipsis_in_body": 0,
        "forbidden_patterns": [
            "第一，.*第二，.*第三",
            "首先，.*其次，.*再次",
            "一方面，.*另一方面，",
        ],
        "forbidden_phrases": [
            "深刻", "极具", "丰富而多元", "复杂而深刻",
            "不可或缺", "至关重要", "众所周知", "不言而喻",
            "毋庸置疑", "在新时代背景下",
            "具有重要的理论意义和实践意义",
        ],
        "max_words_per_sentence": 60,
        "max_words_per_paragraph": 400,
        "min_words_per_paragraph": 100,
        "citation_format": "(author, year)",
        "forbidden_citation_patterns": ["xx说", "xx指出", "xx认为"],
        "max_quote_ratio": 0.30,
    },
    "abstract": {
        "words": 350,
        "structure": ["historical_background", "method_brief", "findings_flow", "contribution"],
        "forbidden": ["分号", "引号", "破折号", "第一", "第二", "第三"],
        "first_sentence_style": "宏观社会变迁切入，不使用'随着……的发展'等空洞套话",
    },
    "introduction": {
        "words": 600,
        "structure": ["historical_background", "data_anchor", "method_brief",
                      "research_question", "purpose"],
        "forbidden": ["括号（非引用）", "破折号", "第一第二第三"],
    },
    "literature_review": {
        "words": 2000,
        "sections": 3,
        "section_labels": ["文献地图", "理论对话", "研究缺口"],
        "citation_format": "(author, year)",
        "forbidden": ["xx说", "xx指出", "xx认为", "书籍专著为主"],
    },
    "method": {
        "words": 800,
        "required_sections": ["research_design", "sample", "data_collection", "analysis_strategy"],
        "required_fields": ["抽样策略", "地区分布", "年龄范围与均值", "样本选择理由"],
    },
    "findings": {
        "words": 3750,
        "min_words": 3500,
        "max_words": 4000,
        "structure": "two_sections_three_subsections_each",
        "max_interview_quote_ratio": 0.30,
        "min_analysis_ratio": 0.70,
        "forbidden": ["C-XX编码编号出现在正文中"],
        "subtitle_style": "小节标题即论点，3-8字，信息密度高",
    },
    "conclusion": {
        "words": 1750,
        "min_words": 1500,
        "max_words": 2000,
        "structure": ["reflection", "conceptual_elevation",
                      "constructive_suggestions", "humanistic_critique"],
    },
    "title": {
        "main_title_max_chars": 25,
        "main_title_min_chars": 5,
        "require_rhetorical_question": True,
        "subtitle_connector": "冒号",
        "forbidden": ["引号", "破折号", "分号", "虚词开头"],
        "section_title_chars": {"level_2": "10-25字", "level_3": "3-8字"},
        "keywords_count": {"min": 3, "max": 5},
    },
}


# ============================================================================
# v1.2新增：动态字数预算计算函数
# ============================================================================

def compute_section_budgets(target_words: int, tolerance: float = 0.10) -> Dict[str, Dict[str, int]]:
    """根据用户指定的全文字数目标，按比例计算各章节字数预算（v1.2新增）

    以 STYLE_RULES 中各章节的默认字数比例为基准，按用户目标等比缩放。
    """
    DEFAULT_TOTAL = 15000
    section_defaults = {}
    for section, rules in STYLE_RULES.items():
        if section in ("global", "title"):
            continue
        if isinstance(rules, dict) and "words" in rules:
            section_defaults[section] = {
                "default_words": rules["words"],
                "default_min": rules.get("min_words", int(rules["words"] * 0.9)),
                "default_max": rules.get("max_words", int(rules["words"] * 1.1)),
            }

    scale = target_words / DEFAULT_TOTAL
    budgets: Dict[str, Dict[str, int]] = {}

    budgets["global"] = {
        "target": target_words,
        "hard_limit": int(target_words * (1 + tolerance)),
        "soft_limit": int(target_words * (1 - tolerance)),
    }

    for section, defaults in section_defaults.items():
        scaled_target = max(100, int(defaults["default_words"] * scale))
        scaled_min = max(50, int(defaults["default_min"] * scale))
        scaled_max = max(scaled_target, int(defaults["default_max"] * scale))
        budgets[section] = {
            "target": scaled_target,
            "min": scaled_min,
            "max": scaled_max,
        }

    return budgets


def build_word_budget_constraint(target_words: int, current_words: int,
                                 section_words: Dict[str, int] = None,
                                 tolerance: float = 0.10) -> str:
    """构建字数预算硬约束文本，注入到每个 Agent 的 instruction 中（v1.2新增）

    核心策略：
    - 事前约束：告诉 Agent 当前剩余预算，禁止超限
    - 动态调整：根据当前实际字数与目标的差距，给出不同强度的约束
    - 硬约束语言：使用"禁止""不得超过"等绝对性表述
    """
    budgets = compute_section_budgets(target_words, tolerance)
    hard_limit = budgets["global"]["hard_limit"]
    delta = current_words - target_words
    over_limit = current_words > hard_limit
    near_limit = current_words > target_words

    parts = [
        "【字数硬约束 — 不可违反】",
        f"用户指定全文字数：{target_words}字",
        f"硬上限（含容差）：{hard_limit}字",
        f"当前全文字数：{current_words}字",
        f"与目标差距：{'超' if delta > 0 else '差'}{abs(delta)}字",
    ]

    parts.append("\n各章节字数预算：")
    for section, budget in budgets.items():
        if section == "global":
            continue
        section_name_map = {
            "abstract": "摘要", "introduction": "引言",
            "literature_review": "文献回顾", "method": "研究方法",
            "findings": "研究发现", "conclusion": "结语",
        }
        name = section_name_map.get(section, section)
        actual = section_words.get(section, 0) if section_words else 0
        status = ""
        if actual > 0:
            if actual > budget["max"]:
                status = f" ❌ 超标({actual}字)"
            elif actual > budget["target"]:
                status = f" ⚠ 接近上限({actual}字)"
            else:
                status = f" ✅ ({actual}字)"
        parts.append(f"  {name}: 目标{budget['target']}字 ({budget['min']}-{budget['max']}){status}")

    if over_limit:
        parts.append("\n⚠⚠⚠ 严重超标！当前字数已超过硬上限！")
        parts.append("【强制指令】你只能删除内容，禁止新增任何文字。")
        parts.append("每处修改必须使总字数减少，不得增加。")
        parts.append(f"必须至少削减 {delta - int(target_words * tolerance)} 字才能回到安全范围。")
    elif near_limit:
        parts.append("\n⚠ 字数已超过目标值，接近硬上限。")
        parts.append("【约束指令】修改时优先精简，新增内容必须同时删除等量或更多文字。")
        parts.append("禁止净增字数。")
    else:
        remaining = target_words - current_words
        parts.append(f"\n字数在安全范围内，剩余预算 {remaining} 字。")
        parts.append("修改时注意控制篇幅，新增内容需在预算内。")

    return "\n".join(parts)


# ============================================================================
# 评分配置（9 维度 100 分制，阈值 95）
# ============================================================================

SCORING_CONFIG: Dict[str, Any] = {
    "dimensions": {
        "topic_question": {
            "name": "选题与问题意识", "max_score": 12,
            "freeze_condition": "连续2轮满分",
            "checkpoints": [
                "选题是否具有前沿性与理论张力？",
                "研究问题是否清晰、可操作？",
                "问题边界是否界定清楚？",
                "是否体现学术品位？",
            ],
        },
        "theory_literature": {
            "name": "理论框架与文献", "max_score": 15,
            "freeze_condition": "连续2轮≥14分",
            "checkpoints": [
                "理论选择是否合理？",
                "核心概念是否清晰界定？",
                "文献覆盖面与批判性如何？",
                "是否与5-8篇核心文献实质性对话？",
            ],
        },
        "research_design": {
            "name": "研究设计与方法", "max_score": 15,
            "freeze_condition": "连续2轮≥14分",
            "checkpoints": [
                "设计逻辑是否自洽？",
                "数据代表性是否充分？",
                "信效度说明是否完整？",
                "方法选择是否恰当？",
            ],
        },
        "findings": {
            "name": "研究发现与结果", "max_score": 12,
            "freeze_condition": "连续2轮满分",
            "checkpoints": [
                "结果呈现是否完整？",
                "统计指标/编码数据是否充分？",
                "效应量/引语比例是否合规？",
                "理论与预期对应关系是否清晰？",
            ],
        },
        "discussion": {
            "name": "讨论与理论对话", "max_score": 12,
            "freeze_condition": "连续2轮≥11分",
            "checkpoints": [
                "文献对话深度如何？",
                "意外发现是否充分解释？",
                "理论贡献是否凝练？",
                "是否超越'是什么'回答'为什么'？",
            ],
        },
        "writing_style": {
            "name": "文笔与文风", "max_score": 12,
            "freeze_condition": "连续2轮满分",
            "checkpoints": [
                "语言自然度如何（无断裂式表达）？",
                "标点是否规范（破折号/冒号/引号）？",
                "是否存在翻译腔？",
                "行文是否有呼吸感？",
            ],
        },
        "logic_rigor": {
            "name": "逻辑缜密度", "max_score": 10,
            "freeze_condition": "连续2轮≥9分",
            "checkpoints": [
                "句子过渡是否平滑（无生硬切换）？",
                "段落逻辑呼吸感如何？",
                "论证是否层层递进？",
                "是否存在并列描述替代层次嵌套？",
            ],
        },
        "rigor_norm": {
            "name": "严谨性与规范性", "max_score": 7,
            "freeze_condition": "连续2轮满分",
            "checkpoints": [
                "文献引用是否真实准确？",
                "格式是否标准统一？",
                "学术伦理是否声明？",
                "脚注体例是否正确？",
            ],
        },
        "innovation": {
            "name": "创新性与启发价值", "max_score": 5,
            "freeze_condition": "不冻结（创新性可随修订提升）",
            "checkpoints": [
                "是否提出新概念或分析框架？",
                "是否对既有理论有实质性推进？",
                "实践启示是否具体可操作？",
            ],
        },
    },
    "total_max_score": 100,
    "pass_threshold": 95,                       # 通过阈值 95 分
    "max_rounds": 7,                            # 最大循环轮次
    "min_rounds": 3,                            # 最小循环轮次
    "stagnation_threshold": 3,                  # 连续 3 轮提升<3分触发人工介入
    "stagnation_score_delta": 3,                # 停滞判定：单轮提升 < 3 分
    "freeze_consecutive_full_score_rounds": 2,  # 连续 2 轮满分冻结
    "freeze_consecutive_no_improvement_rounds": 3,  # 连续 3 轮无提升冻结
    "dimension_regression_threshold": -1,       # 维度倒退检测阈值（负值即倒退）
}


# ============================================================================
# 4 维质量量化配置
# ============================================================================

QUALITY_METRICS_CONFIG: Dict[str, Any] = {
    "language_naturality": {
        "name": "语言自然度",
        "description": "检测断裂式表达、机械过渡句、公式化辞藻",
        "pass_criteria": {
            "broken_expressions": 0,      # 断裂式表达数（必须为 0）
            "mechanical_transitions": 0,  # 机械过渡句数（必须为 0）
            "formulaic_phrases": 0,       # 公式化辞藻数（必须为 0）
        },
        "detection_method": "style_guard 程序化检测 + 外审专家评估",
    },
    "logic_rigor": {
        "name": "逻辑缜密度",
        "description": "检测句子生硬切换、段落过渡呼吸感",
        "pass_criteria": {
            "transition_smoothness": 0.85,  # 过渡平滑度 ≥ 0.85
            "logic_score": 9,               # 外审逻辑维度 ≥ 9/10
            "hard_switches": 2,             # 生硬切换数 ≤ 2
        },
        "detection_method": "quality_metrics 过渡平滑度算法 + 外审专家评估",
    },
    "review_score": {
        "name": "外审评分",
        "description": "9 维度综合评分",
        "pass_criteria": {
            "min_score": 95,  # ≥ 95/100
        },
        "detection_method": "external_reviewer 9 维度量化评分",
    },
    "instruction_consistency": {
        "name": "指令一致性",
        "description": "幻觉检测、初始指令偏离度",
        "pass_criteria": {
            "hallucinations": 0,       # 幻觉数（必须为 0）
            "deviation_score": 0.05,   # 指令偏离度 < 5%
        },
        "detection_method": "instruction_guard 指令快照对比",
    },
}


# ============================================================================
# Pipeline 主配置类
# ============================================================================

@dataclass
class PipelineConfig:
    """
    循环式论文审稿优化 Pipeline 主配置（v1.0）。

    封装期刊格式、研究类型、循环控制、评分阈值等所有可调参数，
    提供统一的配置访问接口。

    Attributes:
        research_type: 研究类型（qualitative/quantitative/computational/
                       mixed/interview_report/theoretical）
        journal_style: 目标期刊（xwycbyj/gjxwj/xwdx/shxyj）
        max_rounds: 最大循环轮次（默认 7）
        pass_threshold: 通过分数阈值（默认 95）
        min_rounds: 最小循环轮次（默认 3）
        stagnation_threshold: 连续 N 轮停滞触发人工介入（默认 3）
        stagnation_score_delta: 停滞判定单轮提升阈值（默认 3）
        incremental_mode: 是否启用增量修改（冻结已通过章节）
        auto_route_opinions: 是否自动分发审稿意见
        style_enforcement: 是否启用风格守卫强制执行
        instruction_guard_enabled: 是否启用指令守卫（防遗忘）
        quality_metrics_enabled: 是否启用 4 维质量量化检测
        output_format: 输出格式（word/markdown）
        save_all_versions: 是否保存所有版本
    """

    # ===== 研究与期刊 =====
    research_type: str = "qualitative"
    journal_style: str = "xwycbyj"

    # ===== 字数控制（v1.2新增：用户自定义字数目标） =====
    user_target_words: int = 15000          # 用户指定的全文字数目标
    word_count_tolerance: float = 0.1       # 字数容忍度（±10%）
    word_count_enforcement: str = "strict"  # 执行模式: "strict"(硬截断) / "compress"(仅压缩) / "warn"(仅警告)

    # ===== GAN对抗评分（v1.3新增：消除AI自评幻觉） =====
    gan_enabled: bool = True                # 是否启用GAN对抗评分（D Agent）
    trust_weight_alpha: float = 0.4         # G评分的信任权重（默认0.4，偏向D挑刺方）
    adversarial_signal_threshold: float = 10.0  # 对抗信号强度阈值

    # ===== 循环控制 =====
    max_rounds: int = 7
    pass_threshold: int = 95
    min_rounds: int = 3
    stagnation_threshold: int = 3
    stagnation_score_delta: int = 3

    # ===== 执行模式 =====
    incremental_mode: bool = True
    auto_route_opinions: bool = True
    style_enforcement: bool = True
    instruction_guard_enabled: bool = True
    quality_metrics_enabled: bool = True

    # ===== 输出配置 =====
    output_format: str = "word"
    save_all_versions: bool = True
    keep_last_n_versions: int = 3
    output_dir: str = ""

    # ===== 文献配置 =====
    min_chinese_citations: int = 8
    max_citation_age: int = 10

    def get_journal_config(self) -> Dict[str, Any]:
        """
        获取当前目标期刊的格式配置。

        Returns:
            期刊配置字典；若 journal_style 无效则回退至 xwycbyj。
        """
        config = JOURNAL_CONFIGS.get(self.journal_style)
        if config is None:
            logger.warning(
                "未知期刊格式 '%s'，回退至 'xwycbyj'", self.journal_style
            )
            config = JOURNAL_CONFIGS["xwycbyj"]
        return config

    def get_effective_hard_limit(self) -> int:
        """获取有效的字数硬上限（v1.2新增）"""
        return int(self.user_target_words * (1 + self.word_count_tolerance))

    def get_section_budgets(self) -> Dict[str, Any]:
        """获取按用户目标字数等比缩放的各章节预算（v1.2新增）"""
        return compute_section_budgets(self.user_target_words, self.word_count_tolerance)

    def get_research_type_config(self) -> Dict[str, Any]:
        """
        获取当前研究类型的配置。

        Returns:
            研究类型配置字典；若 research_type 无效则回退至 qualitative。
        """
        config = RESEARCH_TYPE_CONFIGS.get(self.research_type)
        if config is None:
            logger.warning(
                "未知研究类型 '%s'，回退至 'qualitative'", self.research_type
            )
            config = RESEARCH_TYPE_CONFIGS["qualitative"]
        return config

    def get_research_type_agent_map(self) -> Dict[str, Any]:
        """
        获取当前研究类型对应的 Agent 映射。

        Returns:
            Agent 映射字典，包含 required（必执行 Agent 列表）、
            emphasis（侧重 Agent）和 extra（额外配置）。
        """
        mapping = RESEARCH_TYPE_AGENT_MAP.get(self.research_type)
        if mapping is None:
            mapping = RESEARCH_TYPE_AGENT_MAP["qualitative"]
        return mapping

    def get_scoring_config(self) -> Dict[str, Any]:
        """
        获取 9 维度评分配置。

        Returns:
            评分配置字典，包含 dimensions、total_max_score、pass_threshold 等。
        """
        return SCORING_CONFIG

    def get_quality_metrics_config(self) -> Dict[str, Any]:
        """获取 4 维质量量化配置。"""
        return QUALITY_METRICS_CONFIG

    def get_style_rules(self) -> Dict[str, Any]:
        """获取中央风格约束（与 style_guard.py 一致）。"""
        return STYLE_RULES

    def get_dimension_weights(self) -> Dict[str, float]:
        """
        获取当前研究类型对应的评分维度权重。

        Returns:
            维度权重字典 {dimension_key: weight}。
        """
        rt_config = self.get_research_type_config()
        return rt_config.get("dimension_weights", {})

    def validate(self) -> List[str]:
        """
        验证配置有效性。

        Returns:
            错误信息列表；空列表表示配置有效。
        """
        errors: List[str] = []

        if self.research_type not in RESEARCH_TYPE_CONFIGS:
            errors.append(
                f"不支持的研究类型: {self.research_type}，"
                f"支持: {list(RESEARCH_TYPE_CONFIGS.keys())}"
            )

        if self.journal_style not in JOURNAL_CONFIGS:
            errors.append(
                f"不支持的期刊格式: {self.journal_style}，"
                f"支持: {list(JOURNAL_CONFIGS.keys())}"
            )

        if not (1 <= self.max_rounds <= 10):
            errors.append(f"max_rounds 应在 1-10 之间，当前值: {self.max_rounds}")

        if not (60 <= self.pass_threshold <= 100):
            errors.append(
                f"pass_threshold 应在 60-100 之间，当前值: {self.pass_threshold}"
            )

        if self.min_rounds > self.max_rounds:
            errors.append(
                f"min_rounds({self.min_rounds}) 不能大于 "
                f"max_rounds({self.max_rounds})"
            )

        if self.output_format not in ("word", "markdown"):
            errors.append(
                f"不支持的输出格式: {self.output_format}，支持: word/markdown"
            )

        if self.stagnation_threshold < 2:
            errors.append(
                f"stagnation_threshold 应 ≥ 2，当前值: {self.stagnation_threshold}"
            )

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典表示。"""
        return {
            "research_type": self.research_type,
            "journal_style": self.journal_style,
            "max_rounds": self.max_rounds,
            "pass_threshold": self.pass_threshold,
            "min_rounds": self.min_rounds,
            "stagnation_threshold": self.stagnation_threshold,
            "stagnation_score_delta": self.stagnation_score_delta,
            "incremental_mode": self.incremental_mode,
            "auto_route_opinions": self.auto_route_opinions,
            "style_enforcement": self.style_enforcement,
            "instruction_guard_enabled": self.instruction_guard_enabled,
            "quality_metrics_enabled": self.quality_metrics_enabled,
            "output_format": self.output_format,
            "save_all_versions": self.save_all_versions,
            "min_chinese_citations": self.min_chinese_citations,
        }


# ============================================================================
# 模块级常量快捷访问
# ============================================================================

DEFAULT_CONFIG = PipelineConfig()


def get_default_config() -> PipelineConfig:
    """获取默认 Pipeline 配置实例。"""
    return PipelineConfig()


def list_supported_journals() -> List[str]:
    """列出所有支持的期刊格式标识符。"""
    return list(JOURNAL_CONFIGS.keys())


def list_supported_research_types() -> List[str]:
    """列出所有支持的研究类型标识符。"""
    return list(RESEARCH_TYPE_CONFIGS.keys())


if __name__ == "__main__":
    # 配置自检
    cfg = PipelineConfig()
    validation_errors = cfg.validate()
    if validation_errors:
        print("配置验证失败:")
        for err in validation_errors:
            print(f"  - {err}")
    else:
        print("✅ 配置验证通过")
        print(f"  目标期刊: {cfg.get_journal_config()['name']}")
        print(f"  研究类型: {cfg.get_research_type_config()['name']}")
        print(f"  通过阈值: {cfg.pass_threshold} 分")
        print(f"  最大轮次: {cfg.max_rounds} 轮")
        print(f"  评分维度: {len(SCORING_CONFIG['dimensions'])} 维")
        print(f"  质量量化: {len(QUALITY_METRICS_CONFIG)} 维")
        print(f"  支持 Agent: {len(AGENT_DEFINITIONS)} 个")
