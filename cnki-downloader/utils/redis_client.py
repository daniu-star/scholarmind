"""Redis async client with connection pool and reconnection."""

from __future__ import annotations

import asyncio
import structlog
from typing import Optional, Any

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool

from config.settings import settings

logger = structlog.get_logger()


class RedisClient:
    """Async Redis client wrapper with auto-reconnection."""

    _instance: Optional[Redis] = None
    _pool: Optional[ConnectionPool] = None

    @classmethod
    async def get_client(cls) -> Redis:
        """Get or create Redis client singleton."""
        if cls._instance is None:
            cls._pool = ConnectionPool.from_url(
                settings.REDIS_URL,
                max_connections=50,
                socket_connect_timeout=5,
                socket_keepalive=True,
                health_check_interval=30,
                retry_on_timeout=True,
            )
            cls._instance = Redis(connection_pool=cls._pool)
            logger.info("redis_client_created", url=settings.REDIS_URL)
        return cls._instance

    @classmethod
    async def health_check(cls) -> bool:
        """Ping Redis to verify connectivity."""
        try:
            client = await cls.get_client()
            return await client.ping()
        except Exception as e:
            logger.error("redis_health_check_failed", error=str(e))
            return False

    @classmethod
    async def close(cls) -> None:
        """Gracefully close Redis connections."""
        if cls._instance:
            await cls._instance.close()
            cls._instance = None
        if cls._pool:
            await cls._pool.disconnect()
            cls._pool = None
        logger.info("redis_client_closed")


async def get_redis() -> Redis:
    """Dependency injection helper."""
    return await RedisClient.get_client()
