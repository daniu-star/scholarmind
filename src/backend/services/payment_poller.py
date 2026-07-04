"""Payment Order Poller — 24/7 后台订单追踪服务

设计原理：
- 每创建一个支付订单，Poller 开始轮询支付宝/微信的订单查询 API
- 轮询间隔采用指数退避：5s → 15s → 30s → 60s → 120s（最大 120s）
- 最长轮询时间 = 订单过期时间（15 分钟）
- 支付宝/微信回调（webhook）仍然是最快路径（秒级确认）
- 轮询是兜底机制：回调丢失时，Poller 仍能自动确认支付

生命周期：
- app startup → PaymentPoller.start()
- app shutdown → PaymentPoller.stop()
"""
from __future__ import annotations

import asyncio
import structlog
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..models.orm import Order
from .payment_gateway import (
    AlipayGateway,
    PaymentConfigurationError,
    PaymentProviderError,
    WeChatGateway,
)

logger = structlog.get_logger(__name__)

# ── 轮询配置 ──
_POLL_BACKOFF_SECONDS = [5, 15, 30, 60, 120]   # 指数退避序列
_MAX_POLL_ATTEMPTS = len(_POLL_BACKOFF_SECONDS)
_POLL_CYCLE_INTERVAL = 5                          # 主循环间隔（秒）
_ORDER_EXPIRE_MINUTES = 15                        # 订单过期时间


async def _mark_order_paid(db: AsyncSession, order_no: str, trade_no: str) -> bool:
    """原子地将订单置为 paid 并发放权益（复用 payment.py 的核心逻辑）"""
    from .entitlement_service import EntitlementService, PRODUCTS

    now = datetime.now(timezone.utc)
    # SELECT ... FOR UPDATE 暂不支持 SQLite，使用条件 UPDATE 保证幂等
    result = await db.execute(
        update(Order)
        .where(Order.order_no == order_no, Order.status == "pending")
        .values(status="paid", trade_no=trade_no, paid_at=now)
    )
    if result.rowcount != 1:
        return False  # 已被处理或状态异常

    order = (await db.execute(select(Order).where(Order.order_no == order_no))).scalar_one()
    product_id = order.plan
    # 兼容历史套餐 ID
    legacy_map = {"pro_monthly": "monthly_all", "pro_yearly": "monthly_all"}
    product_id = legacy_map.get(product_id, product_id)
    await EntitlementService.grant_product(
        db, order.user_id, product_id, f"payment:{order.order_no}"
    )
    await db.execute(
        update(Order)
        .where(Order.id == order.id)
        .values(entitlements_granted_at=now)
    )
    return True


async def _expire_order(db: AsyncSession, order_no: str) -> bool:
    """将过期订单标记为 expired"""
    result = await db.execute(
        update(Order)
        .where(Order.order_no == order_no, Order.status == "pending")
        .values(status="expired")
    )
    return result.rowcount == 1


class PaymentPoller:
    """后台支付订单轮询器 — 24/7 自动追踪资金流向"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory
        self._task: Optional[asyncio.Task] = None
        # 追踪每个订单的轮询次数
        self._poll_counts: dict[str, int] = {}

    async def start(self) -> None:
        """启动后台轮询任务"""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("payment_poller_started")

    async def stop(self) -> None:
        """停止后台轮询任务"""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("payment_poller_stopped")

    def track_order(self, order_no: str) -> None:
        """开始追踪一个新订单"""
        self._poll_counts[order_no] = 0
        logger.info(f"payment_poller_tracking order_no={order_no}")

    async def _poll_loop(self) -> None:
        """主轮询循环：每 5 秒检查所有待支付订单"""
        while True:
            try:
                await self._poll_pending_orders()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"payment_poller_cycle_error err={e}", exc_info=True)
            await asyncio.sleep(_POLL_CYCLE_INTERVAL)

    async def _poll_pending_orders(self) -> None:
        """查询所有 pending 订单并逐个轮询"""
        now = datetime.now(timezone.utc)

        async with self._session_factory() as db:
            # 查找所有待支付且未过期的订单
            result = await db.execute(
                select(Order).where(
                    Order.status == "pending",
                    Order.payment_mode == "api",
                ).limit(50)
            )
            orders = result.scalars().all()

            for order in orders:
                try:
                    await self._poll_single_order(db, order, now)
                except Exception as e:
                    logger.warning(
                        f"payment_poll_single_failed order_no={order.order_no} err={e}"
                    )

            await db.commit()

    async def _poll_single_order(
        self, db: AsyncSession, order: Order, now: datetime
    ) -> None:
        """轮询单个订单"""
        # 检查是否过期
        if order.expires_at:
            expire_time = order.expires_at.replace(tzinfo=timezone.utc) if order.expires_at.tzinfo is None else order.expires_at
            if now > expire_time:
                await _expire_order(db, order.order_no)
                self._poll_counts.pop(order.order_no, None)
                logger.info(f"payment_order_expired order_no={order.order_no}")
                return

        # 检查轮询次数：已达到最大次数则等待更久
        count = self._poll_counts.get(order.order_no, 0)
        if count >= _MAX_POLL_ATTEMPTS:
            # 已用完全部退避序列，每 120s 轮询一次直到过期
            if order.updated_at and (now - order.updated_at.replace(tzinfo=timezone.utc)).total_seconds() < 120:
                return
        else:
            # 检查是否到了下一次轮询时间
            backoff = _POLL_BACKOFF_SECONDS[min(count, _MAX_POLL_ATTEMPTS - 1)]
            if order.updated_at:
                updated = order.updated_at.replace(tzinfo=timezone.utc) if order.updated_at.tzinfo is None else order.updated_at
                if (now - updated).total_seconds() < backoff:
                    return

        # 执行查询
        gateway_cls = AlipayGateway if order.payment_method == "alipay" else WeChatGateway
        try:
            gateway = gateway_cls()
            result = await gateway.query_payment(order.order_no)
        except PaymentConfigurationError:
            # 商户凭证未配置 → 停止轮询此订单（不会自动确认）
            logger.warning(
                f"payment_poller_config_missing order_no={order.order_no} "
                f"method={order.payment_method}"
            )
            return
        except PaymentProviderError as e:
            logger.warning(f"payment_query_failed order_no={order.order_no} err={e}")
            return

        # 更新轮询计数和订单时间戳
        self._poll_counts[order.order_no] = count + 1
        order.updated_at = now

        if result is None:
            # 查询返回空（非终态）→ 继续等待
            return

        if result.get("is_paid"):
            # 支付成功！
            trade_no = result.get("trade_no") or f"POLLED_{order.order_no}"
            ok = await _mark_order_paid(db, order.order_no, trade_no)
            self._poll_counts.pop(order.order_no, None)
            logger.info(
                f"payment_poller_confirmed order_no={order.order_no} "
                f"trade_no={trade_no} method={order.payment_method} "
                f"poll_attempts={count + 1}"
            )
        elif result.get("trade_status") in ("TRADE_CLOSED", "CLOSED", "PAYERROR"):
            # 支付已关闭/失败
            await db.execute(
                update(Order)
                .where(Order.order_no == order.order_no, Order.status == "pending")
                .values(status="failed")
            )
            self._poll_counts.pop(order.order_no, None)
            logger.info(
                f"payment_order_closed order_no={order.order_no} "
                f"trade_status={result.get('trade_status')}"
            )


# ── 单例 ──
_poller: Optional[PaymentPoller] = None


def get_payment_poller() -> Optional[PaymentPoller]:
    return _poller


def init_payment_poller(session_factory: async_sessionmaker[AsyncSession]) -> PaymentPoller:
    global _poller
    if _poller is None:
        _poller = PaymentPoller(session_factory)
    return _poller
