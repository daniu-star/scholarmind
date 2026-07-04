"""
PipelineStateRepo 单元测试

覆盖：
- 内存模式 CRUD（Redis 不可用时自动降级）
- 用户索引维护与隔离
- 日志追加与截断（200 条上限）
- 部分状态更新（update_status）
- list_by_user 按 updated_at 降序排序
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from ...db import pipeline_state_repo as repo_module
from ...db.pipeline_state_repo import get_pipeline_state_repo
from ...utils import redis_client


# ── Fixtures ──────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def reset_state():
    """每个测试前后重置 Redis 状态和 Repo 单例，确保隔离"""
    await redis_client.reset_redis_state()
    repo_module._repo = None
    yield
    await redis_client.reset_redis_state()
    repo_module._repo = None


@pytest.fixture
def repo():
    """获取 PipelineStateRepo 实例（内存模式，因 Redis 不可用）"""
    return get_pipeline_state_repo()


# ── save / get ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_and_get_memory_mode(repo):
    """内存模式下 save + get 正确存取"""
    pipeline_id = "pipe-001"
    state = {
        "status": "pending",
        "config": {"topic": "AI伦理"},
        "user_id": "user-123",
    }

    result = await repo.save(pipeline_id, state, user_id="user-123")
    assert result is False  # 内存模式返回 False

    fetched = await repo.get(pipeline_id)
    assert fetched is not None
    assert fetched["status"] == "pending"
    assert fetched["config"]["topic"] == "AI伦理"
    assert "updated_at" in fetched  # save 自动添加时间戳


@pytest.mark.asyncio
async def test_get_nonexistent_returns_none(repo):
    """get 不存在的 pipeline 返回 None"""
    assert await repo.get("nonexistent-id") is None


@pytest.mark.asyncio
async def test_save_without_user_id(repo):
    """save 不传 user_id 时也能正常存储"""
    await repo.save("pipe-no-user", {"status": "pending"})

    fetched = await repo.get("pipe-no-user")
    assert fetched is not None
    assert fetched["status"] == "pending"


# ── delete ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_removes_state(repo):
    """delete 移除 pipeline 状态"""
    pipeline_id = "pipe-002"
    await repo.save(pipeline_id, {"status": "running"}, user_id="user-1")

    assert await repo.get(pipeline_id) is not None

    await repo.delete(pipeline_id)

    assert await repo.get(pipeline_id) is None


@pytest.mark.asyncio
async def test_delete_nonexistent_returns_true(repo):
    """delete 不存在的 pipeline 也返回 True（幂等）"""
    assert await repo.delete("nonexistent") is True


# ── update_status ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_status_partial_update(repo):
    """update_status 仅更新指定字段，保留其他字段"""
    pipeline_id = "pipe-003"
    await repo.save(pipeline_id, {
        "status": "pending",
        "config": {"topic": "原话题"},
        "user_id": "user-1",
    }, user_id="user-1")

    updated = await repo.update_status(pipeline_id, "running", progress=50)

    assert updated is not None
    assert updated["status"] == "running"
    assert updated["progress"] == 50
    assert updated["config"]["topic"] == "原话题"  # 原字段保留
    assert updated["user_id"] == "user-1"  # user_id 保留


@pytest.mark.asyncio
async def test_update_status_nonexistent_returns_none(repo):
    """update_status 不存在的 pipeline 返回 None"""
    assert await repo.update_status("nonexistent", "running") is None


@pytest.mark.asyncio
async def test_update_status_preserves_user_id_for_index(repo):
    """update_status 后 user_id 索引仍然有效"""
    user_id = "user-update-test"
    await repo.save("pipe-update", {
        "status": "pending",
        "user_id": user_id,
    }, user_id=user_id)

    await repo.update_status("pipe-update", "completed")

    pipelines = await repo.list_by_user(user_id)
    assert len(pipelines) == 1
    assert pipelines[0]["status"] == "completed"


# ── list_by_user ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_by_user_returns_sorted_desc(repo):
    """list_by_user 返回用户的所有 pipeline，按 updated_at 降序"""
    user_id = "user-list-test"

    for i in range(3):
        await repo.save(f"pipe-list-{i}", {
            "status": "pending",
            "user_id": user_id,
            "updated_at": f"2024-01-0{i+1}T10:00:00",  # 1/1 < 1/2 < 1/3
        }, user_id=user_id)

    result = await repo.list_by_user(user_id)

    assert len(result) == 3
    # 降序：最新的在前
    assert result[0]["updated_at"] > result[1]["updated_at"]
    assert result[1]["updated_at"] > result[2]["updated_at"]


@pytest.mark.asyncio
async def test_list_by_user_empty(repo):
    """list_by_user 无 pipeline 时返回空列表"""
    result = await repo.list_by_user("no-pipelines-user")
    assert result == []


@pytest.mark.asyncio
async def test_list_by_user_respects_limit(repo):
    """list_by_user 遵守 limit 参数"""
    user_id = "user-limit-test"
    for i in range(5):
        await repo.save(f"pipe-limit-{i}", {
            "status": "pending",
            "user_id": user_id,
            "updated_at": f"2024-01-0{i+1}T10:00:00",
        }, user_id=user_id)

    result = await repo.list_by_user(user_id, limit=2)
    assert len(result) == 2


# ── append_log ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_append_log_adds_timestamped_entry(repo):
    """append_log 追加带时间戳的日志条目"""
    pipeline_id = "pipe-log-001"
    await repo.save(pipeline_id, {"status": "running", "logs": []}, user_id="user-1")

    await repo.append_log(pipeline_id, "Pipeline 启动")
    await repo.append_log(pipeline_id, "Agent[researcher] 完成")

    state = await repo.get(pipeline_id)
    logs = state["logs"]
    assert len(logs) == 2
    assert logs[0].startswith("[")  # 时间戳前缀
    assert "Pipeline 启动" in logs[0]
    assert "Agent[researcher] 完成" in logs[1]


@pytest.mark.asyncio
async def test_append_log_initializes_empty_logs(repo):
    """append_log 在 logs 字段不存在时自动初始化"""
    pipeline_id = "pipe-log-init"
    await repo.save(pipeline_id, {"status": "running"}, user_id="user-1")

    await repo.append_log(pipeline_id, "第一条日志")

    state = await repo.get(pipeline_id)
    assert state["logs"] == 1 or len(state["logs"]) == 1


@pytest.mark.asyncio
async def test_append_log_truncates_to_200(repo):
    """日志超过 200 条时自动截断，保留最近 200 条"""
    pipeline_id = "pipe-log-trunc"
    await repo.save(pipeline_id, {"status": "running", "logs": []}, user_id="user-1")

    # 追加 210 条日志
    for i in range(210):
        await repo.append_log(pipeline_id, f"entry_{i}")

    state = await repo.get(pipeline_id)
    logs = state["logs"]
    assert len(logs) == 200
    # 最后一条是 entry_209
    assert "entry_209" in logs[-1]


@pytest.mark.asyncio
async def test_append_log_nonexistent_returns_none(repo):
    """append_log 不存在的 pipeline 返回 None"""
    assert await repo.append_log("nonexistent", "some log") is None


# ── 用户索引隔离 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_user_index_isolation(repo):
    """不同用户的 pipeline 互不干扰"""
    await repo.save("pipe-user-a", {"status": "pending"}, user_id="user-a")
    await repo.save("pipe-user-b", {"status": "pending"}, user_id="user-b")
    await repo.save("pipe-user-a-2", {"status": "running"}, user_id="user-a")

    user_a = await repo.list_by_user("user-a")
    user_b = await repo.list_by_user("user-b")

    assert len(user_a) == 2
    assert len(user_b) == 1


@pytest.mark.asyncio
async def test_delete_clears_user_index(repo):
    """delete 后用户索引中不再包含该 pipeline"""
    user_id = "user-del-test"
    await repo.save("pipe-del-1", {"status": "pending"}, user_id=user_id)
    await repo.save("pipe-del-2", {"status": "pending"}, user_id=user_id)

    await repo.delete("pipe-del-1")

    result = await repo.list_by_user(user_id)
    assert len(result) == 1
    # 剩下的应该是 pipe-del-2（通过状态内容间接验证）
    assert result[0]["status"] == "pending"
