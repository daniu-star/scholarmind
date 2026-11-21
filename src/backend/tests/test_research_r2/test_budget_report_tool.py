"""R2 预算报表工具：只用真实任务行、费用未知就写"未知"（T23 / FR-15）。

``tools/research_budget_report.py`` 是给验收人看的只读报表，最容易出的问题是
"把未知费用写成 0"和"重复事件把用量放大"。这组用例用临时 SQLite 直接喂数据，
不依赖后端跑任务，因此足够快：

* 费用缺失时列值必须是"未知"，且整份输出不得出现 ``0.0000``；
* 同一 ``sequence`` 的重复事件只计一次（重复值 99 不得污染汇总）；
* 完全没有事件的任务，调用数/tokens 显示 ``-``（缺失不补零）；
* 没有匹配任务时不输出空表、不编造基线；
* 路径不存在 / 不是 ScholarMind 库时以非零码退出并给出可读原因。
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[4] / "tools" / "research_budget_report.py"

TASK_COLUMNS = (
    "id TEXT PRIMARY KEY, kind TEXT, status TEXT, attempt_no INTEGER,"
    " billing_group_id TEXT, retry_of TEXT, constraints_json TEXT,"
    " snapshot_summary TEXT, coverage_json TEXT, created_at TEXT, ended_at TEXT"
)

EVENT_COLUMNS = (
    "id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, sequence INTEGER,"
    " attempt_no INTEGER, type TEXT, payload_json TEXT, created_at TEXT"
)


def _create_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE research_tasks ({TASK_COLUMNS})")
    conn.execute(f"CREATE TABLE research_task_events ({EVENT_COLUMNS})")
    return conn


def _insert_task(conn, task_id: str, *, status="partial", budget=None, events=None):
    conn.execute(
        "INSERT INTO research_tasks (id, kind, status, attempt_no, billing_group_id,"
        " retry_of, constraints_json, snapshot_summary, coverage_json, created_at,"
        " ended_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            task_id,
            "review",
            status,
            1,
            "bg_test",
            None,
            json.dumps({"accepted_budget": budget} if budget else {}, ensure_ascii=False),
            json.dumps({"variant": "baseline"}, ensure_ascii=False),
            json.dumps({"ratio": 0.5}, ensure_ascii=False),
            "2026-11-20T10:00:00+00:00",
            "2026-11-20T10:00:10+00:00",
        ),
    )
    for sequence, payload in events or []:
        conn.execute(
            "INSERT INTO research_task_events (task_id, sequence, attempt_no, type,"
            " payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                task_id,
                sequence,
                1,
                "task.progress",
                json.dumps(payload, ensure_ascii=False),
                "2026-11-20T10:00:05+00:00",
            ),
        )
    conn.commit()


def _decode(raw: bytes) -> str:
    # 工具已把 stdout/stderr 都重配成 UTF-8；保留 gbk 兜底只为兼容旧版本行为。
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _run(*args: str) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        timeout=120,
        check=False,
    )
    return subprocess.CompletedProcess(
        completed.args,
        completed.returncode,
        _decode(completed.stdout),
        _decode(completed.stderr),
    )


def _json_tail(stdout: str) -> list:
    """报表的 ``--json`` 明细是最后一段独立 JSON 数组。"""
    start = stdout.rindex("\n[")
    return json.loads(stdout[start:])


def test_unknown_cost_is_reported_as_unknown_and_events_dedupe(tmp_path):
    db_path = tmp_path / "budget.db"
    conn = _create_db(db_path)
    budget = {
        "max_model_calls": 2,
        "max_tokens": 100,
        "max_duration_seconds": 60,
        "max_cost_usd": None,
    }
    _insert_task(
        conn,
        "rt_over",
        budget=budget,
        events=[
            # 同一 sequence 重复投递：只能算第一条。
            (1, {"usage_mode": "cumulative", "model_calls": 2, "tokens": 50}),
            (1, {"usage_mode": "cumulative", "model_calls": 99, "tokens": 999}),
            (2, {"usage_mode": "cumulative", "model_calls": 3, "tokens": 120}),
        ],
    )
    _insert_task(conn, "rt_silent")
    conn.close()

    result = _run("--db", str(db_path), "--json")
    assert result.returncode == 0, result.stderr
    stdout = result.stdout

    assert "任务数：2" in stdout
    assert "## 任务明细" in stdout
    assert "未知" in stdout
    assert "0.0000" not in stdout, "费用未知绝不能显示成 0"
    assert "exceeded" in stdout and "model_calls" in stdout
    # 只有一个变体分组：不生成对比表，也不编造基线数据。
    assert "只有一个变体分组" in stdout

    records = {item["task_id"]: item for item in _json_tail(stdout)}
    assert records["rt_over"]["calls"] == 3, "重复 sequence 不得把用量放大成 99"
    assert records["rt_over"]["tokens"] == 120
    assert records["rt_over"]["cost"] == "未知"
    assert records["rt_over"]["budget"].startswith("exceeded")
    assert records["rt_over"]["budget_recorded"] is True
    # 没有任何用量事件的任务显示缺失，而不是 0。
    assert records["rt_silent"]["calls"] == "-"
    assert records["rt_silent"]["tokens"] == "-"
    assert records["rt_silent"]["cost"] == "未知"
    assert records["rt_silent"]["budget"].endswith("*")


def test_empty_database_prints_no_fabricated_table(tmp_path):
    db_path = tmp_path / "empty.db"
    _create_db(db_path).close()

    result = _run("--db", str(db_path))
    assert result.returncode == 0, result.stderr
    assert "没有匹配的任务" in result.stdout
    assert "## 任务明细" not in result.stdout
    assert "任务数：0" in result.stdout


def test_missing_database_exits_non_zero(tmp_path):
    result = _run("--db", str(tmp_path / "absent.db"))
    assert result.returncode != 0
    assert "数据库不存在" in result.stderr


def test_error_stream_is_utf8_not_console_codepage(tmp_path):
    """D3 回归：诊断信息不能依赖 Windows 控制台编码（cp936 会变替换字符）。"""
    completed = subprocess.run(
        [sys.executable, str(TOOL), "--db", str(tmp_path / "absent.db")],
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode != 0
    text = completed.stderr.decode("utf-8")  # 严格解码：有非法字节就抛错
    assert "数据库不存在" in text
    assert "�" not in text


def test_non_scholarmind_database_is_refused(tmp_path):
    db_path = tmp_path / "other.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE unrelated (id TEXT)")
    conn.commit()
    conn.close()

    result = _run("--db", str(db_path))
    assert result.returncode != 0
    assert "不是 ScholarMind 数据库" in result.stderr


@pytest.mark.parametrize("flags", [(), ("--json",)])
def test_exit_code_is_zero_for_readable_reports(tmp_path, flags):
    db_path = tmp_path / "ok.db"
    conn = _create_db(db_path)
    _insert_task(conn, "rt_ok", status="succeeded")
    conn.close()

    result = _run("--db", str(db_path), *flags)
    assert result.returncode == 0, result.stderr
    assert "rt_ok" in result.stdout
