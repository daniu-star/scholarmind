"""admin audit logs, agent execution logs, login attempts, and security fields

Revision ID: m4_audit_security
Revises: m3_verification_qr
Create Date: 2026-07-03

迁移内容（P0/P1 安全修复新增模型和字段）:
  1. 创建 admin_audit_logs 表（管理员操作审计）
  2. 创建 agent_execution_logs 表（LLM 调用统计）
  3. 创建 login_attempts 表（登录审计）
  4. users 表增加 role, email_verified, failed_login_attempts, locked_until 字段
  5. conversations 表增加 agent_user 复合索引
  6. orders 表增加 user_status 复合索引
  7. chart_records 表增加 user_id 字段
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "m4_audit_security"
down_revision: Union[str, Sequence[str], None] = "m3_verification_qr"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table) if i.get("name")}


def upgrade() -> None:
    # ── 1. admin_audit_logs 表 ──
    if "admin_audit_logs" not in _tables():
        op.create_table(
            "admin_audit_logs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("admin_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("action", sa.String(64), nullable=False),
            sa.Column("target_type", sa.String(32), nullable=True),
            sa.Column("target_id", sa.String(64), nullable=True),
            sa.Column("ip_address", sa.String(45), nullable=True),
            sa.Column("detail", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_audit_admin_created", "admin_audit_logs", ["admin_id", "created_at"])
        op.create_index("idx_audit_action", "admin_audit_logs", ["action"])

    # ── 2. agent_execution_logs 表 ──
    if "agent_execution_logs" not in _tables():
        op.create_table(
            "agent_execution_logs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("agent_id", sa.String(32), nullable=False),
            sa.Column("session_id", sa.String(64), nullable=False),
            sa.Column("request_id", sa.String(64), nullable=True),
            sa.Column("model", sa.String(64), nullable=False),
            sa.Column("prompt_tokens", sa.Integer(), nullable=True),
            sa.Column("completion_tokens", sa.Integer(), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="success"),
            sa.Column("error_code", sa.String(32), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_ael_user_created", "agent_execution_logs", ["user_id", "created_at"])
        op.create_index("idx_ael_session", "agent_execution_logs", ["session_id"])
        op.create_index("idx_ael_agent_status", "agent_execution_logs", ["agent_id", "status"])

    # ── 3. login_attempts 表 ──
    if "login_attempts" not in _tables():
        op.create_table(
            "login_attempts",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("identifier", sa.String(128), nullable=False),
            sa.Column("ip_address", sa.String(45), nullable=True),
            sa.Column("success", sa.Boolean(), nullable=False),
            sa.Column("failure_reason", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_la_identifier_created", "login_attempts", ["identifier", "created_at"])

    # ── 4. users 表增加安全字段 ──
    if "users" in _tables():
        user_cols = _columns("users")
        with op.batch_alter_table("users") as batch_op:
            if "role" not in user_cols:
                batch_op.add_column(sa.Column("role", sa.String(16), nullable=False, server_default="user"))
            if "email_verified" not in user_cols:
                batch_op.add_column(sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
            if "failed_login_attempts" not in user_cols:
                batch_op.add_column(sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"))
            if "locked_until" not in user_cols:
                batch_op.add_column(sa.Column("locked_until", sa.DateTime(), nullable=True))

    # ── 5. conversations 表增加 agent_user 索引 ──
    if "conversations" in _tables() and "idx_conversations_agent_user" not in _indexes("conversations"):
        with op.batch_alter_table("conversations") as batch_op:
            batch_op.create_index("idx_conversations_agent_user", ["agent_id", "user_id"])

    # ── 6. orders 表增加 user_status 索引 ──
    if "orders" in _tables() and "idx_orders_user_status" not in _indexes("orders"):
        with op.batch_alter_table("orders") as batch_op:
            batch_op.create_index("idx_orders_user_status", ["user_id", "status"])

    # ── 7. chart_records 表增加 user_id 字段 ──
    if "chart_records" in _tables() and "user_id" not in _columns("chart_records"):
        with op.batch_alter_table("chart_records") as batch_op:
            batch_op.add_column(sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True, index=True))


def downgrade() -> None:
    # 7. chart_records 移除 user_id
    if "chart_records" in _tables() and "user_id" in _columns("chart_records"):
        with op.batch_alter_table("chart_records") as batch_op:
            batch_op.drop_column("user_id")

    # 6. orders 移除 user_status 索引
    if "orders" in _tables() and "idx_orders_user_status" in _indexes("orders"):
        with op.batch_alter_table("orders") as batch_op:
            batch_op.drop_index("idx_orders_user_status")

    # 5. conversations 移除 agent_user 索引
    if "conversations" in _tables() and "idx_conversations_agent_user" in _indexes("conversations"):
        with op.batch_alter_table("conversations") as batch_op:
            batch_op.drop_index("idx_conversations_agent_user")

    # 4. users 移除安全字段
    if "users" in _tables():
        user_cols = _columns("users")
        with op.batch_alter_table("users") as batch_op:
            for col in ("locked_until", "failed_login_attempts", "email_verified", "role"):
                if col in user_cols:
                    batch_op.drop_column(col)

    # 3. 删除 login_attempts
    if "login_attempts" in _tables():
        op.drop_index("idx_la_identifier_created", table_name="login_attempts")
        op.drop_table("login_attempts")

    # 2. 删除 agent_execution_logs
    if "agent_execution_logs" in _tables():
        for idx in ("idx_ael_agent_status", "idx_ael_session", "idx_ael_user_created"):
            if idx in _indexes("agent_execution_logs"):
                op.drop_index(idx, table_name="agent_execution_logs")
        op.drop_table("agent_execution_logs")

    # 1. 删除 admin_audit_logs
    if "admin_audit_logs" in _tables():
        for idx in ("idx_audit_action", "idx_audit_admin_created"):
            if idx in _indexes("admin_audit_logs"):
                op.drop_index(idx, table_name="admin_audit_logs")
        op.drop_table("admin_audit_logs")
