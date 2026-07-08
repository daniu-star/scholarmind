"""
循环式论文生成Pipeline v6.0 - 共享学习档案管理

所有 Agent 共享的学习档案（Shared Learning Profile）。
每次循环完成后，Orchestrator 从各 agent 的学习日志中提取共性模式，
更新共享档案。下一轮开始时 ConstraintInjector 据此生成个性化指令。

Author: Cyclical Paper Generation Pipeline
Version: 6.3.0
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import json
import os


# ============================================================================
# 共享学习档案数据结构
# ============================================================================

DEFAULT_SHARED_PROFILE = {
    "user_style_preferences": {
        "title_style": "反问式, 15-25字",
        "hates_colon_in_body": None,  # bool: 用户是否厌恶正文冒号
        "prefers_short_paragraphs": None,  # bool: 用户是否偏好短段落
        "forbidden_phrases": [],  # list[str]: 用户反感的具体用语
        "preferred_citation_style": "(author, year)",
        "max_dash_tolerance": 15,  # 用户对破折号的容忍度
        "abstract_style_notes": "",  # 用户偏好的摘要风格
        "findings_structure_notes": "",  # 用户偏好的研究发现结构
    },
    "theoretical_preferences": {
        "preferred_theories": [],  # list[str]: 高频引用的理论
        "preferred_scholars": [],  # list[str]: 高频引用的学者
        "avoided_theories": [],  # list[str]: 用户不喜欢使用的理论
    },
    "structural_preferences": {
        "findings_structure": "two_sections_three_subsections_each",
        "conclusion_structure": "反思+升华+建议+人文关怀",
        "literature_review_structure": "三节递进",
        "method_sections_preferred": ["抽样", "数据收集", "编码分析", "伦理"],
    },
    "citation_preferences": {
        "min_chinese_citations": 8,
        "preferred_journals": [],  # list[str]: 高频引用的期刊
        "avoid_books": True,  # 避免以书籍专著为主
        "citation_age_limit": 10,  # 超过此年限建议更新
    },
    "research_design_preferences": {
        "preferred_methods": [],  # list[str]: 偏好的研究方法
        "sample_size_reference": "",  # 偏好的样本规模参考
        "coding_approach": "",  # 偏好的编码策略
    },
    "update_history": [],  # list[dict]: 学习记录历史
    "last_updated": None,  # ISO datetime string
}


class SharedLearningProfile:
    """共享学习档案管理器"""

    def __init__(self, profile_path: Optional[str] = None):
        if profile_path is None:
            profile_path = "shared_learning_profile.json"
        self.profile_path = profile_path
        self.profile: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        """从文件加载共享学习档案"""
        if os.path.exists(self.profile_path):
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # 确保所有字段存在
                    for key, default_value in DEFAULT_SHARED_PROFILE.items():
                        if key not in data:
                            data[key] = default_value
                    return data
            except (json.JSONDecodeError, IOError):
                return DEFAULT_SHARED_PROFILE.copy()
        return DEFAULT_SHARED_PROFILE.copy()

    def save(self):
        """保存共享学习档案到文件"""
        self.profile["last_updated"] = datetime.now().isoformat()
        os.makedirs(os.path.dirname(self.profile_path) or ".", exist_ok=True)
        with open(self.profile_path, "w", encoding="utf-8") as f:
            json.dump(self.profile, f, ensure_ascii=False, indent=2)

    def update_from_agent_log(self, agent_type: str, log_entry: Dict):
        """根据 agent 的学习日志更新共享档案

        参数:
            agent_type: polisher / expert / reviewer / architect / visualizer
            log_entry: 学习日志条目，包含 extracted_features 和 rule_updates
        """
        features = log_entry.get("extracted_features", [])
        rule_updates = log_entry.get("rule_updates", [])

        for feature in features:
            self._apply_feature(agent_type, feature)
        for update in rule_updates:
            self._apply_rule_update(agent_type, update)

        # 记录更新历史
        self.profile["update_history"].append({
            "timestamp": datetime.now().isoformat(),
            "agent_type": agent_type,
            "features": features,
            "rule_updates": rule_updates,
        })

        self.save()

    def extract_style_features(self, text: str) -> Dict[str, Any]:
        """提取文本的风格特征（v6.2新增）

        提取句长分布、连接词偏好、人称视角、术语密度、段落开头多样性等风格特征，
        写入 self.profile["style_features"] 并返回。

        Args:
            text: 待分析的文本

        Returns:
            风格特征字典，包含：
            - avg_sentence_length: 平均句长（字/句）
            - short_sentence_ratio: 短句占比（<15字的句子占比）
            - long_sentence_ratio: 长句占比（>40字的句子占比）
            - connector_preferences: 连接词偏好（因果/转折/并列/递进四类频率）
            - person_perspective: 人称视角（第一人称单数/复数/第三人称占比）
            - terminology_density: 术语密度（专业术语数/总字数）
            - paragraph_opening_diversity: 段落开头多样性（30种模式命中率）
        """
        import re

        # 句子分割（按句号、问号、感叹号）
        sentences = re.split(r'[。！？]', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        total_sentences = len(sentences)

        if total_sentences == 0:
            return {"error": "无有效句子"}

        # 句长分布
        sentence_lengths = [len(s) for s in sentences]
        avg_length = sum(sentence_lengths) / total_sentences
        short_count = sum(1 for l in sentence_lengths if l < 15)
        long_count = sum(1 for l in sentence_lengths if l > 40)

        # 连接词偏好
        causal_connectors = len(re.findall(r'因此|所以|由于|因为|导致|使得|促使', text))
        adversative_connectors = len(re.findall(r'然而|但是|不过|尽管|虽然|反之|相反', text))
        coordinative_connectors = len(re.findall(r'同时|此外|另外|并且|而且|以及', text))
        progressive_connectors = len(re.findall(r'进而|甚至|更|尤其|特别是|不仅.*而且', text))

        # 人称视角
        first_person_singular = len(re.findall(r'我[^们]|笔者', text))
        first_person_plural = len(re.findall(r'我们|本研究|本文', text))
        third_person = len(re.findall(r'他[^们]|她[^们]|它[^们]|受访者|被试', text))
        total_person = first_person_singular + first_person_plural + third_person or 1

        # 术语密度（简化版：统计含英文括号注释的术语）
        terminology_count = len(re.findall(r'[\u4e00-\u9fa5]+（[A-Za-z]+）', text))
        total_chars = len(text)

        # 段落开头多样性
        paragraphs = text.split('\n')
        paragraphs = [p.strip() for p in paragraphs if p.strip()]
        opening_patterns = [
            '基于', '通过', '在', '对', '从', '随着', '然而', '因此', '本研究', '本文',
            '值得注意', '需要指出', '综上', '由此', '进一步', '与此', '尽管', '虽然',
            '正如', '根据', '按照', '相较于', '不同于', '类似于', '不同于', '有别于',
            '聚焦于', '着眼于', '立足于', '致力于', '回归到', '回到'
        ]
        opening_hits = sum(1 for p in paragraphs if any(p.startswith(op) for op in opening_patterns))
        opening_diversity = opening_hits / len(paragraphs) if paragraphs else 0

        features = {
            "avg_sentence_length": round(avg_length, 1),
            "short_sentence_ratio": round(short_count / total_sentences, 3),
            "long_sentence_ratio": round(long_count / total_sentences, 3),
            "connector_preferences": {
                "causal": causal_connectors,
                "adversative": adversative_connectors,
                "coordinative": coordinative_connectors,
                "progressive": progressive_connectors,
            },
            "person_perspective": {
                "first_singular": round(first_person_singular / total_person, 3),
                "first_plural": round(first_person_plural / total_person, 3),
                "third_person": round(third_person / total_person, 3),
            },
            "terminology_density": round(terminology_count / (total_chars / 1000), 3) if total_chars > 0 else 0,
            "paragraph_opening_diversity": round(opening_diversity, 3),
            "total_sentences": total_sentences,
            "total_paragraphs": len(paragraphs),
        }

        self.profile["style_features"] = features
        return features

    def extract_citation_features(self, text: str) -> Dict[str, Any]:
        """提取文本的引用特征（v6.2新增）

        提取引用密度、引用格式分布、引用来源类型分布、自引率等引用特征，
        写入 self.profile["citation_features"] 并返回。

        Args:
            text: 待分析的文本

        Returns:
            引用特征字典
        """
        import re

        total_chars = len(text)
        if total_chars == 0:
            return {"error": "空文本"}

        # 引用提取
        inline_citations = re.findall(r'（[^）]*\d{4}[^）]*）', text)  # 内嵌式：（张三，2020）
        three_part_citations = re.findall(r'[\u4e00-\u9fa5]{2,4}（\d{4}）', text)  # 三段式：张三（2020）
        footnote_citations = re.findall(r'\[\d+\]', text)  # 脚注式：[1]

        total_citations = len(inline_citations) + len(three_part_citations) + len(footnote_citations)

        # 引用来源类型（简化版：基于关键词匹配）
        journal_count = len(re.findall(r'期刊|学报|Journal|journal', text))
        book_count = len(re.findall(r'出版社|Press|press|Book|book', text))
        conference_count = len(re.findall(r'会议|Conference|conference|Proceedings', text))
        web_count = len(re.findall(r'http|www\.|访问日期|检索自', text))
        total_sources = journal_count + book_count + conference_count + web_count or 1

        # 自引率（简化版：统计作者姓名与profile中记录的作者匹配的引用）
        known_authors = self.profile.get("known_authors", [])
        self_citations = 0
        for author in known_authors:
            self_citations += len(re.findall(author, text))

        features = {
            "citation_density": round(total_citations / (total_chars / 1000), 3),  # 引用数/千字
            "total_citations": total_citations,
            "format_distribution": {
                "inline": len(inline_citations),
                "three_part": len(three_part_citations),
                "footnote": len(footnote_citations),
            },
            "source_type_distribution": {
                "journal": round(journal_count / total_sources, 3),
                "book": round(book_count / total_sources, 3),
                "conference": round(conference_count / total_sources, 3),
                "web": round(web_count / total_sources, 3),
            },
            "self_citation_rate": round(self_citations / total_citations, 3) if total_citations > 0 else 0,
        }

        self.profile["citation_features"] = features
        return features

    def extract_structural_features(self, text: str) -> Dict[str, Any]:
        """提取文本的结构特征（v6.2新增）

        提取章节结构、段落结构、论证结构、图表分布等结构特征，
        写入 self.profile["structural_features"] 并返回。

        Args:
            text: 待分析的文本

        Returns:
            结构特征字典
        """
        import re

        # 章节结构（一级标题）
        headings = re.findall(r'^#{1,2}\s+(.+)$', text, re.MULTILINE)
        if not headings:
            headings = re.findall(r'^[一二三四五六七八九十]+、(.+)$', text, re.MULTILINE)

        heading_depth = max([len(re.match(r'#+', h).group()) for h in re.findall(r'^#+\s+', text, re.MULTILINE)] + [1])

        # 段落结构
        paragraphs = [p.strip() for p in text.split('\n') if p.strip() and not p.strip().startswith('#')]
        paragraph_count = len(paragraphs)
        avg_paragraph_length = sum(len(p) for p in paragraphs) / paragraph_count if paragraph_count > 0 else 0

        # 过渡段占比（含"综上""由此可见""进一步"等过渡词的段落）
        transition_words = ['综上', '由此可见', '进一步', '与此', '尽管如此', '总而言之', '综合以上']
        transition_paragraphs = sum(1 for p in paragraphs if any(tw in p for tw in transition_words))

        # 论证结构（假设-证据-结论三段式命中率）
        hypothesis_markers = len(re.findall(r'假设|假定|本研究认为|本文提出', text))
        evidence_markers = len(re.findall(r'数据表明|结果显示|分析发现|统计显示|访谈发现', text))
        conclusion_markers = len(re.findall(r'因此|综上|由此可见|这表明|这说明|由此可知', text))
        argumentation_hits = min(hypothesis_markers, evidence_markers, conclusion_markers)

        # 图表分布
        figure_count = len(re.findall(r'图\d+|Figure\s*\d+', text))
        table_count = len(re.findall(r'表\d+|Table\s*\d+', text))
        total_figures = figure_count + table_count

        features = {
            "heading_structure": {
                "headings": headings[:20],  # 最多记录20个标题
                "heading_count": len(headings),
                "max_depth": heading_depth,
            },
            "paragraph_structure": {
                "paragraph_count": paragraph_count,
                "avg_paragraph_length": round(avg_paragraph_length, 1),
                "transition_paragraph_ratio": round(transition_paragraphs / paragraph_count, 3) if paragraph_count > 0 else 0,
            },
            "argumentation_structure": {
                "hypothesis_markers": hypothesis_markers,
                "evidence_markers": evidence_markers,
                "conclusion_markers": conclusion_markers,
                "three_part_hits": argumentation_hits,
            },
            "figure_distribution": {
                "total_figures": total_figures,
                "figure_count": figure_count,
                "table_count": table_count,
                "density_per_thousand_chars": round(total_figures / (len(text) / 1000), 3) if len(text) > 0 else 0,
            },
        }

        self.profile["structural_features"] = features
        return features

    def learn_from_user_edit(self, original_text: str, edited_text: str,
                             section_name: str = "") -> Dict[str, Any]:
        """从用户编辑中学习写作偏好（v6.2新增）

        对比原始文本和编辑后文本的差异，提取用户编辑模式，
        更新风格特征，累积学习用户写作偏好。

        Args:
            original_text: 原始文本
            edited_text: 编辑后文本
            section_name: 章节名称（可选，用于记录编辑位置）

        Returns:
            编辑摘要字典，包含差异统计和编辑模式
        """
        import re
        from datetime import datetime

        # 字符级差异统计
        original_chars = len(original_text)
        edited_chars = len(edited_text)
        char_diff = edited_chars - original_chars

        # 句子级差异
        original_sentences = [s.strip() for s in re.split(r'[。！？]', original_text) if s.strip()]
        edited_sentences = [s.strip() for s in re.split(r'[。！？]', edited_text) if s.strip()]
        sentence_diff = len(edited_sentences) - len(original_sentences)

        # 编辑模式识别
        edit_patterns = []

        # 检测删除短句模式
        if len(edited_sentences) < len(original_sentences) and edited_chars < original_chars:
            edit_patterns.append("偏好删减短句")

        # 检测合并分句模式
        original_commas = original_text.count("，")
        edited_commas = edited_text.count("，")
        if edited_commas > original_commas and len(edited_sentences) < len(original_sentences):
            edit_patterns.append("偏好合并分句")

        # 检测连接词替换模式
        mechanical_connectors = ["综上所述", "由此可见", "不难发现", "显而易见", "毋庸置疑"]
        original_mechanical = sum(original_text.count(mc) for mc in mechanical_connectors)
        edited_mechanical = sum(edited_text.count(mc) for mc in mechanical_connectors)
        if edited_mechanical < original_mechanical:
            edit_patterns.append("偏好删除机械连接词")

        # 检测术语增加模式
        original_terms = len(re.findall(r'[\u4e00-\u9fa5]+（[A-Za-z]+）', original_text))
        edited_terms = len(re.findall(r'[\u4e00-\u9fa5]+（[A-Za-z]+）', edited_text))
        if edited_terms > original_terms:
            edit_patterns.append("偏好增加术语标注")

        # 检测人称视角变化
        original_first_plural = len(re.findall(r'我们|本研究|本文', original_text))
        edited_first_plural = len(re.findall(r'我们|本研究|本文', edited_text))
        if edited_first_plural != original_first_plural:
            if edited_first_plural > original_first_plural:
                edit_patterns.append("偏好增加第一人称复数")
            else:
                edit_patterns.append("偏好减少第一人称复数")

        # 更新风格特征（基于编辑后文本）
        self.extract_style_features(edited_text)

        # 累积编辑模式到profile
        if "edit_patterns" not in self.profile:
            self.profile["edit_patterns"] = []

        edit_record = {
            "timestamp": datetime.now().isoformat(),
            "section_name": section_name,
            "original_chars": original_chars,
            "edited_chars": edited_chars,
            "char_diff": char_diff,
            "sentence_diff": sentence_diff,
            "patterns_detected": edit_patterns,
        }
        self.profile["edit_patterns"].append(edit_record)

        # 保留最近50条编辑记录
        if len(self.profile["edit_patterns"]) > 50:
            self.profile["edit_patterns"] = self.profile["edit_patterns"][-50:]

        # 统计编辑模式频率
        pattern_frequency = {}
        for record in self.profile["edit_patterns"]:
            for pattern in record.get("patterns_detected", []):
                pattern_frequency[pattern] = pattern_frequency.get(pattern, 0) + 1
        self.profile["edit_pattern_frequency"] = pattern_frequency

        return {
            "char_diff": char_diff,
            "sentence_diff": sentence_diff,
            "patterns_detected": edit_patterns,
            "total_edit_records": len(self.profile["edit_patterns"]),
            "pattern_frequency": pattern_frequency,
        }

    def _apply_feature(self, agent_type: str, feature: str):
        """应用单个特征到共享档案"""
        pref = self.profile["user_style_preferences"]

        # 标点相关特征
        if "冒号" in feature and ("讨厌" in feature or "禁用" in feature or "删除" in feature):
            pref["hates_colon_in_body"] = True
        elif "冒号" in feature and ("允许" in feature or "保留" in feature):
            pref["hates_colon_in_body"] = False

        # 段落长度相关
        if "段落" in feature and "短" in feature:
            pref["prefers_short_paragraphs"] = True
        elif "段落" in feature and "长" in feature:
            pref["prefers_short_paragraphs"] = False

        # 禁止用语
        if "讨厌" in feature or "反感" in feature:
            for phrase in ["在新时代背景下", "具有重要的", "众所周知", "不言而喻"]:
                if phrase in feature and phrase not in pref["forbidden_phrases"]:
                    pref["forbidden_phrases"].append(phrase)

        # 理论偏好（v6.3.0 完成：实现理论名称提取逻辑）
        if "理论" in feature and "偏好" in agent_type:
            theories = self.profile["theoretical_preferences"]["preferred_theories"]
            import re
            # 匹配引号包裹的理论名
            quoted = re.findall(r'[「"\'](.*?)[」"\']', feature)
            # 匹配"XX理论"模式
            theory_pattern = re.findall(r'([\u4e00-\u9fa5]{2,8}理论)', feature)
            # 匹配已知理论库
            known_theories = [
                "行动者网络", "生命政治", "媒介化", "可供性", "框架理论",
                "议程设置", "使用与满足", "创新扩散", "知识沟", "沉默的螺旋",
                "数字劳动", "情感劳动", "隐性知识", "马克思主义新闻观",
                "嵌入性", "元问题", "统一真实观", "原型田野",
            ]
            known_matches = [t for t in known_theories if t in feature]
            extracted = list(set(quoted + theory_pattern + known_matches))
            for theory in extracted:
                if theory and theory not in theories:
                    theories.append(theory)
                    if len(theories) > 20:
                        theories.pop(0)

    def _apply_rule_update(self, agent_type: str, update: str):
        """应用规则更新"""
        pref = self.profile["user_style_preferences"]

        # 破折号容忍度更新
        if "破折号" in update and "容忍" in update:
            import re
            match = re.search(r'(\d+)', update)
            if match:
                pref["max_dash_tolerance"] = int(match.group(1))

    def get_instruction_context(self, agent_type: str) -> str:
        """为指定 agent 生成个性化指令上下文"""
        pref = self.profile["user_style_preferences"]
        parts = ["【学习反馈】"]

        if pref.get("hates_colon_in_body"):
            parts.append("⚠ 用户厌恶正文中的句中冒号，请严格避免。")
        if pref.get("prefers_short_paragraphs") is True:
            parts.append("⚠ 用户偏好短段落，建议控制在150-250字。")
        elif pref.get("prefers_short_paragraphs") is False:
            parts.append("⚠ 用户不排斥较长段落，可适当展开。")

        if pref.get("forbidden_phrases"):
            parts.append(f"⚠ 用户反感的用语: {', '.join(pref['forbidden_phrases'])}")

        if pref.get("max_dash_tolerance", 15) < 15:
            parts.append(f"⚠ 用户对破折号容忍度低: ≤{pref['max_dash_tolerance']}处")

        theories = self.profile["theoretical_preferences"].get("preferred_theories", [])
        if theories:
            parts.append(f"💡 用户偏好理论: {', '.join(theories[-3:])}")

        return "\n".join(parts)

    def get_summary(self) -> Dict:
        """获取共享学习档案摘要"""
        return {
            "style_preferences": {
                k: v for k, v in self.profile["user_style_preferences"].items()
                if v is not None
            },
            "theoretical_preferences": self.profile["theoretical_preferences"],
            "structural_preferences": self.profile["structural_preferences"],
            "learning_updates": len(self.profile["update_history"]),
            "last_updated": self.profile["last_updated"],
        }

    def reset(self):
        """重置学习档案为默认值"""
        self.profile = DEFAULT_SHARED_PROFILE.copy()
        self.save()

    # ========================================================================
    # v6.3.0 新增：6个文风特征提取方法（基于131篇CSSCI论文文风分析成果）
    # 数据来源：数据库scholar_analysis分析报告01-06
    # ========================================================================

    def extract_title_features(self, text: str) -> Dict[str, Any]:
        """提取标题特征（类型/结构/隐喻度）

        基于131篇论文标题分析：隐喻式/引语式/命题式/判断式四种类型

        Args:
            text: 全文文本（含标题行）

        Returns:
            标题特征字典
        """
        import re
        lines = text.strip().split('\n')
        title = ""
        for line in lines[:5]:
            line = line.strip().lstrip('#').strip()
            if line and len(line) > 5:
                title = line
                break

        if not title:
            return {"title_type": "unknown", "structure": "unknown", "metaphor_degree": 0}

        # 标题类型判定
        title_type = "judgment"
        if re.search(r'[「"\'].*?[」"\']', title):
            if any(q in title for q in ['？', '?']):
                title_type = "question"
            else:
                title_type = "quotation"
        elif any(m in title for m in ['隐喻', '河', '湖', '海', '桥', '摆渡', '蜂', '补丁', '脐带']):
            title_type = "metaphor"
        elif '：' in title or '——' in title:
            title_type = "compound"

        # 结构判定
        has_subtitle = bool(re.search(r'[：—]|（.*?）', title))
        structure = "subtitle" if has_subtitle else "single"

        # 隐喻度评分（0-3）
        metaphor_markers = ['隐喻', '河', '湖', '海', '桥', '摆渡', '蜂', '补丁',
                           '脐带', '脚手架', '凝视', '黑箱', '孤岛']
        metaphor_degree = min(3, sum(1 for m in metaphor_markers if m in title))

        # 长度
        title_length = len(title)

        return {
            "title": title,
            "title_type": title_type,
            "structure": structure,
            "has_subtitle": has_subtitle,
            "metaphor_degree": metaphor_degree,
            "title_length": title_length,
        }

    def extract_transition_features(self, text: str) -> Dict[str, Any]:
        """提取句子/段落过渡特征

        基于131篇论文分析：5种过渡方式+72个示例，避免5种硬转折反模式

        Args:
            text: 全文文本

        Returns:
            过渡特征字典
        """
        import re
        paragraphs = [p.strip() for p in text.split('\n') if p.strip()]

        # 句子级过渡词
        sentence_transitions = {
            "classical": 0,  # 文言过渡：亦/或/由此/然而/因而/综上
            "mechanical": 0,  # 机械连接：此外/另外/其次/再次/最后
            "semantic": 0,  # 语义衔接：这一/据此/由是/基于此/亦或
            "dialectical": 0,  # 辩证转折：然而/不过/尽管如此/然则
            "causal": 0,  # 因果推断：因此/可见/也就是说/据此
        }
        classical_words = ["亦", "或", "由此", "然而", "因而", "综上", "由是", "再者", "基于此", "亦或"]
        mechanical_words = ["此外", "另外", "其次", "再次", "最后", "首先", "第一", "第二"]
        semantic_words = ["这一", "据此", "换言之", "鉴于", "综上"]
        dialectical_words = ["然而", "不过", "尽管如此", "然则", "固然"]
        causal_words = ["因此", "可见", "也就是说", "据此", "由此"]

        for para in paragraphs:
            for word in classical_words:
                if word in para:
                    sentence_transitions["classical"] += 1
            for word in mechanical_words:
                if word in para:
                    sentence_transitions["mechanical"] += 1
            for word in semantic_words:
                if word in para:
                    sentence_transitions["semantic"] += 1
            for word in dialectical_words:
                if word in para:
                    sentence_transitions["dialectical"] += 1
            for word in causal_words:
                if word in para:
                    sentence_transitions["causal"] += 1

        # 段落开头多样性
        paragraph_openings = []
        for para in paragraphs[:30]:
            opening = para[:15] if len(para) > 15 else para
            paragraph_openings.append(opening)

        # 过渡多样性评分
        total_transitions = sum(sentence_transitions.values())
        transition_diversity = len([v for v in sentence_transitions.values() if v > 0])

        # 机械连接占比（越低越好）
        mechanical_ratio = (
            sentence_transitions["mechanical"] / total_transitions
            if total_transitions > 0 else 0
        )

        return {
            "sentence_transitions": sentence_transitions,
            "total_transitions": total_transitions,
            "transition_diversity": transition_diversity,
            "mechanical_ratio": round(mechanical_ratio, 3),
            "paragraph_count": len(paragraphs),
            "classical_ratio": round(
                sentence_transitions["classical"] / total_transitions, 3
            ) if total_transitions > 0 else 0,
        }

    def extract_argumentation_features(self, text: str) -> Dict[str, Any]:
        """提取论证逻辑特征

        基于131篇论文分析：演绎/归纳/辩证/实证四种论证类型

        Args:
            text: 全文文本

        Returns:
            论证逻辑特征字典
        """
        import re
        # 论证类型判定
        argument_type = "mixed"
        if re.search(r'从.*?到.*?(?:的|转变|转向)', text):
            argument_type = "dialectical"
        elif re.search(r'回归.*?元问题|回到.*?本体', text):
            argument_type = "deductive"
        elif re.search(r'访谈|编码|田野|受访者', text):
            argument_type = "inductive"
        elif re.search(r'回归|显著|假设|变量|样本', text):
            argument_type = "empirical"

        # 辩证对识别
        dialectical_pairs = []
        pair_patterns = [
            (r'赋权.*?控制', "赋权/控制"),
            (r'可见.*?不可见', "可见/不可见"),
            (r'部分.*?整体', "部分/整体"),
            (r'微观.*?宏观', "微观/宏观"),
            (r'理论.*?实践', "理论/实践"),
            (r'历史.*?现实', "历史/现实"),
            (r'个体.*?社会', "个体/社会"),
            (r'标准化.*?个性化', "标准化/个性化"),
        ]
        for pattern, name in pair_patterns:
            if re.search(pattern, text):
                dialectical_pairs.append(name)

        # 论证结构识别
        logic_chain = []
        if re.search(r'现象.*?机制.*?反思|现象呈现.*?机制揭示.*?理论提升', text):
            logic_chain.append("现象-机制-反思三段式")
        if re.search(r'理论.*?现实.*?路径|理论渊源.*?现实依据.*?提升路径', text):
            logic_chain.append("理论-现实-路径三段式")
        if re.search(r'概念界定.*?特征阐释.*?关系揭示.*?余论反思', text):
            logic_chain.append("概念建构四段式")
        if re.search(r'问题.*?方法.*?结论', text):
            logic_chain.append("问题-方法-结论三段式")

        # 判断句密度
        judgment_sentences = len(re.findall(r'[^。]*?(?:是|即|意味着|表明|揭示|说明)[^。]*?。', text))
        total_sentences = len(re.findall(r'。', text)) or 1
        judgment_density = round(judgment_sentences / total_sentences, 3)

        return {
            "argument_type": argument_type,
            "dialectical_pairs": dialectical_pairs,
            "logic_chain": logic_chain,
            "judgment_density": judgment_density,
            "has_dialectical_reasoning": len(dialectical_pairs) > 0,
        }

    def extract_metaphor_features(self, text: str) -> Dict[str, Any]:
        """提取隐喻特征（有机性/体系化）

        基于131篇论文分析：体系化隐喻贯穿全篇，非装饰性

        Args:
            text: 全文文本

        Returns:
            隐喻特征字典
        """
        import re
        # 隐喻词库（基于数据库论文实证）
        metaphor_categories = {
            "spatial": ["河", "湖", "海", "边疆", "中心", "边缘", "走廊", "场域", "田野", "黑箱", "孤岛"],
            "body": ["脐带", "补丁", "脚手架", "骨架", "血脉", "神经", "触角"],
            "mechanical": ["齿轮", "引擎", "枢纽", "桥梁", "摆渡", "转译", "中介"],
            "biological": ["蜂王", "工蜂", "生态", "共生", "寄生", "繁衍", "根系"],
            "visual": ["凝视", "镜像", "可见", "盲区", "聚焦", "折射", "透视"],
            "container": ["容器", "圈层", "茧房", "池", "网"],
        }

        metaphor_count = 0
        metaphor_types = []
        for category, words in metaphor_categories.items():
            category_count = 0
            for word in words:
                count = text.count(word)
                category_count += count
            if category_count > 0:
                metaphor_count += category_count
                metaphor_types.append(category)

        # 有机性评分（隐喻类别多样性，越高越体系化）
        organic_degree = len(metaphor_types)

        # 体系化判定（同一隐喻在文中多次出现）
        systematic_metaphors = []
        for category, words in metaphor_categories.items():
            for word in words:
                if text.count(word) >= 3:
                    systematic_metaphors.append(f"{word}({text.count(word)}次)")

        # 概念命名识别（引号包裹的创新概念）
        quoted_concepts = re.findall(r'[「"\'](.*?)[」"\']', text)
        concept_naming_count = len([c for c in quoted_concepts if 2 <= len(c) <= 12])

        return {
            "metaphor_count": metaphor_count,
            "metaphor_types": metaphor_types,
            "organic_degree": organic_degree,
            "systematic_metaphors": systematic_metaphors[:10],
            "concept_naming_count": concept_naming_count,
            "has_systematic_metaphor": len(systematic_metaphors) > 0,
        }

    def extract_paragraph_opening_features(self, text: str) -> Dict[str, Any]:
        """提取段落开头特征

        基于131篇论文分析：段落开头多样性≥6种，避免机械重复

        Args:
            text: 全文文本

        Returns:
            段落开头特征字典
        """
        import re
        paragraphs = [p.strip() for p in text.split('\n') if p.strip() and len(p.strip()) > 20]

        if not paragraphs:
            return {"opening_types": [], "diversity_score": 0, "mechanical_ratio": 1.0}

        # 段落开头分类
        opening_types = []
        for para in paragraphs[:50]:
            first_clause = para[:30]
            if re.match(r'^首先|^其次|^再次|^最后|^第一|^第二|^第三', first_clause):
                opening_types.append("ordinal")
            elif re.match(r'^此外|^另外|^然而|^因此|^综上|^由此', first_clause):
                opening_types.append("mechanical")
            elif re.match(r'^本文|^本研究|^我们', first_clause):
                opening_types.append("self_reference")
            elif re.match(r'^[「"\']', first_clause):
                opening_types.append("quotation")
            elif re.match(r'^\d+\.', first_clause):
                opening_types.append("numbered")
            elif re.search(r'[。！？]', first_clause[:15]):
                opening_types.append("short_judgment")
            elif re.match(r'^如果说|^假设|^倘若|^即使|^尽管', first_clause):
                opening_types.append("concessive")
            elif re.match(r'^为什么|^何以|^如何|^何为', first_clause):
                opening_types.append("question")
            else:
                opening_types.append("concept_anchor")

        # 多样性评分
        unique_types = len(set(opening_types))
        diversity_score = unique_types

        # 机械占比
        mechanical_count = opening_types.count("mechanical") + opening_types.count("ordinal")
        mechanical_ratio = round(mechanical_count / len(opening_types), 3)

        # 概念锚定占比（人类论文特征）
        concept_anchor_ratio = round(opening_types.count("concept_anchor") / len(opening_types), 3)

        return {
            "opening_types": opening_types,
            "unique_types": unique_types,
            "diversity_score": diversity_score,
            "mechanical_ratio": mechanical_ratio,
            "concept_anchor_ratio": concept_anchor_ratio,
            "total_paragraphs": len(paragraphs),
            "passes_diversity_check": diversity_score >= 6,
        }

    def extract_scholar_voice_profile(self, text: str, scholar_name: str = "") -> Dict[str, Any]:
        """提取学者声音画像

        基于131篇论文分析：15位学者差异化声音指纹

        Args:
            text: 全文文本
            scholar_name: 学者姓名（可选，用于匹配已知声音指纹）

        Returns:
            学者声音画像字典
        """
        # 已知学者声音指纹库（基于数据库分析报告01-06）
        scholar_fingerprints = {
            "黄阳坤": {"metaphor": "共现性/分布式道德", "method": "算法审计", "type": "computational"},
            "周葆华": {"metaphor": "出圈/折叠", "method": "多模态计算", "type": "computational_zhou"},
            "刘战伟": {"metaphor": "蜂王/工蜂", "method": "深度访谈", "type": "qualitative"},
            "雷紫雯": {"metaphor": "知识摆渡人/人类补丁", "method": "田野观察", "type": "digital_sociology"},
            "邓绍根": {"metaphor": "继承/突破", "method": "年度盘点", "type": "theoretical_deng"},
            "童兵": {"metaphor": "范畴认知", "method": "政策阐释", "type": "theoretical_tong"},
            "郑保卫": {"metaphor": "四问框架", "method": "历史代际梳理", "type": "theoretical_zheng"},
            "陈力丹": {"metaphor": "词源考证", "method": "多语言对照", "type": "theoretical_chen"},
            "周勇": {"metaphor": "元问题", "method": "哲学思辨", "type": "theoretical_zhouyong"},
            "禹卫华": {"metaphor": "三维度框架", "method": "数据挖掘", "type": "computational_yu"},
            "卜玉梅": {"metaphor": "原型田野", "method": "学科史梳理", "type": "qualitative_bu"},
            "支庭荣": {"metaphor": "嵌入性视角", "method": "理论思辨", "type": "theoretical_zhi"},
            "沈正赋": {"metaphor": "河-湖-海空间隐喻", "method": "历史脉络梳理", "type": "theoretical_shen"},
            "杨保军": {"metaphor": "统一真实观", "method": "概念建构", "type": "theoretical_yang"},
            "李兴博": {"metaphor": "年度盘点", "method": "综述研究", "type": "theoretical_li"},
        }

        # 综合提取各项特征
        style_features = self.extract_style_features(text)
        title_features = self.extract_title_features(text)
        transition_features = self.extract_transition_features(text)
        argumentation_features = self.extract_argumentation_features(text)
        metaphor_features = self.extract_metaphor_features(text)
        opening_features = self.extract_paragraph_opening_features(text)

        # 匹配已知学者指纹
        matched_fingerprint = None
        style_match_score = 0.0
        if scholar_name and scholar_name in scholar_fingerprints:
            matched_fingerprint = scholar_fingerprints[scholar_name]
            # 计算风格匹配度
            match_points = 0
            total_points = 5
            if matched_fingerprint["type"].startswith("theoretical"):
                if argumentation_features["argument_type"] in ["deductive", "dialectical"]:
                    match_points += 1
            if matched_fingerprint["type"].startswith("computational"):
                if argumentation_features["argument_type"] == "empirical":
                    match_points += 1
            if matched_fingerprint["type"].startswith("qualitative"):
                if argumentation_features["argument_type"] == "inductive":
                    match_points += 1
            if metaphor_features["has_systematic_metaphor"]:
                match_points += 1
            if opening_features["passes_diversity_check"]:
                match_points += 1
            if transition_features["classical_ratio"] > 0.1:
                match_points += 1
            if style_features.get("sentence_length_std", 0) >= 10.0:
                match_points += 1
            style_match_score = round(match_points / total_points, 3)

        return {
            "scholar_name": scholar_name,
            "matched_fingerprint": matched_fingerprint,
            "style_match_score": style_match_score,
            "voice_fingerprint": {
                "style": style_features,
                "title": title_features,
                "transitions": transition_features,
                "argumentation": argumentation_features,
                "metaphor": metaphor_features,
                "paragraph_opening": opening_features,
            },
            "available_scholars": list(scholar_fingerprints.keys()),
        }
