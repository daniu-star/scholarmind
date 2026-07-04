"""Task data model — Redis-serializable."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict

from models.enums import TaskStatus, Discipline


@dataclass
class Task:
    """A single download task representing one paper to download."""

    task_id: str = ""
    discipline: str = ""
    journal_name: str = ""
    journal_url: str = ""
    year: int = 0
    issue_number: str = ""
    issue_url: str = ""
    paper_title: str = ""
    paper_url: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 0
    retry_count: int = 0
    max_retries: int = 5
    created_at: str = ""
    assigned_worker: str = ""
    started_at: str = ""
    completed_at: str = ""
    last_heartbeat: str = ""
    error_message: str = ""
    error_type: str = ""

    def __post_init__(self):
        if not self.task_id:
            self.task_id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value if isinstance(self.status, TaskStatus) else self.status
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def to_redis_hash(self) -> dict[str, str]:
        """Convert to flat dict for Redis HASH storage."""
        d = self.to_dict()
        return {k: str(v) if not isinstance(v, str) else v for k, v in d.items()}

    @classmethod
    def from_dict(cls, d: dict) -> Task:
        status = d.get("status", "pending")
        if isinstance(status, str):
            try:
                status = TaskStatus(status)
            except ValueError:
                status = TaskStatus.PENDING
        return cls(
            task_id=d.get("task_id", ""),
            discipline=d.get("discipline", ""),
            journal_name=d.get("journal_name", ""),
            journal_url=d.get("journal_url", ""),
            year=int(d.get("year", 0)),
            issue_number=d.get("issue_number", ""),
            issue_url=d.get("issue_url", ""),
            paper_title=d.get("paper_title", ""),
            paper_url=d.get("paper_url", ""),
            status=status,
            priority=int(d.get("priority", 0)),
            retry_count=int(d.get("retry_count", 0)),
            max_retries=int(d.get("max_retries", 5)),
            created_at=d.get("created_at", ""),
            assigned_worker=d.get("assigned_worker", ""),
            started_at=d.get("started_at", ""),
            completed_at=d.get("completed_at", ""),
            last_heartbeat=d.get("last_heartbeat", ""),
            error_message=d.get("error_message", ""),
            error_type=d.get("error_type", ""),
        )

    @classmethod
    def from_redis_hash(cls, d: dict[bytes, str]) -> Task:
        decoded = {}
        for k, v in d.items():
            key = k.decode() if isinstance(k, bytes) else k
            val = v.decode() if isinstance(v, bytes) else v
            decoded[key] = val
        return cls.from_dict(decoded)
