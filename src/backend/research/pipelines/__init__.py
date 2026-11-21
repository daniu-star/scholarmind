"""研究流水线独立包（FR-10、T04）。

命名空间约定：
- ``pipelines.review``：全文诊断流水线；
- ``pipelines.generation``：提纲扩写/草稿生成流水线。

硬性约束（AT-021）：
- 本包**不得**导入 FastAPI、数据库会话（AsyncSession/ORM）、全局配置单例；
- 模型客户端只通过构造参数注入（``ModelClient`` Protocol），便于注入
  ``FakeClient`` 做离线测试，也保证两条流水线并行时不会串用同一个全局客户端；
- 导入本包不得产生任何 I/O（不连库、不读密钥、不下载模型）。

服务层（``review_workflow`` / ``task_runner``）负责取数、持久化与事件，
本包只负责“把模型能力编排成可核对的结果对象”。
"""
from __future__ import annotations

from .base import (
    DEFAULT_MAX_CALLS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_WINDOW_CODEPOINTS,
    GENERATION_PROMPT_VERSION,
    PIPELINE_VERSION,
    REVIEW_PROMPT_VERSION,
    TOKEN_COUNTER_VERSION,
    BudgetExceeded,
    BudgetTracker,
    EmptyInputError,
    FindingDraft,
    GeneratedSection,
    GenerationOutcome,
    GenerationRequest,
    ModelClient,
    ModelOutputError,
    OutlineSection,
    PipelineError,
    ReviewBlock,
    ReviewOutcome,
    ReviewRequest,
    ReviewWindow,
    as_str_list,
    build_review_windows,
    count_visible_words,
    estimate_tokens,
    parse_json_object,
    split_outline,
    truncate_text,
    within_target_range,
)
from .generation.pipeline import GENERATION_JSON_SCHEMA, GenerationPipeline
from .review.pipeline import REVIEW_JSON_SCHEMA, ReviewPipeline

__all__ = [
    # 流水线
    "ReviewPipeline",
    "GenerationPipeline",
    # 模型客户端契约
    "ModelClient",
    "BudgetTracker",
    "BudgetExceeded",
    "PipelineError",
    "ModelOutputError",
    "EmptyInputError",
    # 诊断 DTO
    "ReviewBlock",
    "ReviewRequest",
    "ReviewWindow",
    "ReviewOutcome",
    "FindingDraft",
    "REVIEW_JSON_SCHEMA",
    # 生成 DTO
    "OutlineSection",
    "GenerationRequest",
    "GeneratedSection",
    "GenerationOutcome",
    "GENERATION_JSON_SCHEMA",
    # 常量与工具
    "PIPELINE_VERSION",
    "REVIEW_PROMPT_VERSION",
    "GENERATION_PROMPT_VERSION",
    "TOKEN_COUNTER_VERSION",
    "DEFAULT_MAX_CALLS",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_WINDOW_CODEPOINTS",
    "build_review_windows",
    "split_outline",
    "count_visible_words",
    "within_target_range",
    "parse_json_object",
    "truncate_text",
    "as_str_list",
    "estimate_tokens",
]
