"""修改提案与补丁应用（R0：AT-034、AT-038、FR-08/FR-15）。

两部分：
1. ``validate_hunks`` 纯函数：区间/原文哈希/重叠/受保护内容/无差异都必须报问题。
2. ``apply_proposal`` 服务：基准版本固定（409 VERSION_CONFLICT）、倒序应用、
   新版本 + 变更说明成果 + 幂等重放、他人提案统一 404。

断言的是**数据库最终状态**（版本号、当前版本指针、块偏移、成果行）与错误码。
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from ...research import revision_service
from ...research.contracts import (
    PRESERVE_DEFAULTS,
    new_id,
    text_hash,
    utcnow,
)
from ...research.errors import ResearchAPIError
from ...research.models import (
    Artifact,
    Document,
    DocumentBlock,
    DocumentVersion,
    Project,
    RevisionProposalRow,
)
from ...research.revision_service import (
    MAX_HUNK_CODEPOINTS,
    apply_proposal,
    validate_hunks,
)


BASE_TEXT = (
    "第一段：样本量为 120 人，2023 年收集数据，结论仍需谨慎。\n\n"
    "第二段：研究结果并不显著，作者应补充反例讨论。"
)


def _hunk(
    base: str,
    old: str,
    new: str,
    *,
    hunk_id: str = "hunk_1",
    finding_id: str = "rfnd_1",
    start: int | None = None,
    end: int | None = None,
) -> dict:
    start = base.index(old) if start is None else start
    end = start + len(old) if end is None else end
    return {
        "id": hunk_id,
        "finding_id": finding_id,
        "start": start,
        "end": end,
        "original_text": old,
        "original_hash": text_hash(old),
        "replacement_text": new,
        "reason": "改写表述使其更审慎",
    }


def _assert_error(excinfo, status: int, code: str) -> ResearchAPIError:
    error = excinfo.value
    assert isinstance(error, ResearchAPIError)
    assert (error.status_code, error.code) == (status, code), (
        f"期望 {status}/{code}，实际 {error.status_code}/{error.code}"
    )
    return error


# ── validate_hunks：纯函数 ───────────────────────────────


def test_valid_hunks_pass_validation():
    hunk = _hunk(BASE_TEXT, "结论仍需谨慎", "结论仍需谨慎，并说明边界条件")
    assert validate_hunks(BASE_TEXT, [hunk]) == []


def test_two_non_overlapping_hunks_pass_validation():
    hunks = [
        _hunk(BASE_TEXT, "结论仍需谨慎", "结论仍需谨慎，并说明边界条件", hunk_id="h1"),
        _hunk(
            BASE_TEXT,
            "作者应补充反例讨论",
            "作者应补充反例与替代解释的讨论",
            hunk_id="h2",
        ),
    ]
    assert validate_hunks(BASE_TEXT, hunks) == []


def test_validate_rejects_non_string_base_text():
    assert validate_hunks(None, []) == ["基准正文必须是字符串"]


def test_validate_rejects_none_and_non_list():
    assert validate_hunks(BASE_TEXT, None) == ["补丁列表不能为空"]
    assert validate_hunks(BASE_TEXT, {"start": 1}) == ["补丁列表必须是数组"]


def test_validate_rejects_non_dict_hunk():
    issues = validate_hunks(BASE_TEXT, ["not-a-dict"])
    assert issues and "必须是对象" in issues[0]


def test_validate_reports_missing_fields():
    issues = validate_hunks(BASE_TEXT, [{"id": "hunk_x"}])
    joined = "\n".join(issues)
    for field in ("start", "end", "original_text", "replacement_text", "original_hash"):
        assert field in joined, joined


def test_validate_rejects_negative_and_reversed_range():
    cases = [
        {"start": -1, "end": 3},
        {"start": 10, "end": 5},
    ]
    for bounds in cases:
        issues = validate_hunks(
            BASE_TEXT,
            [
                {
                    "id": "h",
                    "start": bounds["start"],
                    "end": bounds["end"],
                    "original_text": "x",
                    "original_hash": text_hash("x"),
                    "replacement_text": "yy",
                }
            ],
        )
        assert issues, bounds


def test_validate_rejects_end_beyond_text():
    issues = validate_hunks(
        BASE_TEXT,
        [
            {
                "id": "h",
                "start": 0,
                "end": len(BASE_TEXT) + 10,
                "original_text": "x",
                "original_hash": text_hash("x"),
                "replacement_text": "yy",
            }
        ],
    )
    assert any("超出正文长度" in issue for issue in issues), issues


def test_validate_rejects_original_text_mismatch():
    hunk = _hunk(BASE_TEXT, "结论仍需谨慎", "结论仍需审慎")
    hunk["original_text"] = "原文并不在这个位置"
    hunk["original_hash"] = text_hash("原文并不在这个位置")
    issues = validate_hunks(BASE_TEXT, [hunk])
    assert any("原文与基准版本不一致" in issue for issue in issues), issues


def test_validate_rejects_hash_mismatch():
    hunk = _hunk(BASE_TEXT, "结论仍需谨慎", "结论仍需审慎")
    hunk["original_hash"] = "0" * 64
    issues = validate_hunks(BASE_TEXT, [hunk])
    assert any("original_hash" in issue for issue in issues), issues


def test_validate_accepts_nfc_equivalent_original():
    base = "café 论证"  # NFC 预组合
    decomposed = "cafe\u0301 论证"  # NFD
    hunk = {
        "id": "h",
        "start": 0,
        "end": len(base),
        "original_text": decomposed,
        "original_hash": text_hash(decomposed),
        "replacement_text": "café 论证更充分",
    }
    assert validate_hunks(base, [hunk]) == []


def test_validate_rejects_no_op_replacement():
    hunk = _hunk(BASE_TEXT, "结论仍需谨慎", "结论仍需谨慎")
    issues = validate_hunks(BASE_TEXT, [hunk])
    assert any("未产生实际修改" in issue for issue in issues), issues


def test_validate_rejects_overlapping_hunks():
    first = _hunk(BASE_TEXT, "结论仍需谨慎", "结论仍需谨慎，并说明边界", hunk_id="h1")
    start = BASE_TEXT.index("仍需谨慎")
    second = {
        "id": "h2",
        "start": start,
        "end": start + 4,
        "original_text": "仍需谨慎",
        "original_hash": text_hash("仍需谨慎"),
        "replacement_text": "仍需非常谨慎",
    }
    issues = validate_hunks(BASE_TEXT, [first, second])
    assert any("重叠" in issue for issue in issues), issues


def test_validate_protects_numbers_and_dates():
    hunk = _hunk(BASE_TEXT, "样本量为 120 人，2023 年收集数据", "样本量为若干人，近年收集数据")
    issues = validate_hunks(BASE_TEXT, [hunk])
    joined = "\n".join(issues)
    assert "受保护内容（数字）" in joined, issues
    assert "受保护内容（日期）" in joined, issues


def test_validate_can_skip_preserve_rules_when_explicitly_empty():
    hunk = _hunk(BASE_TEXT, "样本量为 120 人", "样本量为若干人")
    assert validate_hunks(BASE_TEXT, [hunk], preserve=[]) == []


def test_validate_rejects_hunk_larger_than_limit():
    base = "甲" * (MAX_HUNK_CODEPOINTS + 200)
    hunk = {
        "id": "h",
        "start": 0,
        "end": len(base),
        "original_text": base,
        "original_hash": text_hash(base),
        "replacement_text": "乙" * len(base),
    }
    issues = validate_hunks(base, [hunk], preserve=[])
    assert any("超过局部修改上限" in issue for issue in issues), issues


# ── apply_proposal：服务层 ───────────────────────────────


@pytest_asyncio.fixture
async def rev_env(db, research_store):
    """一个归属 A 的项目/文档/基准版本，供提案应用用例复用。"""
    owner = research_store.user_ids["a"]
    project = Project(
        id=new_id("rproj"),
        owner_id=owner,
        title="修改验证项目",
        status="active",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(project)
    await db.flush()
    document = Document(
        id=new_id("rdoc"),
        project_id=project.id,
        owner_id=owner,
        filename="revision.md",
        mime="text/markdown",
        size_bytes=len(BASE_TEXT.encode("utf-8")),
        content_hash=text_hash(BASE_TEXT),
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(document)
    await db.flush()
    version = DocumentVersion(
        id=new_id("rver"),
        document_id=document.id,
        version_no=1,
        content_hash=text_hash(BASE_TEXT),
        text=BASE_TEXT,
        codepoints=len(BASE_TEXT),
        parse_status="complete",
        page_count=1,
        source="upload",
        created_at=utcnow(),
    )
    db.add(version)
    await db.flush()
    document.current_version_id = version.id
    await db.commit()
    return {
        "owner": owner,
        "project_id": project.id,
        "document_id": document.id,
        "version_id": version.id,
    }


async def _proposal(
    db,
    env,
    hunks,
    *,
    report: dict | None = None,
    status: str = "proposed",
    owner: int | None = None,
    task_id: str = "rtask_revision_test",
) -> RevisionProposalRow:
    row = RevisionProposalRow(
        id=new_id("rprop"),
        task_id=task_id,
        owner_id=env["owner"] if owner is None else owner,
        base_version_id=env["version_id"],
        selected_findings=["rfnd_1"],
        hunks_json=hunks,
        validation_report=(
            report
            if report is not None
            else {
                "base_text_hash": text_hash(BASE_TEXT),
                "preserve": list(PRESERVE_DEFAULTS),
            }
        ),
        status=status,
        created_at=utcnow(),
    )
    db.add(row)
    await db.commit()
    return row


async def _version_count(db, document_id: str) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_apply_creates_new_version_blocks_and_change_log(
    db, research_store, rev_env
):
    actor = research_store.actor("a")
    row = await _proposal(
        db,
        rev_env,
        [_hunk(BASE_TEXT, "结论仍需谨慎", "结论仍需谨慎，并补充边界条件")],
    )

    result = await apply_proposal(
        db,
        actor,
        row.id,
        expected_version_id=rev_env["version_id"],
        idempotency_key="revision-apply-0001",
    )

    assert result.proposal_id == row.id
    assert result.document_id == rev_env["document_id"]
    assert result.new_version_id != rev_env["version_id"]
    assert result.applied_hunk_ids == ["hunk_1"]
    assert result.change_log_artifact_id.startswith("art_")

    new_version = (
        await db.execute(
            select(DocumentVersion).where(DocumentVersion.id == result.new_version_id)
        )
    ).scalar_one()
    assert new_version.version_no == 2
    assert "并补充边界条件" in new_version.text

    document = (
        await db.execute(
            select(Document).where(Document.id == rev_env["document_id"])
        )
    ).scalar_one()
    assert document.current_version_id == result.new_version_id
    assert document.content_hash == new_version.content_hash

    blocks = list(
        (
            await db.execute(
                select(DocumentBlock)
                .where(DocumentBlock.version_id == new_version.id)
                .order_by(DocumentBlock.ordinal)
            )
        )
        .scalars()
        .all()
    )
    assert blocks, "新版本必须重建块"
    for block in blocks:
        assert new_version.text[block.start : block.end] == block.text

    artifact = (
        await db.execute(
            select(Artifact).where(Artifact.id == result.change_log_artifact_id)
        )
    ).scalar_one()
    assert artifact.kind == "change_log"
    assert artifact.task_id == row.task_id
    assert artifact.validation_json["proposal_id"] == row.id
    assert artifact.validation_json["new_version_id"] == new_version.id

    await db.refresh(row)
    assert row.status == "applied"
    assert row.applied_version_id == new_version.id
    assert row.idempotency_key == "revision-apply-0001"


@pytest.mark.asyncio
async def test_apply_rejects_wrong_expected_version(db, research_store, rev_env):
    actor = research_store.actor("a")
    row = await _proposal(
        db, rev_env, [_hunk(BASE_TEXT, "结论仍需谨慎", "结论仍需谨慎，并补充边界条件")]
    )
    with pytest.raises(ResearchAPIError) as excinfo:
        await apply_proposal(
            db, actor, row.id, expected_version_id="rver_some_other_version"
        )
    error = _assert_error(excinfo, 409, "VERSION_CONFLICT")
    assert error.details["base_version_id"] == rev_env["version_id"]
    assert await _version_count(db, rev_env["document_id"]) == 1


@pytest.mark.asyncio
async def test_apply_rejects_when_document_moved_to_newer_version(
    db, research_store, rev_env
):
    actor = research_store.actor("a")
    newer = DocumentVersion(
        id=new_id("rver"),
        document_id=rev_env["document_id"],
        version_no=2,
        content_hash=text_hash(BASE_TEXT + "\n\n第三段：补充。"),
        text=BASE_TEXT + "\n\n第三段：补充。",
        codepoints=len(BASE_TEXT) + 8,
        parse_status="complete",
        page_count=1,
        source="revision",
        created_at=utcnow(),
    )
    db.add(newer)
    await db.flush()
    document = (
        await db.execute(
            select(Document).where(Document.id == rev_env["document_id"])
        )
    ).scalar_one()
    document.current_version_id = newer.id
    await db.commit()

    row = await _proposal(
        db, rev_env, [_hunk(BASE_TEXT, "结论仍需谨慎", "结论仍需谨慎，并补充边界条件")]
    )
    with pytest.raises(ResearchAPIError) as excinfo:
        await apply_proposal(
            db, actor, row.id, expected_version_id=rev_env["version_id"]
        )
    error = _assert_error(excinfo, 409, "VERSION_CONFLICT")
    assert error.details["current_version_id"] == newer.id


@pytest.mark.asyncio
async def test_apply_rejects_base_text_hash_mismatch(db, research_store, rev_env):
    actor = research_store.actor("a")
    row = await _proposal(
        db,
        rev_env,
        [_hunk(BASE_TEXT, "结论仍需谨慎", "结论仍需谨慎，并补充边界条件")],
        report={"base_text_hash": "f" * 64, "preserve": list(PRESERVE_DEFAULTS)},
    )
    with pytest.raises(ResearchAPIError) as excinfo:
        await apply_proposal(
            db, actor, row.id, expected_version_id=rev_env["version_id"]
        )
    _assert_error(excinfo, 409, "VERSION_CONFLICT")


@pytest.mark.asyncio
async def test_apply_replay_with_same_key_returns_same_result(
    db, research_store, rev_env
):
    actor = research_store.actor("a")
    row = await _proposal(
        db, rev_env, [_hunk(BASE_TEXT, "结论仍需谨慎", "结论仍需谨慎，并补充边界条件")]
    )
    first = await apply_proposal(
        db,
        actor,
        row.id,
        expected_version_id=rev_env["version_id"],
        idempotency_key="revision-replay-0001",
    )
    second = await apply_proposal(
        db,
        actor,
        row.id,
        expected_version_id=rev_env["version_id"],
        idempotency_key="revision-replay-0001",
    )
    assert second.model_dump() == first.model_dump()
    assert await _version_count(db, rev_env["document_id"]) == 2


@pytest.mark.asyncio
async def test_apply_twice_with_different_key_conflicts(db, research_store, rev_env):
    actor = research_store.actor("a")
    row = await _proposal(
        db, rev_env, [_hunk(BASE_TEXT, "结论仍需谨慎", "结论仍需谨慎，并补充边界条件")]
    )
    await apply_proposal(
        db,
        actor,
        row.id,
        expected_version_id=rev_env["version_id"],
        idempotency_key="revision-first-0001",
    )
    with pytest.raises(ResearchAPIError) as excinfo:
        await apply_proposal(
            db,
            actor,
            row.id,
            expected_version_id=rev_env["version_id"],
            idempotency_key="revision-second-0002",
        )
    _assert_error(excinfo, 409, "PROPOSAL_ALREADY_APPLIED")
    assert await _version_count(db, rev_env["document_id"]) == 2


@pytest.mark.asyncio
async def test_apply_rejects_invalid_proposal(db, research_store, rev_env):
    actor = research_store.actor("a")
    row = await _proposal(
        db,
        rev_env,
        [_hunk(BASE_TEXT, "结论仍需谨慎", "结论仍需谨慎，并补充边界条件")],
        status="invalid",
    )
    with pytest.raises(ResearchAPIError) as excinfo:
        await apply_proposal(
            db, actor, row.id, expected_version_id=rev_env["version_id"]
        )
    _assert_error(excinfo, 422, "PROPOSAL_INVALID")


@pytest.mark.asyncio
async def test_apply_rejects_unknown_hunk_ids(db, research_store, rev_env):
    actor = research_store.actor("a")
    row = await _proposal(
        db, rev_env, [_hunk(BASE_TEXT, "结论仍需谨慎", "结论仍需谨慎，并补充边界条件")]
    )
    with pytest.raises(ResearchAPIError) as excinfo:
        await apply_proposal(
            db,
            actor,
            row.id,
            expected_version_id=rev_env["version_id"],
            hunk_ids=["hunk_missing"],
        )
    error = _assert_error(excinfo, 422, "HUNK_NOT_FOUND")
    assert error.details["missing"] == ["hunk_missing"]


@pytest.mark.asyncio
async def test_apply_requires_hunks(db, research_store, rev_env):
    actor = research_store.actor("a")
    row = await _proposal(db, rev_env, [])
    with pytest.raises(ResearchAPIError) as excinfo:
        await apply_proposal(
            db, actor, row.id, expected_version_id=rev_env["version_id"]
        )
    _assert_error(excinfo, 422, "NO_HUNKS")


@pytest.mark.asyncio
async def test_apply_rejects_stale_hunks(db, research_store, rev_env):
    actor = research_store.actor("a")
    stale = _hunk(BASE_TEXT, "结论仍需谨慎", "结论仍需谨慎，并补充边界条件")
    stale["original_text"] = "一段已经不存在于基准版本的原文"
    stale["original_hash"] = text_hash(stale["original_text"])
    row = await _proposal(db, rev_env, [stale])
    with pytest.raises(ResearchAPIError) as excinfo:
        await apply_proposal(
            db, actor, row.id, expected_version_id=rev_env["version_id"]
        )
    error = _assert_error(excinfo, 422, "HUNK_VALIDATION_FAILED")
    assert error.details["issues"]


@pytest.mark.asyncio
async def test_apply_requires_expected_version(db, research_store, rev_env):
    actor = research_store.actor("a")
    row = await _proposal(
        db, rev_env, [_hunk(BASE_TEXT, "结论仍需谨慎", "结论仍需谨慎，并补充边界条件")]
    )
    with pytest.raises(ResearchAPIError) as excinfo:
        await apply_proposal(db, actor, row.id, expected_version_id="  ")
    _assert_error(excinfo, 422, "MISSING_EXPECTED_VERSION")


@pytest.mark.asyncio
async def test_apply_rejects_malformed_idempotency_key(db, research_store, rev_env):
    actor = research_store.actor("a")
    row = await _proposal(
        db, rev_env, [_hunk(BASE_TEXT, "结论仍需谨慎", "结论仍需谨慎，并补充边界条件")]
    )
    with pytest.raises(ResearchAPIError) as excinfo:
        await apply_proposal(
            db,
            actor,
            row.id,
            expected_version_id=rev_env["version_id"],
            idempotency_key="short",
        )
    _assert_error(excinfo, 422, "INVALID_IDEMPOTENCY_KEY")


@pytest.mark.asyncio
async def test_apply_other_users_proposal_is_404(db, research_store, rev_env):
    other = research_store.actor("b")
    row = await _proposal(
        db, rev_env, [_hunk(BASE_TEXT, "结论仍需谨慎", "结论仍需谨慎，并补充边界条件")]
    )
    with pytest.raises(ResearchAPIError) as excinfo:
        await apply_proposal(
            db, other, row.id, expected_version_id=rev_env["version_id"]
        )
    error = _assert_error(excinfo, 404, "NOT_FOUND")
    assert error.code == "NOT_FOUND"
    assert await _version_count(db, rev_env["document_id"]) == 1


def test_module_exports_apply_proposal_and_validate_hunks():
    assert revision_service.apply_proposal is apply_proposal
    assert revision_service.validate_hunks is validate_hunks
    assert revision_service.MAX_HUNK_CODEPOINTS == MAX_HUNK_CODEPOINTS
