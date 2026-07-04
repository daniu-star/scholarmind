"""
Alembic 迁移环境配置
使用 settings.DATABASE_URL 和 ORM Base.metadata
"""
import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# 确保项目根目录 c:\Users\13067\Desktop\AI产品 在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.config import settings
from src.backend.db.session import Base
# 导入所有 ORM 模型以确保它们被注册到 Base.metadata
# 导入所有 ORM 模型以确保 Alembic autogenerate 能检测到完整 schema
from src.backend.models.orm import (  # noqa: F401
    Conversation, Skill, ChartRecord,
    User, UserQuota, Order, EntitlementGrant, VerificationCode,
    AdminAuditLog, AgentExecutionLog, LoginAttempt,
)

# Alembic Config 对象
config = context.config

# 覆盖 sqlalchemy.url 为实际配置（Alembic 需要同步驱动）
db_url = settings.DATABASE_URL
# 将异步驱动替换为同步驱动（Alembic 不支持异步）
if "+aiosqlite" in db_url:
    db_url = db_url.replace("+aiosqlite", "")
config.set_main_option("sqlalchemy.url", db_url)

# 配置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 设置 target_metadata
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：生成 SQL 脚本"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：直接连接数据库执行迁移"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite 需要的批量模式
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()