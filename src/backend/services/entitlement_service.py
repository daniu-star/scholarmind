"""账户权益、对话次数和 Pipeline 额度的原子化领域服务。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.orm import EntitlementGrant, User, UserQuota
from ..config import settings
from ..core.datetime_utils import as_utc

PipelineCapability = Literal["generation", "external_review", "modification"]

PRODUCTS: dict[str, dict] = {
    "paper_once": {
        "id": "paper_once",
        "name": "单次论文生成",
        "amount_cents": 499,
        "description": "1 次一键生成论文 Pipeline",
    },
    "paper_bundle_5": {
        "id": "paper_bundle_5",
        "name": "论文进阶包",
        "amount_cents": 1999,
        "description": "5 次论文生成或修改，外审专家服务 30 天",
    },
    "monthly_all": {
        "id": "monthly_all",
        "name": "全功能月度会员",
        "amount_cents": 3990,
        "description": "全部功能 30 天，使用 Flash 模型",
    },
    "monthly_pro": {
        "id": "monthly_pro",
        "name": "全功能 Pro 月度会员",
        "amount_cents": 5990,
        "description": "全部功能 30 天，使用 Pro 模型",
    },
}


class EntitlementError(PermissionError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _active(value: datetime | None, now: datetime) -> bool:
    value = as_utc(value)
    return bool(value and value > now)


def _extend_30_days(value: datetime | None, now: datetime) -> datetime:
    base = as_utc(value)
    if base is None or base < now:
        base = now
    return base + timedelta(days=30)


class EntitlementService:
    @staticmethod
    async def ensure_quota(db: AsyncSession, user_id: int) -> UserQuota:
        result = await db.execute(
            select(UserQuota).where(UserQuota.user_id == user_id)
        )
        quota = result.scalar_one_or_none()
        if quota is None:
            # 使用原始 SQL 插入（避免 ORM 的 NOT NULL 默认值问题）
            from sqlalchemy import text as _t
            await db.execute(
                _t(
                    "INSERT INTO user_quotas (user_id, tokens_used, tokens_limit, plan, "
                    "free_chats_used, free_chat_limit, generation_credits, "
                    "shared_pipeline_credits, model_tier, created_at, updated_at) "
                    "VALUES (:uid, 0, :limit, 'free', 0, :chat_limit, 0, 0, 'flash', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    " ON CONFLICT (user_id) DO NOTHING"
                ),
                {"uid": user_id, "limit": settings.FREE_TIER_TOKEN_LIMIT,
                 "chat_limit": settings.FREE_CHAT_LIMIT},
            )
            await db.flush()
            # 重新查询以获取 ORM 对象
            result2 = await db.execute(
                select(UserQuota).where(UserQuota.user_id == user_id)
            )
            quota = result2.scalar_one()
        return quota

    @staticmethod
    async def get_snapshot(db: AsyncSession, user_id: int) -> dict:
        quota = await EntitlementService.ensure_quota(db, user_id)
        now = datetime.now(timezone.utc)
        membership_active = _active(quota.membership_expires_at, now)
        external_active = membership_active or _active(
            quota.external_review_expires_at, now
        )
        remaining = max(0, quota.free_chat_limit - quota.free_chats_used)
        generation_access = (
            membership_active
            or quota.generation_credits > 0
            or quota.shared_pipeline_credits > 0
        )
        modification_access = membership_active or quota.shared_pipeline_credits > 0
        return {
            "plan": quota.plan,
            "free_chats_used": quota.free_chats_used,
            "free_chat_limit": quota.free_chat_limit,
            "free_chats_remaining": remaining,
            "generation_credits": quota.generation_credits,
            "shared_pipeline_credits": quota.shared_pipeline_credits,
            "modification_credits": quota.shared_pipeline_credits,
            "external_review_active": external_active,
            "external_review_expires_at": (
                quota.external_review_expires_at.isoformat()
                if quota.external_review_expires_at
                else None
            ),
            "membership_active": membership_active,
            "membership_expires_at": (
                quota.membership_expires_at.isoformat()
                if quota.membership_expires_at
                else None
            ),
            "unlimited_chat": membership_active,
            "unlimited_pipeline": membership_active,
            "model_tier": quota.model_tier if membership_active else "flash",
            "pipeline_access": {
                "generation": generation_access,
                "external_review": external_active,
                "modification": modification_access,
            },
        }

    @staticmethod
    async def consume_chat(db: AsyncSession, user_id: int) -> dict:
        quota = await EntitlementService.ensure_quota(db, user_id)
        now = datetime.now(timezone.utc)
        if _active(quota.membership_expires_at, now):
            snapshot = await EntitlementService.get_snapshot(db, user_id)
            snapshot["consumed"] = "unlimited"
            return snapshot

        try:
            result = await db.execute(
                update(UserQuota)
                .where(
                    UserQuota.user_id == user_id,
                    UserQuota.free_chats_used < UserQuota.free_chat_limit,
                )
                .values(free_chats_used=UserQuota.free_chats_used + 1)
            )
        except Exception as e:
            raise EntitlementError(
                "ENTITLEMENT_SERVICE_ERROR",
                f"配额服务暂时不可用，请稍后重试。",
            ) from e
        if result.rowcount != 1:
            raise EntitlementError(
                "CHAT_QUOTA_EXHAUSTED",
                "20 次免费对话已用完，请购买月度会员后继续使用。",
            )
        await db.flush()
        snapshot = await EntitlementService.get_snapshot(db, user_id)
        snapshot["consumed"] = "free_chat"
        return snapshot

    @staticmethod
    async def refund_chat(db: AsyncSession, user_id: int, consumed: str) -> None:
        if consumed != "free_chat":
            return
        try:
            await db.execute(
                update(UserQuota)
                .where(UserQuota.user_id == user_id, UserQuota.free_chats_used > 0)
                .values(free_chats_used=UserQuota.free_chats_used - 1)
            )
        except Exception:
            pass  # 退还不应阻断主流程

    @staticmethod
    async def require_external_reviewer(db: AsyncSession, user_id: int) -> None:
        snapshot = await EntitlementService.get_snapshot(db, user_id)
        if not snapshot["external_review_active"]:
            raise EntitlementError(
                "PAYMENT_REQUIRED",
                "外审专家服务仅对论文进阶包或月度会员开放。",
            )

    @staticmethod
    async def consume_pipeline(
        db: AsyncSession, user_id: int, capability: PipelineCapability
    ) -> dict:
        quota = await EntitlementService.ensure_quota(db, user_id)
        now = datetime.now(timezone.utc)
        if _active(quota.membership_expires_at, now):
            return {"consumed": "unlimited", "capability": capability}

        if capability == "external_review":
            if _active(quota.external_review_expires_at, now):
                return {"consumed": "external_subscription", "capability": capability}
            raise EntitlementError(
                "PAYMENT_REQUIRED",
                "专家修订论文需要论文进阶包或月度会员。",
            )

        if capability == "generation":
            try:
                result = await db.execute(
                    update(UserQuota)
                    .where(
                        UserQuota.user_id == user_id,
                        UserQuota.generation_credits > 0,
                    )
                    .values(generation_credits=UserQuota.generation_credits - 1)
                )
            except Exception as e:
                raise EntitlementError(
                    "ENTITLEMENT_SERVICE_ERROR",
                    "配额服务暂时不可用，请稍后重试。",
                ) from e
            if result.rowcount == 1:
                return {"consumed": "generation_credit", "capability": capability}

        try:
            result = await db.execute(
                update(UserQuota)
                .where(
                    UserQuota.user_id == user_id,
                    UserQuota.shared_pipeline_credits > 0,
                )
                .values(shared_pipeline_credits=UserQuota.shared_pipeline_credits - 1)
            )
        except Exception as e:
            raise EntitlementError(
                "ENTITLEMENT_SERVICE_ERROR",
                "配额服务暂时不可用，请稍后重试。",
            ) from e
        if result.rowcount == 1:
            return {"consumed": "shared_pipeline_credit", "capability": capability}

        raise EntitlementError(
            "PAYMENT_REQUIRED",
            "该快速通道需要有效的论文额度或月度会员。",
        )

    @staticmethod
    async def refund_pipeline(
        db: AsyncSession, user_id: int, reservation: dict
    ) -> None:
        consumed = reservation.get("consumed")
        if consumed == "generation_credit":
            values = {"generation_credits": UserQuota.generation_credits + 1}
        elif consumed == "shared_pipeline_credit":
            values = {
                "shared_pipeline_credits": UserQuota.shared_pipeline_credits + 1
            }
        else:
            return
        await db.execute(
            update(UserQuota).where(UserQuota.user_id == user_id).values(**values)
        )

    @staticmethod
    async def grant_product(
        db: AsyncSession,
        user_id: int,
        product_id: str,
        source_ref: str,
    ) -> dict:
        if product_id not in PRODUCTS:
            raise ValueError(f"unknown product: {product_id}")

        existing = await db.execute(
            select(EntitlementGrant).where(
                EntitlementGrant.source_ref == source_ref
            )
        )
        if existing.scalar_one_or_none() is not None:
            return await EntitlementService.get_snapshot(db, user_id)

        quota = await EntitlementService.ensure_quota(db, user_id)
        now = datetime.now(timezone.utc)
        if product_id == "paper_once":
            quota.generation_credits += 1
        elif product_id == "paper_bundle_5":
            quota.shared_pipeline_credits += 5
            quota.external_review_expires_at = _extend_30_days(
                quota.external_review_expires_at, now
            )
        elif product_id in {"monthly_all", "monthly_pro"}:
            quota.membership_expires_at = _extend_30_days(
                quota.membership_expires_at, now
            )
            quota.external_review_expires_at = quota.membership_expires_at
            quota.model_tier = "pro" if product_id == "monthly_pro" else "flash"

        quota.plan = product_id
        user = await db.get(User, user_id)
        if user is not None:
            user.plan = product_id
        db.add(
            EntitlementGrant(
                user_id=user_id,
                source_ref=source_ref,
                product_id=product_id,
            )
        )
        await db.flush()
        return await EntitlementService.get_snapshot(db, user_id)
