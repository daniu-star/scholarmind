"""
ScholarMind ORM 数据模型
SQLAlchemy 异步 ORM 模型定义
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    JSON,
    Index,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.session import Base


def _utcnow() -> datetime:
    """统一的 UTC 当前时间函数(替代已弃用的 datetime.utcnow)

    返回 offset-naive datetime，与 PostgreSQL TIMESTAMP WITHOUT TIME ZONE 列类型一致。
    避免 asyncpg "can't subtract offset-naive and offset-aware datetimes" 错误。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Conversation(Base):
    """对话消息模型 —— 替代 JSON 文件存储"""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, comment="会话唯一标识"
    )
    agent_id: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="Agent 类型"
    )
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="user / assistant"
    )
    content: Mapped[str] = mapped_column(
        Text, nullable=False, comment="消息内容"
    )
    title: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, comment="会话标题(取首条用户消息前 30 字)"
    )
    # P0 Task 3.6：会话归属用户 ID（IDOR 防护）。
    # - 新会话写入登录用户 user_id（>= 1）
    # - 历史匿名会话 user_id=NULL（视为 guest，登录用户查询不会匹配）
    # - 查询时 Repository WHERE 同时按 session_id + user_id 过滤
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True, comment="会话归属用户 ID（NULL=guest）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow, comment="最后更新时间"
    )

    __table_args__ = (
        Index("idx_conversations_session_time", "session_id", "created_at"),
        Index("idx_conversations_agent_updated", "agent_id", "updated_at"),
        # P0 Task 3.4：按 user_id + session_id 双过滤的复合索引
        Index("idx_conversations_user_session", "user_id", "session_id"),
        # P1 修复: 按 agent + user 筛选的复合索引
        Index("idx_conversations_agent_user", "agent_id", "user_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Conversation(id={self.id}, session={self.session_id}, "
            f"role={self.role}, created_at={self.created_at})>"
        )


class Skill(Base):
    """技能配置模型 —— 替代 YAML 文件存储"""

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    skill_id: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True, comment="技能唯一标识"
    )
    display_name: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="展示名称"
    )
    description: Mapped[str] = mapped_column(
        Text, default="", comment="技能描述"
    )
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="custom", comment="技能分类"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="是否启用"
    )
    agents: Mapped[list] = mapped_column(
        JSON, default=list, comment="关联的 Agent 列表"
    )
    triggers: Mapped[list] = mapped_column(
        JSON, default=list, comment="触发关键词列表"
    )
    rules: Mapped[str] = mapped_column(
        Text, default="", comment="技能规则（Markdown）"
    )
    is_preset: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否预设技能"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,  # 自动刷新更新时间
        comment="更新时间",
    )

    __table_args__ = (
        Index("idx_skills_enabled", "enabled"),
        Index("idx_skills_category", "category"),
    )

    def __repr__(self) -> str:
        return (
            f"<Skill(id={self.id}, skill_id={self.skill_id}, "
            f"name={self.display_name}, enabled={self.enabled})>"
        )


class ChartRecord(Base):
    """图表生成记录模型"""

    __tablename__ = "chart_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chart_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True, comment="图表 UUID"
    )
    chart_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="图表类型"
    )
    title: Mapped[str] = mapped_column(
        String(256), default="", comment="图表标题"
    )
    filepath: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="文件路径"
    )
    session_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, comment="会话标识"
    )
    # P1 修复: 图表归属用户（IDOR 防护）
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True, comment="图表归属用户"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, comment="创建时间"
    )

    __table_args__ = (
        Index("idx_chart_records_session", "session_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ChartRecord(id={self.id}, chart_id={self.chart_id}, "
            f"type={self.chart_type}, session={self.session_id})>"
        )


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    phone: Mapped[Optional[str]] = mapped_column(
        String(20), unique=True, nullable=True, index=True, comment="E.164 手机号"
    )
    email: Mapped[Optional[str]] = mapped_column(
        String(128), unique=True, nullable=True, index=True, comment="用户邮箱（验证码发送目标）"
    )
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    nickname: Mapped[str] = mapped_column(String(64), default="")
    # P0 修复: 基于角色的访问控制 + 登录安全
    # Task 23.5: role 字段添加 index=True，加速管理员列表/权限过滤查询
    role: Mapped[str] = mapped_column(
        String(16), default="user", index=True, comment="user / editor / admin"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="邮箱是否已验证"
    )
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, default=0, comment="连续登录失败次数"
    )
    locked_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="账户锁定到期时间"
    )
    plan: Mapped[str] = mapped_column(String(32), default="free")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        # Task 23.4: 原 users_username 索引与 username 字段的 unique=True, index=True 重复，已删除。
        Index("idx_users_phone", "phone", unique=True),
    )
    def __repr__(self): return f"<User {self.username}>"


class UserQuota(Base):
    __tablename__ = "user_quotas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    tokens_limit: Mapped[int] = mapped_column(Integer, default=1000000)
    plan: Mapped[str] = mapped_column(String(32), default="free")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    free_chats_used: Mapped[int] = mapped_column(Integer, default=0)
    free_chat_limit: Mapped[int] = mapped_column(Integer, default=20)
    generation_credits: Mapped[int] = mapped_column(Integer, default=0)
    shared_pipeline_credits: Mapped[int] = mapped_column(Integer, default=0)
    external_review_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    membership_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    model_tier: Mapped[str] = mapped_column(String(16), default="flash")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_quotas_user_id"),)
    def __repr__(self): return f"<UserQuota user={self.user_id} used={self.tokens_used}>"


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    plan: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # P0 Task 2.6: trade_no 唯一约束 + 索引，nullable 让历史无 trade_no 的订单不报错。
    # 字段长度 64（支付宝 28 位、微信 32 位均足够）。
    # P0 阶段 Alembic 损坏，依赖 init_db 的 _migrate_orders_table 创建
    # `CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_trade_no_unique ON orders(trade_no) WHERE trade_no IS NOT NULL`
    # （SQLite 部分唯一索引，允许多个 NULL）。P1 修复 Alembic 后由迁移管理。
    trade_no: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    entitlements_granted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    provider_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    payment_mode: Mapped[str] = mapped_column(
        String(16), default="api", comment="api | personal_qr"
    )
    proof_uploaded: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否上传了支付凭证"
    )
    proof_filename: Mapped[Optional[str]] = mapped_column(
        String(256), nullable=True
    )
    confirmed_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, comment="确认支付的管理员ID"
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        # P1 修复: 按用户 + 状态查询的复合索引（用户订单列表高频查询）
        Index("idx_orders_user_status", "user_id", "status"),
    )

    def __repr__(self): return f"<Order {self.order_no} status={self.status}>"


class EntitlementGrant(Base):
    """支付权益发放账本，source_ref 唯一保证回调重放不会重复加额度。"""

    __tablename__ = "entitlement_grants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    source_ref: Mapped[str] = mapped_column(
        String(96), unique=True, nullable=False, index=True
    )
    product_id: Mapped[str] = mapped_column(String(32), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class VerificationCode(Base):
    """邮箱验证码模型"""

    __tablename__ = "verification_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True, comment="手机号或邮箱地址"
    )
    code: Mapped[str] = mapped_column(String(6), nullable=False)
    purpose: Mapped[str] = mapped_column(
        String(16), default="login", comment="login | register"
    )
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("idx_vc_target_purpose", "target", "purpose"),
        Index("idx_vc_target_created", "target", "created_at"),
    )


# ═══════════════════════════════════════════════════════════════
# P0 修复: 管理员审计日志模型
# ═══════════════════════════════════════════════════════════════
class AdminAuditLog(Base):
    """管理员操作审计日志 — 满足企业安全审计与 SOC2 合规要求"""

    __tablename__ = "admin_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True, comment="操作管理员 ID"
    )
    action: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="payment_confirm / user_ban / code_execute / order_approve"
    )
    target_type: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, comment="order / user / code"
    )
    target_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True, comment="操作来源 IP（IPv4/IPv6）"
    )
    detail: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="操作详情 JSON"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("idx_audit_admin_created", "admin_id", "created_at"),
        Index("idx_audit_action", "action"),
    )


# ═══════════════════════════════════════════════════════════════
# P1 修复: Agent 执行日志模型（LLM 调用量/延迟/成功率统计）
# ═══════════════════════════════════════════════════════════════
class AgentExecutionLog(Base):
    """每次 LLM 调用记录一条，用于成本分析、延迟监控与故障排查"""

    __tablename__ = "agent_execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(String(32), nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="X-Request-ID 用于全链路追踪"
    )
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="success", comment="success / failed / timeout"
    )
    error_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("idx_ael_user_created", "user_id", "created_at"),
        Index("idx_ael_session", "session_id"),
        Index("idx_ael_agent_status", "agent_id", "status"),
    )


# ═══════════════════════════════════════════════════════════════
# P1 修复: 登录尝试记录模型（暴力破解检测与安全审计）
# ═══════════════════════════════════════════════════════════════
class LoginAttempt(Base):
    """每次登录尝试记录一条，用于暴力破解检测与安全审计"""

    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    identifier: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="手机号或邮箱"
    )
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_reason: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="invalid_password / invalid_code / locked"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("idx_la_identifier_created", "identifier", "created_at"),
    )