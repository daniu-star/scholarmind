"""T17 导出幂等与附章开关（R1 / AT-038、AT-011）。

这三个用例锁定的是"看似生效实则静默丢弃"的接口契约：

1. 同一个 ``Idempotency-Key`` 重复 ``POST /research/exports`` 只产生一个
   Artifact / 一条 export 任务行，且两次返回同一 ``artifact_id``；
2. 同键不同请求体 → 409 ``IDEMPOTENCY_CONFLICT``（不得静默复用旧成果）；
3. ``include_report`` / ``include_change_log`` 勾选但没有对应来源时 → 422
   ``EXPORT_SECTION_UNAVAILABLE``，而不是生成一份缺章节却自称完整的文件。
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from ...research.models import Artifact, ResearchTask
from ..test_research.conftest import (
    assert_error,
    create_project,
    upload_document,
    version_id_of,
)

pytestmark = pytest.mark.asyncio

TEXT = "第一段：样本量为 120 人，2023 年收集。\n\n第二段：结论仍需谨慎。\n"


async def _setup(client) -> dict:
    project_id = await create_project(client, "导出幂等")
    doc = await upload_document(client, project_id, text=TEXT)
    return {"project_id": project_id, "document_version_id": version_id_of(doc)}


async def test_same_idempotency_key_replays_single_artifact(client_a, db):
    base = await _setup(client_a)
    body = {**base, "format": "md", "journal_style": "generic"}
    headers = {"Idempotency-Key": "r1-export-key-0001"}

    first = await client_a.post("/api/v1/research/exports", json=body, headers=headers)
    second = await client_a.post("/api/v1/research/exports", json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]

    db.expire_all()
    artifacts = int(
        (await db.execute(select(func.count()).select_from(Artifact))).scalar_one()
    )
    tasks = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ResearchTask)
                .where(ResearchTask.kind == "export")
            )
        ).scalar_one()
    )
    assert artifacts == 1
    assert tasks == 1


async def test_same_key_different_request_conflicts(client_a, db):
    base = await _setup(client_a)
    headers = {"Idempotency-Key": "r1-export-key-0002"}
    first = await client_a.post(
        "/api/v1/research/exports",
        json={**base, "format": "md", "journal_style": "generic"},
        headers=headers,
    )
    assert first.status_code == 201, first.text

    conflict = await client_a.post(
        "/api/v1/research/exports",
        json={**base, "format": "docx", "journal_style": "generic"},
        headers=headers,
    )
    assert_error(conflict, 409, "IDEMPOTENCY_CONFLICT")
    db.expire_all()
    assert (
        int((await db.execute(select(func.count()).select_from(Artifact))).scalar_one()) == 1
    )


@pytest.mark.parametrize("option", ["include_report", "include_change_log"])
async def test_include_sections_without_source_are_rejected(client_a, db, option):
    base = await _setup(client_a)
    response = await client_a.post(
        "/api/v1/research/exports",
        json={
            **base,
            "format": "md",
            "journal_style": "generic",
            option: True,
        },
        headers={"Idempotency-Key": f"r1-export-key-{option}"},
    )
    assert_error(response, 422, "EXPORT_SECTION_UNAVAILABLE")
    db.expire_all()
    assert (
        int((await db.execute(select(func.count()).select_from(Artifact))).scalar_one()) == 0
    )
