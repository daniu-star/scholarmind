"""T15 / AT-014·AT-015·AT-026·AT-027：全文诊断的检查点续跑与诚实覆盖。

验证 R1_INTERFACE_SPEC §2.3：
- 检查点存在时只分析剩余块，历史诊断项合并且不重复；
- 尾部块必须始终被分析（预算不足时优先丢弃中段窗口）；
- 结构性缺失（completeness 纯函数）与模型诊断一起进入成果，且来源可区分；
- ``coverage.unassessed_objects`` 必须说明未分析对象与原因，不能静默少算。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from ...research import document_service, project_service, review_workflow
from ...research.checkpoints import load_checkpoint
from ...research.contracts import new_id
from ...research.errors import ResearchAPIError, unavailable
from ...research.models import (
    Artifact,
    DocumentBlock,
    FindingRow,
    ResearchTask,
    TaskAttempt,
)
from ...research.task_repository import open_attempt

pytestmark = pytest.mark.asyncio


def _doc_text() -> str:
    """构造多窗口文档：11 个带唯一标记的正文段 + 四个标准章节标题。"""
    parts = ["# 论文标题"]
    sections = (("1 引言", 3), ("2 研究方法", 3), ("3 结论", 3), ("参考文献", 2))
    index = 0
    for heading, count in sections:
        parts.append(f"## {heading}")
        for _ in range(count):
            marker = f"MARK{index:04d}"
            body = "这段文字用于验证全文诊断、覆盖统计与检查点续跑行为。" * 5
            parts.append(f"{marker} {body}")
            index += 1
    # 最后一段带专用标记：用于验证“尾部块必须被分析”。
    parts[-1] = parts[-1].replace("MARK0010", "TAILMARK")
    return "\n\n".join(parts)


@pytest_asyncio.fixture
async def flow_env(db, research_store):
    actor = research_store.actor("a")
    project = await project_service.create_project(db, actor, "R1 诊断流程项目")
    await db.commit()
    project_id = project["id"] if isinstance(project, dict) else project
    payload = await document_service.upload_document(
        db,
        actor,
        project_id,
        filename="flow.md",
        mime="text/markdown",
        data=_doc_text().encode("utf-8"),
    )
    await db.commit()
    document = payload["document"] if isinstance(payload, dict) else payload
    version = payload["version"] if isinstance(payload, dict) else payload
    return SimpleNamespace(
        actor=actor,
        owner=research_store.user_ids["a"],
        project_id=project_id,
        document_id=document["id"],
        version_id=version["id"],
    )


@pytest_asyncio.fixture
async def short_env(db, research_store):
    """只有引言、没有方法/结论/参考文献的最小文档。"""
    actor = research_store.actor("a")
    project = await project_service.create_project(db, actor, "R1 结构缺失项目")
    await db.commit()
    project_id = project["id"] if isinstance(project, dict) else project
    payload = await document_service.upload_document(
        db,
        actor,
        project_id,
        filename="short.md",
        mime="text/markdown",
        data="# 标题\n\n## 1 引言\n\n只有引言，没有方法与结论。\n".encode("utf-8"),
    )
    await db.commit()
    document = payload["document"] if isinstance(payload, dict) else payload
    version = payload["version"] if isinstance(payload, dict) else payload
    return SimpleNamespace(
        actor=actor,
        owner=research_store.user_ids["a"],
        project_id=project_id,
        document_id=document["id"],
        version_id=version["id"],
    )


class _RecordingClient:
    """记录每次提示词的合法 JSON 客户端。"""

    def __init__(self):
        self.prompts: list[str] = []

    async def complete(self, system, user, json_schema=None):
        self.prompts.append(user)
        return json.dumps(
            {"findings": [], "notes": ["已按窗口完成阅读"], "unresolved": []},
            ensure_ascii=False,
        )


class _TailOnlyClient:
    """只对含 TAILMARK 的窗口返回合法 JSON，其余窗口输出乱码。"""

    def __init__(self):
        self.prompts: list[str] = []

    async def complete(self, system, user, json_schema=None):
        self.prompts.append(user)
        if "TAILMARK" in user:
            return json.dumps({"findings": [], "notes": [], "unresolved": []})
        return "抱歉，我无法按要求输出 JSON。"


class _UnavailableClient:
    async def complete(self, system, user, json_schema=None):
        raise unavailable("MODEL_UNAVAILABLE", "模型不可用（测试替身）")


async def _blocks(db, version_id: str) -> list[DocumentBlock]:
    result = await db.execute(
        select(DocumentBlock)
        .where(DocumentBlock.version_id == version_id, DocumentBlock.eligible.is_(True))
        .order_by(DocumentBlock.ordinal)
    )
    return list(result.scalars().all())


def _marker_ordinals(blocks: list[DocumentBlock]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for block in blocks:
        head = (block.text or "").strip()[:8]
        if head.startswith("MARK") or head.startswith("TAILMARK"):
            mapping[head] = int(block.ordinal)
    return mapping


async def _seed_task(db, env, *, budget: dict | None = None, attempt_no: int = 1):
    task = ResearchTask(
        id=new_id("rtask"),
        owner_id=env.owner,
        project_id=env.project_id,
        kind="review",
        objective="验证全文诊断与检查点",
        input_json={"document_version_id": env.version_id},
        snapshot_summary={"accepted_budget": budget} if budget else {},
        attempt_no=attempt_no,
        billing_group_id="bg_flow",
    )
    db.add(task)
    await db.flush()
    return task


async def _seed_attempt(db, task, checkpoint: dict | None, *, attempt_no: int = 1):
    attempt = TaskAttempt(
        id=new_id("att"),
        task_id=task.id,
        attempt_no=attempt_no,
        status="running",
        lease_holder="verifier",
        fencing_token=attempt_no,
    )
    # JSON 列显式传 None 会被序列化为字符串 "null"，必须省略属性才是 SQL NULL。
    if checkpoint is not None:
        attempt.checkpoint_json = checkpoint
    db.add(attempt)
    await db.flush()
    return attempt


def _history_finding() -> dict:
    return {
        "category": "argument",
        "severity": "minor",
        "problem": "恢复的历史问题",
        "reason": "检查点中已记录",
        "recommendation": "复核论证链条",
        "scope": "document",
        "quote": None,
        "locator": {"scope": "document"},
        "evidence_refs": [],
        "checked_sections": ["1 引言"],
        "required_user_action": None,
        "block_ordinal": None,
        "verification_method": "model",
    }


class TestCheckpointResume:
    async def test_resume_analyzes_only_remaining_blocks(self, db, flow_env):
        blocks = await _blocks(db, flow_env.version_id)
        markers = _marker_ordinals(blocks)
        seeded_markers = list(markers)[:5]
        seeded = [markers[name] for name in seeded_markers]
        task = await _seed_task(db, flow_env)
        await _seed_attempt(
            db,
            task,
            {
                "document_version_id": flow_env.version_id,
                "analyzed_ordinals": seeded,
                "cursor": 1,
                "model_calls": 2,
                "tokens": 120,
                "findings": [_history_finding()],
            },
        )
        client = _RecordingClient()

        result = await review_workflow.run_review(db, task, client=client)

        assert result["resumed_blocks"] == len(seeded)
        assert result["coverage"]["analyzed_eligible_blocks"] == len(blocks)
        assert result["coverage"]["unassessed_objects"] == []
        # 只剩 11 个块待分析：窗口数必须显著少于全量 16 块，且每次模型调用对应一个窗口。
        joined = "\n".join(client.prompts)
        for ordinal in seeded:
            assert f"[块 {ordinal}]" not in joined
        assert result["calls"] == 2 + len(client.prompts)
        assert 0 < len(client.prompts) < len(blocks)
        assert "TAILMARK" in joined
        problems = [item["problem"] for item in result["findings"]]
        assert problems.count("恢复的历史问题") == 1

        checkpoint = await load_checkpoint(db, task.id)
        assert checkpoint["analyzed_ordinals"] == sorted(
            int(block.ordinal) for block in blocks
        )
        assert checkpoint["model_calls"] == result["calls"] > 0

    async def test_resumed_paragraph_text_is_not_reanalyzed(self, db, flow_env):
        """已分析块的原文字不应再次出现在新窗口里（契约 §2.3“只分析剩余”）。

        回归（原缺陷 R1-D2）：`review_workflow._build_review_blocks` 曾把检索分块
        （会合并相邻短块）当作单块文本，使已分析段的文字被分块带进新窗口；
        修复方式是 `_chunk_text_for_block` 按 chunk.start/end ∩ block.start/end 裁剪。
        """
        blocks = await _blocks(db, flow_env.version_id)
        markers = _marker_ordinals(blocks)
        seeded_markers = list(markers)[:5]
        seeded = [markers[name] for name in seeded_markers]
        task = await _seed_task(db, flow_env)
        await _seed_attempt(
            db,
            task,
            {
                "document_version_id": flow_env.version_id,
                "analyzed_ordinals": seeded,
                "cursor": 1,
                "model_calls": 2,
                "tokens": 120,
                "findings": [],
            },
        )
        client = _RecordingClient()

        await review_workflow.run_review(db, task, client=client)

        joined = "\n".join(client.prompts)
        for marker in seeded_markers:
            assert marker not in joined

    async def test_checkpoint_from_other_version_is_ignored(self, db, flow_env):
        blocks = await _blocks(db, flow_env.version_id)
        markers = _marker_ordinals(blocks)
        task = await _seed_task(db, flow_env)
        await _seed_attempt(
            db,
            task,
            {
                "document_version_id": "rdv_other_version",
                "analyzed_ordinals": list(markers.values()),
                "cursor": 9,
                "model_calls": 9,
                "tokens": 900,
                "findings": [_history_finding()],
            },
        )
        client = _RecordingClient()

        result = await review_workflow.run_review(db, task, client=client)

        assert result["resumed_blocks"] == 0
        assert any("其他文档版本" in item for item in result["warnings"])
        assert result["coverage"]["analyzed_eligible_blocks"] == len(blocks)
        # 旧版本的历史诊断项不得跨版本复用。
        problems = [item["problem"] for item in result["findings"]]
        assert "恢复的历史问题" not in problems


class TestTailGuarantee:
    async def test_tail_block_is_analyzed_even_when_budget_is_tight(
        self, db, flow_env
    ):
        blocks = await _blocks(db, flow_env.version_id)
        markers = _marker_ordinals(blocks)
        tail_ordinal = markers["TAILMARK"]
        # 只给 1 次调用预算：中段窗口必须让位，最后一块（含结论/声明）必须被分析。
        task = await _seed_task(db, flow_env, budget={"max_calls": 1, "max_tokens": 100000})
        await _seed_attempt(db, task, None)
        client = _TailOnlyClient()

        result = await review_workflow.run_review(db, task, client=client)

        checkpoint = await load_checkpoint(db, task.id)
        assert tail_ordinal in checkpoint["analyzed_ordinals"]
        assert result["truncated"] is True
        assert result["coverage"]["analyzed_eligible_blocks"] < len(blocks)
        # 尾部块所在窗口被真实分析：结果与成果都必须体现，而不是只分析前 8000 字。
        assert result["quality_verdict"] == "insufficient_evidence"
        assert result["coverage"]["unassessed_objects"]
        assert all(
            item.startswith("block:") for item in result["coverage"]["unassessed_objects"]
        )
        assert any("预算" in item for item in result["coverage"]["unassessed_objects"])
        assert "TAILMARK" in "\n".join(client.prompts)

    async def test_budget_exhausted_checkpoint_skips_model_and_is_honest(
        self, db, flow_env
    ):
        blocks = await _blocks(db, flow_env.version_id)
        task = await _seed_task(db, flow_env, budget={"max_calls": 2, "max_tokens": 100000})
        await _seed_attempt(
            db,
            task,
            {
                "document_version_id": flow_env.version_id,
                "analyzed_ordinals": [int(blocks[0].ordinal)],
                "cursor": 1,
                "model_calls": 2,
                "tokens": 500,
                "findings": [],
            },
        )
        client = _RecordingClient()

        result = await review_workflow.run_review(db, task, client=client)

        assert client.prompts == []
        assert result["truncated"] is True
        assert result["quality_verdict"] == "insufficient_evidence"
        assert result["coverage"]["analyzed_eligible_blocks"] == 1
        assert result["coverage"]["unassessed_objects"]
        assert all(
            "预算已耗尽" in item for item in result["coverage"]["unassessed_objects"]
        )


class TestStructuralFindings:
    async def test_missing_sections_enter_artifact_with_structural_source(
        self, db, short_env
    ):
        task = await _seed_task(db, short_env)
        client = _RecordingClient()

        result = await review_workflow.run_review(db, task, client=client)

        assert result["structural_finding_count"] >= 3
        assert result["quality_verdict"] == "issues_found"
        rows = list(
            (
                await db.execute(
                    select(FindingRow).where(FindingRow.task_id == task.id)
                )
            )
            .scalars()
            .all()
        )
        structural = [row for row in rows if row.verification_method == "structural"]
        assert structural
        assert {row.category for row in structural} <= {"format", "evidence"}
        for row in structural:
            assert row.scope == "document"
            assert row.locator["scope"] == "document"
            # checked_sections 记录的是真实分析范围（标题层级路径）。
            assert any(
                section == "1 引言" or section.endswith("1 引言")
                for section in row.checked_sections
            )
            assert row.problem
            assert row.reason

        artifact = (
            await db.execute(select(Artifact).where(Artifact.task_id == task.id))
        ).scalar_one()
        assert artifact.validation_json["structural_finding_count"] == len(structural)
        assert "缺少「方法」章节" in artifact.body
        assert "检查方式：结构性检查" in artifact.body
        assert review_workflow.DIAGNOSIS_DISCLAIMER in artifact.body

    async def test_model_findings_and_structural_findings_are_separately_counted(
        self, db, short_env
    ):
        class _OneFindingClient:
            async def complete(self, system, user, json_schema=None):
                return json.dumps(
                    {
                        "findings": [
                            {
                                "category": "expression",
                                "severity": "minor",
                                "problem": "表述可以更精确",
                                "reason": "存在模糊指代",
                                "recommendation": "明确指代对象",
                                "quote": "只有引言",
                                "checked_sections": ["1 引言"],
                            }
                        ],
                        "notes": [],
                        "unresolved": [],
                    },
                    ensure_ascii=False,
                )

        task = await _seed_task(db, short_env)

        result = await review_workflow.run_review(db, task, client=_OneFindingClient())

        assert result["model_finding_count"] == 1
        assert result["structural_finding_count"] >= 3
        assert result["finding_count"] == (
            result["model_finding_count"] + result["structural_finding_count"]
        )


class TestSevereVerdict:
    async def test_critical_finding_yields_issues_found_without_faking_clean(
        self, db, short_env
    ):
        class _CriticalClient:
            async def complete(self, system, user, json_schema=None):
                return json.dumps(
                    {
                        "findings": [
                            {
                                "category": "argument",
                                "severity": "critical",
                                "problem": "核心论证缺少证据支撑",
                                "reason": "结论直接由断言给出，未提供数据或引文",
                                "quote": "只有引言",
                                "checked_sections": ["1 引言"],
                            }
                        ],
                        "notes": [],
                        "unresolved": [],
                    },
                    ensure_ascii=False,
                )

        task = await _seed_task(db, short_env)
        result = await review_workflow.run_review(db, task, client=_CriticalClient())

        # 严重问题必须如实给出 issues_found，不能因为结构缺失而抹成“无问题”。
        assert result["quality_verdict"] == "issues_found"
        coverage = result["coverage"]
        assert coverage["analyzed_eligible_blocks"] == coverage["expected_eligible_blocks"]
        rows = (
            await db.execute(select(FindingRow).where(FindingRow.task_id == task.id))
        ).scalars().all()
        assert any(row.severity == "critical" for row in rows)
        artifact = (
            await db.execute(select(Artifact).where(Artifact.task_id == task.id))
        ).scalar_one()
        assert artifact.validation_json["quality_verdict"] == "issues_found"


class TestFailurePaths:
    async def test_model_unavailable_is_not_swallowed(self, db, flow_env):
        task = await _seed_task(db, flow_env)

        with pytest.raises(ResearchAPIError) as excinfo:
            await review_workflow.run_review(db, task, client=_UnavailableClient())

        assert excinfo.value.code == "MODEL_UNAVAILABLE"
        findings = await db.scalar(
            select(func.count()).select_from(FindingRow).where(FindingRow.task_id == task.id)
        )
        artifacts = await db.scalar(
            select(func.count()).select_from(Artifact).where(Artifact.task_id == task.id)
        )
        assert findings == 0
        assert artifacts == 0

    async def test_attempt_bound_run_writes_checkpoint(self, db, flow_env):
        """检查点写入与当前 attempt 绑定：open_attempt 之后可续跑并写回。"""
        task = await _seed_task(db, flow_env)
        attempt = await open_attempt(
            db, task, lease_holder="verifier", lease_seconds=120
        )

        result = await review_workflow.run_review(
            db, task, client=_RecordingClient()
        )

        assert attempt.attempt_no == 2
        checkpoint = await load_checkpoint(db, task.id)
        assert checkpoint["analyzed_ordinals"] == sorted(
            int(block.ordinal) for block in await _blocks(db, flow_env.version_id)
        )
        assert result["coverage"]["unassessed_objects"] == []