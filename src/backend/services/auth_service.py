from datetime import datetime, timezone, timedelta
import secrets
from typing import Optional
import jwt
from pwdlib import PasswordHash
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.orm import User, UserQuota, VerificationCode, LoginAttempt
from ..config import settings

pwd_hash = PasswordHash.recommended()

# 显式导出列表，确保 Railway/Python 3.12 环境中函数定义可被导入
# 此前 Railway 部署报 ImportError: cannot import name 'create_code' ——
# 可能是 Docker 层缓存导致旧版文件未更新；添加此注释触发干净重建
__all__ = [
    "normalize_phone",
    "verify_password",
    "get_password_hash",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "authenticate_user",
    "register_user",
    "register_user_by_email",
    "get_user_by_id",
    "generate_verification_code",
    "create_code",
    "send_code_background",
    "create_and_send_code",
    "verify_code_and_login",
]


def normalize_phone(phone: str) -> str:
    """将中国大陆手机号统一保存为 E.164，接受空格、短横线和 +86 前缀。"""
    compact = "".join(ch for ch in phone.strip() if ch.isdigit() or ch == "+")
    compact = compact.replace("-", "")
    digits = "".join(ch for ch in compact if ch.isdigit())
    if digits.startswith("0086"):
        digits = digits[4:]
    elif digits.startswith("86") and len(digits) == 13:
        digits = digits[2:]
    if len(digits) != 11 or not digits.startswith("1") or digits[1] not in "3456789":
        raise ValueError("请输入有效的中国大陆手机号")
    return f"+86{digits}"

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_hash.verify(plain, hashed)

def get_password_hash(password: str) -> str:
    return pwd_hash.hash(password)

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def decode_token(
    token: str, expected_type: Optional[str] = None
) -> Optional[dict]:
    """解码并校验 JWT。

    Args:
        token: JWT 字符串
        expected_type: 期望的 token 类型 ("access" 或 "refresh")。
            - None（默认）：不校验 type，保持向后兼容（仅检查签名与过期）
            - "access"：仅接受 type=access 的 token，refresh/其他类型返回 None
            - "refresh"：仅接受 type=refresh 的 token
            P0 Task 3.7：阻断 refresh token 访问业务 API（access 端点），
            以及 access token 调用 refresh 端点的混用攻击。
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    if expected_type is not None and payload.get("type") != expected_type:
        # 类型不匹配（如 refresh token 访问业务 API）→ 视为无效
        return None
    return payload

async def authenticate_user(
    db: AsyncSession, identifier: str, password: str
) -> Optional[User]:
    """验证用户密码（支持手机号和邮箱两种标识符）。

    identifier 可以是 E.164 手机号或邮箱地址。
    """
    # 判断是邮箱还是手机号
    if "@" in identifier:
        result = await db.execute(
            select(User).where(User.email == identifier)
        )
    else:
        try:
            identifier = normalize_phone(identifier)
        except ValueError:
            return None
        result = await db.execute(
            select(User).where(User.phone == identifier)
        )
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return None
    return user

async def _init_user_quota(db: AsyncSession, user_id: int) -> None:
    """为新注册用户初始化免费配额（UserQuota 记录）。"""
    quota = UserQuota(
        user_id=user_id,
        tokens_used=0,
        tokens_limit=settings.FREE_TIER_TOKEN_LIMIT,
        plan="free",
        free_chats_used=0,
        free_chat_limit=settings.FREE_CHAT_LIMIT,
        model_tier="flash",
    )
    db.add(quota)
    await db.flush()


async def register_user(
    db: AsyncSession, identifier: str, password: str, nickname: str = ""
) -> User:
    """注册新用户（自动识别手机号或邮箱）— 使用原始 SQL 确保 PostgreSQL 兼容。

    Args:
        db: 数据库会话
        identifier: 手机号（自动归一化为 E.164）或邮箱地址（含 @ 则视为邮箱）
        password: 明文密码（内部哈希存储）
        nickname: 可选昵称

    Returns:
        新创建的 User 对象（已 flush，id 可用）
    """
    from sqlalchemy import text as _t

    if "@" in identifier:
        username = identifier
        phone = None
        email = identifier
    else:
        normalized = normalize_phone(identifier)
        username = normalized
        phone = normalized
        email = None

    # 使用原始 SQL INSERT 确保 Railway PostgreSQL 兼容
    pwd = get_password_hash(password)
    nick = nickname or username[-8:] if len(username) > 8 else username

    # 先检查是否已存在（避免唯一约束冲突）
    existing = await db.execute(
        select(User).where(
            (User.username == username) | ((User.email == email) if email else False)
        )
    )
    existing_user = existing.scalar_one_or_none()
    if existing_user:
        return existing_user

    # 使用原始 INSERT（不依赖 ON CONFLICT，先查后插已在上面完成）
    result = await db.execute(
        _t(
            "INSERT INTO users (username, phone, email, password_hash, nickname, "
            "role, is_active, email_verified, failed_login_attempts, plan, created_at, updated_at) "
            "VALUES (:u, :p, :e, :pw, :n, 'user', TRUE, FALSE, 0, 'free', NOW(), NOW()) "
            "RETURNING id"
        ),
        {"u": username, "p": phone, "e": email, "pw": pwd, "n": nick},
    )
    user_id = result.scalar_one()
    await db.flush()

    # 初始化配额（包含所有 NOT NULL 列）
    await db.execute(
        _t(
            "INSERT INTO user_quotas (user_id, tokens_used, tokens_limit, plan, "
            "free_chats_used, free_chat_limit, generation_credits, "
            "shared_pipeline_credits, model_tier, created_at, updated_at) "
            "VALUES (:uid, 0, :limit, 'free', 0, :chat_limit, 0, 0, 'flash', NOW(), NOW())"
        ),
        {"uid": user_id, "limit": settings.FREE_TIER_TOKEN_LIMIT, "chat_limit": settings.FREE_CHAT_LIMIT},
    )
    await db.flush()

    # 构造 User 对象返回
    user = User(
        id=user_id,
        username=username,
        phone=phone,
        email=email,
        password_hash=pwd,
        nickname=nick,
    )
    return user


# register_user_by_email 保留为向后兼容的别名
async def register_user_by_email(
    db: AsyncSession, email: str, password: str, nickname: str = ""
) -> User:
    """通过邮箱注册新用户（已合并到 register_user，保留作为语义别名）。

    新代码请直接使用 register_user(identifier, ...)。
    """
    return await register_user(db, email, password, nickname)

async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


# ── 邮箱验证码 ──────────────────────────────────────────


def generate_verification_code() -> str:
    return str(secrets.randbelow(900000) + 100000)


async def create_code(
    db: AsyncSession, target: str, purpose: str = "login"
) -> str:
    """创建验证码并存入数据库（不发送邮件）。含限频检查。

    Returns:
        生成的验证码字符串
    """
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

    code = generate_verification_code()
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
        minutes=settings.VERIFICATION_CODE_EXPIRE_MINUTES
    )

    vc = VerificationCode(
        target=target,
        code=code,
        purpose=purpose,
        expires_at=expires_at,
    )
    db.add(vc)
    await db.flush()
    return code


async def send_code_background(code: str, target: str) -> None:
    """发送验证码邮件（同步模式——返回真实 SMTP 错误）。

    若 SMTP 配置可用，同步发送邮件；异常会向上传播由调用方处理。
    """
    from ..services.email_service import send_verification_email
    await send_verification_email(target, code)


async def create_and_send_code(
    db: AsyncSession, target: str, purpose: str = "login"
) -> dict:
    """创建验证码并发送邮件（同步模式，仅用于兼容旧调用）。

    新代码应使用 create_code() + asyncio.create_task(send_code_background(...))。
    """
    code = await create_code(db, target, purpose)
    await send_code_background(code, target)
    return {
        "target": target,
        "expires_in_seconds": settings.VERIFICATION_CODE_EXPIRE_MINUTES * 60,
    }


async def verify_code_and_login(
    db: AsyncSession, target: str, code: str
) -> Optional[User]:
    """校验验证码，返回或创建用户。

    target 可以是手机号或邮箱。若用户不存在则自动注册（验证码登录模式）。
    """
    from sqlalchemy import text as _t
    # 使用 naive UTC datetime（兼容 PostgreSQL 无时区列）
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # 检查最近 5 分钟内该 target 的失败验证尝试次数（LoginAttempt 表），防止暴力破解
    failed_window = now - timedelta(minutes=5)
    failed_count = await db.scalar(
        select(func.count(LoginAttempt.id)).where(
            LoginAttempt.identifier == target,
            LoginAttempt.success.is_(False),
            LoginAttempt.failure_reason == "invalid_code",
            LoginAttempt.created_at >= failed_window,
        )
    )
    if failed_count and failed_count >= 10:
        return None  # 10 次失败验证后拒绝，防止暴力破解

    result = await db.execute(
        select(VerificationCode)
        .where(
            VerificationCode.target == target,
            VerificationCode.code == code,
            VerificationCode.used.is_(False),
            VerificationCode.expires_at > now,
        )
        .order_by(VerificationCode.created_at.desc())
    )
    vc = result.scalars().first()
    if not vc:
        # 记录失败尝试（原始 SQL）
        await db.execute(
            _t(
                "INSERT INTO login_attempts (identifier, success, failure_reason, created_at) "
                "VALUES (:id, FALSE, :reason, NOW())"
            ),
            {"id": target, "reason": "invalid_code"},
        )
        return None

    # 标记已使用（UPDATE 安全）
    vc.used = True
    await db.flush()

    # 查找或创建用户：按 phone 或 email 匹配
    user_result = await db.execute(
        select(User).where(
            (User.phone == target) | (User.email == target)
        )
    )
    user = user_result.scalar_one_or_none()

    if user is None:
        # 自动注册新用户（原始 SQL）
        pwd = get_password_hash(secrets.token_hex(16))
        phone_val = target if "@" not in target else None
        email_val = target if "@" in target else None
        nick_val = target[-8:] if len(target) > 8 else target

        ins_result = await db.execute(
            _t(
                "INSERT INTO users (username, phone, email, password_hash, nickname, "
                "role, is_active, email_verified, failed_login_attempts, plan, created_at, updated_at) "
                "VALUES (:u, :p, :e, :pw, :n, 'user', TRUE, FALSE, 0, 'free', NOW(), NOW()) "
                "RETURNING id"
            ),
            {"u": target, "p": phone_val, "e": email_val, "pw": pwd, "n": nick_val},
        )
        uid = ins_result.scalar_one()
        await db.flush()

        # 初始化配额（原始 SQL）
        await db.execute(
            _t(
                "INSERT INTO user_quotas (user_id, tokens_used, tokens_limit, plan, "
                "free_chats_used, free_chat_limit, generation_credits, "
                "shared_pipeline_credits, model_tier, created_at, updated_at) "
                "VALUES (:uid, 0, :limit, 'free', 0, :chat_limit, 0, 0, 'flash', NOW(), NOW())"
            ),
            {"uid": uid, "limit": settings.FREE_TIER_TOKEN_LIMIT, "chat_limit": settings.FREE_CHAT_LIMIT},
        )
        await db.flush()

        # 查询构建 User 对象
        result2 = await db.execute(select(User).where(User.id == uid))
        user = result2.scalar_one()
        return user

    return user
