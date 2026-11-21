"""R2 预算接线：超预算的任务绝不能落成 ``succeeded``（T23 / FR-15 / AT-056）。

纯函数边界由 ``test_budget_contract.py`` 覆盖；这里只验证**真实执行链路**：

* 默认预算的导出任务照常 ``succeeded``（对照组，证明实验组不是环境坏了）；
* 预算越界后，同一导出任务必须以 ``partial`` 收尾（成果已产出但预算越界），
  ``error_json.code`` 为 ``BUDGET_EXCEEDED``，``budget_evaluation.state`` 为
  ``exceeded``，``overruns`` 点名超限项，``cost_known`` 为 ``False`` 而不是编造 0；
* 终态事件是 ``task.partial``，不得出现 ``task.completed``，序号仍连续。

为什么用 ``export``：导出任务不需要 external_review 权益、不调用模型，因此这个
用例既快又不需要任何模型替身。用量通过任务事件注入（与 review_workflow 写增量
用量的方式一致）来制造真实越界，而不是靠伪造返回值。
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from ...research import document_service, project_service, task_repository
from ...research.contracts import EventType
from ...research.models import Artifact, ResearchTask, TaskEvent
from ...research.task_runner import execute_task
from ...research.task_service import create_task

pytestmark = pytest.mark.asyncio

DOC_TEXT = (
    "# 论文标题\n\n"
    "第一段：样本量为 120 人，2023 年收集数据。\n\n"
    "第二段：结论仍需谨慎，作者应补充反例讨论。\n"
)

TIGHT_BUDGET = {
    "max_model_calls": 1,
    "max_tokens": 8,
    "max_duration_seconds": None,
    "max_cost_usd": None,
}


@pytest_asyncio.fixture
async def export_env(db, research_store):
    actor = research_store.actor("a")
    project = await project_service.create_project(db, actor, "预算降级验证")
    await db.commit()
    project_id = project["id"] if isinstance(project, dict) else project
    payload = await document_service.upload_document(
        db,
        actor,
        project_id,
        filename="budget.md",
        mime="text/markdown",
        data=DOC_TEXT.encode("utf-8"),
    )
    await db.commit()
    document = payload["document"]
    return {
        "actor": actor,
        "project_id": document["project_id"],
        "version_id": payload["version"]["id"],
    }


async def _create_export(db, env, key: str) -> ResearchTask:
    accepted = await create_task(
        db,
        env["actor"],
        {
            "schema_version": "1.0",
            "project_id": env["project_id"],
            "kind": "export",
            "objective": "验证超预算不会假成功",
            "input": {"document_version_id": env["version_id"]},
        },
        idempotency_key=key,
    )
    return (
        await db.execute(select(ResearchTask).where(ResearchTask.id == accepted.task_id))
    ).scalar_one()


async def _events(db, task_id: str) -> list[TaskEvent]:
    return list(
        (
            await db.execute(
                select(TaskEvent)
                .where(TaskEvent.task_id == task_id)
                .order_by(TaskEvent.sequence)
            )
        )
        .scalars()
        .all()
    )


async def _artifacts(db, task_id: str) -> list[Artifact]:
    return list(
        (
            await db.execute(select(Artifact).where(Artifact.task_id == task_id))
        )
        .scalars()
        .all()
    )


async def test_export_within_budget_still_succeeds(db, export_env):
    task = await _create_export(db, export_env, "r2-budget-control")
    recorded = task.constraints_json["accepted_budget"]
    assert set(recorded) >= {
        "max_model_calls",
        "max_tokens",
        "max_duration_seconds",
        "max_cost_usd",
    }
    assert recorded["max_cost_usd"] is None  # 没有价目表就不伪造金额上限

    await execute_task(db, task, holder="r2-verifier")
    await db.refresh(task)

    assert task.status == "succeeded"
    assert task.error_json is None
    artifacts = await _artifacts(db, task.id)
    assert artifacts and artifacts[0].kind == "export"
    events = await _events(db, task.id)
    assert events[-1].type == "task.completed"
    assert task.snapshot_summary["budget_evaluation"]["state"] == "within"


async def test_budget_overrun_degrades_to_partial_not_succeeded(db, export_env):
    task = await _create_export(db, export_env, "r2-budget-overrun")
    # 受理时冻结的预算被外部收紧（例如受理后才发现租户配额更小）。
    task.constraints_json = {
        **dict(task.constraints_json or {}),
        "accepted_budget": dict(TIGHT_BUDGET),
    }
    await db.commit()
    # 与诊断链路的增量用量事件同形：3 次调用 / 9 tokens，已超过上限 1 / 8。
    await task_repository.append_event(
        db,
        task,
        EventType.TASK_PROGRESS.value,
        payload={"usage_mode": "delta", "model_calls": 3, "tokens": 9},
    )
    await db.commit()

    await execute_task(db, task, holder="r2-verifier")
    await db.refresh(task)

    assert task.status != "succeeded"
    assert task.status == "partial"

    error = task.error_json or {}
    assert error.get("code") == "BUDGET_EXCEEDED"
    messages = error.get("errors") or []
    assert any("预算超限" in item for item in messages)
    assert any("3" in item and "1" in item for item in messages)

    evaluation = error["budget_evaluation"]
    assert evaluation["state"] == "exceeded"
    assert set(evaluation["overruns"]) >= {"model_calls", "tokens"}
    assert evaluation["checks"]["model_calls"] == {
        "limit": 1,
        "used": 3,
        "over": True,
        "ratio": 3.0,
    }
    assert evaluation["cost_known"] is False
    assert evaluation["usage"]["cost_usd"] is None

    # partial 的语义是"已交付已覆盖范围内的成果"，成果必须真的在。
    artifacts = await _artifacts(db, task.id)
    assert artifacts, "partial 必须留下已产出的成果，否则应判 failed"
    assert task.result_json["artifact_ids"] == [item.id for item in artifacts]

    events = await _events(db, task.id)
    assert events[-1].type == "task.partial"
    assert all(event.type != "task.completed" for event in events)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))


# ── 回归锁（D2 已修） ────────────────────────────────────────────────
# 生产路径 src/backend/research/task_service.py:431 传的是 TaskKind 枚举，
# 旧实现用 str(kind) 得到 "TaskKind.EXPORT"，匹配不到 NO_MODEL_KINDS，
# 于是"不调用模型"的导出/图表任务拿到 160 次调用 / 100000 tokens。
# budget.default_accepted_budget 现已先取枚举 .value 再剥前缀；本用例防止回退。


async def test_enum_kind_gets_zero_budget_for_no_model_tasks():
    from ...research import budget as budget_module
    from ...research.contracts import TaskKind

    for kind in (TaskKind.EXPORT, TaskKind.CHART):
        accepted = budget_module.default_accepted_budget(kind)
        assert accepted.max_model_calls == 0
        assert accepted.max_tokens == 0
