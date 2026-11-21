"""诚实性 / 交付底线（R0：AT-022、AT-034、AT-039、AT-042）。

核心断言：**没有真实成果就不能算成功**。
- 导出任务跑通 → succeeded + 非空 export 成果 + 终态事件带 artifact_ids；
- 正文为空 → failed / 部分失败，绝不 succeeded，额度释放；
- 模型不可用 / 输出不是合法 JSON → recoverable 或 failed，不允许“假成功”；
- 已终态任务重入执行 → 无副作用（不重复事件、不重复结算）；
- 排队中的快照不得携带成果/质量结论。
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from ...models.orm import UserQuota
from ...research import artifact_service, export_service
from ...research import document_service, project_service
from ...research.contracts import utcnow
from ...research.errors import ResearchAPIError
from ...research.models import (
    Artifact,
    DocumentVersion,
    ResearchTask,
    TaskEvent,
)
from ...research.task_runner import execute_task
from ...research.task_service import create_task, get_task_snapshot
from ...services.entitlement_service import EntitlementService

DOC_TEXT = (
    "# 论文标题\n\n"
    "第一段：样本量为 120 人，2023 年收集数据，结论仍需谨慎。\n\n"
    "第二段：研究结果并不显著，作者应补充反例讨论。\n"
)


class _UnavailableClient:
    """模拟无模型凭证：调用即 503，绝不允许被当成“没问题”。"""

    async def complete(self, system, user, json_schema=None):
        from ...research.errors import unavailable

        raise unavailable("MODEL_UNAVAILABLE", "模型不可用（测试替身）")


class _GarbageClient:
    """模拟模型输出不是合法 JSON（空泛回答 / 截断）。"""

    async def complete(self, system, user, json_schema=None):
        return "抱歉，我无法完成该请求。"


class _Env(dict):
    pass


async def _grant_review_entitlement(db, user_id: int) -> None:
    await EntitlementService.ensure_quota(db, user_id)
    quota = (
        await db.execute(select(UserQuota).where(UserQuota.user_id == user_id))
    ).scalar_one()
    quota.external_review_expires_at = utcnow().replace(year=utcnow().year + 2)
    quota.membership_expires_at = utcnow().replace(year=utcnow().year + 2)
    await db.commit()


@pytest_asyncio.fixture
async def honesty_env(db, research_store):
    """真实走 project/document 服务上传一篇正文（含块，可被 review 消费）。"""
    actor = research_store.actor("a")
    project = await project_service.create_project(db, actor, "诚实性验证项目")
    await db.commit()
    payload = await document_service.upload_document(
        db,
        actor,
        project["id"] if isinstance(project, dict) else project,
        filename="honesty.md",
        mime="text/markdown",
        data=DOC_TEXT.encode("utf-8"),
    )
    await db.commit()
    document = payload["document"]
    version = payload["version"]
    return _Env(
        actor=actor,
        owner=research_store.user_ids["a"],
        project_id=document["project_id"] if isinstance(document, dict) else project,
        document_id=document["id"],
        version_id=version["id"],
    )


def _task_body(env: _Env, kind: str, **overrides):
    body = {
        "schema_version": "1.0",
        "project_id": env["project_id"],
        "kind": kind,
        "objective": "验证任务执行结果是否诚实",
        "input": {"document_version_id": env["version_id"]},
    }
    body.update(overrides)
    return body


async def _create(db, env: _Env, kind: str, key: str, **overrides) -> ResearchTask:
    accepted = await create_task(
        db, env["actor"], _task_body(env, kind, **overrides), idempotency_key=key
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


# ── 导出：有成果才算成功 ─────────────────────────────────


@pytest.mark.asyncio
async def test_export_task_succeeds_only_with_non_empty_artifact(db, honesty_env):
    task = await _create(db, honesty_env, "export", "honesty-export-0001")
    await execute_task(db, task, holder="verifier")
    await db.refresh(task)

    assert task.status == "succeeded"
    artifacts = await _artifacts(db, task.id)
    assert artifacts, "succeeded 必须留下可下载成果"
    assert artifacts[0].kind == "export"
    assert artifacts[0].body.strip()
    assert artifacts[0].size_bytes > 0

    assert task.result_json["artifact_ids"] == [artifacts[0].id]
    events = await _events(db, task.id)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    terminal = events[-1]
    assert terminal.type == "task.completed"
    assert terminal.payload_json["artifact_ids"] == [artifacts[0].id]
    assert task.ended_at is not None
    assert task.quality_verdict is None  # 导出不应该编造质量结论


@pytest.mark.asyncio
async def test_export_with_empty_body_fails_and_releases_quota(db, honesty_env):
    empty_version = DocumentVersion(
        id="rver_honesty_empty",
        document_id=honesty_env["document_id"],
        version_no=99,
        content_hash="0" * 64,
        text="   \n\n  ",
        codepoints=0,
        parse_status="complete",
        page_count=1,
        source="upload",
        created_at=utcnow(),
    )
    db.add(empty_version)
    await db.commit()

    body = _task_body(honesty_env, "export")
    body["input"] = {"document_version_id": empty_version.id}
    accepted = await create_task(
        db, honesty_env["actor"], body, idempotency_key="honesty-export-empty"
    )
    task = (
        await db.execute(select(ResearchTask).where(ResearchTask.id == accepted.task_id))
    ).scalar_one()

    await execute_task(db, task, holder="verifier")
    await db.refresh(task)

    assert task.status in {"failed", "partial"}
    assert task.status != "succeeded"
    assert await _artifacts(db, task.id) == []
    assert task.error_json and task.error_json["code"] in {
        "EMPTY_EXPORT_CONTENT",
        "INCOMPLETE_DELIVERABLE",
    }
    assert task.billing_state == "released"


# ── 模型失败：不允许假成功 ───────────────────────────────


@pytest.mark.asyncio
async def test_review_with_unavailable_model_is_recoverable_not_success(
    db, research_store, honesty_env
):
    await _grant_review_entitlement(db, honesty_env["owner"])
    task = await _create(db, honesty_env, "review", "honesty-review-nomodel")
    await execute_task(db, task, holder="verifier", client=_UnavailableClient())
    await db.refresh(task)

    assert task.status == "recoverable"
    assert task.status != "succeeded"
    assert await _artifacts(db, task.id) == []
    assert task.quality_verdict is None
    assert task.billing_state == "reserved"  # 等待恢复/超时后再释放
    types = [event.type for event in await _events(db, task.id)]
    assert "task.recoverable" in types
    assert "task.completed" not in types


@pytest.mark.asyncio
async def test_review_with_garbage_model_output_does_not_succeed(db, honesty_env):
    await _grant_review_entitlement(db, honesty_env["owner"])
    task = await _create(db, honesty_env, "review", "honesty-review-garbage")
    await execute_task(db, task, holder="verifier", client=_GarbageClient())
    await db.refresh(task)

    # 部分诊断可以成为 partial（有成果但不完整），但绝不 succeeded 且必须带原因。
    assert task.status in {"failed", "recoverable", "partial"}
    assert task.status != "succeeded"
    artifacts = await _artifacts(db, task.id)
    if task.status == "partial":
        # partial 允许保留已有成果，但成果本身必须非空，且不得冒充质量结论。
        assert artifacts and all(item.body.strip() for item in artifacts)
    else:
        assert artifacts == []
    assert task.quality_verdict is None
    assert task.error_json, "失败必须带明确原因"


# ── 终态重入与快照诚实性 ─────────────────────────────────


@pytest.mark.asyncio
async def test_terminal_task_is_not_executed_twice(db, honesty_env):
    task = await _create(db, honesty_env, "export", "honesty-export-once")
    await execute_task(db, task, holder="verifier")
    await db.refresh(task)
    assert task.status == "succeeded"
    event_count = len(await _events(db, task.id))

    await execute_task(db, task, holder="verifier-again")
    await db.refresh(task)
    assert task.status == "succeeded"
    assert len(await _events(db, task.id)) == event_count
    assert len(await _artifacts(db, task.id)) == 1


@pytest.mark.asyncio
async def test_queued_snapshot_has_no_fake_deliverable(db, honesty_env):
    task = await _create(db, honesty_env, "export", "honesty-snapshot-0001")
    snapshot = await get_task_snapshot(db, honesty_env["actor"], task.id)

    assert snapshot.status == "queued"
    assert snapshot.artifact_ids == []
    assert snapshot.quality_verdict is None
    assert snapshot.can_resume is False


# ── 成果与导出的底线校验 ─────────────────────────────────


@pytest.mark.asyncio
async def test_create_artifact_rejects_empty_body_and_unknown_kind(db, honesty_env):
    with pytest.raises(ResearchAPIError) as empty:
        await artifact_service.create_artifact(
            db,
            owner_id=honesty_env["owner"],
            task_id="task_honesty",
            kind="export",
            body="   ",
            mime="text/markdown",
            filename="empty.md",
        )
    assert (empty.value.status_code, empty.value.code) == (422, "EMPTY_ARTIFACT")

    with pytest.raises(ResearchAPIError) as unknown:
        await artifact_service.create_artifact(
            db,
            owner_id=honesty_env["owner"],
            task_id="task_honesty",
            kind="whatever",
            body="正文",
            mime="text/markdown",
            filename="x.md",
        )
    assert (unknown.value.status_code, unknown.value.code) == (
        422,
        "INVALID_ARTIFACT_KIND",
    )


@pytest.mark.asyncio
async def test_export_rejects_unknown_style_and_format(db, honesty_env):
    with pytest.raises(ResearchAPIError) as style:
        await export_service.export(
            db,
            honesty_env["actor"],
            project_id=honesty_env["project_id"],
            document_version_id=honesty_env["version_id"],
            fmt="md",
            journal_style="nature",
        )
    assert (style.value.status_code, style.value.code) == (
        422,
        "UNSUPPORTED_JOURNAL_STYLE",
    )

    with pytest.raises(ResearchAPIError) as fmt:
        await export_service.export(
            db,
            honesty_env["actor"],
            project_id=honesty_env["project_id"],
            document_version_id=honesty_env["version_id"],
            fmt="pdf",
            journal_style="generic",
        )
    assert (fmt.value.status_code, fmt.value.code) == (
        422,
        "UNSUPPORTED_EXPORT_FORMAT",
    )


@pytest.mark.asyncio
async def test_export_is_owner_scoped(db, research_store, honesty_env):
    other = research_store.actor("b")
    with pytest.raises(ResearchAPIError) as excinfo:
        await export_service.export(
            db,
            other,
            project_id=honesty_env["project_id"],
            document_version_id=honesty_env["version_id"],
            fmt="md",
            journal_style="generic",
        )
    assert excinfo.value.status_code == 404
    assert excinfo.value.code == "NOT_FOUND"
