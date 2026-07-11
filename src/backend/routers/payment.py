"""支付产品目录、下单、支付宝/微信回调和订单状态查询。

v2.0: 移除个人收款码模式 + OCR审核 + 人工确认。
所有支付通过官方 API + 实时回调 + 后台主动轮询 (PaymentPoller) 全自动完成。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.dependencies import get_db, require_admin
from ..core.logging_config import get_logger
from ..models.orm import Order, User, UserQuota
from ..services.entitlement_service import (
    PRODUCTS,
    EntitlementService,
)
from ..services.payment_gateway import (
    AlipayGateway,
    PaymentConfigurationError,
    PaymentProviderError,
    WeChatGateway,
    gateway_for,
)
from ..services.payment_poller import get_payment_poller, _mark_order_paid
from .auth import get_current_user

logger = get_logger(__name__)
router = APIRouter(prefix="/payment", tags=["payment"])


def verify_alipay_signature(data: dict) -> bool:
    return AlipayGateway().verify_notification(data)


def _legacy_product(product_id: str) -> str:
    return {
        "pro_monthly": "monthly_all",
        "pro_yearly": "monthly_all",
    }.get(product_id, product_id)


async def mark_order_paid(
    db: AsyncSession,
    order_no: str,
    trade_no: str,
    provider_payload: dict | None = None,
) -> str:
    """原子地将订单置为 paid 并发放权益（幂等，用于 webhook 回调）。"""
    from sqlalchemy import update as sa_update

    result = await db.execute(select(Order).where(Order.order_no == order_no))
    order = result.scalar_one_or_none()
    if order is None:
        return "failure"
    if order.status == "paid":
        return "success"
    if order.status != "pending":
        # 已失败/过期/拒绝的订单：返回 success 让支付宝停止重试
        return "success"

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    claimed = await db.execute(
        sa_update(Order)
        .where(Order.id == order.id, Order.status.in_(["pending", "reviewing"]))
        .values(
            status="paid",
            trade_no=trade_no,
            paid_at=now,
            provider_payload=provider_payload,
        )
    )
    if claimed.rowcount != 1:
        return "success"

    product_id = _legacy_product(order.plan)
    await EntitlementService.grant_product(
        db, order.user_id, product_id, f"payment:{order.order_no}"
    )
    await db.execute(
        sa_update(Order)
        .where(Order.id == order.id)
        .values(entitlements_granted_at=now)
    )

    if order.plan in {"monthly_all", "monthly_pro", "pro_monthly", "pro_yearly"}:
        await db.execute(
            sa_update(UserQuota)
            .where(UserQuota.user_id == order.user_id)
            .values(
                plan=order.plan,
                tokens_limit=settings.PRO_TIER_TOKEN_LIMIT,
            )
        )
        await db.execute(
            sa_update(User).where(User.id == order.user_id).values(plan=order.plan)
        )
    return "success"


# ── Schema ──

class CreateOrderRequest(BaseModel):
    product_id: Literal[
        "paper_once", "paper_bundle_5", "monthly_all", "monthly_pro"
    ]
    payment_method: Literal["wechat", "alipay"]


# ── 产品目录 ──

@router.get("/packages")
async def get_packages():
    # 仅返回已配置凭证的支付方式，避免用户选择后下单失败
    available_methods = []
    if settings.ALIPAY_APP_ID:
        available_methods.append("alipay")
    if settings.WECHAT_PAY_APP_ID:
        available_methods.append("wechat")
    return {
        "packages": [
            {
                **product,
                "price": f"{product['amount_cents'] / 100:.2f}",
            }
            for product in PRODUCTS.values()
        ],
        "payment_enabled": settings.PAYMENT_ENABLED,
        "methods": available_methods,
    }


# ── 下单 ──

@router.post("/orders")
async def create_order(
    req: CreateOrderRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建支付订单并返回支付链接。

    订单创建后，PaymentPoller 自动开始后台轮询追踪支付状态。
    支付宝/微信回调 + 轮询双重保障，无需人工介入。
    """
    if not settings.PAYMENT_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="支付尚未启用。请在服务端配置商户凭证并设置 PAYMENT_ENABLED=true",
        )

    product = PRODUCTS.get(req.product_id)
    if product is None:
        raise HTTPException(status_code=400, detail=f"未知产品: {req.product_id}")

    # 防滥用
    one_hour_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    recent_count = await db.scalar(
        select(func.count(Order.id)).where(
            Order.user_id == user.id, Order.created_at >= one_hour_ago
        )
    )
    if recent_count and recent_count >= 5:
        raise HTTPException(status_code=429, detail="操作过于频繁，请稍后再试")

    pending_count = await db.scalar(
        select(func.count(Order.id)).where(
            Order.user_id == user.id, Order.status == "pending",
        )
    )
    if pending_count and pending_count >= 3:
        raise HTTPException(status_code=429, detail="您有多个待支付订单，请先取消或等待过期")

    order_no = f"SM{datetime.now():%Y%m%d%H%M%S}{uuid.uuid4().hex[:8].upper()}"
    order = Order(
        order_no=order_no,
        user_id=user.id,
        plan=req.product_id,
        amount=product["amount_cents"],
        payment_method=req.payment_method,
        status="pending",
        payment_mode="api",
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=15),
    )
    db.add(order)
    await db.commit()

    gateway = gateway_for(req.payment_method)
    try:
        pay_result = await gateway.create_payment(
            order_no, product["amount_cents"], f"ScholarMind-{product['name']}"
        )
    except PaymentConfigurationError as exc:
        order.status = "failed"
        await db.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PaymentProviderError as exc:
        order.status = "failed"
        await db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # 启动后台轮询追踪
    poller = get_payment_poller()
    if poller:
        poller.track_order(order_no)

    return {
        "order_no": order_no,
        "pay_url": pay_result,
        "method": req.payment_method,
        "product": product,
        "expires_in_seconds": 900,
    }


# ── 支付宝回调 ──

@router.post("/alipay/notify", response_class=PlainTextResponse)
async def alipay_notify(request: Request, db: AsyncSession = Depends(get_db)):
    if not settings.PAYMENT_ENABLED:
        return "failure"
    form = await request.form()
    data = {key: value for key, value in form.items()}
    if not verify_alipay_signature(data):
        logger.warning(f"alipay signature rejected order_no={data.get('out_trade_no')}")
        return "failure"
    order_no = data.get("out_trade_no")
    trade_no = data.get("trade_no")
    if not order_no or not trade_no:
        return "failure"
    if data.get("trade_status") not in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
        return "failure"
    # P1 安全加固：app_id 与 total_amount 必须与配置/订单匹配，防止伪造回调
    if data.get("app_id") != settings.ALIPAY_APP_ID:
        logger.warning(f"alipay app_id mismatch order_no={order_no} got={data.get('app_id')}")
        return "failure"
    if settings.ALIPAY_SELLER_ID and data.get("seller_id") != settings.ALIPAY_SELLER_ID:
        logger.warning(
            f"alipay seller_id mismatch order_no={order_no} "
            f"expected={settings.ALIPAY_SELLER_ID} got={data.get('seller_id')}"
        )
        return "failure"
    result = await db.execute(select(Order).where(Order.order_no == order_no))
    order = result.scalar_one_or_none()
    if order is None or order.payment_method != "alipay":
        return "failure"
    # 金额校验：total_amount（元，字符串）必须与订单 amount_cents/100 一致
    try:
        notify_amount_yuan = float(data.get("total_amount", "0"))
    except (TypeError, ValueError):
        logger.warning(f"alipay total_amount invalid order_no={order_no} value={data.get('total_amount')!r}")
        return "failure"
    expected_amount_yuan = order.amount / 100.0
    if abs(notify_amount_yuan - expected_amount_yuan) > 0.001:
        logger.warning(
            f"alipay amount mismatch order_no={order_no} expected={expected_amount_yuan} got={notify_amount_yuan}"
        )
        return "failure"
    try:
        outcome = await mark_order_paid(
            db, order_no, trade_no,
            {"app_id": data.get("app_id"), "seller_id": data.get("seller_id"),
             "trade_status": data.get("trade_status")},
        )
        await db.commit()
        return outcome
    except Exception as exc:
        await db.rollback()
        logger.warning(f"alipay entitlement grant failed order_no={order_no} err={exc}")
        return "failure"


# ── 微信回调 ──

@router.post("/wechat/notify")
async def wechat_notify(request: Request, db: AsyncSession = Depends(get_db)):
    if not settings.PAYMENT_ENABLED:
        return {"code": "FAIL", "message": "payment disabled"}
    body = await request.body()
    headers = {key.lower(): value for key, value in request.headers.items()}
    try:
        notification = WeChatGateway().verify_and_decrypt(body, headers)
    except (PaymentConfigurationError, PaymentProviderError, ValueError) as exc:
        logger.warning(f"wechat notification rejected err={exc}")
        return {"code": "FAIL", "message": "signature or payload invalid"}

    transaction = notification.get("transaction") or {}
    order_no = transaction.get("out_trade_no")
    trade_no = transaction.get("transaction_id")
    if (
        notification.get("event_type") != "TRANSACTION.SUCCESS"
        or transaction.get("trade_state") != "SUCCESS"
        or not order_no or not trade_no
    ):
        return {"code": "FAIL", "message": "unexpected transaction state"}

    result = await db.execute(select(Order).where(Order.order_no == order_no))
    order = result.scalar_one_or_none()
    amount = transaction.get("amount") or {}
    if (
        order is None
        or order.payment_method != "wechat"
        or transaction.get("appid") != settings.WECHAT_PAY_APP_ID
        or transaction.get("mchid") != settings.WECHAT_PAY_MCH_ID
        or amount.get("total") != order.amount
        or amount.get("currency", "CNY") != "CNY"
    ):
        return {"code": "FAIL", "message": "transaction fields mismatch"}
    try:
        outcome = await mark_order_paid(
            db, order_no, trade_no,
            {"trade_state": transaction.get("trade_state"),
             "success_time": transaction.get("success_time")},
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning(f"wechat entitlement grant failed order_no={order_no} err={exc}")
        return {"code": "FAIL", "message": "internal error"}
    return (
        {"code": "SUCCESS", "message": "成功"}
        if outcome == "success"
        else {"code": "FAIL", "message": "order not found"}
    )


# ── 订单状态查询 ──

@router.get("/orders/{order_no}/status")
async def get_order_status(
    order_no: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Order).where(Order.order_no == order_no, Order.user_id == user.id)
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    return {
        "order_no": order.order_no,
        "status": order.status,
        "product_id": order.plan,
        "amount_cents": order.amount,
        "payment_method": order.payment_method,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "expires_at": order.expires_at.isoformat() if order.expires_at else None,
        "entitlements": (
            await EntitlementService.get_snapshot(db, user.id)
            if order.status == "paid"
            else None
        ),
    }


# ── 主动查询（手动触发轮询，用于调试） ──

@router.post("/orders/{order_no}/query")
async def query_order_payment(
    order_no: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """手动触发一次支付状态查询（通常由后台 Poller 自动完成）。"""
    result = await db.execute(
        select(Order).where(Order.order_no == order_no, Order.user_id == user.id)
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != "pending":
        return {"order_no": order_no, "status": order.status, "message": "订单已处理"}

    gateway_cls = AlipayGateway if order.payment_method == "alipay" else WeChatGateway
    try:
        gateway = gateway_cls()
        query_result = await gateway.query_payment(order_no)
    except PaymentConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except PaymentProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if query_result is None:
        return {"order_no": order_no, "status": "pending", "message": "支付平台未返回结果，请稍后重试"}

    if query_result.get("is_paid"):
        ok = await _mark_order_paid(db, order_no, query_result.get("trade_no") or f"MANUAL_{order_no}")
        await db.commit()
        return {
            "order_no": order_no,
            "status": "paid" if ok else order.status,
            "message": "支付已确认" if ok else "确认失败（订单可能已被处理）",
        }

    return {
        "order_no": order_no,
        "status": "pending",
        "trade_status": query_result.get("trade_status") or query_result.get("trade_state"),
        "message": "支付尚未完成",
    }


# ── 付款凭证上传（个人收款码模式） ──
# C1: 前端 paymentApi.confirmPayment() 调用的端点，之前缺失导致 404

class ConfirmPaymentRequest(BaseModel):
    order_no: str


@router.post("/confirm")
async def confirm_payment(
    req: ConfirmPaymentRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """上传付款凭证，标记订单为待审核。

    用户完成支付后调用此端点确认。后台 Poller 或管理员审核后完成订单。
    """
    result = await db.execute(
        select(Order).where(Order.order_no == req.order_no, Order.user_id == user.id)
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != "pending":
        return {"order_no": req.order_no, "status": order.status, "message": "订单已处理"}

    # 标记为待人工审核
    order.status = "reviewing"
    await db.commit()
    logger.info(f"payment_confirm_reviewing order_no={req.order_no} user_id={user.id}")
    return {"order_no": req.order_no, "status": "reviewing", "message": "已提交审核，请等待管理员确认"}


# ── 管理员支付审核端点 ──
# C2: 前端 paymentApi.getAdminPending/approveOrder/rejectOrder 调用的端点，之前缺失导致 404


@router.get("/admin/pending")
async def list_pending_orders(
    db: AsyncSession = Depends(get_db),
    admin_id: int = Depends(require_admin),
):
    """管理员：列出所有待审核订单（pending + reviewing 状态）"""
    _ = admin_id  # 仅鉴权用
    result = await db.execute(
        select(Order)
        .where(Order.status.in_(["pending", "reviewing"]))
        .order_by(Order.created_at.desc())
        .limit(50)
    )
    orders = result.scalars().all()
    return {
        "total": len(orders),
        "orders": [
            {
                "order_no": o.order_no,
                "status": o.status,
                "plan": o.plan,
                "amount_cents": o.amount,
                "payment_method": o.payment_method,
                "user_id": o.user_id,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "expires_at": o.expires_at.isoformat() if o.expires_at else None,
            }
            for o in orders
        ],
    }


@router.post("/admin/{order_no}/approve")
async def approve_order(
    order_no: str,
    db: AsyncSession = Depends(get_db),
    admin_id: int = Depends(require_admin),
):
    """管理员：手动批准订单（完成支付确认）。
    支持 pending 和 reviewing 状态的订单。"""
    _ = admin_id
    # 先查询订单状态
    result = await db.execute(select(Order).where(Order.order_no == order_no))
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status not in ("pending", "reviewing"):
        raise HTTPException(status_code=400, detail="订单状态不允许批准")
    ok = await _mark_order_paid(db, order_no, f"ADMIN_APPROVED_{order_no}")
    await db.commit()
    if ok:
        logger.info(f"admin_approved_order order_no={order_no} admin_id={admin_id}")
        return {"order_no": order_no, "status": "paid", "message": "已批准"}
    raise HTTPException(status_code=404, detail="订单不存在或无法批准")


@router.post("/admin/{order_no}/reject")
async def reject_order(
    order_no: str,
    db: AsyncSession = Depends(get_db),
    admin_id: int = Depends(require_admin),
):
    """管理员：拒绝订单"""
    _ = admin_id
    result = await db.execute(select(Order).where(Order.order_no == order_no))
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status not in ("pending", "reviewing"):
        raise HTTPException(status_code=400, detail="订单状态不允许拒绝")
    order.status = "rejected"
    await db.commit()
    logger.info(f"admin_rejected_order order_no={order_no} admin_id={admin_id}")
    return {"order_no": order_no, "status": "rejected", "message": "已拒绝"}
