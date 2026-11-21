"""提纲扩写/草稿生成流水线命名空间（FR-10）。"""
from __future__ import annotations

from .pipeline import GENERATION_JSON_SCHEMA, MAX_SECTION_CODEPOINTS, GenerationPipeline

__all__ = ["GenerationPipeline", "GENERATION_JSON_SCHEMA", "MAX_SECTION_CODEPOINTS"]
