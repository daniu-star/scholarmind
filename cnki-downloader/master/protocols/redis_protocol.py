"""Redis key schemas, Lua atomic scripts, and Pub/Sub message protocols.

This is the single source of truth for all inter-component communication.
Reuses the Lua scripting pattern from ScholarMind's redis_rate_limit.py.
"""

from __future__ import annotations

import json
from typing import Optional
from redis.asyncio import Redis

# ═══════════════════════════════════════════════════════════════
# Key Schemas
# ═══════════════════════════════════════════════════════════════

# Task queues (per discipline)
TASK_QUEUE_KEY = "cnki:task:queue:{discipline}"
TASK_RETRY_QUEUE_KEY = "cnki:task:queue:{discipline}:retry"

# Task data
TASK_DATA_KEY = "cnki:task:data:{task_id}"
TASK_ASSIGNED_KEY = "cnki:task:assigned:{worker_id}"
TASK_LOCK_KEY = "cnki:lock:task:{task_id}"

# Worker registry
WORKER_INFO_KEY = "cnki:worker:{worker_id}"
WORKER_HEARTBEAT_KEY = "cnki:heartbeat:{worker_id}"

# Statistics
STATS_DISCIPLINE_KEY = "cnki:stats:{discipline}"
STATS_GLOBAL_KEY = "cnki:stats:global"

# Scheduler lock
SCHEDULER_LOCK_KEY = "cnki:lock:scheduler"

# ── Pub/Sub Channels ──

CHANNEL_MASTER_COMMANDS = "cnki:master:commands"
CHANNEL_WORKER_EVENTS = "cnki:worker:events"
CHANNEL_WORKER_HEARTBEAT = "cnki:worker:heartbeat"


# ═══════════════════════════════════════════════════════════════
# Lua Scripts (Atomic Operations)
# ═══════════════════════════════════════════════════════════════

LUA_TASK_ACQUIRE = """
-- KEYS[1] = cnki:task:queue:{discipline}
-- KEYS[2] = cnki:task:assigned:{worker_id}
-- ARGV[1] = worker_id
-- ARGV[2] = current_timestamp
-- Returns: task_id (JSON) or nil
local task_json = redis.call('RPOP', KEYS[1])
if task_json then
    local task = cjson.decode(task_json)
    local task_id = task['task_id']
    local lock_key = 'cnki:lock:task:' .. task_id
    redis.call('SET', lock_key, ARGV[1], 'EX', 300)
    redis.call('SADD', KEYS[2], task_id)
    task['status'] = 'assigned'
    task['assigned_worker'] = ARGV[1]
    task['started_at'] = ARGV[2]
    redis.call('HSET', 'cnki:task:data:' .. task_id,
        'status', 'assigned',
        'assigned_worker', ARGV[1],
        'started_at', ARGV[2]
    )
    return cjson.encode(task)
end
return nil
"""

LUA_TASK_COMPLETE = """
-- KEYS[1] = cnki:task:assigned:{worker_id}
-- ARGV[1] = task_id
redis.call('SREM', KEYS[1], ARGV[1])
redis.call('DEL', 'cnki:lock:task:' .. ARGV[1])
redis.call('DEL', 'cnki:task:data:' .. ARGV[1])
return 1
"""

LUA_TASK_FAIL = """
-- KEYS[1] = cnki:task:assigned:{worker_id}
-- KEYS[2] = cnki:task:queue:{discipline}:retry
-- ARGV[1] = task_id
-- ARGV[2] = task_json (updated with error info)
redis.call('SREM', KEYS[1], ARGV[1])
redis.call('DEL', 'cnki:lock:task:' .. ARGV[1])
redis.call('LPUSH', KEYS[2], ARGV[2])
return 1
"""

LUA_UPDATE_STATS = """
-- KEYS[1] = cnki:stats:{discipline}
-- KEYS[2] = cnki:stats:global
-- ARGV[1] = field to increment (total/completed/failed/pending/processing)
-- ARGV[2] = delta (integer)
redis.call('HINCRBY', KEYS[1], ARGV[1], ARGV[2])
redis.call('HINCRBY', KEYS[2], ARGV[1], ARGV[2])
return 1
"""

LUA_HEARTBEAT = """
-- KEYS[1] = cnki:heartbeat:{worker_id}
-- ARGV[1] = heartbeat_payload (JSON)
-- ARGV[2] = expire_seconds
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
return 1
"""

LUA_REQUEUE_STALLED = """
-- KEYS[1] = cnki:task:queue:{discipline}
-- ARGV[1] = task_json (with priority=10)
-- ARGV[2] = task_id
redis.call('LPUSH', KEYS[1], ARGV[1])
redis.call('DEL', 'cnki:lock:task:' .. ARGV[2])
return 1
"""


# ═══════════════════════════════════════════════════════════════
# Protocol Loader
# ═══════════════════════════════════════════════════════════════

class RedisProtocol:
    """Manages Lua script loading and execution on Redis."""

    def __init__(self, redis: Redis):
        self._redis = redis
        self._scripts: dict[str, str] = {}

    async def load_scripts(self) -> None:
        """Load all Lua scripts into Redis for efficient execution."""
        scripts = {
            "task_acquire": LUA_TASK_ACQUIRE,
            "task_complete": LUA_TASK_COMPLETE,
            "task_fail": LUA_TASK_FAIL,
            "update_stats": LUA_UPDATE_STATS,
            "heartbeat": LUA_HEARTBEAT,
            "requeue_stalled": LUA_REQUEUE_STALLED,
        }
        for name, script in scripts.items():
            sha = await self._redis.script_load(script)
            self._scripts[name] = sha

    async def evalsha(self, name: str, keys: list[str], args: list[str]) -> Optional[str]:
        """Execute a loaded script by name."""
        sha = self._scripts.get(name)
        if not sha:
            raise ValueError(f"Unknown script: {name}")
        return await self._redis.evalsha(sha, len(keys), *keys, *args)


# ═══════════════════════════════════════════════════════════════
# Message Protocol Helpers
# ═══════════════════════════════════════════════════════════════

def master_command(cmd: str, discipline: str = "all") -> dict:
    """Build a master→worker command message."""
    return {
        "command": cmd,  # pause, resume, shutdown, reconfigure
        "discipline": discipline,
    }


def worker_event(
    event: str,
    worker_id: str,
    task_id: str = "",
    paper: Optional[dict] = None,
    duration_ms: int = 0,
    error: str = "",
    captcha_type: str = "",
) -> dict:
    """Build a worker→master event message."""
    msg = {
        "event": event,  # task_completed, task_failed, captcha_triggered, worker_started
        "worker_id": worker_id,
        "task_id": task_id,
        "error": error,
    }
    if paper:
        msg["paper"] = paper
    if duration_ms:
        msg["duration_ms"] = duration_ms
    if captcha_type:
        msg["captcha_type"] = captcha_type
    return msg


async def publish_message(redis: Redis, channel: str, message: dict) -> int:
    """Publish a JSON message to a Redis channel."""
    payload = json.dumps(message, ensure_ascii=False)
    return await redis.publish(channel, payload)
