"""AT-054：删除即撤权、迟到执行器与事件重放不得泄露已删内容。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from ...research import retrieval_service, task_repository, task_runner
from ...research.contracts import TaskStatus
from ...research.errors import ResearchAPIError
from ...research.models import DocumentChunk, DocumentVersion, ResearchTask
from ..test_research.conftest import assert_error
from .conftest import (
    create_project,
    create_task,
    patch_switch,
    task_body,
    upload_document,
    version_id_of,
)


@pytest_asyncio.fixture
async def entitled_user(research_env, db):
    """开通会员：review 任务映射 external_review 权益（走真实发放，不改 plan 字段）。"""
    from ...services.entitlement_service import EntitlementService

    user_id = research_env.user_ids["a"]
    await EntitlementService.grant_product(db, user_id, "monthly_pro", "r2-revocation-grant")
    await db.commit()
    return user_id


async def _project_with_document(client, *, filename: str = "revoke.md") -> tuple[str, str, str]:
    project_id = await create_project(client, "撤权验证项目")
    text = (
        "# 引言\n\n"
        + "本文讨论平台算法与新闻消费的关系，关注推荐系统如何改变用户的信息接触结构。" * 12
        + "\n\n# 方法\n\n"
        + "研究采用问卷与日志结合的混合设计，样本 1200 人，辅以 24 次深度访谈。" * 12
        + "\n"
    )
    uploaded = await upload_document(client, project_id, filename=filename, text=text)
    document = uploaded.get("document") or uploaded
    return project_id, document["id"], version_id_of(uploaded)


@pytest.mark.asyncio
async def test_delete_document_closes_every_read_path(client_a) -> None:
    project_id, document_id, version_id = await _project_with_document(client_a)

    assert (await client_a.get(f"/api/v1/research/documents/{document_id}")).status_code == 200
    assert (await client_a.get(f"/api/v1/research/documents/{document_id}/blocks")).status_code == 200

    deleted = await client_a.delete(f"/api/v1/research/documents/{document_id}")
    assert deleted.status_code in (200, 204), deleted.text

    for path in (
        f"/api/v1/research/documents/{document_id}",
        f"/api/v1/research/documents/{document_id}/blocks",
    ):
        payload = assert_error(await client_a.get(path), 404)
        assert "filename" not in (payload.get("details") or {})

    # 已删版本不能再作为任务输入（归属/存在性校验在扣额之前）
    task = await create_task(
        client_a,
        task_body(project_id=project_id, document_version_id=version_id),
        idempotency_key="revoke-task-after-delete",
    )
    assert_error(task, 404, "NOT_FOUND")


@pytest.mark.asyncio
async def test_delete_document_cascades_versions_and_chunks(client_a, db, research_env) -> None:
    _project_id, document_id, version_id = await _project_with_document(client_a, filename="cleanup.md")

    # 分块是懒建的：先跑一次检索索引，才有 DocumentChunk 可级联
    await retrieval_service.iter_chunks(db, research_env.actor("a"), version_id)
    await db.commit()

    assert await db.scalar(select(DocumentVersion).where(DocumentVersion.id == version_id)) is not None
    assert await db.scalar(select(DocumentChunk).where(DocumentChunk.version_id == version_id)) is not None

    deleted = await client_a.delete(f"/api/v1/research/documents/{document_id}")
    assert deleted.status_code in (200, 204), deleted.text

    assert await db.scalar(select(DocumentVersion).where(DocumentVersion.id == version_id)) is None
    assert await db.scalar(select(DocumentChunk).where(DocumentChunk.version_id == version_id)) is None


@pytest.mark.asyncio
async def test_other_user_cannot_probe_document(client_a, client_b) -> None:
    _project_id, document_id, _version_id = await _project_with_document(client_a, filename="private.md")

    assert_error(await client_b.get(f"/api/v1/research/documents/{document_id}"), 404, "NOT_FOUND")
    assert (await client_a.delete(f"/api/v1/research/documents/{document_id}")).status_code in (200, 204)
    assert_error(await client_b.get(f"/api/v1/research/documents/{document_id}"), 404, "NOT_FOUND")


@pytest.mark.asyncio
async def test_lease_blocks_second_executor(client_a, db, entitled_user) -> None:
    project_id, _document_id, version_id = await _project_with_document(client_a, filename="lease.md")
    task_id = await _entitled_review(client_a, project_id, version_id, key="lease-task")

    task = await db.get(ResearchTask, task_id)
    assert task is not None
    first = await task_repository.open_attempt(db, task, lease_holder="worker-a")
    await db.commit()
    assert first.lease_holder == "worker-a"

    with pytest.raises(ResearchAPIError) as excinfo:
        await task_repository.open_attempt(db, task, lease_holder="worker-b")
    assert excinfo.value.code == "LEASE_HELD"
    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_terminal_task_cannot_be_reclaimed(client_a, db, entitled_user, monkeypatch) -> None:
    patch_switch(monkeypatch, "RESEARCH_MODEL_STUB", True)
    project_id, _document_id, version_id = await _project_with_document(client_a, filename="late.md")
    task_id = await _entitled_review(client_a, project_id, version_id, key="late-task")

    task = await db.get(ResearchTask, task_id)
    assert task is not None
    await task_runner.execute_task(db, task, holder="worker-a")
    await db.commit()

    refreshed = await db.get(ResearchTask, task_id)
    assert refreshed is not None
    assert TaskStatus(refreshed.status) in {
        TaskStatus.SUCCEEDED,
        TaskStatus.PARTIAL,
        TaskStatus.NEEDS_INPUT,
        TaskStatus.FAILED,
    }

    with pytest.raises(ResearchAPIError) as excinfo:
        await task_repository.open_attempt(db, refreshed, lease_holder="worker-b")
    assert excinfo.value.code == "TASK_NOT_CLAIMABLE"

    # 迟到执行器不得再写事件
    before = [event.sequence for event in await task_repository.list_events(db, task_id, after_sequence=0)]
    await task_runner.execute_task(db, refreshed, holder="worker-b")
    await db.commit()
    after = [event.sequence for event in await task_repository.list_events(db, task_id, after_sequence=0)]
    assert after == before


async def _entitled_review(client, project_id: str, version_id: str, *, key: str) -> str:
    response = await create_task(
        client,
        task_body(project_id=project_id, document_version_id=version_id),
        idempotency_key=key,
    )
    assert response.status_code in (200, 201, 202), response.text
    payload = response.json()
    return payload.get("task_id") or payload.get("id")
