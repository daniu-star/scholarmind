"""契约层验收测试（AT-004/AT-024/AT-034 的协议基础）。

只断言行为语义：非法组合必须被拒绝、默认值必须符合 PRD v1.0 §8、完成检查
只在 succeeded 时生效。不测试“字段是否存在”这类实现细节。
"""
from __future__ import annotations

import hashlib
import unicodedata
from datetime import datetime

import pytest
from pydantic import ValidationError

from ...research import contracts as c


# ── 枚举与状态机 ────────────────────────────────────────────


def test_schema_version_is_v1():
    assert c.SCHEMA_VERSION == "1.0"


def test_task_kinds_cover_all_prd_kinds():
    assert {kind.value for kind in c.TaskKind} == {
        "review",
        "revision",
        "draft_from_outline",
        "literature_review",
        "chart",
        "export",
    }


def test_terminal_statuses_are_exactly_four():
    assert c.TERMINAL_STATUSES == {
        c.TaskStatus.PARTIAL,
        c.TaskStatus.SUCCEEDED,
        c.TaskStatus.FAILED,
        c.TaskStatus.CANCELLED,
    }


@pytest.mark.parametrize(
    "current,target",
    [
        (c.TaskStatus.QUEUED, c.TaskStatus.RUNNING),
        (c.TaskStatus.QUEUED, c.TaskStatus.FAILED),
        (c.TaskStatus.QUEUED, c.TaskStatus.CANCELLED),
        (c.TaskStatus.RUNNING, c.TaskStatus.NEEDS_INPUT),
        (c.TaskStatus.RUNNING, c.TaskStatus.RECOVERABLE),
        (c.TaskStatus.RUNNING, c.TaskStatus.PARTIAL),
        (c.TaskStatus.RUNNING, c.TaskStatus.SUCCEEDED),
        (c.TaskStatus.RUNNING, c.TaskStatus.FAILED),
        (c.TaskStatus.RUNNING, c.TaskStatus.CANCELLED),
        (c.TaskStatus.NEEDS_INPUT, c.TaskStatus.QUEUED),
        (c.TaskStatus.NEEDS_INPUT, c.TaskStatus.PARTIAL),
        (c.TaskStatus.NEEDS_INPUT, c.TaskStatus.FAILED),
        (c.TaskStatus.NEEDS_INPUT, c.TaskStatus.CANCELLED),
        (c.TaskStatus.RECOVERABLE, c.TaskStatus.QUEUED),
        (c.TaskStatus.RECOVERABLE, c.TaskStatus.PARTIAL),
        (c.TaskStatus.RECOVERABLE, c.TaskStatus.FAILED),
        (c.TaskStatus.RECOVERABLE, c.TaskStatus.CANCELLED),
    ],
)
def test_allowed_transitions(current, target):
    assert c.can_transition(current, target) is True


@pytest.mark.parametrize(
    "current,target",
    [
        # queued 不能直接 succeeded/partial/needs_input
        (c.TaskStatus.QUEUED, c.TaskStatus.SUCCEEDED),
        (c.TaskStatus.QUEUED, c.TaskStatus.PARTIAL),
        (c.TaskStatus.QUEUED, c.TaskStatus.NEEDS_INPUT),
        (c.TaskStatus.QUEUED, c.TaskStatus.RECOVERABLE),
        # running 不能回到 queued
        (c.TaskStatus.RUNNING, c.TaskStatus.QUEUED),
        # 任何终态不可再转移（AT-039：终态不得被改成 succeeded）
        (c.TaskStatus.SUCCEEDED, c.TaskStatus.FAILED),
        (c.TaskStatus.SUCCEEDED, c.TaskStatus.CANCELLED),
        (c.TaskStatus.FAILED, c.TaskStatus.QUEUED),
        (c.TaskStatus.CANCELLED, c.TaskStatus.SUCCEEDED),
        (c.TaskStatus.PARTIAL, c.TaskStatus.SUCCEEDED),
        (c.TaskStatus.PARTIAL, c.TaskStatus.FAILED),
    ],
)
def test_illegal_transitions(current, target):
    assert c.can_transition(current, target) is False


def test_same_status_is_not_a_transition():
    for status in c.TaskStatus:
        assert c.can_transition(status, status) is False


def test_terminal_statuses_have_no_way_out():
    for status in c.TERMINAL_STATUSES:
        for target in c.TaskStatus:
            assert c.can_transition(status, target) is False


def test_event_terminal_status_mapping():
    assert c.EVENT_TERMINAL_STATUS == {
        c.EventType.TASK_COMPLETED: c.TaskStatus.SUCCEEDED,
        c.EventType.TASK_PARTIAL: c.TaskStatus.PARTIAL,
        c.EventType.TASK_FAILED: c.TaskStatus.FAILED,
        c.EventType.TASK_CANCELLED: c.TaskStatus.CANCELLED,
    }


def test_quality_verdict_kinds():
    assert c.QUALITY_VERDICT_KINDS == {
        c.TaskKind.REVIEW,
        c.TaskKind.REVISION,
        c.TaskKind.LITERATURE_REVIEW,
    }


# ── 基础工具函数 ────────────────────────────────────────────


def test_actor_requires_positive_int():
    assert c.Actor(user_id=1).user_id == 1
    for invalid in (0, -1):
        with pytest.raises(ValueError):
            c.Actor(user_id=invalid)


def test_actor_is_frozen():
    actor = c.Actor(user_id=3)
    with pytest.raises(Exception):
        actor.user_id = 4  # type: ignore[misc]


def test_new_id_has_prefix_and_unique_suffix():
    first = c.new_id("task")
    second = c.new_id("task")
    assert first.startswith("task_")
    assert len(first) > len("task_")
    assert first != second


def test_normalize_text_nfc():
    decomposed = unicodedata.normalize("NFD", "café")
    assert c.normalize_text(decomposed) == unicodedata.normalize("NFC", "café")
    assert c.normalize_text(decomposed) != decomposed


def test_text_hash_is_stable_across_normalization():
    composed = "café"
    decomposed = unicodedata.normalize("NFD", composed)
    assert c.text_hash(composed) == c.text_hash(decomposed)
    assert c.text_hash("abc") == hashlib.sha256(b"abc").hexdigest()


def test_content_hash_accepts_bytes_and_str():
    assert c.content_hash(b"abc") == c.content_hash("abc")
    assert len(c.content_hash("abc")) == 64


@pytest.mark.parametrize(
    "key",
    ["abc12345", "A.b_c:1-2", "x" * 128, "任务内容不参与"[:0] + "01234567"],
)
def test_valid_idempotency_keys(key):
    assert c.validate_idempotency_key(key) == key


@pytest.mark.parametrize(
    "key",
    [
        "short",  # 太短
        "x" * 129,  # 太长
        "has space123",  # 非法字符
        "中文中文中文中文",  # 非 ASCII
        "abc/12345",  # 非法字符
        "abc+12345",
    ],
)
def test_invalid_idempotency_keys(key):
    with pytest.raises(ValueError):
        c.validate_idempotency_key(key)


def test_idempotency_key_regex_boundaries():
    assert c.IDEMPOTENCY_KEY_RE.match("a" * 8) is not None
    assert c.IDEMPOTENCY_KEY_RE.match("a" * 7) is None
    assert c.IDEMPOTENCY_KEY_RE.match("a" * 128) is not None
    assert c.IDEMPOTENCY_KEY_RE.match("a" * 129) is None


def test_r0_limits_match_prd():
    assert c.MAX_FILE_BYTES == 20 * 1024 * 1024
    assert c.MAX_SKILL_IDS == 8
    assert c.MAX_PAGES == 200
    assert c.MAX_CODEPOINTS == 200_000
    assert c.DIMENSIONS == ("argument", "method", "evidence", "expression", "format")
    assert set(c.PRESERVE_DEFAULTS) == {
        "numbers",
        "dates",
        "names",
        "direct_quotes",
        "citations",
    }
    assert c.SUPPORTED_JOURNAL_STYLES == frozenset({"generic"})
    assert c.SUPPORTED_EXPORT_FORMATS == frozenset({"md", "docx"})


# ── TaskScope / TaskConstraints ─────────────────────────────


def test_task_scope_defaults_to_all_dimensions():
    scope = c.TaskScope()
    assert tuple(scope.dimensions) == c.DIMENSIONS
    assert scope.section_ids == []
    assert scope.finding_ids == []


def test_task_scope_rejects_empty_dimensions():
    with pytest.raises(ValidationError):
        c.TaskScope(dimensions=[])


def test_task_scope_rejects_unknown_dimensions():
    with pytest.raises(ValidationError):
        c.TaskScope(dimensions=["argument", "vibes"])


def test_task_scope_dedupes_dimensions_keeping_order():
    scope = c.TaskScope(dimensions=["format", "argument", "format"])
    assert scope.dimensions == ["format", "argument"]


def test_task_constraints_defaults():
    constraints = c.TaskConstraints()
    assert tuple(constraints.preserve) == c.PRESERVE_DEFAULTS
    assert constraints.target_word_count is None
    assert constraints.journal_style == "generic"
    assert constraints.no_new_empirical_claims is True


def test_task_constraints_rejects_unknown_preserve():
    with pytest.raises(ValidationError):
        c.TaskConstraints(preserve=["numbers", "vibes"])


def test_task_constraints_dedupes_preserve():
    assert c.TaskConstraints(preserve=["names", "names", "dates"]).preserve == [
        "names",
        "dates",
    ]


@pytest.mark.parametrize("count", [0, 1_000_001])
def test_task_constraints_target_word_count_bounds(count):
    with pytest.raises(ValidationError):
        c.TaskConstraints(target_word_count=count)


def test_task_constraints_accepts_max_word_count():
    assert c.TaskConstraints(target_word_count=1_000_000).target_word_count == 1_000_000


# ── ResearchTaskInput（AT-004 显式空 Skill 契约 / AT-024 输入快照）──


def _task_body(**overrides) -> dict:
    body = {
        "project_id": "p1",
        "kind": "review",
        "objective": "检查全文",
        "input": {"document_version_id": "v1"},
    }
    body.update(overrides)
    return body


def test_minimal_task_input_valid():
    payload = c.ResearchTaskInput(**_task_body())
    assert payload.schema_version == "1.0"
    assert payload.kind is c.TaskKind.REVIEW
    assert payload.skill_ids == []


def test_task_input_objective_is_stripped():
    assert c.ResearchTaskInput(**_task_body(objective="  有效目标  ")).objective == "有效目标"


@pytest.mark.parametrize("objective", ["", "   ", "\n\t "])
def test_task_input_rejects_blank_objective(objective):
    with pytest.raises(ValidationError):
        c.ResearchTaskInput(**_task_body(objective=objective))


def test_task_input_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        c.ResearchTaskInput(**_task_body(owner_id=999))


def test_task_input_rejects_wrong_schema_version():
    with pytest.raises(ValidationError):
        c.ResearchTaskInput(**_task_body(schema_version="2.0"))


def test_task_input_rejects_too_many_skills():
    with pytest.raises(ValidationError):
        c.ResearchTaskInput(**_task_body(skill_ids=[f"s{i}" for i in range(9)]))


def test_task_input_rejects_duplicate_skills():
    with pytest.raises(ValidationError):
        c.ResearchTaskInput(**_task_body(skill_ids=["s1", "s1"]))


def test_task_input_accepts_explicit_empty_skills():
    payload = c.ResearchTaskInput(**_task_body(skill_ids=[]))
    assert payload.skill_ids == []


def test_task_input_accepts_max_skills():
    payload = c.ResearchTaskInput(
        **_task_body(skill_ids=[f"s{i}" for i in range(8)])
    )
    assert len(payload.skill_ids) == 8


def test_revision_requires_finding_or_section_ids():
    with pytest.raises(ValidationError):
        c.ResearchTaskInput(**_task_body(kind="revision"))


def test_revision_accepts_finding_ids():
    payload = c.ResearchTaskInput(
        **_task_body(kind="revision", scope={"finding_ids": ["f1"]})
    )
    assert payload.kind is c.TaskKind.REVISION


def test_revision_accepts_section_ids():
    payload = c.ResearchTaskInput(
        **_task_body(kind="revision", scope={"section_ids": ["sec-3"]})
    )
    assert payload.scope.section_ids == ["sec-3"]


def test_target_word_count_rejected_for_review():
    with pytest.raises(ValidationError):
        c.ResearchTaskInput(
            **_task_body(constraints={"target_word_count": 3000})
        )


def test_target_word_count_allowed_for_draft():
    payload = c.ResearchTaskInput(
        **_task_body(
            kind="draft_from_outline",
            input={
                "document_version_id": "v1",
                "outline_document_version_id": "v2",
            },
            constraints={"target_word_count": 3000},
        )
    )
    assert payload.constraints.target_word_count == 3000


def test_draft_requires_outline_version():
    with pytest.raises(ValidationError):
        c.ResearchTaskInput(**_task_body(kind="draft_from_outline"))


def test_draft_with_outline_is_valid():
    payload = c.ResearchTaskInput(
        **_task_body(
            kind="draft_from_outline",
            input={
                "document_version_id": "v1",
                "outline_document_version_id": "v2",
            },
        )
    )
    assert payload.input.outline_document_version_id == "v2"


def test_mode_accepts_flash_and_pro_only():
    assert c.ResearchTaskInput(**_task_body(mode="flash")).mode == "flash"
    assert c.ResearchTaskInput(**_task_body(mode="pro")).mode == "pro"
    with pytest.raises(ValidationError):
        c.ResearchTaskInput(**_task_body(mode="turbo"))


def test_input_refs_requires_document_version_id():
    with pytest.raises(ValidationError):
        c.TaskInputRefs()


def test_input_refs_source_ids_max_200():
    assert len(c.TaskInputRefs(document_version_id="v1", source_ids=["s"] * 200).source_ids) == 200
    with pytest.raises(ValidationError):
        c.TaskInputRefs(document_version_id="v1", source_ids=["s"] * 201)


def test_task_input_serializes_for_snapshot():
    """AT-024：执行输入必须能原样序列化进任务快照。"""
    payload = c.ResearchTaskInput(
        **_task_body(
            kind="draft_from_outline",
            input={
                "document_version_id": "v1",
                "outline_document_version_id": "v2",
            },
            constraints={"target_word_count": 2500, "journal_style": "generic"},
            skill_ids=["s1"],
        )
    )
    dumped = payload.model_dump(mode="json")
    assert dumped["constraints"]["target_word_count"] == 2500
    assert dumped["skill_ids"] == ["s1"]
    assert dumped["input"]["document_version_id"] == "v1"
    assert dumped["input"]["outline_document_version_id"] == "v2"


# ── ResumeInput ─────────────────────────────────────────────


def test_resume_input_defaults():
    payload = c.ResumeInput(expected_state_revision=2)
    assert payload.answers == {}
    assert payload.supplemental_source_ids == []


def test_resume_input_requires_state_revision_positive():
    with pytest.raises(ValidationError):
        c.ResumeInput(expected_state_revision=0)


def test_resume_input_limits_answer_length():
    payload = c.ResumeInput(
        expected_state_revision=1, answers={"q": "x" * 50_000}
    )
    assert len(payload.answers["q"]) == 50_000
    with pytest.raises(ValidationError):
        c.ResumeInput(expected_state_revision=1, answers={"q": "x" * 50_001})


def test_resume_input_forbids_extra():
    with pytest.raises(ValidationError):
        c.ResumeInput(expected_state_revision=1, bogus=True)


# ── Coverage / TaskResult（AT-034 交付检查的数据基础）─────────


def test_coverage_defaults():
    coverage = c.Coverage()
    assert coverage.parse_status is c.ParseStatus.COMPLETE
    assert coverage.expected_eligible_blocks == 0
    assert coverage.analysis_ratio == 1.0
    assert coverage.full_coverage is False  # 预期块为 0 不能证明已读全文


def test_coverage_ratio_and_full_coverage():
    coverage = c.Coverage(expected_eligible_blocks=4, analyzed_eligible_blocks=4)
    assert coverage.analysis_ratio == 1.0
    assert coverage.full_coverage is True


def test_coverage_partial_ratio_not_full():
    coverage = c.Coverage(expected_eligible_blocks=4, analyzed_eligible_blocks=3)
    assert coverage.analysis_ratio == 0.75
    assert coverage.full_coverage is False


def test_coverage_unsupported_is_not_full():
    coverage = c.Coverage(
        parse_status=c.ParseStatus.UNSUPPORTED,
        expected_eligible_blocks=3,
        analyzed_eligible_blocks=3,
    )
    assert coverage.full_coverage is False


def test_coverage_rejects_analyzed_over_expected():
    with pytest.raises(ValidationError):
        c.Coverage(expected_eligible_blocks=1, analyzed_eligible_blocks=2)


def test_task_result_defaults():
    result = c.TaskResult(task_id="t1", status=c.TaskStatus.QUEUED)
    assert result.schema_version == "1.0"
    assert result.artifact_ids == []
    assert result.quality_verdict is None


def test_task_result_verdict_only_for_succeeded():
    with pytest.raises(ValidationError):
        c.TaskResult(
            task_id="t1",
            status=c.TaskStatus.PARTIAL,
            quality_verdict=c.QualityVerdict.ISSUES_FOUND,
        )


def test_task_result_succeeded_may_carry_verdict():
    result = c.TaskResult(
        task_id="t1",
        status=c.TaskStatus.SUCCEEDED,
        quality_verdict=c.QualityVerdict.NO_MAJOR_ISSUES_FOUND,
    )
    assert result.quality_verdict is c.QualityVerdict.NO_MAJOR_ISSUES_FOUND


def test_task_result_insufficient_evidence_requires_unresolved_items():
    with pytest.raises(ValidationError):
        c.TaskResult(
            task_id="t1",
            status=c.TaskStatus.SUCCEEDED,
            quality_verdict=c.QualityVerdict.INSUFFICIENT_EVIDENCE,
        )
    result = c.TaskResult(
        task_id="t1",
        status=c.TaskStatus.SUCCEEDED,
        quality_verdict=c.QualityVerdict.INSUFFICIENT_EVIDENCE,
        unresolved_items=["无法获取第 2 节全文"],
    )
    assert result.unresolved_items == ["无法获取第 2 节全文"]


# ── Finding / RevisionHunk / Proposal ───────────────────────


def _finding(**overrides) -> dict:
    body = {
        "id": "f1",
        "task_id": "t1",
        "version_id": "v1",
        "scope": "local",
        "category": "argument",
        "severity": "major",
        "problem": "论点缺少证据",
        "locator": {"block_id": "b1", "start": 0, "end": 10},
        "quote": "因此可以证明",
    }
    body.update(overrides)
    return body


def test_local_finding_requires_locator():
    body = _finding()
    body.pop("locator")
    with pytest.raises(ValidationError):
        c.Finding(**body)


def test_local_finding_requires_quote():
    body = _finding()
    body.pop("quote")
    with pytest.raises(ValidationError):
        c.Finding(**body)


def test_local_finding_rejects_blank_quote():
    with pytest.raises(ValidationError):
        c.Finding(**_finding(quote="   "))


def test_document_finding_requires_checked_sections():
    with pytest.raises(ValidationError):
        c.Finding(**_finding(scope="document", locator=None, quote=None))
    finding = c.Finding(
        **_finding(scope="document", locator=None, quote=None, checked_sections=["1", "2"])
    )
    assert finding.checked_sections == ["1", "2"]


def test_finding_ids_required():
    body = _finding()
    body.pop("id")
    with pytest.raises(ValidationError):
        c.Finding(**body)


def test_valid_local_finding():
    finding = c.Finding(**_finding())
    assert finding.scope is c.FindingScope.LOCAL
    assert finding.severity is c.Severity.MAJOR


def _hunk(text: str = "原文", **overrides) -> dict:
    body = {
        "id": "h1",
        "finding_id": "f1",
        "start": 0,
        "end": len(text),
        "original_text": text,
        "original_hash": c.text_hash(text),
        "replacement_text": "替换",
    }
    body.update(overrides)
    # 允许调用方只替换 original_text；哈希/区间默认跟随最终原文，避免测试自身构造错误。
    if "original_hash" not in overrides:
        body["original_hash"] = c.text_hash(body["original_text"])
    if "end" not in overrides:
        body["end"] = len(body["original_text"])
    return body


def test_valid_hunk():
    hunk = c.RevisionHunk(**_hunk())
    assert hunk.original_hash == c.text_hash("原文")


def test_hunk_rejects_hash_mismatch():
    with pytest.raises(ValidationError) as excinfo:
        c.RevisionHunk(**_hunk(original_hash="0" * 64))
    assert "哈希" in str(excinfo.value)


def test_hunk_rejects_reversed_offsets():
    with pytest.raises(ValidationError):
        c.RevisionHunk(**_hunk(start=5, end=2, original_hash=c.text_hash("原文")))


def test_hunk_rejects_negative_offsets():
    with pytest.raises(ValidationError):
        c.RevisionHunk(**_hunk(start=-1))


def test_hunk_hash_uses_nfc_normalization():
    decomposed = unicodedata.normalize("NFD", "café")
    hunk = c.RevisionHunk(**_hunk(original_text=decomposed))
    assert hunk.original_hash == c.text_hash("café")


def test_revision_proposal_defaults():
    proposal = c.RevisionProposal(
        id="p1",
        task_id="t1",
        base_version_id="v1",
        hunks=[c.RevisionHunk(**_hunk())],
    )
    assert proposal.status == "proposed"
    assert proposal.selected_findings == []


def test_apply_result_requires_state_revision():
    with pytest.raises(ValidationError):
        c.ApplyResult(
            proposal_id="p1",
            document_id="d1",
            new_version_id="v2",
            applied_hunk_ids=["h1"],
            state_revision=0,
        )


# ── 快照 / 事件 / 成果 / 错误 / 能力 ────────────────────────


def test_task_snapshot_defaults():
    snapshot = c.TaskSnapshot(
        id="t1",
        owner_id=1,
        project_id="p1",
        kind=c.TaskKind.REVIEW,
        status=c.TaskStatus.QUEUED,
        objective="目标",
        state_revision=1,
        billing_group_id="bg1",
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    assert snapshot.can_resume is False
    assert snapshot.can_retry is False
    assert snapshot.attempt_no == 0


def test_task_snapshot_rejects_zero_state_revision():
    with pytest.raises(ValidationError):
        c.TaskSnapshot(
            id="t1",
            owner_id=1,
            project_id="p1",
            kind=c.TaskKind.REVIEW,
            status=c.TaskStatus.QUEUED,
            objective="目标",
            state_revision=0,
            billing_group_id="bg1",
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
        )


def _event(**overrides) -> dict:
    body = {
        "task_id": "t1",
        "sequence": 1,
        "attempt_no": 0,
        "created_at": datetime(2026, 1, 1),
        "type": "task.accepted",
    }
    body.update(overrides)
    return body


def test_event_tool_completed_requires_persisted_id():
    with pytest.raises(ValidationError):
        c.TaskEventDTO(**_event(type="tool.completed", payload={"tool": "search"}))
    event = c.TaskEventDTO(
        **_event(type="tool.completed", payload={"evidence_id": "e1"})
    )
    assert event.payload["evidence_id"] == "e1"


def test_event_task_completed_requires_artifact_ids():
    with pytest.raises(ValidationError):
        c.TaskEventDTO(**_event(type="task.completed", payload={}))
    event = c.TaskEventDTO(
        **_event(type="task.completed", payload={"artifact_ids": ["a1"]})
    )
    assert event.payload["artifact_ids"] == ["a1"]


def test_event_sequence_must_start_at_one():
    with pytest.raises(ValidationError):
        c.TaskEventDTO(**_event(sequence=0))


def test_artifact_ref_defaults():
    artifact = c.ArtifactRef(
        id="a1",
        owner_id=1,
        task_id="t1",
        kind="review_report",
        content_hash="x" * 64,
        mime="application/json",
        filename="report.json",
        size_bytes=10,
    )
    assert artifact.downloadable is True
    assert artifact.version == 1
    with pytest.raises(ValidationError):
        c.ArtifactRef(
            id="a1",
            owner_id=1,
            task_id="t1",
            kind="review_report",
            version=0,
            content_hash="x" * 64,
            mime="application/json",
            filename="report.json",
            size_bytes=10,
        )


def test_research_error_defaults():
    error = c.ResearchError(code="NOT_FOUND", message="不存在")
    assert error.retryable is False
    assert error.details == {}


def test_task_accepted_defaults():
    accepted = c.TaskAccepted(task_id="t1")
    assert accepted.status is c.TaskStatus.QUEUED
    assert accepted.state_revision == 1
    assert accepted.billing_state is c.BillingState.RESERVED


def test_capability_status_values():
    assert {status.value for status in c.CapabilityStatus} == {
        "ready",
        "degraded",
        "disabled",
        "unauthorized",
        "unknown",
    }


def test_capability_response_default_disclaimer():
    response = c.CapabilityResponse(
        user_id=1,
        capabilities=[
            c.CapabilityInfo(
                name="model_bridge",
                status=c.CapabilityStatus.UNKNOWN,
                checked_at=datetime(2026, 1, 1),
            )
        ],
    )
    assert response.disclaimer
    assert "不构成发表保证" in response.disclaimer


def test_capability_info_rejects_invalid_status():
    with pytest.raises(ValidationError):
        c.CapabilityInfo(
            name="model_bridge",
            status="totally_ready",
            checked_at=datetime(2026, 1, 1),
        )


def test_required_artifact_kinds_mapping():
    assert c.REQUIRED_ARTIFACT_KINDS == {
        c.TaskKind.REVIEW: frozenset({"review_report"}),
        c.TaskKind.REVISION: frozenset({"revision_proposal"}),
        c.TaskKind.DRAFT_FROM_OUTLINE: frozenset({"draft"}),
        c.TaskKind.LITERATURE_REVIEW: frozenset({"literature_review"}),
        c.TaskKind.CHART: frozenset({"chart"}),
        c.TaskKind.EXPORT: frozenset({"export"}),
    }


# ── completion_errors：AT-034 的判定核心 ────────────────────


def _review_result(**overrides) -> c.TaskResult:
    body = {
        "task_id": "t1",
        "status": c.TaskStatus.SUCCEEDED,
        "coverage": c.Coverage(
            expected_eligible_blocks=3, analyzed_eligible_blocks=3
        ),
        "quality_verdict": c.QualityVerdict.ISSUES_FOUND,
    }
    body.update(overrides)
    return c.TaskResult(**body)


def test_completion_errors_ignores_non_succeeded():
    result = c.TaskResult(task_id="t1", status=c.TaskStatus.FAILED)
    assert c.completion_errors(c.TaskKind.REVIEW, result, set()) == []


def test_completion_errors_success_without_artifact():
    errors = c.completion_errors(c.TaskKind.REVIEW, _review_result(), set())
    assert errors, "succeeded 但没有任何成果时必须报错"
    assert any("review_report" in message for message in errors)


def test_completion_errors_success_with_artifact_is_clean():
    errors = c.completion_errors(
        c.TaskKind.REVIEW, _review_result(), {"review_report"}
    )
    assert errors == []


def test_completion_errors_review_requires_coverage():
    result = _review_result(coverage=None)
    errors = c.completion_errors(c.TaskKind.REVIEW, result, {"review_report"})
    assert errors


def test_completion_errors_review_requires_full_coverage():
    result = _review_result(
        coverage=c.Coverage(expected_eligible_blocks=3, analyzed_eligible_blocks=2)
    )
    errors = c.completion_errors(c.TaskKind.REVIEW, result, {"review_report"})
    assert errors


def test_completion_errors_review_rejects_zero_blocks():
    result = _review_result(
        coverage=c.Coverage(expected_eligible_blocks=0, analyzed_eligible_blocks=0)
    )
    errors = c.completion_errors(c.TaskKind.REVIEW, result, {"review_report"})
    assert errors


def test_completion_errors_review_requires_verdict():
    result = _review_result(quality_verdict=None)
    errors = c.completion_errors(c.TaskKind.REVIEW, result, {"review_report"})
    assert errors


def test_completion_errors_revision_requires_proposal():
    result = c.TaskResult(task_id="t1", status=c.TaskStatus.SUCCEEDED)
    errors = c.completion_errors(c.TaskKind.REVISION, result, {"draft"})
    assert errors


def test_completion_errors_draft_requires_draft_artifact():
    result = c.TaskResult(task_id="t1", status=c.TaskStatus.SUCCEEDED)
    assert c.completion_errors(c.TaskKind.DRAFT_FROM_OUTLINE, result, set())
    assert (
        c.completion_errors(c.TaskKind.DRAFT_FROM_OUTLINE, result, {"draft"}) == []
    )


def test_completion_errors_chart_and_export_require_artifact():
    result = c.TaskResult(task_id="t1", status=c.TaskStatus.SUCCEEDED)
    assert c.completion_errors(c.TaskKind.CHART, result, set())
    assert c.completion_errors(c.TaskKind.EXPORT, result, set())
