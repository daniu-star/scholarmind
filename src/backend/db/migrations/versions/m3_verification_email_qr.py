"""verification codes, user email, and payment QR fields

Revision ID: m3_verification_qr
Revises: e7b1a2c3d4f5
Create Date: 2026-07-03

迁移内容（替代 db/session.py 中的 _migrate_verification_and_qr 手动迁移）:
  1. 创建 verification_codes 表（验证码存储）
  2. users 表增加 email 列 + 唯一索引
  3. orders 表增加个人收款码相关字段
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "m3_verification_qr"
down_revision: Union[str, Sequence[str], None] = "e7b1a2c3d4f5"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table) if i.get("name")}


def upgrade() -> None:
    # ── 1. 创建 verification_codes 表 ──
    if "verification_codes" not in _tables():
        op.create_table(
            "verification_codes",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("target", sa.String(128), nullable=False, comment="手机号或邮箱地址"),
            sa.Column("code", sa.String(6), nullable=False),
            sa.Column("purpose", sa.String(16), nullable=False, server_default="login"),
            sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_vc_target_purpose", "verification_codes", ["target", "purpose"])
        op.create_index("idx_vc_target_created", "verification_codes", ["target", "created_at"])
        op.create_index("ix_verification_codes_target", "verification_codes", ["target"])

    # ── 2. users 表增加 email 列 ──
    if "users" in _tables() and "email" not in _columns("users"):
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(sa.Column("email", sa.String(128), nullable=True, comment="用户邮箱"))
    if "users" in _tables() and "idx_users_email" not in _indexes("users"):
        op.create_index(
            "idx_users_email",
            "users",
            ["email"],
            unique=True,
            sqlite_where=sa.text("email IS NOT NULL"),
            postgresql_where=sa.text("email IS NOT NULL"),
        )

    # ── 3. orders 表增加个人收款码字段 ──
    if "orders" in _tables():
        order_cols = _columns("orders")
        with op.batch_alter_table("orders") as batch_op:
            if "payment_mode" not in order_cols:
                batch_op.add_column(sa.Column(
                    "payment_mode", sa.String(16), nullable=False,
                    server_default="api", comment="api | personal_qr"
                ))
            if "proof_uploaded" not in order_cols:
                batch_op.add_column(sa.Column(
                    "proof_uploaded", sa.Boolean(), nullable=False,
                    server_default=sa.false(), comment="是否上传了支付凭证"
                ))
            if "proof_filename" not in order_cols:
                batch_op.add_column(sa.Column(
                    "proof_filename", sa.String(256), nullable=True
                ))
            if "confirmed_by" not in order_cols:
                batch_op.add_column(sa.Column(
                    "confirmed_by", sa.Integer(),
                    sa.ForeignKey("users.id"), nullable=True,
                    comment="确认支付的管理员ID"
                ))
            if "confirmed_at" not in order_cols:
                batch_op.add_column(sa.Column(
                    "confirmed_at", sa.DateTime(), nullable=True
                ))


def downgrade() -> None:
    # 3. 移除 orders 个人收款码字段
    if "orders" in _tables():
        order_cols = _columns("orders")
        with op.batch_alter_table("orders") as batch_op:
            for col in ("confirmed_at", "confirmed_by", "proof_filename", "proof_uploaded", "payment_mode"):
                if col in order_cols:
                    batch_op.drop_column(col)

    # 2. 移除 users email
    if "users" in _tables():
        if "idx_users_email" in _indexes("users"):
            with op.batch_alter_table("users") as batch_op:
                batch_op.drop_index("idx_users_email")
        if "email" in _columns("users"):
            with op.batch_alter_table("users") as batch_op:
                batch_op.drop_column("email")

    # 1. 删除 verification_codes 表
    if "verification_codes" in _tables():
        op.drop_index("ix_verification_codes_target", table_name="verification_codes")
        op.drop_index("idx_vc_target_created", table_name="verification_codes")
        op.drop_index("idx_vc_target_purpose", table_name="verification_codes")
        op.drop_table("verification_codes")
