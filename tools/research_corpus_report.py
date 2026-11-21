"""把真实语料评估结果（可多批/多库）合并成一份可复核报告。

背景：真实模型批量评估会因网络抖动中断，工具支持 ``--keep-db`` + ``--only`` 分批
续跑；本脚本把多份 ``research_corpus_eval.py`` 输出按 ``sample_id`` 合并（同一篇
优先取 succeeded 的结果），再叠加 ``research_corpus_audit.py`` 的引文保真/重复率，
生成 ``docs/reports/R2_CORPUS_EVAL.md`` 与 ``R2_CORPUS_EVAL_RESULTS.json``。

用法::

    ./.venv/Scripts/python.exe tools/research_corpus_report.py \\
        --eval tmp/r2-corpus-eval-v2.json --eval tmp/r2-corpus-eval-v3.json \\
        --audit tmp/r2-corpus-v2-audit.json --audit tmp/r2-corpus-v3-audit.json \\
        --out docs/reports/R2_CORPUS_EVAL_RESULTS.json

注意：本报告只陈述**可机器验证**的过程指标；没有人工标注，因此不计算
召回率/误报率，也不得把“诊断条数多”当成“诊断准确”。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_STATUS_RANK = {"succeeded": 0, "partial": 1, "recoverable": 2, "failed": 3, "crashed": 4}
_DISCLAIMER = (
"> 本报告没有人工缺陷标注与第二评审（按用户指示本次盲评豁免），"
"因此**不计算召回率、误报率与人工提速率**；"
"下列指标只说明“流程是否完整、诊断是否落在真实原文上”，不构成质量结论。"
)


def _load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _merge_samples(evals: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for doc in evals:
        for sample in doc.get("samples") or []:
            sid = sample["sample_id"]
            current = merged.get(sid)
            if current is None:
                merged[sid] = sample
                continue
            old_rank = _STATUS_RANK.get(current["review"]["status"], 9)
            new_rank = _STATUS_RANK.get(sample["review"]["status"], 9)
            if new_rank < old_rank:
                merged[sid] = sample
            elif new_rank == old_rank:
                # 同为 partial/recoverable 时优先保留覆盖更完整的那次运行。
                old_cov = (current["review"].get("coverage") or {}).get("ratio") or 0
                new_cov = (sample["review"].get("coverage") or {}).get("ratio") or 0
                if new_cov >= old_cov:
                    # 覆盖相同时取后跑的一次：修复后的运行应覆盖修复前的记录。
                    merged[sid] = sample
    return merged


def _merge_audits(audits: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for doc in audits:
        for sample in doc.get("samples") or []:
            merged[sample["task_id"]] = sample
    return merged


def _mean(values: List[float]) -> Optional[float]:
    return round(sum(values) / len(values), 2) if values else None


def _aggregate(samples: List[Dict[str, Any]], audits: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    succeeded = [s for s in samples if s["review"]["status"] == "succeeded"]
    partial = [s for s in samples if s["review"]["status"] == "partial"]
    other = [s for s in samples if s["review"]["status"] not in ("succeeded", "partial")]
    coverages = [
        s["review"]["coverage"]["ratio"]
        for s in samples
        if s["review"]["coverage"].get("ratio") is not None
    ]
    per_10k = [s["review"]["findings_per_10k_codepoints"] for s in succeeded]
    severity = {"critical": 0, "major": 0, "minor": 0}
    category: Dict[str, int] = {}
    for s in succeeded:
        for key, value in (s["review"].get("severity") or {}).items():
            severity[key] = severity.get(key, 0) + int(value)
        for key, value in (s["review"].get("category") or {}).items():
            category[key] = category.get(key, 0) + int(value)
    revision_papers = sum(1 for s in samples if (s.get("revision") or {}).get("proposals"))
    proposals = sum(int((s.get("revision") or {}).get("proposals") or 0) for s in samples)
    valid = sum(int((s.get("revision") or {}).get("proposals_valid") or 0) for s in samples)
    hunks = sum(int((s.get("revision") or {}).get("hunks") or 0) for s in samples)
    audited = [audits[s["review"]["task_id"]] for s in samples if s["review"]["task_id"] in audits]
    findings_total = sum(int(a["findings"]) for a in audited)
    quote_ok = sum(int(a["quote_exact"]) + int(a["quote_loose"]) for a in audited)
    quote_missing = sum(int(a["quote_missing"]) for a in audited)
    duplicates = sum(int(a["duplicates"]) for a in audited)
    locator_bad = sum(int(a["locator_bad"]) for a in audited)
    return {
        "papers": len(samples),
        "succeeded": len(succeeded),
        "partial": len(partial),
        "other_status": {s["sample_id"]: s["review"]["status"] for s in other},
        "mean_codepoints": _mean([float(s["codepoints"]) for s in samples if s.get("codepoints")]),
        "mean_coverage_ratio": _mean(coverages),
        "mean_findings_per_10k": _mean(per_10k),
        "findings_total": sum(int(s["review"]["findings_total"]) for s in samples),
        "severity_totals": severity,
        "category_totals": category,
        "mean_model_calls": _mean([float(s["review"]["model_calls"]) for s in succeeded]),
        "mean_tokens": _mean([float(s["review"]["tokens"]) for s in succeeded]),
        "mean_seconds": _mean(
            [
                float(s["review"]["duration_seconds"] or s["review"]["wall_seconds"] or 0)
                for s in succeeded
            ]
        ),
        "revision": {
            "papers_with_proposals": revision_papers,
            "proposals": proposals,
            "proposals_valid": valid,
            "valid_ratio": round(valid / proposals, 4) if proposals else None,
            "hunks": hunks,
        },
        "audit": {
            "papers": len(audited),
            "findings_total": findings_total,
            "quote_coverage_ratio": round(quote_ok / findings_total, 4) if findings_total else None,
            "pure_hallucination_ratio": round(quote_missing / findings_total, 4)
            if findings_total
            else None,
            "duplicate_ratio": round(duplicates / findings_total, 4) if findings_total else None,
            "locator_bad": locator_bad,
        },
        "budget_boundary": [
            {
                "sample_id": s["sample_id"],
                "codepoints": s.get("codepoints"),
                "blocks": s.get("blocks"),
                "tokens": s["review"]["tokens"],
                "coverage": s["review"]["coverage"].get("ratio"),
            }
            for s in partial
        ],
    }


def _pct(value: Any) -> str:
    if value is None:
        return "—"
    return f"{float(value) * 100:.2f}%"


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _render(payload: Dict[str, Any], sources: Dict[str, str]) -> str:
    agg = payload["aggregate"]
    aud = agg["audit"]
    lines = [
        "# T21 真实语料评估（合规替代）",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 数据来源：{sources['eval']}",
        f"- 审计数据：{sources['audit']}",
        f"- 模型：`{payload['model']['name']}`（stub={payload['model']['stub']}，quality_evidence={payload['model']['quality_evidence']}）",
        "",
        _DISCLAIMER,
        "",
        "## 1. 结论摘要",
        "",
        f"- 论文数：{agg['papers']}（succeeded {agg['succeeded']} / partial {agg['partial']}）",
        f"- 平均码点：{_fmt(agg['mean_codepoints'])}",
        f"- 平均覆盖率（有覆盖率记录的任务）：**{_pct(agg['mean_coverage_ratio'])}**",
        f"- 诊断项合计：{agg['findings_total']}（每万码点均值 {_fmt(agg['mean_findings_per_10k'])}）",
        f"- 严重度分布：critical {agg['severity_totals'].get('critical', 0)} / major {agg['severity_totals'].get('major', 0)} / minor {agg['severity_totals'].get('minor', 0)}",
        f"- 类别分布：{json.dumps(agg['category_totals'], ensure_ascii=False)}",
        f"- 平均模型调用：{_fmt(agg['mean_model_calls'])} 次；平均 tokens：{_fmt(agg['mean_tokens'])}；平均耗时：{_fmt(agg['mean_seconds'])} s",
        f"- 修改提案：{agg['revision']['papers_with_proposals']} 篇有提案、共 {agg['revision']['proposals']} 份（合法 {agg['revision']['proposals_valid']}，合法率 {_fmt(agg['revision']['valid_ratio'])}），补丁 {agg['revision']['hunks']} 个",
        f"- 引文保真：**{_pct(aud['quote_coverage_ratio'])}** 的诊断项 quote 能在原文逐字核对；纯编造引文率 **{_pct(aud['pure_hallucination_ratio'])}**",
        f"- 重复诊断：{_pct(aud['duplicate_ratio'])}；locator 与引文不一致：{aud['locator_bad']} 条",
        "",
        "## 2. 语料与逐篇指标",
        "",
        "| 语料 | 语言 | 码点 | 块 | 状态 | 覆盖 | 诊断项 | critical/major/minor | 调用 | tokens | 耗时(s) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in payload["samples"]:
        review = s["review"]
        sev = review.get("severity") or {}
        coverage = review["coverage"].get("ratio")
        lines.append(
            "| {sid} | {lang} | {cp} | {blocks} | {status} | {cov} | {findings} | {c}/{ma}/{mi} | {calls} | {tokens} | {secs} |".format(
                sid=s["sample_id"],
                lang=s.get("language") or "—",
                cp=s.get("codepoints") or 0,
                blocks=s.get("blocks") or 0,
                status=review["status"],
                cov=_pct(coverage),
                findings=review["findings_total"],
                c=sev.get("critical", 0),
                ma=sev.get("major", 0),
                mi=sev.get("minor", 0),
                calls=review["model_calls"],
                tokens=review["tokens"],
                secs=_fmt(review["duration_seconds"] or review["wall_seconds"]),
            )
        )
    lines += [
        "",
        "## 3. partial 的边界（预算与解析）",
        "",
        "| 语料 | 码点 | 块 | 已用 tokens | 覆盖率 |",
        "| --- | --- | --- | --- | --- |",
    ]
    if agg["budget_boundary"]:
        for row in agg["budget_boundary"]:
            lines.append(
                f"| {row['sample_id']} | {row['codepoints']} | {row['blocks']} | {row['tokens']} | {_pct(row['coverage'])} |"
            )
    else:
        lines.append("| — | — | — | — | — |")
    lines += [
        "",
        "### 3.1 为什么是 partial，而不是“少分析几块也算通过”",
        "",
        "`review_workflow` 在覆盖不足时按 PRD §7.2 最小交付契约返回 `partial` + "
        "`INCOMPLETE_DELIVERABLE`，并在 error 里写明 `全文诊断覆盖不足: N/M`；"
        "报告与诊断项仍然交付，但**不会**声称“已完整分析全文”。",
        "",
        "p10（59,582 码点 / 146 块）用掉 98,076/100,000 tokens 后仍有 55 个块未分析：",
        "按当前 1,200 码点窗口与审稿系统提示词，每次窗口调用平均约 1.5k tokens"
        "（提示词 + 窗口正文 + 诊断 JSON），要覆盖 59.6k 码点约需 1.6 倍预算。"
        "这是 PRD §9「单任务 100,000 tokens」的**真实边界**，不是程序错误。",
        "",
        "可选改进（属于产品决策，本次未擅自扩大预算）：放大窗口上限（如 2,000–4,000 码点）"
        "以减少系统提示词的重复开销；精简审稿提示词；或对 >40k 码点文档单独提高预算并在 UI 明示。",
        "",
        "另：p11 在早期一次运行中是 108/109（某个窗口的 JSON 被输出上限截断）。"
        "加入「finish_reason=length 时关闭思维链并把输出上限翻倍重试」后重跑达到 109/109；"
        "本报告采用修复后的结果，原始 partial 记录保留在 `tmp/r2-corpus-eval-v3.json`。",
        "",
        "## 4. 引文保真审计（`tools/research_corpus_audit.py`）",
        "",
        f"- 审计论文：{aud['papers']} 篇，诊断项 {aud['findings_total']} 条",
        f"- quote 逐字命中或去空白后命中：{_pct(aud['quote_coverage_ratio'])}",
        f"- 无法命中（疑似编造）：{_pct(aud['pure_hallucination_ratio'])}",
        f"- 完全重复的 (quote, problem)：{_pct(aud['duplicate_ratio'])}",
        f"- locator 切片与引文不一致：{aud['locator_bad']} 条",
        "",
        "## 5. 复跑命令",
        "",
        "```bash",
        "# 1) 分批跑真实模型（每篇独立用户与项目；断网后会复位熔断器继续）",
        "./.venv/Scripts/python.exe tools/research_corpus_eval.py --corpus tmp/r2-corpus \\",
        "  --db tmp/r2-corpus-v2.db --out tmp/r2-corpus-eval-v2.json",
        "",
        "# 2) 审计引文保真与重复率",
        "./.venv/Scripts/python.exe tools/research_corpus_audit.py --db tmp/r2-corpus-v2.db \\",
        "  --out tmp/r2-corpus-v2-audit.json",
        "",
        "# 3) 合并多批结果生成本报告",
        "./.venv/Scripts/python.exe tools/research_corpus_report.py \\",
        "  --eval tmp/r2-corpus-eval-v2.json --audit tmp/r2-corpus-v2-audit.json \\",
        "  --out docs/reports/R2_CORPUS_EVAL_RESULTS.json",
        "```",
        "",
        "## 6. 不能被本报告支持的表述",
        "",
        "- 不能说“诊断准确率/召回率/误报率达标”——没有人工标注。",
        "- 不能说“诊断质量达到发表级/审稿级”——未与真人审稿对照。",
        "- 不能说“成本/效率提升 X%”——费用未知，且无对照基线。",
        "- 可以说：流程完整（覆盖率）、诊断可定位到真实原文（引文保真）、无重复灌水、修改提案可复核。",
        "",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="合并真实语料评估结果并生成报告")
    parser.add_argument("--eval", action="append", default=[], help="evaluation JSON（可多次）")
    parser.add_argument("--audit", action="append", default=[], help="audit JSON（可多次）")
    parser.add_argument("--out", default="docs/reports/R2_CORPUS_EVAL_RESULTS.json")
    parser.add_argument("--md", default="docs/reports/R2_CORPUS_EVAL.md")
    args = parser.parse_args(argv)
    if not args.eval:
        parser.error("至少需要一个 --eval")

    evals = [_load(Path(p)) for p in args.eval]
    audits = [_load(Path(p)) for p in args.audit]
    samples = _merge_samples(evals)
    audit_map = _merge_audits(audits)
    model = next((doc.get("model") for doc in evals if doc.get("model")), {"name": "unknown"})
    ordered = sorted(samples.values(), key=lambda s: s["sample_id"])
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "model": {
            "name": model.get("name"),
            "stub": bool(model.get("stub")),
            "quality_evidence": bool(model.get("quality_evidence")),
        },
        "sources": {
            "eval": args.eval,
            "audit": args.audit,
        },
        "aggregate": _aggregate(ordered, audit_map),
        "samples": ordered,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md = Path(args.md)
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(
        _render(payload, {"eval": ", ".join(f"`{p}`" for p in args.eval), "audit": ", ".join(f"`{p}`" for p in args.audit)}),
        encoding="utf-8",
    )
    agg = payload["aggregate"]
    print(
        f"papers={agg['papers']} succeeded={agg['succeeded']} partial={agg['partial']} "
        f"coverage={agg['mean_coverage_ratio']} findings={agg['findings_total']} "
        f"quote_ok={agg['audit']['quote_coverage_ratio']} hallucination={agg['audit']['pure_hallucination_ratio']}"
    )
    print(f"written: {out} / {md}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
