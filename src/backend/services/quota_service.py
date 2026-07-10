from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.orm import UserQuota
from ..config import settings
from datetime import datetime, timezone, timedelta


class QuotaService:
    @staticmethod
    async def check_quota(db: AsyncSession, user_id: int, estimated_tokens: int = 0) -> bool:
        result = await db.execute(select(UserQuota).where(UserQuota.user_id == user_id))
        quota = result.scalar_one_or_none()
        if not quota:
            return False
        return quota.tokens_used + estimated_tokens < quota.tokens_limit

    @staticmethod
    async def deduct_tokens(db: AsyncSession, user_id: int, tokens: int):
        """扣除 token 配额（不提交事务，由调用方管理事务边界）。

        🔴 修复: 移除内部 commit()，避免破坏调用方的事务一致性。
        """
        await db.execute(
            update(UserQuota).where(UserQuota.user_id == user_id)
            .values(tokens_used=UserQuota.tokens_used + tokens)
        )

    @staticmethod
    async def get_usage(db: AsyncSession, user_id: int) -> dict:
        result = await db.execute(select(UserQuota).where(UserQuota.user_id == user_id))
        quota = result.scalar_one_or_none()
        if not quota:
            return {"used": 0, "limit": settings.FREE_TIER_TOKEN_LIMIT, "plan": "free"}
        return {"used": quota.tokens_used, "limit": quota.tokens_limit, "plan": quota.plan, "expires_at": quota.expires_at}

    @staticmethod
    async def upgrade_plan(db: AsyncSession, user_id: int, plan: str, duration_days: int):
        """升级套餐（不提交事务，由调用方管理事务边界）。"""
        limit = settings.PRO_TIER_TOKEN_LIMIT if plan.startswith("pro") else settings.FREE_TIER_TOKEN_LIMIT
        expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=duration_days)
        result = await db.execute(select(UserQuota).where(UserQuota.user_id == user_id))
        quota = result.scalar_one_or_none()
        if quota:
            quota.plan = plan
            quota.tokens_limit = limit
            quota.expires_at = expires
        else:
            quota = UserQuota(user_id=user_id, plan=plan, tokens_limit=limit, expires_at=expires)
            db.add(quota)
