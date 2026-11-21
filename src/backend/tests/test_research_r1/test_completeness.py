"""T15 / AT-014·AT-015·AT-027：结构性完整性检查（纯函数）。

R1_INTERFACE_SPEC §2.2 的硬约束：
- ``expected_sections`` 去重且保持出现顺序；
- ``section_coverage`` 只用真实 analyzed ordinals，不遗漏、不虚报；
- ``document_level_findings`` 只报“按块级 section_path 可核对”的结构缺失，
  且 ``checked_sections`` 必须是真实已分析范围；没有任何已分析块时不得下结论。
"""
from __future__ import annotations

import pytest

from ...research.completeness import (
    document_level_findings,
    expected_sections,
    section_coverage,
)


def block(ordinal: int, section_path: str, *, text: str = "正文", kind: str = "paragraph"):
    """用最小映射模拟解析块；纯函数只读取 ordinal/section_path/kind。"""
    return {
        "ordinal": ordinal,
        "section_path": section_path,
        "text": text,
        "kind": kind,
    }


def paper() -> list[dict]:
    return [
        block(0, "1 引言"),
        block(1, "1 引言"),
        block(2, "2 研究方法"),
        block(3, "2 研究方法"),
        block(4, "3 结论"),
        block(5, "参考文献"),
    ]


class TestExpectedSections:
    def test_dedupes_and_preserves_first_seen_order(self):
        blocks = [
            block(0, "方法"),
            block(1, "引言"),
            block(2, "方法"),
            block(3, "结论"),
        ]

        assert expected_sections(blocks) == ["方法", "引言", "结论"]

    def test_ignores_empty_and_whitespace_paths(self):
        blocks = [
            block(0, ""),
            block(1, "   "),
            block(2, "引言"),
        ]

        assert expected_sections(blocks) == ["引言"]

    def test_accepts_mapping_blocks(self):
        blocks = [
            {"ordinal": 0, "section_path": "方法"},
            {"ordinal": 1, "section_path": "结论"},
        ]

        assert expected_sections(blocks) == ["方法", "结论"]

    def test_empty_and_none_inputs_are_safe(self):
        assert expected_sections([]) == []
        assert expected_sections(None) == []


class TestSectionCoverage:
    def test_covered_and_missing_follow_expected_order(self):
        coverage = section_coverage(paper(), [0, 2, 3])

        assert coverage["expected"] == ["1 引言", "2 研究方法", "3 结论", "参考文献"]
        assert coverage["covered"] == ["1 引言", "2 研究方法"]
        assert coverage["missing"] == ["3 结论", "参考文献"]

    def test_analyzed_outside_expected_does_not_invent_sections(self):
        coverage = section_coverage(paper(), [99, "junk", None])

        assert coverage["covered"] == []
        assert coverage["missing"] == coverage["expected"]

    def test_string_ordinals_are_coerced(self):
        coverage = section_coverage(paper(), ["0", "5"])

        assert coverage["covered"] == ["1 引言", "参考文献"]

    def test_duplicate_ordinals_do_not_double_count(self):
        coverage = section_coverage(paper(), [2, 2, 2, 3])

        assert coverage["covered"] == ["2 研究方法"]

    def test_empty_blocks_yield_empty_coverage(self):
        assert section_coverage([], [0, 1]) == {
            "expected": [],
            "covered": [],
            "missing": [],
        }


class TestDocumentLevelFindings:
    def test_complete_structure_has_no_findings(self):
        assert document_level_findings(
            title="完整论文", blocks=paper(), analyzed_ordinals=range(6)
        ) == []

    def test_missing_sections_are_reported_with_document_locator(self):
        blocks = [block(0, "1 引言"), block(1, "1 引言")]

        findings = document_level_findings(
            title="缺章节论文", blocks=blocks, analyzed_ordinals=[0, 1]
        )

        labels = {item["problem"] for item in findings}
        assert any("方法" in label for label in labels)
        assert any("结论" in label for label in labels)
        assert any("参考文献" in label for label in labels)
        for item in findings:
            assert item["severity"] == "major"
            assert item["locator"]["scope"] == "document"
            assert item["checked_sections"] == ["1 引言"]
            assert set(item) == {
                "category",
                "severity",
                "problem",
                "reason",
                "locator",
                "checked_sections",
            }

    def test_no_analyzed_blocks_means_no_document_claim(self):
        assert (
            document_level_findings(
                title="未分析论文", blocks=paper(), analyzed_ordinals=[]
            )
            == []
        )

    def test_checked_sections_is_the_real_analyzed_range(self):
        blocks = [
            block(0, "1 引言"),
            block(1, "2 研究方法"),
            block(2, "2 研究方法"),
            block(3, "附录"),
        ]

        findings = document_level_findings(
            title="部分分析", blocks=blocks, analyzed_ordinals=[1, 2]
        )

        assert findings
        assert all(item["checked_sections"] == ["2 研究方法"] for item in findings)
        # 方法章节本身存在且已被分析，不应报“缺方法”。
        assert not any("方法" in item["problem"] for item in findings)
        # 引言存在但未被分析：这是“未评估”，不是“缺失”，不得断言缺失。
        assert not any("引言" in item["problem"] for item in findings)

    def test_reference_entries_count_as_reference_section(self):
        blocks = [
            block(0, "引言"),
            block(1, "方法"),
            block(2, "结论"),
            block(3, "", kind="reference"),
        ]

        findings = document_level_findings(
            title="条目式参考文献", blocks=blocks, analyzed_ordinals=range(4)
        )

        assert not any("参考文献" in item["problem"] for item in findings)

    @pytest.mark.parametrize(
        "heading",
        ["1 引言", "## 引言", "一、引言", "1. Introduction", "【引言】"],
    )
    def test_numbered_and_markdown_headings_are_recognized(self, heading):
        blocks = [
            block(0, heading),
            block(1, "材料与方法"),
            block(2, "结语"),
            block(3, "参考文献"),
        ]

        findings = document_level_findings(
            title="标题变体", blocks=blocks, analyzed_ordinals=range(4)
        )

        assert not any("引言" in item["problem"] for item in findings)

    def test_findings_are_structural_not_subjective(self):
        blocks = [block(0, "引言")]

        findings = document_level_findings(
            title="纯结构", blocks=blocks, analyzed_ordinals=[0]
        )

        text = " ".join(
            str(item["problem"]) + str(item["reason"]) for item in findings
        )
        for banned in ("应该更好", "写得差", "质量低下", "建议重写全文"):
            assert banned not in text
        assert "section_path" in text

    def test_empty_title_still_produces_valid_problem_text(self):
        blocks = [block(0, "引言")]

        findings = document_level_findings(
            title="", blocks=blocks, analyzed_ordinals=[0]
        )

        assert findings
        assert all(item["problem"].strip() for item in findings)