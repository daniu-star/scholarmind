"""
ScholarMind 对话仓储
管理对话历史的 CRUD 操作
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy import select, delete, desc
from sqlalchemy.ext.asyncio import AsyncSession

from .base import BaseRepository
from ...models.orm import Conversation


class ConversationRepository(BaseRepository[Conversation]):
    """对话历史数据仓储"""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Conversation)

    async def get_by_session(
        self, session_id: str, limit: int = 40
    ) -> Sequence[Conversation]:
        """按 session_id 获取对话历史（按时间正序，最近 N 条）"""
        subq = (
            select(Conversation)
            .where(Conversation.session_id == session_id)
            .order_by(desc(Conversation.created_at))
            .limit(limit)
            .subquery()
        )
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.id.in_(
                select(subq.c.id)
            ))
            .order_by(Conversation.created_at.asc())
        )
        return result.scalars().all()

    async def add_message(
        self,
        session_id: str,
        agent_id: str,
        role: str,
        content: str,
    ) -> Conversation:
        """添加一条对话消息"""
        msg = Conversation(
            session_id=session_id,
            agent_id=agent_id,
            role=role,
            content=content,
            created_at=datetime.utcnow(),
        )
        return await self.create(msg)

    async def clear_session(self, session_id: str) -> int:
        """清空会话的所有消息，返回删除数量"""
        result = await self.db.execute(
            delete(Conversation).where(Conversation.session_id == session_id)
        )
        await self.db.flush()
        return result.rowcount

    async def list_sessions(self) -> list[str]:
        """获取所有不重复的 session_id"""
        result = await self.db.execute(
            select(Conversation.session_id).distinct()
        )
        return [row[0] for row in result.all()]

    async def get_session_count(self, session_id: str) -> int:
        """获取某个会话的消息数量"""
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.session_id == session_id)
        )
        return len(result.scalars().all())