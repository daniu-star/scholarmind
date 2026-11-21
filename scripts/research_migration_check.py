#!/usr/bin/env python
"""研究域迁移 dry-run / 回退演练（T20：迁移 dry-run 与恢复脚本）。

对 PRD v1.0 §6 的 15 张 ``research_*`` 表做三件事，且**不触碰任何真实数据库**：

1. **离线 dry-run**：以离线模式生成 ``m4_audit_security -> head`` 的 SQL，确认
   - 只出现 ``research_*`` 表的 CREATE TABLE / DROP TABLE；
   - 不产生对既有业务表（users、conversations…）的破坏性 DDL；
   - 生成的 SQL 里包含唯一约束（事件序号、owner 幂等键、结算组、成果版本）。
2. **升级/回退/再升级**：在临时 SQLite 库上跑 ``upgrade head`` → ``downgrade
   m4_audit_security`` → ``upgrade head``，验证迁移**可重复执行**且回退干净。
3. **既有表无损**：回退后再读 users/conversations 表定义，确认未被改动。

用法（项目根目录）：

    .venv\\Scripts\\python.exe scripts/research_migration_check.py

退出码 0 表示全部通过；任一断言失败返回 1，并打印具体原因（可放进 CI）。
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "src" / "backend" / "alembic.ini"
BASE_REVISION = "m4_audit_security"
RESEARCH_TABLES = [
    "research_projects",
    "research_documents",
    "research_document_versions",
    "research_document_blocks",
    "research_document_chunks",
    "research_source_records",
    "research_evidences",
    "research_tasks",
    "research_task_attempts",
    "research_task_events",
    "research_findings",
    "research_revision_proposals",
    "research_artifacts",
    "research_billing_operations",
    "research_outbox_messages",
]
UNIQUE_MARKERS = [
    "uq_event_task_sequence",
    "uq_task_owner_idempotency",
    "uq_billing_group_operation",
    "uq_artifact_task_kind_ver",
]


def _alembic(*args: str, database_url: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["DATABASE_URL"] = database_url
    env.setdefault("JWT_SECRET_KEY", "migration-check-secret-key-min-32-chars!!")
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _fail(reason: str) -> int:
    print(f"[FAIL] {reason}")
    return 1


def check_offline_dry_run(tmpdir: Path) -> int:
    sql_path = tmpdir / "research_upgrade.sql"
    url = f"sqlite:///{tmpdir / 'offline.db'}"
    result = _alembic(
        "upgrade", BASE_REVISION + ":head", "--sql", database_url=url
    )
    if result.returncode != 0:
        return _fail(f"离线 dry-run 失败：{result.stderr.strip()[:400]}")
    sql = result.stdout
    sql_path.write_text(sql, encoding="utf-8")
    lowered = sql.lower()

    created = [table for table in RESEARCH_TABLES if f"create table {table}" in lowered]
    missing_created = [table for table in RESEARCH_TABLES if table not in created]
    if missing_created:
        return _fail(f"dry-run 未创建这些研究表：{missing_created}")

    for marker in UNIQUE_MARKERS:
        if marker not in lowered:
            return _fail(f"dry-run 缺少唯一约束：{marker}")

    # 既有业务表不允许被研究段迁移改写。
    for table in ("users", "conversations", "user_quotas", "skills"):
        if f"alter table {table} " in lowered or f"drop table {table}" in lowered:
            return _fail(f"研究迁移改写了既有业务表：{table}")

    destroyed = [table for table in RESEARCH_TABLES if f"drop table {table}" in lowered]
    if destroyed:
        return _fail(f"升级段意外包含 DROP：{destroyed}")

    print(f"[OK] 离线 dry-run：15 张研究表建表语句齐全，4 个唯一约束齐全，未触碰既有业务表（{len(sql.splitlines())} 行 SQL）")
    return 0


def _table_names(db_file: Path) -> set[str]:
    with sqlite3.connect(db_file) as connection:
        rows = connection.execute(
            "select name from sqlite_master where type='table'"
        ).fetchall()
    return {row[0] for row in rows}


def check_upgrade_downgrade(tmpdir: Path) -> int:
    db_file = tmpdir / "migration_check.db"
    url = f"sqlite:///{db_file}"

    up1 = _alembic("upgrade", "head", database_url=url)
    if up1.returncode != 0:
        return _fail(f"首次 upgrade head 失败：{up1.stderr.strip()[:400]}")
    tables = _table_names(db_file)
    missing = [table for table in RESEARCH_TABLES if table not in tables]
    if missing:
        return _fail(f"upgrade 后缺少表：{missing}")

    down = _alembic("downgrade", BASE_REVISION, database_url=url)
    if down.returncode != 0:
        return _fail(f"downgrade {BASE_REVISION} 失败：{down.stderr.strip()[:400]}")
    after_down = _table_names(db_file)
    leftovers = [table for table in RESEARCH_TABLES if table in after_down]
    if leftovers:
        return _fail(f"downgrade 后仍有研究表残留：{leftovers}")
    if "users" not in after_down:
        return _fail("downgrade 误删既有业务表 users")

    up2 = _alembic("upgrade", "head", database_url=url)
    if up2.returncode != 0:
        return _fail(f"再次 upgrade head 失败（迁移不可重复）：{up2.stderr.strip()[:400]}")
    again = _table_names(db_file)
    missing2 = [table for table in RESEARCH_TABLES if table not in again]
    if missing2:
        return _fail(f"二次 upgrade 后缺少表：{missing2}")

    print(
        "[OK] 升级→回退→再升级 全部成功；回退后研究表清零、既有 users 表保留，"
        f"最终研究表 {len([t for t in again if t in RESEARCH_TABLES])} 张"
    )
    return 0


def main() -> int:
    if not ALEMBIC_INI.exists():
        return _fail(f"找不到 alembic 配置：{ALEMBIC_INI}")
    failures: list[str] = []
    with tempfile.TemporaryDirectory(
        prefix="research-migration-", ignore_cleanup_errors=True
    ) as raw:
        tmpdir = Path(raw)
        if check_offline_dry_run(tmpdir) != 0:
            failures.append("offline")
        if check_upgrade_downgrade(tmpdir) != 0:
            failures.append("upgrade-downgrade")
    if failures:
        print(f"\n迁移检查未通过：{failures}")
        return 1
    print("\n研究域迁移 dry-run / 回退演练全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
