"""归属校验（AT-006/AT-007/AT-010）：统一 404，绝不因“存在但属于别人”泄露信息。

本文件直接构造 ORM 行，不经过任何写接口，验证的是**归一层**本身：
- ``require_*`` 对“不存在”与“属于别人”给出同一个 404 NOT_FOUND；
- ``owned`` 只以 actor.user_id 判定；
- 版本归属以所属文档的 owner 为准（防止拿别人的 version_id 穿透）。
"""
from __future__ import annotations

import pytest

from ...research import ownership
from ...research.contracts import Actor, utcnow
from ...research.errors import ResearchAPIError
from ...research.models import (
    Artifact,
    Document,
    DocumentVersion,
    Project,
    ResearchTask,
    RevisionProposalRow,
)



def _actor(research_store, who: str = "a") -> Actor:
    return Actor(research_store.user_ids[who])


async def _project_row(db, owner_id: int, *, title: str = "归属项目") -> Project:
    row = Project(
        id=f"rproj_{owner_id}_p",
        owner_id=owner_id,
        title=title,
        status="active",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(row)
    await db.flush()
    return row


async def _document_row(db, owner_id: int, project_id: str) -> Document:
    row = Document(
        id=f"rdoc_{owner_id}_d",
        project_id=project_id,
        owner_id=owner_id,
        filename="paper.md",
        mime="text/markdown",
        size_bytes=10,
        content_hash="0" * 64,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(row)
    await db.flush()
    return row


async def _version_row(db, document: Document) -> DocumentVersion:
    row = DocumentVersion(
        id=f"rver_{document.id}",
        document_id=document.id,
        version_no=1,
        content_hash="1" * 64,
        text="正文内容。",
        codepoints=5,
        parse_status="complete",
        page_count=1,
        source="upload",
        created_at=utcnow(),
    )
    db.add(row)
    await db.flush()
    return row


async def _task_row(db, owner_id: int, project_id: str) -> ResearchTask:
    row = ResearchTask(
        id=f"rtask_{owner_id}_t",
        owner_id=owner_id,
        project_id=project_id,
        kind="review",
        status="queued",
        objective="检查全文",
        input_json={"document_version_id": "x"},
        scope_json={},
        constraints_json={},
        state_revision=1,
        billing_group_id=f"bg_{owner_id}",
        billing_state="reserved",
        attempt_no=0,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(row)
    await db.flush()
    return row


async def _artifact_row(db, owner_id: int, task_id: str) -> Artifact:
    row = Artifact(
        id=f"rart_{owner_id}_a",
        owner_id=owner_id,
        task_id=task_id,
        kind="review_report",
        version=1,
        content_hash="2" * 64,
        mime="text/markdown",
        filename="review.md",
        body="报告正文。",
        size_bytes=15,
        validation_json={},
        created_at=utcnow(),
    )
    db.add(row)
    await db.flush()
    return row


async def _proposal_row(db, owner_id: int, task_id: str, version_id: str) -> RevisionProposalRow:
    row = RevisionProposalRow(
        id=f"rprop_{owner_id}_p",
        task_id=task_id,
        owner_id=owner_id,
        base_version_id=version_id,
        selected_findings=["f1"],
        hunks_json=[],
        validation_report={},
        status="proposed",
        created_at=utcnow(),
    )
    db.add(row)
    await db.flush()
    return row


def test_owned_is_pure_identity_check():
    actor = Actor(7)
    assert ownership.owned(7, actor) is True
    assert ownership.owned(8, actor) is False
    assert ownership.owned(None, actor) is False


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_require_project_returns_own_row(db, research_store):
    actor = _actor(research_store)
    project = await _project_row(db, actor.user_id)
    assert (await ownership.require_project(db, actor, project.id)).id == project.id


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_require_project_hides_other_owner_as_404(db, research_store):
    actor_a, actor_b = _actor(research_store, "a"), _actor(research_store, "b")
    project = await _project_row(db, actor_a.user_id)
    for actor in (actor_b,):
        with pytest.raises(ResearchAPIError) as excinfo:
            await ownership.require_project(db, actor, project.id)
        assert excinfo.value.code == "NOT_FOUND"
        assert excinfo.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_require_missing_project_is_same_404(db, research_store):
    actor = _actor(research_store)
    with pytest.raises(ResearchAPIError) as excinfo:
        await ownership.require_project(db, actor, "rproj_does_not_exist")
    assert excinfo.value.status_code == 404
    assert excinfo.value.code == "NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_require_document_hides_other_owner(db, research_store):
    actor_a, actor_b = _actor(research_store, "a"), _actor(research_store, "b")
    project = await _project_row(db, actor_a.user_id)
    document = await _document_row(db, actor_a.user_id, project.id)
    assert (await ownership.require_document(db, actor_a, document.id)).id == document.id
    with pytest.raises(ResearchAPIError) as excinfo:
        await ownership.require_document(db, actor_b, document.id)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_require_version_uses_document_owner(db, research_store):
    """B 拿到 A 的 version_id 也不能穿透（版本没有 owner 列）。"""

    actor_a, actor_b = _actor(research_store, "a"), _actor(research_store, "b")
    project = await _project_row(db, actor_a.user_id)
    document = await _document_row(db, actor_a.user_id, project.id)
    version = await _version_row(db, document)
    assert (await ownership.require_version(db, actor_a, version.id)).id == version.id
    with pytest.raises(ResearchAPIError) as excinfo:
        await ownership.require_version(db, actor_b, version.id)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_require_task_hides_other_owner(db, research_store):
    actor_a, actor_b = _actor(research_store, "a"), _actor(research_store, "b")
    project = await _project_row(db, actor_a.user_id)
    task = await _task_row(db, actor_a.user_id, project.id)
    assert (await ownership.require_task(db, actor_a, task.id)).id == task.id
    with pytest.raises(ResearchAPIError) as excinfo:
        await ownership.require_task(db, actor_b, task.id)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_require_artifact_hides_other_owner(db, research_store):
    actor_a, actor_b = _actor(research_store, "a"), _actor(research_store, "b")
    project = await _project_row(db, actor_a.user_id)
    task = await _task_row(db, actor_a.user_id, project.id)
    artifact = await _artifact_row(db, actor_a.user_id, task.id)
    assert (await ownership.require_artifact(db, actor_a, artifact.id)).id == artifact.id
    with pytest.raises(ResearchAPIError) as excinfo:
        await ownership.require_artifact(db, actor_b, artifact.id)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_require_proposal_hides_other_owner(db, research_store):
    actor_a, actor_b = _actor(research_store, "a"), _actor(research_store, "b")
    project = await _project_row(db, actor_a.user_id)
    document = await _document_row(db, actor_a.user_id, project.id)
    version = await _version_row(db, document)
    task = await _task_row(db, actor_a.user_id, project.id)
    proposal = await _proposal_row(db, actor_a.user_id, task.id, version.id)
    assert (
        await ownership.require_proposal(db, actor_a, proposal.id)
    ).id == proposal.id
    with pytest.raises(ResearchAPIError) as excinfo:
        await ownership.require_proposal(db, actor_b, proposal.id)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_all_require_helpers_hide_existence_uniformly(db, research_store):
    """不存在与无权限必须无法区分：同一个 404 + NOT_FOUND。"""

    actor_b = _actor(research_store, "b")
    actor_a = _actor(research_store, "a")
    project = await _project_row(db, actor_a.user_id)
    document = await _document_row(db, actor_a.user_id, project.id)
    version = await _version_row(db, document)
    task = await _task_row(db, actor_a.user_id, project.id)
    artifact = await _artifact_row(db, actor_a.user_id, task.id)
    proposal = await _proposal_row(db, actor_a.user_id, task.id, version.id)

    cases = [
        (ownership.require_project, project.id),
        (ownership.require_document, document.id),
        (ownership.require_version, version.id),
        (ownership.require_task, task.id),
        (ownership.require_artifact, artifact.id),
        (ownership.require_proposal, proposal.id),
    ]
    for helper, existing_id in cases:
        errors = []
        for target_id in (existing_id, f"{existing_id}_missing"):
            with pytest.raises(ResearchAPIError) as excinfo:
                await helper(db, actor_b, target_id)
            errors.append((excinfo.value.status_code, excinfo.value.code))
        assert errors[0] == errors[1] == (404, "NOT_FOUND"), (helper.__name__, errors)
