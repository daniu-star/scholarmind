"""
循环式论文生成Pipeline — 配置文件 v6.0（12 Agent 增强版）

定义Pipeline的所有可配置参数，包括循环控制、评分维度权重、
期刊格式、Agent行为等。

v6.0变更：
- 从 5 Agent 扩展至 12 Agent（新增 Methodologist, LiteratureCurator,
  WordCountController, Narrator, Orchestrator, WordFormatValidator）
- 新增 RESEARCH_TYPE_AGENT_MAP 研究类型→Agent 映射
- 新增 WORD_VALIDATION_CONFIG Word 验证配置
- 新增 AGENT_EXECUTION_ORDER v6.0 执行流定义
- 更新 OPINION_ROUTING_RULES 为六路路由
- 更新版本号至 6.0.0

Author: Cyclical Paper Generation Pipeline
Version: 6.0.0
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field


# ============================================================================
# 期刊格式配置
# ============================================================================

JOURNAL_CONFIGS = {
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
# 内参报告配置（★v7.4新增）
# ============================================================================

NEICAN_CONFIG = {
    "enabled": False,                          # 默认关闭，仅用户明确请求时开启
    "trigger_keywords": [                      # 触发关键词
        "内参", "内参报告", "政策建议", "决策参考",
        "将论文改写为内参", "neican", "policy brief",
    ],
    "word_count": {
        "short": (3000, 5000),                 # 短报告
        "standard": (5000, 8000),              # 标准报告
        "long": (8000, 12000),                # 长报告
        "comprehensive": (12000, 18000),       # 综合规划报告
    },
    "title_patterns": [
        "对策建议型",    # 关于"XX"的若干建议
        "现状挑战型",    # XX的现状、挑战和对策
        "折射启示型",    # XX折射的XX及其治理启示
        "动向警示型",    # XX出现XX新动向值得重视
    ],
    "section_count": {"min": 3, "max": 5},     # 板块数量
    "hierarchy": ["一、", "（一）", "1.", "（1）"],  # 层级编号
    "signature_format": "作者信息：\nXXX XX单位XX职务",
    "no_summary_paragraph": True,              # 不写总结段
    "no_academic_residue": True,                # 不残留学术元素
}


# ============================================================================
# 评分维度权重配置
# ============================================================================

SCORING_DIMENSIONS = {
    "title_impact": {
        "name": "标题冲击力",
        "max_score": 10,
        "weight": 1.0,
        "freeze_condition": "连续2轮满分",
        "related_sections": ["title", "section_titles"],
        "responsible_agent": "polisher",
        "checkpoints": [
            "主标题是否以问号结尾？",
            "小节标题是否在3-12字之间？",
            "标题中是否滥用了冒号、破折号、引号？",
            "关键词是否精准反映核心概念？",
        ],
    },
    "writing_style": {
        "name": "文笔与文风",
        "max_score": 15,
        "weight": 1.0,
        "freeze_condition": "连续2轮满分",
        "related_sections": ["all"],
        "responsible_agent": "polisher",
        "checkpoints": [
            "破折号是否超过15处？",
            "冒号是否在句中滥用？",
            "是否存在空洞修饰语？",
            "是否存在断裂式表达？",
            "句长是否普遍超过40字？",
            "段落是否普遍超过400字？",
        ],
    },
    "academic_depth": {
        "name": "学术深度",
        "max_score": 15,
        "weight": 1.0,
        "freeze_condition": "连续2轮≥14分",
        "related_sections": ["literature_review", "findings"],
        "responsible_agent": "expert",
        "checkpoints": [
            "核心概念是否在首次出现时清晰定义？",
            "论证是否层层递进？",
            "是否与至少5-8篇核心文献进行了实质性对话？",
            "理论贡献是否明确？",
        ],
    },
    "theoretical_rigor": {
        "name": "学理性",
        "max_score": 15,
        "weight": 1.0,
        "freeze_condition": "连续2轮≥14分",
        "related_sections": ["findings", "discussion"],
        "responsible_agent": "expert",
        "checkpoints": [
            "论文是否超越了'是什么'而回答了'为什么'和'所以呢'？",
            "是否存在'并列描述'而非'层次嵌套'的问题？",
            "每个核心论点是否有至少2-3个编码节点支撑？",
            "反直觉发现是否被充分展开？",
        ],
    },
    "visual_quality": {
        "name": "图表美观度与专业性",
        "max_score": 10,
        "weight": 1.0,
        "freeze_condition": "连续2轮满分",
        "related_sections": ["figures", "tables"],
        "responsible_agent": "visualizer",
        "checkpoints": [
            "表格是否为规范的三线表？",
            "是否使用了高级图表类型？",
            "是否出现了柱状图/饼图等低级图表？",
            "图表配色是否学术？",
            "分辨率是否≥300dpi？",
            "图表是否具有自明性？",
        ],
    },
    "format_standard": {
        "name": "格式标准性",
        "max_score": 10,
        "weight": 1.0,
        "freeze_condition": "连续2轮满分",
        "related_sections": ["all"],
        "responsible_agent": "visualizer",
        "checkpoints": [
            "页面设置是否符合目标期刊要求？",
            "标题层级是否规范？",
            "脚注体例是否正确？",
            "参考文献格式是否统一？",
        ],
    },
    "rigor": {
        "name": "严谨性",
        "max_score": 10,
        "weight": 1.0,
        "freeze_condition": "连续2轮≥9分",
        "related_sections": ["citations", "methodology"],
        "responsible_agent": "expert",
        "checkpoints": [
            "文献引用是否真实、准确？",
            "编码数据与论文论点是否一致？",
            "方法论说明是否完整？",
            "研究局限是否坦诚具体？",
        ],
    },
    "professionalism": {
        "name": "专业性",
        "max_score": 10,
        "weight": 1.0,
        "freeze_condition": "连续2轮≥9分",
        "related_sections": ["all"],
        "responsible_agent": "expert",
        "checkpoints": [
            "是否体现了对学科理论的深入理解？",
            "术语使用是否恰当？",
            "研究设计是否合理？",
            "中文CSSCI期刊文献是否≥8条？",
        ],
    },
    "innovation": {
        "name": "创新性与启发价值",
        "max_score": 5,
        "weight": 1.0,
        "freeze_condition": "不冻结（创新性可随修订提升）",
        "related_sections": ["discussion", "conclusion"],
        "responsible_agent": "expert",
        "checkpoints": [
            "是否提出了新概念或分析框架？",
            "是否对既有理论有实质性推进？",
            "实践启示是否具体可操作？",
        ],
    },
}


# ============================================================================
# 论文架构师配置（v5.1新增）
# ============================================================================

ARCHITECT_CONFIG = {
    "enabled": True,                         # 架构师是否启用
    "trigger_keywords": [                    # 触发关键词
        "理清研究思路",
        "搭建论文框架",
        "设计论文结构",
        "帮我组织论文",
        "论文框架",
        "研究框架",
        "章节结构",
        "帮我确定研究问题",
        "设计研究方案",
    ],
    "five_stage_guidance": {                # 五阶段引导配置
        "stage_1_phenomenon": {"max_rounds": 3, "output_words": 300},
        "stage_2_subject": {"max_rounds": 3, "output_words": 400},
        "stage_3_question": {"max_rounds": 3, "output_words": 300},
        "stage_4_value": {"max_rounds": 2, "output_words": 300},
        "stage_5_framework": {"output_words": 1500},
    },
    "framework_output": {                    # 框架输出配置
        "include_title": True,
        "include_abstract": True,
        "include_keywords": True,
        "include_chapter_structure": True,
        "include_method_recommendation": True,
        "include_literature_direction": True,
        "include_argumentation_line": True,
        "include_writing_notes": True,
    },
    "title_style": {                         # 标题风格配置
        "main_title_max_chars": 25,
        "main_title_min_chars": 15,
        "require_rhetorical_question": True,  # 主标题是否必须反问式
        "subtitle_connector": "冒号",
    },
    "word_count_constraints": {              # 全文字数约束（v6.3：改为动态计算，此为默认值）
        "total": 15000,                     # 默认值，实际由 PipelineConfig.user_target_words 决定
        "abstract": 350,
        "introduction": 600,
        "literature_review": 2000,
        "method": 800,
        "findings": 3750,                    # 3500-4000中值
        "conclusion": 1750,                    # 1500-2000中值
        "tolerance": 0.10,                   # ±10%容差
        "note": "v6.3: 各章节字数按 user_target_words/15000 等比缩放",
    },
}


# ============================================================================
# 意见路由规则配置（v6.2 六Agent版：新增 narrator 路由）
# ============================================================================

OPINION_ROUTING_RULES: Dict[str, str] = {
    # ===== 润色者 (Polisher) =====
    "标题": "polisher",
    "主标题": "polisher",
    "副标题": "polisher",
    "小节标题": "polisher",
    "关键词": "polisher",
    "破折号": "polisher",
    "冒号": "polisher",
    "引号": "polisher",
    "标点": "polisher",
    "标点符号": "polisher",
    "语句": "polisher",
    "长句": "polisher",
    "句子": "polisher",
    "修辞": "polisher",
    "修饰语": "polisher",
    "文笔": "polisher",
    "文风": "polisher",
    "语言": "polisher",
    "行文": "polisher",
    "表达": "polisher",
    "段落": "polisher",
    "篇幅": "polisher",
    "字数": "polisher",
    "口语": "polisher",
    "口语化": "polisher",
    "流畅": "polisher",
    "流畅性": "polisher",
    "可读性": "polisher",
    "冗余": "polisher",
    "重复": "polisher",
    "辞藻": "polisher",
    "措辞": "polisher",
    "引语": "polisher",    # v5.0: 受访者引语润色归润色者

    # ===== 可视化者 (Visualizer) =====
    "图表": "visualizer",
    "表格": "visualizer",
    "三线表": "visualizer",
    "图": "visualizer",
    "表": "visualizer",
    "可视化": "visualizer",
    "配色": "visualizer",
    "颜色": "visualizer",
    "字体": "visualizer",
    "分辨率": "visualizer",
    "dpi": "visualizer",
    "占位符": "visualizer",
    "图题": "visualizer",
    "表题": "visualizer",
    "表注": "visualizer",
    "英文摘要": "visualizer",
    "英文关键词": "visualizer",
    "排版": "visualizer",
    "页面": "visualizer",
    "页边距": "visualizer",
    "字号": "visualizer",
    "行距": "visualizer",

    # ===== 专家 (Expert) — v5.0整合文献验证+合并功能 =====
    # 内容与理论
    "文献": "expert",
    "参考文献": "expert",
    "引用": "expert",
    "理论": "expert",
    "论证": "expert",
    "逻辑": "expert",
    "概念": "expert",
    "定义": "expert",
    "编码": "expert",
    "方法论": "expert",
    "方法": "expert",
    "研究设计": "expert",
    "抽样": "expert",
    "样本": "expert",
    "饱和": "expert",
    "理论饱和": "expert",
    "效度": "expert",
    "信度": "expert",
    "结构": "expert",
    "框架": "expert",
    "章节": "expert",
    "对话": "expert",
    "理论对话": "expert",
    "贡献": "expert",
    "理论贡献": "expert",
    "创新": "expert",
    "局限": "expert",
    "摘要": "expert",
    "引言": "expert",
    "结语": "expert",
    "讨论": "expert",
    "规范性": "expert",
    "学术规范": "expert",
    "归因": "expert",
    "命题": "expert",
    "发现": "expert",
    "分析": "expert",
    "数据": "expert",
    "证据": "expert",
    "案例": "expert",
    "性别": "expert",
    "年龄": "expert",
    "代际": "expert",
    # 文献验证（原文献追踪者 → 整合至专家）
    "验证": "expert",
    "真实性": "expert",
    "文献核实": "expert",
    "DOI": "expert",
    "检索": "expert",
    "数据库": "expert",
    # 合并与一致性（原合并者 → 整合至专家）
    "一致性": "expert",
    "统一": "expert",
    "混用": "expert",
    "术语": "expert",
    # 全局路由
    "全局": "expert",
    "整体": "expert",
    "全文": "expert",
    "总体": "expert",
    "综合": "expert",

    # ===== 论文架构师 (Architect) — v5.1新增 =====
    "架构": "architect",
    "框架设计": "architect",
    "结构问题": "architect",
    "章节划分": "architect",
    "论证路线": "architect",
    "论证逻辑线": "architect",
    "比例失调": "architect",
    "结构性缺陷": "architect",
    "重新架构": "architect",
    "框架调整": "architect",
    "研究问题界定": "architect",
    "研究对象界定": "architect",
    "概念操作化": "architect",

    # ===== 叙事连贯性主编 (Narrator) — v6.2新增 =====
    "节奏": "narrator",
    "节奏感": "narrator",
    "连贯": "narrator",
    "连贯性": "narrator",
    "声音": "narrator",
    "声音一致性": "narrator",
    "断裂": "narrator",
    "断裂化": "narrator",
    "生硬": "narrator",
    "翻译腔": "narrator",
    "翻译感": "narrator",
    "机械": "narrator",
    "机械感": "narrator",
    "机器味": "narrator",
    "AI味": "narrator",
    "过渡": "narrator",
    "过渡生硬": "narrator",
    "衔接": "narrator",
    "衔接不当": "narrator",
    "叙事": "narrator",
    "叙事断裂": "narrator",
    "朗读": "narrator",
    "朗读测试": "narrator",
    "语感": "narrator",
    "语流": "narrator",
    "气口": "narrator",
    "人类化": "narrator",
    "人味": "narrator",

    # ===== 内参撰写者 (NeicanWriter) — ★v7.4新增 =====
    "内参": "neican_writer",
    "内参报告": "neican_writer",
    "政策建议": "neican_writer",
    "决策参考": "neican_writer",
    "公鸡打鸣": "neican_writer",
    "虎气": "neican_writer",
    "猴气": "neican_writer",
    "对策建议": "neican_writer",
    "报忧": "neican_writer",
    "报喜": "neican_writer",
}


# ============================================================================
# 修改范围控制配置（v5.1 五Agent版）
# ============================================================================

MODIFICATION_SCOPE: Dict[str, List[str]] = {
    "language_only": ["polisher"],
    "chart_only": ["visualizer"],
    "content_theory": ["expert"],
    "citation_verify": ["expert"],
    "framework_design": ["architect"],       # v5.1新增
    "title": ["polisher", "expert"],
    "global": ["polisher", "visualizer", "expert", "architect"],
}


# ============================================================================
# 研究类型配置（v6.2 扩展为6类：新增 mixed/interview_report/theoretical）
# ============================================================================

RESEARCH_TYPE_CONFIGS: Dict[str, Dict] = {
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
        "expert_focus": [
            "编码数据充分利用",
            "理论命题对照验证",
            "分析深度（超越描述）",
            "反直觉发现挖掘",
        ],
        "review_dimension_weights": {
            "theoretical_rigor": 1.2,   # 学理性加权
            "academic_depth": 1.0,
            "innovation": 1.2,          # 创新性加权
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
        "expert_focus": [
            "假设推导逻辑",
            "变量操作化合理性",
            "统计结果解释准确性",
            "稳健性检验完整性",
        ],
        "review_dimension_weights": {
            "rigor": 1.2,               # 严谨性加权
            "professionalism": 1.1,     # 专业性加权
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
        "expert_focus": [
            "方法创新性说明",
            "计算范式与社科学理的桥接",
            "结果可解释性",
            "数据伦理与隐私",
        ],
        "review_dimension_weights": {
            "innovation": 1.3,          # 创新性加权
            "academic_depth": 1.1,      # 学术深度加权
        },
    },
    "mixed": {
        "name": "混合方法研究",
        "name_en": "Mixed Methods Research",
        "key_methods": ["序列解释设计", "并行三角验证", "嵌入设计", "解释性序列设计", "探索性序列设计"],
        "codebook_required": True,
        "verification_points": [
            "质化-量化整合逻辑检查",
            "三角验证完整性",
            "两种方法权重说明",
            "整合节点（merging point）明确性",
        ],
        "expert_focus": [
            "方法整合的论证逻辑",
            "质化发现与量化结果的对话",
            "不一致发现的解释深度",
            "元推论（meta-inference）质量",
        ],
        "review_dimension_weights": {
            "rigor": 1.2,               # 严谨性加权（整合要求高）
            "innovation": 1.1,          # 创新性加权
            "academic_depth": 1.2,      # 学术深度加权
        },
    },
    "interview_report": {
        "name": "访谈报告",
        "name_en": "Interview Report",
        "key_methods": ["半结构化访谈", "深度访谈", "口述史", "生命史访谈", "焦点小组访谈"],
        "codebook_required": True,
        "verification_points": [
            "受访者信息表完整性",
            "访谈编码矩阵展示",
            "三明治引语结构检查（概念命名→引语支撑→即时概念化）",
            "受访者匿名化处理",
        ],
        "expert_focus": [
            "受访者画像立体度",
            "引语选择的分析性（非装饰性）",
            "场景描写的厚度",
            "受访者声音的多样性呈现",
        ],
        "review_dimension_weights": {
            "academic_depth": 1.2,      # 学术深度加权
            "innovation": 1.0,
            "theoretical_rigor": 1.1,   # 学理性加权
        },
    },
    "theoretical": {
        "name": "理论建构研究",
        "name_en": "Theoretical Research",
        "key_methods": ["概念谱系梳理", "理论对话", "命题推演", "思想实验", "元理论分析"],
        "codebook_required": False,
        "verification_points": [
            "概念定义清晰度检查",
            "理论对话层次完整性",
            "命题推演逻辑链条",
            "理论贡献边界界定",
        ],
        "expert_focus": [
            "概念谱系梳理的完整性",
            "理论对话的深度（非标签式引用）",
            "命题的可证伪性",
            "理论建构的增量贡献",
        ],
        "review_dimension_weights": {
            "theoretical_rigor": 1.4,   # 学理性强加权
            "innovation": 1.3,          # 创新性强加权
            "academic_depth": 1.2,      # 学术深度加权
        },
    },
}


# ============================================================================
# 持续学习配置（v5.0新增）
# ============================================================================

LEARNING_CONFIG = {
    "enabled": True,                       # 总体学习开关
    "trigger_round": 1,                     # 从第1轮开始学习
    "review_required": False,               # 规则更新是否需要人工审核
    "log_path": ".trae/skills/cyclical-paper-generation/learning_logs/",
    "agents": {                             # 各Agent学习配置
        "polisher": {"enabled": True, "focus": ["标点偏好", "语句风格", "标题风格"]},
        "visualizer": {"enabled": True, "focus": ["图表类型", "配色方案", "表格密度"]},
        "expert": {"enabled": True, "focus": ["理论偏好", "章节结构", "文献偏好"]},
        "reviewer": {"enabled": True, "focus": ["评分权重", "容忍度", "批评风格"]},
        "architect": {"enabled": True, "focus": ["框架偏好", "方法论倾向", "标题风格"]},
    },
    "rule_update": {
        "max_rules_per_agent": 50,          # 每个Agent最多规则数
        "auto_update_threshold": 3,          # 同一特征出现3次以上自动更新
        "version_tracking": True,            # 是否追踪规则版本
    }
}


# ============================================================================
# v6.0 新增：Agent 定义
# ============================================================================

AGENT_DEFINITIONS = {
    "architect": {"name": "论文架构师", "order": 0, "enabled": True, "file": "agents/architect.md", "category": "framework"},
    "polisher": {"name": "润色者", "order": 1, "enabled": True, "file": "agents/polisher.md", "category": "language"},
    "visualizer": {"name": "可视化者", "order": 2, "enabled": True, "file": "agents/visualizer.md", "category": "visual"},
    "methodologist": {"name": "方法论专家", "order": 3, "enabled": True, "file": "agents/methodologist.md", "category": "methodology"},
    "literature_curator": {"name": "文献策展人", "order": 4, "enabled": True, "file": "agents/literature_curator.md", "category": "literature"},
    "expert": {"name": "内容专家", "order": 5, "enabled": True, "file": "agents/expert.md", "category": "content"},
    "reviewer": {"name": "审稿人", "order": 6, "enabled": True, "file": "agents/reviewer.md", "category": "review"},
    "word_count_controller": {"name": "字数控制器", "order": 7, "enabled": True, "file": "agents/word_count_controller.md", "category": "control"},
    "narrator": {"name": "叙事连贯性主编", "order": 8, "enabled": True, "file": "agents/narrator.md", "category": "narrative"},
    "orchestrator": {"name": "编排者", "order": 9, "enabled": True, "file": "agents/orchestrator.md", "category": "meta"},
    "style_guard": {"name": "风格守卫", "order": 10, "enabled": True, "file": None, "category": "guard"},
    "word_format_validator": {"name": "Word格式验证", "order": 11, "enabled": True, "file": "agents/word_format_validator.md", "category": "output"},
    "neican_writer": {"name": "内参撰写者", "order": 12, "enabled": False, "file": "agents/neican_writer.md", "category": "neican"},
}

AGENT_EXECUTION_ORDER = [
    "constraint_injector",
    "polisher", "style_validator", "visualizer",
    "methodologist", "literature_curator",
    "expert", "style_validator", "word_count_controller",
    "narrator", "orchestrator", "reviewer",
]


# ============================================================================
# v6.0 新增：研究类型映射
# ============================================================================

RESEARCH_TYPE_AGENT_MAP = {
    "qualitative": {
        "required": ["constraint_injector", "polisher", "visualizer", "methodologist",
                     "literature_curator", "expert", "word_count_controller", "narrator",
                     "orchestrator", "reviewer", "word_format_validator"],
        "extra": {"methodologist_mode": "qualitative"},
    },
    "quantitative": {
        "required": ["constraint_injector", "polisher", "visualizer", "methodologist",
                     "literature_curator", "expert", "word_count_controller", "narrator",
                     "orchestrator", "reviewer", "word_format_validator"],
        "extra": {"methodologist_mode": "quantitative"},
    },
    "computational": {
        "required": ["constraint_injector", "polisher", "visualizer", "methodologist",
                     "literature_curator", "expert", "word_count_controller", "narrator",
                     "orchestrator", "reviewer", "word_format_validator"],
        "extra": {"methodologist_mode": "computational"},
    },
    "mixed": {
        "required": ["constraint_injector", "polisher", "visualizer", "methodologist",
                     "literature_curator", "expert", "word_count_controller", "narrator",
                     "orchestrator", "reviewer", "word_format_validator"],
        "extra": {"methodologist_mode": "mixed"},
    },
    "interview_report": {
        "required": ["constraint_injector", "polisher", "methodologist", "expert",
                     "word_count_controller", "narrator", "orchestrator", "reviewer",
                     "word_format_validator"],
        "optional": ["visualizer"],
        "extra": {"methodologist_mode": "qualitative"},
    },
    "theoretical": {
        "required": ["constraint_injector", "expert", "literature_curator", "narrator",
                     "orchestrator", "reviewer", "word_format_validator"],
        "optional": ["polisher", "visualizer", "methodologist"],
    },
}


# ============================================================================
# v6.0 新增：Word 验证配置
# ============================================================================

WORD_VALIDATION_CONFIG = {
    "enabled": True,
    "checks": {"docx_openable": True, "footnote_real": True,
               "footnote_ref_match": True, "chinese_quote_font": True,
               "chart_numbering": True},
    "font_rules": {"east_asian": "宋体", "western": "Times New Roman"},
}


# ============================================================================
# Pipeline主配置类（v6.0）
# ============================================================================
# ============================================================================

@dataclass
class PipelineConfig:
    """Pipeline全局配置（v5.1五Agent版）"""

    # ===== 循环控制 =====
    max_rounds: int = 7                    # 最大循环次数（v7.0: 从5调整为7，因GAN对抗评分加入后需要更多轮次达到95分阈值）
    pass_threshold: int = 90               # 通过分数阈值
    stagnation_threshold: float = 3.0      # 连续N轮提升<此值触发人工介入
    max_stagnant_rounds: int = 3           # 最多停滞轮次

    # ===== 防死锁参数 =====
    max_score_stagnation_rounds: int = 3   # 连续N轮评分提升不足则触发死锁
    dimension_regression_threshold: int = -1  # 维度倒退检测阈值（负值即倒退）

    # ===== Agent执行模式 =====
    sequential_mode: bool = True           # Agent是否顺序执行
    incremental_mode: bool = True          # 是否启用增量修改
    auto_route_opinions: bool = True       # 是否自动分发审稿意见

    # ===== 论文架构师配置（v5.1新增） =====
    architect_enabled: bool = True          # 论文架构师是否启用
    architect_auto_trigger: bool = True     # 是否自动检测触发条件

    # ===== 研究类型 =====
    research_type: str = "qualitative"     # qualitative/quantitative/computational/mixed/interview_report/theoretical

    # ===== 字数控制（v6.3重构：用户自定义字数目标） =====
    user_target_words: int = 15000          # 用户指定的全文字数目标（v6.3新增：取代硬编码15000）
    word_count_hard_limit: int = 0          # 字数硬上限（0表示自动计算 = user_target_words * 1.1）
    word_count_tolerance: float = 0.1       # 字数容忍度（±10%）
    word_count_enforcement: str = "strict"  # 执行模式: "strict"(硬截断) / "compress"(仅压缩) / "warn"(仅警告)
    word_count_compression_strategies: List = field(default_factory=lambda: ["P1", "P2", "P3", "P4", "P5"])

    # ===== 回滚机制（v6.2新增） =====
    rollback_enabled: bool = True          # 是否启用检查回滚
    max_rollback_per_round: int = 3        # 每轮最大回滚次数
    max_agent_retry: int = 2               # Agent回滚后最大重试次数
    snapshot_max_versions: int = 5         # 每章节最大快照保留数

    # ===== GAN对抗评分（v7.0新增：消除AI自评幻觉） =====
    gan_enabled: bool = True                # 是否启用GAN对抗评分（D Agent）
    trust_weight_alpha: float = 0.4         # G评分的信任权重（默认0.4，偏向D挑刺方）
    adversarial_signal_threshold: float = 10.0  # 对抗信号强度阈值

    # ===== 输出配置 =====
    output_format: str = "word"            # 输出格式: "word" / "markdown"
    journal_style: str = "xwycbyj"         # 目标期刊: xwycbyj/gjxwj/xwdx/shxyj
    save_all_versions: bool = True         # 是否保存所有版本
    keep_last_n_versions: int = 3          # 保留最近N个版本

    # ===== 内参报告配置（★v7.4新增） =====
    output_mode: str = "paper"              # 输出模式: "paper"(默认) / "neican" / "both"

    # ===== 评分配置 =====
    scoring_dimensions: Dict = field(default_factory=lambda: SCORING_DIMENSIONS)
    freeze_on_perfect: bool = True         # 满分是否触发章节冻结
    freeze_on_stagnation: bool = True      # 停滞是否触发章节冻结

    # ===== 文献配置 =====
    min_chinese_citations: int = 8         # 最少中文CSSCI文献数
    max_citation_age: int = 10             # 文献最大年限（超过则建议更新）

    # ===== 图表配置 =====
    output_dpi: int = 600                  # 图表分辨率（投稿用）
    review_dpi: int = 300                  # 图表分辨率（审稿用）
    preferred_format: str = "png"          # 首选图表格式
    color_scheme: str = "okabe_ito"        # 配色方案

    # ===== 路径配置 =====
    paper_path: str = ""                   # 论文文件路径
    output_dir: str = ""                   # 输出目录
    coding_data_path: str = ""             # 编码数据路径

    # ===== 持续学习配置（v5.0新增） =====
    learning_enabled: bool = True           # 学习开关
    learning_trigger_round: int = 1         # 从第几轮开始学习
    learning_review_required: bool = False  # 规则更新是否需要人工审核
    learning_log_path: str = ".trae/skills/cyclical-paper-generation/learning_logs/"  # 学习日志路径

    def get_journal_config(self) -> Dict:
        """获取当前期刊配置"""
        return JOURNAL_CONFIGS.get(self.journal_style, JOURNAL_CONFIGS["xwycbyj"])

    def get_effective_hard_limit(self) -> int:
        """获取有效的字数硬上限（v6.3新增）

        若 word_count_hard_limit > 0 则使用用户设定值，
        否则自动计算 = user_target_words * (1 + tolerance)
        """
        if self.word_count_hard_limit > 0:
            return self.word_count_hard_limit
        return int(self.user_target_words * (1 + self.word_count_tolerance))

    def get_section_budgets(self) -> Dict:
        """获取按用户目标字数等比缩放的各章节预算（v6.3新增）"""
        from .style_constraints import compute_section_budgets
        return compute_section_budgets(self.user_target_words, self.word_count_tolerance)

    def get_scoring_dimensions(self) -> Dict:
        """获取评分维度配置"""
        return self.scoring_dimensions

    def get_routing_rules(self) -> Dict[str, str]:
        """获取意见路由规则"""
        return OPINION_ROUTING_RULES

    def get_research_type_config(self) -> Dict:
        """获取当前研究类型配置（v5.0新增）"""
        return RESEARCH_TYPE_CONFIGS.get(
            self.research_type, RESEARCH_TYPE_CONFIGS["qualitative"]
        )

    def get_research_type_weights(self) -> Dict:
        """获取研究类型对应的维度权重（v5.0新增）"""
        rt_config = self.get_research_type_config()
        return rt_config.get("review_dimension_weights", {})

    def validate(self) -> List[str]:
        """验证配置有效性，返回错误列表"""
        errors = []

        if self.max_rounds < 1 or self.max_rounds > 10:
            errors.append(
                f"max_rounds应在1-10之间，当前值: {self.max_rounds}"
            )

        if self.pass_threshold < 60 or self.pass_threshold > 100:
            errors.append(
                f"pass_threshold应在60-100之间，当前值: {self.pass_threshold}"
            )

        if self.journal_style not in JOURNAL_CONFIGS:
            errors.append(
                f"不支持的期刊格式: {self.journal_style}，"
                f"支持: {list(JOURNAL_CONFIGS.keys())}"
            )

        if self.output_format not in ["word", "markdown"]:
            errors.append(
                f"不支持的输出格式: {self.output_format}，支持: word/markdown"
            )

        if self.output_mode not in ["paper", "neican", "both"]:
            errors.append(
                f"不支持的输出模式: {self.output_mode}，支持: paper/neican/both"
            )

        if self.research_type not in RESEARCH_TYPE_CONFIGS:
            errors.append(
                f"不支持的研究类型: {self.research_type}，"
                f"支持: {list(RESEARCH_TYPE_CONFIGS.keys())}"
            )

        if self.max_score_stagnation_rounds < 2:
            errors.append(
                f"max_score_stagnation_rounds应≥2，当前值: {self.max_score_stagnation_rounds}"
            )

        return errors

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "max_rounds": self.max_rounds,
            "pass_threshold": self.pass_threshold,
            "stagnation_threshold": self.stagnation_threshold,
            "max_stagnant_rounds": self.max_stagnant_rounds,
            "max_score_stagnation_rounds": self.max_score_stagnation_rounds,
            "dimension_regression_threshold": self.dimension_regression_threshold,
            "sequential_mode": self.sequential_mode,
            "incremental_mode": self.incremental_mode,
            "auto_route_opinions": self.auto_route_opinions,
            "architect_enabled": self.architect_enabled,
            "architect_auto_trigger": self.architect_auto_trigger,
            "research_type": self.research_type,
            "output_format": self.output_format,
            "output_mode": self.output_mode,
            "journal_style": self.journal_style,
            "save_all_versions": self.save_all_versions,
            "min_chinese_citations": self.min_chinese_citations,
            "output_dpi": self.output_dpi,
            "learning_enabled": self.learning_enabled,
            "learning_trigger_round": self.learning_trigger_round,
            "learning_review_required": self.learning_review_required,
            "learning_log_path": self.learning_log_path,
        }