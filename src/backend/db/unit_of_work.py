"""
ScholarMind 工作单元（Unit of Work）
统一管理跨Repository的事务边界，确保多个Repository操作在同一事务中执行。
模式：企业级 Unit of Work + Repository 组合模式
"""
from __future__ import annotations

import structlog
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .repository.conversation import ConversationRepository
from .repository.skill import SkillRepository
from .repository.chart import ChartRepository

logger = structlog.get_logger(__name__)


class UnitOfWork:
    """工作单元：管理事务边界和Repository实例化

    用法：
        async with UnitOfWork(session_factory) as uow:
            await uow.conversations.add_message(...)
            await uow.charts.save_record(...)
            await uow.commit()          # 统一提交

    自动回滚：如果 async with 块内抛出异常，自动回滚所有操作。
    手动控制：可调用 uow.rollback() 主动回滚。

    Repository 访问：
        uow.conversations  → ConversationRepository
        uow.skills         → SkillRepository
        uow.charts         → ChartRepository
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory
        self._session: Optional[AsyncSession] = None

        # Repository 实例（延迟初始化）
        self.conversations: Optional[ConversationRepository] = None
        self.skills: Optional[SkillRepository] = None
        self.charts: Optional[ChartRepository] = None

    async def __aenter__(self) -> UnitOfWork:
        self._session = self._session_factory()
        self.conversations = ConversationRepository(self._session)
        self.skills = SkillRepository(self._session)
        self.charts = ChartRepository(self._session)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            if exc_type is not None:
                await self._session.rollback()
                self._report_rollback(exc_type.__name__)
        finally:
            await self._session.close()
            self._session = None

    async def commit(self) -> None:
        """提交当前事务"""
        if self._session is None:
            raise RuntimeError("UnitOfWork not entered (use async with)")
        await self._session.commit()

    async def rollback(self) -> None:
        """回滚当前事务"""
        if self._session is None:
            raise RuntimeError("UnitOfWork not entered (use async with)")
        await self._session.rollback()

    async def flush(self) -> None:
        """刷新挂起的变更到数据库（不提交）"""
        if self._session is not None:
            await self._session.flush()

    @property
    def session(self) -> AsyncSession:
        """获取原始数据库会话（谨慎使用）"""
        if self._session is None:
            raise RuntimeError("UnitOfWork not entered (use async with)")
        return self._session

    @staticmethod
    def _report_rollback(exc_name: str) -> None:
        """记录回滚事件"""
        logger.debug(f"UnitOfWork rolled back due to exception exception={exc_name}")