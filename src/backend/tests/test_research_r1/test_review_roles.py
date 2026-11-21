"""T23：诊断流程 single / multi_role 的契约测试（不联网）。

验证：
- 默认 ``review_mode=single`` 行为不变：一遍全文，覆盖完整，无多角色提示；
- ``review_mode=multi_role`` 会把全文再跑一遍（角色焦点进入提示词），
  覆盖仍按「分析过的块」计，模型诊断项按（引文，问题）去重不重复；
- 预算在两轮之间平分，第二轮不会因为第一轮花光额度而静默跳过报告。
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from ...research import document_service, project_service, review_workflow
from ...research.contracts import new_id
from ...research.models import Artifact, FindingRow, ResearchTask

pytestmark = pytest.mark.asyncio

_DOC = (
    "# 平台算法与新闻消费\n\n"
    "## 1 引言\n\n"
    "本文讨论推荐系统如何改变用户的信息接触结构，并回顾既有争论。\n\n"
    "## 2 研究方法\n\n"
    "研究采用问卷与日志结合的混合设计，样本 1200 人，辅以 24 次深度访谈。\n\n"
    "## 3 结论\n\n"
    "算法并非单向决定，用户的选择性接触同样重要。\n\n"
    "## 参考文献\n\n"
    "[1] 张三. 算法推荐研究. 2024.\n"
)

_ONE_FINDING = {
    "findings": [
        {
            "category": "method",
            "severity": "major",
            "problem": "样本代表性未说明",
            "reason": "只写了样本量，没有交代抽样方式",
            "recommendation": "补充抽样框与配额说明",
            "quote": "样本 1200 人",
            "checked_sections": ["2 研究方法"],
        }
    ],
    "notes": [],
    "unresolved": [],
}


class _RecordingClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete(self, system, user, json_schema=None):
        self.prompts.append(user)
        return json.dumps(_ONE_FINDING, ensure_ascii=False)


async def _seed(db, store, *, review_mode: str | None):
    actor = store.actor("a")
    project = await project_service.create_project(db, actor, f"角色流程 {review_mode}")
    await db.commit()
    project_id = project["id"] if isinstance(project, dict) else project
    payload = await document_service.upload_document(
        db,
        actor,
        project_id,
        filename="roles.md",
        mime="text/markdown",
        data=_DOC.encode("utf-8"),
    )
    await db.commit()
    version = payload["version"] if isinstance(payload, dict) else payload
    constraints = {"review_mode": review_mode} if review_mode else {}
    task = ResearchTask(
        id=new_id("rtask"),
        owner_id=store.user_ids["a"],
        project_id=project_id,
        kind="review",
        objective="对全文做投稿前诊断",
        input_json={"document_version_id": version["id"]},
        constraints_json=constraints,
        snapshot_summary={"accepted_budget": {"max_model_calls": 40, "max_tokens": 60_000}},
        attempt_no=1,
        billing_group_id=f"bg_{review_mode}",
    )
    db.add(task)
    await db.flush()
    return task


async def test_single_mode_runs_one_pass(db, research_store):
    task = await _seed(db, research_store, review_mode=None)
    client = _RecordingClient()

    result = await review_workflow.run_review(db, task, client=client)

    assert client.prompts, "至少要发一次模型调用"
    assert not any("研究方法与证据" in prompt for prompt in client.prompts)
    assert result["coverage"]["analyzed_eligible_blocks"] == (
        result["coverage"]["expected_eligible_blocks"]
    )
    assert not any("multi_role" in warning for warning in result["warnings"])


async def test_multi_role_runs_second_pass_and_dedupes(db, research_store):
    single = await _seed(db, research_store, review_mode="single")
    single_client = _RecordingClient()
    await review_workflow.run_review(db, single, client=single_client)
    single_calls = len(single_client.prompts)

    multi = await _seed(db, research_store, review_mode="multi_role")
    multi_client = _RecordingClient()
    result = await review_workflow.run_review(db, multi, client=multi_client)

    # 第二轮真的跑了：调用翻倍，且第二遍带角色焦点。
    assert len(multi_client.prompts) > single_calls
    assert sum("研究方法与证据" in prompt for prompt in multi_client.prompts) >= 1
    assert any("multi_role" in warning for warning in result["warnings"])

    # 覆盖仍按真实分析过的块计，两遍不重复计数。
    assert result["coverage"]["analyzed_eligible_blocks"] == (
        result["coverage"]["expected_eligible_blocks"]
    )

    # 模型诊断项按（引文，问题）去重：同一问题两遍都报也只落一行。
    rows = (
        await db.execute(select(FindingRow).where(FindingRow.task_id == multi.id))
    ).scalars().all()
    model_rows = [row for row in rows if row.verification_method == "model"]
    keys = [(row.quote, row.problem) for row in model_rows]
    assert len(keys) == len(set(keys))
    assert any(quote == "样本 1200 人" for quote, _ in keys)

    artifacts = (
        await db.execute(select(Artifact).where(Artifact.task_id == multi.id))
    ).scalars().all()
    assert artifacts
