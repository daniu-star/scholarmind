"""预算与流程增益对比报表（T23 / AT-056）。

用法::

    ./.venv/Scripts/python.exe tools/research_budget_report.py --db data/scholarmind.db

只读 SQLite 的任务行（``research_tasks``）与事件（``research_task_events``），
不改库、不联网、不重新读模型。输出两张表：

1. **任务明细**：每个任务的调用数、tokens、事件跨度耗时、覆盖率、预算状态、费用；
2. **基线 / 变体对比**：按 ``snapshot_summary["variant"]``（或
   ``experiment_variant`` / ``optimization`` / ``optimization_tag``）分组，
   行是指标、列是变体，基线排在最左。

诚实口径（与 ``budget.py`` 一致）：

- 没有真实用量事件时调用数/tokens 显示 ``-``，不拿 0 冒充“测过”；
- 费用没有价目表时显示 **未知**，绝不显示 0；
- 覆盖率缺失（例如导出任务）显示 ``-``，不从字数反推；
- 受理预算缺记录时状态加 ``*`` 标记“上限来自进程缺省值”，便于区分历史任务。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence, Tuple

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from backend.research.budget import (  # noqa: E402  - 需要先补 sys.path
    ACCEPTED_BUDGET_KEY,
    accepted_budget,
    evaluate_budget,
    usage_from_events,
)

MISSING = "-"
UNKNOWN_COST = "未知"
DEFAULT_VARIANT = "未标注"

_VARIANT_KEYS = (
    "variant",
    "experiment_variant",
    "optimization",
    "optimization_tag",
    "experiment",
)


# ── 只读装载 ────────────────────────────────────────────────


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"数据库不存在：{path}")
    # mode=ro：整个报表过程不允许任何写操作。
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _json_object(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _load_tasks(
    conn: sqlite3.Connection, *, kind: Optional[str], status: Optional[str], limit: int
) -> List[sqlite3.Row]:
    if not _table_exists(conn, "research_tasks"):
        raise SystemExit("数据库里没有 research_tasks 表：不是 ScholarMind 数据库")
    clauses: List[str] = []
    params: List[Any] = []
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if status:
        clauses.append("status = ?")
        params.append(status)
    sql = (
        "SELECT id, kind, status, attempt_no, billing_group_id, retry_of,"
        " constraints_json, snapshot_summary, coverage_json, created_at, ended_at"
        " FROM research_tasks"
    )
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC, id"
    sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, params).fetchall()


def _load_events(conn: sqlite3.Connection, task_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT sequence, attempt_no, type, payload_json, created_at"
        " FROM research_task_events WHERE task_id = ? ORDER BY sequence",
        (task_id,),
    ).fetchall()
    events: List[Dict[str, Any]] = []
    for row in rows:
        events.append(
            {
                "sequence": row["sequence"],
                "attempt_no": row["attempt_no"],
                "type": row["type"],
                "payload": _json_object(row["payload_json"]),
                "created_at": row["created_at"],
            }
        )
    return events


# ── 口径计算 ────────────────────────────────────────────────


def _variant_of(summary: Dict[str, Any], key: str) -> str:
    for candidate in (key, *_VARIANT_KEYS):
        raw = summary.get(candidate) if candidate else None
        if isinstance(raw, (str, int, float)) and str(raw).strip():
            return str(raw).strip()
    return DEFAULT_VARIANT


def _budget_recorded(task: sqlite3.Row) -> bool:
    for raw in (task["constraints_json"], task["snapshot_summary"]):
        data = _json_object(raw)
        candidate = data.get(ACCEPTED_BUDGET_KEY)
        if isinstance(candidate, dict) and candidate:
            return True
    return False


def _usage_flags(events: Sequence[Dict[str, Any]]) -> Tuple[bool, bool]:
    """事件里是否真实出现过调用数 / tokens（决定显示数值还是 "-"）。"""

    calls_known = False
    tokens_known = False
    for event in events:
        payload = event.get("payload") or {}
        if isinstance(payload, dict):
            if payload.get("model_calls") is not None or payload.get("calls") is not None:
                calls_known = True
            if payload.get("tokens") is not None or payload.get("output_tokens") is not None:
                tokens_known = True
    return calls_known, tokens_known


def _parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(tz=None).replace(tzinfo=None)
    return parsed


def _duration_text(
    *,
    event_seconds: float,
    created_at: Any,
    ended_at: Any,
) -> str:
    if event_seconds > 0:
        return f"{event_seconds:.1f}"
    started = _parse_time(created_at)
    ended = _parse_time(ended_at)
    if started is not None and ended is not None:
        seconds = (ended - started).total_seconds()
        return f"{max(0.0, seconds):.1f}"
    return MISSING


def _coverage_text(raw: Any) -> str:
    data = _json_object(raw)
    if not data:
        return MISSING
    analyzed = data.get("analyzed_eligible_blocks")
    expected = data.get("expected_eligible_blocks")
    if not isinstance(analyzed, int) or not isinstance(expected, int):
        return MISSING
    if expected <= 0:
        return f"{analyzed}/0"
    return f"{analyzed}/{expected} ({analyzed / expected:.0%})"


def _coverage_ratio(raw: Any) -> Optional[float]:
    data = _json_object(raw)
    analyzed = data.get("analyzed_eligible_blocks")
    expected = data.get("expected_eligible_blocks")
    if not isinstance(analyzed, int) or not isinstance(expected, int):
        return None
    if expected <= 0:
        return 1.0 if analyzed >= 0 else None
    return analyzed / expected


def _task_record(task: sqlite3.Row, events: Sequence[Dict[str, Any]], variant_key: str) -> Dict[str, Any]:
    summary = _json_object(task["snapshot_summary"])
    constraints = _json_object(task["constraints_json"])
    usage = usage_from_events(events)
    calls_known, tokens_known = _usage_flags(events)
    budget = accepted_budget(
        SimpleNamespace(
            kind=task["kind"],
            constraints_json=constraints,
            snapshot_summary=summary,
        )
    )
    evaluation = evaluate_budget(budget, usage)
    recorded = _budget_recorded(task)
    state = str(evaluation.get("state"))
    overruns = [str(item) for item in evaluation.get("overruns") or []]
    status_text = state
    if overruns:
        status_text += f"[{'/'.join(overruns)}]"
    if not recorded:
        status_text += "*"
    return {
        "task_id": task["id"],
        "kind": task["kind"],
        "status": task["status"],
        "attempt_no": int(task["attempt_no"] or 0),
        "variant": _variant_of(summary, variant_key),
        "calls": usage.model_calls if calls_known else MISSING,
        "tokens": usage.tokens if tokens_known else MISSING,
        "duration": _duration_text(
            event_seconds=usage.duration_seconds,
            created_at=task["created_at"],
            ended_at=task["ended_at"],
        ),
        "coverage": _coverage_text(task["coverage_json"]),
        "coverage_ratio": _coverage_ratio(task["coverage_json"]),
        "budget": status_text,
        "cost": UNKNOWN_COST if usage.cost_usd is None else f"{usage.cost_usd:.4f}",
        "budget_recorded": recorded,
    }


# ── 渲染 ────────────────────────────────────────────────────


def _display_width(text: str) -> int:
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def _pad(text: str, width: int, *, right: bool) -> str:
    gap = max(0, width - _display_width(text))
    return (" " * gap + text) if right else (text + " " * gap)


def _render_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    cells = [[str(cell) for cell in row] for row in rows]
    widths = [_display_width(head) for head in headers]
    for row in cells:
        for index, cell in enumerate(row):
            if index < len(widths):
                widths[index] = max(widths[index], _display_width(cell))
    lines = [
        " | ".join(_pad(head, widths[i], right=i > 0) for i, head in enumerate(headers)),
        "-+-".join("-" * width for width in widths),
    ]
    for row in cells:
        lines.append(
            " | ".join(
                _pad(cell, widths[i], right=i > 0) for i, cell in enumerate(row)
            )
        )
    return "\n".join(lines)


def _mean(values: Sequence[Optional[float]]) -> Optional[float]:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present) / len(present)


def _aggregate(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    calls = [float(r["calls"]) for r in records if isinstance(r["calls"], (int, float))]
    tokens = [float(r["tokens"]) for r in records if isinstance(r["tokens"], (int, float))]
    durations = [float(r["duration"]) for r in records if isinstance(r["duration"], str) and r["duration"] != MISSING]
    ratios = [r["coverage_ratio"] for r in records if r["coverage_ratio"] is not None]
    states = [str(r["budget"]).rstrip("*").split("[")[0] for r in records]
    return {
        "tasks": len(records),
        "calls_sum": int(sum(calls)) if calls else None,
        "calls_mean": _mean(calls),
        "tokens_sum": int(sum(tokens)) if tokens else None,
        "tokens_mean": _mean(tokens),
        "duration_mean": _mean(durations),
        "coverage_mean": _mean(ratios),
        "within": states.count("within"),
        "exceeded": states.count("exceeded"),
        "unknown_state": sum(1 for state in states if state not in {"within", "exceeded"}),
    }


def _format_metric(value: Optional[float], *, digits: int = 1, suffix: str = "") -> str:
    if value is None:
        return MISSING
    if digits <= 0:
        return f"{int(round(value))}{suffix}"
    return f"{value:.{digits}f}{suffix}"


def _variant_order(variants: Sequence[str]) -> List[str]:
    def key(name: str) -> Tuple[int, str]:
        lowered = name.lower()
        if lowered in {"baseline", "base", "基线"}:
            return (0, lowered)
        if name == DEFAULT_VARIANT:
            return (2, lowered)
        return (1, lowered)

    return sorted(variants, key=key)


def _render_comparison(records: Sequence[Dict[str, Any]]) -> Optional[str]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record["variant"]), []).append(record)
    if len(grouped) < 2:
        return None
    variants = _variant_order(list(grouped))
    aggregates = {name: _aggregate(grouped[name]) for name in variants}

    rows = [
        ["任务数", *[str(aggregates[name]["tasks"]) for name in variants]],
        [
            "调用数（合计）",
            *[_format_metric(aggregates[name]["calls_sum"], digits=0) for name in variants],
        ],
        [
            "调用数（均值）",
            *[_format_metric(aggregates[name]["calls_mean"], digits=1) for name in variants],
        ],
        [
            "tokens（合计）",
            *[_format_metric(aggregates[name]["tokens_sum"], digits=0) for name in variants],
        ],
        [
            "tokens（均值）",
            *[_format_metric(aggregates[name]["tokens_mean"], digits=0) for name in variants],
        ],
        [
            "耗时均值(s)",
            *[_format_metric(aggregates[name]["duration_mean"], digits=1) for name in variants],
        ],
        [
            "覆盖率",
            *[
                _format_metric(
                    None
                    if aggregates[name]["coverage_mean"] is None
                    else aggregates[name]["coverage_mean"] * 100,
                    digits=0,
                    suffix="%",
                )
                for name in variants
            ],
        ],
        [
            "预算状态",
            *[
                f"{aggregates[name]['within']} / {aggregates[name]['exceeded']}"
                for name in variants
            ],
        ],
    ]
    return _render_table(["指标", *variants], rows)


def _render_detail(records: Sequence[Dict[str, Any]]) -> str:
    rows: List[Sequence[Any]] = []
    for record in records:
        rows.append(
            [
                str(record["task_id"]),
                str(record["kind"]),
                str(record["status"]),
                str(record["variant"]),
                str(record["calls"]),
                str(record["tokens"]),
                str(record["duration"]),
                str(record["coverage"]),
                str(record["budget"]),
                str(record["cost"]),
            ]
        )
    return _render_table(
        [
            "任务",
            "类型",
            "终态",
            "变体",
            "调用数",
            "tokens",
            "耗时(s)",
            "覆盖率",
            "预算状态",
            "费用(USD)",
        ],
        rows,
    )


def run(args: argparse.Namespace) -> int:
    # Windows 控制台默认 cp936：中文列名与诊断信息重定向到管道时会编码失败，
    # stdout/stderr 必须一起按 UTF-8 输出，否则报错信息会变成替换字符。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    path = Path(args.db)
    conn = _connect(path)
    try:
        tasks = _load_tasks(
            conn, kind=args.kind, status=args.status, limit=max(1, int(args.limit))
        )
        records = [
            _task_record(task, _load_events(conn, task["id"]), args.variant_key)
            for task in tasks
        ]
    finally:
        conn.close()

    print(f"数据库：{path}")
    print(f"任务数：{len(records)}（只读；事件按 sequence 去重累计）")
    if not records:
        print("没有匹配的任务：不输出空表，也不编造基线数据。")
        return 0

    print()
    print("## 任务明细")
    print(_render_detail(records))

    comparison = _render_comparison(records)
    if comparison:
        print()
        print("## 基线 / 变体对比（基线在最左）")
        print(comparison)
        print(
            "说明：变体标签取自 snapshot_summary 的 variant/experiment_variant/"
            "optimization*；预算状态中的 * 表示任务未记录受理预算，上限来自进程缺省值。"
        )
    else:
        print()
        print("## 基线 / 变体对比")
        print("只有一个变体分组：未构成对比，不生成对比表（先跑基线再跑变体）。")

    if args.json:
        print()
        print(json.dumps(records, ensure_ascii=False, indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="预算与流程增益对比报表（只读 SQLite；缺失显示 '-'，费用未知显示 '未知'）"
    )
    parser.add_argument("--db", required=True, help="SQLite 数据库路径（只读打开）")
    parser.add_argument("--kind", default=None, help="只统计该任务类型，例如 review")
    parser.add_argument("--status", default=None, help="只统计该终态，例如 partial")
    parser.add_argument("--variant-key", default="variant", help="自定义变体标签键")
    parser.add_argument("--limit", type=int, default=200, help="最多读取多少个任务")
    parser.add_argument("--json", action="store_true", help="追加 JSON 明细（便于机读）")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
