"""T14 恢复语义（R1 / AT-038、AT-039、AT-042 补充）。

验证「进程崩溃 / 重复投递 / 用户取消 / SSE 重放」四类恢复场景的真实行为。
全部使用临时 SQLite + 真实 ``task_service`` / ``task_runner`` / ``dispatcher``，
不联网、不调真实模型（export 任务本身不需要模型）。

**边界说明（很重要）**：SQLite 只能证明“单进程内、串行提交”的恢复语义。
真正的 PG/Redis 多进程并发、租约跨进程过期、投递至少一次的网络重试，仍需在
生产同构环境验证；本文件不把它当作生产验证的替代。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from ...research import outbox, task_repository, task_runner, task_service
from ...research.contracts import (
    TERMINAL_STATUSES,
    TaskStatus,
    content_hash,
    utcnow,
)
from ...research.dispatcher import create_dispatcher
from ...research.errors import ResearchAPIError
from ...research.models import (
    Artifact,
    Document,
    DocumentVersion,
    Project,
    ResearchTask,
    TaskAttempt,
    TaskEvent,
)

pytestmark = pytest.mark.asyncio

EXPORT_TEXT = "第一段：样本量为 120 人，2023 年收集数据。\n\n第二段：结论仍需谨慎。"


# ── 夹具与工具 ────────────────────────────────────────────────


@pytest_asyncio.fixture
async def export_inputs(db, research_store) -> Dict[str, Any]:
    """为 A 用户准备真实项目 + 文档版本（导出任务不需要模型，便于恢复测试）。"""
    owner = research_store.user_ids["a"]
    now = utcnow()
    project = Project(
        id="rproj_recovery",
        owner_id=owner,
        title="恢复语义测试",
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(project)
    await db.flush()
    version = DocumentVersion(
        id="rver_recovery_1",
        document_id="rdoc_recovery",
        version_no=1,
        content_hash=content_hash(EXPORT_TEXT),
        text=EXPORT_TEXT,
        codepoints=len(EXPORT_TEXT),
        parse_status="complete",
        page_count=1,
        source="upload",
        created_at=now,
    )
    document = Document(
        id="rdoc_recovery",
        project_id=project.id,
        owner_id=owner,
        filename="recovery.md",
        mime="text/markdown",
        size_bytes=len(EXPORT_TEXT.encode("utf-8")),
        content_hash=version.content_hash,
        current_version_id=version.id,
        created_at=now,
        updated_at=now,
    )
    db.add(document)
    await db.flush()
    db.add(version)
    await db.flush()
    await db.commit()
    return {
        "project_id": project.id,
        "version_id": version.id,
        "owner_id": owner,
        "text": EXPORT_TEXT,
    }


async def _create_export_task(db, actor, inputs: Dict[str, Any], key: str) -> str:
    payload = {
        "schema_version": "1.0",
        "project_id": inputs["project_id"],
        "kind": "export",
        "objective": "导出恢复语义测试文档",
        "input": {"document_version_id": inputs["version_id"]},
        "scope": {},
        "constraints": {},
    }
    accepted = await task_service.create_task(db, actor, payload, idempotency_key=key)
    return accepted.task_id


async def _drain_once_and_wait(dispatcher, *, timeout: float = 20.0) -> int:
    """跑一轮派发，并等待本轮启动的执行协程结束（dispatcher 不等它们）。"""
    dispatched = await dispatcher.drain_once()
    jobs = list(getattr(dispatcher, "_in_flight", ()))
    if jobs:
        await asyncio.wait_for(asyncio.gather(*jobs, return_exceptions=True), timeout=timeout)
    return dispatched


async def _reload(db, task_id: str) -> ResearchTask:
    db.expire_all()
    task = await db.get(ResearchTask, task_id)
    assert task is not None
    return task


async def _events(store, task_id: str) -> List[TaskEvent]:
    async with store.session_factory() as session:
        result = await session.execute(
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id)
            .order_by(TaskEvent.sequence)
        )
        return list(result.scalars().all())


def _event_tuples(events: List[TaskEvent]) -> List[Any]:
    """把事件压成可比较的纯数据（跨 session 的 ORM 对象身份不同，不能直接比较）。"""
    return [(event.sequence, event.attempt_no, event.type, event.payload_json) for event in events]


async def _count(store, model) -> int:
    async with store.session_factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def _wait_status(store, task_id: str, *, timeout: float = 20.0) -> ResearchTask:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        async with store.session_factory() as session:
            task = await session.get(ResearchTask, task_id)
            if task is not None and TaskStatus(task.status) in TERMINAL_STATUSES:
                return task
        await asyncio.sleep(0.05)
    raise AssertionError(f"任务 {task_id} 未在 {timeout}s 内进入终态")


def _sse_frames(body: str) -> List[Dict[str, Any]]:
    frames: List[Dict[str, Any]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        frame: Dict[str, Any] = {}
        for line in block.splitlines():
            if line.startswith("id: "):
                frame["id"] = line[len("id: "):]
            elif line.startswith("event: "):
                frame["event"] = line[len("event: "):]
            elif line.startswith("data: "):
                frame["data"] = json.loads(line[len("data: "):])
        if frame:
            frames.append(frame)
    return frames


# ── 1. 投递前崩溃：重启后仍能派发 ─────────────────────────────


async def test_pending_outbox_is_dispatched_after_restart(db, research_store, export_inputs):
    task_id = await _create_export_task(
        db, research_store.actor("a"), export_inputs, "recovery-restart-0001"
    )

    # 崩溃前状态：任务已登记、outbox 有待投递消息、任务尚未开始执行。
    async with research_store.session_factory() as session:
        task = await session.get(ResearchTask, task_id)
        assert task is not None
        assert task.status == TaskStatus.QUEUED.value
        assert task.attempt_no == 0
        pending = await outbox.pending(session)
        assert len(pending) == 1
        assert pending[0].task_id == task_id
        assert pending[0].published_at is None
        attempts = await session.scalar(
            select(func.count()).select_from(TaskAttempt).where(TaskAttempt.task_id == task_id)
        )
        assert attempts == 0

    # 模拟进程重启：新建派发器（不调用 start()，等价于崩溃后第一次轮询）。
    dispatcher = create_dispatcher(research_store.session_factory)
    dispatched = await _drain_once_and_wait(dispatcher)
    assert dispatched >= 1

    started = await _wait_status(research_store, task_id)
    assert started.status == TaskStatus.SUCCEEDED.value
    assert started.attempt_no == 1
    assert started.billing_state is not None

    events = await _events(research_store, task_id)
    assert [event.type for event in events] == [
        "task.accepted",
        "task.started",
        "artifact.created",
        "task.completed",
    ]
    assert [event.sequence for event in events] == [1, 2, 3, 4]
    assert events[-1].payload_json["artifact_ids"]

    async with research_store.session_factory() as session:
        message = (
            await session.execute(
                select(outbox.OutboxMessage).where(outbox.OutboxMessage.task_id == task_id)
            )
        ).scalars().first()
        assert message is not None
        assert message.published_at is not None


# ── 2. 重复投递：只执行一次 ───────────────────────────────────


async def test_duplicate_outbox_delivery_executes_task_only_once(
    db, research_store, export_inputs
):
    task_id = await _create_export_task(
        db, research_store.actor("a"), export_inputs, "recovery-duplicate-0001"
    )

    dispatcher = create_dispatcher(research_store.session_factory)
    await _drain_once_and_wait(dispatcher)
    await _wait_status(research_store, task_id)

    first_events = _event_tuples(await _events(research_store, task_id))
    first_artifact_count = await _count(research_store, Artifact)

    # 重复投递：再挂一条同样的 task.accepted 消息（模拟至少一次投递语义）。
    async with research_store.session_factory() as session:
        outbox.enqueue(
            session,
            outbox.TOPIC_TASK_ACCEPTED,
            {"task_id": task_id},
            task_id=task_id,
        )
        await session.commit()

    await _drain_once_and_wait(dispatcher)

    assert await _count(research_store, Artifact) == first_artifact_count == 1
    assert _event_tuples(await _events(research_store, task_id)) == first_events
    async with research_store.session_factory() as session:
        attempts = await session.scalar(
            select(func.count()).select_from(TaskAttempt).where(TaskAttempt.task_id == task_id)
        )
        terminal_events = await session.scalar(
            select(func.count())
            .select_from(TaskEvent)
            .where(
                TaskEvent.task_id == task_id,
                TaskEvent.type.in_(
                    ["task.completed", "task.partial", "task.failed", "task.cancelled"]
                ),
            )
        )
    assert attempts == 1
    assert terminal_events == 1


# ── 3. 租约/fencing：重复领取被拒绝，旧租约不能覆盖 ───────────


async def test_lease_prevents_second_worker_and_stale_worker_cannot_write(
    db, research_store, export_inputs
):
    task_id = await _create_export_task(
        db, research_store.actor("a"), export_inputs, "recovery-lease-0001"
    )
    task = await db.get(ResearchTask, task_id)
    assert task is not None

    # worker-1 抢占租约（模拟执行中崩溃，租约尚未过期）。
    await task_repository.open_attempt(db, task, lease_holder="worker-1")
    await db.commit()
    before_events = len(await _events(research_store, task_id))

    with pytest.raises(ResearchAPIError) as lease_error:
        await task_repository.open_attempt(db, task, lease_holder="worker-2")
    assert lease_error.value.code == "LEASE_HELD"
    assert lease_error.value.status_code == 409

    # 第二个执行器（重复投递）会被安全放弃：不新增 attempt、不写事件。
    await task_runner.execute_task(db, task, holder="worker-2")
    assert len(await _events(research_store, task_id)) == before_events
    async with research_store.session_factory() as session:
        attempts = await session.scalar(
            select(func.count()).select_from(TaskAttempt).where(TaskAttempt.task_id == task_id)
        )
        assert attempts == 1

    # 旧 worker 结束后，新的执行器可以正常接管并完成任务。
    async with research_store.session_factory() as session:
        attempt = (
            await session.execute(
                select(TaskAttempt).where(TaskAttempt.task_id == task_id)
            )
        ).scalars().first()
        assert attempt is not None
        await task_repository.close_attempt(session, attempt, "failed")
        await session.commit()

    task = await _reload(db, task_id)
    await task_runner.execute_task(db, task, holder="worker-3")
    finished = await _wait_status(research_store, task_id)
    assert finished.status == TaskStatus.SUCCEEDED.value
    assert finished.attempt_no == 2


# ── 4. 取消后的迟到写入被拒绝 ────────────────────────────────


async def test_cancel_rejects_late_worker_writes(db, research_store, export_inputs):
    task_id = await _create_export_task(
        db, research_store.actor("a"), export_inputs, "recovery-cancel-0001"
    )

    snapshot = await task_service.cancel_task(db, research_store.actor("a"), task_id)
    assert snapshot.status == TaskStatus.CANCELLED

    # 迟到的执行器：任务已终态，execute_task 必须直接跳过。
    task = await _reload(db, task_id)
    await task_runner.execute_task(db, task, holder="late-worker")

    assert await _count(research_store, Artifact) == 0
    events = await _events(research_store, task_id)
    assert [event.type for event in events] == ["task.accepted", "task.cancelled"]
    assert [event.sequence for event in events] == [1, 2]
    async with research_store.session_factory() as session:
        attempts = await session.scalar(
            select(func.count()).select_from(TaskAttempt).where(TaskAttempt.task_id == task_id)
        )
    assert attempts == 0

    # 旧 worker 手里的状态迁移也必须被拒绝（终态不可回到 running）。
    task = await _reload(db, task_id)
    with pytest.raises(ResearchAPIError) as transition_error:
        await task_repository.transition(db, task, TaskStatus.RUNNING)
    assert transition_error.value.code == "INVALID_TRANSITION"
    assert transition_error.value.status_code == 409

    finished = await _reload(db, task_id)
    assert finished.status == TaskStatus.CANCELLED.value


# ── 5. SSE 事件重放幂等 ──────────────────────────────────────


async def test_sse_replay_is_idempotent(client_a, research_store, export_inputs):
    async with research_store.session_factory() as session:
        payload = {
            "schema_version": "1.0",
            "project_id": export_inputs["project_id"],
            "kind": "export",
            "objective": "SSE 重放测试",
            "input": {"document_version_id": export_inputs["version_id"]},
            "scope": {},
            "constraints": {},
        }
        accepted = await task_service.create_task(
            session, research_store.actor("a"), payload, idempotency_key="recovery-sse-0001"
        )
        task_id = accepted.task_id

    async with research_store.session_factory() as session:
        task = await session.get(ResearchTask, task_id)
        assert task is not None
        await task_runner.execute_task(session, task, holder="sse-worker")
    await _wait_status(research_store, task_id)

    url = f"/api/v1/research/tasks/{task_id}/events?after_sequence=0"
    first = await client_a.get(url)
    assert first.status_code == 200
    frames = _sse_frames(first.text)
    assert [int(frame["id"]) for frame in frames] == [1, 2, 3, 4]
    assert [frame["event"] for frame in frames] == [
        "task.accepted",
        "task.started",
        "artifact.created",
        "task.completed",
    ]

    # 同一游标重放必须返回完全相同的事件流（幂等，不追加也不丢帧）。
    second = await client_a.get(url)
    assert second.status_code == 200
    assert _sse_frames(second.text) == frames

    # 终态 + Last-Event-ID 已是最新：不再返回任何帧，连接立即结束。
    last_id = frames[-1]["id"]
    tail = await client_a.get(
        f"/api/v1/research/tasks/{task_id}/events",
        headers={"Last-Event-ID": last_id},
    )
    assert tail.status_code == 200
    assert _sse_frames(tail.text) == []


# ── 6. 终态任务不再产生新的 attempt（恢复边界）────────────────


async def test_terminal_task_is_never_reclaimed(
    db, research_store, export_inputs, monkeypatch
):
    task_id = await _create_export_task(
        db, research_store.actor("a"), export_inputs, "recovery-terminal-0001"
    )
    dispatcher = create_dispatcher(research_store.session_factory)
    await _drain_once_and_wait(dispatcher)
    await _wait_status(research_store, task_id)

    async with research_store.session_factory() as session:
        task = await session.get(ResearchTask, task_id)
        assert task is not None
        with pytest.raises(ResearchAPIError) as claim_error:
            await task_repository.open_attempt(session, task, lease_holder="after-terminal")
        assert claim_error.value.code == "TASK_NOT_CLAIMABLE"
        assert claim_error.value.status_code == 409

    attempts = await _count(research_store, TaskAttempt)
    assert attempts == 1

