"""T15 / AT-014：分析检查点的读写、续跑与 fencing 归属。

覆盖范围（对应 R1_INTERFACE_SPEC §2.1）：
- 无记录返回空结构而不是异常；
- 保存后可按 ``task_id + attempt_no`` 读回，扩展键不影响公开四键；
- attempt 行不存在时静默跳过；非 dict 载荷显式报错；
- 损坏数据（字符串序号、负数计数）被安全归一化；
- 重试（新 attempt）尚未写检查点时，按最近一个带检查点的 attempt 续跑；
- 指定 attempt_no 时绝不串读别的 attempt；
- 写检查点必须带上 task_id，否则不能穿透到别的任务同号 attempt。
"""
from __future__ import annotations

import pytest

from ...research import checkpoints
from ...research.models import ResearchTask, TaskAttempt

pytestmark = pytest.mark.asyncio


async def _seed_task(db, owner_id: int, task_id: str) -> ResearchTask:
    task = ResearchTask(
        id=task_id,
        owner_id=owner_id,
        project_id="proj_checkpoint",
        kind="review",
        objective="检查点验证",
        billing_group_id="bg_checkpoint",
    )
    db.add(task)
    await db.flush()
    return task


async def _seed_attempt(
    db,
    task_id: str,
    attempt_no: int,
    *,
    checkpoint: dict | None = None,
    started_at=None,
) -> TaskAttempt:
    # 与生产路径一致：没有检查点时不要显式写 None。JSON 列在 SQLite 上会把
    # 显式 None 序列化成 JSON 'null'（不等于 SQL NULL），显式构造的测试数据
    # 会与 open_attempt 的真实行不同。
    attempt = TaskAttempt(
        id=f"att_{task_id}_{attempt_no}",
        task_id=task_id,
        attempt_no=attempt_no,
        status="running",
        fencing_token=attempt_no,
    )
    if checkpoint is not None:
        attempt.checkpoint_json = dict(checkpoint)
    if started_at is not None:
        attempt.started_at = started_at
    db.add(attempt)
    await db.flush()
    return attempt


async def _checkpoint_of(db, attempt_id: str) -> dict | None:
    row = await db.get(TaskAttempt, attempt_id)
    return row.checkpoint_json


class TestLoadEmpty:
    async def test_missing_task_returns_empty_structure(self, db, research_store):
        payload = await checkpoints.load_checkpoint(db, "rtask_does_not_exist")

        assert payload == {
            "analyzed_ordinals": [],
            "cursor": 0,
            "model_calls": 0,
            "tokens": 0,
        }
        assert set(payload) == set(checkpoints.CHECKPOINT_KEYS)

    async def test_attempt_without_checkpoint_returns_empty_structure(
        self, db, research_store
    ):
        await _seed_task(db, research_store.user_ids["a"], "rtask_cp_none")
        await _seed_attempt(db, "rtask_cp_none", 1)

        payload = await checkpoints.load_checkpoint(db, "rtask_cp_none", 1)

        assert payload["analyzed_ordinals"] == []
        assert payload["cursor"] == 0
        assert payload["model_calls"] == 0
        assert payload["tokens"] == 0

    async def test_payload_load_preserves_extension_keys(self, db, research_store):
        await _seed_task(db, research_store.user_ids["a"], "rtask_cp_ext")
        await _seed_attempt(
            db,
            "rtask_cp_ext",
            1,
            checkpoint={
                "analyzed_ordinals": [1],
                "cursor": 1,
                "model_calls": 2,
                "tokens": 300,
                "findings": [{"problem": "缺失结论"}],
            },
        )

        public = await checkpoints.load_checkpoint(db, "rtask_cp_ext", 1)
        full = await checkpoints.load_checkpoint_payload(db, "rtask_cp_ext", 1)

        assert "findings" not in public
        assert full["findings"] == [{"problem": "缺失结论"}]


class TestSaveAndLoad:
    async def test_roundtrip_after_save(self, db, research_store):
        await _seed_task(db, research_store.user_ids["a"], "rtask_cp_rt")
        await _seed_attempt(db, "rtask_cp_rt", 1)

        await checkpoints.save_checkpoint(
            db,
            1,
            {
                "analyzed_ordinals": [0, 2, 4],
                "cursor": 2,
                "model_calls": 3,
                "tokens": 1234,
            },
            task_id="rtask_cp_rt",
        )
        payload = await checkpoints.load_checkpoint(db, "rtask_cp_rt", 1)

        assert payload == {
            "analyzed_ordinals": [0, 2, 4],
            "cursor": 2,
            "model_calls": 3,
            "tokens": 1234,
        }

    async def test_save_missing_attempt_is_silent_noop(self, db, research_store):
        # 不允许抛异常：重试竞态下旧 attempt 可能已被清理。
        await checkpoints.save_checkpoint(
            db, 7, {"analyzed_ordinals": [1]}, task_id="rtask_absent"
        )

        assert await checkpoints.load_checkpoint(db, "rtask_absent") == {
            "analyzed_ordinals": [],
            "cursor": 0,
            "model_calls": 0,
            "tokens": 0,
        }

    async def test_save_rejects_non_dict_payload(self, db, research_store):
        await _seed_task(db, research_store.user_ids["a"], "rtask_cp_bad")
        await _seed_attempt(db, "rtask_cp_bad", 1)

        with pytest.raises(TypeError):
            await checkpoints.save_checkpoint(
                db, 1, ["not", "a", "dict"], task_id="rtask_cp_bad"
            )

    async def test_corrupt_payload_is_normalized(self, db, research_store):
        await _seed_task(db, research_store.user_ids["a"], "rtask_cp_corrupt")
        await _seed_attempt(db, "rtask_cp_corrupt", 1)

        await checkpoints.save_checkpoint(
            db,
            1,
            {
                "analyzed_ordinals": ["3", "3", 2, "x"],
                "cursor": -5,
                "model_calls": "7",
                "tokens": "not-a-number",
            },
            task_id="rtask_cp_corrupt",
        )
        payload = await checkpoints.load_checkpoint(db, "rtask_cp_corrupt", 1)

        assert payload["analyzed_ordinals"] == [3, 2]
        assert payload["cursor"] == 0
        assert payload["model_calls"] == 7
        assert payload["tokens"] == 0


class TestAttemptSelection:
    async def test_retry_without_checkpoint_resumes_from_previous_attempt(
        self, db, research_store
    ):
        await _seed_task(db, research_store.user_ids["a"], "rtask_cp_resume")
        await _seed_attempt(
            db,
            "rtask_cp_resume",
            1,
            checkpoint={
                "analyzed_ordinals": [0, 1],
                "cursor": 1,
                "model_calls": 2,
                "tokens": 900,
            },
        )
        await _seed_attempt(db, "rtask_cp_resume", 2)

        payload = await checkpoints.load_checkpoint(db, "rtask_cp_resume")

        assert payload["analyzed_ordinals"] == [0, 1]
        assert payload["cursor"] == 1
        assert payload["model_calls"] == 2
        assert payload["tokens"] == 900

    async def test_explicit_attempt_no_does_not_read_other_attempt(
        self, db, research_store
    ):
        await _seed_task(db, research_store.user_ids["a"], "rtask_cp_explicit")
        await _seed_attempt(
            db,
            "rtask_cp_explicit",
            1,
            checkpoint={"analyzed_ordinals": [9], "cursor": 9},
        )
        await _seed_attempt(db, "rtask_cp_explicit", 2)

        payload = await checkpoints.load_checkpoint(db, "rtask_cp_explicit", 2)

        assert payload["analyzed_ordinals"] == []
        assert payload["cursor"] == 0

    async def test_save_is_fenced_to_task_id(self, db, research_store):
        owner = research_store.user_ids["a"]
        await _seed_task(db, owner, "rtask_cp_a")
        await _seed_task(db, owner, "rtask_cp_b")
        await _seed_attempt(
            db, "rtask_cp_a", 1, checkpoint={"analyzed_ordinals": [1], "tokens": 10}
        )
        await _seed_attempt(
            db, "rtask_cp_b", 1, checkpoint={"analyzed_ordinals": [2], "tokens": 99}
        )

        await checkpoints.save_checkpoint(
            db, 1, {"analyzed_ordinals": [5], "tokens": 55}, task_id="rtask_cp_a"
        )

        assert (await _checkpoint_of(db, "att_rtask_cp_a_1"))["tokens"] == 55
        assert (await _checkpoint_of(db, "att_rtask_cp_b_1"))["tokens"] == 99