"""
ScholarMind 缓存工具
支持内存缓存（默认）和 Redis 缓存两种模式

P1 Task 11 修复：
- CacheManager 改用 OrderedDict + maxsize LRU 淘汰，防止无界增长撑爆内存。
- cache_result 装饰器改为共享 default_cache 实例（而非每个函数独立 CacheManager）。
- cache_key 加入 func.__module__ 并用 json.dumps(sort_keys=True) 保证 dict 参数稳定。
"""
from __future__ import annotations

import json
import time
import functools
from collections import OrderedDict
from typing import Any, Callable, Optional


class CacheManager:
    """通用缓存管理器（带 LRU 淘汰）

    用法：
        cache = CacheManager(default_ttl=300, maxsize=1000)
        cache.set("key", value)
        value = cache.get("key")
    """

    def __init__(self, default_ttl: int = 300, maxsize: int = 1000):
        # P1 Task 11：OrderedDict 维持 LRU 顺序，maxsize 上限淘汰最旧
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._default_ttl = default_ttl
        self._maxsize = maxsize

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值（自动检查过期）"""
        if key not in self._cache:
            return None
        value, expiry = self._cache[key]
        if time.time() > expiry:
            del self._cache[key]
            return None
        # P1 Task 11：命中后移到末尾（最近使用），维持 LRU 顺序
        self._cache.move_to_end(key)
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """设置缓存值"""
        ttl = ttl or self._default_ttl
        self._cache[key] = (value, time.time() + ttl)
        # P1 Task 11：写入/更新后移到末尾（最近使用）
        self._cache.move_to_end(key)
        # 超过 maxsize 时淘汰最旧（LRU 淘汰）
        if len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)

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


# 全局缓存实例（cache_result 装饰器共享此实例，避免每个函数独立 CacheManager）
default_cache = CacheManager()


def cache_result(ttl: int = 300, key_func: Optional[Callable] = None):
    """缓存装饰器

    P1 Task 11：改用共享 default_cache 实例（受全局 maxsize=1000 LRU 约束），
    cache_key 加入 func.__module__ 并用 json.dumps(sort_keys=True) 保证 dict 参数稳定。

    用法：
        @cache_result(ttl=600)
        async def expensive_operation(arg1, arg2):
            ...

        @cache_result(ttl=300, key_func=lambda query, **kw: f"search:{query}")
        async def search(query, limit=10):
            ...
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                # P1 Task 11：module.name + json.dumps(sort_keys=True) 保证 dict 参数稳定
                cache_key = (
                    f"{func.__module__}.{func.__name__}:"
                    f"{json.dumps(args, default=str)}:"
                    f"{json.dumps(kwargs, sort_keys=True, default=str)}"
                )

            cached = default_cache.get(cache_key)
            if cached is not None:
                return cached

            result = await func(*args, **kwargs)
            default_cache.set(cache_key, result, ttl)
            return result

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = (
                    f"{func.__module__}.{func.__name__}:"
                    f"{json.dumps(args, default=str)}:"
                    f"{json.dumps(kwargs, sort_keys=True, default=str)}"
                )

            cached = default_cache.get(cache_key)
            if cached is not None:
                return cached

            result = func(*args, **kwargs)
            default_cache.set(cache_key, result, ttl)
            return result

        # Task 27: 自动检测 sync/async 函数，返回对应 wrapper
        import inspect as _inspect
        if _inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
