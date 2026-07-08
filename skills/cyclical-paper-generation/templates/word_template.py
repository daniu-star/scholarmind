"""
Word生成模板 - 《新闻与传播研究》格式 v1.0

使用 python-docx 库生成符合《新闻与传播研究》格式规范的Word文档。
支持：A4页面（34行×36字）、标题层级、脚注、三线表、图表插入、参考文献。

依赖：pip install python-docx
"""

from docx import Document
from docx.shared import Pt, Cm, Inches, Emu, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from lxml import etree
import os


# =============================================================================
# v6.0 新增：字体安全辅助函数
# =============================================================================

def _set_font_safe(run, east_asian: str = "宋体", western: str = "Times New Roman",
                    size_pt: float = 10.5, bold: bool = False):
    """安全设置字体：同时设置东亚字体、西文字体、大小、加粗"""
    run.font.size = Pt(size_pt)
    run.bold = bold
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = etree.SubElement(rPr, qn("w:rFonts"))
    rFonts.set(qn("w:eastAsia"), east_asian)
    rFonts.set(qn("w:ascii"), western)
    rFonts.set(qn("w:hAnsi"), western)
    run.font.name = east_asian


# =============================================================================
# v7.4 新增：弯引号字符规范——写入前自动将直引号替换为弯引号
# =============================================================================

# 直引号 → 弯引号映射（U+0022/U+0027 → U+201C/U+201D / U+2018/U+2019）
_STRAIGHT_DOUBLE = '"'   # U+0022
_STRAIGHT_SINGLE = "'"   # U+0027
_CURLY_DOUBLE_OPEN = "\u201C"   # "
_CURLY_DOUBLE_CLOSE = "\u201D"  # "
_CURLY_SINGLE_OPEN = "\u2018"   # '
_CURLY_SINGLE_CLOSE = "\u2019"  # '


def _normalize_quotes_in_text(text: str) -> str:
    """
    将文本中的直引号自动替换为弯引号（开-闭交替策略）。

    替换规则：
        - 直双引号 " (U+0022) → 开引号 " (U+201C) / 闭引号 " (U+201D) 交替
        - 直单引号 ' (U+0027) → 开引号 ' (U+2018) / 闭引号 ' (U+2019) 交替

    嵌套规则（参考数据库C刊论文）：
        - 外层用双引号（""），内层用单引号（''）
        - 同一对引号内，第一个为开引号，第二个为闭引号

    Args:
        text: 待处理的文本（正文、脚注、表格、标题等）

    Returns:
        替换后的文本（仅含弯引号）
    """
    if not text:
        return text

    result = []
    double_open = True   # 下一个双引号是否为开引号
    single_open = True   # 下一个单引号是否为开引号

    for ch in text:
        if ch == _STRAIGHT_DOUBLE:
            if double_open:
                result.append(_CURLY_DOUBLE_OPEN)
            else:
                result.append(_CURLY_DOUBLE_CLOSE)
            double_open = not double_open
        elif ch == _STRAIGHT_SINGLE:
            if single_open:
                result.append(_CURLY_SINGLE_OPEN)
            else:
                result.append(_CURLY_SINGLE_CLOSE)
            single_open = not single_open
        else:
            result.append(ch)

    return "".join(result)


def add_normalized_run(para, text: str, *args, **kwargs):
    """
    向段落添加 run，并自动将文本中的直引号替换为弯引号。

    用法（替代 para.add_run(text)）：
        run = add_normalized_run(para, "概念"共现性"的失落")
        _set_font_safe(run, ...)

    Args:
        para: docx Paragraph 对象
        text: 待写入文本
        *args, **kwargs: 传递给 para.add_run 的额外参数

    Returns:
        Run 对象（已写入弯引号规范化的文本）
    """
    normalized = _normalize_quotes_in_text(text)
    return para.add_run(normalized, *args, **kwargs)


# =============================================================================
# 一、全局配置
# =============================================================================

# 页面设置
PAGE_CONFIG = {
    "width": Cm(21.0),       # A4 宽度
    "height": Cm(29.7),      # A4 高度
    "top": Cm(2.54),         # 上边距
    "bottom": Cm(2.54),      # 下边距
    "left": Cm(3.17),        # 左边距
    "right": Cm(3.17),       # 右边距
}

# 字体配置
FONT_CONFIG = {
    "body": {"name": "宋体", "size": Pt(10.5), "line_spacing": 1.5},       # 正文五号
    "heading1": {"name": "黑体", "size": Pt(16), "bold": True, "align": WD_ALIGN_PARAGRAPH.CENTER},   # 三号
    "heading2": {"name": "黑体", "size": Pt(14), "bold": True, "align": WD_ALIGN_PARAGRAPH.LEFT},     # 四号
    "heading3": {"name": "黑体", "size": Pt(12), "bold": True, "align": WD_ALIGN_PARAGRAPH.LEFT},     # 小四号
    "heading4": {"name": "宋体", "size": Pt(10.5), "bold": False, "align": WD_ALIGN_PARAGRAPH.LEFT},  # 五号
    "footnote": {"name": "宋体", "size": Pt(9), "line_spacing": 1.0},       # 小五号
    "table_title": {"name": "黑体", "size": Pt(10.5), "bold": True},         # 表题
    "table_content": {"name": "宋体", "size": Pt(9)},                        # 表内容
    "table_note": {"name": "宋体", "size": Pt(8)},                           # 表注
    "figure_title": {"name": "宋体", "size": Pt(10.5)},                      # 图题
}

# 三线表边框
TABLE_BORDER = {
    "top": {"sz": "12", "val": "single", "color": "000000"},      # 顶线 1.5pt (粗)
    "bottom": {"sz": "12", "val": "single", "color": "000000"},   # 底线 1.5pt (粗)
    "insideH": {"sz": "4", "val": "single", "color": "000000"},   # 栏目线 0.5pt (细)
}


# =============================================================================
# 二、文档初始化
# =============================================================================

def create_document() -> Document:
    """创建并初始化文档，设置页面和默认样式"""
    doc = Document()

    # --- 页面设置 ---
    section = doc.sections[0]
    section.page_width = PAGE_CONFIG["width"]
    section.page_height = PAGE_CONFIG["height"]
    section.top_margin = PAGE_CONFIG["top"]
    section.bottom_margin = PAGE_CONFIG["bottom"]
    section.left_margin = PAGE_CONFIG["left"]
    section.right_margin = PAGE_CONFIG["right"]

    # --- v6.0 设置默认字体（增强安全字体设置，防止引号回退到西文） ---
    style = doc.styles["Normal"]
    style.font.name = FONT_CONFIG["body"]["name"]
    style.font.size = FONT_CONFIG["body"]["size"]
    rPr = style.element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        from lxml import etree
        rFonts = etree.SubElement(rPr, qn("w:rFonts"))
    rFonts.set(qn("w:eastAsia"), FONT_CONFIG["body"]["name"])
    rFonts.set(qn("w:ascii"), "Times New Roman")
    rFonts.set(qn("w:hAnsi"), "Times New Roman")
    style.paragraph_format.line_spacing = FONT_CONFIG["body"]["line_spacing"]

    return doc


# =============================================================================
# v6.0 新增：真实 Word 脚注支持（OOXML 底层操作）
# =============================================================================

def add_real_footnote(para, footnote_text, footnote_id):
    """
    向段落添加真正的 Word 脚注（使用 OOXML w:footnoteReference）。

    参数:
        para: docx Paragraph 对象
        footnote_text: 脚注文本内容
        footnote_id: 脚注 ID（必须连续且 ≥ 1）
    """
    from lxml import etree
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part

    # 1. 段落内插入脚注引用标记
    run = para.add_run()
    footnote_ref = etree.SubElement(run._element, qn("w:footnoteReference"))
    footnote_ref.set(qn("w:id"), str(footnote_id))

    # 2. 获取或创建 footnotes.xml
    document = para.part.document
    try:
        footnotes_part = document.part.footnotes_part
    except AttributeError:
        # 首次使用脚注，创建 footnotes.xml 部分
        footnotes_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
            ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<w:footnote w:type="separator" w:id="-1">'
            '<w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
            '<w:footnote w:type="continuationSeparator" w:id="0">'
            '<w:p><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>'
            '</w:footnotes>'
        )
        footnotes_part = Part(
            PackURI("/word/footnotes.xml"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
            footnotes_xml.encode("utf-8"),
            document.part.package,
        )
        document.part.relate_to(footnotes_part, RT.FOOTNOTES)

    # 3. 添加脚注内容（w:footnote 元素）
    footnote = etree.SubElement(footnotes_part.element, qn("w:footnote"))
    footnote.set(qn("w:id"), str(footnote_id))

    p = etree.SubElement(footnote, qn("w:p"))
    r = etree.SubElement(p, qn("w:r"))
    rPr = etree.SubElement(r, qn("w:rPr"))
    rStyle = etree.SubElement(rPr, qn("w:rStyle"))
    rStyle.set(qn("w:val"), "FootnoteReference")
    # 脚注编号数字：西文正文字体(Times New Roman)、小五号(9pt)、上标
    rFonts_num = etree.SubElement(rPr, qn("w:rFonts"))
    rFonts_num.set(qn("w:eastAsia"), FONT_CONFIG["body"]["name"])
    rFonts_num.set(qn("w:ascii"), "Times New Roman")
    rFonts_num.set(qn("w:hAnsi"), "Times New Roman")
    sz_num = etree.SubElement(rPr, qn("w:sz"))
    sz_num.set(qn("w:val"), "18")  # 9pt 小五号
    szCs_num = etree.SubElement(rPr, qn("w:szCs"))
    szCs_num.set(qn("w:val"), "18")
    vertAlign_num = etree.SubElement(rPr, qn("w:vertAlign"))
    vertAlign_num.set(qn("w:val"), "superscript")
    etree.SubElement(r, qn("w:footnoteRef"))

    r2 = etree.SubElement(p, qn("w:r"))
    rPr2 = etree.SubElement(r2, qn("w:rPr"))
    rFonts = etree.SubElement(rPr2, qn("w:rFonts"))
    rFonts.set(qn("w:eastAsia"), FONT_CONFIG["body"]["name"])
    sz = etree.SubElement(rPr2, qn("w:sz"))
    sz.set(qn("w:val"), "18")  # 9pt
    t = etree.SubElement(r2, qn("w:t"))
    # ★v7.4：脚注文本写入前自动将直引号替换为弯引号
    t.text = " " + _normalize_quotes_in_text(footnote_text)
    t.set(qn("xml:space"), "preserve")


def enforce_all_fonts(doc):
    """
    审查并修复文档中所有 run 的字体设置（含正文与脚注）。
    确保中文引号使用宋体，西文使用 Times New Roman。
    返回修复的 run 数量。

    v7.3 修复：增加对 footnotes.xml 中 run 的字体检查，
    防止脚注内容中的中文引号回退到西文字体。
    """
    fixed = 0

    def _fix_run_element(run_element):
        """修复单个 w:r 元素的字体设置"""
        nonlocal fixed
        rPr = run_element.find(qn("w:rPr"))
        if rPr is None:
            return
        rFonts = rPr.find(qn("w:rFonts"))
        if rFonts is not None:
            changed = False
            if rFonts.get(qn("w:eastAsia")) is None:
                rFonts.set(qn("w:eastAsia"), FONT_CONFIG["body"]["name"])
                changed = True
            if rFonts.get(qn("w:ascii")) is None:
                rFonts.set(qn("w:ascii"), "Times New Roman")
                changed = True
            if rFonts.get(qn("w:hAnsi")) is None:
                rFonts.set(qn("w:hAnsi"), "Times New Roman")
                changed = True
            if changed:
                fixed += 1

    # 1. 检查正文 paragraphs 中的 run
    for para in doc.paragraphs:
        for run in para.runs:
            rPr = run._element.rPr
            if rPr is not None:
                rFonts = rPr.find(qn("w:rFonts"))
                if rFonts is not None:
                    if rFonts.get(qn("w:eastAsia")) is None:
                        rFonts.set(qn("w:eastAsia"), FONT_CONFIG["body"]["name"])
                        fixed += 1
                    if rFonts.get(qn("w:ascii")) is None:
                        rFonts.set(qn("w:ascii"), "Times New Roman")
                    if rFonts.get(qn("w:hAnsi")) is None:
                        rFonts.set(qn("w:hAnsi"), "Times New Roman")

    # 2. 检查 footnotes.xml 中的 run（v7.3 新增）
    try:
        footnotes_part = doc.part.footnotes_part
        if footnotes_part is not None:
            for fn in footnotes_part.element.findall(qn("w:footnote")):
                fid = fn.get(qn("w:id"))
                if fid and int(fid) >= 0:
                    for p in fn.findall(qn("w:p")):
                        for r in p.findall(qn("w:r")):
                            _fix_run_element(r)
    except AttributeError:
        pass

    # 3. 检查表格中的 run（v7.3 新增）
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    for run in para.runs:
                        rPr = run._element.rPr
                        if rPr is not None:
                            rFonts = rPr.find(qn("w:rFonts"))
                            if rFonts is not None:
                                if rFonts.get(qn("w:eastAsia")) is None:
                                    rFonts.set(qn("w:eastAsia"), FONT_CONFIG["body"]["name"])
                                    fixed += 1

    return fixed


# =============================================================================
# v7.3 新增：脚注内容完整性验证与安全脚注生成
# =============================================================================

import re as _re

# 脚注必填字段定义（按引用类型分类）
FOOTNOTE_REQUIRED_FIELDS = {
    "chinese_journal": {
        "author": r"([一-鿿]{2,4})",
        "title": r"《([^》]+)》",
        "journal": r"《([^》]+)》",
        "year": r"(\d{4})",
        "issue": r"第(\d+)期",
        "pages": r"第([\d\-]+)页",
    },
    "chinese_book": {
        "author": r"([一-鿿]{2,4})",
        "title": r"《([^》]+)》",
        "place": r"([\u4e00-\u9fa5]{2,4})：",
        "publisher": r"：([\u4e00-\u9fa5\w]+出版社)",
        "year": r"(\d{4})",
    },
    "english_journal": {
        "author": r"([A-Z][a-z]+,\s[A-Z]\.)",
        "title": r'"([^"]+)"',
        "journal": r"\*([^*]+)\*",
        "year": r"(\d{4})",
        "pages": r"pp\.\s([\d\-]+)",
    },
    "english_book": {
        "author": r"([A-Z][a-z]+,\s[A-Z]\.)",
        "title": r"\*([^*]+)\*",
        "place": r"([A-Z][a-z]+):",
        "publisher": r":\s([\w\s]+),",
        "year": r"(\d{4})",
    },
}


def detect_footnote_type(footnote_text: str) -> str:
    """
    根据脚注文本特征判断引用类型。

    返回: "chinese_journal" | "chinese_book" | "english_journal" | "english_book" | "unknown"
    """
    text = footnote_text.strip()
    # 中文期刊：含"第X期"或"年第X期"
    if _re.search(r"\d{4}年第\d+期", text) or _re.search(r"第\d+期", text):
        if _re.search(r"[一-鿿]", text):
            return "chinese_journal"
    # 中文著作：含"出版社"
    if _re.search(r"出版社", text):
        return "chinese_book"
    # 英文期刊：含 "vol." "no." "pp."
    if _re.search(r'(vol\.|no\.)', text, _re.IGNORECASE):
        return "english_journal"
    # 英文著作：含 "*" 斜体标记
    if _re.search(r'\*[^*]+\*', text):
        return "english_book"
    # 中文期刊（无期号但有页码）
    if _re.search(r"第[\d\-]+页", text) and _re.search(r"[一-鿿]", text):
        return "chinese_journal"
    # 默认
    if _re.search(r"[一-鿿]", text):
        return "chinese_journal"
    return "unknown"


def extract_footnote_fields(footnote_text: str) -> dict:
    """
    从脚注文本中提取结构化字段。

    返回字典: {type, fields: {author, title, journal, year, ...}, missing: [缺失字段名]}
    """
    fn_type = detect_footnote_type(footnote_text)
    fields = {}
    missing = []

    if fn_type == "unknown":
        return {"type": "unknown", "fields": {}, "missing": ["无法识别引用类型"]}

    patterns = FOOTNOTE_REQUIRED_FIELDS.get(fn_type, {})
    for field_name, pattern in patterns.items():
        match = _re.search(pattern, footnote_text)
        if match:
            fields[field_name] = match.group(1)
        else:
            missing.append(field_name)

    return {"type": fn_type, "fields": fields, "missing": missing}


def validate_footnote_content(footnote_text: str) -> dict:
    """
    验证脚注内容的完整性。

    检查项：
    1. 文本非空且长度合理（≥10字符）
    2. 必填字段齐全（作者、标题、期刊/出版社、年份、页码）
    3. 无乱码（无连续不可读字符）
    4. 无占位符（如"..."、"待补充"、"XXX"）

    返回: {passed, issues, fields, missing}
    """
    issues = []
    text = footnote_text.strip()

    # 1. 非空检查
    if not text or len(text) < 10:
        issues.append("脚注内容过短（<10字符），可能为空或残缺")
        return {"passed": False, "issues": issues, "fields": {}, "missing": []}

    # 2. 乱码检测：连续非打印字符或替换字符
    if "�" in text or "\ufffd" in text:
        issues.append("脚注含乱码字符（U+FFFD）")
    # 连续3个以上非中文非英文非数字非标点字符
    garbled = _re.findall(r"[^\u4e00-\u9fa5a-zA-Z0-9\s《》""''.,;:!?()（）\-—–/\d]", text)
    if len(garbled) > 5:
        issues.append(f"脚注含{len(garbled)}个异常字符，可能为乱码")

    # 3. 占位符检测
    placeholders = ["...", "。。。", "待补充", "XXX", "xxx", "待填写",
                   "此处填写", "占位符", "placeholder", "TBD", "TODO"]
    for ph in placeholders:
        if ph in text:
            issues.append(f"脚注含占位符：{ph}")

    # 4. 字段完整性检查
    result = extract_footnote_fields(text)
    fn_type = result["type"]
    fields = result["fields"]
    missing = result["missing"]

    if fn_type == "unknown":
        issues.append("无法识别引用类型，脚注格式不符合任何已知规范")
    else:
        # 关键字段缺失检查
        critical_fields = {
            "chinese_journal": ["author", "title", "journal", "year"],
            "chinese_book": ["author", "title", "publisher", "year"],
            "english_journal": ["author", "title", "journal", "year"],
            "english_book": ["author", "title", "year"],
        }
        critical = critical_fields.get(fn_type, [])
        for cf in critical:
            if cf in missing:
                issues.append(f"关键字段缺失：{cf}")

    passed = len(issues) == 0
    return {
        "passed": passed,
        "issues": issues,
        "type": fn_type,
        "fields": fields,
        "missing": missing,
    }


def add_footnote_with_validation(para, footnote_text: str, footnote_id: int) -> dict:
    """
    生成脚注并自动验证内容完整性。

    若脚注内容验证失败，仍会插入脚注但返回验证报告，
    调用方可根据报告决定是否触发回滚或重试。

    参数:
        para: docx Paragraph 对象
        footnote_text: 脚注文本内容
        footnote_id: 脚注 ID（必须连续且 ≥ 1）

    返回: {inserted: bool, validation: dict}
    """
    # 先验证内容
    validation = validate_footnote_content(footnote_text)

    # 插入真实 OOXML 脚注
    try:
        add_real_footnote(para, footnote_text, footnote_id)
        inserted = True
    except Exception as e:
        inserted = False
        validation["issues"].append(f"脚注插入失败：{str(e)}")
        validation["passed"] = False

    return {"inserted": inserted, "validation": validation}


def get_all_footnote_texts(doc) -> list:
    """
    提取文档中所有脚注的文本内容。

    返回: [{id, text, validation}]
    """
    results = []
    try:
        footnotes_part = doc.part.footnotes_part
        if footnotes_part is None:
            return results
        for fn in footnotes_part.element.findall(qn("w:footnote")):
            fid = fn.get(qn("w:id"))
            if not fid or int(fid) < 0:
                continue
            txt = "".join(
                r.text or ""
                for p in fn.findall(qn("w:p"))
                for r in p.findall(".//" + qn("w:t"))
            )
            validation = validate_footnote_content(txt)
            results.append({
                "id": int(fid),
                "text": txt,
                "validation": validation,
            })
    except AttributeError:
        pass
    return results


def validate_all_footnotes(doc) -> dict:
    """
    验证文档中所有脚注的完整性和格式。

    返回: {total, valid, invalid, details, passed}
    """
    footnotes = get_all_footnote_texts(doc)
    total = len(footnotes)
    valid = sum(1 for fn in footnotes if fn["validation"]["passed"])
    invalid = total - valid
    details = []
    for fn in footnotes:
        if not fn["validation"]["passed"]:
            details.append({
                "id": fn["id"],
                "text_preview": fn["text"][:80],
                "issues": fn["validation"]["issues"],
            })
    return {
        "total": total,
        "valid": valid,
        "invalid": invalid,
        "details": details,
        "passed": invalid == 0 and total > 0,
    }


def format_footnote_text(ref_type: str, **fields) -> str:
    """
    根据引用类型和结构化字段生成规范的脚注文本。

    参数:
        ref_type: "chinese_journal" | "chinese_book" | "english_journal" | "english_book"
        fields: 对应类型的字段（author, title, journal, year, etc.）

    返回: 格式化的脚注文本字符串

    示例:
        format_footnote_text("chinese_journal",
            author="胡泳", title="数字鸿沟的再思考",
            journal="新闻与传播研究", year="2020", issue="3", pages="5-23")
        → "胡泳：《数字鸿沟的再思考》，《新闻与传播研究》2020年第3期，第5-23页。"
    """
    if ref_type == "chinese_journal":
        author = fields.get("author", "")
        title = fields.get("title", "")
        journal = fields.get("journal", "")
        year = fields.get("year", "")
        issue = fields.get("issue", "")
        pages = fields.get("pages", "")
        text = f"{author}：《{title}》，《{journal}》{year}年第{issue}期，第{pages}页。"
        return text

    elif ref_type == "chinese_book":
        author = fields.get("author", "")
        title = fields.get("title", "")
        place = fields.get("place", "")
        publisher = fields.get("publisher", "")
        year = fields.get("year", "")
        page = fields.get("page", "")
        page_text = f"，第{page}页" if page else ""
        text = f"{author}：《{title}》，{place}：{publisher}，{year}年{page_text}。"
        return text

    elif ref_type == "english_journal":
        author = fields.get("author", "")
        title = fields.get("title", "")
        journal = fields.get("journal", "")
        volume = fields.get("volume", "")
        issue = fields.get("issue", "")
        year = fields.get("year", "")
        pages = fields.get("pages", "")
        doi = fields.get("doi", "")
        text = (f'{author}, "{title}," *{journal}*, vol. {volume}, '
                f'no. {issue}, {year}, pp. {pages}.')
        if doi:
            text += f" DOI: {doi}."
        return text

    elif ref_type == "english_book":
        author = fields.get("author", "")
        title = fields.get("title", "")
        place = fields.get("place", "")
        publisher = fields.get("publisher", "")
        year = fields.get("year", "")
        page = fields.get("page", "")
        page_text = f", p. {page}" if page else ""
        text = f"{author}, *{title}*, {place}: {publisher}, {year}{page_text}."
        return text

    else:
        return fields.get("raw_text", "")


def add_footnote_from_reference(para, ref_type: str, footnote_id: int, **fields) -> dict:
    """
    从结构化引用数据生成脚注（推荐使用）。

    自动格式化脚注文本并验证内容完整性。

    参数:
        para: docx Paragraph 对象
        ref_type: 引用类型
        footnote_id: 脚注ID
        fields: 引用字段

    返回: {inserted, validation, formatted_text}
    """
    formatted_text = format_footnote_text(ref_type, **fields)
    result = add_footnote_with_validation(para, formatted_text, footnote_id)
    result["formatted_text"] = formatted_text
    return result


# =============================================================================
# 三、标题样式辅助函数
# =============================================================================

def add_heading_1(doc: Document, text: str):
    """添加一级标题：一、…… （黑体 三号 居中）"""
    para = doc.add_paragraph()
    para.alignment = FONT_CONFIG["heading1"]["align"]
    run = para.add_run(text)
    run.font.name = FONT_CONFIG["heading1"]["name"]
    run.font.size = FONT_CONFIG["heading1"]["size"]
    run.bold = FONT_CONFIG["heading1"]["bold"]
    run.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CONFIG["heading1"]["name"])
    para.paragraph_format.space_before = Pt(12)
    para.paragraph_format.space_after = Pt(6)


def add_heading_2(doc: Document, text: str):
    """添加二级标题：（一）…… （黑体 四号 左对齐）"""
    para = doc.add_paragraph()
    para.alignment = FONT_CONFIG["heading2"]["align"]
    run = para.add_run(text)
    run.font.name = FONT_CONFIG["heading2"]["name"]
    run.font.size = FONT_CONFIG["heading2"]["size"]
    run.bold = FONT_CONFIG["heading2"]["bold"]
    run.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CONFIG["heading2"]["name"])
    para.paragraph_format.space_before = Pt(6)
    para.paragraph_format.space_after = Pt(3)


def add_heading_3(doc: Document, text: str):
    """添加三级标题：1．…… （黑体 小四号 左对齐，全角句号）"""
    para = doc.add_paragraph()
    para.alignment = FONT_CONFIG["heading3"]["align"]
    run = para.add_run(text)
    run.font.name = FONT_CONFIG["heading3"]["name"]
    run.font.size = FONT_CONFIG["heading3"]["size"]
    run.bold = FONT_CONFIG["heading3"]["bold"]
    run.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CONFIG["heading3"]["name"])
    para.paragraph_format.space_before = Pt(3)
    para.paragraph_format.space_after = Pt(2)


def add_heading_4(doc: Document, text: str):
    """添加四级标题：（1）…… （宋体 五号 左对齐）"""
    para = doc.add_paragraph()
    para.alignment = FONT_CONFIG["heading4"]["align"]
    run = para.add_run(text)
    run.font.name = FONT_CONFIG["heading4"]["name"]
    run.font.size = FONT_CONFIG["heading4"]["size"]
    run.bold = FONT_CONFIG["heading4"]["bold"]
    run.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CONFIG["heading4"]["name"])


def add_body_text(doc: Document, text: str):
    """添加正文段落（宋体 五号 1.5倍行距）"""
    para = doc.add_paragraph()
    para.paragraph_format.first_line_indent = Pt(21)  # 首行缩进2字符
    run = para.add_run(text)
    run.font.name = FONT_CONFIG["body"]["name"]
    run.font.size = FONT_CONFIG["body"]["size"]
    run.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CONFIG["body"]["name"])


# =============================================================================
# 四、三线表生成
# =============================================================================

def add_three_line_table(
    doc: Document,
    title: str,
    headers: list,
    data: list,
    note: str = "",
    col_widths: list = None,
) -> None:
    """
    添加三线表（《新闻与传播研究》格式）

    参数：
        doc: Document对象
        title: 表题（如 "表1  受访者基本信息"）
        headers: 表头列表
        data: 数据行列表（二维列表）
        note: 表注（可选）
        col_widths: 列宽列表（可选，单位为Cm）
    """
    # --- 添加表题 ---
    table_title = doc.add_paragraph()
    table_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = table_title.add_run(title)
    run.font.name = FONT_CONFIG["table_title"]["name"]
    run.font.size = FONT_CONFIG["table_title"]["size"]
    run.bold = FONT_CONFIG["table_title"]["bold"]
    run.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CONFIG["table_title"]["name"])

    # --- 创建表格 ---
    n_rows = len(data) + 1  # +1 for header
    n_cols = len(headers)
    table = doc.add_table(rows=n_rows, cols=n_cols)

    # 设置表格对齐
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # 设置列宽
    if col_widths:
        for i, width in enumerate(col_widths):
            for row in table.rows:
                row.cells[i].width = width

    # --- 填充表头 ---
    for i, header in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ""
        para = cell.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = para.add_run(header)
        run.font.name = FONT_CONFIG["table_content"]["name"]
        run.font.size = FONT_CONFIG["table_content"]["size"]
        run.bold = True
        run.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CONFIG["table_content"]["name"])

    # --- 填充数据 ---
    for r, row_data in enumerate(data):
        for c, value in enumerate(row_data):
            cell = table.rows[r + 1].cells[c]
            cell.text = ""
            para = cell.paragraphs[0]
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = para.add_run(str(value))
            run.font.name = FONT_CONFIG["table_content"]["name"]
            run.font.size = FONT_CONFIG["table_content"]["size"]
            run.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CONFIG["table_content"]["name"])

    # --- 设置三线表边框 ---
    _apply_three_line_borders(table)

    # --- 添加表注 ---
    if note:
        table_note = doc.add_paragraph()
        table_note.paragraph_format.space_before = Pt(2)
        run = table_note.add_run(note)
        run.font.name = FONT_CONFIG["table_note"]["name"]
        run.font.size = FONT_CONFIG["table_note"]["size"]
        run.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CONFIG["table_note"]["name"])


def _apply_three_line_borders(table):
    """为表格应用三线表边框样式"""
    tbl = table._tbl
    tblPr = tbl.tblPr if tbl.tblPr is not None else parse_xml(f'<w:tblPr {nsdecls("w")}></w:tblPr>')

    # 移除所有默认边框
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'  <w:top w:val="{TABLE_BORDER["top"]["val"]}" w:sz="{TABLE_BORDER["top"]["sz"]}" w:space="0" w:color="{TABLE_BORDER["top"]["color"]}"/>'
        f'  <w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        f'  <w:bottom w:val="{TABLE_BORDER["bottom"]["val"]}" w:sz="{TABLE_BORDER["bottom"]["sz"]}" w:space="0" w:color="{TABLE_BORDER["bottom"]["color"]}"/>'
        f'  <w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        f'  <w:insideH w:val="{TABLE_BORDER["insideH"]["val"]}" w:sz="{TABLE_BORDER["insideH"]["sz"]}" w:space="0" w:color="{TABLE_BORDER["insideH"]["color"]}"/>'
        f'  <w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        f'</w:tblBorders>'
    )

    # 移除现有的边框元素（如果有的话）
    existing_borders = tblPr.findall(qn("w:tblBorders"))
    for b in existing_borders:
        tblPr.remove(b)

    tblPr.append(borders)


# =============================================================================
# 五、图表插入位置标注
# =============================================================================

def add_figure_placeholder(doc: Document, fig_number: int, title: str, description: str = ""):
    """
    插入图片占位符（在最终排版时替换为实际图片）

    参数：
        doc: Document对象
        fig_number: 图片编号
        title: 图题内容
        description: 占位符描述（用于后期替换）
    """
    # 占位符段落
    placeholder = doc.add_paragraph()
    placeholder.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = placeholder.add_run(f"[此处插入图{fig_number}]")
    run.font.size = Pt(10.5)
    run.font.color.rgb = RGBColor(128, 128, 128)  # 灰色

    if description:
        desc = doc.add_paragraph()
        desc.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = desc.add_run(description)
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(128, 128, 128)

    # 图题（置于图下方）
    fig_caption = doc.add_paragraph()
    fig_caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = fig_caption.add_run(f"图{fig_number}  {title}")
    run.font.name = FONT_CONFIG["figure_title"]["name"]
    run.font.size = FONT_CONFIG["figure_title"]["size"]
    run.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CONFIG["figure_title"]["name"])


# =============================================================================
# 六、脚注辅助
# =============================================================================

# python-docx 原生不支持脚注，但本模块已通过OOXML底层操作实现真实脚注
FOOTNOTE_NOTE = """
[脚注说明 - v7.3更新]
本模块已实现真正的 Word OOXML 脚注支持（w:footnoteReference）。

强制使用规范：
1. 【必须】使用 add_real_footnote() 或 add_footnote_with_validation() 插入真实脚注
2. 【禁止】使用 add_footnote_marker() 的手动上标[1]方式（已废弃，仅保留向后兼容）
3. 【必须】脚注内容必须包含完整字段：作者、标题、期刊/出版社、年份、页码
4. 【必须】脚注ID必须连续（1, 2, 3, ...），不得跳号
5. 【必须】脚注内容不得为占位符（如"待补充"、"..."、"XXX"）
6. 【必须】脚注内容不得有乱码或残缺字段
7. 【建议】生成后调用 validate_all_footnotes(doc) 验证完整性

真实脚注函数：
- add_real_footnote(para, footnote_text, footnote_id) — 插入OOXML脚注
- add_footnote_with_validation(para, footnote_text, footnote_id) — 插入并验证
- validate_all_footnotes(doc) — 验证所有脚注完整性
- get_all_footnote_texts(doc) — 提取所有脚注文本
"""


def add_footnote_marker(doc: Document, text_with_marker: str, footnote_number: int):
    """
    【已废弃 v7.3】在正文中添加手动上标脚注标记。

    此函数使用手动上标[1]方式，不符合OOXML规范。
    请改用 add_real_footnote() 或 add_footnote_with_validation()。

    保留此函数仅为向后兼容，调用时会打印警告。

    参数：
        doc: Document对象
        text_with_marker: 正文文本（不含脚注标记）
        footnote_number: 脚注编号
    """
    import warnings
    warnings.warn(
        "add_footnote_marker() 已废弃，请使用 add_real_footnote() 或 "
        "add_footnote_with_validation() 插入真实OOXML脚注。",
        DeprecationWarning,
        stacklevel=2
    )
    para = doc.add_paragraph()
    para.paragraph_format.first_line_indent = Pt(21)

    run_text = para.add_run(text_with_marker)
    run_text.font.name = FONT_CONFIG["body"]["name"]
    run_text.font.size = FONT_CONFIG["body"]["size"]
    run_text.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CONFIG["body"]["name"])

    # 脚注编号上标
    run_fn = para.add_run(f"[{footnote_number}]")
    run_fn.font.name = FONT_CONFIG["body"]["name"]
    run_fn.font.size = Pt(7.5)  # 略小于正文
    run_fn.font.superscript = True


# =============================================================================
# 七、参考文献格式
# =============================================================================

def add_reference_title(doc: Document):
    """添加参考文献标题"""
    add_heading_1(doc, "参考文献")


def add_reference_chinese_journal(doc: Document, author: str, title: str, journal: str,
                                    year: str, issue: str, pages: str):
    """添加中文期刊参考文献"""
    text = f"{author}：《{title}》，《{journal}》{year}年第{issue}期，第{pages}页。"
    para = doc.add_paragraph()
    para.paragraph_format.left_indent = Pt(21)
    para.paragraph_format.first_line_indent = Pt(-10.5)  # 悬挂缩进
    run = para.add_run(text)
    run.font.name = FONT_CONFIG["body"]["name"]
    run.font.size = Pt(9)  # 小五号
    run.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CONFIG["body"]["name"])


def add_reference_chinese_book(doc: Document, author: str, title: str, place: str,
                                 publisher: str, year: str, page: str = ""):
    """添加中文著作参考文献"""
    page_text = f"，第{page}页" if page else ""
    text = f"{author}：《{title}》，{place}：{publisher}，{year}年{page_text}。"
    para = doc.add_paragraph()
    para.paragraph_format.left_indent = Pt(21)
    para.paragraph_format.first_line_indent = Pt(-10.5)
    run = para.add_run(text)
    run.font.name = FONT_CONFIG["body"]["name"]
    run.font.size = Pt(9)
    run.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CONFIG["body"]["name"])


def add_reference_english_journal(doc: Document, author: str, title: str, journal: str,
                                    volume: str, issue: str, year: str, pages: str,
                                    doi: str = ""):
    """添加英文期刊参考文献（APA格式，v7.3新增DOI字段）"""
    text = f'{author}, "{title}," *{journal}*, vol. {volume}, no. {issue}, {year}, pp. {pages}.'
    if doi:
        text += f" DOI: {doi}."
    para = doc.add_paragraph()
    para.paragraph_format.left_indent = Pt(21)
    para.paragraph_format.first_line_indent = Pt(-10.5)
    run = para.add_run(text)
    run.font.name = "Times New Roman"
    run.font.size = Pt(9)
    # 期刊名斜体
    # 注意：python-docx的add_run不支持部分斜体，此处整体显示
    # 正式使用时建议手动调整斜体部分


def add_reference_english_book(doc: Document, author: str, title: str, place: str,
                                 publisher: str, year: str):
    """添加英文著作参考文献"""
    text = f"{author}, *{title}*, {place}: {publisher}, {year}."
    para = doc.add_paragraph()
    para.paragraph_format.left_indent = Pt(21)
    para.paragraph_format.first_line_indent = Pt(-10.5)
    run = para.add_run(text)
    run.font.name = "Times New Roman"
    run.font.size = Pt(9)


# =============================================================================
# 八、完整文档生成示例
# =============================================================================

def generate_sample_document(output_path: str = "output.docx"):
    """生成一个示例文档，展示所有格式元素"""

    doc = create_document()

    # --- 标题 ---
    add_heading_1(doc, "老年人数字沉迷的生成机制研究")
    # 副标题（居中，小一点）
    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run("——基于生命历程视角的质化分析")
    run.font.name = "宋体"
    run.font.size = Pt(14)
    run.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    # --- 摘要 ---
    add_body_text(doc, "摘要内容在此处填写……")

    # --- 关键词 ---
    keywords_para = doc.add_paragraph()
    run = keywords_para.add_run("关键词：老年人；数字沉迷；生命历程；质化研究")
    run.font.name = "宋体"
    run.font.size = Pt(10.5)
    run.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    # --- 一、问题的提出 ---
    add_heading_1(doc, "一、问题的提出")
    add_body_text(doc, "引言内容在此处填写。这是正文的示例段落，展示宋体五号、1.5倍行距、首行缩进两个字符的格式。")

    # --- 二、文献回顾 ---
    add_heading_1(doc, "二、文献回顾")

    add_heading_2(doc, "（一）数字鸿沟研究回顾")
    add_body_text(doc, "二级标题下的正文内容。")

    add_heading_3(doc, "1．老年人与数字技术接入")
    add_body_text(doc, "三级标题下的正文内容。注意三级标题使用全角句号。")

    add_heading_4(doc, "（1）接入鸿沟")
    add_body_text(doc, "四级标题下的正文内容。")

    # --- 三线表示例 ---
    add_heading_1(doc, "三、研究方法")
    add_heading_2(doc, "（一）样本特征")

    add_three_line_table(
        doc,
        title="表1  受访者基本信息",
        headers=["编号", "性别", "年龄", "教育程度", "日使用时长"],
        data=[
            ["P01", "男", "68", "初中", "4小时"],
            ["P02", "女", "72", "小学", "6小时"],
            ["P03", "男", "65", "高中", "3小时"],
        ],
        note="注：使用时长数据来源于受访者自报的手机屏幕使用时间统计。",
        col_widths=[Cm(2), Cm(2), Cm(2), Cm(2.5), Cm(2.5)],
    )

    # --- 图片占位符示例 ---
    add_heading_1(doc, "四、研究发现")
    add_figure_placeholder(
        doc,
        fig_number=1,
        title="老年人短视频沉迷的三阶段模型",
        description="[占位符：请替换为实际图片，分辨率≥300dpi]",
    )

    # --- 脚注示例（v7.3 修复：使用真实OOXML脚注，不再使用手动上标） ---
    add_body_text(doc, "这是包含脚注标记的正文示例。")
    fn_para = doc.add_paragraph()
    fn_para.paragraph_format.first_line_indent = Pt(21)
    run = fn_para.add_run("Van Dijk提出了三级数字鸿沟框架，将数字不平等从接入层面拓展到技能和结果层面。")
    run.font.name = "宋体"
    run.font.size = Pt(10.5)
    run.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    # 使用真实OOXML脚注替代手动上标[1]
    add_real_footnote(
        fn_para,
        "Van Dijk, J. & Hacker, K., \"The digital divide as a complex and dynamic phenomenon,\" *The Information Society*, vol. 19, no. 4, 2003, pp. 315-326.",
        footnote_id=1
    )

    # --- 结语 ---
    add_heading_1(doc, "五、结语")
    add_body_text(doc, "结语内容在此处填写。")

    # --- 参考文献 ---
    add_reference_title(doc)
    add_reference_chinese_journal(
        doc, "胡泳", "数字鸿沟的再思考", "新闻与传播研究",
        "2020", "3", "5-23"
    )
    add_reference_chinese_book(
        doc, "彭兰", "新媒体用户研究", "北京",
        "中国人民大学出版社", "2020"
    )
    add_reference_english_journal(
        doc, "van Dijk, J. & Hacker, K.", "The digital divide as a complex and dynamic phenomenon",
        "The Information Society", "19", "4", "2003", "315-326"
    )
    add_reference_english_book(
        doc, "Zuboff, S.", "The Age of Surveillance Capitalism",
        "New York", "PublicAffairs", "2019"
    )

    # 保存
    doc.save(output_path)
    print(f"文档已生成：{os.path.abspath(output_path)}")
    return doc


# =============================================================================
# 九、主入口
# ============================================================================

# ============================================================================
# 内参报告Word模板（★v7.4新增）
# ============================================================================

def add_neican_title(doc, title: str):
    """添加内参标题（居中、黑体、16pt）"""
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = para.add_run(title)
    run.font.name = "黑体"
    run.font.size = Pt(16)
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
    return para


def add_neican_section(doc, level: int, text: str):
    """添加内参板块（层级编号：一、/（一）/1.）"""
    from docx.shared import Pt
    para = doc.add_paragraph()
    run = para.add_run(text)

    if level == 1:
        run.font.name = "黑体"
        run.font.size = Pt(14)
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
        para.paragraph_format.space_before = Pt(12)
        para.paragraph_format.space_after = Pt(6)
    elif level == 2:
        run.font.name = "楷体"
        run.font.size = Pt(12)
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "楷体")
        para.paragraph_format.space_before = Pt(6)
    else:
        run.font.name = "宋体"
        run.font.size = Pt(10.5)
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    return para


def add_neican_body(doc, text: str):
    """添加内参正文段落"""
    from docx.shared import Pt
    para = doc.add_paragraph()
    run = para.add_run(text)
    run.font.name = "宋体"
    run.font.size = Pt(10.5)
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    para.paragraph_format.line_spacing = 1.5
    para.paragraph_format.first_line_indent = Pt(21)
    return para


def add_neican_signature(doc, authors: list):
    """添加内参署名"""
    from docx.shared import Pt
    para = doc.add_paragraph()
    run = para.add_run("作者信息：")
    run.font.name = "宋体"
    run.font.size = Pt(10.5)
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    run.bold = True

    for author in authors:
        p = doc.add_paragraph()
        r = p.add_run(f"{author['name']} {author['unit']}{author.get('title', '')}")
        r.font.name = "宋体"
        r.font.size = Pt(10.5)
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    return para


def generate_neican_document(title: str, opening: str, sections: list,
                              signature_authors: list, output_path: str = None):
    """生成内参报告Word文档

    Args:
        title: 内参标题
        opening: 开篇段（公鸡打鸣段）
        sections: 板块列表，每个板块为 {"level1": "一、XX", "content": [...]}
        signature_authors: 署名作者列表
        output_path: 输出路径
    """
    from docx import Document
    from docx.shared import Pt, Cm

    doc = Document()

    # 页面设置
    for section in doc.sections:
        section.top_margin = Cm(2.54)
        section.bottom_margin = Cm(2.54)
        section.left_margin = Cm(3.17)
        section.right_margin = Cm(3.17)

    # 标题
    add_neican_title(doc, title)

    # 署名（正文前）
    if signature_authors:
        sig_para = doc.add_paragraph()
        sig_para.alignment = 1  # CENTER
        for i, author in enumerate(signature_authors):
            run = sig_para.add_run(f"{author['name']} ")
            run.font.size = Pt(10.5)
            run.font.name = "宋体"
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    # 开篇段
    add_neican_body(doc, opening)

    # 正文板块
    for section in sections:
        add_neican_section(doc, 1, section["level1"])
        for content in section.get("content", []):
            if isinstance(content, dict):
                if content.get("level2"):
                    add_neican_section(doc, 2, content["level2"])
                if content.get("level3"):
                    add_neican_section(doc, 3, content["level3"])
                if content.get("text"):
                    add_neican_body(doc, content["text"])
            else:
                add_neican_body(doc, content)

    # 署名（正文后）
    add_neican_signature(doc, signature_authors)

    # 保存
    if output_path:
        doc.save(output_path)
    return doc


if __name__ == "__main__":
    generate_sample_document("论文模板_新闻与传播研究格式.docx")