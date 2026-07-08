r"""
声音提取器 v6.3 — 从 PDF/Markdown 提取学者写作声音特征

功能：
  - 从 PDF 文件提取全文文本（通过 mcp_pdf-reader-mcp 的 read_pdf 工具）
  - 分析文本的声音特征（调用 SharedLearningProfile.extract_style_features）
  - 构建声音锚点段落（150-200字典型学者声音范本）
  - 批量提取并保存到 voice_library/ 目录
  - 加载声音库供 Narrator Agent 和 Polisher Agent 参考

使用方式：
  extractor = VoiceExtractor(
      pdf_dir=r"C:\Users\13067\.trae-cn\数据库\论文",
      voice_library_dir=r"...\voice_library"
  )
  extractor.batch_extract({
      "qualitative": ["paper1.pdf", "paper2.pdf"],
      "quantitative": ["paper3.pdf"],
  })
"""

import os
import re
from typing import Dict, List, Any, Optional
from datetime import datetime


class VoiceExtractor:
    """声音提取器：从 PDF 提取学者写作声音特征并构建声音锚点库"""

    def __init__(self, pdf_dir: str, voice_library_dir: str):
        """初始化声音提取器

        Args:
            pdf_dir: PDF 文件所在目录（如 C:\\Users\\13067\\.trae-cn\\数据库\\论文）
            voice_library_dir: 声音库目录（如 ...\\voice_library）
        """
        self.pdf_dir = pdf_dir
        self.voice_library_dir = voice_library_dir
        os.makedirs(self.voice_library_dir, exist_ok=True)

    def extract_from_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """从 PDF 提取全文文本

        通过 mcp_pdf-reader-mcp 的 read_pdf 工具读取 PDF 内容。
        注意：此方法在 Trae IDE 运行时由 MCP 工具替换，此处为占位实现。

        Args:
            pdf_path: PDF 文件路径

        Returns:
            包含 text（全文文本）、metadata（文件元信息）的字典
        """
        # 占位实现：实际运行时由 mcp_pdf-reader-mcp 的 read_pdf 工具替换
        filename = os.path.basename(pdf_path)
        return {
            "text": "",  # 占位：实际运行时填充 PDF 全文
            "metadata": {
                "filename": filename,
                "path": pdf_path,
                "extracted_at": datetime.now().isoformat(),
                "note": "占位实现，实际运行时由 mcp_pdf-reader-mcp 填充"
            }
        }

    def analyze_voice(self, text: str, research_type: str = "") -> Dict[str, Any]:
        """分析文本的声音特征

        调用 SharedLearningProfile.extract_style_features 提取声音特征，
        附加 research_type 标签。

        Args:
            text: 待分析的文本
            research_type: 研究类型标签（qualitative/quantitative/computational/mixed/interview_report/theoretical）

        Returns:
            声音特征字典，包含 style_features 和 research_type
        """
        try:
            from .shared_learning import SharedLearningProfile
            profile = SharedLearningProfile()
            features = profile.extract_style_features(text)
            features["research_type"] = research_type
            features["analyzed_at"] = datetime.now().isoformat()
            return features
        except Exception as e:
            return {
                "error": f"声音特征提取失败: {e}",
                "research_type": research_type
            }

    def build_voice_anchor(self, text: str, research_type: str) -> str:
        """从文本中提取 150-200 字的典型声音锚点段落

        优先选择包含该研究类型核心术语的段落。

        Args:
            text: 全文文本
            research_type: 研究类型

        Returns:
            150-200 字的声音锚点段落
        """
        # 研究类型核心术语映射
        type_keywords = {
            "qualitative": ["编码", "主题", "访谈", "田野", "叙事", "诠释", "意义"],
            "quantitative": ["回归", "显著", "假设", "变量", "问卷", "统计", "效应"],
            "computational": ["算法", "数据集", "模型", "训练", "预测", "网络", "计算"],
            "mixed": ["三角验证", "量化", "质化", "混合", "收敛", "互补", "整合"],
            "interview_report": ["受访者", "引语", "田野", "叙述", "场景", "对话", "原话"],
            "theoretical": ["概念", "理论", "命题", "范式", "谱系", "框架", "建构"],
        }

        keywords = type_keywords.get(research_type, [])
        paragraphs = [p.strip() for p in text.split('\n') if p.strip() and len(p.strip()) > 50]

        if not paragraphs:
            return ""

        # 按关键词命中数排序段落
        def keyword_count(p):
            return sum(p.count(kw) for kw in keywords)

        sorted_paragraphs = sorted(paragraphs, key=keyword_count, reverse=True)

        # 从关键词命中最多的段落中提取 150-200 字
        for para in sorted_paragraphs:
            if 150 <= len(para) <= 200:
                return para
            elif len(para) > 200:
                # 截取前 150-200 字（在句号处截断）
                for i in range(200, 150, -1):
                    if i < len(para) and para[i] in '。！？':
                        return para[:i + 1]
                return para[:200]
            elif len(para) < 150 and len(sorted_paragraphs) > 1:
                # 合并相邻短段落
                idx = paragraphs.index(para)
                if idx + 1 < len(paragraphs):
                    combined = para + paragraphs[idx + 1]
                    if 150 <= len(combined) <= 200:
                        return combined

        return sorted_paragraphs[0][:200] if sorted_paragraphs else ""

    def save_to_library(self, voice_anchor: str, features: Dict[str, Any],
                        research_type: str, source_pdf: str) -> str:
        """将声音锚点和特征保存到 voice_library/ 目录

        Args:
            voice_anchor: 声音锚点段落
            features: 声音特征字典
            research_type: 研究类型
            source_pdf: 源 PDF 文件路径

        Returns:
            保存的文件路径
        """
        source_stem = os.path.splitext(os.path.basename(source_pdf))[0]
        filename = f"{research_type}_{source_stem}.md"
        filepath = os.path.join(self.voice_library_dir, filename)

        type_names = {
            "qualitative": "质化研究",
            "quantitative": "量化研究",
            "computational": "计算社会科学",
            "mixed": "混合方法研究",
            "interview_report": "访谈报告",
            "theoretical": "理论建构研究",
        }

        content = f"""# {type_names.get(research_type, research_type)} 声音锚点库

## 元信息
- 研究类型：{research_type}
- 来源 PDF：{os.path.basename(source_pdf)}
- 提取日期：{datetime.now().strftime('%Y-%m-%d')}

## 声音锚点段落

{voice_anchor}

## 声音特征

"""

        # 写入特征
        for key, value in features.items():
            if isinstance(value, dict):
                content += f"### {key}\n"
                for subkey, subvalue in value.items():
                    content += f"- {subkey}: {subvalue}\n"
            else:
                content += f"- {key}: {value}\n"

        content += """
## 使用指引
供 Narrator Agent 和 Polisher Agent 在声音诊断和改写时参考。
此声音锚点从人类学者论文中提取，用于校准 AI 生成文本的写作风格。
"""

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        return filepath

    def batch_extract(self, research_type_map: Dict[str, List[str]]) -> Dict[str, int]:
        """批量提取声音锚点

        Args:
            research_type_map: 研究类型到 PDF 路径列表的映射
                如 {"qualitative": ["paper1.pdf", "paper2.pdf"], "quantitative": ["paper3.pdf"]}

        Returns:
            每种研究类型提取的声音锚点数量
        """
        results = {}
        for research_type, pdf_paths in research_type_map.items():
            count = 0
            for pdf_path in pdf_paths:
                # 构建完整路径
                if not os.path.isabs(pdf_path):
                    pdf_path = os.path.join(self.pdf_dir, pdf_path)

                if not os.path.exists(pdf_path):
                    print(f"警告：PDF 文件不存在: {pdf_path}")
                    continue

                # 提取文本
                extracted = self.extract_from_pdf(pdf_path)
                text = extracted.get("text", "")

                if not text or len(text) < 200:
                    print(f"警告：PDF 文本过短或为空: {pdf_path}")
                    continue

                # 分析声音特征
                features = self.analyze_voice(text, research_type)

                # 构建声音锚点
                voice_anchor = self.build_voice_anchor(text, research_type)

                if not voice_anchor:
                    print(f"警告：无法从 PDF 构建声音锚点: {pdf_path}")
                    continue

                # 保存到声音库
                saved_path = self.save_to_library(voice_anchor, features, research_type, pdf_path)
                print(f"已保存: {saved_path}")
                count += 1

            results[research_type] = count

        return results

    def load_voice_library(self) -> Dict[str, List[Dict[str, Any]]]:
        """加载声音库目录下所有声音锚点，按 research_type 分组返回

        Returns:
            研究类型到声音锚点列表的映射
        """
        library = {}
        if not os.path.exists(self.voice_library_dir):
            return library

        for filename in os.listdir(self.voice_library_dir):
            if not filename.endswith('.md'):
                continue

            filepath = os.path.join(self.voice_library_dir, filename)

            # 从文件名提取研究类型（格式：{research_type}_{source}.md）
            parts = filename.replace('.md', '').split('_', 1)
            if len(parts) < 2:
                continue
            research_type = parts[0]

            # 读取文件内容
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 提取声音锚点段落（在"## 声音锚点段落"和"## 声音特征"之间）
                anchor_match = re.search(
                    r'## 声音锚点段落\s*\n(.*?)\n## 声音特征',
                    content,
                    re.DOTALL
                )
                voice_anchor = anchor_match.group(1).strip() if anchor_match else ""

                entry = {
                    "filename": filename,
                    "filepath": filepath,
                    "research_type": research_type,
                    "voice_anchor": voice_anchor,
                    "content": content,
                }
                library.setdefault(research_type, []).append(entry)
            except Exception as e:
                print(f"警告：读取声音库文件失败: {filepath}, 错误: {e}")

        return library

    # ========================================================================
    # v6.3 新增：3个 markdown 提取方法（绕过 PDF 占位符，直接从 md 提取）
    # 理由：数据库scholar_analysis分析报告01-06已是md格式，无需PDF
    # ========================================================================

    def extract_from_md(self, md_path: str) -> Dict[str, Any]:
        """从 markdown 文件提取全文文本（绕过 PDF 占位符）

        Args:
            md_path: markdown 文件路径

        Returns:
            包含 text、metadata 的字典
        """
        with open(md_path, 'r', encoding='utf-8') as f:
            text = f.read()
        return {
            "text": text,
            "metadata": {
                "filename": os.path.basename(md_path),
                "path": md_path,
                "extracted_at": datetime.now().isoformat(),
                "source_format": "markdown",
            }
        }

    def batch_extract_from_md(self, md_dir: str, scholar_map: Dict[str, str]) -> Dict[str, int]:
        """批量从 markdown 文件提取声音锚点

        绕过 extract_from_pdf 占位符，直接处理 md 格式的分析报告。

        Args:
            md_dir: markdown 文件所在目录
            scholar_map: 学者名到研究类型的映射
                如 {"黄阳坤": "computational", "刘战伟": "qualitative"}

        Returns:
            每位学者提取的声音锚点数量
        """
        results = {}
        if not os.path.exists(md_dir):
            print(f"警告：目录不存在: {md_dir}")
            return results

        for scholar_name, research_type in scholar_map.items():
            count = 0
            # 遍历目录寻找包含学者名的 md 文件
            for filename in os.listdir(md_dir):
                if not filename.endswith('.md'):
                    continue
                filepath = os.path.join(md_dir, filename)
                try:
                    extracted = self.extract_from_md(filepath)
                    text = extracted.get("text", "")

                    # 检查文件是否包含该学者
                    if scholar_name not in text:
                        continue

                    if not text or len(text) < 200:
                        continue

                    # 分析声音特征
                    features = self.analyze_voice(text, research_type)

                    # 构建声音锚点
                    voice_anchor = self.build_voice_anchor(text, research_type)

                    if not voice_anchor:
                        continue

                    # 保存到声音库
                    saved_path = self.save_to_library(
                        voice_anchor, features, research_type, filepath
                    )
                    print(f"已保存 {scholar_name}: {saved_path}")
                    count += 1

                except Exception as e:
                    print(f"警告：处理文件失败: {filepath}, 错误: {e}")

            results[scholar_name] = count

        return results

    def generate_scholar_voice_anchor(
        self,
        scholar_name: str,
        analysis_md_path: str,
        exemplar_md_path: str
    ) -> str:
        """生成学者声音锚点文件

        整合分析报告（声音锚点段落推荐章节）与 style_exemplars.md 对应学者章节，
        生成符合 voice_library 统一模板的学者锚点文件。

        Args:
            scholar_name: 学者姓名
            analysis_md_path: 分析报告 md 文件路径（如 01_黄阳坤_文风分析.md）
            exemplar_md_path: style_exemplars.md 文件路径

        Returns:
            生成的学者锚点文件路径
        """
        # 读取分析报告
        analysis_text = ""
        if os.path.exists(analysis_md_path):
            with open(analysis_md_path, 'r', encoding='utf-8') as f:
                analysis_text = f.read()

        # 读取范本文件
        exemplar_text = ""
        if os.path.exists(exemplar_md_path):
            with open(exemplar_md_path, 'r', encoding='utf-8') as f:
                exemplar_text = f.read()

        # 提取声音锚点段落（分析报告中的"声音锚点段落推荐"章节）
        anchor_paragraphs = []
        anchor_match = re.search(
            r'声音锚点段落推荐(.*?)(?:## 六、句式模板库|## 句式模板|---|\Z)',
            analysis_text,
            re.DOTALL
        )
        if anchor_match:
            anchor_section = anchor_match.group(1)
            # 提取引用块（> 开头的段落）
            paragraph_pattern = r'(?:\*\*段落[一二三四五六七八九十]+?\*\*[^\n]*\n)?>([^\n]+(?:\n(?!>|\*\*|#)[^\n]+)*)'
            matches = re.findall(paragraph_pattern, anchor_section)
            anchor_paragraphs = [m.strip() for m in matches if m.strip()]

        # 提取标志性文风特征（从范本文件）
        features_text = ""
        # 在范本文件中查找学者章节
        scholar_pattern = rf'{re.escape(scholar_name)}[^\n]*\n(.*?)(?=\n## [一二三四五六七八九十]+、|\Z)'
        scholar_match = re.search(scholar_pattern, exemplar_text, re.DOTALL)
        if scholar_match:
            scholar_section = scholar_match.group(1)
            # 提取标志性文风特征表格
            features_match = re.search(
                r'标志性文风特征[^\n]*\n(.*?)(?:\n## |\n### |\Z)',
                scholar_section,
                re.DOTALL
            )
            if features_match:
                features_text = features_match.group(1).strip()

        # 构造输出文件
        filename = f"scholar_{scholar_name}.md"
        filepath = os.path.join(self.voice_library_dir, filename)

        content = f"""# {scholar_name} 声音锚点库

## 元信息
- 学者姓名：{scholar_name}
- 研究类型：自动识别
- 来源论文数：基于数据库scholar_analysis分析报告
- 提取日期：{datetime.now().strftime('%Y-%m-%d')}
- 数据来源：{os.path.basename(analysis_md_path)} + {os.path.basename(exemplar_md_path)}

## 学者概况
{scholar_name}的学术写作风格基于数据库CSSCI论文深度分析，详见分析报告。

## 标志性文风特征
{features_text if features_text else '详见 style_exemplars.md 对应章节'}

## 声音锚点段落（真实摘录）

"""
        # 写入声音锚点段落
        for i, para in enumerate(anchor_paragraphs[:5], 1):
            content += f"### 段落{['一', '二', '三', '四', '五'][i-1]}\n> {para}\n\n"

        if not anchor_paragraphs:
            content += "### 段落一\n> （请从分析报告中手动提取声音锚点段落）\n\n"

        content += f"""## 句式模板库
详见 style_exemplars.md 中 {scholar_name} 对应章节的句式模板。

## 适用研究类型映射
- 主类型：自动识别
- 兼容类型：详见 style_exemplars.md
- 不适用类型：详见 style_exemplars.md

## 使用指引
供 Narrator Agent 和 Polisher Agent 在声音诊断和改写时参考。
本锚点由 VoiceExtractor.generate_scholar_voice_anchor() 自动生成，
内容整合自分析报告与 style_exemplars.md v3.0。
"""

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        return filepath


if __name__ == "__main__":
    # 使用示例
    extractor = VoiceExtractor(
        pdf_dir=r"C:\Users\13067\.trae-cn\数据库\论文",
        voice_library_dir=os.path.join(os.path.dirname(__file__), "..", "voice_library")
    )

    # 加载现有声音库
    library = extractor.load_voice_library()
    for rtype, entries in library.items():
        print(f"{rtype}: {len(entries)} 个声音锚点")
