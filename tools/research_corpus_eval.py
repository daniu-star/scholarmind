"""真实语料评估（T21 合规替代）：用用户提供的论文跑真实 review / revision 任务。

设计要点
========
- 只用**真实**模型客户端（``runtime.get_client``），不注入替身；无 API Key 时直接退出。
- 语料在 ``tmp/r2-corpus/``（用户自有未发表稿的副本），仓库不保存正文；
  ``manifest.json`` 只登记来源、大小与哈希。
- 没有人工标注与真人评分，因此**不计算召回率/误报率/人工提速**；只报告可机器验证的
  过程指标：解析成功率、覆盖率、缺陷分布、证据完整性、修订补丁合法率、耗时与用量。
- 结果写 JSON + Markdown，便于复核与复跑。

用法::

    ./.venv/Scripts/python.exe tools/research_corpus_eval.py \
        --corpus tmp/r2-corpus --db tmp/r2-corpus-eval.db --out docs/reports/R2_CORPUS_EVAL_RESULTS.json
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select  # noqa: E402

from src.backend.research import budget as budget_mod  # noqa: E402
from src.backend.research import document_service, project_service, revision_service  # noqa: E402
from src.backend.research import task_runner, task_service  # noqa: E402
from src.backend.research.contracts import (  # noqa: E402
    Actor,
    PRESERVE_DEFAULTS,
    normalize_text,
)
from src.backend.research.models import (  # noqa: E402
    Artifact,
    DocumentBlock,
    DocumentVersion,
    FindingRow,
    ResearchTask,
    RevisionProposalRow,
    TaskEvent,
)
from src.backend.db.session import create_async_engine_from_url, init_db  # noqa: E402
from src.backend.models.orm import User, UserQuota  # noqa: E402
from src.backend.services.entitlement_service import EntitlementService  # noqa: E402
from src.backend.utils.circuit_breaker import deepseek_circuit_breaker  # noqa: E402

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}


def _iso(value) -> Optional[str]:
    return value.isoformat() + "Z" if value is not None else None


def _ratio(part: int, total: int) -> Optional[float]:
    return round(part / total, 4) if total else None


async def _ensure_user(db, slug: str) -> Actor:
    user = User(
        username=f"corpus-eval-{slug}",
        password_hash="not-a-login-account",
        nickname=f"corpus-eval-{slug}",
        role="user",
        is_active=True,
        email_verified=True,
        plan="pro",
    )
    db.add(user)
    await db.flush()
    db.add(UserQuota(user_id=user.id, plan="pro", generation_credits=50, shared_pipeline_credits=50))
    await db.flush()
    await EntitlementService.grant_product(
        db, user.id, "monthly_pro", f"corpus-eval-grant-{slug}"
    )
    await db.commit()
    return Actor(user_id=user.id)


async def _review_one(db, actor: Actor, sample: Dict[str, Any], corpus: Path,
                      out_dir: Path) -> Dict[str, Any]:
    slug = sample["sample_id"]
    data = (corpus / sample["staged_file"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == sample["sha256"], f"{slug}: sha256 不一致"

    started = time.perf_counter()
    project = await project_service.create_project(db, actor, f"[corpus] {slug}")
    await db.commit()
    upload = await document_service.upload_document(
        db, actor, project["id"], filename=sample["staged_file"], mime=DOCX_MIME, data=data
    )
    await db.commit()
    version_id = upload["version"]["id"]
    document_id = upload["document"]["id"]
    version = await db.get(DocumentVersion, version_id)
    base_text = normalize_text(version.text or "")
    block_count = int(
        (
            await db.execute(
                select(func.count()).select_from(DocumentBlock).where(
                    DocumentBlock.version_id == version_id
                )
            )
        ).scalar()
        or 0
    )

    accepted = await task_service.create_task(
        db,
        actor,
        {
            "schema_version": "1.0",
            "project_id": project["id"],
            "kind": "review",
            "objective": "对全文做投稿前诊断：论证、方法、证据、结构与表达",
            "input": {"document_version_id": version_id},
        },
        idempotency_key=f"corpus-{slug}-review",
    )
    await db.commit()
    task = await db.get(ResearchTask, accepted.task_id)
    review_started = time.perf_counter()
    await task_runner.execute_task(db, task, holder=f"corpus-eval:{slug}")
    review_elapsed = round(time.perf_counter() - review_started, 2)
    await db.refresh(task)

    findings = (
        await db.execute(
            select(FindingRow).where(FindingRow.task_id == task.id).order_by(FindingRow.id)
        )
    ).scalars().all()
    events = (
        await db.execute(
            select(TaskEvent).where(TaskEvent.task_id == task.id).order_by(TaskEvent.sequence)
        )
    ).scalars().all()
    usage = budget_mod.usage_from_events(events)
    artifacts = (
        await db.execute(select(Artifact).where(Artifact.task_id == task.id))
    ).scalars().all()

    coverage = dict(task.coverage_json or {})
    if not coverage:
        # partial/failed 任务的 coverage_json 可能为空；此时以审阅报告快照里的
        # coverage 为准（同一份数据，避免把“部分覆盖”误记成 0）。
        for artifact in artifacts:
            if getattr(artifact, "kind", None) != "review_report":
                continue
            raw_validation = artifact.validation_json
            if isinstance(raw_validation, dict):
                # JSON 列在 ORM 里已经是 dict；再 json.loads 会抛 TypeError，
                # 之前的 `except ... continue` 会静默跳过回退，导致 partial
                # 任务被记成 0% 覆盖（R2 p10 真实踩到）。
                validation = raw_validation
            else:
                try:
                    validation = json.loads(raw_validation or "{}")
                except (TypeError, ValueError):
                    continue
            if isinstance(validation.get("coverage"), dict):
                coverage = dict(validation["coverage"])
                break
    structural = [f for f in findings if str(f.verification_method) == "structural"]
    model_findings = [f for f in findings if str(f.verification_method) != "structural"]
    severity_counts: Dict[str, int] = {}
    category_counts: Dict[str, int] = {}
    for row in findings:
        severity_counts[str(row.severity)] = severity_counts.get(str(row.severity), 0) + 1
        category_counts[str(row.category)] = category_counts.get(str(row.category), 0) + 1
    def _has_locator(row) -> bool:
        locator = row.locator
        if isinstance(locator, dict):
            return any(str(value or "").strip() for value in locator.values())
        if isinstance(locator, (list, tuple)):
            return any(str(value or "").strip() for value in locator)
        return bool(str(locator or "").strip())

    with_locator = sum(1 for f in findings if _has_locator(f))
    with_evidence = sum(1 for f in findings if list(f.evidence_refs or []))

    total_blocks = (
        coverage.get("expected_eligible_blocks")
        or coverage.get("total_blocks")
        or block_count
    )
    analyzed = (
        coverage.get("analyzed_eligible_blocks")
        or coverage.get("analyzed_blocks")
        or 0
    )
    unassessed = coverage.get("unassessed_objects") or []

    result: Dict[str, Any] = {
        "sample_id": slug,
        "language": sample["language"],
        "bytes": len(data),
        "sha256_ok": True,
        "document_id": document_id,
        "document_version_id": version_id,
        "codepoints": len(base_text),
        "blocks": block_count,
        "parse_status": getattr(version.parse_status, "value", version.parse_status),
        "review": {
            "task_id": task.id,
            "status": getattr(task.status, "value", task.status),
            "quality_verdict": task.quality_verdict,
            "error": task.error_json,
            "duration_seconds": round(
                (task.ended_at - task.created_at).total_seconds(), 2
            ) if task.ended_at and task.created_at else None,
            "wall_seconds": review_elapsed,
            "model_calls": usage.model_calls,
            "tokens": usage.tokens,
            "cost_usd": usage.cost_usd,
            "coverage": {
                "analyzed_blocks": analyzed,
                "total_blocks": total_blocks,
                "ratio": _ratio(int(analyzed or 0), int(total_blocks or 0)),
                "unassessed": list(unassessed)[:10],
            },
            "findings_total": len(findings),
            "findings_model": len(model_findings),
            "findings_structural": len(structural),
            "severity": severity_counts,
            "category": category_counts,
            "findings_with_locator_ratio": _ratio(with_locator, len(findings)),
            "findings_with_evidence_ratio": _ratio(with_evidence, len(findings)),
            "findings_per_10k_codepoints": round(len(findings) * 10000 / max(1, len(base_text)), 2),
            "artifacts": [
                {"kind": a.kind, "bytes": a.size_bytes, "mime": a.mime} for a in artifacts
            ],
        },
    }

    # ── 修订：取最严重的两个诊断项生成提案，并校验补丁 ──
    priority = sorted(
        findings,
        key=lambda f: (SEVERITY_ORDER.get(str(f.severity), 9), str(f.id)),
    )
    if priority:
        selected = [f.id for f in priority[:2]]
        proposal_summary: Dict[str, Any] = {"selected": len(selected)}
        try:
            accepted_rev = await task_service.create_task(
                db,
                actor,
                {
                    "schema_version": "1.0",
                    "project_id": project["id"],
                    "kind": "revision",
                    "objective": "按选定诊断项给出可直接采纳的修改补丁",
                    "input": {"document_version_id": version_id},
                    "scope": {"finding_ids": selected},
                },
                idempotency_key=f"corpus-{slug}-revision",
            )
            await db.commit()
            rev_task = await db.get(ResearchTask, accepted_rev.task_id)
            await task_runner.execute_task(db, rev_task, holder=f"corpus-eval:{slug}:rev")
            await db.refresh(rev_task)
            proposals = (
                await db.execute(
                    select(RevisionProposalRow).where(RevisionProposalRow.task_id == rev_task.id)
                )
            ).scalars().all()
            valid = 0
            hunks_total = 0
            patchable = 0
            issues_all: List[str] = []
            for row in proposals:
                hunks = list(row.hunks_json or [])
                hunks_total += len(hunks)
                if not hunks:
                    continue
                patchable += 1
                issues = revision_service.validate_hunks(
                    base_text, hunks, preserve=list(PRESERVE_DEFAULTS)
                )
                if issues:
                    issues_all.extend(issues[:3])
                else:
                    valid += 1
            rev_events = (
                await db.execute(
                    select(TaskEvent)
                    .where(TaskEvent.task_id == rev_task.id)
                    .order_by(TaskEvent.sequence)
                )
            ).scalars().all()
            rev_usage = budget_mod.usage_from_events(rev_events)
            proposal_summary.update(
                {
                    "task_id": rev_task.id,
                    "status": getattr(rev_task.status, "value", rev_task.status),
                    "error": rev_task.error_json,
                    "duration_seconds": round(
                        (rev_task.ended_at - rev_task.created_at).total_seconds(), 2
                    ) if rev_task.ended_at and rev_task.created_at else None,
                    "model_calls": rev_usage.model_calls,
                    "tokens": rev_usage.tokens,
                    "proposals": len(proposals),
                    "hunks": hunks_total,
                    "proposals_with_hunks": patchable,
                    "proposals_valid": valid,
                    "error_code": next(
                        (
                            str(e.payload_json.get("error", {}).get("code"))
                            for e in rev_events
                            if isinstance(e.payload_json, dict)
                            and isinstance(e.payload_json.get("error"), dict)
                        ),
                        None,
                    ),
                    "hunk_issues": issues_all[:5],
                    "protected_violations": [
                        e.payload_json.get("error", {}).get("code")
                        for e in rev_events
                        if isinstance(e.payload_json, dict)
                        and e.payload_json.get("error", {}).get("code") == "PROTECTED_CONTENT_VIOLATION"
                    ],
                }
            )
        except Exception as exc:  # noqa: BLE001 - 记录失败而不是中断整批
            proposal_summary["error"] = f"{type(exc).__name__}: {exc}"
            await db.rollback()
        result["revision"] = proposal_summary

    result["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    return result


def _aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    reviews = [r["review"] for r in rows]
    ok = [r for r in reviews if r["status"] == "succeeded"]
    total_findings = sum(r["findings_total"] for r in reviews)
    covered = [r["coverage"]["ratio"] for r in reviews if r["coverage"]["ratio"] is not None]
    revisions = [r.get("revision") for r in rows if r.get("revision")]
    proposals = sum(int(x.get("proposals") or 0) for x in revisions)
    valid = sum(int(x.get("proposals_valid") or 0) for x in revisions)
    return {
        "samples": len(rows),
        "succeeded": len(ok),
        "failed": len(reviews) - len(ok),
        "succeeded_ratio": _ratio(len(ok), len(reviews)),
        "verdicts": {
            v: sum(1 for r in reviews if r["quality_verdict"] == v)
            for v in {r["quality_verdict"] for r in reviews}
        },
        "mean_codepoints": round(sum(r["codepoints"] for r in rows) / max(1, len(rows)), 1),
        "mean_coverage_ratio": round(sum(covered) / len(covered), 4) if covered else None,
        "findings_total": total_findings,
        "findings_per_10k_mean": round(
            sum(r["findings_per_10k_codepoints"] for r in reviews) / max(1, len(reviews)), 2
        ),
        "severity_totals": {
            s: sum(r["severity"].get(s, 0) for r in reviews)
            for s in ("critical", "major", "minor")
        },
        "model_findings_ratio": _ratio(
            sum(r["findings_model"] for r in reviews), max(1, total_findings)
        ),
        "mean_model_calls": round(
            sum(r["model_calls"] for r in reviews) / max(1, len(reviews)), 2
        ),
        "mean_tokens": round(sum(r["tokens"] for r in reviews) / max(1, len(reviews)), 1),
        "mean_review_seconds": round(
            sum(r["wall_seconds"] for r in reviews) / max(1, len(reviews)), 2
        ),
        "revision": {
            "papers": len(revisions),
            "proposals": proposals,
            "hunks": sum(int(x.get("hunks") or 0) for x in revisions),
            "proposals_with_hunks": sum(int(x.get("proposals_with_hunks") or 0) for x in revisions),
            "proposals_valid": valid,
            "valid_ratio": _ratio(valid, proposals),
            "papers_with_errors": sum(1 for x in revisions if x.get("error")),
            "error_codes": sorted(
                {str(x.get("error_code")) for x in revisions if x.get("error_code")}
            ),
        },
        "human_labels": {
            "available": False,
            "defect_recall": None,
            "false_positive_rate": None,
            "note": "本批语料没有人工作为参照的缺陷标注与第二评审，按 PRD 规定不计算召回率/误报率。",
        },
    }


def _write_markdown(path: Path, payload: Dict[str, Any]) -> None:
    agg = payload["aggregate"]
    lines = [
        "# R2 真实语料评估结果（T21 合规替代）",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 语料：`{payload['corpus']}`（{agg['samples']} 篇，用户自有未发表稿）",
        f"- 模型：`{payload['model']['name']}`（真实调用，非替身）",
        "- 人工标注：**无**，因此不计算召回率/误报率（见 PRD T21 与 R2_EVAL_SPEC 的诚实性要求）。",
        (
            "- 模型：**替身（stub）**，本文件仅为机制演练，不是质量证据。"
            if payload["model"]["stub"]
            else "- 模型：真实调用。"
        ),
        "",
        "## 汇总",
        "",
        f"- 成功：{agg['succeeded']}/{agg['samples']}（{agg['succeeded_ratio']}）",
        f"- 质量判定分布：{agg['verdicts']}",
        f"- 平均码点：{agg['mean_codepoints']}；平均覆盖率：{agg['mean_coverage_ratio']}",
        f"- 诊断项总数：{agg['findings_total']}（每万码点均值 {agg['findings_per_10k_mean']}）",
        f"- 严重度分布：{agg['severity_totals']}；模型判定的占比：{agg['model_findings_ratio']}",
        f"- 平均模型调用：{agg['mean_model_calls']}；平均 tokens：{agg['mean_tokens']}；平均耗时：{agg['mean_review_seconds']}s",
        f"- 修订提案：{agg['revision']['proposals']}，合法 {agg['revision']['proposals_valid']}（{agg['revision']['valid_ratio']}）",
        "",
        "## 逐篇结果",
        "",
        "| 样本 | 语种 | 码点 | 块 | 状态 | 判定 | 覆盖率 | 诊断项 | 严重度 | 调用 | tokens | 耗时(s) |",
        "| --- | --- | ---: | ---: | --- | --- | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for row in payload["samples"]:
        rev = row["review"]
        sev = "/".join(str(rev["severity"].get(s, 0)) for s in ("critical", "major", "minor"))
        lines.append(
            "| {sid} | {lang} | {cp} | {blk} | {st} | {v} | {cov} | {fn} | {sev} | {calls} | {tokens} | {dur} |".format(
                sid=row["sample_id"],
                lang=row["language"],
                cp=row["codepoints"],
                blk=row["blocks"],
                st=rev["status"],
                v=rev["quality_verdict"] or "-",
                cov=rev["coverage"]["ratio"] if rev["coverage"]["ratio"] is not None else "-",
                fn=rev["findings_total"],
                sev=sev,
                calls=rev["model_calls"],
                tokens=rev["tokens"],
                dur=rev["duration_seconds"] if rev["duration_seconds"] is not None else "-",
            )
        )
    lines += ["", "## 修订校验", ""]
    lines.append("| 样本 | 状态 | 提案 | 合法 | 错误 |")
    lines.append("| --- | --- | ---: | ---: | --- |")
    for row in payload["samples"]:
        rev = row.get("revision")
        if not rev:
            continue
        err = str(rev.get("error") or "")[:60].replace("|", "/")
        lines.append(
            f"| {row['sample_id']} | {rev.get('status', '-')} | {rev.get('proposals', 0)} | "
            f"{rev.get('proposals_valid', 0)} | {err or '-'} |"
        )
    lines += [
        "",
        "## 结论边界",
        "",
        "- 本表只证明「真实论文能被解析、诊断、给出证据与补丁」的过程可用性；不证明诊断结论正确。",
        "- 召回率/误报率/人工提速需要真人参照标注与双评审，本轮未做（用户已确认跳过盲评）。",
        "- 文档正文仅存在于本机临时目录，仓库不保存语料原文。",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


async def _run(args: argparse.Namespace) -> int:
    corpus = Path(args.corpus)
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    samples = list(manifest["samples"])
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        samples = [s for s in samples if s["sample_id"] in wanted]
    if args.limit:
        samples = samples[: args.limit]
    if not samples:
        print("没有可评估样本", file=sys.stderr)
        return 2

    db_path = Path(args.db).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if not args.keep_db:
        for name in (db_path, Path(str(db_path) + "-wal"), Path(str(db_path) + "-shm")):
            if name.exists():
                name.unlink()
    engine = create_async_engine_from_url(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    await init_db(engine)
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(engine, expire_on_commit=False)
    stub_active = False
    if args.allow_stub:
        try:
            from src.backend.research import runtime as _runtime

            stub_active = bool(getattr(_runtime._settings(), "RESEARCH_MODEL_STUB", False))
        except Exception:  # noqa: BLE001
            stub_active = False
        print(f"[warn] stub_active={stub_active}", file=sys.stderr)
    model_name = os.getenv("DEEPSEEK_MODEL") or "deepseek-chat"
    if model_name == "deepseek-chat":
        try:
            from src.backend.config import settings as _s

            model_name = str(getattr(_s, "DEEPSEEK_MODEL", model_name) or model_name)
        except Exception:  # noqa: BLE001
            pass
    rows: List[Dict[str, Any]] = []
    async with factory() as db:
        for index, sample in enumerate(samples, start=1):
            print(f"[{index}/{len(samples)}] {sample['sample_id']} …", flush=True)
            # 每篇开始前复位熔断器：一次网络抖动不应连锁污染后续论文，
            # 否则会把“网络问题”误记成“模型不可用”。
            deepseek_circuit_breaker.reset()
            try:
                actor = await _ensure_user(db, sample["sample_id"])
                row = await _review_one(db, actor, sample, corpus, corpus)
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                row = {
                    "sample_id": sample["sample_id"],
                    "language": sample["language"],
                    "error": f"{type(exc).__name__}: {exc}",
                    "review": {
                        "status": "crashed",
                        "quality_verdict": None,
                        "findings_total": 0,
                        "findings_model": 0,
                        "findings_structural": 0,
                        "severity": {},
                        "category": {},
                        "findings_with_locator_ratio": None,
                        "findings_with_evidence_ratio": None,
                        "findings_per_10k_codepoints": 0.0,
                        "model_calls": 0,
                        "tokens": 0,
                        "cost_usd": None,
                        "wall_seconds": 0.0,
                        "duration_seconds": None,
                        "coverage": {"analyzed_blocks": 0, "total_blocks": 0, "ratio": None, "unassessed": []},
                        "artifacts": [],
                        "error": str(exc),
                    },
                    "codepoints": 0,
                    "blocks": 0,
                }
            rows.append(row)
            print(
                f"    -> {row['review']['status']} findings={row['review']['findings_total']} "
                f"calls={row['review']['model_calls']} tokens={row['review']['tokens']}",
                flush=True,
            )
            error = row["review"].get("error") or {}
            if row["review"]["status"] in {"recoverable", "failed"} and (
                error.get("code") == "MODEL_UNAVAILABLE"
            ):
                # 网络抖动/短暂不可用：复位熔断器并等待，再继续下一篇。
                deepseek_circuit_breaker.reset()
                delay = int(getattr(args, "retry_delay", 20) or 0)
                print(f"    -> MODEL_UNAVAILABLE，等待 {delay}s 后继续", flush=True)
                await asyncio.sleep(delay)
            partial = {
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "corpus": str(corpus),
                "model": {
                "name": "stub" if args.allow_stub else model_name,
                "stub": bool(args.allow_stub and stub_active),
                "quality_evidence": not args.allow_stub,
            },
                "samples": rows,
                "aggregate": _aggregate(rows),
            }
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(partial, ensure_ascii=False, indent=2), encoding="utf-8")
    await engine.dispose()
    print("done:", args.out)
    return 0


def _force_stub_settings() -> None:
    """把已实例化的 settings 对象全部切到替身模式（环境变量改不动已缓存实例）。"""
    import importlib

    for name in ("src.backend.config", "backend.config"):
        try:
            module = importlib.import_module(name)
        except ImportError:
            continue
        settings = getattr(module, "settings", None)
        if settings is None:
            continue
        for attr, value in (
            ("RESEARCH_MODEL_STUB", True),
            ("ENVIRONMENT", "test"),
        ):
            try:
                setattr(settings, attr, value)
            except (AttributeError, ValueError):
                pass


def _api_key() -> str:
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    try:
        from src.backend.config import settings

        return str(getattr(settings, "DEEPSEEK_API_KEY", "") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="真实语料评估（T21 合规替代）")
    parser.add_argument("--corpus", default=str(ROOT / "tmp" / "r2-corpus"))
    parser.add_argument("--db", default=str(ROOT / "tmp" / "r2-corpus-eval.db"))
    parser.add_argument("--out", default=str(ROOT / "docs" / "reports" / "R2_CORPUS_EVAL_RESULTS.json"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--only", default="")
    parser.add_argument(
        "--keep-db",
        action="store_true",
        help="不删除已有数据库（用于分批续跑并把结果合并）",
    )
    parser.add_argument(
        "--retry-delay",
        type=int,
        default=20,
        help="遇到 MODEL_UNAVAILABLE 后等待秒数（复位熔断器再继续）",
    )
    parser.add_argument(
        "--allow-stub",
        action="store_true",
        help="仅用于机制演练：允许替身模型，结果标记为非质量证据",
    )
    args = parser.parse_args()
    if args.allow_stub:
        os.environ["RESEARCH_MODEL_STUB"] = "true"
        os.environ.setdefault("ENVIRONMENT", "test")
        _force_stub_settings()
        print("[warn] 替身模型模式：只验证机制，不得作为质量证据", file=sys.stderr)
    elif not _api_key():
        print("缺少 DEEPSEEK_API_KEY，拒绝用替身冒充真实评估", file=sys.stderr)
        return 2
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())