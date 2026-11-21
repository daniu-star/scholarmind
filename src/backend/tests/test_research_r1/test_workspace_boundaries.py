"""T10·T14 / AT-008·AT-032·AT-033：R0 端点在 R1 语境下的边界回归。

R1 新增了检查点、来源适配与指标，但“幂等 / 归属 / 诚实失败”是跨版本不变量：
- 同一 Idempotency-Key + 同一请求只产生一个任务，重放返回同一快照；
- 同一 Key 换请求必须冲突，而不是默默建第二个任务；
- 用户 B 看不到、也不能取消用户 A 的任务（404，不泄露存在性）；
- 未通过归属校验的版本不能创建任务，失败时不留下半成品任务行。
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from ...research.models import ResearchTask
from ..test_research.conftest import (
    assert_error,
    create_project,
    create_task,
    task_body,
    upload_document,
    version_id_of,
)

pytestmark = pytest.mark.asyncio


async def _owned_document(client_a) -> tuple[str, str]:
    project_id = await create_project(client_a, "R1 边界回归项目")
    payload = await upload_document(
        client_a,
        project_id,
        filename="boundary.md",
        text="# 标题\n\n用于边界回归的正文，包含可分析的段落。\n",
    )
    return project_id, version_id_of(payload)


async def _task_count(db, owner_id: int) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(ResearchTask)
            .where(ResearchTask.owner_id == owner_id)
        )
        or 0
    )


class TestTaskIdempotency:
    async def test_same_key_same_body_replays_one_task(self, client_a, db, research_store):
        project_id, version_id = await _owned_document(client_a)
        body = task_body(project_id=project_id, document_version_id=version_id, kind="export")

        first = await create_task(client_a, body, idempotency_key="r1-replay-same-0001")
        second = await create_task(client_a, body, idempotency_key="r1-replay-same-0001")

        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text
        assert first.json()["task_id"] == second.json()["task_id"]
        assert first.json()["state_revision"] == second.json()["state_revision"]
        assert (
            await _task_count(db, research_store.user_ids["a"]) == 1
        )

    async def test_same_key_different_body_conflicts_without_second_task(
        self, client_a, db, research_store
    ):
        project_id, version_id = await _owned_document(client_a)
        body = task_body(project_id=project_id, document_version_id=version_id, kind="export")
        first = await create_task(client_a, body, idempotency_key="r1-replay-diff-0001")
        assert first.status_code == 202, first.text

        other = task_body(
            project_id=project_id,
            document_version_id=version_id,
            kind="export",
            objective="完全不同的任务目标，用于触发幂等冲突",
        )
        response = await create_task(
            client_a, other, idempotency_key="r1-replay-diff-0001"
        )

        error = assert_error(response, 409, "IDEMPOTENCY_CONFLICT")
        assert error["details"]["task_id"] == first.json()["task_id"]
        assert await _task_count(db, research_store.user_ids["a"]) == 1


class TestOwnershipBoundary:
    async def test_other_user_cannot_read_or_cancel_task(
        self, client_a, client_b, db, research_store
    ):
        project_id, version_id = await _owned_document(client_a)
        created = await create_task(
            client_a,
            task_body(project_id=project_id, document_version_id=version_id, kind="export"),
            idempotency_key="r1-owner-task-0001",
        )
        assert created.status_code == 202, created.text
        task_id = created.json()["task_id"]

        read = await client_b.get(f"/api/v1/research/tasks/{task_id}")
        assert_error(read, 404, "NOT_FOUND")

        cancel = await client_b.post(f"/api/v1/research/tasks/{task_id}/cancel")
        assert_error(cancel, 404, "NOT_FOUND")

        # 用户 B 的失败操作不得改变用户 A 任务的状态或归属。
        rows = await _task_count(db, research_store.user_ids["a"])
        assert rows == 1
        task = await db.scalar(
            select(ResearchTask).where(ResearchTask.id == task_id)
        )
        assert task is not None and task.owner_id == research_store.user_ids["a"]

    async def test_unknown_version_is_rejected_without_creating_task(
        self, client_a, db, research_store
    ):
        project_id, _ = await _owned_document(client_a)
        response = await create_task(
            client_a,
            task_body(project_id=project_id, document_version_id="rdv_does_not_exist"),
            idempotency_key="r1-unknown-version-0001",
        )

        assert_error(response, 404, "NOT_FOUND")
        assert await _task_count(db, research_store.user_ids["a"]) == 0

    async def test_anonymous_create_is_rejected(self, anon_client, db, research_store):
        response = await anon_client.post(
            "/api/v1/research/tasks",
            json=task_body(project_id="rproj_any", document_version_id="rdv_any"),
            headers={"Idempotency-Key": "r1-anon-task-0001"},
        )
        assert response.status_code in (401, 403), response.text
        assert await _task_count(db, research_store.user_ids["a"]) == 0