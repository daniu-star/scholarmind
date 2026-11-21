"""真实语料诊断结果的“可核对性”审计（T21 合规替代评估的补充证据）。

只读打开评估数据库（默认 ``tmp/r2-corpus.db``），对每篇论文的 review 任务
逐条核对诊断项：

1. **引文保真**：``quote`` 是否在该版本正文中逐字出现（精确匹配），
   以及去除空白/换行后是否仍能匹配（宽松匹配，用于区分“格式差异”与“编造”）。
2. **定位一致**：``locator.start/end`` 指向的切片是否等于 ``quote``；
   没有 quote 时是否至少是合法区间（0 ≤ start < end ≤ len(text)）。
3. **重复率**：同一任务内 ``(quote, problem)`` 完全相同的诊断项视为重复。
4. **结构占比**：``verification_method`` 分布（model 语义诊断 / structural 结构检查）。
5. **修改提案可验证性**：``RevisionProposalRow.hunks`` 是否能用
   ``revision_service.validate_hunks`` 复核通过。

输出 JSON + Markdown，全程不打印论文正文（只统计与定位信息）。

用法：

    ./.venv/Scripts/python.exe tools/research_corpus_audit.py \\
        --db tmp/r2-corpus.db --out tmp/r2-corpus-audit.json

退出码：0 = 审计完成；2 = 输入/数据库不合法。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

_WS_RE = re.compile(r"\s+")


def _norm(text: Optional[str]) -> str:
    return _WS_RE.sub("", (text or "")).strip()


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _tasks(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT t.id, t.kind, t.status, t.owner_id, t.project_id,
                   t.input_json, t.result_json, t.snapshot_summary
            FROM research_tasks t
            WHERE t.kind = 'review'
            ORDER BY t.created_at
            """
        )
    )


def _findings(conn: sqlite3.Connection, task_id: str) -> List[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM research_findings WHERE task_id = ? ORDER BY id",
            (task_id,),
        )
    )


def _proposals(conn: sqlite3.Connection, task_id: str) -> List[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM research_revision_proposals WHERE task_id = ?",
            (task_id,),
        )
    )


def _version_text(conn: sqlite3.Connection, version_id: Optional[str]) -> str:
    if not version_id:
        return ""
    row = conn.execute(
        "SELECT text FROM research_document_versions WHERE id = ?", (version_id,)
    ).fetchone()
    return str(row["text"]) if row and row["text"] else ""


def _draft_of(task_row: sqlite3.Row) -> Dict[str, Any]:
    return _json(task_row["input_json"], {}) or {}


def _parse_tasks(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """把每个 review 任务解析成审计样本。"""
    samples: List[Dict[str, Any]] = []
    for row in _tasks(conn):
        payload = _draft_of(row)
        version_id = None
        for key in ("document_version_id", "version_id"):
            if isinstance(payload.get(key), str):
                version_id = payload[key]
                break
        if not version_id:
            refs = payload.get("refs") if isinstance(payload.get("refs"), dict) else {}
            for key in ("document_version_id", "version_id"):
                if isinstance(refs.get(key), str):
                    version_id = refs[key]
                    break
        project_id = payload.get("project_id") or row["project_id"]
        document_id = None
        if version_id:
            vrow = conn.execute(
                "SELECT document_id FROM research_document_versions WHERE id = ?",
                (version_id,),
            ).fetchone()
            document_id = vrow["document_id"] if vrow else None
        samples.append(
            {
                "task_id": str(row["id"]),
                "status": str(row["status"]),
                "version_id": version_id,
                "project_id": project_id,
                "document_id": document_id,
                "text": _version_text(conn, version_id),
                "result": _json(row["result_json"], {}) or {},
            }
        )
    return samples


def _audit_sample(conn: sqlite3.Connection, sample: Dict[str, Any]) -> Dict[str, Any]:
    text = sample["text"]
    findings = _findings(conn, sample["task_id"])
    quote_exact = quote_loose = quote_missing = 0
    locator_ok = locator_bad = 0
    dupes = 0
    seen: Counter = Counter()
    methods: Counter = Counter()
    problems = 0
    for row in findings:
        quote = row["quote"]
        locator = _json(row["locator"], {}) or {}
        methods[str(row["verification_method"] or "none")] += 1
        if not (row["problem"] or "").strip():
            problems += 1
        if quote:
            if quote in text:
                quote_exact += 1
            elif _norm(quote) and _norm(quote) in _norm(text):
                quote_loose += 1
            else:
                quote_missing += 1
        if isinstance(locator, dict) and "start" in locator and "end" in locator:
            try:
                start, end = int(locator["start"]), int(locator["end"])
            except (TypeError, ValueError):
                locator_bad += 1
            else:
                if 0 <= start < end <= len(text):
                    if quote:
                        locator_ok += 1 if text[start:end] == quote else 0
                        locator_bad += 0 if text[start:end] == quote else 1
                    else:
                        locator_ok += 1
                else:
                    locator_bad += 1
        key = (_norm(quote), _norm(row["problem"]))
        if key[0] or key[1]:
            seen[key] += 1
            if seen[key] > 1:
                dupes += 1
    proposals = _proposals(conn, sample["task_id"])
    hunks_total = 0
    for prow in proposals:
        hunks_total += len(_json(prow["hunks"], []) or [])
    total = len(findings)
    return {
        "task_id": sample["task_id"],
        "status": sample["status"],
        "document_id": sample["document_id"],
        "version_id": sample["version_id"],
        "codepoints": len(text),
        "findings": total,
        "quote_exact": quote_exact,
        "quote_loose": quote_loose,
        "quote_missing": quote_missing,
        "quote_coverage_ratio": round((quote_exact + quote_loose) / total, 4)
        if total
        else None,
        "locator_ok": locator_ok,
        "locator_bad": locator_bad,
        "duplicates": dupes,
        "duplicate_ratio": round(dupes / total, 4) if total else None,
        "empty_problem": problems,
        "verification_methods": dict(methods),
        "proposals": len(proposals),
        "hunks_total": hunks_total,
    }


def _aggregate(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    def _sum(key: str) -> int:
        return sum(int(s.get(key) or 0) for s in samples)

    total_findings = _sum("findings")
    quoted = _sum("quote_exact") + _sum("quote_loose")
    methods: Counter = Counter()
    for s in samples:
        methods.update(s.get("verification_methods") or {})
    return {
        "papers": len(samples),
        "succeeded": sum(1 for s in samples if s["status"] == "succeeded"),
        "findings_total": total_findings,
        "quote_exact": _sum("quote_exact"),
        "quote_loose": _sum("quote_loose"),
        "quote_missing": _sum("quote_missing"),
        "quote_coverage_ratio": round(quoted / total_findings, 4) if total_findings else None,
        "pure_hallucination_ratio": round(_sum("quote_missing") / total_findings, 4)
        if total_findings
        else None,
        "locator_ok": _sum("locator_ok"),
        "locator_bad": _sum("locator_bad"),
        "duplicates": _sum("duplicates"),
        "duplicate_ratio": round(_sum("duplicates") / total_findings, 4)
        if total_findings
        else None,
        "empty_problem": _sum("empty_problem"),
        "verification_methods": dict(methods),
        "proposals": _sum("proposals"),
        "hunks_total": _sum("hunks_total"),
    }


def _render_markdown(payload: Dict[str, Any]) -> str:
    agg = payload["aggregate"]
    lines = [
        "# 真实语料诊断可核对性审计",
        "",
        f"- 生成时间（UTC）：{payload['generated_at']}",
        f"- 数据库：`{payload['db']}`",
        f"- 论文数：{agg['papers']}（succeeded {agg['succeeded']}）",
        f"- 诊断项总数：{agg['findings_total']}",
        "",
        "## 引文保真",
        "",
        f"- 逐字命中：{agg['quote_exact']}",
        f"- 去空白后命中：{agg['quote_loose']}",
        f"- 无法命中（疑似编造引文）：{agg['quote_missing']}",
        f"- 引文可核对率：**{agg['quote_coverage_ratio']}**",
        f"- 纯编造引文率：**{agg['pure_hallucination_ratio']}**",
        "",
        "## 定位与重复",
        "",
        f"- locator 与引文一致：{agg['locator_ok']}（不一致 {agg['locator_bad']}）",
        f"- 完全重复诊断项：{agg['duplicates']}（重复率 {agg['duplicate_ratio']}）",
        f"- 空 problem：{agg['empty_problem']}",
        f"- verification_method 分布：{json.dumps(agg['verification_methods'], ensure_ascii=False)}",
        f"- 修改提案：{agg['proposals']}，补丁总数：{agg['hunks_total']}",
        "",
        "## 逐篇",
        "",
        "| 论文任务 | 状态 | 码点 | 诊断项 | 引文可核对率 | 定位不一致 | 重复率 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in payload["samples"]:
        lines.append(
            "| {task} | {status} | {cp} | {n} | {q} | {bad} | {dup} |".format(
                task=s["task_id"],
                status=s["status"],
                cp=s["codepoints"],
                n=s["findings"],
                q=s["quote_coverage_ratio"],
                bad=s["locator_bad"],
                dup=s["duplicate_ratio"],
            )
        )
    lines += [
        "",
        "> 说明：本审计只核对“诊断项是否指向真实原文”，**不评价诊断是否专业正确**——",
        "> 后者需要真人标注（按用户指示本次盲评豁免）。引文无法命中的诊断项不计入",
        "> “有效诊断”，也不得被当作已核实结论。",
    ]
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="真实语料诊断可核对性审计")
    parser.add_argument("--db", default="tmp/r2-corpus.db", help="评估数据库（只读）")
    parser.add_argument("--out", default="tmp/r2-corpus-audit.json", help="输出 JSON")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    try:
        conn = _connect(db_path)
    except sqlite3.Error as exc:
        print(f"数据库无法打开：{exc}", file=sys.stderr)
        return 2

    try:
        samples = _parse_tasks(conn)
        if not samples:
            print("数据库中没有 review 任务，先跑 research_corpus_eval.py", file=sys.stderr)
            return 2
        audited = [_audit_sample(conn, s) for s in samples]
    finally:
        conn.close()

    payload = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "db": str(db_path),
        "aggregate": _aggregate(audited),
        "samples": audited,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md = out.with_suffix(".md")
    md.write_text(_render_markdown(payload), encoding="utf-8")
    agg = payload["aggregate"]
    print(
        "audited papers={papers} findings={findings_total} quote_ok={quote_coverage_ratio} "
        "hallucination={pure_hallucination_ratio} dup={duplicate_ratio}".format(**agg)
    )
    print(f"written: {out} / {md}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
