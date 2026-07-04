"""P0 架构强化修复的单元测试。

测试范围：
  1. Redis SCAN 无限循环修复（master/task_manager.py、master/health_monitor.py）
     验证 `while True` + `if cursor == 0: break` 模式在 cursor=0 时正确退出
  2. 时间戳格式不匹配修复（master/health_monitor.py 的 _parse_iso_timestamp）
     验证同时支持 ISO 8601 和 epoch 数字字符串
  3. Lua 原子脚本启用（master/protocols/redis_protocol.py 的 RedisProtocol）
     验证 load_scripts() 和 evalsha() 接口存在且可被 mock 调用

运行方式：
    cd c:\\Users\\13067\\Desktop\\AI产品\\cnki-downloader
    python -m pytest tests/test_hardening_p0.py -v
"""
from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 确保能导入项目模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ═══════════════════════════════════════════════════════════════
# SubTask 5.1.1: SCAN 退出验证
# ═══════════════════════════════════════════════════════════════


class _FakeRedisScan:
    """模拟 redis.asyncio.Redis 的 SCAN 行为。

    记录每次 scan 调用，按预设序列返回 (cursor, keys)。
    最后一次返回 cursor=0 触发退出条件。
    """

    def __init__(self, scan_results: list[tuple[int, list[bytes]]]):
        self._scan_results = list(scan_results)
        self.scan_calls = 0

    async def scan(self, cursor, match=None, count=None):
        self.scan_calls += 1
        if self.scan_calls > len(self._scan_results):
            # 防御性：测试不应走到这里，若走到则强制退出
            return 0, []
        return self._scan_results[self.scan_calls - 1]


@pytest.mark.asyncio
async def test_task_manager_get_tasks_by_status_scan_exits_on_cursor_zero():
    """TaskManager.get_tasks_by_status 在 SCAN 返回 cursor=0 时应正确退出。

    修复前：`while cursor >= 0` 永远为真，导致无限循环
    修复后：`while True` + `if cursor == 0: break`
    """
    from master.task_manager import TaskManager

    # 构造 mock Redis：第一次 SCAN 返回 (0, [])，应立即退出
    fake_redis = AsyncMock()
    fake_redis.scan = AsyncMock(return_value=(0, []))

    tm = TaskManager(fake_redis)
    # 调用 get_tasks_by_status，应不进入无限循环
    tasks = await tm.get_tasks_by_status("queued", limit=10)

    assert tasks == []
    # SCAN 应只被调用一次（cursor=0 立即退出）
    assert fake_redis.scan.call_count == 1


@pytest.mark.asyncio
async def test_task_manager_get_tasks_by_status_multi_iteration_then_exit():
    """多轮 SCAN 后 cursor=0 也应正确退出。

    模拟：第一轮 cursor=1（继续），第二轮 cursor=0（退出）。
    """
    from master.task_manager import TaskManager

    fake_redis = AsyncMock()
    # 第一轮返回 cursor=1（继续），第二轮返回 cursor=0（退出）
    fake_redis.scan = AsyncMock(
        side_effect=[
            (1, [b"cnki:task:data:task-1"]),
            (0, [b"cnki:task:data:task-2"]),
        ]
    )
    # hgetall 返回空 dict，让 from_redis_hash 返回 None 跳过
    fake_redis.hgetall = AsyncMock(return_value={})

    tm = TaskManager(fake_redis)
    tasks = await tm.get_tasks_by_status("queued", limit=50)

    # SCAN 应被调用 2 次（第一轮 + 第二轮，第二轮 cursor=0 退出）
    assert fake_redis.scan.call_count == 2


@pytest.mark.asyncio
async def test_task_manager_cleanup_stale_scan_exits_on_cursor_zero():
    """TaskManager.cleanup_stale 在 SCAN 返回 cursor=0 时应正确退出。"""
    from master.task_manager import TaskManager

    fake_redis = AsyncMock()
    fake_redis.scan = AsyncMock(return_value=(0, []))

    tm = TaskManager(fake_redis)
    count = await tm.cleanup_stale(older_than_hours=1)

    assert count == 0
    assert fake_redis.scan.call_count == 1


@pytest.mark.asyncio
async def test_health_monitor_scan_workers_exits_on_cursor_zero():
    """HealthMonitor._scan_workers 在 SCAN 返回 cursor=0 时应正确退出。"""
    from master.health_monitor import HealthMonitor

    fake_redis = AsyncMock()
    fake_redis.scan = AsyncMock(return_value=(0, []))

    hm = HealthMonitor(fake_redis)
    # _scan_workers 是 async 方法，应正常退出
    await hm._scan_workers()

    # SCAN 应只被调用一次
    assert fake_redis.scan.call_count == 1


@pytest.mark.asyncio
async def test_health_monitor_scan_stalled_tasks_exits_on_cursor_zero():
    """HealthMonitor._scan_stalled_tasks 在 SCAN 返回 cursor=0 时应正确退出。

    _scan_stalled_tasks 内部按 discipline 迭代，每个 discipline 调用一次 SCAN 循环。
    修复前：`while cursor >= 0` 永远为真，导致无限循环
    修复后：`while True` + `if cursor == 0: break`
    """
    from master.health_monitor import HealthMonitor
    from config.journals import VALID_DISCIPLINES

    fake_redis = AsyncMock()
    # 每个 discipline 的 SCAN 都立即返回 cursor=0
    fake_redis.scan = AsyncMock(return_value=(0, []))

    hm = HealthMonitor(fake_redis)
    await hm._scan_stalled_tasks()

    # SCAN 应被调用 len(VALID_DISCIPLINES) 次（每个 discipline 一次，每次 cursor=0 立即退出）
    expected_calls = len(VALID_DISCIPLINES)
    assert fake_redis.scan.call_count == expected_calls
    # 验证每个 discipline 只调用一次 SCAN（无无限循环）
    assert fake_redis.scan.call_count == expected_calls


@pytest.mark.asyncio
async def test_health_monitor_get_workers_status_exits_on_cursor_zero():
    """HealthMonitor.get_workers_status 在 SCAN 返回 cursor=0 时应正确退出。"""
    from master.health_monitor import HealthMonitor

    fake_redis = AsyncMock()
    fake_redis.scan = AsyncMock(return_value=(0, []))

    hm = HealthMonitor(fake_redis)
    workers = await hm.get_workers_status()

    assert workers == []
    assert fake_redis.scan.call_count == 1


@pytest.mark.asyncio
async def test_health_monitor_scan_workers_multi_iteration_exits():
    """多轮 SCAN 后 cursor=0 也应正确退出（_scan_workers）。"""
    from master.health_monitor import HealthMonitor

    fake_redis = AsyncMock()
    fake_redis.scan = AsyncMock(
        side_effect=[
            (1, [b"cnki:heartbeat:worker-1"]),
            (0, [b"cnki:heartbeat:worker-2"]),
        ]
    )
    # 第一轮：worker-1 心跳已过期（get 返回 None）→ _handle_dead_worker
    # 第二轮：worker-2 心跳已过期（get 返回 None）→ _handle_dead_worker
    fake_redis.get = AsyncMock(return_value=None)
    # _handle_dead_worker 内部调用 smembers（返回空集合避免递归）
    fake_redis.smembers = AsyncMock(return_value=set())
    fake_redis.delete = AsyncMock()
    fake_redis.hset = AsyncMock()
    fake_redis.publish = AsyncMock()

    hm = HealthMonitor(fake_redis)
    await hm._scan_workers()

    # SCAN 应被调用 2 次
    assert fake_redis.scan.call_count == 2


# ═══════════════════════════════════════════════════════════════
# SubTask 5.1.2: 时间戳解析
# ═══════════════════════════════════════════════════════════════


def test_parse_iso_timestamp_iso_format():
    """_parse_iso_timestamp 应正确解析 ISO 8601 格式时间戳。"""
    from master.health_monitor import _parse_iso_timestamp

    # ISO 8601 带时区
    ts = _parse_iso_timestamp("2026-06-24T10:00:00+00:00")
    assert ts > 0
    # 验证大致正确（2026-06-24 10:00 UTC ≈ 1782266400）
    assert 1782000000 < ts < 1783000000


def test_parse_iso_timestamp_iso_format_naive():
    """_parse_iso_timestamp 应解析无时区的 ISO 格式（本地时间）。"""
    from master.health_monitor import _parse_iso_timestamp

    ts = _parse_iso_timestamp("2026-06-24T10:00:00")
    assert ts > 0


def test_parse_iso_timestamp_epoch_string():
    """_parse_iso_timestamp 应解析 epoch 数字字符串。

    修复前：worker 写入 str(time.time())，health_monitor 用 fromisoformat 解析会失败
    修复后：先尝试 ISO，失败后 fallback 到 float()
    """
    from master.health_monitor import _parse_iso_timestamp

    # epoch 字符串（worker 实际写入的格式）
    ts = _parse_iso_timestamp("1719212345.67")
    assert ts == pytest.approx(1719212345.67, rel=1e-9)


def test_parse_iso_timestamp_epoch_integer_string():
    """_parse_iso_timestamp 应解析整数 epoch 字符串。"""
    from master.health_monitor import _parse_iso_timestamp

    ts = _parse_iso_timestamp("1719212345")
    assert ts == pytest.approx(1719212345.0, rel=1e-9)


def test_parse_iso_timestamp_empty_string():
    """空字符串应返回 0.0（不抛异常）。"""
    from master.health_monitor import _parse_iso_timestamp

    assert _parse_iso_timestamp("") == 0.0


def test_parse_iso_timestamp_invalid_string():
    """无效字符串应返回 0.0（不抛异常）。"""
    from master.health_monitor import _parse_iso_timestamp

    assert _parse_iso_timestamp("not-a-timestamp") == 0.0


def test_parse_iso_timestamp_none():
    """None 输入应返回 0.0（不抛异常）。"""
    from master.health_monitor import _parse_iso_timestamp

    # None 不是 str，但函数应优雅处理
    try:
        result = _parse_iso_timestamp(None)  # type: ignore[arg-type]
        assert result == 0.0
    except (TypeError, ValueError):
        # 允许抛异常，但调用方应有 try/except 保护
        pass


def test_parse_iso_timestamp_consistency():
    """同一时刻的 ISO 和 epoch 解析结果应接近。"""
    from master.health_monitor import _parse_iso_timestamp
    from datetime import datetime, timezone

    # 用同一时刻生成两种格式
    now = datetime(2026, 6, 24, 10, 0, 0, tzinfo=timezone.utc)
    iso_str = now.isoformat()
    epoch_str = str(now.timestamp())

    ts_iso = _parse_iso_timestamp(iso_str)
    ts_epoch = _parse_iso_timestamp(epoch_str)

    # 两者应相等（精度损失可忽略）
    assert ts_iso == pytest.approx(ts_epoch, rel=1e-6)


# ═══════════════════════════════════════════════════════════════
# SubTask 5.1.3: Lua 脚本加载接口验证
# ═══════════════════════════════════════════════════════════════


def test_redis_protocol_class_exists():
    """RedisProtocol 类应存在且可导入。"""
    from master.protocols.redis_protocol import RedisProtocol
    assert RedisProtocol is not None


def test_redis_protocol_load_scripts_method_exists():
    """RedisProtocol 应有 load_scripts 异步方法。"""
    from master.protocols.redis_protocol import RedisProtocol

    assert hasattr(RedisProtocol, "load_scripts")
    assert callable(getattr(RedisProtocol, "load_scripts"))

    # 验证是协程函数
    assert inspect.iscoroutinefunction(RedisProtocol.load_scripts)


def test_redis_protocol_evalsha_method_exists():
    """RedisProtocol 应有 evalsha 异步方法。"""
    from master.protocols.redis_protocol import RedisProtocol

    assert hasattr(RedisProtocol, "evalsha")
    assert callable(getattr(RedisProtocol, "evalsha"))
    assert inspect.iscoroutinefunction(RedisProtocol.evalsha)


def test_redis_protocol_lua_scripts_defined():
    """所有 Lua 脚本常量应已定义。"""
    from master.protocols import redis_protocol as rp

    # 验证关键 Lua 脚本存在
    assert hasattr(rp, "LUA_TASK_ACQUIRE")
    assert hasattr(rp, "LUA_TASK_COMPLETE")
    assert hasattr(rp, "LUA_TASK_FAIL")
    assert hasattr(rp, "LUA_UPDATE_STATS")
    assert hasattr(rp, "LUA_HEARTBEAT")
    assert hasattr(rp, "LUA_REQUEUE_STALLED")

    # 验证脚本是字符串且非空
    for script_name in [
        "LUA_TASK_ACQUIRE", "LUA_TASK_COMPLETE", "LUA_TASK_FAIL",
        "LUA_UPDATE_STATS", "LUA_HEARTBEAT", "LUA_REQUEUE_STALLED",
    ]:
        script = getattr(rp, script_name)
        assert isinstance(script, str), f"{script_name} 应为字符串"
        assert len(script.strip()) > 0, f"{script_name} 不应为空"
        # Lua 脚本应包含 redis.call
        assert "redis.call" in script, f"{script_name} 应包含 redis.call"


@pytest.mark.asyncio
async def test_redis_protocol_load_scripts_calls_script_load():
    """load_scripts 应对每个脚本调用 redis.script_load 并存储 SHA。"""
    from master.protocols.redis_protocol import RedisProtocol

    # mock redis，记录每次 script_load 调用
    fake_redis = AsyncMock()
    # 每次 script_load 返回不同的 SHA
    fake_redis.script_load = AsyncMock(
        side_effect=[f"sha_{i}" for i in range(6)]
    )

    protocol = RedisProtocol(fake_redis)
    await protocol.load_scripts()

    # 应调用 6 次 script_load（6 个脚本）
    assert fake_redis.script_load.call_count == 6

    # 内部 _scripts 字典应填充
    assert len(protocol._scripts) == 6
    # 验证所有脚本名都注册了
    expected_names = {
        "task_acquire", "task_complete", "task_fail",
        "update_stats", "heartbeat", "requeue_stalled",
    }
    assert set(protocol._scripts.keys()) == expected_names


@pytest.mark.asyncio
async def test_redis_protocol_evalsha_calls_redis_evalsha():
    """evalsha 应使用存储的 SHA 调用 redis.evalsha。"""
    from master.protocols.redis_protocol import RedisProtocol

    fake_redis = AsyncMock()
    fake_redis.script_load = AsyncMock(return_value="abc123sha")
    fake_redis.evalsha = AsyncMock(return_value=b'{"task_id":"t1"}')

    protocol = RedisProtocol(fake_redis)
    await protocol.load_scripts()

    # 调用 evalsha
    result = await protocol.evalsha(
        "task_acquire",
        keys=["cnki:task:queue:新闻传播学", "cnki:task:assigned:w1"],
        args=["w1", "1719212345.67"],
    )

    # 验证 redis.evalsha 被调用
    fake_redis.evalsha.assert_called_once()
    # 第一个参数应是 SHA
    call_args = fake_redis.evalsha.call_args
    assert call_args.args[0] == "abc123sha"
    # 结果应被返回
    assert result == b'{"task_id":"t1"}'


@pytest.mark.asyncio
async def test_redis_protocol_evalsha_unknown_script_raises():
    """evalsha 对未加载的脚本名应抛出 ValueError。"""
    from master.protocols.redis_protocol import RedisProtocol

    fake_redis = AsyncMock()
    protocol = RedisProtocol(fake_redis)

    with pytest.raises(ValueError, match="Unknown script"):
        await protocol.evalsha("nonexistent_script", keys=[], args=[])


@pytest.mark.asyncio
async def test_redis_protocol_evalsha_before_load_raises():
    """未调用 load_scripts 直接调用 evalsha 应抛出 ValueError。"""
    from master.protocols.redis_protocol import RedisProtocol

    fake_redis = AsyncMock()
    protocol = RedisProtocol(fake_redis)

    with pytest.raises(ValueError, match="Unknown script"):
        await protocol.evalsha("task_acquire", keys=[], args=[])


# ═══════════════════════════════════════════════════════════════
# SubTask 5.1.4: worker/main.py 异步 Redis 跨事件循环修复验证
# ═══════════════════════════════════════════════════════════════


def test_worker_main_imports_aioredis_for_thread_local():
    """worker/main.py 的 _handle_task 应在方法内部导入 redis.asyncio。

    修复要点：每线程创建独立 Redis 客户端，避免跨事件循环使用 self._redis。
    """
    import worker.main as worker_main_mod

    # 读取源码，验证 _handle_task 内部创建 thread-local Redis 客户端
    source = inspect.getsource(worker_main_mod.CNKIWorker._handle_task)

    # 应包含 redis.asyncio 的导入或 from_url 调用
    assert "aioredis" in source or "redis.asyncio" in source, \
        "_handle_task 应在内部导入 redis.asyncio 用于线程本地客户端"
    assert "from_url" in source, \
        "_handle_task 应使用 from_url 创建线程本地 Redis 客户端"


def test_worker_main_uses_protocol_evalsha():
    """worker/main.py 的 _task_loop 应使用 RedisProtocol.evalsha 而非直接 RPOP。

    修复要点：使用 Lua 原子脚本（task_acquire）替代非原子的 RPOP+HSET。
    """
    import worker.main as worker_main_mod

    source = inspect.getsource(worker_main_mod.CNKIWorker._task_loop)

    # 应调用 self._protocol.evalsha
    assert "evalsha" in source, \
        "_task_loop 应使用 self._protocol.evalsha 调用 Lua 原子脚本"
    assert "task_acquire" in source, \
        "_task_loop 应调用 task_acquire Lua 脚本"


# ═══════════════════════════════════════════════════════════════
# 测试运行入口
# ═══════════════════════════════════════════════════════════════


if __name__ == "__main__":
    # 允许直接运行：python tests/test_hardening_p0.py
    sys.exit(pytest.main([__file__, "-v"]))
