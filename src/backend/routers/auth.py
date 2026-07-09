"""手机号注册、密码登录、令牌刷新与账户权益接口。"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..config import settings
from ..core.dependencies import get_db
from ..models.orm import User, VerificationCode
import asyncio
from ..services.auth_service import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_user_by_id,
    normalize_phone,
    register_user,
    send_code_background,
    verify_code_and_login,
)
from ..services.entitlement_service import EntitlementService

# create_code 内联定义于此（避免 Railway Python 3.12 对 auth_service 的深层导入失败）
async def create_code(db, target: str, purpose: str = "login") -> str:
    """创建邮箱验证码并存入数据库 — 使用原始 SQL 确保 PostgreSQL 兼容。"""
    import secrets
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import text as _t, select

    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.VERIFICATION_CODE_RATE_LIMIT_SECONDS
    )
    recent = await db.execute(
        select(VerificationCode)
        .where(VerificationCode.target == target, VerificationCode.created_at >= cutoff)
        .limit(1)
    )
    if recent.scalars().first():
        raise ValueError("验证码发送过于频繁，请稍后再试")

    code = str(secrets.randbelow(900000) + 100000)
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.VERIFICATION_CODE_EXPIRE_MINUTES
    )
    await db.execute(
        _t(
            "INSERT INTO verification_codes (target, code, purpose, used, expires_at, created_at) "
            "VALUES (:t, :c, :p, FALSE, :exp, NOW())"
        ),
        {"t": target, "c": code, "p": purpose, "exp": expires_at},
    )
    await db.flush()
    return code

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)


class PhoneCredentials(BaseModel):
    phone: Optional[str] = Field(default=None, min_length=5, max_length=128)
    # 保留一个发布周期的旧前端兼容；值可以是手机号或邮箱。
    username: Optional[str] = Field(default=None, min_length=3, max_length=128)
    email: Optional[str] = Field(default=None, min_length=5, max_length=128)
    password: Optional[str] = Field(default=None, min_length=1, max_length=128)

    def normalized_phone(self) -> str:
        try:
            return normalize_phone(self.phone or self.username or "")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @property
    def identifier(self) -> str:
        """返回用户标识：优先 email → phone → username"""
        return self.email or self.phone or self.username or ""


class RegisterRequest(PhoneCredentials):
    nickname: Optional[str] = Field(default=None, max_length=64)
    code: Optional[str] = Field(default=None, min_length=6, max_length=6)

    @model_validator(mode="after")
    def require_auth_method(self):
        if not self.code and not self.password:
            raise ValueError("必须提供密码或验证码")
        return self


class LoginRequest(PhoneCredentials):
    code: Optional[str] = Field(default=None, min_length=6, max_length=6)

    @model_validator(mode="after")
    def require_auth_method(self):
        if not self.code and not self.password:
            raise ValueError("必须提供密码或验证码")
        return self


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict
    entitlements: dict


def _mask_phone(phone: str | None) -> str | None:
    """脱敏手机号: +8613800138000 → +86138****8000"""
    if not phone:
        return None
    if len(phone) > 8:
        return f"{phone[:6]}****{phone[-2:]}"
    return phone


def _public_user(user: User, entitlements: dict | None = None) -> dict:
    # 🔴 修复: 根据 entitlements snapshot 计算实际 plan，而非 user.plan（过期后不更新）
    if entitlements:
        if entitlements.get("membership_active"):
            actual_plan = entitlements.get("plan", "free")
        else:
            actual_plan = "free"
    else:
        actual_plan = user.plan
    return {
        "id": user.id,
        "phone": _mask_phone(user.phone),
        "nickname": user.nickname or (user.phone[-4:] if user.phone else "用户"),
        "plan": actual_plan,
    }


async def _record_login_attempt(db, identifier: str, success: bool, reason: str | None = None) -> None:
    """使用原始 SQL 记录登录尝试（避免 LoginAttempt ORM INSERT 的 NOT NULL 问题）"""
    from sqlalchemy import text as _t
    await db.execute(
        _t(
            "INSERT INTO login_attempts (identifier, success, failure_reason, created_at) "
            "VALUES (:id, :ok, :reason, NOW())"
        ),
        {"id": identifier or "", "ok": success, "reason": reason},
    )


async def _token_response(db, user: User) -> TokenResponse:
    claims = {"sub": str(user.id)}
    entitlements = await EntitlementService.get_snapshot(db, user.id)
    return TokenResponse(
        access_token=create_access_token(claims),
        refresh_token=create_refresh_token(claims),
        user=_public_user(user, entitlements),
        entitlements=entitlements,
    )


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db=Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供认证凭证"
        )
    payload = decode_token(credentials.credentials, expected_type="access")
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证凭证无效或已过期",
        )
    try:
        user_id = int(payload.get("sub", 0))
    except (TypeError, ValueError):
        user_id = 0
    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已停用"
        )
    return user


class SendCodeRequest(BaseModel):
    target: str = Field(min_length=5, max_length=128, description="手机号或邮箱地址")
    purpose: str = Field(default="login", pattern="^(login|register)$")


@router.post("/send-code")
async def send_verification_code(req: SendCodeRequest, db=Depends(get_db)):
    """发送验证码到指定手机号或邮箱。

    - 若 target 包含 @ → 视作邮箱，直接发送邮件验证码
    - 否则视作手机号 → 仅提示"验证码已发送"（免费短信不可用，用户需用邮箱）
    """
    target = req.target.strip()
    if "@" in target:
        # 邮箱验证码：先存码→立即返回，邮件后台发送（fire-and-forget）
        try:
            code = await create_code(db, target, req.purpose)
        except ValueError as e:
            raise HTTPException(status_code=429, detail=str(e))
        await db.commit()
        # 后台发送邮件，不阻塞 HTTP 响应
        asyncio.create_task(send_code_background(code, target))
        return {"success": True, "message": "验证码已发送到您的邮箱",
                "expires_in_seconds": settings.VERIFICATION_CODE_EXPIRE_MINUTES * 60}

    # 手机号：先归一化，检查是否关联了邮箱
    try:
        phone = normalize_phone(target)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # 查找用户是否绑定过邮箱
    user_result = await db.execute(select(User).where(User.phone == phone))
    user = user_result.scalar_one_or_none()
    if user and user.email:
        try:
            code = await create_code(db, user.email, req.purpose)
        except ValueError as e:
            raise HTTPException(status_code=429, detail=str(e))
        await db.commit()
        asyncio.create_task(send_code_background(code, user.email))
        return {"success": True, "message": "验证码已发送到您绑定的邮箱",
                "expires_in_seconds": settings.VERIFICATION_CODE_EXPIRE_MINUTES * 60}

    # 无绑定邮箱：统一返回成功提示，防止用户枚举
    return {"success": True, "message": "验证码已发送（如该手机号已注册且绑定邮箱）"}


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, db=Depends(get_db)):
    # 验证码注册：与登录共用 verify_code_and_login（新用户自动创建）
    if req.code and len(req.code) == 6:
        target = req.identifier
        if not target:
            raise HTTPException(status_code=422, detail="请提供邮箱或手机号")
        user = await verify_code_and_login(db, target, req.code)
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="验证码错误或已过期")
        if req.nickname:
            user.nickname = req.nickname
        # 若有 email 字段，更新用户邮箱
        if req.email and not user.email:
            user.email = req.email
        await db.commit()
        return await _token_response(db, user)

    # 密码注册（支持邮箱和手机号，register_user 自动识别）
    if not req.password or len(req.password) < settings.PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"密码至少 {settings.PASSWORD_MIN_LENGTH} 位",
        )
    reg_identifier = req.identifier  # email 优先，其次 phone
    if not reg_identifier:
        raise HTTPException(status_code=422, detail="请提供邮箱或手机号")

    # 检查重复注册
    is_email = "@" in reg_identifier
    existing = await db.execute(
        select(User).where(
            User.email == reg_identifier if is_email else User.phone == req.normalized_phone()
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="该邮箱已注册" if is_email else "该手机号已注册")

    user = await register_user(db, reg_identifier, req.password, req.nickname or "")

    try:
        response = await _token_response(db, user)
        await db.commit()
        return response
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="用户已存在") from exc


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db=Depends(get_db)):
    # P0 修复: 登录失败速率限制（5 次/15 分钟窗口）
    identifier = req.identifier
    if identifier:
        existing = await db.execute(
            select(User).where((User.phone == identifier) | (User.email == identifier))
        )
        user_record = existing.scalar_one_or_none()
        if user_record and user_record.locked_until and user_record.locked_until > datetime.now(timezone.utc):
            raise HTTPException(status_code=429, detail="账户已被临时锁定，请15分钟后重试")

    if req.code:
        # 验证码登录/注册：target 优先取 email，其次是 phone/username
        target = req.identifier
        if "@" not in target and target:
            try:
                target = req.normalized_phone()
            except HTTPException:
                pass
        if not target:
            raise HTTPException(status_code=422, detail="请提供邮箱或手机号")
        user = await verify_code_and_login(db, target, req.code)
        if not user or not user.is_active:
            await _record_login_attempt(db, identifier, False, "invalid_code")
            await db.commit()
            raise HTTPException(status_code=401, detail="验证码错误或已过期")
        await _record_login_attempt(db, identifier, True)
        return await _token_response(db, user)

    # 密码登录（支持手机号和邮箱）
    if not req.password:
        raise HTTPException(status_code=422, detail="请提供密码")
    auth_identifier = req.identifier  # email 优先，其次 phone，其次 username
    if not auth_identifier:
        raise HTTPException(status_code=422, detail="请提供邮箱或手机号")
    user = await authenticate_user(db, auth_identifier, req.password)
    if not user or not user.is_active:
        await _record_login_attempt(
            db, identifier, False,
            "locked" if (user and not user.is_active) else "invalid_password"
        )
        # 记录登录失败并锁定（5 次失败后锁定 15 分钟）
        from sqlalchemy import text as _t
        user_result = await db.execute(
            select(User).where((User.phone == auth_identifier) | (User.email == auth_identifier))
        )
        failed_user = user_result.scalar_one_or_none()
        if failed_user:
            new_count = (failed_user.failed_login_attempts or 0) + 1
            lock_time = datetime.now(timezone.utc) + timedelta(minutes=15) if new_count >= 5 else None
            await db.execute(
                _t("UPDATE users SET failed_login_attempts=:c, locked_until=:lt WHERE id=:uid"),
                {"c": new_count, "lt": lock_time, "uid": failed_user.id},
            )
            await db.commit()
        raise HTTPException(status_code=401, detail="邮箱/手机号或密码错误")
    # 登录成功：重置失败计数 + 记录审计日志
    from sqlalchemy import text as _t2
    if user.failed_login_attempts > 0:
        await db.execute(
            _t2("UPDATE users SET failed_login_attempts=0, locked_until=NULL WHERE id=:uid"),
            {"uid": user.id},
        )
    await _record_login_attempt(db, identifier, True)
    return await _token_response(db, user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, db=Depends(get_db)):
    payload = decode_token(req.refresh_token, expected_type="refresh")
    if not payload:
        raise HTTPException(status_code=401, detail="刷新令牌无效或已过期")
    try:
        user_id = int(payload.get("sub", 0))
    except (TypeError, ValueError):
        user_id = 0
    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已停用")
    return await _token_response(db, user)


@router.get("/me")
async def get_me(user: User = Depends(get_current_user), db=Depends(get_db)):
    entitlements = await EntitlementService.get_snapshot(db, user.id)
    return {
        "user": _public_user(user, entitlements),
        "entitlements": entitlements,
    }
