"""research R1: attempt checkpoints (PRD v1.0 T15)

Revision ID: m6_research_attempt_checkpoint
Revises: m5_research_domain
Create Date: 2026-11-20

T15 要求"保存检查点并合并"：诊断/修改任务按分析单元推进，重试必须从检查点
继续，而不是从零重跑（否则覆盖记录会虚报、额度会重复消耗）。
这里给 ``research_task_attempts`` 增加 ``checkpoint_json``；
表不存在时（空库先跑 create_all 的场景）由 create_all 负责，迁移保持幂等。

离线模式（``alembic upgrade --sql``）没有连接、无法 inspect：
直接输出 ADD COLUMN / DROP COLUMN 语句供 dry-run 审阅。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "m6_research_attempt_checkpoint"
down_revision: Union[str, Sequence[str], None] = "m5_research_domain"
branch_labels = None
depends_on = None

TABLE = "research_task_attempts"
COLUMN = "checkpoint_json"


def _offline() -> bool:
    return bool(op.get_context().as_sql)


def upgrade() -> None:
    if _offline():
        op.add_column(TABLE, sa.Column(COLUMN, sa.JSON(), nullable=True))
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if COLUMN in columns:
        return
    op.add_column(TABLE, sa.Column(COLUMN, sa.JSON(), nullable=True))


def downgrade() -> None:
    if _offline():
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_column(COLUMN)
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if COLUMN not in columns:
        return
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column(COLUMN)
