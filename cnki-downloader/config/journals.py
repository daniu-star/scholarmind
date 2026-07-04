"""5 disciplines × 4 top journals configuration."""

from __future__ import annotations

from typing import Optional


class JournalConfig:
    """A single journal's metadata."""

    def __init__(
        self,
        name: str,
        discipline: str,
        issn: str = "",
        cnki_pcode: str = "",
        issues_per_year: int = 12,
        year_range: tuple[int, int] = (2016, 2026),
    ):
        self.name = name
        self.discipline = discipline
        self.issn = issn
        self.cnki_pcode = cnki_pcode  # CNKI journal product code (e.g., "GJXW")
        self.issues_per_year = issues_per_year
        self.year_range = year_range

    @property
    def navi_url(self) -> str:
        """CNKI journal navigation URL."""
        if self.cnki_pcode:
            return f"https://navi.cnki.net/knavi/journal/{self.cnki_pcode}/detail"
        return ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "discipline": self.discipline,
            "issn": self.issn,
            "cnki_pcode": self.cnki_pcode,
            "issues_per_year": self.issues_per_year,
            "year_range": list(self.year_range),
        }


# ── 5 disciplines × 4 journals ──

DISCIPLINE_JOURNALS: dict[str, list[JournalConfig]] = {
    "新闻传播学": [
        JournalConfig("国际新闻界", "新闻传播学", issn="1002-5685", cnki_pcode="GJXW"),
        JournalConfig("新闻与传播研究", "新闻传播学", issn="1005-2577", cnki_pcode="YANJ"),
        JournalConfig("新闻大学", "新闻传播学", issn="1006-1460", cnki_pcode="XWDX"),
        JournalConfig("当代传播", "新闻传播学", issn="1009-5322", cnki_pcode="DACB"),
    ],
    "人工智能": [
        JournalConfig("模式识别与人工智能", "人工智能", issn="1003-6059", cnki_pcode="MSSB"),
        JournalConfig("自动化学报", "人工智能", issn="0254-4156", cnki_pcode="ZDHB"),
        JournalConfig("计算机研究与发展", "人工智能", issn="1000-1239", cnki_pcode="JFYZ"),
        JournalConfig("中国科学：信息科学", "人工智能", issn="1674-7267", cnki_pcode="PZKX"),
    ],
    "人类学": [
        JournalConfig("人类学学报", "人类学", issn="1000-3193", cnki_pcode="RLXB"),
        JournalConfig("民族研究", "人类学", issn="0256-1891", cnki_pcode="MZYJ"),
        JournalConfig("社会学研究", "人类学", issn="1002-5936", cnki_pcode="SHXJ"),
        JournalConfig("社会", "人类学", issn="1004-8804", cnki_pcode="SHEH"),
    ],
    "计算机科学": [
        JournalConfig("计算机学报", "计算机科学", issn="0254-4164", cnki_pcode="JSJX"),
        JournalConfig("软件学报", "计算机科学", issn="1000-9825", cnki_pcode="RJXB"),
        JournalConfig("计算机研究与发展", "计算机科学", issn="1000-1239", cnki_pcode="JFYZ"),
        JournalConfig("中国科学：信息科学", "计算机科学", issn="1674-7267", cnki_pcode="PZKX"),
    ],
    "化学": [
        JournalConfig("化学学报", "化学", issn="0567-7351", cnki_pcode="HXXB"),
        JournalConfig("高等学校化学学报", "化学", issn="0251-0790", cnki_pcode="GDXH"),
        JournalConfig("分析化学", "化学", issn="0253-3820", cnki_pcode="FXHX"),
        JournalConfig("有机化学", "化学", issn="0253-2786", cnki_pcode="YJHU"),
    ],
}

VALID_DISCIPLINES = list(DISCIPLINE_JOURNALS.keys())


def get_journals_for(discipline: str) -> list[JournalConfig]:
    """Get the 4 top journals for a discipline."""
    return DISCIPLINE_JOURNALS.get(discipline, [])


def get_all_journals() -> list[JournalConfig]:
    """Get all 20 journals across all 5 disciplines."""
    result: list[JournalConfig] = []
    for journals in DISCIPLINE_JOURNALS.values():
        result.extend(journals)
    return result
