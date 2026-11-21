"""T15 结构性完整性检查（纯函数，无 IO / 无 DB）。

只回答“按块级 ``section_path`` 能否核对到必备章节”，不评价内容质量、不推断
作者意图、不调用模型。所有结论都可以由传入的块清单复核。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence

# 标题里常见的前缀：编号、markdown 记号、括号序号等。匹配关键词前先剥掉，
# 这样 “1 引言”“一、方法”“## 3.2 结论” 都能识别。
_HEADING_PREFIX = re.compile(
    r"^[\s#>*_`~\-—–·.、,，:：;；()（）\[\]【】<>《》0-9０-９"
    r"一二三四五六七八九十百]+"
)
_WHITESPACE = re.compile(r"\s+")


def _get(block: Any, key: str, default: Any = "") -> Any:
    if isinstance(block, Mapping):
        return block.get(key, default)
    return getattr(block, key, default)


def _as_ordinal(block: Any) -> int | None:
    try:
        return int(_get(block, "ordinal", -1))
    except (TypeError, ValueError):
        return None


def _as_ordinal_set(analyzed_ordinals: Iterable[Any]) -> set[int]:
    result: set[int] = set()
    for item in analyzed_ordinals or ():
        try:
            result.add(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _normalize_heading(value: Any) -> str:
    text = _WHITESPACE.sub("", str(value or "")).casefold()
    return _HEADING_PREFIX.sub("", text)


def expected_sections(blocks: Sequence[Any]) -> List[str]:
    """按出现顺序返回去重后的非空 ``section_path`` 清单。"""
    sections: List[str] = []
    seen: set[str] = set()
    for block in blocks or ():
        path = str(_get(block, "section_path", "") or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        sections.append(path)
    return sections


def section_coverage(
    blocks: Sequence[Any], analyzed_ordinals: Iterable[Any]
) -> Dict[str, List[str]]:
    """返回 ``{'expected': [...], 'covered': [...], 'missing': [...]}``。

    ``covered`` 指至少有一个已分析块落入的章节（按 expected 顺序）；
    ``missing`` 是 expected 中没有任何已分析块的章节。
    """
    expected = expected_sections(blocks)
    analyzed = _as_ordinal_set(analyzed_ordinals)
    covered_set: set[str] = set()
    for block in blocks or ():
        ordinal = _as_ordinal(block)
        if ordinal is None or ordinal not in analyzed:
            continue
        path = str(_get(block, "section_path", "") or "").strip()
        if path:
            covered_set.add(path)
    covered = [section for section in expected if section in covered_set]
    missing = [section for section in expected if section not in covered_set]
    return {"expected": expected, "covered": covered, "missing": missing}


# 必备章节：关键词做子串匹配（标题可能带编号或层级前缀）。references 额外接受
# 参考文献条目块（kind="reference"），因为有些解析器把条目与标题分开。
_REQUIRED_SECTIONS: tuple[Dict[str, Any], ...] = (
    {
        "key": "introduction",
        "label": "引言",
        "keywords": (
            "引言",
            "前言",
            "绪论",
            "导论",
            "研究背景",
            "问题提出",
            "introduction",
        ),
        "category": "format",
        "severity": "major",
        "reason": "按块级 section_path 汇总的章节清单中未匹配到引言/前言/绪论类标题。",
    },
    {
        "key": "method",
        "label": "方法",
        "keywords": (
            "方法",
            "研究方法",
            "数据与方法",
            "材料与方法",
            "研究设计",
            "方法论",
            "methodology",
            "materialsandmethods",
            "method",
        ),
        "category": "format",
        "severity": "major",
        "reason": "按块级 section_path 汇总的章节清单中未匹配到研究方法/研究设计类标题。",
    },
    {
        "key": "conclusion",
        "label": "结论",
        "keywords": (
            "结论",
            "结语",
            "总结",
            "conclusion",
            "conclusions",
        ),
        "category": "format",
        "severity": "major",
        "reason": "按块级 section_path 汇总的章节清单中未匹配到结论/结语类标题。",
    },
    {
        "key": "references",
        "label": "参考文献",
        "keywords": (
            "参考文献",
            "引用文献",
            "文献列表",
            "bibliography",
            "references",
            "reference",
            "workscited",
        ),
        "category": "evidence",
        "severity": "major",
        "reason": "章节清单中未匹配到参考文献标题，且全文块中没有参考文献条目（kind=reference）。",
    },
)

_REFERENCE_KINDS = frozenset({"reference", "references", "bibliography", "citation"})


def _has_reference_blocks(blocks: Sequence[Any]) -> bool:
    for block in blocks or ():
        kind = str(_get(block, "kind", "") or "").strip().casefold()
        if kind in _REFERENCE_KINDS:
            return True
    return False


def _matches(requirement: Dict[str, Any], sections: Sequence[str]) -> bool:
    for section in sections:
        normalized = _normalize_heading(section)
        if not normalized:
            continue
        for keyword in requirement["keywords"]:
            if keyword in normalized:
                return True
    return False


def document_level_findings(
    *,
    title: str,
    blocks: Sequence[Any],
    analyzed_ordinals: Iterable[Any],
) -> List[Dict[str, Any]]:
    """返回可核对的结构性缺失（缺引言/方法/结论/参考文献节）。

    每条 finding 的 ``checked_sections`` 是“已分析块实际覆盖到的章节”，因此
    没有任何已分析块时不产生整体缺失断言（无从核对，宁可不报）。
    """
    blocks = list(blocks or ())
    sections = expected_sections(blocks)
    coverage = section_coverage(blocks, analyzed_ordinals)
    checked = list(coverage["covered"])
    if not checked:
        return []

    has_reference_entries = _has_reference_blocks(blocks)
    prefix = f"《{title}》" if str(title or "").strip() else ""
    findings: List[Dict[str, Any]] = []
    for requirement in _REQUIRED_SECTIONS:
        if requirement["key"] == "references" and has_reference_entries:
            continue
        if _matches(requirement, sections):
            continue
        findings.append(
            {
                "category": requirement["category"],
                "severity": requirement["severity"],
                "problem": f"{prefix}缺少「{requirement['label']}」章节",
                "reason": requirement["reason"],
                "locator": {
                    "scope": "document",
                    "expected_section": requirement["label"],
                    "checked_section_count": len(checked),
                },
                "checked_sections": list(checked),
            }
        )
    return findings


__all__ = [
    "document_level_findings",
    "expected_sections",
    "section_coverage",
]
