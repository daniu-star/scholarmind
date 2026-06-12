"""
ScholarMind 事件总线（EventBus）
轻量级进程内事件驱动架构，解耦服务间直接调用。

设计原则：
  - 发布/订阅模式：Publisher 不感知 Subscriber
  - 异步分发：所有handler并发执行
  - 容错隔离：单个handler异常不影响其他handler
  - 类型安全：EventType枚举约束事件类型

用法：
    # 订阅
    event_bus.subscribe(EventType.CNKI_SEARCH_REQUESTED, handle_cnki_search)

    # 发布
    await event_bus.publish(
        EventType.CNKI_SEARCH_REQUESTED,
        query="机器学习",
        session_id="abc123",
    )
"""
from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """事件类型枚举 — 统一管理所有事件标识"""

    # ── CNKI 检索 ──
    CNKI_SEARCH_REQUESTED = "cnki.search.requested"
    CNKI_SEARCH_COMPLETED = "cnki.search.completed"
    CNKI_SEARCH_FAILED = "cnki.search.failed"

    # ── 图表生成 ──
    CHART_GENERATION_REQUESTED = "chart.generation.requested"
    CHART_GENERATION_COMPLETED = "chart.generation.completed"
    CHART_GENERATION_FAILED = "chart.generation.failed"

    # ── 技能检测 ──
    SKILL_DETECTED = "skill.detected"
    SKILL_EXECUTED = "skill.executed"
    SKILL_FAILED = "skill.failed"

    # ── 对话管理 ──
    CONVERSATION_UPDATED = "conversation.updated"
    CONVERSATION_CLEARED = "conversation.cleared"
    SESSION_CREATED = "session.created"

    # ── 文件上传 ──
    FILE_UPLOADED = "file.uploaded"
    FILE_DELETED = "file.deleted"

    # ── 系统事件 ──
    APP_STARTUP = "app.startup"
    APP_SHUTDOWN = "app.shutdown"
    ERROR_OCCURRED = "error.occurred"


# 事件处理器类型别名
EventHandler = Callable[..., Awaitable[Any]]


class EventBus:
    """轻量级进程内事件总线

    特性：
    - 异步并发分发：所有匹配的handler并发执行
    - 异常隔离：单个handler异常不影响其他handler执行
    - 通配符支持：可订阅 "*" 监听所有事件
    - 调试模式：记录事件发布和handler执行

    注意：
    - 此为进程内实现，不支持跨进程/跨服务事件
    - 不保证事件顺序
    - handler不应执行耗时操作（会阻塞事件循环）
    """

    def __init__(self, debug: bool = False):
        self._handlers: dict[str, list[EventHandler]] = {}
        self._wildcard_handlers: list[EventHandler] = []
        self._debug = debug

    # ── 订阅管理 ──────────────────────────────────────────

    def subscribe(
        self,
        event_type: EventType | str,
        handler: EventHandler,
    ) -> Callable[[], None]:
        """订阅事件

        Args:
            event_type: 事件类型（EventType枚举值 或 "*" 通配符）
            handler: 异步事件处理器

        Returns:
            取消订阅函数（调用即可取消）

        用法：
            unsubscribe = event_bus.subscribe(EventType.CNKI_SEARCH_REQUESTED, handler)
            # 稍后取消
            unsubscribe()
        """
        type_key = event_type.value if isinstance(event_type, EventType) else event_type

        if type_key == "*":
            self._wildcard_handlers.append(handler)
        else:
            if type_key not in self._handlers:
                self._handlers[type_key] = []
            self._handlers[type_key].append(handler)

        if self._debug:
            logger.debug("EventBus subscribed", event_type=type_key)

        # 返回取消订阅函数
        def unsubscribe():
            self.unsubscribe(event_type, handler)

        return unsubscribe

    def unsubscribe(
        self,
        event_type: EventType | str,
        handler: EventHandler,
    ) -> bool:
        """取消订阅

        Returns:
            是否成功取消
        """
        type_key = event_type.value if isinstance(event_type, EventType) else event_type

        if type_key == "*":
            if handler in self._wildcard_handlers:
                self._wildcard_handlers.remove(handler)
                return True
            return False

        handlers = self._handlers.get(type_key, [])
        if handler in handlers:
            handlers.remove(handler)
            if not handlers:
                del self._handlers[type_key]
            return True
        return False

    # ── 事件发布 ──────────────────────────────────────────

    async def publish(
        self,
        event_type: EventType | str,
        **event_data,
    ) -> int:
        """发布事件（异步并发分发）

        Args:
            event_type: 事件类型
            **event_data: 事件数据（以关键字参数传递给handler）

        Returns:
            成功执行的handler数量

        所有匹配的handler并发执行。单个handler的异常会被捕获并记录，
        不会影响其他handler的执行。
        """
        type_key = event_type.value if isinstance(event_type, EventType) else event_type

        # 收集所有匹配的handler
        handlers: list[EventHandler] = []
        handlers.extend(self._handlers.get(type_key, []))
        handlers.extend(self._wildcard_handlers)

        if not handlers:
            return 0

        if self._debug:
            logger.debug(
                "EventBus publishing",
                event_type=type_key,
                handler_count=len(handlers),
            )

        # 并发执行所有handler
        tasks = []
        for handler in handlers:
            tasks.append(self._safe_invoke(handler, type_key, **event_data))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 统计成功数
        success_count = sum(
            1 for r in results if not isinstance(r, Exception)
        )
        return success_count

    async def publish_sequential(
        self,
        event_type: EventType | str,
        **event_data,
    ) -> int:
        """顺序发布事件（按订阅顺序逐个执行）

        用于需要保证执行顺序的场景。
        """
        type_key = event_type.value if isinstance(event_type, EventType) else event_type

        handlers: list[EventHandler] = []
        handlers.extend(self._handlers.get(type_key, []))
        handlers.extend(self._wildcard_handlers)

        if not handlers:
            return 0

        success_count = 0
        for handler in handlers:
            try:
                await handler(**event_data)
                success_count += 1
            except Exception as e:
                logger.error(
                    f"EventBus handler error (sequential): {e}",
                    event_type=type_key,
                    handler=handler.__name__,
                )

        return success_count

    # ── 内部方法 ──────────────────────────────────────────

    async def _safe_invoke(
        self,
        handler: EventHandler,
        event_type: str,
        **event_data,
    ) -> None:
        """安全调用handler，捕获异常并记录"""
        try:
            await handler(**event_data)
        except Exception as e:
            logger.error(
                f"EventBus handler error: {e}",
                event_type=event_type,
                handler=getattr(handler, "__name__", str(handler)),
                exc_info=True,
            )

    # ── 状态查询 ──────────────────────────────────────────

    @property
    def subscriber_count(self) -> int:
        """总订阅数（不含通配符）"""
        return sum(len(h) for h in self._handlers.values())

    @property
    def event_types(self) -> list[str]:
        """所有已订阅的事件类型"""
        return list(self._handlers.keys())

    def clear(self) -> None:
        """清空所有订阅"""
        self._handlers.clear()
        self._wildcard_handlers.clear()


# ── 全局单例 ──────────────────────────────────────────────

event_bus = EventBus(debug=False)