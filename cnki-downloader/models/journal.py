"""Journal and Issue data models."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class Journal:
    """Journal metadata for CNKI crawling."""

    name: str
    discipline: str
    issn: str = ""
    cnki_pcode: str = ""
    issues_per_year: int = 12
    year_range: tuple[int, int] = (2016, 2026)

    @property
    def navi_url(self) -> str:
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


@dataclass
class Issue:
    """A single issue of a journal."""

    journal_name: str
    discipline: str
    year: int
    number: str  # e.g. "03" or "第3期"
    url: str = ""
    paper_count: int = 0
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def display_name(self) -> str:
        return f"{self.journal_name} {self.year}年第{self.number}期"
