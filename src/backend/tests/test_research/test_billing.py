"""额度预留/结算/释放与幂等（R0：AT-038、AT-039、AT-040、AT-042）。

断言的是**账本与任务行的最终状态**：402 之前不得有任何任务行/预留行/事件/
outbox；成功受理必须恰好一条 reserve 操作；settle / release 必须幂等；
释放必须把消耗的额度真的退回去；不同任务不得共享同一个 active 预留。
"""
from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from ...models.orm import UserQuota
from ...research.billing_service import (
    CAPABILITY_BY_KIND,
    release,
    reservation_for_task,
    reserve,
    settle,
)
from ...research.contracts import (
    EventType,
    ResearchTaskInput,
    TaskKind,
    new_id,
    utcnow,
)
from ...research.errors import ResearchAPIError
from ...research.models import (
    BillingOperation,
    Document,
    DocumentVersion,
    FindingRow,
    OutboxMessage,
    Project,
    ResearchTask,
    TaskEvent,
)
from ...research.task_service import compute_request_fingerprint, create_task
from ...services.entitlement_service import EntitlementService

def _value(state):
    return getattr(state, "value", state)


def _payload(kind: str = "review", **overrides) -> dict:
    payload = {
        "project_id": "rproj_billing_test",
        "kind": kind,
        "objective": "检查全文论证与证据问题",
        "input": {"document_version_id": "rver_billing_test"},
        "scope": {},
        "constraints": {},
    }
    payload.update(overrides)
    return payload


def _draft_payload() -> dict:
    return _payload(
        "draft_from_outline",
        input={
            "document_version_id": "rver_billing_test",
            "outline_document_version_id": "rver_outline_test",
        },
        constraints={"target_word_count": 3000},
    )


def _revision_payload() -> dict:
    return _payload("revision", scope={"finding_ids": ["rfnd_billing_test"]})


async def _seed_completed_finding(db, owner: int, project_id: str, version_id: str) -> str:
    """种一条已完成诊断任务 + 诊断项，供修改任务在受理前校验 finding 归属。"""
    task_id = "rtask_billing_seed"
    db.add(
        ResearchTask(
            id=task_id,
            owner_id=owner,
            project_id=project_id,
            kind="review",
            status="succeeded",
            objective="计费夹具诊断任务",
            billing_group_id="bg_billing_seed",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    await db.flush()
    db.add(
        FindingRow(
            id="rfnd_billing_test",
            task_id=task_id,
            owner_id=owner,
            version_id=version_id,
            category="argument",
            severity="major",
            problem="夹具诊断项",
            reason="夹具",
            recommendation="夹具",
            evidence_refs=[],
            locator={"start": 0, "end": 2, "version_id": version_id},
            checked_sections=[],
            verification_method="model",
            created_at=utcnow(),
        )
    )
    await db.commit()
    return task_id


def _fingerprint(payload: dict) -> str:
    return compute_request_fingerprint(ResearchTaskInput.model_validate(payload))


async def _quota(db, user_id: int) -> UserQuota:
    await EntitlementService.ensure_quota(db, user_id)
    row = (
        await db.execute(select(UserQuota).where(UserQuota.user_id == user_id))
    ).scalar_one()
    return row


async def _grant(db, user_id: int, **values) -> None:
    row = await _quota(db, user_id)
    for key, value in values.items():
        setattr(row, key, value)
    await db.commit()


@pytest_asyncio.fixture(autouse=True)
async def _seed_task_inputs(db, research_store):
    """受理前会校验项目/版本归属：给所有计费用例种一套最小输入。

    这些行只用于满足 ``_require_owned_inputs``（项目 + 正文版本 + 提纲版本），
    不参与本项目对账本/事件/outbox 的断言。
    """
    owner = research_store.user_ids["a"]
    # 注意：必须保留 ORM 对象引用并显式 flush，否则 pending 对象可能在
    # commit 前被回收，导致子表先插入而触发外键失败。
    project = Project(
        id="rproj_billing_test",
        owner_id=owner,
        title="计费夹具项目",
        status="active",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(project)
    await db.flush()
    document = Document(
        id="rdoc_billing_test",
        project_id=project.id,
        owner_id=owner,
        filename="billing.md",
        mime="text/markdown",
        size_bytes=8,
        content_hash="0" * 64,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(document)
    await db.flush()
    body_version = DocumentVersion(
        id="rver_billing_test",
        document_id=document.id,
        version_no=1,
        content_hash="0" * 64,
        text="正文内容",
        codepoints=4,
        parse_status="complete",
        page_count=1,
        source="upload",
        created_at=utcnow(),
    )
    outline_version = DocumentVersion(
        id="rver_outline_test",
        document_id=document.id,
        version_no=2,
        content_hash="1" * 64,
        text="提纲",
        codepoints=2,
        parse_status="complete",
        page_count=1,
        source="upload",
        created_at=utcnow(),
    )
    db.add_all([body_version, outline_version])
    await db.flush()
    # 用户 B 的等价输入（跨用户用例不能复用 A 的项目/版本）。
    other = research_store.user_ids["b"]
    project_b = Project(
        id="rproj_billing_test_b",
        owner_id=other,
        title="计费夹具项目 B",
        status="active",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(project_b)
    await db.flush()
    document_b = Document(
        id="rdoc_billing_test_b",
        project_id=project_b.id,
        owner_id=other,
        filename="billing_b.md",
        mime="text/markdown",
        size_bytes=8,
        content_hash="2" * 64,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(document_b)
    await db.flush()
    db.add(
        DocumentVersion(
            id="rver_billing_test_b",
            document_id=document_b.id,
            version_no=1,
            content_hash="2" * 64,
            text="正文内容",
            codepoints=4,
            parse_status="complete",
            page_count=1,
            source="upload",
            created_at=utcnow(),
        )
    )
    await db.commit()
    yield


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def _load_task(db, task_id: str) -> ResearchTask:
    return (
        await db.execute(select(ResearchTask).where(ResearchTask.id == task_id))
    ).scalar_one()


async def _events(db, task_id: str) -> list[TaskEvent]:
    return list(
        (
            await db.execute(
                select(TaskEvent)
                .where(TaskEvent.task_id == task_id)
                .order_by(TaskEvent.sequence)
            )
        )
        .scalars()
        .all()
    )


async def _billing_rows(db, owner_id: int) -> list[BillingOperation]:
    return list(
        (
            await db.execute(
                select(BillingOperation)
                .where(BillingOperation.owner_id == owner_id)
                .order_by(BillingOperation.created_at)
            )
        )
        .scalars()
        .all()
    )


# ── 映射表 ────────────────────────────────────────────────


def test_capability_mapping_is_fixed_for_all_kinds():
    assert _value(CAPABILITY_BY_KIND[TaskKind.REVIEW]) == "external_review"
    assert _value(CAPABILITY_BY_KIND[TaskKind.LITERATURE_REVIEW]) == "external_review"
    assert _value(CAPABILITY_BY_KIND[TaskKind.REVISION]) == "modification"
    assert _value(CAPABILITY_BY_KIND[TaskKind.DRAFT_FROM_OUTLINE]) == "generation"
    assert CAPABILITY_BY_KIND[TaskKind.CHART] is None
    assert CAPABILITY_BY_KIND[TaskKind.EXPORT] is None


# ── 402：受理失败必须整体回滚（AT-042） ────────────────────


@pytest.mark.asyncio
async def test_free_user_review_rejected_402_before_any_row(db, research_store):
    actor = research_store.actor("a")
    with pytest.raises(ResearchAPIError) as excinfo:
        await create_task(db, actor, _payload("review"), idempotency_key=None)
    err = excinfo.value
    assert (err.status_code, err.code) == (402, "PAYMENT_REQUIRED")
    assert err.details.get("capability") == "external_review"

    # 失败不得留下任务行、事件、outbox、预留行。
    assert await _count(db, ResearchTask) == 0
    assert await _count(db, TaskEvent) == 0
    assert await _count(db, OutboxMessage) == 0
    assert await _count(db, BillingOperation) == 0


@pytest.mark.asyncio
async def test_revision_and_draft_report_their_own_capability(db, research_store):
    actor = research_store.actor("a")
    await _seed_completed_finding(
        db, actor.user_id, "rproj_billing_test", "rver_billing_test"
    )

    with pytest.raises(ResearchAPIError) as revision_error:
        await create_task(db, actor, _revision_payload())
    assert revision_error.value.status_code == 402
    assert revision_error.value.details.get("capability") == "modification"

    with pytest.raises(ResearchAPIError) as draft_error:
        await create_task(db, actor, _draft_payload())
    assert draft_error.value.status_code == 402
    assert draft_error.value.details.get("capability") == "generation"


# ── 成功受理的账本（AT-038/AT-040） ───────────────────────


@pytest.mark.asyncio
async def test_generation_credit_reserved_exactly_once(db, research_store):
    owner = research_store.user_ids["a"]
    actor = research_store.actor("a")
    await _grant(db, owner, generation_credits=1)

    accepted = await create_task(
        db, actor, _draft_payload(), idempotency_key="billing-draft-0001"
    )
    assert _value(accepted.billing_state) == "reserved"

    task = await _load_task(db, accepted.task_id)
    assert _value(task.billing_state) == "reserved"
    assert task.billing_group_id

    rows = await _billing_rows(db, owner)
    assert len(rows) == 1
    assert rows[0].operation == "reserve:1"
    assert rows[0].state == "reserved"
    assert rows[0].amount_units == 1
    assert rows[0].entitlement == "generation"
    assert rows[0].billing_group_id == task.billing_group_id

    quota = await _quota(db, owner)
    assert quota.generation_credits == 0  # 已消耗一个额度

    events = await _events(db, accepted.task_id)
    assert [event.sequence for event in events] == [1]
    assert _value(events[0].type) == EventType.TASK_ACCEPTED.value
    assert await _count(db, OutboxMessage) == 1


@pytest.mark.asyncio
async def test_settle_is_idempotent_and_marks_reservation(db, research_store):
    owner = research_store.user_ids["a"]
    actor = research_store.actor("a")
    await _grant(db, owner, generation_credits=1)
    accepted = await create_task(
        db, actor, _draft_payload(), idempotency_key="billing-settle-0001"
    )
    task = await _load_task(db, accepted.task_id)
    reservation = await reservation_for_task(db, task)
    assert reservation["operation"] == "reserve:1"

    await settle(db, task, reservation)
    await db.commit()
    rows = await _billing_rows(db, owner)
    assert [row.operation for row in rows] == ["reserve:1", "settle"]
    assert rows[0].state == "settled"
    assert rows[1].state == "settled"
    assert _value(task.billing_state) == "settled"
    assert (await _quota(db, owner)).generation_credits == 0  # 结算不退款

    # 重复结算：不新增行、状态不变。
    again = await reservation_for_task(db, task)
    await settle(db, task, again)
    await db.commit()
    assert len(await _billing_rows(db, owner)) == 2
    assert _value(task.billing_state) == "settled"


@pytest.mark.asyncio
async def test_release_refunds_once_and_is_idempotent(db, research_store):
    owner = research_store.user_ids["a"]
    actor = research_store.actor("a")
    await _grant(db, owner, generation_credits=1)
    accepted = await create_task(
        db, actor, _draft_payload(), idempotency_key="billing-release-0001"
    )
    task = await _load_task(db, accepted.task_id)
    reservation = await reservation_for_task(db, task)

    await release(db, task, reservation)
    await db.commit()
    assert _value(task.billing_state) == "released"
    rows = await _billing_rows(db, owner)
    assert [row.operation for row in rows] == ["reserve:1", "release:1"]
    assert rows[0].state == "released"
    assert rows[1].state == "released"
    assert rows[1].amount_units == 0
    quota = await _quota(db, owner)
    assert quota.generation_credits == 1  # 额度退回

    # 重复释放：不重复退款、不新增行（AT-042）。
    again = await reservation_for_task(db, task)
    await release(db, task, again)
    await db.commit()
    assert len(await _billing_rows(db, owner)) == 2
    assert (await _quota(db, owner)).generation_credits == 1


@pytest.mark.asyncio
async def test_membership_unlimited_release_does_not_touch_expiry(db, research_store):
    owner = research_store.user_ids["a"]
    actor = research_store.actor("a")
    expiry = utcnow() + timedelta(days=30)
    await _grant(
        db,
        owner,
        membership_expires_at=expiry,
        external_review_expires_at=expiry,
    )
    accepted = await create_task(
        db, actor, _payload("review"), idempotency_key="billing-member-0001"
    )
    task = await _load_task(db, accepted.task_id)
    reservation = await reservation_for_task(db, task)
    assert reservation["consumed"] == "unlimited"
    assert reservation["operation"] == "reserve:1"

    before = (await _quota(db, owner)).membership_expires_at
    await release(db, task, reservation)
    await db.commit()
    assert (await _quota(db, owner)).membership_expires_at == before


@pytest.mark.asyncio
async def test_external_subscription_recorded_in_note(db, research_store):
    owner = research_store.user_ids["a"]
    actor = research_store.actor("a")
    await _grant(
        db, owner, external_review_expires_at=utcnow() + timedelta(days=30)
    )
    accepted = await create_task(
        db, actor, _payload("review"), idempotency_key="billing-reviewsub-0001"
    )
    reservation = await reservation_for_task(
        db, await _load_task(db, accepted.task_id)
    )
    assert reservation["consumed"] == "external_subscription"
    rows = await _billing_rows(db, owner)
    assert len(rows) == 1
    assert "external_subscription" in (rows[0].note or "")


@pytest.mark.asyncio
async def test_chart_and_export_need_no_entitlement_and_write_no_ledger(
    db, research_store
):
    actor = research_store.actor("a")
    with pytest.raises(ResearchAPIError):
        # 先确认：同一用户此时没有任何额度。
        await create_task(db, actor, _payload("review"))

    # chart 与 export 都是免费路径：各自属于不同用户，避免撞上“每用户 1 个活跃任务”。
    for who, kind in (("a", "chart"), ("b", "export")):
        payload = _payload(kind)
        if who == "b":
            payload["project_id"] = "rproj_billing_test_b"
            payload["input"] = {"document_version_id": "rver_billing_test_b"}
        accepted = await create_task(
            db,
            research_store.actor(who),
            payload,
            idempotency_key=f"billing-noent-{who}-{kind}",
        )
        task = await _load_task(db, accepted.task_id)
        assert _value(task.billing_state) == "released"
        assert accepted.billing_state is not None
    assert await _count(db, BillingOperation) == 0


# ── 幂等重放与额度不被重复预留（AT-038/AT-040） ────────────


@pytest.mark.asyncio
async def test_same_idempotency_key_replays_without_second_reservation(
    db, research_store
):
    owner = research_store.user_ids["a"]
    actor = research_store.actor("a")
    await _grant(db, owner, generation_credits=2)

    first = await create_task(
        db, actor, _draft_payload(), idempotency_key="billing-replay-0001"
    )
    second = await create_task(
        db, actor, _draft_payload(), idempotency_key="billing-replay-0001"
    )
    assert second.task_id == first.task_id
    assert second.state_revision == first.state_revision
    assert await _count(db, ResearchTask) == 1
    assert len(await _billing_rows(db, owner)) == 1
    assert (await _quota(db, owner)).generation_credits == 1


@pytest.mark.asyncio
async def test_same_key_different_payload_rejected_409(db, research_store):
    owner = research_store.user_ids["a"]
    actor = research_store.actor("a")
    await _grant(db, owner, generation_credits=2)
    await create_task(
        db, actor, _draft_payload(), idempotency_key="billing-reuse-0001"
    )
    other = _draft_payload()
    other["objective"] = "完全不同的研究目标表述"
    with pytest.raises(ResearchAPIError) as excinfo:
        await create_task(db, actor, other, idempotency_key="billing-reuse-0001")
    assert (excinfo.value.status_code, excinfo.value.code) == (
        409,
        "IDEMPOTENCY_CONFLICT",
    )
    assert await _count(db, ResearchTask) == 1
    assert len(await _billing_rows(db, owner)) == 1
    assert (await _quota(db, owner)).generation_credits == 1


@pytest.mark.asyncio
async def test_concurrent_second_task_rejected_without_extra_reservation(
    db, research_store
):
    owner = research_store.user_ids["a"]
    actor = research_store.actor("a")
    await _grant(db, owner, generation_credits=2)
    await create_task(
        db, actor, _draft_payload(), idempotency_key="billing-active-0001"
    )

    second = _draft_payload()
    second["objective"] = "第二个并行任务应当被并发上限拒绝"
    with pytest.raises(ResearchAPIError) as excinfo:
        await create_task(db, actor, second, idempotency_key="billing-active-0002")
    assert (excinfo.value.status_code, excinfo.value.code) == (
        429,
        "CONCURRENCY_LIMIT",
    )
    assert excinfo.value.details.get("scope") == "user"
    assert len(await _billing_rows(db, owner)) == 1
    assert (await _quota(db, owner)).generation_credits == 1


@pytest.mark.asyncio
async def test_active_reservation_blocks_second_task_in_same_group(
    db, research_store
):
    owner = research_store.user_ids["a"]
    actor = research_store.actor("a")
    await _grant(db, owner, generation_credits=2)
    accepted = await create_task(
        db, actor, _draft_payload(), idempotency_key="billing-group-0001"
    )
    first = await _load_task(db, accepted.task_id)

    duplicate = ResearchTask(
        id=new_id("rtask"),
        owner_id=owner,
        project_id="rproj_billing_test",
        kind=TaskKind.DRAFT_FROM_OUTLINE.value,
        status="queued",
        objective="重复投递的第二个任务",
        input_json="{}",
        scope_json="{}",
        constraints_json="{}",
        state_revision=1,
        billing_group_id=first.billing_group_id,
        billing_state="released",
        attempt_no=0,
        request_fingerprint=_fingerprint(_draft_payload()),
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(duplicate)
    await db.commit()

    with pytest.raises(ResearchAPIError) as excinfo:
        await reserve(db, actor, duplicate, duplicate.kind)
    err = excinfo.value
    assert (err.status_code, err.code) == (409, "BILLING_GROUP_ACTIVE")
    assert err.details.get("billing_group_id") == first.billing_group_id
    assert err.details.get("active_task_id") == first.id
    # 冲突不产生新的账本行。
    assert len(await _billing_rows(db, owner)) == 1


@pytest.mark.asyncio
async def test_snapshot_billing_group_and_state_are_queryable(db, research_store):
    owner = research_store.user_ids["a"]
    actor = research_store.actor("a")
    await _grant(db, owner, generation_credits=1)
    accepted = await create_task(
        db, actor, _draft_payload(), idempotency_key="billing-snapshot-0001"
    )
    task = await _load_task(db, accepted.task_id)
    assert accepted.snapshot_summary["billing_group_id"] == task.billing_group_id
    assert accepted.snapshot_summary["billing_capability"] == "generation"
    assert accepted.snapshot_summary["request_fingerprint"] == (
        task.request_fingerprint
    )
    assert task.request_fingerprint == _fingerprint(_draft_payload())
