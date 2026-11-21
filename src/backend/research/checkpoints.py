"""T15 分析检查点读写（research_task_attempts.checkpoint_json）。

只做持久化读写，不做业务判断：

- :func:`load_checkpoint` 按契约返回四个键；没有记录时返回空结构，不抛异常；
- :func:`load_checkpoint_payload` 额外保留 ``findings`` 等扩展键，供诊断工作流
  在重试时恢复已产出的诊断项（``load_checkpoint`` 的公开结构不受影响）；
- :func:`save_checkpoint` 按 ``task_id + attempt_no`` 定位当前 attempt 行，行不存在
  时静默跳过；定位条件本身即“与当前 attempt 的 fencing 一致”，不会把检查点写到
  别的任务或别的 attempt 上。

调用方负责事务提交；本模块只 ``flush``，保证同一事务内的后续读取可见。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import TaskAttempt

CHECKPOINT_KEYS = ("analyzed_ordinals", "cursor", "model_calls", "tokens")


def _as_int(value: Any, default: int = 0) -> int:
    """把检查点里的计数安全转成非负整数（损坏数据回退默认值）。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def _empty() -> Dict[str, Any]:
    return {"analyzed_ordinals": [], "cursor": 0, "model_calls": 0, "tokens": 0}


def _normalize(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """补齐四个契约键；未知扩展键（如 findings）原样保留。"""
    if not isinstance(payload, dict):
        return _empty()
    ordinals: List[int] = []
    raw = payload.get("analyzed_ordinals")
    if isinstance(raw, (list, tuple)):
        for item in raw:
            try:
                ordinals.append(int(item))
            except (TypeError, ValueError):
                continue
    normalized: Dict[str, Any] = {
        "analyzed_ordinals": list(dict.fromkeys(ordinals)),
        "cursor": _as_int(payload.get("cursor")),
        "model_calls": _as_int(payload.get("model_calls")),
        "tokens": _as_int(payload.get("tokens")),
    }
    for key, value in payload.items():
        if key not in normalized:
            normalized[key] = value
    return normalized


async def _find_attempt(
    db: AsyncSession, task_id: Optional[str], attempt_no: Optional[int]
) -> Optional[TaskAttempt]:
    """定位 attempt：优先 task_id + attempt_no；未指定序号时取最近一个有检查点的 attempt。"""
    stmt = select(TaskAttempt)
    if task_id:
        stmt = stmt.where(TaskAttempt.task_id == task_id)
    if attempt_no is not None:
        stmt = stmt.where(TaskAttempt.attempt_no == _as_int(attempt_no))
        stmt = stmt.order_by(TaskAttempt.started_at.desc(), TaskAttempt.id.desc())
    else:
        stmt = stmt.where(TaskAttempt.checkpoint_json.is_not(None))
        if task_id:
            stmt = stmt.order_by(
                TaskAttempt.attempt_no.desc(), TaskAttempt.started_at.desc()
            )
        else:
            # 没有 task_id 时无法安全归属，返回空结构。
            return None
    result = await db.execute(stmt.limit(1))
    return result.scalars().first()


async def load_checkpoint(
    db: AsyncSession, task_id: str, attempt_no: Optional[int] = None
) -> Dict[str, Any]:
    """读取检查点，返回 ``analyzed_ordinals/cursor/model_calls/tokens`` 四个键。

    未找到记录时返回空结构（``attempt_no`` 省略时取该任务最近一个带检查点的
    attempt，这样重试（新 attempt）也能续跑）。
    """
    payload = await load_checkpoint_payload(db, task_id, attempt_no)
    return {key: payload[key] for key in CHECKPOINT_KEYS}


async def load_checkpoint_payload(
    db: AsyncSession, task_id: str, attempt_no: Optional[int] = None
) -> Dict[str, Any]:
    """读取完整检查点负载（含工作流写入的 ``findings`` 扩展键）。"""
    attempt = await _find_attempt(db, task_id, attempt_no)
    if attempt is None:
        return _empty()
    return _normalize(attempt.checkpoint_json)


async def save_checkpoint(
    db: AsyncSession,
    attempt_no: int,
    payload: Dict[str, Any],
    *,
    task_id: Optional[str] = None,
) -> None:
    """写入检查点；attempt 行不存在时静默跳过（重试竞态下不报错）。

    ``task_id`` 用于把写入限定在目标任务上；定位条件与 ``attempt_no`` 一起构成
    fencing 校验，避免写到其它任务或旧 attempt。
    """
    if not isinstance(payload, dict):
        raise TypeError("checkpoint payload 必须是 dict")
    attempt = await _find_attempt(db, task_id, attempt_no)
    if attempt is None:
        return
    attempt.checkpoint_json = dict(payload)
    await db.flush()


__all__ = [
    "CHECKPOINT_KEYS",
    "load_checkpoint",
    "load_checkpoint_payload",
    "save_checkpoint",
]
