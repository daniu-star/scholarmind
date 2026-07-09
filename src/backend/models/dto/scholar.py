"""学术文献共享 DTO（统一 arxiv / semantic_scholar 的 AcademicPaper 类型）"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class AcademicPaper:
    """统一的学术文献数据结构。

    source 标识来源 ("arxiv" / "semantic_scholar")，
    citation_count 在 arXiv 来源时固定为 0。
    """

    title: str
    authors: list[str]
    year: Optional[int]
    abstract: Optional[str]
    citation_count: int
    url: str
    source: str
    doi: Optional[str] = None
    pdf_url: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)
