"""P0 Task 4.3: 模型策略服务（mode → 实际模型 ID 映射）

将客户端受控的 ``mode`` 枚举（``"flash" | "pro" | None``）按用户套餐
（``UserQuota.plan``）映射为实际 DeepSeek 模型 ID，禁止客户端任意指定模型字符串
绕过套餐与配额控制。

规则：
- ``mode=None``  → 套餐默认模型（Pro 套餐 → ``DEEPSEEK_MODEL_PRO``，其他 → ``DEEPSEEK_MODEL_FLASH``）
- ``mode="flash"`` → ``DEEPSEEK_MODEL_FLASH``（任意套餐可用，含免费）
- ``mode="pro"``  → ``DEEPSEEK_MODEL_PRO``（仅 Pro 套餐可用；免费/其他套餐抛
  ``ModelPolicyError``，Router 层映射为 HTTP 403）
- 非法 mode 值 → ``ValueError``（Router 层映射为 422；正常情况下 ChatRequest 的
  ``Literal`` 校验已先于本函数拦截）

设计说明：
- 直接基于 ``AsyncSession`` 查询 ``UserQuota.plan``，避免对 ``QuotaService`` 实例
  生命周期与 db session 耦合的假设；无配额记录视为 ``free``。
- Pro 套餐判定使用 ``plan.startswith("pro")``，兼容未来 ``pro_yearly`` / ``pro_monthly``
  等子套餐。
- 所有 logger 调用使用 f-string（project_memory.md 硬约束）。
"""
from __future__ import annotations

import structlog
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.orm import UserQuota
from .entitlement_service import EntitlementService

logger = structlog.get_logger(__name__)


class ModelPolicyError(PermissionError):
    """模型策略错误：用户套餐不允许访问所请求的模型。

    Router 层捕获后映射为 HTTP 403（需升级套餐）。
    """


async def _get_user_plan(db: AsyncSession, user_id: int) -> str:
    """查询用户套餐。

    无 ``UserQuota`` 记录时视为 ``free``（与 ``QuotaService.get_usage`` 行为一致）。
    """
    result = await db.execute(
        select(UserQuota.plan).where(UserQuota.user_id == user_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        return "free"
    return plan


async def resolve_model(
    db: AsyncSession, user_id: int, mode: Optional[str]
) -> str:
    """根据用户套餐与 mode 映射实际模型 ID。

    Args:
        db: 异步数据库会话（由 Router 注入，与请求生命周期一致）
        user_id: 当前登录用户 ID
        mode: ``"flash"`` | ``"pro"`` | ``None``

    Returns:
        实际模型 ID 字符串（如 ``deepseek-v4-flash`` / ``deepseek-v4-pro``）

    Raises:
        ModelPolicyError: 免费用户请求 ``mode="pro"``
        ValueError: 非法 mode 值（理论上 ChatRequest Literal 已先拦截）
    """
    plan = await _get_user_plan(db, user_id)
    snapshot = await EntitlementService.get_snapshot(db, user_id)
    is_pro_plan = (
        snapshot["membership_active"] and snapshot["model_tier"] == "pro"
    ) or plan.startswith("pro")

    if mode is None:
        # 套餐默认模型：Pro 用户默认走 Pro 模型，其他用户走 Flash 模型
        model = settings.DEEPSEEK_MODEL_PRO if is_pro_plan else settings.DEEPSEEK_MODEL_FLASH
        logger.info(
            f"model_policy resolved user_id={user_id} plan={plan} mode=None -> model={model}"
        )
        return model

    if mode == "flash":
        # Flash 模型任意套餐可用
        logger.info(
            f"model_policy resolved user_id={user_id} plan={plan} mode=flash -> model={settings.DEEPSEEK_MODEL_FLASH}"
        )
        return settings.DEEPSEEK_MODEL_FLASH

    if mode == "pro":
        if not is_pro_plan:
            logger.warning(
                f"model_policy denied user_id={user_id} plan={plan} requested pro model"
            )
            raise ModelPolicyError(
                f"user {user_id} plan={plan} cannot access pro model, please upgrade your plan"
            )
        logger.info(
            f"model_policy resolved user_id={user_id} plan={plan} mode=pro -> model={settings.DEEPSEEK_MODEL_PRO}"
        )
        return settings.DEEPSEEK_MODEL_PRO

    # 理论不可达：ChatRequest 的 Literal["flash","pro"] 会先返回 422
    raise ValueError(f"invalid mode={mode}, expected one of: flash, pro, null")
