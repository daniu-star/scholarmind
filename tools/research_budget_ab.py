"""T23：预算闸门的真实 A/B 测量（同一个输入、同一个模型、只改预算上限）。

用一篇真实论文跑三种受理预算，比较「状态 / 覆盖率 / 诊断数 / 调用数 / tokens /
耗时 / 是否保留成果」，验证 PRD §9 的预算边界不是纸面条款：

* ``default``     ：平台默认（160 次调用 / 100,000 tokens）——预期 succeeded；
* ``tight_tokens``：保留调用数，只把 tokens 收紧到 12,000——预期 partial；
* ``tight_calls`` ：保留 tokens，只把调用数收紧到 8——预期 partial/needs_input。

用法（需要可用的 DEEPSEEK_API_KEY，会真实计费）：

```text
python tools/research_budget_ab.py --corpus tmp/r2-corpus \\
    --only p14-intelligent-communication --db tmp/budget-ab.db \\
    --out tmp/budget-ab.json --md docs/reports/R2_BUDGET_AB.md
```
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

ARMS: List[Dict[str, Any]] = [
    {
        "arm": "default",
        "note": "平台默认预算（160 次调用 / 100,000 tokens）",
        "max_calls": 160,
        "max_tokens": 100_000,
    },
    {
        "arm": "tight_tokens",
        "note": "调用数不变，只把 tokens 收紧到 12,000",
        "max_calls": 160,
        "max_tokens": 12_000,
    },
    {
        "arm": "tight_calls",
        "note": "tokens 不变，只把调用数收紧到 8",
        "max_calls": 8,
        "max_tokens": 100_000,
    },
]


async def _ensure_user(db, slug: str):
    """每个 arm 用独立用户，避免每用户并发 1 与幂等键互相干扰。"""

    from sqlalchemy import select

    from src.backend.models.orm import User, UserQuota
    from src.backend.research.contracts import Actor
    from src.backend.services.entitlement_service import EntitlementService

    username = f"budget-ab-{slug}"
    existing = (
        await db.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if existing is not None:
        return Actor(user_id=int(existing.id))
    import uuid

    user = User(
        username=username,
        email=f"{username}@example.invalid",
        password_hash="x",
        nickname=username,
        is_active=True,
        email_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserQuota(user_id=user.id, plan="pro"))
    await db.flush()
    await EntitlementService.grant_product(
        db, int(user.id), "monthly_pro", f"budget-ab-grant-{slug}-{uuid.uuid4().hex[:8]}"
    )
    await db.commit()
    return Actor(user_id=int(user.id))


async def _run_arm(db, actor, sample: Dict[str, Any], corpus: Path, arm: Dict[str, Any],
                   settings) -> Dict[str, Any]:
    from sqlalchemy import func, select

    from src.backend.research import budget as budget_mod
    from src.backend.research import document_service, project_service, task_runner
    from src.backend.research import task_service
    from src.backend.research.contracts import normalize_text
    from src.backend.research.models import (
        Artifact,
        DocumentBlock,
        DocumentVersion,
        FindingRow,
        ResearchTask,
        TaskEvent,
    )

    slug = f"{sample['sample_id']}-{arm['arm']}"
    data = (corpus / sample["staged_file"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == sample["sha256"], f"{slug}: sha256 不一致"

    # 只改预算上限：其它条件（输入文档、模型、提示词版本）完全一致。
    settings.RESEARCH_REVIEW_MAX_MODEL_CALLS = arm["max_calls"]
    settings.RESEARCH_MAX_TOKENS_PER_TASK = arm["max_tokens"]

    project = await project_service.create_project(db, actor, f"[budget-ab] {slug}")
    await db.commit()
    upload = await document_service.upload_document(
        db,
        actor,
        project["id"],
        filename=sample["staged_file"],
        mime=DOCX_MIME,
        data=data,
    )
    await db.commit()
    version_id = upload["version"]["id"]
    version = await db.get(DocumentVersion, version_id)
    base_text = normalize_text(version.text or "")
    block_count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(DocumentBlock)
                .where(DocumentBlock.version_id == version_id)
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
        idempotency_key=f"budget-ab-{slug}-review",
    )
    await db.commit()
    task = await db.get(ResearchTask, accepted.task_id)
    accepted_budget = dict((task.constraints_json or {}).get(budget_mod.ACCEPTED_BUDGET_KEY) or {})

    started = time.perf_counter()
    await task_runner.execute_task(db, task, holder=f"budget-ab:{slug}")
    wall = round(time.perf_counter() - started, 2)
    await db.refresh(task)

    findings = (
        await db.execute(select(FindingRow).where(FindingRow.task_id == task.id))
    ).scalars().all()
    events = (
        await db.execute(
            select(TaskEvent)
            .where(TaskEvent.task_id == task.id)
            .order_by(TaskEvent.sequence)
        )
    ).scalars().all()
    usage = budget_mod.usage_from_events(events)
    artifacts = (
        await db.execute(select(Artifact).where(Artifact.task_id == task.id))
    ).scalars().all()
    coverage = dict(task.coverage_json or {})
    evaluation = dict((task.snapshot_summary or {}).get("budget_evaluation") or {})

    analyzed = int(coverage.get("analyzed_eligible_blocks") or 0)
    expected = int(coverage.get("expected_eligible_blocks") or 0)
    error_texts = (
        list((task.error_json or {}).get("errors") or [])
        if isinstance(task.error_json, dict)
        else []
    )
    if not expected:
        # partial 任务的 coverage_json 可能为空；覆盖率仍记在 errors
        # （形如「全文诊断覆盖不足: 18/69」）。这里只解析 DB 中已有的数字，
        # 不为缺失值补 0 或估算值。
        import re

        for text in error_texts:
            match = re.search(r"(\d+)\s*/\s*(\d+)", str(text))
            if match:
                analyzed, expected = int(match.group(1)), int(match.group(2))
                break
    return {
        "arm": arm["arm"],
        "note": arm["note"],
        "accepted_budget": accepted_budget,
        "status": str(task.status),
        "quality_verdict": (task.result_json or {}).get("quality_verdict")
        if isinstance(task.result_json, dict)
        else None,
        "coverage": {
            "analyzed_blocks": analyzed,
            "expected_blocks": expected,
            "ratio": round(analyzed / expected, 4) if expected else None,
        },
        "blocks": block_count,
        "codepoints": len(base_text),
        "findings_total": len(findings),
        "model_calls": int(usage.model_calls),
        "tokens": int(usage.tokens),
        "cost_usd": usage.cost_usd,
        "wall_seconds": wall,
        "artifacts": sorted({str(getattr(a, "kind", "")) for a in artifacts}),
        "artifact_count": len(artifacts),
        "budget_evaluation": evaluation,
        "errors": list((task.error_json or {}).get("errors") or [])
        if isinstance(task.error_json, dict)
        else [],
    }


async def _run(args: argparse.Namespace) -> int:
    corpus = Path(args.corpus)
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    samples = list(manifest["samples"])
    wanted = {s.strip() for s in (args.only or "").split(",") if s.strip()}
    if wanted:
        samples = [s for s in samples if s["sample_id"] in wanted]
    if not samples:
        print("没有匹配的样本", file=sys.stderr)
        return 2
    sample = samples[0]

    db_path = Path(args.db).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(db_path) + suffix)
        if candidate.exists():
            candidate.unlink()

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.backend.config import settings
    from src.backend.db.session import create_async_engine_from_url, init_db

    engine = create_async_engine_from_url(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    await init_db(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    from src.backend.utils.circuit_breaker import deepseek_circuit_breaker

    rows: List[Dict[str, Any]] = []
    async with factory() as db:
        for arm in ARMS:
            print(f"[arm] {arm['arm']} …", flush=True)
            deepseek_circuit_breaker.reset()
            actor = await _ensure_user(db, f"{sample['sample_id']}-{arm['arm']}")
            try:
                row = await _run_arm(db, actor, sample, corpus, arm, settings)
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                row = {
                    "arm": arm["arm"],
                    "note": arm["note"],
                    "status": "crashed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            rows.append(row)
            print(
                f"    -> status={row.get('status')} calls={row.get('model_calls')} "
                f"tokens={row.get('tokens')} coverage={row.get('coverage')}",
                flush=True,
            )

    payload = {
        "sample_id": sample["sample_id"],
        "model": os.getenv("DEEPSEEK_MODEL") or getattr(settings, "DEEPSEEK_MODEL", ""),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "arms": rows,
        "notes": [
            "同一份输入、同一个模型、同一提示词版本，只改变受理预算",
            "预算越界必须体现为 partial/needs_input 或带 BUDGET_EXCEEDED 的失败，绝不 succeeded",
            "cost_usd 未知为 null（不写 0）",
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.md:
        Path(args.md).write_text(_markdown(payload), encoding="utf-8")
    print(f"写入 {out}")
    return 0


def _markdown(payload: Dict[str, Any]) -> str:
    lines = [
        "# T23 预算闸门 A/B 实测（真实模型）",
        "",
        f"- 样本：`{payload['sample_id']}`（同一份文档、同一提示词版本）",
        f"- 模型：`{payload['model']}`",
        f"- 采集时间：{payload['generated_at']}",
        "",
        "| 方案 | 受理预算 | 终态 | 覆盖率 | 诊断数 | 调用 | tokens | 耗时(s) | 成果 | 预算评估 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["arms"]:
        budget = row.get("accepted_budget") or {}
        budget_text = (
            f"{budget.get('max_model_calls')} calls / {budget.get('max_tokens')} tok"
            if budget
            else "-"
        )
        coverage = row.get("coverage") or {}
        ratio = coverage.get("ratio")
        coverage_text = (
            f"{coverage.get('analyzed_blocks')}/{coverage.get('expected_blocks')} "
            f"({round(ratio * 100, 2)}%)"
            if ratio is not None
            else "-"
        )
        evaluation = row.get("budget_evaluation") or {}
        evaluation_text = (
            f"{evaluation.get('state')}"
            + (f"，超限 {','.join(evaluation.get('overruns') or [])}" if evaluation.get("overruns") else "")
            if evaluation
            else "-"
        )
        lines.append(
            "| {arm} | {budget} | {status} | {coverage} | {findings} | {calls} | {tokens} | {wall} | {artifacts} | {evaluation} |".format(
                arm=row.get("arm"),
                budget=budget_text,
                status=row.get("status"),
                coverage=coverage_text,
                findings=row.get("findings_total", "-"),
                calls=row.get("model_calls", "-"),
                tokens=row.get("tokens", "-"),
                wall=row.get("wall_seconds", "-"),
                artifacts=", ".join(row.get("artifacts") or []) or "-",
                evaluation=evaluation_text,
            )
        )
    lines += [
        "",
        "口径与限制：",
        "",
        "- 覆盖率取自任务的 `coverage_json`（分析块 / 应有块）；partial 任务的该字段可能为空，"
        "此时只解析错误信息里记录的「已分析/应有」块数，不补 0、不估算。",
        "- `cost_usd` 未知时写 null，不在报表里显示 0。",
        "- `预算评估=within` 表示闸门在「将要越界」前就停止继续调用，因此评估本身没跨线；"
        "代价是覆盖不足，终态按 FR-15 降为 partial，绝不 succeeded。",
        "- 这是**单篇、单次**测量，用于证明预算闸门行为，不是统计意义上的性能基准。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description="T23 预算闸门 A/B 实测")
    parser.add_argument("--corpus", default="tmp/r2-corpus")
    parser.add_argument("--only", default="p14-intelligent-communication")
    parser.add_argument("--db", default="tmp/budget-ab.db")
    parser.add_argument("--out", default="tmp/budget-ab.json")
    parser.add_argument("--md", default="docs/reports/R2_BUDGET_AB.md")
    args = parser.parse_args()
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("缺少 DEEPSEEK_API_KEY，无法做真实模型测量", file=sys.stderr)
        return 2
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
