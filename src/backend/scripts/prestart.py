"""
Railway pre-start 脚本 — 在应用启动前执行 schema 迁移。
处理 create_all() 无法修改已存在表的问题（ALTER TABLE ADD COLUMN IF NOT EXISTS）。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.config import settings
from src.backend.db.session import create_async_engine_from_url
from sqlalchemy import text as sa_text
import asyncio


MIGRATIONS = [
    # (table, column, type, default)
    ("users", "email", "VARCHAR(128)", None),
    ("users", "email_verified", "BOOLEAN", "FALSE"),
    ("users", "failed_login_attempts", "INTEGER", "0"),
    ("users", "locked_until", "TIMESTAMP WITH TIME ZONE", None),
]


async def run_migrations():
    engine = create_async_engine_from_url()
    async with engine.connect() as conn:
        for table, col, col_type, default_val in MIGRATIONS:
            default_clause = f" DEFAULT {default_val}" if default_val else ""
            try:
                sql = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}{default_clause}"
                await conn.execute(sa_text(sql))
                await conn.commit()
                print(f"[prestart] ensured {table}.{col}")
            except Exception:
                try:
                    sql2 = f"ALTER TABLE {table} ADD COLUMN {col} {col_type}{default_clause}"
                    await conn.execute(sa_text(sql2))
                    await conn.commit()
                    print(f"[prestart] added {table}.{col}")
                except Exception as e2:
                    print(f"[prestart] skip {table}.{col}: {e2}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migrations())
    print("[prestart] done")
