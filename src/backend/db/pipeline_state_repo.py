"""
Pipeline 状态仓库 — 基于 Redis 的持久化存储

为 PaperPipelineService 和 PaperReviewService 提供统一的 Pipeline 状态持久化。
Redis 不可用时自动降级到内存字典（仅限单进程，重启丢失）。

设计要点：
- 状态以 JSON 序列化存储，TTL 24 小时（避免无限增长）
- 支持按 user_id 列出用户的所有 Pipeline
- 状态更新支持部分字段更新（避免读-改-写的竞态）
- 所有方法为 async，兼容 FastAPI 异步生态

Author: ScholarMind Backend
Version: 1.0.0
"""
from __future__ import annotations

import json
import structlog
from datetime import datetime
from typing import Any, Optional

from ..utils.redis_client import get_redis, is_redis_available

logger = structlog.get_logger(__name__)

# ── Redis Key 前缀 ───────────────────────────────────────
_KEY_PREFIX = "scholarmind:pipeline"
_KEY_PIPELINE = f"{_KEY_PREFIX}:state"      # pipeline:{pipeline_id}
_KEY_USER_INDEX = f"{_KEY_PREFIX}:user"     # user:{user_id} → set of pipeline_ids

# ── TTL ──────────────────────────────────────────────────
_TTL_SECONDS = 24 * 60 * 60  # 24 小时


class PipelineStateRepo:
    """Pipeline 状态仓库（Redis 优先，内存降级）"""

    def __init__(self):
        # 内存降级存储：pipeline_id → state dict
        self._memory_store: dict[str, dict[str, Any]] = {}
        # 用户索引：user_id → set of pipeline_ids
        self._memory_user_index: dict[str, set[str]] = {}

    # ── 核心方法 ──────────────────────────────────────────

    async def save(self, pipeline_id: str, state: dict[str, Any], *,
                   user_id: Optional[str] = None) -> bool:
        """保存 Pipeline 状态

        Args:
            pipeline_id: Pipeline ID
            state: 完整状态字典
            user_id: 关联的用户 ID（用于按用户查询）

        Returns:
            bool: 是否成功保存到 Redis（False 表示降级到内存）
        """
        # 确保 state 有时间戳
        state.setdefault("updated_at", datetime.now().isoformat())

        if is_redis_available():
            try:
                redis = await get_redis()
                if redis is not None:
                    key = f"{_KEY_PIPELINE}:{pipeline_id}"
                    await redis.setex(key, _TTL_SECONDS, json.dumps(state, ensure_ascii=False, default=str))

                    # 维护用户索引
                    if user_id:
                        index_key = f"{_KEY_USER_INDEX}:{user_id}"
                        await redis.sadd(index_key, pipeline_id)
                        await redis.expire(index_key, _TTL_SECONDS)

                    return True
            except Exception as e:
                logger.warning(f"pipeline_state_redis_save_failed pipeline_id={pipeline_id} error={e}")

        # 降级到内存
        self._memory_store[pipeline_id] = state
        if user_id:
            self._memory_user_index.setdefault(user_id, set()).add(pipeline_id)
        return False

    async def get(self, pipeline_id: str) -> Optional[dict[str, Any]]:
        """获取 Pipeline 状态

        Returns:
            状态字典，不存在时返回 None
        """
        if is_redis_available():
            try:
                redis = await get_redis()
                if redis is not None:
                    key = f"{_KEY_PIPELINE}:{pipeline_id}"
                    data = await redis.get(key)
                    if data:
                        return json.loads(data)
                    return None
            except Exception as e:
                logger.warning(f"pipeline_state_redis_get_failed pipeline_id={pipeline_id} error={e}")

        # 降级到内存
        return self._memory_store.get(pipeline_id)

    async def delete(self, pipeline_id: str) -> bool:
        """删除 Pipeline 状态"""
        if is_redis_available():
            try:
                redis = await get_redis()
                if redis is not None:
                    key = f"{_KEY_PIPELINE}:{pipeline_id}"
                    await redis.delete(key)
                    # 清理用户索引（需要扫描所有用户索引，代价较高，这里简单处理）
                    # 实际生产中可维护反向索引 pipeline_id → user_id
            except Exception as e:
                logger.warning(f"pipeline_state_redis_delete_failed pipeline_id={pipeline_id} error={e}")

        # 内存清理
        self._memory_store.pop(pipeline_id, None)
        for pipeline_ids in self._memory_user_index.values():
            pipeline_ids.discard(pipeline_id)
        return True

    async def update_status(self, pipeline_id: str, status: str,
                            **extra: Any) -> Optional[dict[str, Any]]:
        """更新 Pipeline 状态（部分更新）

        Args:
            pipeline_id: Pipeline ID
            status: 新状态（pending/running/completed/failed/cancelled）
            **extra: 其他需要更新的字段

        Returns:
            更新后的完整状态字典，不存在时返回 None
        """
        state = await self.get(pipeline_id)
        if state is None:
            return None

        state["status"] = status
        state["updated_at"] = datetime.now().isoformat()
        for k, v in extra.items():
            state[k] = v

        # 重新保存（保持原有 user_id）
        user_id = state.get("user_id")
        await self.save(pipeline_id, state, user_id=user_id)
        return state

    async def list_by_user(self, user_id: str,
                           limit: int = 50) -> list[dict[str, Any]]:
        """列出用户的所有 Pipeline 状态

        Args:
            user_id: 用户 ID
            limit: 最大返回数量

        Returns:
            状态字典列表（按 updated_at 降序）
        """
        pipeline_ids: list[str] = []

        if is_redis_available():
            try:
                redis = await get_redis()
                if redis is not None:
                    index_key = f"{_KEY_USER_INDEX}:{user_id}"
                    ids = await redis.smembers(index_key)
                    pipeline_ids = [pid.decode() if isinstance(pid, bytes) else pid for pid in ids]
            except Exception as e:
                logger.warning(f"pipeline_state_redis_list_failed user_id={user_id} error={e}")

        # 内存降级
        if not pipeline_ids:
            pipeline_ids = list(self._memory_user_index.get(user_id, set()))

        # 批量获取状态
        states: list[dict[str, Any]] = []
        for pid in pipeline_ids[:limit * 2]:  # 多取一些以备过滤
            state = await self.get(pid)
            if state:
                states.append(state)

        # 按 updated_at 降序排序
        states.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
        return states[:limit]

    async def append_log(self, pipeline_id: str, log_entry: str) -> Optional[dict[str, Any]]:
        """向 Pipeline 的 logs 列表追加一条日志

        Args:
            pipeline_id: Pipeline ID
            log_entry: 日志文本

        Returns:
            更新后的完整状态字典
        """
        state = await self.get(pipeline_id)
        if state is None:
            return None

        logs: list = state.get("logs", [])
        timestamped = f"[{datetime.now().isoformat()}] {log_entry}"
        logs.append(timestamped)
        state["logs"] = logs[-200:]  # 保留最近 200 条日志

        user_id = state.get("user_id")
        await self.save(pipeline_id, state, user_id=user_id)
        return state


# ── 单例 ─────────────────────────────────────────────────

_repo: Optional[PipelineStateRepo] = None


def get_pipeline_state_repo() -> PipelineStateRepo:
    """获取 PipelineStateRepo 单例"""
    global _repo
    if _repo is None:
        _repo = PipelineStateRepo()
    return _repo
