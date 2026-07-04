"""
ScholarMind 技能仓储
管理技能配置的 CRUD 操作
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .base import BaseRepository
from ...models.orm import Skill


class SkillRepository(BaseRepository[Skill]):
    """技能配置数据仓储"""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Skill)

    async def get_by_skill_id(self, skill_id: str) -> Optional[Skill]:
        """通过 skill_id（唯一标识符，如 'academic-researcher'）查找"""
        result = await self.db.execute(
            select(Skill).where(Skill.skill_id == skill_id)
        )
        return result.scalar_one_or_none()

    async def list_enabled(self) -> Sequence[Skill]:
        """获取所有已启用的技能"""
        result = await self.db.execute(
            select(Skill).where(Skill.enabled)
        )
        return result.scalars().all()

    async def list_by_agent(self, agent_id: str) -> Sequence[Skill]:
        """获取与指定 Agent 关联的已启用技能"""
        result = await self.db.execute(
            select(Skill)
            .where(
                Skill.enabled,
                Skill.agents.contains(agent_id),
            )
        )
        return result.scalars().all()

    async def list_by_category(self, category: str) -> Sequence[Skill]:
        """按分类获取技能"""
        result = await self.db.execute(
            select(Skill).where(Skill.category == category)
        )
        return result.scalars().all()

    async def toggle_enabled(
        self, skill_id: str, enabled: bool
    ) -> Optional[Skill]:
        """切换技能启用状态"""
        skill = await self.get_by_skill_id(skill_id)
        if skill is None:
            return None
        skill.enabled = enabled
        skill.updated_at = datetime.now(timezone.utc)
        return await self.update(skill)

    async def seed_preset_skills(self, presets: list[dict]) -> int:
        """初始化预设技能（幂等操作，已存在的不会重复插入）

        Returns:
            实际插入的数量
        """
        inserted = 0
        for preset in presets:
            existing = await self.get_by_skill_id(preset["skill_id"])
            if existing is None:
                skill = Skill(
                    skill_id=preset["skill_id"],
                    display_name=preset["display_name"],
                    description=preset.get("description", ""),
                    category=preset["category"],
                    enabled=preset.get("enabled", True),
                    agents=preset.get("agents", []),
                    triggers=preset.get("triggers", []),
                    rules=preset.get("rules", ""),
                    is_preset=preset.get("is_preset", True),
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                self.db.add(skill)
                inserted += 1

        if inserted > 0:
            await self.db.flush()
        return inserted