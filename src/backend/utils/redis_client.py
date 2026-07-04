"""
Redis 异步客户端单例

提供 redis.asyncio.Redis 的单例访问，供：
- PipelineStateRepo 持久化 pipeline/review 状态
- RedisRateLimitMiddleware 分布式限流
- 其他需要共享状态的场景

特性：
- 懒加载，首次调用时初始化
- ping 健康检查
- 不可用时返回 None（调用方需自行降级）
"""
from __future__ import annotations

import structlog
from typing import Optional

from src.backend.config import settings

logger = structlog.get_logger(__name__)

# redis.asyncio 在 Python 3.8+ 可用
try:
    import redis.asyncio as aioredis
    _REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REDIS_AVAILABLE = False
    aioredis = None  # type: ignore


_redis_client: Optional["aioredis.Redis"] = None
_redis_available: Optional[bool] = None  # None=未检测, True=可用, False=不可用


async def get_redis() -> Optional["aioredis.Redis"]:
    """获取 Redis 异步客户端单例

    Returns:
        redis.asyncio.Redis 实例；若 Redis 不可用则返回 None
    """
    global _redis_client, _redis_available

    if not _REDIS_AVAILABLE:
        if _redis_available is None:
            logger.warning("redis_package_unavailable hint=pip install redis>=5.0.0")
            _redis_available = False
        return None

    if _redis_client is not None and _redis_available:
        return _redis_client

    if _redis_available is False:
        return None

    try:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=5,
        )
        await _redis_client.ping()
        _redis_available = True
        logger.info(f"redis_connected url={settings.REDIS_URL}")
        return _redis_client
    except Exception as e:
        _redis_available = False
        _redis_client = None
        logger.warning(
            f"redis_unavailable url={settings.REDIS_URL} error={e} hint=Pipeline 状态将降级为内存模式"
        )
        return None


async def close_redis() -> None:
    """关闭 Redis 连接（应用 shutdown 时调用）"""
    global _redis_client, _redis_available
    if _redis_client is not None:
        try:
            await _redis_client.close()
        except Exception as e:
            logger.warning(f"redis_close_error error={e}")
        finally:
            _redis_client = None
            _redis_available = None


def is_redis_available() -> bool:
    """查询 Redis 是否可用（必须先调用 get_redis 检测）"""
    return bool(_redis_available)


async def reset_redis_state() -> None:
    """重置 Redis 状态（仅供测试使用）"""
    global _redis_client, _redis_available
    if _redis_client is not None:
        try:
            await _redis_client.close()
        except Exception:
            pass
    _redis_client = None
    _redis_available = None
