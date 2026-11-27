"""broker 丢消息后的兜底清扫（FR-11 / FR-15）。

为什么必须测：Redis 未持久化时消息会凭空消失，任务就永久停在 ``queued``。
此时既没有执行器也没有错误——用户只看到「一直排队」，这违反「诚实失败」。
清扫器把超时任务置为 ``failed(QUEUE_TIMEOUT)`` 并归还额度；但只有在
Celery beat 真正注册了周期任务时才可能发生，因此这里同时钉死注册关系。
"""
from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from ...research import task_service
from ...research.models import ResearchTask, TaskEvent
from ...research.contracts import utcnow
from ..test_research.conftest import (
    create_project,
    create_task,
    task_body,
    upload_document,
    version_id_of,
)


@pytest_asyncio.fixture
async def entitled_user(research_env, db):
    """review 任务映射 external_review 权益，必须先真实发放。"""
    from ...services.entitlement_service import EntitlementService

    user_id = research_env.user_ids["a"]
    await EntitlementService.grant_product(db, user_id, "monthly_pro", "r2-reaper-grant")
    await db.commit()
    return user_id


async def _queued_task(client, *, key: str = "reaper-task-1") -> str:
    project_id = await create_project(client, title="清扫验证项目")
    uploaded = await upload_document(
        client,
        project_id,
        text="# 引言\n\n" + "本文讨论平台算法与新闻消费的关系。" * 12 + "\n",
    )
    body = task_body(project_id=project_id, document_version_id=version_id_of(uploaded))
    response = await create_task(client, body, idempotency_key=key)
    assert response.status_code in (200, 201, 202), response.text
    return response.json()["task_id"]


async def _backdate(db, task_id: str, seconds: int) -> None:
    await db.execute(
        update(ResearchTask)
        .where(ResearchTask.id == task_id)
        .values(created_at=utcnow() - timedelta(seconds=seconds))
    )
    await db.commit()


def _queue_wait_seconds() -> int:
    return int(task_service.MAX_QUEUE_WAIT_SECONDS)


@pytest.mark.asyncio
async def test_stale_queued_task_fails_honestly_and_releases_billing(
    client_a, db, entitled_user
):
    task_id = await _queued_task(client_a)
    # 超过排队上限：default 300s，这里多给 60s 余量。
    await _backdate(db, task_id, _queue_wait_seconds() + 60)

    handled = await task_service.expire_stale_queued_tasks(db)
    assert handled == 1

    task = await db.get(ResearchTask, task_id, populate_existing=True)
    assert task.status == "failed"
    assert (task.error_json or {}).get("code") == "QUEUE_TIMEOUT"
    assert (task.error_json or {}).get("retryable") is True
    assert task.billing_state == "released"

    events = (
        await db.execute(
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id, TaskEvent.type == "task.failed")
            .order_by(TaskEvent.sequence)
        )
    ).scalars().all()
    assert len(events) == 1
    # 事件载荷就是错误体本身（task_repository.transition(error=...) 直接落盘）。
    assert events[0].payload_json.get("code") == "QUEUE_TIMEOUT"


@pytest.mark.asyncio
async def test_fresh_queued_task_is_not_touched(client_a, db, entitled_user):
    task_id = await _queued_task(client_a, key="reaper-task-2")

    assert await task_service.expire_stale_queued_tasks(db) == 0

    task = await db.get(ResearchTask, task_id, populate_existing=True)
    assert task.status == "queued"
    assert task.error_json is None


@pytest.mark.asyncio
async def test_reaper_is_idempotent(client_a, db, entitled_user):
    task_id = await _queued_task(client_a, key="reaper-task-3")
    await _backdate(db, task_id, _queue_wait_seconds() + 60)

    assert await task_service.expire_stale_queued_tasks(db) == 1
    # 第二次不能再失败一次，也不能再退还一次额度。
    assert await task_service.expire_stale_queued_tasks(db) == 0


def test_beat_schedule_registers_reaper():
    """只有真正注册进 beat，周期清扫才存在；这是本缺陷的根因所在。"""
    from ...scheduler import research_tasks
    from ...scheduler.celery_app import celery_app

    entry = celery_app.conf.beat_schedule.get("research-reap-stale-queued")
    assert entry is not None
    assert entry["task"] == "research.reap_stale_queued"
    assert "research.reap_stale_queued" in celery_app.tasks
    assert research_tasks.reap_stale_queued.name == "research.reap_stale_queued"
