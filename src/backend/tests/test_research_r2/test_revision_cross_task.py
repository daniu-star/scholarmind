"""跨任务采纳诊断项（R2 / AT-051 修订链路）。

R1 的修改任务测试把诊断项直接挂在修改任务名下，掩盖了一个真实缺口：
界面上「审阅诊断 → 选目标 → 采纳」要求修改任务引用**另一个** review 任务产出的
诊断项。这里锁定：同版本同主人的诊断项可以被修改任务引用并产出可校验补丁；
他人诊断项在受理阶段（扣额之前）就会被 422 拒绝，且不泄露存在性。
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from ...research import revision_service, task_service
from ...research.contracts import PRESERVE_DEFAULTS, new_id, normalize_text
from ...research.models import (
    DocumentVersion,
    FindingRow,
    ResearchTask,
    RevisionProposalRow,
)
from ...research.task_runner import execute_task
from ...services.entitlement_service import EntitlementService
from .conftest import patch_switch
from ..test_research.conftest import (
    create_project,
    task_body,
    upload_document,
    version_id_of,
)

BODY = (
    "# 平台化生存\n\n"
    "算法推荐把用户的注意力切成碎片，平台因此获得了可观的收益。\n\n"
    "现有研究大多停在描述层面。\n"
)


async def _make_version(db, actor, client, *, need_finding: bool):
    """建项目 + 上传正文 + 跑一次 review（替身模型），返回 (project_id, version_id, task)。"""
    project_id = await create_project(client, "跨任务采纳")
    document = await upload_document(client, project_id, text=BODY)
    version_id = version_id_of(document)
    accepted = await task_service.create_task(
        db,
        actor,
        task_body(project_id=project_id, document_version_id=version_id),
        idempotency_key=f"r2-cross-{new_id('key')}",
    )
    task = (
        await db.execute(select(ResearchTask).where(ResearchTask.id == accepted.task_id))
    ).scalar_one()
    await execute_task(db, task, holder=f"verifier:{new_id('h')}")
    await db.refresh(task)
    return project_id, version_id, task


@pytest_asyncio.fixture
async def review_setup(client_a, research_env, db, monkeypatch):
    patch_switch(monkeypatch, "RESEARCH_MODEL_STUB", True)
    user_id = research_env.user_ids["a"]
    await EntitlementService.grant_product(db, user_id, "monthly_pro", "r2-cross-grant-a")
    await db.commit()
    project_id, version_id, task = await _make_version(
        db, research_env.actor("a"), client_a, need_finding=True
    )
    return {"project_id": project_id, "version_id": version_id, "task": task}


def _insert_finding(db, *, owner_id: int, task_id: str, version_id: str) -> FindingRow:
    text = normalize_text(BODY)
    start = text.index("算法推荐")
    end = start + len("算法推荐把用户的注意力切成碎片，平台因此获得了可观的收益。")
    row = FindingRow(
        id=f"find_{new_id('')[:24]}",
        task_id=task_id,
        owner_id=owner_id,
        version_id=version_id,
        scope="local",
        category="argument",
        severity="major",
        problem="论点缺少与既有研究的对话。",
        reason="第二段只给结论，没有比较已有解释。",
        recommendation="补充与既有研究的对照并说明本文增量。",
        evidence_refs=[],
        locator={"start": start, "end": end, "version_id": version_id},
        quote=text[start:end],
        verification_method="model",
    )
    db.add(row)
    return row


@pytest.mark.asyncio
async def test_revision_task_can_reference_findings_from_review_task(
    db, research_env, review_setup
):
    actor = research_env.actor("a")
    finding = _insert_finding(
        db,
        owner_id=actor.user_id,
        task_id=review_setup["task"].id,
        version_id=review_setup["version_id"],
    )
    await db.commit()

    accepted = await task_service.create_task(
        db,
        actor,
        {
            "schema_version": "1.0",
            "project_id": review_setup["project_id"],
            "kind": "revision",
            "objective": "按选中诊断项给出可直接采纳的补丁",
            "input": {"document_version_id": review_setup["version_id"]},
            "scope": {"finding_ids": [finding.id]},
        },
        idempotency_key="r2-cross-revision-0001",
    )
    await db.commit()
    revision_task = (
        await db.execute(select(ResearchTask).where(ResearchTask.id == accepted.task_id))
    ).scalar_one()
    await execute_task(db, revision_task, holder="verifier:cross-revision")
    await db.refresh(revision_task)

    proposals = (
        await db.execute(
            select(RevisionProposalRow).where(
                RevisionProposalRow.task_id == revision_task.id
            )
        )
    ).scalars().all()
    assert proposals, f"应产出修改提案，任务错误：{revision_task.error_json}"
    proposal = proposals[0]
    hunks = list(proposal.hunks_json or [])
    assert hunks, "提案必须包含可应用的补丁"
    version_row = await db.get(DocumentVersion, review_setup["version_id"])
    base_text = normalize_text(version_row.text or "")
    assert revision_service.validate_hunks(
        base_text, hunks, preserve=list(PRESERVE_DEFAULTS)
    ) == []
    for hunk in hunks:
        start, end = int(hunk["start"]), int(hunk["end"])
        assert base_text[start:end] == hunk["original_text"]
    assert proposal.status == "proposed"
    assert proposal.base_version_id == review_setup["version_id"]


@pytest.mark.asyncio
async def test_revision_task_rejects_foreign_finding_before_billing(
    client_a, client_b, research_env, db, monkeypatch
):
    patch_switch(monkeypatch, "RESEARCH_MODEL_STUB", True)
    for name in ("a", "b"):
        await EntitlementService.grant_product(
            db, research_env.user_ids[name], "monthly_pro", f"r2-cross-grant-{name}"
        )
    await db.commit()

    project_b, version_b, task_b = await _make_version(
        db, research_env.actor("b"), client_b, need_finding=True
    )
    finding_b = _insert_finding(
        db,
        owner_id=research_env.user_ids["b"],
        task_id=task_b.id,
        version_id=version_b,
    )
    await db.commit()

    project_a = await create_project(client_a, "他人诊断项")
    document_a = await upload_document(client_a, project_a, text=BODY)
    version_a = version_id_of(document_a)

    response = await client_a.post(
        "/api/v1/research/tasks",
        json={
            "schema_version": "1.0",
            "project_id": project_a,
            "kind": "revision",
            "objective": "尝试引用他人诊断项",
            "input": {"document_version_id": version_a},
            "scope": {"finding_ids": [finding_b.id]},
        },
        headers={"Idempotency-Key": "r2-cross-foreign-0001"},
    )
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "FINDING_NOT_FOUND"
    assert finding_b.id in error["details"]["missing"]

    owned = (
        await db.execute(
            select(ResearchTask).where(
                ResearchTask.owner_id == research_env.user_ids["a"],
                ResearchTask.kind == "revision",
            )
        )
    ).scalars().all()
    assert not owned, "被拒绝的请求不得留下任务行（更不能扣额）"