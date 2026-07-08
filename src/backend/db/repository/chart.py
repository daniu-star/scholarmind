"""
ScholarMind 图表记录仓储
管理图表生成记录的 CRUD 操作
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from .base import BaseRepository
from ...models.orm import ChartRecord


class ChartRepository(BaseRepository[ChartRecord]):
    """图表记录数据仓储"""

    def __init__(self, db: AsyncSession):
        super().__init__(db, ChartRecord)

    async def get_by_chart_id(self, chart_id: str) -> Optional[ChartRecord]:
        """通过 UUID 查找图表记录"""
        result = await self.db.execute(
            select(ChartRecord).where(ChartRecord.chart_id == chart_id)
        )
        return result.scalar_one_or_none()

    async def list_by_session(
        self, session_id: str, limit: int = 20
    ) -> Sequence[ChartRecord]:
        """获取某会话的所有图表记录"""
        result = await self.db.execute(
            select(ChartRecord)
            .where(ChartRecord.session_id == session_id)
            .order_by(ChartRecord.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def save_record(
        self,
        chart_id: str,
        chart_type: str,
        title: str,
        filepath: str,
        session_id: str,
    ) -> ChartRecord:
        """保存图表生成记录"""
        record = ChartRecord(
            chart_id=chart_id,
            chart_type=chart_type,
            title=title,
            filepath=filepath,
            session_id=session_id,
            created_at=datetime.now(timezone.utc),
        )
        return await self.create(record)

    async def count_by_type(self, chart_type: str) -> int:
        """统计某类型图表的生成数量（使用 COUNT 避免全表加载）"""
        result = await self.db.execute(
            select(func.count()).where(ChartRecord.chart_type == chart_type)
        )
        return result.scalar() or 0