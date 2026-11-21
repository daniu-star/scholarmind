"""研究任务 REST 契约（R0：AT-004、AT-006、AT-007、AT-038、AT-039、AT-040）。

全部走真实 HTTP：httpx AsyncClient + 真 app + 临时 SQLite。
断言状态码、统一错误码、任务快照字段与事件序号，而不是“函数存在”。
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from ...research.models import Artifact, FindingRow, ResearchTask, TaskEvent
from .conftest import (
    assert_error,
    create_project,
    create_task,
    task_body,
    upload_document,
    version_id_of,
)

pytestmark = pytest.mark.asyncio


def _document_id(payload: dict) -> str:
    document = payload.get("document")
    if isinstance(document, dict) and isinstance(document.get("id"), str):
        return document["id"]
    raise AssertionError(f"上传响应缺少文档 ID：{payload}")


async def _owned_document(client) -> tuple[str, str, str]:
    """建项目 + 上传一份 markdown，返回 (project_id, version_id, document_id)。"""
    project_id = await create_project(client, "任务接口验证项目")
    payload = await upload_document(client, project_id)
    return project_id, version_id_of(payload), _document_id(payload)


def _export_body(project_id: str, version_id: str, **overrides) -> dict:
    overrides.setdefault("objective", "导出当前稿件用于验证任务契约")
    return task_body(
        project_id=project_id,
        document_version_id=version_id,
        kind="export",
        **overrides,
    )


def _sse_frames(text: str) -> list[dict]:
    frames: list[dict] = []
    for block in text.replace("\r\n", "\n").strip().split("\n\n"):
        if not block.strip():
            continue
        frame: dict = {}
        data: str | None = None
        for line in block.splitlines():
            if line.startswith("id: "):
                frame["id"] = int(line[4:].strip())
            elif line.startswith("event: "):
                frame["event"] = line[7:].strip()
            elif line.startswith("data: "):
                data = line[6:]
        assert data is not None, block
        frame["data"] = json.loads(data)
        frames.append(frame)
    return frames


async def _task_rows(client_db, owner_id: int) -> int:
    return (
        await client_db.execute(
            select(func.count())
            .select_from(ResearchTask)
            .where(ResearchTask.owner_id == owner_id)
        )
    ).scalar_one()


# ── 鉴权（AT-006） ────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/research/capabilities"),
        ("GET", "/api/v1/research/projects"),
        ("POST", "/api/v1/research/projects"),
        ("GET", "/api/v1/research/projects/rproj_missing"),
        ("GET", "/api/v1/research/documents/rdoc_missing"),
        ("GET", "/api/v1/research/tasks/rtask_missing"),
        ("POST", "/api/v1/research/tasks"),
        ("GET", "/api/v1/research/tasks/rtask_missing/events"),
        ("GET", "/api/v1/research/tasks/rtask_missing/findings"),
        ("POST", "/api/v1/research/tasks/rtask_missing/cancel"),
        ("POST", "/api/v1/research/tasks/rtask_missing/resume"),
        ("POST", "/api/v1/research/tasks/rtask_missing/retry"),
        ("GET", "/api/v1/research/artifacts/rart_missing"),
        ("GET", "/api/v1/research/artifacts/rart_missing/download"),
        ("POST", "/api/v1/research/exports"),
        ("POST", "/api/v1/research/revision-proposals/rprop_missing/apply"),
    ],
)
async def test_every_endpoint_requires_authentication(anon_client, method, path):
    kwargs = {"json": {}} if method == "POST" else {}
    response = await anon_client.request(method, path, **kwargs)
    # 复用产品既有认证依赖：未携带 Bearer → 401，错误码 AUTHENTICATION_FAILED。
    assert_error(response, 401, "AUTHENTICATION_FAILED")


# ── 伪造身份（AT-006） ───────────────────────────────────


async def test_forged_owner_id_in_task_body_is_rejected(client_a, db, research_store):
    project_id, version_id, _ = await _owned_document(client_a)
    body = _export_body(project_id, version_id)
    body["owner_id"] = research_store.user_ids["b"]
    response = await create_task(client_a, body, idempotency_key="forge-owner-0001")
    assert_error(response, 422, "VALIDATION_ERROR")
    assert await _task_rows(db, research_store.user_ids["a"]) == 0
    assert await _task_rows(db, research_store.user_ids["b"]) == 0


async def test_forged_user_id_in_project_body_is_rejected(
    client_a, db, research_store
):
    response = await client_a.post(
        "/api/v1/research/projects",
        json={"title": "伪造归属", "user_id": research_store.user_ids["b"]},
    )
    assert_error(response, 422, "VALIDATION_ERROR")
    assert await _task_rows(db, research_store.user_ids["b"]) == 0


# ── Idempotency-Key（PRD §8.2） ───────────────────────────


async def test_missing_and_malformed_idempotency_key_are_rejected(client_a, db):
    project_id, version_id, _ = await _owned_document(client_a)
    body = _export_body(project_id, version_id)
    response = await client_a.post("/api/v1/research/tasks", json=body)
    assert_error(response, 422, "INVALID_IDEMPOTENCY_KEY")

    response = await client_a.post(
        "/api/v1/research/tasks",
        json=body,
        headers={"Idempotency-Key": "short"},
    )
    assert_error(response, 422, "INVALID_IDEMPOTENCY_KEY")

    # 注意：httpx 不允许非 ASCII 头值，这里用“ASCII 但含非法字符”的键。
    response = await client_a.post(
        "/api/v1/research/tasks",
        json=body,
        headers={"Idempotency-Key": "invalid!key-0001"},
    )
    assert_error(response, 422, "INVALID_IDEMPOTENCY_KEY")


async def test_same_key_same_request_replays_the_same_task(client_a, db, research_store):
    project_id, version_id, _ = await _owned_document(client_a)
    body = _export_body(project_id, version_id)

    first = await create_task(client_a, body, idempotency_key="replay-same-0001")
    assert first.status_code == 202, first.text
    second = await create_task(client_a, body, idempotency_key="replay-same-0001")
    assert second.status_code == 202, second.text
    assert second.json()["task_id"] == first.json()["task_id"]
    assert second.json()["state_revision"] == first.json()["state_revision"]
    assert await _task_rows(db, research_store.user_ids["a"]) == 1


async def test_same_key_different_request_is_rejected(client_a, db, research_store):
    project_id, version_id, _ = await _owned_document(client_a)
    body = _export_body(project_id, version_id)
    first = await create_task(client_a, body, idempotency_key="replay-diff-0001")
    assert first.status_code == 202, first.text

    other = _export_body(project_id, version_id, objective="另一个完全不同的任务目标")
    response = await create_task(client_a, other, idempotency_key="replay-diff-0001")
    # PRD §8.2：键复用但请求不同 → 409 IDEMPOTENCY_CONFLICT（422 只留给键缺失/非法）。
    error = assert_error(response, 409, "IDEMPOTENCY_CONFLICT")
    assert error["details"]["task_id"] == first.json()["task_id"]
    assert await _task_rows(db, research_store.user_ids["a"]) == 1


# ── 受理 / 快照 / 事件顺序（AT-038） ──────────────────────


async def test_create_task_returns_accepted_snapshot_and_event_cursor(
    client_a, db, research_store
):
    project_id, version_id, _ = await _owned_document(client_a)
    response = await create_task(
        client_a,
        _export_body(project_id, version_id),
        idempotency_key="accepted-0001",
    )
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert {"task_id", "status", "state_revision", "billing_state"} <= set(accepted)
    assert accepted["status"] == "queued"
    assert accepted["state_revision"] == 1
    assert accepted["task_id"].startswith("task_")
    task_id = accepted["task_id"]

    snapshot = await client_a.get(f"/api/v1/research/tasks/{task_id}")
    assert snapshot.status_code == 200, snapshot.text
    data = snapshot.json()
    assert data["id"] == task_id
    assert data["owner_id"] == research_store.user_ids["a"]
    assert data["kind"] == "export"
    assert data["status"] == "queued"
    assert data["state_revision"] == 1
    assert data["billing_state"] == "released"  # export 不消耗额度

    events = await client_a.get(f"/api/v1/research/tasks/{task_id}/events")
    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    frames = _sse_frames(events.text)
    assert [frame["id"] for frame in frames] == [1]
    assert frames[0]["event"] == "task.accepted"
    assert frames[0]["data"]["sequence"] == 1
    assert frames[0]["data"]["task_id"] == task_id
    assert frames[0]["data"]["type"] == "task.accepted"
    assert frames[0]["data"]["payload"]["billing_state"] == "released"


async def test_cancel_is_idempotent_and_emits_single_terminal_event(
    client_a, db, research_store
):
    project_id, version_id, _ = await _owned_document(client_a)
    created = await create_task(
        client_a,
        _export_body(project_id, version_id),
        idempotency_key="cancel-once-0001",
    )
    task_id = created.json()["task_id"]

    first = await client_a.post(f"/api/v1/research/tasks/{task_id}/cancel")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "cancelled"
    assert first.json()["state_revision"] == 2

    second = await client_a.post(f"/api/v1/research/tasks/{task_id}/cancel")
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "cancelled"
    assert second.json()["state_revision"] == 2  # 幂等：不再推进版本

    events = await client_a.get(f"/api/v1/research/tasks/{task_id}/events")
    frames = _sse_frames(events.text)
    assert [frame["id"] for frame in frames] == [1, 2]
    assert [frame["event"] for frame in frames] == ["task.accepted", "task.cancelled"]

    # 终态不可恢复：补充输入必须 409 STATE_CONFLICT。
    resume = await client_a.post(
        f"/api/v1/research/tasks/{task_id}/resume",
        json={"expected_state_revision": 2},
        headers={"Idempotency-Key": "cancel-resume-0001"},
    )
    assert_error(resume, 409, "STATE_CONFLICT")


async def test_resume_requires_current_state_revision_and_resumable_status(
    client_a,
):
    project_id, version_id, _ = await _owned_document(client_a)
    created = await create_task(
        client_a,
        _export_body(project_id, version_id),
        idempotency_key="resume-guard-0001",
    )
    task_id = created.json()["task_id"]

    missing_key = await client_a.post(
        f"/api/v1/research/tasks/{task_id}/resume",
        json={"expected_state_revision": 1},
    )
    assert_error(missing_key, 422, "INVALID_IDEMPOTENCY_KEY")

    stale = await client_a.post(
        f"/api/v1/research/tasks/{task_id}/resume",
        json={"expected_state_revision": 9},
        headers={"Idempotency-Key": "resume-stale-0001"},
    )
    error = assert_error(stale, 409, "STATE_CONFLICT")
    assert error["details"]["state_revision"] == 1

    # 版本号正确但状态是 queued（只有 needs_input/recoverable 可 resume）。
    not_resumable = await client_a.post(
        f"/api/v1/research/tasks/{task_id}/resume",
        json={"expected_state_revision": 1},
        headers={"Idempotency-Key": "resume-status-0001"},
    )
    assert_error(not_resumable, 409, "STATE_CONFLICT")


async def test_retry_requires_expected_revision_and_retryable_status(client_a):
    project_id, version_id, _ = await _owned_document(client_a)
    created = await create_task(
        client_a,
        _export_body(project_id, version_id),
        idempotency_key="retry-guard-0001",
    )
    task_id = created.json()["task_id"]

    stale = await client_a.post(
        f"/api/v1/research/tasks/{task_id}/retry",
        json={"expected_state_revision": 5},
        headers={"Idempotency-Key": "retry-stale-0001"},
    )
    assert_error(stale, 409, "STATE_REVISION_MISMATCH")

    queued = await client_a.post(
        f"/api/v1/research/tasks/{task_id}/retry",
        json={"expected_state_revision": 1},
        headers={"Idempotency-Key": "retry-queued-0001"},
    )
    assert_error(queued, 409, "STATE_CONFLICT")


async def test_event_replay_cursors_and_mismatch(client_a):
    project_id, version_id, _ = await _owned_document(client_a)
    created = await create_task(
        client_a,
        _export_body(project_id, version_id),
        idempotency_key="events-cursor-0001",
    )
    task_id = created.json()["task_id"]
    await client_a.post(f"/api/v1/research/tasks/{task_id}/cancel")

    after = await client_a.get(
        f"/api/v1/research/tasks/{task_id}/events", params={"after_sequence": 1}
    )
    frames = _sse_frames(after.text)
    assert [frame["id"] for frame in frames] == [2]
    assert frames[0]["event"] == "task.cancelled"

    by_header = await client_a.get(
        f"/api/v1/research/tasks/{task_id}/events",
        headers={"Last-Event-ID": "1"},
    )
    assert [frame["id"] for frame in _sse_frames(by_header.text)] == [2]

    mismatch = await client_a.get(
        f"/api/v1/research/tasks/{task_id}/events",
        params={"after_sequence": 1},
        headers={"Last-Event-ID": "2"},
    )
    assert_error(mismatch, 422, "EVENT_SEQUENCE_MISMATCH")

    empty = await client_a.get(
        f"/api/v1/research/tasks/{task_id}/events", params={"after_sequence": 99}
    )
    assert empty.status_code == 200
    assert _sse_frames(empty.text) == []


async def test_open_stream_ends_for_queued_task_without_hanging(client_a):
    project_id, version_id, _ = await _owned_document(client_a)
    created = await create_task(
        client_a,
        _export_body(project_id, version_id),
        idempotency_key="events-open-0001",
    )
    task_id = created.json()["task_id"]
    # research_app 夹具已把 SSE 等待上限压到 1s，排队任务的事件流不会挂 60s。

    response = await client_a.get(
        f"/api/v1/research/tasks/{task_id}/events", timeout=10
    )
    assert response.status_code == 200
    assert [frame["id"] for frame in _sse_frames(response.text)] == [1]


# ── 归属隔离（AT-007） ───────────────────────────────────


async def test_cross_user_reads_return_unified_404(
    client_a, client_b, db, research_store
):
    project_id, version_id, _ = await _owned_document(client_a)
    created = await create_task(
        client_a,
        _export_body(project_id, version_id),
        idempotency_key="cross-user-0001",
    )
    task_id = created.json()["task_id"]
    document_id = (await client_a.get(
        f"/api/v1/research/projects/{project_id}"
    )).json()["documents"][0]["id"]

    artifact = Artifact(
        id="rart_crossuser_test",
        owner_id=research_store.user_ids["a"],
        task_id=task_id,
        kind="export",
        version=1,
        content_hash="0" * 64,
        mime="text/markdown",
        filename="export.md",
        body="# 导出\n",
        size_bytes=6,
        validation_json={},
    )
    db.add(artifact)
    await db.commit()

    for path in (
        f"/api/v1/research/projects/{project_id}",
        f"/api/v1/research/documents/{document_id}",
        f"/api/v1/research/documents/{document_id}/blocks",
        f"/api/v1/research/tasks/{task_id}",
        f"/api/v1/research/tasks/{task_id}/findings",
        "/api/v1/research/artifacts/rart_crossuser_test",
        "/api/v1/research/artifacts/rart_crossuser_test/download",
    ):
        response = await client_b.get(path)
        assert_error(response, 404, "NOT_FOUND")

    for path in (
        f"/api/v1/research/tasks/{task_id}/cancel",
        f"/api/v1/research/tasks/{task_id}/resume",
        f"/api/v1/research/tasks/{task_id}/retry",
    ):
        kwargs = {"json": {"expected_state_revision": 1}} if not path.endswith(
            "/cancel"
        ) else {}
        headers = {"Idempotency-Key": "cross-write-0001"}
        response = await client_b.post(path, headers=headers, **kwargs)
        assert_error(response, 404, "NOT_FOUND")

    events = await client_b.get(f"/api/v1/research/tasks/{task_id}/events")
    assert_error(events, 404, "NOT_FOUND")

    # A 自己的读取必须成功，证明 404 不是“功能没实现”。
    assert (
        await client_a.get(f"/api/v1/research/tasks/{task_id}")
    ).status_code == 200
    assert (
        await client_a.get("/api/v1/research/artifacts/rart_crossuser_test")
    ).status_code == 200
    download = await client_a.get(
        "/api/v1/research/artifacts/rart_crossuser_test/download"
    )
    assert download.status_code == 200
    assert download.content == "# 导出\n".encode()


async def test_lists_do_not_leak_other_users_content(client_a, client_b):
    project_id, _, _ = await _owned_document(client_a)
    listed = await client_b.get("/api/v1/research/projects")
    assert listed.status_code == 200
    assert listed.json()["items"] == []
    own = await create_project(client_b, "B 自己的项目")
    listed = await client_b.get("/api/v1/research/projects")
    ids = [item["id"] for item in listed.json()["items"]]
    assert ids == [own]
    assert project_id not in ids


async def test_findings_are_owner_scoped(client_a, client_b, db, research_store):
    project_id, version_id, _ = await _owned_document(client_a)
    created = await create_task(
        client_a,
        _export_body(project_id, version_id),
        idempotency_key="findings-owner-0001",
    )
    task_id = created.json()["task_id"]
    db.add(
        FindingRow(
            id="rfnd_owner_scope_1",
            task_id=task_id,
            owner_id=research_store.user_ids["a"],
            version_id=version_id,
            scope="document",
            category="argument",
            severity="major",
            problem="论证链中段缺少反例讨论。",
            reason="缺少对相反证据的回应。",
            recommendation="补充反例段落。",
            evidence_refs=[],
            checked_sections=["引言", "讨论"],
            required_user_action="作者补充",
            verification_method="model",
        )
    )
    await db.commit()

    mine = await client_a.get(f"/api/v1/research/tasks/{task_id}/findings")
    assert mine.status_code == 200
    assert [item["id"] for item in mine.json()["items"]] == ["rfnd_owner_scope_1"]
    theirs = await client_b.get(f"/api/v1/research/tasks/{task_id}/findings")
    assert_error(theirs, 404, "NOT_FOUND")


# ── Skill 契约（AT-004） ─────────────────────────────────


async def _task_with_skills(client, project_id, version_id, skill_ids, key):
    body = _export_body(project_id, version_id)
    if skill_ids is not None:
        # 只有“显式提供”才写进 JSON；None = 字段缺席，不能序列化成 null。
        body["skill_ids"] = skill_ids
    return await create_task(client, body, idempotency_key=key)


async def test_absent_skill_ids_means_no_skill_selected(
    client_a, db, research_store
):
    project_id, version_id, _ = await _owned_document(client_a)
    response = await _task_with_skills(
        client_a, project_id, version_id, None, "skills-absent-0001"
    )
    if response.status_code == 422:
        pytest.fail(f"skill_ids=None 不应被拒绝：{response.text}")
    assert response.status_code == 202, response.text
    task = await client_a.get(
        f"/api/v1/research/tasks/{response.json()['task_id']}"
    )
    assert task.json()["snapshot_summary"]["skill_ids"] == []


async def test_explicit_empty_skill_ids_loads_nothing(client_a):
    project_id, version_id, _ = await _owned_document(client_a)
    response = await _task_with_skills(
        client_a, project_id, version_id, [], "skills-empty-0001"
    )
    assert response.status_code == 202, response.text
    task = await client_a.get(
        f"/api/v1/research/tasks/{response.json()['task_id']}"
    )
    summary = task.json()["snapshot_summary"]
    assert summary["skill_ids"] == []


async def test_enabled_skill_is_recorded_in_snapshot(client_a):
    project_id, version_id, _ = await _owned_document(client_a)
    response = await _task_with_skills(
        client_a,
        project_id,
        version_id,
        ["academic-researcher"],
        "skills-enabled-0001",
    )
    assert response.status_code == 202, response.text
    task = await client_a.get(
        f"/api/v1/research/tasks/{response.json()['task_id']}"
    )
    assert task.json()["snapshot_summary"]["skill_ids"] == ["academic-researcher"]
    events = await client_a.get(
        f"/api/v1/research/tasks/{response.json()['task_id']}/events"
    )
    frame = _sse_frames(events.text)[0]
    assert frame["data"]["payload"]["skill_ids"] == ["academic-researcher"]


async def test_unknown_or_disabled_skill_rejected_before_billing(
    client_a, db, research_store
):
    project_id, version_id, _ = await _owned_document(client_a)
    for index, skill_id in enumerate(("does-not-exist", "nature-polishing")):
        response = await _task_with_skills(
            client_a,
            project_id,
            version_id,
            [skill_id],
            f"skills-invalid-{index:04d}",
        )
        assert_error(response, 422, "SKILL_UNAVAILABLE")
    assert await _task_rows(db, research_store.user_ids["a"]) == 0
    ledger = (
        await db.execute(select(func.count()).select_from(TaskEvent))
    ).scalar_one()
    assert ledger == 0


async def test_too_many_or_duplicate_skills_are_rejected(client_a):
    project_id, version_id, _ = await _owned_document(client_a)
    too_many = await _task_with_skills(
        client_a,
        project_id,
        version_id,
        ["academic-researcher"] * 9,
        "skills-toomany-0001",
    )
    assert_error(too_many, 422, "VALIDATION_ERROR")
    duplicate = await _task_with_skills(
        client_a,
        project_id,
        version_id,
        ["academic-researcher", "academic-researcher"],
        "skills-dup-0001",
    )
    assert duplicate.status_code == 422, duplicate.text
