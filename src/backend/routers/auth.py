"""手机号注册、密码登录、令牌刷新与账户权益接口。"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..config import settings
from ..core.dependencies import get_db
from ..models.orm import User, UserDevice, VerificationCode
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
from ..services.email_service import get_last_resend_error
from ..services.entitlement_service import EntitlementService

# create_code 内联定义于此（避免 Railway Python 3.12 对 auth_service 的深层导入失败）
async def create_code(db, target: str, purpose: str = "login") -> str:
    """创建邮箱验证码并存入数据库 — 使用原始 SQL 确保 PostgreSQL 兼容。"""
    import secrets
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import text as _t, select

    # 使用 naive UTC datetime（兼容 PostgreSQL DateTime 无时区列）
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
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
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
        minutes=settings.VERIFICATION_CODE_EXPIRE_MINUTES
    )
    await db.execute(
        _t(
            "INSERT INTO verification_codes (target, code, purpose, used, expires_at, created_at) "
            "VALUES (:t, :c, :p, FALSE, :exp, CURRENT_TIMESTAMP)"
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
    # 设备指纹+信任设备登录策略：前端登录/注册时附带
    device_fingerprint: Optional[str] = Field(default=None, max_length=128)
    device_name: Optional[str] = Field(default=None, max_length=128)
    trust_device: bool = Field(default=False, description="是否将此设备标记为信任设备（7天免登录）")

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
    device_trusted: bool = False
    device_fingerprint: Optional[str] = None


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
            "VALUES (:id, :ok, :reason, CURRENT_TIMESTAMP)"
        ),
        {"id": identifier or "", "ok": success, "reason": reason},
    )


async def _upsert_user_device(
    db,
    user_id: int,
    device_fingerprint: str,
    device_name: Optional[str],
    trust_device: bool,
    client_ip: Optional[str],
) -> bool:
    """登录/注册成功后记录或更新设备指纹。

    - 若 user_id + device_fingerprint 已存在 → 更新 last_login_at/ip，trust 状态按 trust_device 刷新
    - 若不存在 → 新建记录
    - trust_device=True 时设置 trusted_until = now + 7天
    返回当前设备是否被信任（用于响应字段 device_trusted）。
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    trusted_until = (now + timedelta(days=7)) if trust_device else None
    result = await db.execute(
        select(UserDevice).where(
            UserDevice.user_id == user_id,
            UserDevice.device_fingerprint == device_fingerprint,
        )
    )
    device = result.scalar_one_or_none()
    if device:
        device.last_login_at = now
        device.last_login_ip = client_ip
        if device_name:
            device.device_name = device_name
        if trust_device:
            device.trusted = True
            device.trusted_until = trusted_until
        # 注意：trust_device=False 时不主动撤销已有的信任状态（用户重新登录可能不勾选但保留之前信任）
    else:
        device = UserDevice(
            user_id=user_id,
            device_fingerprint=device_fingerprint,
            device_name=device_name,
            trusted=trust_device,
            trusted_until=trusted_until,
            last_login_at=now,
            last_login_ip=client_ip,
            created_at=now,
        )
        db.add(device)
    await db.flush()
    # 计算当前设备是否仍处于信任期
    if device.trusted and device.trusted_until and device.trusted_until > now:
        return True
    return False


async def _token_response(
    db,
    user: User,
    device_fingerprint: Optional[str] = None,
    device_name: Optional[str] = None,
    trust_device: bool = False,
    client_ip: Optional[str] = None,
) -> TokenResponse:
    """生成 token 响应；若提供 device_fingerprint 则记录设备并写入 JWT claims。"""
    claims = {"sub": str(user.id)}
    device_trusted = False
    if device_fingerprint:
        claims["device_fp"] = device_fingerprint
        try:
            device_trusted = await _upsert_user_device(
                db, user.id, device_fingerprint, device_name, trust_device, client_ip
            )
        except Exception as exc:
            # 设备记录失败不应阻断登录流程
            import structlog
            structlog.get_logger(__name__).warning(f"upsert UserDevice failed: {exc}")
    entitlements = await EntitlementService.get_snapshot(db, user.id)
    return TokenResponse(
        access_token=create_access_token(claims),
        refresh_token=create_refresh_token(claims),
        user=_public_user(user, entitlements),
        entitlements=entitlements,
        device_trusted=device_trusted,
        device_fingerprint=device_fingerprint,
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
        # 邮箱验证码：存码 → 发送邮件 → 返回结果
        try:
            code = await create_code(db, target, req.purpose)
        except ValueError as e:
            raise HTTPException(status_code=429, detail=str(e))
        await db.commit()
        # 同步发送邮件，捕获错误并返回给用户
        email_sent = True
        email_error = None
        try:
            await send_code_background(code, target)
        except Exception as e:
            email_sent = False
            email_error = str(e)
        return {
            "success": True,
            "message": "验证码已发送到您的邮箱" if email_sent else f"邮件发送失败，验证码：{code}",
            "code": code if not email_sent else None,
            "expires_in_seconds": settings.VERIFICATION_CODE_EXPIRE_MINUTES * 60,
            "email_sent": email_sent,
            "email_error": email_error,
            "resend_configured": bool(settings.RESEND_API_KEY),
            "resend_error": None if email_sent else get_last_resend_error(),
        }

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
        email_sent = True
        email_error = None
        try:
            await send_code_background(code, user.email)
        except Exception as e:
            email_sent = False
            email_error = str(e)
        return {
            "success": True,
            "message": "验证码已发送到您绑定的邮箱" if email_sent else f"邮件发送失败，验证码：{code}",
            "code": code if not email_sent else None,
            "expires_in_seconds": settings.VERIFICATION_CODE_EXPIRE_MINUTES * 60,
            "email_sent": email_sent,
            "email_error": email_error,
            "resend_error": None if email_sent else get_last_resend_error(),
        }

    # 无绑定邮箱：统一返回成功提示，防止用户枚举
    return {"success": True, "message": "验证码已发送（如该手机号已注册且绑定邮箱）"}


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, request: Request, db=Depends(get_db)):
    client_ip = request.client.host if request and request.client else None
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
        return await _token_response(
            db, user,
            device_fingerprint=req.device_fingerprint,
            device_name=req.device_name,
            trust_device=req.trust_device,
            client_ip=client_ip,
        )

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
        response = await _token_response(
            db, user,
            device_fingerprint=req.device_fingerprint,
            device_name=req.device_name,
            trust_device=req.trust_device,
            client_ip=client_ip,
        )
        await db.commit()
        return response
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="用户已存在") from exc


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, request: Request, db=Depends(get_db)):
    client_ip = request.client.host if request and request.client else None
    # P0 修复: 登录失败速率限制（5 次/15 分钟窗口）
    identifier = req.identifier
    if identifier:
        existing = await db.execute(
            select(User).where((User.phone == identifier) | (User.email == identifier))
        )
        user_record = existing.scalar_one_or_none()
        if user_record and user_record.locked_until and user_record.locked_until > datetime.now(timezone.utc).replace(tzinfo=None):
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
        return await _token_response(
            db, user,
            device_fingerprint=req.device_fingerprint,
            device_name=req.device_name,
            trust_device=req.trust_device,
            client_ip=client_ip,
        )

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
            lock_time = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=15) if new_count >= 5 else None
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
    return await _token_response(
        db, user,
        device_fingerprint=req.device_fingerprint,
        device_name=req.device_name,
        trust_device=req.trust_device,
        client_ip=client_ip,
    )


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


# ═══════════════════════════════════════════════════════════════
# 设备指纹+信任设备登录策略：设备管理端点
# ═══════════════════════════════════════════════════════════════

@router.get("/devices")
async def list_user_devices(user: User = Depends(get_current_user), db=Depends(get_db)):
    """列出当前用户的所有设备（按最后登录时间倒序）。"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result = await db.execute(
        select(UserDevice)
        .where(UserDevice.user_id == user.id)
        .order_by(UserDevice.last_login_at.desc())
    )
    devices = result.scalars().all()
    return {
        "devices": [
            {
                "id": d.id,
                "device_name": d.device_name or "未命名设备",
                "device_fingerprint": d.device_fingerprint,
                "trusted": d.trusted,
                "trusted_until": d.trusted_until.isoformat() if d.trusted_until else None,
                "is_current_active": bool(
                    d.trusted and d.trusted_until and d.trusted_until > now
                ),
                "last_login_at": d.last_login_at.isoformat() if d.last_login_at else None,
                "last_login_ip": d.last_login_ip,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in devices
        ]
    }


@router.delete("/devices/{device_id}")
async def revoke_device(
    device_id: int,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """撤销指定设备的信任状态（不删除记录，仅置 trusted=False）。"""
    result = await db.execute(
        select(UserDevice).where(
            UserDevice.id == device_id,
            UserDevice.user_id == user.id,
        )
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在或无权操作")
    device.trusted = False
    device.trusted_until = None
    await db.commit()
    return {"success": True, "message": "已撤销该设备的信任状态"}


@router.post("/devices/{device_id}/trust")
async def trust_device_again(
    device_id: int,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """重新信任某设备（延长 7 天）。"""
    result = await db.execute(
        select(UserDevice).where(
            UserDevice.id == device_id,
            UserDevice.user_id == user.id,
        )
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在或无权操作")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    device.trusted = True
    device.trusted_until = now + timedelta(days=7)
    await db.commit()
    return {
        "success": True,
        "message": "已重新信任该设备（7天免登录）",
        "trusted_until": device.trusted_until.isoformat(),
    }


class ValidateDeviceRequest(BaseModel):
    device_fingerprint: str = Field(min_length=8, max_length=128)


@router.post("/validate-device")
async def validate_device(
    req: ValidateDeviceRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db=Depends(get_db),
):
    """前端页面加载时校验：token 是否有效 + 设备是否在信任列表。

    返回:
        - valid: token 是否有效
        - need_login: 是否需要重新登录
        - device_trusted: 当前设备是否处于信任期
        - user: 用户基本信息（若 token 有效）
    """
    # 1. 无 token → 需要登录
    if not credentials:
        return {"valid": False, "need_login": True, "device_trusted": False, "user": None}

    # 2. token 解码
    payload = decode_token(credentials.credentials, expected_type="access")
    if not payload:
        return {"valid": False, "need_login": True, "device_trusted": False, "user": None}

    try:
        user_id = int(payload.get("sub", 0))
    except (TypeError, ValueError):
        user_id = 0
    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        return {"valid": False, "need_login": True, "device_trusted": False, "user": None}

    # 3. 校验设备指纹是否在用户设备列表中
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result = await db.execute(
        select(UserDevice).where(
            UserDevice.user_id == user.id,
            UserDevice.device_fingerprint == req.device_fingerprint,
        )
    )
    device = result.scalar_one_or_none()

    if not device:
        # 设备未在列表中 → 需要登录（用户可勾选信任）
        return {
            "valid": True,
            "need_login": True,
            "device_trusted": False,
            "user": _public_user(user),
            "reason": "device_not_found",
        }

    # 4. 检查信任状态是否仍有效
    is_still_trusted = bool(
        device.trusted and device.trusted_until and device.trusted_until > now
    )
    if is_still_trusted:
        return {
            "valid": True,
            "need_login": False,
            "device_trusted": True,
            "user": _public_user(user),
        }
    else:
        # 设备已记录但信任过期 → 需重新登录可勾选信任
        return {
            "valid": True,
            "need_login": True,
            "device_trusted": False,
            "user": _public_user(user),
            "reason": "trust_expired",
        }
