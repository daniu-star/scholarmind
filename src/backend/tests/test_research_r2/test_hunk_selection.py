"""逐条采纳补丁（hunk 级 apply）。

背景：R1 的界面上只能「整份采纳」，因为客户端拿不到逐条补丁的真实 id；
后端 `apply_proposal` 早就支持 `hunk_ids` 子集，但缺一个只读端点暴露 id。
这里锁定：

1. `GET /revision-proposals/{id}` 返回逐条补丁（含真实 id、区间、原文、替换文）；
2. 只提交其中一条时，**只有这条生效**，其余补丁的原文保持不变；
3. 未知补丁 id 会被 422 `HUNK_NOT_FOUND` 拒绝，不会静默忽略；
4. 他人的提案读不到（404，不泄露存在性）。
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from ...research import task_service
from ...research.contracts import new_id, normalize_text
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
    + "本段用于拉开两处诊断项的距离，不承载诊断内容。" * 8
    + "\n\n现有研究大多停在描述层面。\n"
)

MARKER = "（示例改写）"


def _findings(text: str):
    return [
        ("算法推荐把用户的注意力切成碎片，平台因此获得了可观的收益。", "argument", "第一处"),
        ("现有研究大多停在描述层面。", "evidence", "第二处"),
    ], text


async def _make_proposal(db, client, actor):
    """跑 review（替身模型）+ 手工插入两条诊断项 + 跑 revision，返回提案行与基准版本。"""
    project_id = await create_project(client, "逐条采纳")
    document = await upload_document(client, project_id, text=BODY)
    version_id = version_id_of(document)
    accepted = await task_service.create_task(
        db,
        actor,
        task_body(project_id=project_id, document_version_id=version_id),
        idempotency_key=f"r2-hunk-review-{new_id('key')}",
    )
    task = (
        await db.execute(select(ResearchTask).where(ResearchTask.id == accepted.task_id))
    ).scalar_one()
    await execute_task(db, task, holder=f"verifier:{new_id('h')}")
    await db.refresh(task)

    stored = await db.get(DocumentVersion, version_id, populate_existing=True)
    assert stored is not None, version_id
    text = normalize_text(stored.text or "")
    finding_ids = []
    for quote, category, label in _findings(text)[0]:
        start = text.index(quote)
        row = FindingRow(
            id=f"find_{new_id('')[:24]}",
            task_id=task.id,
            owner_id=actor.user_id,
            version_id=version_id,
            scope="local",
            category=category,
            severity="major",
            problem=f"{label}需要修改。",
            reason=f"{label}的论证不充分。",
            recommendation=f"请改写{label}。",
            evidence_refs=[],
            locator={"start": start, "end": start + len(quote), "version_id": version_id},
            quote=quote,
            verification_method="model",
        )
        db.add(row)
        finding_ids.append(row.id)
    await db.commit()

    revision_accepted = await task_service.create_task(
        db,
        actor,
        {
            "schema_version": "1.0",
            "project_id": project_id,
            "kind": "revision",
            "objective": "按选中诊断项给出可直接采纳的补丁",
            "input": {"document_version_id": version_id},
            "scope": {"finding_ids": finding_ids},
        },
        idempotency_key=f"r2-hunk-revision-{new_id('key')}",
    )
    revision_task = (
        await db.execute(
            select(ResearchTask).where(ResearchTask.id == revision_accepted.task_id)
        )
    ).scalar_one()
    await execute_task(db, revision_task, holder=f"verifier:{new_id('h')}")
    await db.refresh(revision_task)

    proposal = (
        await db.execute(
            select(RevisionProposalRow).where(
                RevisionProposalRow.task_id == revision_task.id
            )
        )
    ).scalars().first()
    assert proposal is not None, f"应产出提案，任务错误：{revision_task.error_json}"
    version = await db.get(DocumentVersion, version_id)
    return {
        "proposal": proposal,
        "version": version,
        "project_id": project_id,
    }


@pytest_asyncio.fixture
async def proposal_setup(client_a, research_env, db, monkeypatch):
    patch_switch(monkeypatch, "RESEARCH_MODEL_STUB", True)
    user_id = research_env.user_ids["a"]
    await EntitlementService.grant_product(db, user_id, "monthly_pro", "r2-hunk-grant-a")
    await db.commit()
    return await _make_proposal(db, client_a, research_env.actor("a"))


@pytest.mark.asyncio
async def test_get_proposal_exposes_hunk_ids(client_a, proposal_setup):
    proposal = proposal_setup["proposal"]
    response = await client_a.get(f"/api/v1/research/revision-proposals/{proposal.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == proposal.id
    assert body["base_version_id"] == proposal.base_version_id
    assert body["status"] == "proposed"
    assert len(body["hunks"]) >= 2, body
    ids = [hunk["id"] for hunk in body["hunks"]]
    assert len(ids) == len(set(ids)), "补丁 id 不应重复"
    for hunk in body["hunks"]:
        assert hunk["start"] <= hunk["end"]
        assert hunk["original_text"]
        assert hunk["original_hash"]


@pytest.mark.asyncio
async def test_apply_only_selected_hunk(client_a, db, proposal_setup):
    proposal = proposal_setup["proposal"]
    version = proposal_setup["version"]
    detail = (await client_a.get(f"/api/v1/research/revision-proposals/{proposal.id}")).json()
    hunks = sorted(detail["hunks"], key=lambda item: item["start"])
    chosen = hunks[0]

    response = await client_a.post(
        f"/api/v1/research/revision-proposals/{proposal.id}/apply",
        json={
            "expected_version_id": proposal.base_version_id,
            "hunk_ids": [chosen["id"]],
        },
        headers={"Idempotency-Key": f"r2-hunk-apply-{new_id('')[:16]}"},
    )
    assert response.status_code == 200, response.text
    applied = response.json()
    assert applied["applied_hunk_ids"] == [chosen["id"]]

    refreshed = await client_a.get(f"/api/v1/research/documents/{version.document_id}")
    assert refreshed.status_code == 200
    new_version_id = applied["new_version_id"]
    assert refreshed.json()["current_version_id"] == new_version_id

    new_version = await db.get(
        DocumentVersion, new_version_id, populate_existing=True
    )
    assert new_version is not None, new_version_id
    base_text = normalize_text(version.text or "")
    expected = (
        base_text[: chosen["start"]] + chosen["replacement_text"] + base_text[chosen["end"] :]
    )
    assert normalize_text(new_version.text) == normalize_text(expected)
    # 只有一条补丁生效：其余补丁的原文必须仍保留
    for other in hunks[1:]:
        assert other["original_text"] in normalize_text(new_version.text)


@pytest.mark.asyncio
async def test_apply_unknown_hunk_is_rejected(client_a, proposal_setup):
    proposal = proposal_setup["proposal"]
    response = await client_a.post(
        f"/api/v1/research/revision-proposals/{proposal.id}/apply",
        json={
            "expected_version_id": proposal.base_version_id,
            "hunk_ids": ["hunk_does_not_exist"],
        },
        headers={"Idempotency-Key": f"r2-hunk-bad-{new_id('')[:16]}"},
    )
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "HUNK_NOT_FOUND"
    assert "hunk_does_not_exist" in error["details"]["missing"]


@pytest.mark.asyncio
async def test_foreign_proposal_is_hidden(client_b, proposal_setup):
    proposal = proposal_setup["proposal"]
    response = await client_b.get(f"/api/v1/research/revision-proposals/{proposal.id}")
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "NOT_FOUND"
