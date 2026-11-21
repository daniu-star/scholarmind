"""T19 产品指标（AT-040 / AT-043 / AT-050 / AT-052）。

覆盖两层：
1. ``research.analytics`` 纯聚合口径（成功率分母、事件去重、分位数、均值、
   owner/时间窗隔离、不泄露正文）；
2. ``GET /api/v1/research/metrics`` 的鉴权、self 作用域与结构。

造数据只用临时 SQLite；不联网、不调模型、不写生产表。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ...research import analytics
from ...research.contracts import new_id
from ...research.models import (
    Artifact,
    Document,
    FindingRow,
    Project,
    ResearchTask,
    RevisionProposalRow,
    TaskEvent,
)
from .conftest import assert_error

pytestmark = pytest.mark.asyncio

BASE = datetime(2026, 1, 1, 0, 0, 0)
TASK_KEYS = {
    "total",
    "succeeded",
    "partial",
    "failed",
    "cancelled",
    "needs_input",
    "success_rate",
    "retried_tasks",
    "replay_events_deduped",
    "p50_duration_seconds",
    "p95_duration_seconds",
    "avg_model_calls",
    "avg_tokens",
}
FUNNEL_KEYS = {
    "projects",
    "documents",
    "tasks_by_kind",
    "tasks_with_findings",
    "findings_total",
    "proposals_created",
    "proposals_applied",
    "artifacts_created",
    "exports",
    "first_finding_rate",
    "apply_rate",
}


def _task(
    owner_id: int,
    *,
    status: str = "queued",
    kind: str = "review",
    created_at: datetime | None = None,
    ended_at: datetime | None = None,
    attempt_no: int = 1,
    retry_of: str | None = None,
    task_id: str | None = None,
    project_id: str = "proj_metric",
) -> ResearchTask:
    return ResearchTask(
        id=task_id or new_id("task"),
        owner_id=owner_id,
        project_id=project_id,
        kind=kind,
        status=status,
        objective="聚合口径验证用的任务目标（不得出现在指标返回里）",
        input_json={},
        scope_json={},
        constraints_json={},
        state_revision=1,
        billing_group_id=new_id("bg"),
        attempt_no=attempt_no,
        snapshot_summary={},
        created_at=created_at or BASE,
        ended_at=ended_at,
        retry_of=retry_of,
    )


def _finish(task: ResearchTask, seconds: float) -> ResearchTask:
    task.ended_at = task.created_at + timedelta(seconds=seconds)
    return task


async def test_success_rate_denominator_excludes_cancelled_and_in_flight(db, research_store):
    owner = research_store.user_ids["a"]
    rows = [
        _task(owner, status="succeeded"),
        _task(owner, status="succeeded"),
        _task(owner, status="partial"),
        _task(owner, status="failed"),
        _task(owner, status="cancelled"),
        _task(owner, status="cancelled"),
        _task(owner, status="queued"),
        _task(owner, status="running"),
        _task(owner, status="needs_input"),
        _task(owner, status="recoverable"),
    ]
    db.add_all(rows)
    await db.flush()

    metrics = await analytics.task_metrics(db)

    assert set(metrics) == TASK_KEYS
    assert metrics["total"] == 10
    assert metrics["succeeded"] == 2
    assert metrics["partial"] == 1
    assert metrics["failed"] == 1
    assert metrics["cancelled"] == 2
    assert metrics["needs_input"] == 1
    # 2 / (2 + 1 + 1)：取消与在途都不在分母
    assert metrics["success_rate"] == pytest.approx(0.5)


async def test_zero_denominators_return_none_not_zero_or_nan(db, research_store):
    owner = research_store.user_ids["a"]
    db.add_all([_task(owner, status="queued"), _task(owner, status="running")])
    await db.flush()

    metrics = await analytics.task_metrics(db)
    funnel = await analytics.funnel_metrics(db)

    assert metrics["total"] == 2
    assert metrics["success_rate"] is None
    assert metrics["p50_duration_seconds"] is None
    assert metrics["p95_duration_seconds"] is None
    assert metrics["avg_model_calls"] is None
    assert metrics["avg_tokens"] is None
    # 窗口内没有任何任务 → 漏斗率为 None；没有提案 → apply_rate 为 None
    assert funnel["tasks_by_kind"] == {"review": 2}
    assert funnel["first_finding_rate"] == pytest.approx(0.0)
    assert funnel["apply_rate"] is None
    for value in metrics.values():
        assert value is None or isinstance(value, (int, float))


async def test_terminal_event_replay_is_counted_once(db, research_store):
    owner = research_store.user_ids["a"]
    duplicated = _task(owner, status="succeeded")
    single = _task(owner, status="failed")
    db.add_all([duplicated, single])
    await db.flush()
    db.add_all(
        [
            TaskEvent(
                task_id=duplicated.id,
                sequence=1,
                attempt_no=1,
                type="task.completed",
                payload_json={},
                created_at=BASE,
            ),
            # 断线重放/重复回调造成的多余终态事件
            TaskEvent(
                task_id=duplicated.id,
                sequence=2,
                attempt_no=1,
                type="task.completed",
                payload_json={},
                created_at=BASE,
            ),
            TaskEvent(
                task_id=duplicated.id,
                sequence=3,
                attempt_no=1,
                type="task.completed",
                payload_json={},
                created_at=BASE,
            ),
            TaskEvent(
                task_id=single.id,
                sequence=1,
                attempt_no=1,
                type="task.failed",
                payload_json={},
                created_at=BASE,
            ),
        ]
    )
    await db.flush()

    metrics = await analytics.task_metrics(db)

    # 任务数按 task_id 计（2），不会被 4 条事件放大；去重量 = 2 条多余终态事件
    assert metrics["total"] == 2
    assert metrics["replay_events_deduped"] == 2


async def test_retried_tasks_counted_once_per_task_row(db, research_store):
    owner = research_store.user_ids["a"]
    retried_by_lineage = _task(owner, status="succeeded", attempt_no=1)
    retried_by_attempt = _task(owner, status="failed", attempt_no=2)
    # 同时满足 retry_of 与 attempt_no>1 仍只算一次
    both = _task(owner, status="succeeded", attempt_no=3, retry_of=retried_by_lineage.id)
    plain = _task(owner, status="succeeded", attempt_no=1)
    db.add_all([retried_by_lineage, retried_by_attempt, both, plain])
    await db.flush()

    metrics = await analytics.task_metrics(db)
    # 口径：统计“本身是重试产物的任务行”，被重试的原任务不计数
    assert metrics["retried_tasks"] == 2


async def test_durations_only_from_finished_tasks_and_use_linear_percentiles(db, research_store):
    owner = research_store.user_ids["a"]
    rows = [
        _finish(_task(owner, status="succeeded"), 10),
        _finish(_task(owner, status="partial"), 20),
        _finish(_task(owner, status="failed"), 30),
        _finish(_task(owner, status="cancelled"), 40),
        # 未结束任务不进入耗时样本
        _task(owner, status="running"),
    ]
    db.add_all(rows)
    await db.flush()

    metrics = await analytics.task_metrics(db)

    assert metrics["p50_duration_seconds"] == pytest.approx(25.0)
    assert metrics["p95_duration_seconds"] == pytest.approx(38.5)


async def test_model_usage_requires_recorded_artifacts(db, research_store):
    owner = research_store.user_ids["a"]
    first = _task(owner, status="succeeded")
    second = _task(owner, status="succeeded")
    unmeasured = _task(owner, status="succeeded")
    db.add_all([first, second, unmeasured])
    await db.flush()
    db.add_all(
        [
            Artifact(
                id=new_id("art"),
                owner_id=owner,
                task_id=first.id,
                kind="review_report",
                version=1,
                content_hash="h1",
                mime="text/markdown",
                filename="a.md",
                body="body",
                size_bytes=4,
                validation_json={"calls": 3, "output_tokens": 100},
                created_at=BASE,
            ),
            Artifact(
                id=new_id("art"),
                owner_id=owner,
                task_id=second.id,
                kind="review_report",
                version=1,
                content_hash="h2",
                mime="text/markdown",
                filename="b.md",
                body="body",
                size_bytes=4,
                validation_json={"calls": 5, "tokens": 300},
                created_at=BASE,
            ),
            Artifact(
                id=new_id("art"),
                owner_id=owner,
                task_id=unmeasured.id,
                kind="review_report",
                version=1,
                content_hash="h3",
                mime="text/markdown",
                filename="c.md",
                body="body",
                size_bytes=4,
                validation_json={},
                created_at=BASE,
            ),
        ]
    )
    await db.flush()

    metrics = await analytics.task_metrics(db)

    # 只对有留痕的任务求均值：未测量不等于 0
    assert metrics["avg_model_calls"] == pytest.approx(4.0)
    assert metrics["avg_tokens"] == pytest.approx(200.0)


async def test_owner_and_since_scope_are_applied(db, research_store):
    owner_a = research_store.user_ids["a"]
    owner_b = research_store.user_ids["b"]
    old = _finish(_task(owner_a, status="succeeded", created_at=BASE), 5)
    new = _finish(_task(owner_a, status="failed", created_at=BASE + timedelta(days=1)), 5)
    foreign = _finish(_task(owner_b, status="succeeded", created_at=BASE + timedelta(days=2)), 5)
    db.add_all([old, new, foreign])
    await db.flush()

    scoped = await analytics.task_metrics(db, owner_id=owner_a)
    assert scoped["total"] == 2
    assert scoped["succeeded"] == 1 and scoped["failed"] == 1

    windowed = await analytics.task_metrics(
        db, owner_id=owner_a, since=BASE + timedelta(hours=12)
    )
    assert windowed["total"] == 1
    assert windowed["failed"] == 1

    # 带时区的 since 必须换算到 UTC naive 后再比较，而不是直接报错/忽略
    aware = await analytics.task_metrics(
        db,
        owner_id=owner_a,
        since=(BASE + timedelta(hours=12)).replace(tzinfo=timezone.utc),
    )
    assert aware["total"] == 1


async def test_funnel_counts_and_rates(db, research_store):
    owner = research_store.user_ids["a"]
    project = Project(id=new_id("proj"), owner_id=owner, title="漏斗项目", created_at=BASE)
    db.add(project)
    await db.flush()
    db.add(
        Document(
            id=new_id("doc"),
            project_id=project.id,
            owner_id=owner,
            filename="paper.md",
            mime="text/markdown",
            size_bytes=10,
            content_hash="h",
            created_at=BASE,
        )
    )
    review = _task(owner, status="succeeded", kind="review", created_at=BASE)
    export_task = _task(owner, status="succeeded", kind="export", created_at=BASE)
    revision = _task(owner, status="succeeded", kind="revision", created_at=BASE)
    db.add_all([review, export_task, revision])
    await db.flush()
    db.add_all(
        [
            FindingRow(
                id=new_id("find"),
                task_id=review.id,
                owner_id=owner,
                version_id="ver_x",
                scope="document",
                category="structure",
                severity="major",
                problem="缺少结论章节",
                reason="结构检查",
                recommendation="补充结论",
                evidence_refs=[],
                locator={"scope": "document"},
                quote=None,
                checked_sections=["1 引言"],
                verification_method="structural",
                created_at=BASE,
            ),
            FindingRow(
                id=new_id("find"),
                task_id=review.id,
                owner_id=owner,
                version_id="ver_x",
                scope="document",
                category="evidence",
                severity="minor",
                problem="引文不足",
                reason="结构检查",
                recommendation="补充引文",
                evidence_refs=[],
                locator={"scope": "document"},
                quote=None,
                checked_sections=["1 引言"],
                verification_method="structural",
                created_at=BASE,
            ),
            RevisionProposalRow(
                id=new_id("prop"),
                task_id=revision.id,
                owner_id=owner,
                base_version_id="ver_x",
                selected_findings=[],
                hunks_json=[],
                validation_report={},
                status="applied",
                created_at=BASE,
            ),
            RevisionProposalRow(
                id=new_id("prop"),
                task_id=revision.id,
                owner_id=owner,
                base_version_id="ver_x",
                selected_findings=[],
                hunks_json=[],
                validation_report={},
                status="proposed",
                created_at=BASE,
            ),
            Artifact(
                id=new_id("art"),
                owner_id=owner,
                task_id=review.id,
                kind="review_report",
                version=1,
                content_hash="h1",
                mime="text/markdown",
                filename="a.md",
                body="body",
                size_bytes=4,
                validation_json={},
                created_at=BASE,
            ),
            Artifact(
                id=new_id("art"),
                owner_id=owner,
                task_id=export_task.id,
                kind="export",
                version=1,
                content_hash="h2",
                mime="text/markdown",
                filename="b.md",
                body="body",
                size_bytes=4,
                validation_json={},
                created_at=BASE,
            ),
        ]
    )
    await db.flush()

    funnel = await analytics.funnel_metrics(db)

    assert set(funnel) == FUNNEL_KEYS
    assert funnel["projects"] == 1
    assert funnel["documents"] == 1
    assert funnel["tasks_by_kind"] == {"review": 1, "export": 1, "revision": 1}
    assert funnel["tasks_with_findings"] == 1
    assert funnel["findings_total"] == 2
    assert funnel["proposals_created"] == 2
    assert funnel["proposals_applied"] == 1
    assert funnel["artifacts_created"] == 2
    assert funnel["exports"] == 1
    assert funnel["first_finding_rate"] == pytest.approx(1 / 3)
    assert funnel["apply_rate"] == pytest.approx(0.5)


async def test_metrics_never_include_free_text_columns(db, research_store):
    owner = research_store.user_ids["a"]
    task = _task(owner, status="succeeded", created_at=BASE)
    db.add(task)
    await db.flush()
    db.add(
        FindingRow(
            id=new_id("find"),
            task_id=task.id,
            owner_id=owner,
            version_id="ver_x",
            scope="local",
            category="argument",
            severity="critical",
            problem="这里是被引用的正文原句",
            reason="原因文本",
            recommendation="建议文本",
            evidence_refs=["ev1"],
            locator={"scope": "document"},
            quote="逐字引用原文",
            checked_sections=["1 引言"],
            verification_method="model",
            created_at=BASE,
        )
    )
    await db.flush()

    metrics = await analytics.task_metrics(db)
    funnel = await analytics.funnel_metrics(db)
    serialized = repr({"tasks": metrics, "funnel": funnel})

    for forbidden in ("正文原句", "逐字引用原文", "原因文本", "建议文本", "任务目标"):
        assert forbidden not in serialized


async def test_metrics_endpoint_requires_authentication(anon_client):
    response = await anon_client.get("/api/v1/research/metrics")
    assert_error(response, 401)


async def test_metrics_endpoint_is_self_scoped_and_never_leaks_foreign_tasks(
    client_a, client_b, research_store, db
):
    owner_a = research_store.user_ids["a"]
    owner_b = research_store.user_ids["b"]
    db.add_all(
        [
            _task(owner_a, status="succeeded"),
            _task(owner_a, status="failed"),
            _task(owner_b, status="succeeded"),
            _task(owner_b, status="succeeded"),
            _task(owner_b, status="failed"),
        ]
    )
    await db.flush()
    await db.commit()

    response_a = await client_a.get("/api/v1/research/metrics")
    assert response_a.status_code == 200, response_a.text
    payload_a = response_a.json()
    assert payload_a["scope"] == "self"
    assert payload_a["since"] is None
    assert payload_a["tasks"]["total"] == 2, payload_a
    assert payload_a["tasks"]["succeeded"] == 1
    assert payload_a["tasks"]["failed"] == 1
    assert payload_a["tasks"]["success_rate"] == pytest.approx(0.5)

    response_b = await client_b.get("/api/v1/research/metrics")
    assert response_b.status_code == 200, response_b.text
    assert response_b.json()["tasks"]["total"] == 3

    serialized = response_a.text
    assert "任务目标" not in serialized
    assert "objective" not in payload_a["tasks"]


async def test_metrics_endpoint_since_filter_and_shape(client_a, research_store, db):
    owner = research_store.user_ids["a"]
    db.add_all(
        [
            _finish(_task(owner, status="succeeded", created_at=BASE), 10),
            _finish(
                _task(owner, status="failed", created_at=BASE + timedelta(days=2)),
                20,
            ),
        ]
    )
    await db.flush()
    await db.commit()

    response = await client_a.get(
        "/api/v1/research/metrics", params={"since": "2026-01-02T00:00:00"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"scope", "since", "tasks", "funnel"}
    assert body["since"].startswith("2026-01-02")
    assert body["tasks"]["total"] == 1
    assert body["tasks"]["failed"] == 1
    assert set(body["tasks"]) == TASK_KEYS
    assert set(body["funnel"]) == FUNNEL_KEYS


async def test_metrics_endpoint_rejects_malformed_since(client_a):
    response = await client_a.get(
        "/api/v1/research/metrics", params={"since": "not-a-timestamp"}
    )
    assert response.status_code in (400, 422), response.text
