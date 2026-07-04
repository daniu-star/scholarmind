"""accounts payments and entitlements

Revision ID: e7b1a2c3d4f5
Revises: c4ddc7870a8f
Create Date: 2026-07-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e7b1a2c3d4f5"
down_revision: Union[str, Sequence[str], None] = "c4ddc7870a8f"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(table)
        if index.get("name")
    }


def upgrade() -> None:
    conversation_columns = _columns("conversations")
    with op.batch_alter_table("conversations") as batch_op:
        if "title" not in conversation_columns:
            batch_op.add_column(sa.Column("title", sa.String(128), nullable=True))
        if "user_id" not in conversation_columns:
            batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        if "updated_at" not in conversation_columns:
            batch_op.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
        if "idx_conversations_user_session" not in _indexes("conversations"):
            batch_op.create_index(
                "idx_conversations_user_session", ["user_id", "session_id"]
            )

    if "users" not in _tables():
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("username", sa.String(64), nullable=False),
            sa.Column("phone", sa.String(20), nullable=True),
            sa.Column("password_hash", sa.String(256), nullable=False),
            sa.Column("nickname", sa.String(64), nullable=False, server_default=""),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("plan", sa.String(32), nullable=False, server_default="free"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("username"),
            sa.UniqueConstraint("phone"),
        )
        op.create_index("idx_users_username", "users", ["username"])
        op.create_index(
            "idx_users_phone",
            "users",
            ["phone"],
            unique=True,
            sqlite_where=sa.text("phone IS NOT NULL"),
            postgresql_where=sa.text("phone IS NOT NULL"),
        )
    else:
        if "phone" not in _columns("users"):
            with op.batch_alter_table("users") as batch_op:
                batch_op.add_column(sa.Column("phone", sa.String(20), nullable=True))
        if "idx_users_phone" not in _indexes("users"):
            op.create_index(
                "idx_users_phone",
                "users",
                ["phone"],
                unique=True,
                sqlite_where=sa.text("phone IS NOT NULL"),
                postgresql_where=sa.text("phone IS NOT NULL"),
            )

    if "user_quotas" not in _tables():
        op.create_table(
            "user_quotas",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("tokens_limit", sa.Integer(), nullable=False, server_default="1000000"),
            sa.Column("plan", sa.String(32), nullable=False, server_default="free"),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("free_chats_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("free_chat_limit", sa.Integer(), nullable=False, server_default="20"),
            sa.Column("generation_credits", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("shared_pipeline_credits", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("external_review_expires_at", sa.DateTime(), nullable=True),
            sa.Column("membership_expires_at", sa.DateTime(), nullable=True),
            sa.Column("model_tier", sa.String(16), nullable=False, server_default="flash"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", name="uq_user_quotas_user_id"),
        )
        op.create_index("ix_user_quotas_user_id", "user_quotas", ["user_id"])
    else:
        quota_columns = _columns("user_quotas")
        additions = [
            sa.Column("free_chats_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("free_chat_limit", sa.Integer(), nullable=False, server_default="20"),
            sa.Column("generation_credits", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("shared_pipeline_credits", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("external_review_expires_at", sa.DateTime(), nullable=True),
            sa.Column("membership_expires_at", sa.DateTime(), nullable=True),
            sa.Column("model_tier", sa.String(16), nullable=False, server_default="flash"),
        ]
        with op.batch_alter_table("user_quotas") as batch_op:
            for column in additions:
                if column.name not in quota_columns:
                    batch_op.add_column(column)
            if "idx_user_quotas_user_unique" not in _indexes("user_quotas"):
                batch_op.create_index(
                    "idx_user_quotas_user_unique", ["user_id"], unique=True
                )

    if "orders" not in _tables():
        op.create_table(
            "orders",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("order_no", sa.String(64), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("plan", sa.String(32), nullable=False),
            sa.Column("amount", sa.Integer(), nullable=False),
            sa.Column("payment_method", sa.String(16), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("trade_no", sa.String(64), nullable=True),
            sa.Column("paid_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("entitlements_granted_at", sa.DateTime(), nullable=True),
            sa.Column("provider_payload", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("order_no"),
        )
        op.create_index("ix_orders_order_no", "orders", ["order_no"], unique=True)
    else:
        order_columns = _columns("orders")
        additions = [
            sa.Column("trade_no", sa.String(64), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("entitlements_granted_at", sa.DateTime(), nullable=True),
            sa.Column("provider_payload", sa.JSON(), nullable=True),
        ]
        with op.batch_alter_table("orders") as batch_op:
            for column in additions:
                if column.name not in order_columns:
                    batch_op.add_column(column)
    if "idx_orders_trade_no_unique" not in _indexes("orders"):
        op.create_index(
            "idx_orders_trade_no_unique",
            "orders",
            ["trade_no"],
            unique=True,
            sqlite_where=sa.text("trade_no IS NOT NULL"),
            postgresql_where=sa.text("trade_no IS NOT NULL"),
        )

    if "entitlement_grants" not in _tables():
        op.create_table(
            "entitlement_grants",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("source_ref", sa.String(96), nullable=False),
            sa.Column("product_id", sa.String(32), nullable=False),
            sa.Column("granted_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("source_ref"),
        )
        op.create_index(
            "ix_entitlement_grants_source_ref",
            "entitlement_grants",
            ["source_ref"],
            unique=True,
        )
        op.create_index(
            "ix_entitlement_grants_user_id",
            "entitlement_grants",
            ["user_id"],
        )


def downgrade() -> None:
    for table in ("entitlement_grants", "orders", "user_quotas", "users"):
        if table in _tables():
            op.drop_table(table)
    if "conversations" in _tables():
        columns = _columns("conversations")
        with op.batch_alter_table("conversations") as batch_op:
            if "idx_conversations_user_session" in _indexes("conversations"):
                batch_op.drop_index("idx_conversations_user_session")
            for column in ("updated_at", "user_id", "title"):
                if column in columns:
                    batch_op.drop_column(column)
