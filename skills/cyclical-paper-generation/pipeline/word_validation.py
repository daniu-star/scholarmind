"""
循环式论文生成Pipeline v6.0 - Word文档输出质量验证模块

程序化验证（非 LLM Agent），确保生成的 .docx 文件：
1. 可被 Word/WPS 正常打开
2. 脚注为真正的 Word 脚注（OOXML w:footnote）
3. 脚注编号与参考文献条目一致
4. 中文引号字体为宋体（非 Times New Roman / 等线 / Calibri）
5. 脚注内容完整性（无缺漏字段、无乱码、无占位符）—— v7.3 新增
6. 脚注编号格式（上标、字号、字体）—— v7.3 新增
7. 脚注-参考文献严格匹配（作者+年份+标题关键词）—— v7.3 增强

Author: Cyclical Paper Generation Pipeline
Version: 7.3.0
"""

import re
from typing import Dict, List, Tuple
from docx import Document
from docx.oxml.ns import qn
from docx.opc.exceptions import PackageNotFoundError


CHINESE_QUOTES = ["“", "”", "‘", "’", "「", "」"]

# ★v7.4 新增：直引号字符列表（U+0022, U+0027）——必须替换为弯引号
STRAIGHT_QUOTES = ['"', "'"]
# 弯引号对应映射（直→弯）
STRAIGHT_TO_CURLY_MAP = {
    '"': (""", """),  # 开引号、闭引号
    "'": ("‘", "’"),  # 开单引号、闭单引号
}

# v7.3 新增：脚注占位符检测列表
FOOTNOTE_PLACEHOLDERS = [
    "...", "。。。", "待补充", "待填写", "此处填写",
    "占位符", "placeholder", "TBD", "TODO", "XXX", "xxx",
    "脚注内容", "参考文献信息", "[作者]", "[标题]", "[期刊]",
]

# v7.3 新增：脚注必填字段（按引用类型）
FOOTNOTE_CRITICAL_FIELDS = {
    "chinese_journal": ["author", "title", "journal", "year"],
    "chinese_book": ["author", "title", "publisher", "year"],
    "english_journal": ["author", "title", "journal", "year"],
    "english_book": ["author", "title", "year"],
}


def validate_docx_openable(filepath: str) -> Tuple[bool, str]:
    """验证 docx 文件是否可以正常打开"""
    try:
        Document(filepath)
        return (True, "OK")
    except PackageNotFoundError:
        return (False, "文件损坏：PackageNotFoundError")
    except Exception as e:
        return (False, f"打开异常：{str(e)}")


def validate_footnote_format(doc: Document) -> Dict:
    """验证脚注是否为真正的 Word 脚注"""
    try:
        fn_part = doc.part.footnotes_part
        fns = fn_part.element.findall(qn("w:footnote"))
        real = []
        for fn in fns:
            fid = fn.get(qn("w:id"))
            if fid and int(fid) >= 0:
                real.append(fn)
        ids = sorted([int(fn.get(qn("w:id"))) for fn in real])
        gaps = []
        for i in range(len(ids) - 1):
            if ids[i + 1] - ids[i] != 1:
                gaps.append(f"{ids[i]}->{ids[i+1]}")
        return {
            "total": len(real), "ids": ids, "continuous": len(gaps) == 0,
            "has_real": len(real) > 0, "gaps": gaps,
            "passed": len(gaps) == 0 and len(real) > 0,
        }
    except AttributeError:
        return {"total": 0, "ids": [], "continuous": False, "has_real": False,
                "passed": False, "error": "footnotes.xml 缺失"}


def detect_manual_footnotes(doc: Document) -> List[Dict]:
    """检测手动上标伪脚注"""
    manual = []
    pat = re.compile(r"[\[\(](\d+)[\]\)]")
    for pi, p in enumerate(doc.paragraphs):
        for r in p.runs:
            m = pat.findall(r.text or "")
            if not m:
                continue
            rPr = r._element.rPr
            sup = False
            if rPr is not None:
                va = rPr.find(qn("w:vertAlign"))
                if va is not None and va.get(qn("w:val")) == "superscript":
                    sup = True
            if sup:
                for n in m:
                    manual.append({"para": pi, "num": int(n), "preview": r.text[:60]})
    return manual


def extract_references(text: str) -> List[str]:
    """从论文文本提取参考文献列表"""
    refs = []
    in_ref = False
    for line in text.split("\n"):
        line = line.strip()
        if re.match(r"^参考文献", line):
            in_ref = True
            continue
        if in_ref and line and len(line) > 10:
            refs.append(line)
    return refs


def _extract_footnote_texts(doc: Document) -> List[Dict]:
    """
    提取所有脚注文本（v7.3 新增内部辅助函数）

    返回: [{id, text}]
    """
    fn_texts = []
    try:
        fn_part = doc.part.footnotes_part
        if fn_part is None:
            return fn_texts
        for fn in fn_part.element.findall(qn("w:footnote")):
            fid = fn.get(qn("w:id"))
            if fid and int(fid) >= 0:
                txt = "".join(
                    r.text or ""
                    for p in fn.findall(qn("w:p"))
                    for r in p.findall(".//" + qn("w:t"))
                )
                fn_texts.append({"id": int(fid), "text": txt})
    except (AttributeError, Exception):
        pass
    return fn_texts


def validate_footnote_content_completeness(doc: Document) -> Dict:
    """
    v7.3 新增：验证脚注内容的完整性

    检查项：
    1. 脚注文本非空且长度合理（≥10字符）
    2. 无占位符（"待补充"、"..."、"XXX"等）
    3. 无乱码（U+FFFD替换字符、异常字符过多）
    4. 必填字段齐全（作者、标题、期刊/出版社、年份）

    返回: {total, valid, invalid, details, passed}
    """
    fn_texts = _extract_footnote_texts(doc)
    total = len(fn_texts)
    valid = 0
    details = []

    for fn in fn_texts:
        text = fn["text"].strip()
        issues = []

        # 1. 非空检查
        if not text or len(text) < 10:
            issues.append("脚注内容过短（<10字符），可能为空或残缺")
            details.append({"id": fn["id"], "text_preview": text[:80], "issues": issues})
            continue

        # 2. 占位符检测
        for ph in FOOTNOTE_PLACEHOLDERS:
            if ph in text:
                issues.append(f"脚注含占位符：{ph}")

        # 3. 乱码检测
        if "\ufffd" in text:
            issues.append("脚注含乱码字符（U+FFFD）")
        garbled_chars = re.findall(
            r"[^一-龥a-zA-Z0-9\s《》“”‘’.,;:\!?()（）\\-—–/\d]", text
        )
        if len(garbled_chars) > 5:
            issues.append(f"脚注含{len(garbled_chars)}个异常字符，可能为乱码")

        # 4. 字段完整性检查
        # 中文期刊：作者：《标题》，《期刊》年份第X期，第X页。
        has_chinese_journal = (
            re.search(r"[一-鿿]{2,4}：《", text)
            and re.search(r"\d{4}年", text)
        )
        # 中文著作：作者：《标题》，地点：出版社，年份年。
        has_chinese_book = (
            re.search(r"[一-鿿]{2,4}：《", text)
            and re.search(r"出版社", text)
        )
        # 英文期刊：Author, "Title," *Journal*, ...
        has_english_journal = (
            re.search(r'[A-Z][a-z]+,\s', text)
            and re.search(r'"[^"]+"', text)
        )
        # 英文著作：Author, *Title*, ...
        has_english_book = (
            re.search(r'[A-Z][a-z]+,\s', text)
            and re.search(r'\*[^*]+\*', text)
        )

        is_valid_type = (
            has_chinese_journal or has_chinese_book
            or has_english_journal or has_english_book
        )
        if not is_valid_type:
            issues.append("无法识别引用类型，脚注格式不符合任何已知规范")
        else:
            # 关键字段缺失检查
            if has_chinese_journal:
                if not re.search(r"[一-鿿]{2,4}：《", text):
                    issues.append("关键字段缺失：作者")
                if not re.search(r"《[^》]+》", text):
                    issues.append("关键字段缺失：标题")
                if not re.search(r"\d{4}年", text):
                    issues.append("关键字段缺失：年份")
            elif has_chinese_book:
                if not re.search(r"[一-鿿]{2,4}：《", text):
                    issues.append("关键字段缺失：作者")
                if not re.search(r"出版社", text):
                    issues.append("关键字段缺失：出版社")
                if not re.search(r"\d{4}年", text):
                    issues.append("关键字段缺失：年份")
            elif has_english_journal:
                if not re.search(r'[A-Z][a-z]+', text):
                    issues.append("关键字段缺失：作者")
                if not re.search(r'"[^"]+"', text):
                    issues.append("关键字段缺失：标题")
                if not re.search(r'\d{4}', text):
                    issues.append("关键字段缺失：年份")
            elif has_english_book:
                if not re.search(r'[A-Z][a-z]+', text):
                    issues.append("关键字段缺失：作者")
                if not re.search(r'\d{4}', text):
                    issues.append("关键字段缺失：年份")

        if issues:
            details.append({"id": fn["id"], "text_preview": text[:80], "issues": issues})
        else:
            valid += 1

    invalid = total - valid
    return {
        "total": total,
        "valid": valid,
        "invalid": invalid,
        "details": details,
        "passed": invalid == 0 and total > 0,
    }


def validate_footnote_number_format(doc: Document) -> Dict:
    """
    v7.3 新增：验证脚注编号的格式

    检查项：
    1. 脚注编号使用上标（vertAlign=superscript）
    2. 脚注编号字体为 Times New Roman（西文）
    3. 脚注编号字号为小五号（9pt = sz val 18）

    返回: {total, compliant, violations, passed}
    """
    violations = []
    total = 0
    try:
        fn_part = doc.part.footnotes_part
        if fn_part is None:
            return {"total": 0, "compliant": 0, "violations": [], "passed": True}
        for fn in fn_part.element.findall(qn("w:footnote")):
            fid = fn.get(qn("w:id"))
            if not fid or int(fid) < 0:
                continue
            total += 1
            # 检查脚注引用标记 run（含 w:footnoteRef 的 run）
            for p in fn.findall(qn("w:p")):
                for r in p.findall(qn("w:r")):
                    rPr = r.find(qn("w:rPr"))
                    if rPr is None:
                        continue
                    # 检查是否含 footnoteRef（编号标记）
                    has_fn_ref = r.find(qn("w:footnoteRef")) is not None
                    if not has_fn_ref:
                        continue
                    # 检查上标
                    va = rPr.find(qn("w:vertAlign"))
                    if va is None or va.get(qn("w:val")) != "superscript":
                        violations.append({
                            "footnote_id": int(fid),
                            "issue": "脚注编号未设置上标",
                        })
                    # 检查字号
                    sz = rPr.find(qn("w:sz"))
                    if sz is not None:
                        sz_val = sz.get(qn("w:val"))
                        if sz_val and int(sz_val) != 18:  # 9pt = 18 half-points
                            violations.append({
                                "footnote_id": int(fid),
                                "issue": f"脚注编号字号不合规（sz={sz_val}，应为18）",
                            })
                    # 检查字体
                    rFonts = rPr.find(qn("w:rFonts"))
                    if rFonts is not None:
                        ascii_font = rFonts.get(qn("w:ascii"))
                        if ascii_font and ascii_font != "Times New Roman":
                            violations.append({
                                "footnote_id": int(fid),
                                "issue": f"脚注编号字体不合规（ascii={ascii_font}，应为Times New Roman）",
                            })
    except (AttributeError, Exception):
        pass

    compliant = total - len(set(v["footnote_id"] for v in violations))
    return {
        "total": total,
        "compliant": compliant,
        "violations": violations,
        "passed": len(violations) == 0,
    }


def validate_footnote_refs(doc: Document, paper: str) -> Dict:
    """
    v7.3 增强：验证脚注引用与参考文献列表的一致性

    增强点：
    - 匹配阈值从≥2提高到≥3（作者2分+年份1分+标题关键词1分）
    - 增加标题关键词匹配
    - 返回未匹配脚注的详细信息
    """
    refs = extract_references(paper)
    fn_texts = _extract_footnote_texts(doc)
    fn_texts_only = [fn["text"] for fn in fn_texts]

    if not fn_texts_only:
        return {"total": 0, "matched": 0, "unmatched": 0, "passed": False,
                "details": []}

    matched = 0
    unmatched_details = []
    for fn_item in fn_texts:
        ft = fn_item["text"]
        # 提取作者+年份
        ay = re.findall(r"([一-鿿]{2,4})[（(](\d{4})[）)]", ft)
        # 提取标题关键词（从《标题》中提取）
        title_match = re.search(r"《([^》]+)》", ft)
        title_keywords = []
        if title_match:
            title = title_match.group(1)
            # 提取2-4字的关键词
            title_keywords = re.findall(r"[\u4e00-\u9fa5]{2,4}", title)

        found = False
        best_score = 0
        best_ref = ""
        for ref in refs:
            score = 0
            for a, y in ay:
                if a in ref:
                    score += 2
                if y in ref:
                    score += 1
            # 标题关键词匹配
            for kw in title_keywords[:3]:  # 最多匹配3个关键词
                if kw in ref:
                    score += 1
            if score > best_score:
                best_score = score
                best_ref = ref
            if score >= 3:  # v7.3: 阈值从2提高到3
                found = True
                break

        if found:
            matched += 1
        else:
            unmatched_details.append({
                "footnote_id": fn_item["id"],
                "footnote_text": ft[:100],
                "best_match_score": best_score,
                "best_match_ref": best_ref[:100],
            })

    return {
        "total": len(fn_texts_only),
        "total_refs": len(refs),
        "matched": matched,
        "unmatched": len(fn_texts_only) - matched,
        "details": unmatched_details,
        "passed": matched == len(fn_texts_only) and len(fn_texts_only) > 0,
    }


def validate_chinese_quote_font(doc: Document) -> List[Dict]:
    """验证中文引号的字体是否为宋体"""
    violations = []
    for pi, p in enumerate(doc.paragraphs):
        for ri, r in enumerate(p.runs):
            text = r.text or ""
            if not any(c in text for c in CHINESE_QUOTES):
                continue
            rPr = r._element.rPr
            if rPr is None:
                violations.append({"para": pi, "text": text[:40], "issue": "rPr missing"})
                continue
            rf = rPr.find(qn("w:rFonts"))
            if rf is None:
                violations.append({"para": pi, "text": text[:40], "issue": "rFonts missing"})
                continue
            ea = rf.get(qn("w:eastAsia"))
            if ea is None:
                violations.append({"para": pi, "text": text[:40], "issue": "eastAsia unset"})
            elif ea not in ["宋体", "SimSun"]:
                violations.append({"para": pi, "text": text[:40], "issue": f"font={ea}"})
    return violations


def validate_quote_characters(text: str) -> Dict:
    """★v7.4 新增：验证文本中是否包含直引号字符（U+0022, U+0027）

    检测文本中是否使用了直引号（"'），若包含则返回违规列表。
    所有中文论文输出必须使用弯引号（""''），禁止直引号。

    Args:
        text: 待检测的论文文本（纯文本）

    Returns:
        检测结果字典：
            - straight_quote_count: 直引号总数
            - double_straight_count: 直双引号数量
            - single_straight_count: 直单引号数量
            - violations: 违规位置列表（含上下文）
            - passed: 是否通过（无直引号即通过）
    """
    violations = []
    double_count = 0
    single_count = 0

    for i, char in enumerate(text):
        if char == '"':
            double_count += 1
            # 提取上下文（前后各20字）
            start = max(0, i - 20)
            end = min(len(text), i + 21)
            context = text[start:end]
            violations.append({
                "position": i,
                "char": '"',
                "type": "double_straight",
                "context": context,
                "suggestion": "应替换为弯引号 “ 或 ”",
            })
        elif char == "'":
            single_count += 1
            start = max(0, i - 20)
            end = min(len(text), i + 21)
            context = text[start:end]
            violations.append({
                "position": i,
                "char": "'",
                "type": "single_straight",
                "context": context,
                "suggestion": "应替换为弯引号 ‘ 或 ’",
            })

    total = double_count + single_count
    return {
        "straight_quote_count": total,
        "double_straight_count": double_count,
        "single_straight_count": single_count,
        "violations": violations,
        "passed": total == 0,
    }


def normalize_straight_quotes(text: str) -> Tuple[str, List[Dict]]:
    """★v7.4 新增：将文本中的直引号自动替换为弯引号

    采用"开-闭"交替策略：同一对引号内，第一个替换为开引号，第二个替换为闭引号。

    Args:
        text: 待处理的论文文本

    Returns:
        元组 (替换后的文本, 替换记录列表)
    """
    result = []
    replacements = []
        # Track open/close state for both double and single quotes
    double_open = True
    single_open = True

    LEFT_DQ = "“"
    RIGHT_DQ = "”"
    LEFT_SQ = "‘"
    RIGHT_SQ = "’"

    for i, char in enumerate(text):
        if char == '"':
            if double_open:
                result.append(LEFT_DQ)
                replacements.append({"position": i, "from": '"', "to": LEFT_DQ})
            else:
                result.append(RIGHT_DQ)
                replacements.append({"position": i, "from": '"', "to": RIGHT_DQ})
            double_open = not double_open
        elif char == "'":
            if single_open:
                result.append(LEFT_SQ)
                replacements.append({"position": i, "from": "'", "to": LEFT_SQ})
            else:
                result.append(RIGHT_SQ)
                replacements.append({"position": i, "from": "'", "to": RIGHT_SQ})
            single_open = not single_open
        else:
            result.append(char)

    return "".join(result), replacements

def validate_charts(doc: Document) -> Dict:
    """验证图表编号连续性"""
    fig_pat = re.compile(r"图(\d+)")
    tab_pat = re.compile(r"表(\d+)")
    figs = sorted(set(int(m) for p in doc.paragraphs for m in fig_pat.findall(p.text)))
    tabs = sorted(set(int(m) for p in doc.paragraphs for m in tab_pat.findall(p.text)))

    def cont(nums):
        if not nums:
            return True
        return nums == list(range(nums[0], nums[-1] + 1))

    return {"figures": figs, "tables": tabs, "passed": cont(figs) and cont(tabs)}


def run_full_validation(filepath: str, paper_text: str = "") -> Dict:
    """
    运行完整 Word 格式验证（只读，不写文件）

    v7.3 新增检查项：
    - footnote_content: 脚注内容完整性验证
    - footnote_number_format: 脚注编号格式验证
    """
    ok, msg = validate_docx_openable(filepath)
    report = {"filepath": filepath, "openable": {"passed": ok, "msg": msg}, "passed": False}
    if not ok:
        return report
    doc = Document(filepath)
    report["footnote_format"] = validate_footnote_format(doc)
    report["manual_footnotes"] = detect_manual_footnotes(doc)
    report["footnote_refs"] = validate_footnote_refs(doc, paper_text)
    report["footnote_content"] = validate_footnote_content_completeness(doc)  # v7.3 新增
    report["footnote_number_format"] = validate_footnote_number_format(doc)  # v7.3 新增
    report["quote_violations"] = validate_chinese_quote_font(doc)
    report["charts"] = validate_charts(doc)
    checks = [
        report["footnote_format"].get("passed", True),
        len(report["manual_footnotes"]) == 0,
        report["footnote_refs"].get("passed", True),
        report["footnote_content"].get("passed", True),  # v7.3 新增
        report["footnote_number_format"].get("passed", True),  # v7.3 新增
        len(report["quote_violations"]) == 0,
        report["charts"].get("passed", True),
    ]
    report["passed"] = all(checks)
    return report


def format_report(report: Dict) -> str:
    """格式化验证报告"""
    lines = [
        "=" * 48,
        "  Word 文档质量验证报告 (v7.3)",
        "=" * 48,
        f"文件: {report.get('filepath', 'N/A')}",
        "",
    ]
    o = report.get("openable", {})
    lines.append(f"{'OK' if o.get('passed') else 'FAIL'} 可打开性: {o.get('msg', 'N/A')}")

    ff = report.get("footnote_format", {})
    if ff.get("has_real"):
        lines.append(
            f"{'OK' if ff.get('passed') else 'FAIL'} 脚注: {ff['total']} 条, "
            f"连续={ff.get('continuous', False)}"
        )
    else:
        lines.append("FAIL 脚注: 无真实 Word 脚注")

    mf = report.get("manual_footnotes", [])
    lines.append(f"{'FAIL' if mf else 'OK'} 手动伪脚注: {len(mf)} 处")

    fr = report.get("footnote_refs", {})
    if fr:
        lines.append(
            f"{'OK' if fr.get('passed') else 'FAIL'} 脚注-参考文献: "
            f"匹配{fr.get('matched', 0)}/{fr.get('total', 0)}"
        )
        # v7.3: 显示未匹配详情
        for detail in fr.get("details", []):
            lines.append(f"  ⚠ 脚注#{detail['footnote_id']}: {detail['footnote_text'][:60]}")

    # v7.3 新增：脚注内容完整性
    fc = report.get("footnote_content", {})
    if fc:
        lines.append(
            f"{'OK' if fc.get('passed') else 'FAIL'} 脚注内容完整性: "
            f"有效{fc.get('valid', 0)}/{fc.get('total', 0)}"
        )
        for detail in fc.get("details", []):
            lines.append(f"  ⚠ 脚注#{detail['id']}: {'; '.join(detail['issues'])}")

    # v7.3 新增：脚注编号格式
    nf = report.get("footnote_number_format", {})
    if nf:
        lines.append(
            f"{'OK' if nf.get('passed') else 'FAIL'} 脚注编号格式: "
            f"合规{nf.get('compliant', 0)}/{nf.get('total', 0)}"
        )
        for v in nf.get("violations", []):
            lines.append(f"  ⚠ 脚注#{v['footnote_id']}: {v['issue']}")

    qv = report.get("quote_violations", [])
    lines.append(f"{'FAIL' if qv else 'OK'} 引号字体: {len(qv)} 处问题")

    cn = report.get("charts", {})
    lines.append(
        f"{'OK' if cn.get('passed') else 'FAIL'} 图表编号: "
        f"图{cn.get('figures', [])} 表{cn.get('tables', [])}"
    )

    lines.append("")
    lines.append(f"{'PASS' if report.get('passed') else 'FAIL'} 综合判定")
    lines.append("=" * 48)
    return "\n".join(lines)


# ============================================================================
# 内参报告格式验证（★v7.4新增）
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


def validate_neican_title(doc) -> dict:
    """验证内参标题范式（★v7.4新增）"""
    import re
    title = ""
    for para in doc.paragraphs[:3]:
        if para.text.strip() and len(para.text.strip()) > 5:
            title = para.text.strip()
            break
    if not title:
        return {"valid": False, "pattern": None, "issue": "未找到标题"}

    for pattern_name, pattern_regex in NEICAN_TITLE_PATTERNS.items():
        if re.search(pattern_regex, title):
            return {"valid": True, "pattern": pattern_name, "title": title}

    # 检测是否为学术化标题（研究描述型）
    if any(kw in title for kw in ["研究", "分析", "探讨", "考察"]):
        return {"valid": False, "pattern": "研究描述型(需转化)", "title": title,
                "issue": "标题偏学术化，需转化为内参标题范式"}

    return {"valid": False, "pattern": None, "title": title,
            "issue": "标题不符合任何内参标题范式"}


def validate_neican_opening(doc) -> dict:
    """验证内参开篇范式（★v7.4新增）"""
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    if len(paragraphs) < 2:
        return {"valid": False, "issue": "段落不足，无法判断开篇范式"}

    first_para = paragraphs[1] if paragraphs[0].startswith("作者") else paragraphs[0]

    # 检测公鸡打鸣段关键词
    timing_keywords = ["近期", "近期，", "党的", "会议", "政策", "出台", "事件", "报告提出"]
    has_timing = any(kw in first_para for kw in timing_keywords)

    # 检测"本文"或"本报告"
    has_action = any(kw in first_para for kw in ["本文", "本报告", "建议", "提出", "分析"])

    if has_timing and has_action:
        # 检查是否为双段式（第二段做性质判断）
        if len(paragraphs) >= 3:
            second_para = paragraphs[2]
            judgment_keywords = ["不是", "而是", "值得", "凸显", "表明", "实质"]
            is_double = any(kw in second_para for kw in judgment_keywords)
            if is_double:
                return {"valid": True, "pattern": "双段式", "issue": None}
        return {"valid": True, "pattern": "单段式", "issue": None}

    return {"valid": False, "pattern": None,
            "issue": "开篇缺少公鸡打鸣段（时机→意义→做什么）"}


def validate_neican_hierarchy(doc) -> dict:
    """验证内参层级编号（★v7.4新增）"""
    import re
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    issues = []

    level1_pattern = re.compile(r'^[一二三四五六七八九十]+[、．.]')
    level2_pattern = re.compile(r'^（[一二三四五六七八九十]+）')
    level3_pattern = re.compile(r'^\d+[.．]')

    level1_count = sum(1 for p in paragraphs if level1_pattern.match(p))
    level2_count = sum(1 for p in paragraphs if level2_pattern.match(p))
    level3_count = sum(1 for p in paragraphs if level3_pattern.match(p))

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


def validate_neican_countermeasure(doc) -> dict:
    """验证内参对策刻度（★v7.4新增）"""
    import re
    full_text = "\n".join(p.text for p in doc.paragraphs)
    issues = []

    for pattern in NEICAN_ABSTRACT_COUNTERMEASURE_PATTERNS:
        matches = re.findall(pattern, full_text)
        for match in matches:
            issues.append(f"抽象对策表述：'{match}'，需具体化（添加比例/机制/路径）")

    # 检测责任主体
    responsibility_keywords = ["建议由", "要求", "推动", "牵头", "负责", "主管部门", "网信"]
    has_responsibility = any(kw in full_text for kw in responsibility_keywords)

    if not has_responsibility:
        issues.append("对策建议缺少明确责任主体")

    return {
        "valid": len(issues) == 0,
        "abstract_count": len([i for i in issues if "抽象" in i]),
        "has_responsibility": has_responsibility,
        "issues": issues,
    }


def validate_neican_ending(doc) -> dict:
    """验证内参结尾规范（★v7.4新增）"""
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    if not paragraphs:
        return {"valid": False, "issue": "文档为空"}

    last_para = paragraphs[-1]
    forbidden_endings = ["综上所述", "总而言之", "总之", "结语", "结论"]

    for ending in forbidden_endings:
        if ending in last_para:
            return {"valid": False, "issue": f"结尾包含禁止词汇：'{ending}'，内参不写总结段"}

    return {"valid": True, "issue": None}


def validate_neican_signature(doc) -> dict:
    """验证内参署名格式（★v7.4新增）"""
    full_text = "\n".join(p.text for p in doc.paragraphs)

    has_author_info = "作者信息" in full_text or "作者介绍" in full_text
    if not has_author_info:
        return {"valid": False, "issue": "缺少署名信息（'作者信息：'或'作者介绍：'）"}

    # 检查格式规范性
    import re
    signature_patterns = [
        r'作者信息[：:]\s*\n.*?单位',
        r'作者介绍[：:]\s*\n.*?单位',
    ]
    for pattern in signature_patterns:
        if re.search(pattern, full_text, re.DOTALL):
            return {"valid": True, "issue": None}

    return {"valid": False, "issue": "署名格式不规范，应为'作者信息：\nXXX XX单位XX职务'"}


def validate_neican_academic_residue(doc) -> dict:
    """检测内参中的学术残留（★v7.4新增）"""
    import re
    full_text = "\n".join(p.text for p in doc.paragraphs)
    residues = []

    for pattern in NEICAN_ACADEMIC_RESIDUE_PATTERNS:
        matches = re.findall(pattern, full_text)
        for match in matches:
            residues.append(f"学术残留：'{match}'")

    return {
        "valid": len(residues) == 0,
        "residue_count": len(residues),
        "residues": residues,
    }


def run_neican_validation(doc) -> dict:
    """整合所有内参验证项（★v7.4新增）"""
    results = {
        "title": validate_neican_title(doc),
        "opening": validate_neican_opening(doc),
        "hierarchy": validate_neican_hierarchy(doc),
        "countermeasure": validate_neican_countermeasure(doc),
        "ending": validate_neican_ending(doc),
        "signature": validate_neican_signature(doc),
        "academic_residue": validate_neican_academic_residue(doc),
    }

    all_valid = all(r.get("valid", False) for r in results.values())
    results["overall_valid"] = all_valid
    results["total_issues"] = sum(
        len(r.get("issues", [])) if isinstance(r.get("issues"), list)
        else (1 if r.get("issue") else 0)
        for r in results.values()
    )
    return results
