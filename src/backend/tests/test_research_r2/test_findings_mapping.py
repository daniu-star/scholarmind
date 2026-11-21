"""结构性检查证据与 DTO 出口映射（R2 / AT-023 AT-024 AT-045）。

``review_workflow`` 会在库里写 ``verification_method="structural"``，但 PRD 只允许
``tool/model/human/none`` 四值。这里锁定两件事：库里保留 structural 供导出文案
使用，API 出口必须映射成契约内的值，且任何组合都不能让列表接口 500。
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from ...research import task_service
from ...research.contracts import VerificationMethod
from ...research.models import FindingRow, ResearchTask
from ...research.task_runner import execute_task
from ...services.entitlement_service import EntitlementService
from .conftest import patch_switch
from ..test_research.conftest import (
    create_project,
    task_body,
    upload_document,
    version_id_of,
)

ALLOWED_METHODS = {member.value for member in VerificationMethod}


@pytest_asyncio.fixture
async def review_task(client_a, research_env, db, monkeypatch):
    """缺章节的短文档 → 结构性检查必然产出 document 级诊断项。"""
    # 走真实 runtime.get_client 路径（替身模型），两套 settings 都要打点。
    patch_switch(monkeypatch, "RESEARCH_MODEL_STUB", True)
    user_id = research_env.user_ids["a"]
    await EntitlementService.grant_product(db, user_id, "monthly_pro", "r2-findings-grant")
    await db.commit()

    project_id = await create_project(client_a, "结构性检查映射")
    document = await upload_document(
        client_a,
        project_id,
        text="# 一个没有方法也没有参考文献的稿子\n\n我们看到了一些现象，结论很有意义。\n",
    )
    body = task_body(
        project_id=project_id,
        document_version_id=version_id_of(document),
    )
    accepted = await task_service.create_task(
        db, research_env.actor("a"), body, idempotency_key="r2-findings-key-0001"
    )
    task = (
        await db.execute(select(ResearchTask).where(ResearchTask.id == accepted.task_id))
    ).scalar_one()
    await execute_task(db, task, holder="verifier")
    await db.refresh(task)
    return task


@pytest.mark.asyncio
async def test_structural_findings_expose_contract_method(review_task, db, research_env):
    findings = await task_service.list_findings(
        db, research_env.actor("a"), review_task.id
    )
    assert findings, "缺章节文档应产出结构性诊断项"

    structural_rows = list(
        (
            await db.execute(
                select(FindingRow).where(FindingRow.task_id == review_task.id)
            )
        )
        .scalars()
        .all()
    )
    raw_methods = {str(row.verification_method) for row in structural_rows}
    assert "structural" in raw_methods, "库里应保留 structural 以支撑导出文案"

    exposed = {finding.verification_method for finding in findings}
    assert exposed <= ALLOWED_METHODS, f"出口出现契约外的值：{exposed - ALLOWED_METHODS}"
    assert "tool" in exposed, "结构性检查对外必须呈现为确定性检查(tool)"

    for finding in findings:
        assert finding.id
        assert finding.task_id == review_task.id
        assert finding.severity in {"critical", "major", "minor"}
        assert finding.problem and finding.reason
        assert isinstance(finding.locator, dict) and finding.locator


@pytest.mark.asyncio
async def test_findings_endpoint_does_not_500_on_structural_rows(
    review_task, client_a
):
    response = await client_a.get(f"/api/v1/research/tasks/{review_task.id}/findings")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload, dict)
    items = payload.get("items")
    assert items, "接口应返回诊断项"
    for item in items:
        assert item["verification_method"] in ALLOWED_METHODS
        assert item["task_id"] == review_task.id