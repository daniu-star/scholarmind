"""
ScholarMind 数据仓储基类
提供泛型 CRUD 操作，所有具体仓储继承此类
"""
from __future__ import annotations

from typing import Any, Generic, List, Optional, Sequence, Type, TypeVar

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """泛型数据仓储基类

    用法：
        class ConversationRepository(BaseRepository[Conversation]):
            def __init__(self, db: AsyncSession):
                super().__init__(db, Conversation)
    """

    def __init__(self, db: AsyncSession, model: Type[T]):
        self.db = db
        self.model = model

    async def get_by_id(self, id: Any) -> Optional[T]:
        """根据主键获取单条记录"""
        result = await self.db.execute(
            select(self.model).where(self.model.id == id)
        )
        return result.scalar_one_or_none()

    async def list_all(
        self, offset: int = 0, limit: int = 100
    ) -> Sequence[T]:
        """分页获取所有记录"""
        result = await self.db.execute(
            select(self.model).offset(offset).limit(limit)
        )
        return result.scalars().all()

    async def count(self) -> int:
        """获取记录总数"""
        result = await self.db.execute(
            select(func.count()).select_from(self.model)
        )
        return result.scalar() or 0

    async def create(self, entity: T) -> T:
        """创建单条记录"""
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def bulk_create(self, entities: List[T]) -> List[T]:
        """批量创建记录"""
        self.db.add_all(entities)
        await self.db.flush()
        return entities

    async def update(self, entity: T) -> T:
        """更新记录"""
        await self.db.merge(entity)
        await self.db.flush()
        return entity

    async def delete(self, entity: T) -> None:
        """删除记录"""
        await self.db.delete(entity)
        await self.db.flush()

    async def delete_by_id(self, id: Any) -> bool:
        """根据主键删除记录，返回是否成功"""
        entity = await self.get_by_id(id)
        if entity:
            await self.delete(entity)
            return True
        return False