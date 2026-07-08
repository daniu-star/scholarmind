"""Pipeline 公共工具函数 — paper_pipeline_service 和 paper_review_service 共享。

提取重复模式：
- 用户所有权校验
- 取消机制
- 心跳协程
- 进度计算
- 研究类型映射
- 期刊格式映射
"""
from __future__ import annotations

import asyncio
import structlog
from typing import Any, Optional

logger = structlog.get_logger(__name__)


# ── 研究类型映射（前端值 → Pipeline 值）──
RESEARCH_TYPE_MAP: dict[str, str] = {
    "quantitative": "quantitative",
    "qualitative": "qualitative",
    "mixed": "mixed",
    "computational": "computational",
    "theoretical": "theoretical",
    "interview_report": "interview_report",
    # 中文别名
    "量化研究": "quantitative",
    "质性研究": "qualitative",
    "混合方法": "mixed",
    "混合": "mixed",
    "计算社会科学": "computational",
    "理论论文": "theoretical",
    "访谈报告": "interview_report",
}

# ── 学科 → 期刊格式映射 ──
DISCIPLINE_TO_JOURNAL: dict[str, str] = {
    "communication": "xwycbyj",
    "journalism": "xwycbyj",
    "sociology": "shxyj",
    "psychology": "xwycbyj",
    "education": "xwycbyj",
    "literature": "gjxwj",
    "history": "gjxwj",
    "management": "xwdx",
    "economics": "xwdx",
}

# ── 输出格式映射（前端值 → Pipeline 值）──
OUTPUT_FORMAT_MAP: dict[str, str] = {
    "docx": "word",
    "pdf": "pdf",
    "pdf+docx": "pdf+word",
    "md": "markdown",
    "word": "word",
    "markdown": "markdown",
}


def check_pipeline_ownership(
    pipeline_state: dict[str, Any] | None, user_id: Optional[str]
) -> bool:
    """校验 Pipeline 归属用户。

    Args:
        pipeline_state: 从 repo 获取的 pipeline 状态
        user_id: 请求用户 ID

    Returns:
        True 表示允许访问，False 表示无权限（应返回 404）
    """
    if pipeline_state is None:
        return False
    if user_id is not None and str(pipeline_state.get("user_id")) != str(user_id):
        return False
    return True


def resolve_research_type(raw_type: Optional[str]) -> str:
    """将前端传入的研究类型映射为 Pipeline 内部值。"""
    if raw_type is None:
        return "mixed"
    return RESEARCH_TYPE_MAP.get(raw_type, raw_type)


def resolve_journal_style(discipline: Optional[str], journal_style: Optional[str]) -> str:
    """解析期刊格式：优先显式 journal_style，其次从 discipline 推断。"""
    if journal_style:
        return journal_style
    if discipline:
        return DISCIPLINE_TO_JOURNAL.get(discipline, "xwycbyj")
    return "xwycbyj"


def resolve_output_format(raw_format: Optional[str]) -> str:
    """将前端传入的输出格式映射为 Pipeline 内部值。"""
    if raw_format is None:
        return "word"
    return OUTPUT_FORMAT_MAP.get(raw_format, raw_format)


async def heartbeat_coroutine(
    repo, pipeline_id: str, interval: float, stop_event: asyncio.Event
) -> None:
    """心跳协程：定期更新 updated_at 时间戳，用于检测健康状态。"""
    try:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
                break
            except asyncio.TimeoutError:
                pass
            # 更新心跳
            state = await repo.get(pipeline_id)
            if state and state.get("status") in ("running", "pending"):
                await repo.update_status(pipeline_id, state["status"])
    except asyncio.CancelledError:
        pass


def calculate_pipeline_progress(
    p: dict[str, Any],
    agent_order: list[tuple[str, str, str]],
    default_max_rounds: int = 5,
) -> float:
    """通用 Pipeline 进度计算。

    Args:
        p: pipeline 状态 dict
        agent_order: Agent 执行顺序列表 [(agent_id, label, description), ...]
        default_max_rounds: 默认最大轮数

    Returns:
        0.0 ~ 1.0 的进度值
    """
    if p.get("status") == "completed":
        return 1.0
    if p.get("status") in ("failed", "cancelled"):
        return 0.0

    max_rounds = p.get("config", {}).get("max_rounds", default_max_rounds)
    current_round = p.get("current_round", 1)
    agent_count = len(agent_order)
    current_agent_idx = 0
    if p.get("current_agent"):
        for i, (agent_id, _, _) in enumerate(agent_order):
            if agent_id == p["current_agent"]:
                current_agent_idx = i
                break
    return round(min(0.99, (current_round * agent_count + current_agent_idx) / (max_rounds * agent_count)), 4)


async def cancel_pipeline_task(
    pipeline_id: str,
    tasks: dict[str, asyncio.Task],
    cancel_events: dict[str, asyncio.Event],
    user_id: Optional[str],
    repo,
) -> bool:
    """通用 Pipeline 取消逻辑。

    Returns:
        True 表示取消成功，False 表示不存在或不属于当前用户。
    """
    p = await repo.get(pipeline_id)
    if not p:
        return False
    if user_id is not None and str(p.get("user_id")) != str(user_id):
        return False
    if p["status"] not in ("running", "pending"):
        return False

    event = cancel_events.get(pipeline_id)
    if event:
        event.set()

    task = tasks.get(pipeline_id)
    if task and not task.done():
        task.cancel()

    await repo.update_status(pipeline_id, "cancelled")
    return True
