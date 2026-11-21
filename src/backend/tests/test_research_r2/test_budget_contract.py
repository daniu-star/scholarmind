"""T23 预算契约与任务接线（R2 / AT-048–AT-049·AT-052）。

预算的价值全在"诚实"：受理时固定上限、用量只能来自事件、超限必须降级为
``partial``/``needs_input`` 且带 ``BUDGET_EXCEEDED``，费用未知时永远是 ``None``
而不是 0。这里既测纯函数，也测"受理任务后预算真的被写进 DB"。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

from ...research import budget
from ...research.models import ResearchTask
from ..test_research.conftest import (
    create_project,
    create_task,
    task_body,
    upload_document,
    version_id_of,
)

def _event(sequence: int, attempt_no: int = 1, **payload):
    return SimpleNamespace(
        sequence=sequence,
        type="task.progress",
        attempt_no=attempt_no,
        payload=payload,
    )


@pytest_asyncio.fixture
async def entitled_user(research_env, db):
    """给种子用户开通 30 天会员：review 任务映射 external_review 权益。

    不便宜行事地改 plan 字段——走真实权益发放，才可能暴露映射错误。
    """
    from ...services.entitlement_service import EntitlementService

    user_id = research_env.user_ids["a"]
    await EntitlementService.grant_product(db, user_id, "monthly_pro", "r2-budget-grant")
    await db.commit()
    return user_id


# ── 纯函数：受理预算、用量重放、超限判定 ─────────────────────


def test_default_budget_follows_task_kind():
    review = budget.default_accepted_budget("review")
    assert review.max_model_calls == 160
    assert review.max_tokens == 100000
    assert review.max_duration_seconds == 1200

    revision = budget.default_accepted_budget("revision")
    assert revision.max_model_calls == 128

    export = budget.default_accepted_budget("export")
    assert export.max_model_calls == 0
    assert export.max_tokens == 0



def test_enum_kind_is_normalized_before_budget_lookup():
    """生产路径传的是 TaskKind 枚举（str() 得到 "TaskKind.EXPORT"）。

    规范化一旦漏掉，导出/图表任务会被误配成 160 次模型调用——预算就形同虚设。
    """
    from ...research.contracts import TaskKind

    for kind in (TaskKind.EXPORT, TaskKind.CHART):
        parsed = budget.default_accepted_budget(kind)
        assert parsed.max_model_calls == 0
        assert parsed.max_tokens == 0
        assert parsed.max_cost_usd is None

    review = budget.default_accepted_budget(TaskKind.REVIEW)
    assert review.max_model_calls == 160
    revision = budget.default_accepted_budget(TaskKind.REVISION)
    assert revision.max_model_calls == 128


def test_explicit_budget_overrides_and_rejects_garbage():
    parsed = budget.accepted_budget_from_mapping(
        {"max_model_calls": 3, "max_tokens": 10, "max_duration_seconds": 5.5}
    )
    assert parsed.max_model_calls == 3
    assert parsed.max_tokens == 10
    assert parsed.max_duration_seconds == 5.5
    assert parsed.max_cost_usd is None

    # 非法值不得被"修正"成一个看起来合理的数，只能是未设限。
    junk = budget.accepted_budget_from_mapping({"max_model_calls": "abc"})
    assert junk.max_model_calls is None


def test_usage_dedupes_by_sequence_and_never_fabricates_cost():
    events = [
        _event(2, usage_mode="delta", model_calls=1, tokens=10),
        _event(1, usage_mode="delta", model_calls=1, tokens=5),
        _event(2, usage_mode="delta", model_calls=1, tokens=10),  # 重复序列号，只算一次
    ]
    usage = budget.usage_from_events(events)
    assert usage.model_calls == 2
    assert usage.tokens == 15
    assert usage.cost_usd is None


def test_cumulative_usage_takes_max_per_attempt():
    events = [
        _event(1, attempt_no=1, usage_mode="cumulative", model_calls=1, tokens=10),
        _event(2, attempt_no=1, usage_mode="cumulative", model_calls=2, tokens=15),
        _event(3, attempt_no=2, usage_mode="cumulative", model_calls=1, tokens=5),
    ]
    usage = budget.usage_from_events(events)
    # 单次尝试内是累计值 → 取最大值再跨尝试相加，不能直接求和（否则 4 次）。
    assert usage.model_calls == 3
    assert usage.tokens == 20


def test_evaluate_budget_marks_overruns():
    accepted = budget.AcceptedBudget(max_model_calls=2, max_tokens=100)
    usage = budget.BudgetUsage(model_calls=3, tokens=120)
    evaluation = budget.evaluate_budget(accepted, usage)

    assert evaluation["state"] == "exceeded"
    assert set(evaluation["overruns"]) == {"model_calls", "tokens"}
    assert evaluation["cost_known"] is False
    assert evaluation["usage"]["cost_usd"] is None
    messages = budget.overrun_messages(evaluation)
    assert any("模型调用" in item for item in messages)
    assert any("tokens" in item for item in messages)
    details = budget.overrun_details(evaluation)
    assert {item["field"] for item in details} == {"model_calls", "tokens"}


def test_evaluate_budget_within_limits():
    accepted = budget.AcceptedBudget(max_model_calls=10, max_tokens=1000)
    evaluation = budget.evaluate_budget(
        accepted, budget.BudgetUsage(model_calls=1, tokens=10)
    )
    assert evaluation["state"] == "within"
    assert evaluation["overruns"] == []


# ── 接线：受理任务时预算被固定写入 ──────────────────────────


@pytest.mark.asyncio
async def test_task_creation_persists_accepted_budget(client_a, db, entitled_user):
    project_id = await create_project(client_a, "预算接线")
    doc = await upload_document(client_a, project_id, text="# 标题\n\n正文。\n")
    body = task_body(
        project_id=project_id,
        document_version_id=version_id_of(doc),
    )

    response = await create_task(client_a, body, idempotency_key="r2-budget-key-0001")
    assert response.status_code in (200, 201, 202), response.text
    payload = response.json()
    task_id = payload.get("task_id") or payload.get("id")

    db.expire_all()
    row = (
        await db.execute(select(ResearchTask).where(ResearchTask.id == task_id))
    ).scalar_one()
    constraints = row.constraints_json or {}
    accepted = constraints.get("accepted_budget")
    assert isinstance(accepted, dict)
    assert accepted["max_model_calls"] == 160
    assert accepted["max_tokens"] == 100000
    # 未知费用必须是 None，不能被填成 0；未设限的项也不能凭空出现。
    assert accepted["max_cost_usd"] is None
    assert set(accepted) >= {"max_model_calls", "max_tokens", "max_duration_seconds"}

    # 快照里也要能看到同一份预算，便于前端解释"为什么可能降级"。
    snapshot = row.snapshot_summary or {}
    assert snapshot.get("accepted_budget")["max_model_calls"] == 160


@pytest.mark.asyncio
async def test_retry_does_not_inflate_budget(client_a, db, entitled_user):
    project_id = await create_project(client_a, "预算重试")
    doc = await upload_document(client_a, project_id, text="# 标题\n\n正文。\n")
    body = task_body(
        project_id=project_id,
        document_version_id=version_id_of(doc),
    )
    created = await create_task(client_a, body, idempotency_key="r2-budget-key-0002")
    assert created.status_code in (200, 201, 202), created.text
    payload = created.json()
    task_id = payload.get("task_id") or payload.get("id")

    db.expire_all()
    first = (
        await db.execute(select(ResearchTask).where(ResearchTask.id == task_id))
    ).scalar_one()
    before = json.dumps(first.constraints_json or {}, sort_keys=True)

    retried = await client_a.post(
        f"/api/v1/research/tasks/{task_id}/retry",
        headers={"Idempotency-Key": "r2-budget-retry-0002"},
        json={},
    )
    assert retried.status_code in (200, 201, 202, 409, 422), retried.text

    db.expire_all()
    after = (
        await db.execute(select(ResearchTask).where(ResearchTask.id == task_id))
    ).scalar_one()
    if retried.status_code in (200, 201, 202):
        assert json.dumps(after.constraints_json or {}, sort_keys=True) == before
