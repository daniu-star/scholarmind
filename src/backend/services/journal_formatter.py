"""
ScholarMind 期刊格式化器
基于 python-docx 实现 4 种期刊格式：
  - gjxwj   国际新闻界
  - xwycbyj 新闻与传播研究
  - xwahz   新闻爱好者
  - generic 通用学术格式
"""
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
import io


class BaseFormatter:
    """格式化器基类：提供 Markdown → Word 的基础转换"""

    # 默认正文字体
    body_font_name = 'SimSun'
    body_font_size = 12
    # 默认标题字体
    heading_font_name = 'SimHei'

    def format(self, content, title=None, author=None):
        doc = Document()
        self.setup_page(doc)
        if title:
            self.add_title(doc, title)
        if author:
            self.add_author(doc, author)
        self.parse_markdown(doc, content)
        self.add_references_section(doc)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

    def setup_page(self, doc):
        """A4 页面，标准页边距"""
        for section in doc.sections:
            section.page_width = Cm(21)
            section.page_height = Cm(29.7)
            section.top_margin = Cm(2.54)
            section.bottom_margin = Cm(2.54)
            section.left_margin = Cm(3.17)
            section.right_margin = Cm(3.17)

    def add_title(self, doc, title):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(title)
        run.font.size = Pt(16)
        run.font.name = self.heading_font_name
        run.bold = True

    def add_author(self, doc, author):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(author)
        run.font.size = Pt(12)
        run.font.name = self.body_font_name

    def parse_markdown(self, doc, content):
        """解析 Markdown 文本并写入 doc"""
        lines = content.split('\n')
        in_code_block = False
        code_lines = []

        for line in lines:
            # 处理代码块
            if line.strip().startswith('```'):
                if in_code_block:
                    # 结束代码块
                    code_text = '\n'.join(code_lines)
                    p = doc.add_paragraph(code_text)
                    for run in p.runs:
                        run.font.name = 'Consolas'
                        run.font.size = Pt(10.5)
                    code_lines = []
                    in_code_block = False
                else:
                    in_code_block = True
                continue
            if in_code_block:
                code_lines.append(line)
                continue

            stripped = line.strip()
            if not stripped:
                continue

            # 标题
            if stripped.startswith('### '):
                p = doc.add_heading(stripped[4:], level=3)
                self._style_heading(p, self.heading_font_name)
            elif stripped.startswith('## '):
                p = doc.add_heading(stripped[3:], level=2)
                self._style_heading(p, self.heading_font_name)
            elif stripped.startswith('# '):
                p = doc.add_heading(stripped[2:], level=1)
                self._style_heading(p, self.heading_font_name)
            elif stripped.startswith('> '):
                # 引用块
                p = doc.add_paragraph(stripped[2:])
                p.paragraph_format.left_indent = Cm(1)
                for run in p.runs:
                    run.font.name = self.body_font_name
                    run.font.size = Pt(self.body_font_size)
                    run.italic = True
            elif stripped.startswith('- ') or stripped.startswith('* ') or stripped.startswith('+ '):
                # 无序列表
                p = doc.add_paragraph(stripped[2:], style='List Bullet')
                for run in p.runs:
                    run.font.name = self.body_font_name
                    run.font.size = Pt(self.body_font_size)
            else:
                # 普通段落（处理行内 Markdown）
                p = doc.add_paragraph()
                self._add_inline_markdown(p, stripped)

    def _style_heading(self, paragraph, font_name):
        """统一设置标题段落的字体"""
        for run in paragraph.runs:
            run.font.name = font_name

    def _add_inline_markdown(self, paragraph, text):
        """处理行内 Markdown：**粗体**、*斜体*、`代码`、[链接](url)"""
        import re
        # 简单解析：按顺序匹配粗体、斜体、代码、链接
        pattern = re.compile(
            r'(\*\*([^*]+)\*\*)'      # **粗体**
            r'|(\*([^*]+)\*)'          # *斜体*
            r'|(`([^`]+)`)'            # `代码`
            r'|(\[([^\]]+)\]\([^)]+\))' # [文本](链接)
        )
        last = 0
        for m in pattern.finditer(text):
            # 添加匹配前的普通文本
            if m.start() > last:
                run = paragraph.add_run(text[last:m.start()])
                run.font.name = self.body_font_name
                run.font.size = Pt(self.body_font_size)

            if m.group(1):  # 粗体
                run = paragraph.add_run(m.group(2))
                run.font.name = self.body_font_name
                run.font.size = Pt(self.body_font_size)
                run.bold = True
            elif m.group(3):  # 斜体
                run = paragraph.add_run(m.group(4))
                run.font.name = self.body_font_name
                run.font.size = Pt(self.body_font_size)
                run.italic = True
            elif m.group(5):  # 代码
                run = paragraph.add_run(m.group(6))
                run.font.name = 'Consolas'
                run.font.size = Pt(10.5)
            elif m.group(7):  # 链接
                run = paragraph.add_run(m.group(8))
                run.font.name = self.body_font_name
                run.font.size = Pt(self.body_font_size)
                run.font.color.rgb = None

            last = m.end()

        # 添加剩余文本
        if last < len(text):
            run = paragraph.add_run(text[last:])
            run.font.name = self.body_font_name
            run.font.size = Pt(self.body_font_size)

    def add_references_section(self, doc):
        """参考文献章节处理（子类可覆盖）"""
        pass


class GuojiXinwenjieFormatter(BaseFormatter):
    """国际新闻界格式：较宽的左右页边距"""
    body_font_name = 'SimSun'
    heading_font_name = 'SimHei'

    def setup_page(self, doc):
        super().setup_page(doc)
        for section in doc.sections:
            section.left_margin = Cm(3.5)
            section.right_margin = Cm(3.5)


class XwycbyjFormatter(BaseFormatter):
    """新闻与传播研究格式：较大的上下页边距"""
    body_font_name = 'SimSun'
    heading_font_name = 'SimHei'

    def setup_page(self, doc):
        super().setup_page(doc)
        for section in doc.sections:
            section.top_margin = Cm(3)
            section.bottom_margin = Cm(3)


class XwahzFormatter(BaseFormatter):
    """新闻爱好者格式：使用默认页边距"""
    body_font_name = 'SimSun'
    heading_font_name = 'SimHei'


class GenericFormatter(BaseFormatter):
    """通用学术格式：使用默认页边距"""
    body_font_name = 'SimSun'
    heading_font_name = 'SimHei'


class JournalFormatter:
    """期刊格式化器工厂"""
    _formatters = {
        'gjxwj': GuojiXinwenjieFormatter,
        'xwycbyj': XwycbyjFormatter,
        'xwahz': XwahzFormatter,
        'generic': GenericFormatter,
    }

    @classmethod
    def get_formatter(cls, style):
        """获取指定期刊的格式化器实例"""
        formatter_cls = cls._formatters.get(style, GenericFormatter)
        return formatter_cls()

    @classmethod
    def list_styles(cls):
        """列出所有支持的期刊格式"""
        return list(cls._formatters.keys())
