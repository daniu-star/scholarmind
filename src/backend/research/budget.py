"""预算契约：受理上限、事件用量聚合与超预算判定（R2_INTERFACE_SPEC §4）。

对应 PRD FR-10 / FR-11 / FR-16 与 §9（调用数、输出 tokens、累计耗时、费用）。
本模块只做**纯计算**：不 import ORM 会话、不读写数据库、不联网、不读全局状态
（``default_accepted_budget`` 仅在需要缺省值时延迟读取 ``settings``）。

三条不可放宽的不变量：

1. **费用未知就是 ``None``**：没有价目表时禁止把成本写成 ``0``；报告必须显示
   “未知”，而不是冒充免费。
2. **同一 ``sequence`` 只计一次**：事件重复投递/重放不会放大用量。
3. **缺失值不补零**：只有事件里真实出现的 ``model_calls`` / ``tokens`` /
   ``cost_usd`` 才被采信；没出现就是没记录。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

#: 评估结果与受理快照的版本标记；口径变化时必须递增。
SCHEMA_VERSION = "budget-1.0"

#: constraints_json / snapshot_summary 中保存受理预算的键名。
ACCEPTED_BUDGET_KEY = "accepted_budget"

#: 这些事件类型的用量字段默认按“任务累计值”（可重入、可续跑），而不是增量。
CUMULATIVE_EVENT_TYPES = frozenset({"task.progress"})

#: 不调用模型的任务类型：受理预算是 0 次调用、0 token（仍然记录，不省略）。
NO_MODEL_KINDS = frozenset({"export", "chart"})

_MISSING = object()


@dataclass(frozen=True)
class AcceptedBudget:
    """任务受理时固定的预算上限；``None`` 表示该项未设限（不是 0）。"""

    max_model_calls: Optional[int] = None
    max_tokens: Optional[int] = None
    max_duration_seconds: Optional[float] = None
    max_cost_usd: Optional[float] = None


@dataclass(frozen=True)
class BudgetUsage:
    """从事件累计出来的实测用量。

    ``cost_usd`` 为 ``None`` 表示**费用未知**（缺价目表或事件未报费用），
    永远不能用 0 代替。
    """

    model_calls: int = 0
    tokens: int = 0
    duration_seconds: float = 0.0
    cost_usd: Optional[float] = None


# ── 取值工具（缺省/非法都不编造）─────────────────────────────


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _first_present(data: Mapping[str, Any], keys: Tuple[str, ...]) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return _MISSING


def _to_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _to_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _as_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(tz=None).replace(tzinfo=None)
    return parsed


def _event_field(event: Any, *names: str) -> Any:
    if isinstance(event, Mapping):
        for name in names:
            if name in event:
                return event[name]
        return None
    for name in names:
        if hasattr(event, name):
            return getattr(event, name)
    return None


# ── 受理预算 ────────────────────────────────────────────────


def accepted_budget_from_mapping(raw: Any) -> AcceptedBudget:
    """把快照字典解析成 :class:`AcceptedBudget`（兼容 R1 旧键名）。"""
    data = _as_mapping(raw)
    calls = _to_int(
        _first_present(data, ("max_model_calls", "max_calls"))
        if data
        else _MISSING
    )
    tokens = _to_int(
        _first_present(data, ("max_tokens", "max_output_tokens"))
        if data
        else _MISSING
    )
    duration = _to_float(
        _first_present(data, ("max_duration_seconds", "max_seconds", "timeout_seconds"))
        if data
        else _MISSING
    )
    cost = _to_float(
        _first_present(data, ("max_cost_usd", "max_cost")) if data else _MISSING
    )
    return AcceptedBudget(
        max_model_calls=calls,
        max_tokens=tokens,
        max_duration_seconds=duration,
        max_cost_usd=cost,
    )


def _normalize_kind(kind: Any) -> str:
    """把任务类型规整成小写字符串。

    ``task_service`` 传入的是 ``TaskKind`` 枚举（``str(enum)`` 得到
    ``"TaskKind.EXPORT"``），旧路径可能传 ``"export"`` 或 ``"TaskKind.export"``。
    统一剥掉枚举前缀再比较，避免导出/图表任务被误配成 160 次模型调用。
    """
    raw = getattr(kind, "value", kind)
    value = str(raw or "").strip().lower()
    if "." in value:
        value = value.rsplit(".", 1)[-1]
    return value


def default_accepted_budget(kind: Any = None) -> AcceptedBudget:
    """按任务类型取缺省预算（PRD §9 默认值）。

    只在任务**尚未记录**受理预算时使用；仍会显式写入快照，便于事后核对。
    费用上限默认 ``None``：平台没有可用价目表，不能伪造金额上限。
    """
    from ..config import settings  # 延迟导入：纯计算模块不依赖配置可用性

    value = _normalize_kind(kind)
    if value in NO_MODEL_KINDS:
        calls = 0
        tokens = 0
    elif value == "revision":
        calls = int(settings.RESEARCH_REVISION_MAX_MODEL_CALLS)
        tokens = int(settings.RESEARCH_MAX_TOKENS_PER_TASK)
    else:
        calls = int(settings.RESEARCH_REVIEW_MAX_MODEL_CALLS)
        tokens = int(settings.RESEARCH_MAX_TOKENS_PER_TASK)
    return AcceptedBudget(
        max_model_calls=calls,
        max_tokens=tokens,
        max_duration_seconds=float(settings.RESEARCH_TASK_TIMEOUT_SECONDS),
        max_cost_usd=None,
    )


def accepted_budget(task: Any) -> AcceptedBudget:
    """读取任务受理预算。

    优先级：``constraints_json["accepted_budget"]``（新任务，受理时冻结）→
    ``snapshot_summary["accepted_budget"]``（R1 旧快照，键名 max_calls）→
    按 kind 的 PRD 缺省值。已冻结的快照优先于缺省值，避免会话中途改配置。
    """
    constraints = _as_mapping(getattr(task, "constraints_json", None))
    raw = constraints.get(ACCEPTED_BUDGET_KEY)
    if isinstance(raw, Mapping) and raw:
        return accepted_budget_from_mapping(raw)
    summary = _as_mapping(getattr(task, "snapshot_summary", None))
    raw = summary.get(ACCEPTED_BUDGET_KEY)
    if isinstance(raw, Mapping) and raw:
        return accepted_budget_from_mapping(raw)
    return default_accepted_budget(getattr(task, "kind", None))


def budget_payload(budget: AcceptedBudget, *, legacy_aliases: bool = False) -> Dict[str, Any]:
    """把受理预算转成 JSON 安全字典（写入 constraints_json / 快照）。

    ``legacy_aliases=True`` 时额外写 ``max_calls``（R1 的 review_workflow /
    revision_service 仍读该键），新键始终是权威口径。
    """
    payload: Dict[str, Any] = {
        "max_model_calls": budget.max_model_calls,
        "max_tokens": budget.max_tokens,
        "max_duration_seconds": budget.max_duration_seconds,
        "max_cost_usd": budget.max_cost_usd,
    }
    if legacy_aliases:
        payload["max_calls"] = budget.max_model_calls
    return payload


# ── 事件用量聚合 ────────────────────────────────────────────


def _ordered_events(events: Iterable[Any]) -> List[Tuple[Optional[int], int, Any]]:
    """按 sequence 升序排列并按 sequence 去重（同序号只保留第一条）。"""
    rows: List[Tuple[Optional[int], int, Any]] = []
    seen = set()
    for index, event in enumerate(events or ()):
        sequence = _to_int(_event_field(event, "sequence"))
        key: Tuple[str, Any] = (
            ("sequence", sequence) if sequence is not None else ("index", index)
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append((sequence, index, event))
    numbered = [row for row in rows if row[0] is not None]
    numbered.sort(key=lambda row: int(row[0] or 0))
    return numbered + [row for row in rows if row[0] is None]


def usage_from_events(events: Iterable[Any]) -> BudgetUsage:
    """从任务事件累计用量（纯函数，接受 ORM 行或字典）。

    计数口径：

    - ``usage_mode == "cumulative"``（或 ``task.progress`` 未标注）的用量字段是
      **单次尝试内的累计值**：同一 attempt 取最大值，不做加法；
    - ``usage_mode == "delta"``（诊断每窗口落一条）与其它事件：直接累加；
    - 同一 ``sequence`` 只计一次；乱序输入按 sequence 重排。

    耗时 = 最早与最晚事件时间之差；没有可用于比较的时间戳时记为 0.0，并在
    报告里由调用方决定是否展示为“-”。
    """
    cumulative_calls: Dict[int, int] = {}
    cumulative_tokens: Dict[int, int] = {}
    delta_calls = 0
    delta_tokens = 0
    cost_total = 0.0
    usage_events = 0
    cost_missing = 0
    first_ts: Optional[datetime] = None
    last_ts: Optional[datetime] = None

    for _sequence, _index, event in _ordered_events(events):
        created_at = _as_datetime(_event_field(event, "created_at", "createdAt"))
        if created_at is not None:
            if first_ts is None or created_at < first_ts:
                first_ts = created_at
            if last_ts is None or created_at > last_ts:
                last_ts = created_at

        payload = _as_mapping(_event_field(event, "payload_json", "payload"))
        if not payload:
            continue

        calls = _to_int(
            _first_present(payload, ("model_calls", "calls")) if payload else _MISSING
        )
        tokens = _to_int(
            _first_present(payload, ("tokens", "output_tokens"))
            if payload
            else _MISSING
        )
        if calls is None and tokens is None:
            continue

        usage_events += 1
        event_type = str(_event_field(event, "type", "event_type") or "")
        attempt_no = _to_int(_event_field(event, "attempt_no")) or 0
        mode = str(payload.get("usage_mode") or "").strip().lower()
        if mode == "delta":
            cumulative = False
        elif mode == "cumulative":
            cumulative = True
        else:
            cumulative = event_type in CUMULATIVE_EVENT_TYPES

        if calls is not None:
            if cumulative:
                cumulative_calls[attempt_no] = max(
                    cumulative_calls.get(attempt_no, 0), calls
                )
            else:
                delta_calls += calls
        if tokens is not None:
            if cumulative:
                cumulative_tokens[attempt_no] = max(
                    cumulative_tokens.get(attempt_no, 0), tokens
                )
            else:
                delta_tokens += tokens

        raw_cost = _first_present(payload, ("cost_usd", "cost"))
        if raw_cost is _MISSING:
            cost_missing += 1
            continue
        cost = _to_float(raw_cost)
        if cost is None:
            # 显式 null / 非法值 = 费用未知，绝不能当 0。
            cost_missing += 1
        else:
            cost_total += cost

    model_calls = delta_calls + sum(cumulative_calls.values())
    tokens = delta_tokens + sum(cumulative_tokens.values())
    cost_known = usage_events > 0 and cost_missing == 0
    duration = 0.0
    if first_ts is not None and last_ts is not None:
        duration = max(0.0, (last_ts - first_ts).total_seconds())
    return BudgetUsage(
        model_calls=model_calls,
        tokens=tokens,
        duration_seconds=round(duration, 3),
        cost_usd=round(cost_total, 6) if cost_known else None,
    )


# ── 超预算判定 ──────────────────────────────────────────────


def _check_int(limit: Optional[int], used: int) -> Dict[str, Any]:
    over = limit is not None and used > limit
    ratio = round(used / limit, 4) if limit not in (None, 0) else None
    return {"limit": limit, "used": used, "over": over, "ratio": ratio}


def _check_float(limit: Optional[float], used: Optional[float]) -> Dict[str, Any]:
    over = limit is not None and used is not None and used > limit
    ratio = round(used / limit, 4) if limit not in (None, 0) and used is not None else None
    return {"limit": limit, "used": used, "over": over, "ratio": ratio}


def evaluate_budget(budget: AcceptedBudget, usage: BudgetUsage) -> Dict[str, Any]:
    """判定是否超预算（纯函数，可直接落盘到 ``snapshot_summary``）。

    返回 ``{"state": "within"|"exceeded", "overruns": [...], "cost_known": bool,
    "budget": ..., "usage": ..., "checks": ...}``。`state="exceeded"` 时执行器
    必须把原本会 succeeded 的任务降级为 partial/needs_input。
    """
    if not isinstance(budget, AcceptedBudget):
        budget = accepted_budget_from_mapping(budget)
    if not isinstance(usage, BudgetUsage):
        usage = BudgetUsage()

    checks = {
        "model_calls": _check_int(budget.max_model_calls, usage.model_calls),
        "tokens": _check_int(budget.max_tokens, usage.tokens),
        "duration_seconds": _check_float(
            budget.max_duration_seconds, usage.duration_seconds
        ),
        "cost_usd": _check_float(budget.max_cost_usd, usage.cost_usd),
    }
    overruns = [name for name, item in checks.items() if item["over"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "exceeded" if overruns else "within",
        "overruns": overruns,
        "cost_known": usage.cost_usd is not None,
        "budget": budget_payload(budget),
        "usage": {
            "model_calls": usage.model_calls,
            "tokens": usage.tokens,
            "duration_seconds": usage.duration_seconds,
            "cost_usd": usage.cost_usd,
        },
        "checks": checks,
    }


_LABELS = {
    "model_calls": "模型调用",
    "tokens": "输出 tokens",
    "duration_seconds": "任务耗时",
    "cost_usd": "费用",
}


def overrun_details(evaluation: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """把超限项整理成结构化的 ``[{field, used, limit}]``（用于 error details）。"""
    checks = _as_mapping(evaluation.get("checks"))
    details: List[Dict[str, Any]] = []
    for name in evaluation.get("overruns") or []:
        item = _as_mapping(checks.get(name))
        details.append(
            {"field": name, "used": item.get("used"), "limit": item.get("limit")}
        )
    return details


def overrun_messages(evaluation: Mapping[str, Any]) -> List[str]:
    """把超限项转成可直接放进 warnings/unresolved 的中文说明。"""
    checks = _as_mapping(evaluation.get("checks"))
    messages: List[str] = []
    for name in evaluation.get("overruns") or []:
        item = _as_mapping(checks.get(name))
        used = item.get("used")
        limit = item.get("limit")
        label = _LABELS.get(str(name), str(name))
        if name == "duration_seconds":
            text = f"预算超限：{label}已用 {float(used or 0):.1f}s，上限 {float(limit or 0):.1f}s"
        else:
            text = f"预算超限：{label}已用 {used}，上限 {limit}"
        messages.append(f"{text}（overrun: {name}）")
    return messages


__all__ = [
    "ACCEPTED_BUDGET_KEY",
    "CUMULATIVE_EVENT_TYPES",
    "NO_MODEL_KINDS",
    "SCHEMA_VERSION",
    "AcceptedBudget",
    "BudgetUsage",
    "accepted_budget",
    "accepted_budget_from_mapping",
    "budget_payload",
    "default_accepted_budget",
    "evaluate_budget",
    "overrun_details",
    "overrun_messages",
    "usage_from_events",
]
