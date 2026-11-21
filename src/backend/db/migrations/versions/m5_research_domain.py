"""research domain tables (PRD v1.0 §6)

Revision ID: m5_research_domain
Revises: m4_audit_security
Create Date: 2026-11-19

说明：15 张研究领域表的建表方式按 ``Base.metadata`` 排序后创建，
避免在迁移里重复声明一遍字段而与 ORM 漂移；仅当表不存在时创建。

离线模式（``alembic upgrade --sql``）没有真实连接、无法 ``inspect``，
此时直接输出建表/删表语句：离线 SQL 只用于 dry-run 审阅与 DBA 预演，
不会落库，因此不需要表存在性判断。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "m5_research_domain"
down_revision: Union[str, Sequence[str], None] = "m4_audit_security"
branch_labels = None
depends_on = None


def _research_tables():
    """返回研究领域表（按外键依赖排序）。"""
    from src.backend.db.session import Base
    from src.backend.research import models as _research_models  # noqa: F401

    return [
        table
        for table in Base.metadata.sorted_tables
        if table.name.startswith("research_")
    ]


def _offline() -> bool:
    return bool(op.get_context().as_sql)


def upgrade() -> None:
    bind = op.get_bind()
    existing = set() if _offline() else set(_inspect_table_names(bind))
    for table in _research_tables():
        if table.name not in existing:
            table.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    existing = (
        {table.name for table in _research_tables()}
        if _offline()
        else set(_inspect_table_names(bind))
    )
    for table in reversed(_research_tables()):
        if table.name in existing:
            table.drop(bind, checkfirst=True)


def _inspect_table_names(bind) -> list:
    import sqlalchemy as sa

    return sa.inspect(bind).get_table_names()
