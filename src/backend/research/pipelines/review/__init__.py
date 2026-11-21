"""全文诊断流水线命名空间（FR-07）。"""
from __future__ import annotations

from .pipeline import MAX_FINDINGS_PER_WINDOW, REVIEW_JSON_SCHEMA, ReviewPipeline

__all__ = ["ReviewPipeline", "REVIEW_JSON_SCHEMA", "MAX_FINDINGS_PER_WINDOW"]
