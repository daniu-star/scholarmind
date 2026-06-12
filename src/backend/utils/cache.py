"""
ScholarMind 缓存工具
支持内存缓存（默认）和 Redis 缓存两种模式
"""
from __future__ import annotations

import time
import functools
from typing import Any, Callable, Optional


class CacheManager:
    """通用缓存管理器

    用法：
        cache = CacheManager(default_ttl=300)
        cache.set("key", value)
        value = cache.get("key")
    """

    def __init__(self, default_ttl: int = 300):
        self._cache: dict[str, tuple[Any, float]] = {}
        self._default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值（自动检查过期）"""
        if key not in self._cache:
            return None
        value, expiry = self._cache[key]
        if time.time() > expiry:
            del self._cache[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """设置缓存值"""
        ttl = ttl or self._default_ttl
        self._cache[key] = (value, time.time() + ttl)

    def delete(self, key: str) -> None:
        """删除缓存"""
        self._cache.pop(key, None)

    def clear(self) -> None:
        """清空所有缓存"""
        self._cache.clear()

    def get_or_set(
        self, key: str, factory: Callable[[], Any], ttl: Optional[int] = None
    ) -> Any:
        """获取缓存值，不存在时通过 factory 生成并缓存"""
        value = self.get(key)
        if value is None:
            value = factory()
            self.set(key, value, ttl)
        return value

    @property
    def size(self) -> int:
        """当前缓存条目数"""
        self._clean_expired()
        return len(self._cache)

    def _clean_expired(self) -> int:
        """清理过期条目，返回清理数量"""
        now = time.time()
        expired = [k for k, (_, exp) in self._cache.items() if now > exp]
        for k in expired:
            del self._cache[k]
        return len(expired)


def cache_result(ttl: int = 300, key_func: Optional[Callable] = None):
    """缓存装饰器

    用法：
        @cache_result(ttl=600)
        async def expensive_operation(arg1, arg2):
            ...

        @cache_result(ttl=300, key_func=lambda query, **kw: f"search:{query}")
        async def search(query, limit=10):
            ...
    """
    cache = CacheManager(default_ttl=ttl)

    def decorator(func: Callable):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"

            cached = cache.get(cache_key)
            if cached is not None:
                return cached

            result = await func(*args, **kwargs)
            cache.set(cache_key, result, ttl)
            return result

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"

            cached = cache.get(cache_key)
            if cached is not None:
                return cached

            result = func(*args, **kwargs)
            cache.set(cache_key, result, ttl)
            return result

        return async_wrapper

    return decorator


# 全局缓存实例
default_cache = CacheManager()