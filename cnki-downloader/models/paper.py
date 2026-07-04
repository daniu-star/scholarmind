"""Paper and metadata data models."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict

from models.enums import TaskStatus


@dataclass
class Paper:
    """Represents a single academic paper."""

    paper_id: str = ""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int = 0
    journal_name: str = ""
    discipline: str = ""
    issue_number: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    doi: str = ""
    cnki_url: str = ""
    pdf_download_url: str = ""
    file_format: str = ""  # "pdf" or "caj"
    pdf_path: str = ""
    txt_path: str = ""
    pdf_size_bytes: int = 0
    pdf_page_count: int = 0
    metadata_path: str = ""
    download_status: TaskStatus = TaskStatus.PENDING
    downloaded_at: str = ""

    def __post_init__(self):
        if not self.paper_id:
            self.paper_id = str(uuid.uuid4())

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> Paper:
        return cls(
            paper_id=d.get("paper_id", ""),
            title=d.get("title", ""),
            authors=d.get("authors", []),
            year=int(d.get("year", 0)),
            journal_name=d.get("journal_name", ""),
            discipline=d.get("discipline", ""),
            issue_number=d.get("issue_number", ""),
            abstract=d.get("abstract", ""),
            keywords=d.get("keywords", []),
            doi=d.get("doi", ""),
            cnki_url=d.get("cnki_url", ""),
            pdf_download_url=d.get("pdf_download_url", ""),
            file_format=d.get("file_format", ""),
            pdf_path=d.get("pdf_path", ""),
            txt_path=d.get("txt_path", ""),
            pdf_size_bytes=int(d.get("pdf_size_bytes", 0)),
            pdf_page_count=int(d.get("pdf_page_count", 0)),
            metadata_path=d.get("metadata_path", ""),
            download_status=TaskStatus(d.get("download_status", "pending")),
            downloaded_at=d.get("downloaded_at", ""),
        )


@dataclass
class PaperMetadata:
    """Sidecar JSON metadata for a downloaded paper."""

    paper: Paper
    download_history: list[dict] = field(default_factory=list)
    checks: dict = field(default_factory=dict)

    def log_attempt(self, status: str, error: str = "") -> None:
        self.download_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "error": error,
        })

    def to_dict(self) -> dict:
        return {
            "paper": self.paper.to_dict(),
            "download_history": self.download_history,
            "checks": self.checks,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
