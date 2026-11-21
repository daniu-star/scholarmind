#!/usr/bin/env python
"""生产同构恢复演练：真实 PostgreSQL 上的租约、崩溃接管、重复投递与持久化。

为什么需要这个脚本
------------------
R0–R2 的所有自动化测试都跑在 SQLite 上；SQLite 没有真实的行级并发、没有
``SELECT ... FOR UPDATE`` 语义差异、也没有服务端崩溃与重启。PRD FR-11 要求
「任务登记、租约/fencing、事件序号重放」在真实数据库上成立，本脚本用
**便携版 PostgreSQL 16** 起一个真实集群，按以下顺序演练：

1. 迁移：``alembic upgrade head`` 在 PG 上真正执行 DDL，并核对研究域表与唯一约束；
2. 崩溃前：子进程 A 领取租约（短租约）、写入 ``task.started``、随后被 SIGKILL；
3. 崩溃后：租约到期，主进程 B 重新领取（``attempt_no=2``/``fencing_token=2``）并完成
   任务，核对「只有一次终态事件、只有一份成果、只结算一次」；
4. 迟到写入：用已过期且被接管的第一份 attempt 再写事件/迁移状态，记录它是否被拒绝；
5. 重复投递：两个子进程同时执行同一任务，核对只执行一次；
6. 数据库崩溃重启：``pg_ctl restart -m immediate`` 后核对任务与事件仍在、序号连续。

用法
----
    ./.venv/Scripts/python.exe scripts/research_recovery_drill.py --keep

如实边界（报告里同样写明）：
- Redis/Celery 不在本演练内：本机没有 Redis 服务，研究域目前的执行链路是进程内
  dispatcher（``TASK_BACKEND=background``），Celery 只覆盖旧链路；不假装覆盖。
- 演练使用替身模型（``RESEARCH_MODEL_STUB=true``），只验证恢复语义，不产生质量证据。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import subprocess
import sys
import time
from typing import Any, Optional

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# PostgreSQL 的 initdb / 数据目录不接受非 ASCII 路径（本仓库路径含中文，
# 实测 "invalid byte sequence for encoding UTF8"），故集群放在 ASCII 目录；
# 压缩包仍留在仓库 tmp/pg 下。
# 说明：仓库路径含中文，PG 的 initdb/postgres 在 Windows 上不接受非 ASCII 数据目录；
# 同时本机 AppData\Local\Temp 对当前进程不可写。故默认用 subst 映射出的 ASCII 盘符：
#   powershell -NoProfile -Command "subst X: '<repo>'"
# 可用 DRILL_PG_ROOT 覆盖。
PG_ROOT = pathlib.Path(os.environ.get("DRILL_PG_ROOT", r"X:\pgdrill"))
PG_BIN = PG_ROOT / "pgsql" / "bin"
PG_DATA = PG_ROOT / "data"
PG_LOG = PG_ROOT / "pg.log"
PG_CTL_LOG = PG_ROOT / "pgctl.log"
PG_ZIP = REPO_ROOT / "tmp" / "pg" / "pg-win.zip"
DRILL_JSON = REPO_ROOT / "tmp" / "recovery-drill.json"
PG_USER = "postgres"
PG_DB = "scholarmind_drill"
DEFAULT_PORT = 55432


def _pg(name: str) -> str:
    exe = PG_BIN / f"{name}.exe"
    return str(exe) if exe.exists() else str(PG_BIN / name)


def _run(cmd: list[str], *, env: Optional[dict] = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env or os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ── PostgreSQL 集群生命周期 ─────────────────────────────────────


def ensure_pg(port: int) -> tuple[str, int]:
    """确保便携版 PG 已解压、已 initdb、正在监听；返回 (asyncpg URL, 实际端口)。"""
    if not PG_BIN.exists():
        if not PG_ZIP.exists():
            raise SystemExit(
                f"缺少便携版 PostgreSQL 压缩包：{PG_ZIP}\n"
                "下载：https://get.enterprisedb.com/postgresql/"
                "postgresql-16.4-1-windows-x64-binaries.zip"
            )
        print(f"[drill] 解压 {PG_ZIP} …")
        import zipfile

        with zipfile.ZipFile(PG_ZIP) as zf:
            zf.extractall(PG_ROOT)
        print(f"[drill] 解压完成：{PG_BIN}")

    if not (PG_DATA / "PG_VERSION").exists():
        print("[drill] initdb …")
        res = _run(
            [
                _pg("initdb"),
                "-D",
                str(PG_DATA),
                "-U",
                PG_USER,
                "--auth=trust",
                "--encoding=UTF8",
                "--locale=C",
            ],
            timeout=300,
        )
        if res.returncode != 0:
            raise SystemExit(f"initdb 失败：\n{res.stdout}\n{res.stderr}")

    chosen = None
    for candidate in range(port, port + 40):
        if not pg_ready(candidate):
            chosen = candidate
            break
        owner_dir = _server_data_dir(candidate)
        if owner_dir and _same_path(owner_dir, str(PG_DATA)):
            chosen = candidate
            break
        print(f"[drill] 端口 {candidate} 被其它 PG 占用（data_directory={owner_dir}），换端口")
    if chosen is None:
        raise SystemExit(f"从 {port} 起 40 个端口都被占用，无法启动演练用 PG")
    port = chosen

    if not pg_ready(port):
        print(f"[drill] pg_ctl start（端口 {port}）…")
        start_pg(port)

    owner_dir = _server_data_dir(port)
    if not owner_dir or not _same_path(owner_dir, str(PG_DATA)):
        raise SystemExit(
            f"端口 {port} 上的 PG 不是本次演练的集群（data_directory={owner_dir}，期望 {PG_DATA}）"
        )

    # 建库（幂等）
    res = _run(
        [_pg("psql"), "-h", "127.0.0.1", "-p", str(port), "-U", PG_USER, "-d", "postgres",
         "-tAc", f"SELECT 1 FROM pg_database WHERE datname='{PG_DB}'"]
    )
    if "1" not in (res.stdout or ""):
        res = _run([_pg("createdb"), "-h", "127.0.0.1", "-p", str(port), "-U", PG_USER, PG_DB])
        if res.returncode != 0:
            raise SystemExit(f"createdb 失败：{res.stderr}")

    return f"postgresql+asyncpg://{PG_USER}@127.0.0.1:{port}/{PG_DB}", port


def _server_data_dir(port: int) -> Optional[str]:
    """查询监听在该端口上的 PG 实际 data_directory（用于识别端口被别的项目占用）。"""
    res = _run(
        [_pg("psql"), "-h", "127.0.0.1", "-p", str(port), "-U", PG_USER, "-d", "postgres",
         "-tAc", "show data_directory"],
        timeout=25,
    )
    return (res.stdout or "").strip() or None if res.returncode == 0 else None


def _same_path(a: str, b: str) -> bool:
    pa = pathlib.Path(a.strip()).as_posix().rstrip("/").lower()
    pb = pathlib.Path(b.strip()).as_posix().rstrip("/").lower()
    return pa == pb


def start_pg(port: int) -> None:
    """显式带端口启动（不依赖 postmaster.opts；崩溃重启也走这里）。

    注意：不能对 pg_ctl 用 ``capture_output=True``——postgres 会继承这些管道，
    pg_ctl 退出后父进程仍等不到 EOF（实测挂起 10 分钟以上）。改用文件重定向。
    """
    cmd = [
        _pg("pg_ctl"),
        "start",
        "-D",
        str(PG_DATA),
        "-l",
        str(PG_LOG),
        "-o",
        f'-p {port} -c listen_addresses=127.0.0.1 -c fsync=on',
        "-w",
        "-t",
        "90",
    ]
    with open(PG_CTL_LOG, "ab") as log:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            timeout=240,
        )
    if proc.returncode != 0:
        tail = ""
        try:
            tail = PG_CTL_LOG.read_text(encoding="utf-8", errors="replace")[-2000:]
        except OSError:  # pragma: no cover
            pass
        raise SystemExit(f"pg_ctl start 失败（exit {proc.returncode}）：\n{tail}\n日志见 {PG_LOG}")


def stop_pg(mode: str = "immediate") -> None:
    """停止集群；未运行时忽略错误（崩溃演练需要幂等）。"""
    cmd = [_pg("pg_ctl"), "stop", "-D", str(PG_DATA), "-m", mode, "-w", "-t", "60"]
    with open(PG_CTL_LOG, "ab") as log:
        subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            timeout=180,
            check=False,
        )


def pg_ready(port: int) -> bool:
    res = _run([_pg("pg_isready"), "-h", "127.0.0.1", "-p", str(port)], timeout=20)
    return res.returncode == 0


def pg_ctl(port: int, action: str, *, mode: Optional[str] = None) -> None:
    cmd = [_pg("pg_ctl"), action, "-D", str(PG_DATA), "-w", "-t", "60"]
    if mode:
        cmd += ["-m", mode]
    res = _run(cmd, timeout=180)
    if res.returncode != 0:
        raise SystemExit(f"pg_ctl {action} 失败：\n{res.stdout}\n{res.stderr}")


# ── 环境准备：迁移 + 数据 ─────────────────────────────────────


def run_migrations(sync_url: str) -> dict:
    """在 PG 上执行 alembic upgrade head；返回迁移后核对结果。"""
    env = os.environ.copy()
    env["DATABASE_URL"] = sync_url
    env["ENVIRONMENT"] = "test"
    res = _run(
        [sys.executable, "-m", "alembic", "-c", "src/backend/alembic.ini", "upgrade", "head"],
        env=env,
        timeout=300,
    )
    if res.returncode != 0:
        raise SystemExit(f"alembic upgrade 失败：\n{res.stdout[-4000:]}\n{res.stderr[-4000:]}")
    return {"alembic_exit": res.returncode, "alembic_tail": (res.stdout or "").strip().splitlines()[-3:]}


async def pg_schema_facts(async_url: str) -> dict:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(async_url, future=True)
    facts: dict[str, Any] = {}
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema='public' AND table_name LIKE 'research_%' "
                        "ORDER BY table_name"
                    )
                )
            ).scalars().all()
            facts["research_tables"] = list(rows)
            facts["research_table_count"] = len(rows)
            cons = (
                await conn.execute(
                    text(
                        "SELECT conname FROM pg_constraint WHERE contype='u' "
                        "AND conname IN ('uq_event_task_sequence','uq_task_owner_idempotency',"
                        "'uq_billing_group_operation','uq_artifact_task_kind_ver') ORDER BY conname"
                    )
                )
            ).scalars().all()
            facts["unique_constraints"] = list(cons)
            facts["server_version"] = (
                await conn.execute(text("SHOW server_version"))
            ).scalar_one()
    finally:
        await engine.dispose()
    return facts


async def prepare_task(async_url: str, *, lease_seconds: int) -> dict:
    """建用户/授权益/项目/文档/任务，返回任务与文档标识。"""
    from src.backend.db.session import (
        create_async_engine_from_url,
        create_async_sessionmaker_from_engine,
    )
    from src.backend.models.orm import User, UserQuota
    from src.backend.research.contracts import Actor
    from src.backend.research.document_service import upload_document
    from src.backend.research.project_service import create_project
    from src.backend.research.task_service import create_task
    from src.backend.services.auth_service import get_password_hash
    from src.backend.services.entitlement_service import EntitlementService

    engine = create_async_engine_from_url(async_url)
    session_factory = create_async_sessionmaker_from_engine(engine)
    body_text = (
        "# 引言\n\n"
        + "本文讨论平台算法与新闻消费的关系，关注推荐系统如何改变用户的信息接触结构。" * 30
        + "\n\n# 方法\n\n"
        + "研究采用问卷与日志结合的混合设计，样本 1200 人，辅以 24 次深度访谈。" * 30
        + "\n"
    )
    try:
        async with session_factory() as db:
            user = User(
                username=f"recovery_drill_user_{int(time.time() * 1000)}",
                password_hash=get_password_hash("drill_pass_123"),
                nickname="RecoveryDrill",
                is_active=True,
                plan="free",
            )
            db.add(user)
            await db.flush()
            db.add(UserQuota(user_id=user.id, plan="free"))
            await db.flush()
            await EntitlementService.grant_product(
                db, user.id, "monthly_pro", f"recovery-drill-grant-{int(time.time() * 1000)}"
            )
            actor = Actor(user_id=user.id)
            project = await create_project(db, actor, "恢复演练项目")
            uploaded = await upload_document(
                db,
                actor,
                project["id"],
                filename="recovery-drill.md",
                mime="text/markdown",
                data=body_text.encode("utf-8"),
            )
            version_id = uploaded["version"]["id"]
            task = await create_task(
                db,
                actor,
                {
                    "schema_version": "1.0",
                    "project_id": project["id"],
                    "kind": "review",
                    "objective": "检查全文论证与证据问题",
                    "input": {"document_version_id": version_id},
                },
                idempotency_key="recovery-drill-task-1",
            )
            await db.commit()
            return {
                "user_id": user.id,
                "project_id": project["id"],
                "document_id": uploaded["document"]["id"],
                "version_id": version_id,
                "task_id": task.task_id,
                "lease_seconds": lease_seconds,
            }
    finally:
        await engine.dispose()


async def prepare_second_task(async_url: str, info: dict) -> str:
    """为「重复投递」再建一个任务（同一文档，独立幂等键）。"""
    from src.backend.db.session import (
        create_async_engine_from_url,
        create_async_sessionmaker_from_engine,
    )
    from src.backend.research.contracts import Actor
    from src.backend.research.task_service import create_task

    engine = create_async_engine_from_url(async_url)
    session_factory = create_async_sessionmaker_from_engine(engine)
    try:
        async with session_factory() as db:
            task = await create_task(
                db,
                Actor(user_id=info["user_id"]),
                {
                    "schema_version": "1.0",
                    "project_id": info["project_id"],
                    "kind": "review",
                    "objective": "检查全文论证与证据问题（重复投递演练）",
                    "input": {"document_version_id": info["version_id"]},
                },
                idempotency_key="recovery-drill-task-2",
            )
            await db.commit()
            return task.task_id
    finally:
        await engine.dispose()


# ── 子进程角色 ────────────────────────────────────────────────


async def _child_claim(task_id: str, lease_seconds: int, marker: str) -> None:
    """领取租约、写 task.started、落 marker，然后挂起等待被杀死。"""
    from src.backend.db.session import (
        create_async_engine_from_url,
        create_async_sessionmaker_from_engine,
    )
    from src.backend.research.contracts import EventType
    from src.backend.research.models import ResearchTask
    from src.backend.research import task_repository

    engine = create_async_engine_from_url(os.environ["DRILL_ASYNC_URL"])
    session_factory = create_async_sessionmaker_from_engine(engine)
    async with session_factory() as db:
        task = await db.get(ResearchTask, task_id)
        attempt = await task_repository.open_attempt(
            db, task, lease_holder="drill-worker-a", lease_seconds=lease_seconds
        )
        await task_repository.append_event(
            db, task, EventType.TASK_STARTED.value, payload={"holder": "drill-worker-a"}
        )
        await db.commit()
        pathlib.Path(marker).write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "attempt_no": attempt.attempt_no,
                    "fencing_token": attempt.fencing_token,
                    "lease_expires_at": attempt.lease_expires_at.isoformat(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    await asyncio.sleep(600)


async def _child_execute(task_id: str, holder: str) -> None:
    """模拟一次「重复投递」的投递方：直接并发执行同一任务。"""
    from src.backend.db.session import (
        create_async_engine_from_url,
        create_async_sessionmaker_from_engine,
    )
    from src.backend.research.models import ResearchTask
    from src.backend.research.task_runner import execute_task

    engine = create_async_engine_from_url(os.environ["DRILL_ASYNC_URL"])
    session_factory = create_async_sessionmaker_from_engine(engine)
    async with session_factory() as db:
        task = await db.get(ResearchTask, task_id)
        await execute_task(db, task, holder=holder)
        await db.commit()
    await engine.dispose()


# ── 主演练流程 ────────────────────────────────────────────────


async def _db_facts(async_url: str, task_id: str) -> dict:
    from sqlalchemy import select
    from src.backend.db.session import (
        create_async_engine_from_url,
        create_async_sessionmaker_from_engine,
    )
    from src.backend.research.models import (
        Artifact,
        BillingOperation,
        ResearchTask,
        TaskEvent,
        TaskAttempt,
    )

    engine = create_async_engine_from_url(async_url)
    session_factory = create_async_sessionmaker_from_engine(engine)
    try:
        async with session_factory() as db:
            task = await db.get(ResearchTask, task_id)
            attempts = (
                await db.execute(
                    select(TaskAttempt.attempt_no, TaskAttempt.status, TaskAttempt.fencing_token,
                           TaskAttempt.lease_holder, TaskAttempt.lease_expires_at)
                    .where(TaskAttempt.task_id == task_id)
                    .order_by(TaskAttempt.attempt_no)
                )
            ).all()
            terminal = (
                await db.execute(
                    select(TaskEvent.sequence, TaskEvent.type)
                    .where(
                        TaskEvent.task_id == task_id,
                        TaskEvent.type.in_(
                            ["task.completed", "task.partial", "task.failed", "task.cancelled"]
                        ),
                    )
                )
            ).all()
            events = (
                await db.execute(
                    select(TaskEvent.sequence).where(TaskEvent.task_id == task_id).order_by(TaskEvent.sequence)
                )
            ).scalars().all()
            artifacts = (
                await db.execute(
                    select(Artifact.id).where(Artifact.task_id == task_id)
                )
            ).scalars().all()
            ledger = (
                await db.execute(
                    select(BillingOperation.id, BillingOperation.state)
                    .where(BillingOperation.task_id == task_id)
                )
            ).all()
            return {
                "task_status": task.status if task else None,
                "attempt_no": task.attempt_no if task else None,
                "attempts": [
                    {
                        "attempt_no": a[0],
                        "status": a[1],
                        "fencing_token": a[2],
                        "lease_holder": a[3],
                        "lease_expires_at": a[4].isoformat() if a[4] else None,
                    }
                    for a in attempts
                ],
                "terminal_events": [{"sequence": e[0], "type": e[1]} for e in terminal],
                "terminal_event_count": len(terminal),
                "event_sequences": list(events),
                "event_types": [
                    t
                    for t in (
                        await db.execute(
                            select(TaskEvent.type)
                            .where(TaskEvent.task_id == task_id)
                            .order_by(TaskEvent.sequence)
                        )
                    ).scalars().all()
                ],
                "events_monotonic": all(b > a for a, b in zip(events, events[1:])),
                "artifact_count": len(artifacts),
                "billing_operations": [{"id": b[0], "state": b[1]} for b in ledger],
                "settled_count": sum(1 for b in ledger if b[1] in ("settled", "reserved")),
                "quality_verdict": task.quality_verdict if task else None,
            }
    finally:
        await engine.dispose()


def wait_marker(path: pathlib.Path, timeout: float = 60.0) -> Optional[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                time.sleep(0.2)
                continue
        time.sleep(0.1)
    return None


async def _lease_expired(async_url: str, task_id: str) -> bool:
    """真实数据库时钟判断 attempt 1 的租约是否已过期。"""
    from sqlalchemy import select
    from src.backend.db.session import (
        create_async_engine_from_url,
        create_async_sessionmaker_from_engine,
    )
    from src.backend.research.contracts import utcnow
    from src.backend.research.models import TaskAttempt

    engine = create_async_engine_from_url(async_url)
    sf = create_async_sessionmaker_from_engine(engine)
    try:
        async with sf() as db:
            row = (
                await db.execute(
                    select(TaskAttempt.lease_expires_at)
                    .where(TaskAttempt.task_id == task_id, TaskAttempt.attempt_no == 1)
                )
            ).scalar_one_or_none()
            return bool(row is not None and row <= utcnow())
    finally:
        await engine.dispose()


async def reclaim_and_finish(async_url: str, task_id: str) -> dict:
    """租约到期后由第二个执行器接管并完成（真实 execute_task 路径）。"""
    from src.backend.db.session import (
        create_async_engine_from_url,
        create_async_sessionmaker_from_engine,
    )
    from src.backend.research.models import ResearchTask
    from src.backend.research.task_runner import execute_task

    engine = create_async_engine_from_url(async_url)
    session_factory = create_async_sessionmaker_from_engine(engine)
    try:
        async with session_factory() as db:
            task = await db.get(ResearchTask, task_id)
            await execute_task(db, task, holder="drill-worker-b")
            await db.commit()
    finally:
        await engine.dispose()
    return await _db_facts(async_url, task_id)


async def stale_write_probe(async_url: str, task_id: str) -> dict:
    """用已被接管的第一份 attempt 模拟迟到写入，记录是否被拒绝。"""
    from src.backend.db.session import (
        create_async_engine_from_url,
        create_async_sessionmaker_from_engine,
    )
    from src.backend.research.models import ResearchTask, TaskAttempt
    from src.backend.research import task_repository
    from src.backend.research.contracts import TaskStatus
    from sqlalchemy import select

    result: dict[str, Any] = {}
    engine = create_async_engine_from_url(async_url)
    session_factory = create_async_sessionmaker_from_engine(engine)
    try:
        async with session_factory() as db:
            task = await db.get(ResearchTask, task_id)
            attempt1 = (
                await db.execute(
                    select(TaskAttempt).where(
                        TaskAttempt.task_id == task_id, TaskAttempt.attempt_no == 1
                    )
                )
            ).scalar_one()
            before = await _db_facts(async_url, task_id)
            result["before_terminal_event_count"] = before["terminal_event_count"]
            try:
                # 用**合法载荷**的 progress 事件探测：若被接受，说明 fencing token
                # 只落库、未在校验路径生效（不能拿非法载荷的拒绝当证据）。
                await task_repository.append_event(
                    db,
                    task,
                    "task.progress",
                    payload={"holder": "drill-worker-a", "late": True},
                    fencing_token=1,
                )
                await db.commit()
                result["late_event_accepted"] = True
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                result["late_event_accepted"] = False
                result["late_event_error"] = f"{type(exc).__name__}: {exc}"
            async with session_factory() as db2:
                task2 = await db2.get(ResearchTask, task_id)
                try:
                    await task_repository.transition(
                        db2,
                        task2,
                        TaskStatus.FAILED,
                        error={"code": "LATE_WRITE"},
                        fencing_token=1,
                    )
                    await task_repository.close_attempt(db2, attempt1, "failed")
                    await db2.commit()
                    result["late_transition_accepted"] = True
                except Exception as exc:  # noqa: BLE001
                    await db2.rollback()
                    result["late_transition_accepted"] = False
                    result["late_transition_error"] = f"{type(exc).__name__}: {exc}"
            after = await _db_facts(async_url, task_id)
            result["after_terminal_event_count"] = after["terminal_event_count"]
            result["task_status_after"] = after["task_status"]
    finally:
        await engine.dispose()
    return result


def spawn_child(args: list[str], env: dict) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(pathlib.Path(__file__).resolve()), *args],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def kill_process(pid: int) -> bool:
    """SIGKILL 等价物（Windows 用 taskkill /F，POSIX 用 SIGKILL）。"""
    if os.name == "nt":
        res = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True)
        return res.returncode == 0
    try:
        os.kill(pid, 9)
        return True
    except OSError:
        return False


async def drill(async_url: str, *, port: int, lease_seconds: int, keep: bool) -> dict:
    report: dict[str, Any] = {"port": port, "async_url": async_url.replace(PG_USER, "***")}
    env = os.environ.copy()
    env.update(
        {
            "DRILL_ASYNC_URL": async_url,
            "RESEARCH_ENABLED": "true",
            "RESEARCH_MODEL_STUB": "true",
            "ENVIRONMENT": "test",
            "RATE_LIMIT_ENABLED": "false",
            "DISABLE_VECTOR_PREWARM": "true",
        }
    )

    print("[drill] 准备数据（用户/权益/项目/文档/任务）…")
    info = await prepare_task(async_url, lease_seconds=lease_seconds)
    report["fixtures"] = {k: v for k, v in info.items() if k in ("project_id", "document_id", "version_id", "task_id")}
    task_id = info["task_id"]

    # ── 崩溃前：子进程领取租约并被杀死 ──────────────────────────
    marker = REPO_ROOT / "tmp" / "recovery-drill-marker.json"
    marker.unlink(missing_ok=True)
    print("[drill] 子进程 A 领取租约（holder=drill-worker-a）…")
    child = spawn_child(["--child-claim", task_id, "--lease-seconds", str(lease_seconds), "--marker", str(marker)], env)
    claimed = wait_marker(marker, timeout=90)
    if not claimed:
        child.kill()
        raise SystemExit("子进程未在 90s 内完成领取（见 tmp/recovery-drill-marker.json）")
    report["claim"] = claimed
    before = await _db_facts(async_url, task_id)
    report["after_claim"] = before
    killed = kill_process(int(claimed["pid"]))
    try:
        child.wait(timeout=30)
    except subprocess.TimeoutExpired:  # pragma: no cover
        child.kill()
    report["kill"] = {"pid": claimed["pid"], "killed": killed, "returncode": child.returncode}

    # ── 崩溃后：租约到期 → 第二执行器接管 ──────────────────────
    print("[drill] 等待租约过期（真实数据库时钟）…")
    expired = False
    deadline = time.time() + 120
    while time.time() < deadline:
        expired = await _lease_expired(async_url, task_id)
        if expired:
            break
        time.sleep(1.5)
    report["lease_expired"] = expired
    if not expired:
        raise SystemExit("租约未在 120s 内过期，无法演练接管")

    print("[drill] 执行器 B 接管并完成任务（真实 execute_task）…")
    after_reclaim = await reclaim_and_finish(async_url, task_id)
    report["after_reclaim"] = after_reclaim

    # ── 迟到写入探针 ─────────────────────────────────────────────
    print("[drill] 迟到写入探针（旧 attempt 1）…")
    report["stale_write"] = await stale_write_probe(async_url, task_id)

    # ── 重复投递：两个进程同时执行同一任务 ──────────────────────
    print("[drill] 重复投递：两个进程同时 execute_task 新任务…")
    task2 = await prepare_second_task(async_url, info)
    report["duplicate_task_id"] = task2
    procs = [
        spawn_child(["--child-execute", task2, "--holder", f"drill-dup-{i}"], env)
        for i in (1, 2)
    ]
    for p in procs:
        try:
            out, err = p.communicate(timeout=180)
        except subprocess.TimeoutExpired:  # pragma: no cover
            p.kill()
            out, err = p.communicate()
        print(f"[drill]   子进程 {p.pid} exit={p.returncode} {((err or '').strip().splitlines() or [''])[-1][:160]}")
    dup_facts = await _db_facts(async_url, task2)
    report["duplicate_delivery"] = dup_facts

    # ── 数据库崩溃重启 ───────────────────────────────────────────
    print("[drill] pg_ctl stop -m immediate + start（模拟数据库崩溃后重启）…")
    stop_pg("immediate")
    if pg_ready(port):
        raise SystemExit("模拟崩溃失败：停止后端口仍在监听")
    print("[drill] 集群已停止（immediate），正在重启…")
    start_pg(port)
    deadline = time.time() + 120
    while time.time() < deadline and not pg_ready(port):
        time.sleep(1.0)
    if not pg_ready(port):
        raise SystemExit("PG 重启后未就绪")
    after_restart = await _db_facts(async_url, task_id)
    report["after_db_restart"] = after_restart
    report["db_restart_consistent"] = (
        after_restart["task_status"] == after_reclaim["task_status"]
        and after_restart["event_sequences"] == after_reclaim["event_sequences"]
        and after_restart["artifact_count"] == after_reclaim["artifact_count"]
    )

    # ── 断言汇总 ─────────────────────────────────────────────────
    checks = {
        "claim_wrote_started_event": "task.started" in before.get("event_types", []),
        "reclaim_incremented_attempt": len(after_reclaim["attempts"]) >= 2
        and after_reclaim["attempts"][1]["fencing_token"] > after_reclaim["attempts"][0]["fencing_token"],
        "single_terminal_event": after_reclaim["terminal_event_count"] == 1,
        "single_artifact": after_reclaim["artifact_count"] == 1,
        "events_monotonic": after_reclaim["events_monotonic"],
        "stale_write_rejected": not report["stale_write"].get("late_event_accepted")
        and not report["stale_write"].get("late_transition_accepted"),
        "duplicate_delivery_exactly_once": dup_facts["terminal_event_count"] == 1
        and dup_facts["artifact_count"] == 1
        and len(dup_facts["attempts"]) == 1,
        "db_restart_keeps_state": report["db_restart_consistent"],
    }
    report["checks"] = checks
    if not checks["stale_write_rejected"]:
        report["known_defects"] = [
            {
                "id": "R2-A13",
                "title": "fencing token 未在校验路径生效：租约过期后被接管的旧执行器仍能写事件/改状态",
                "severity": "medium",
                "evidence": report["stale_write"],
                "suggested_fix": (
                    "append_event/transition 增加 fencing_token 参数并与该任务当前最大 attempt "
                    "的 token 比对，不等则抛 conflict('STALE_ATTEMPT')；task_runner 全路径传入。"
                ),
            }
        ]
    report["passed"] = all(checks.values())
    DRILL_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[drill] 结果写入 {DRILL_JSON}")
    if not keep:
        pass
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="生产同构恢复演练（PostgreSQL）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--lease-seconds", type=int, default=8)
    parser.add_argument("--keep", action="store_true", help="保留 PG 集群与数据（默认同样保留，便于复跑）")
    parser.add_argument("--skip-migrations", action="store_true")
    parser.add_argument("--child-claim", metavar="TASK_ID")
    parser.add_argument("--child-execute", metavar="TASK_ID")
    parser.add_argument("--holder", default="drill-child")
    parser.add_argument("--marker", default="")
    args = parser.parse_args()

    if args.child_claim:
        asyncio.run(_child_claim(args.child_claim, args.lease_seconds, args.marker))
        return 0
    if args.child_execute:
        asyncio.run(_child_execute(args.child_execute, args.holder))
        return 0

    async_url, actual_port = ensure_pg(args.port)
    sync_url = async_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    print(f"[drill] PG 就绪：{async_url.replace(PG_USER, '***')}")
    if not args.skip_migrations:
        run_migrations(sync_url)
    facts = asyncio.run(pg_schema_facts(async_url))
    print(f"[drill] 迁移后表：{facts['research_table_count']} 张 research_*，唯一约束 {len(facts['unique_constraints'])} 个")

    report = asyncio.run(drill(async_url, port=actual_port, lease_seconds=args.lease_seconds, keep=args.keep))
    report["pg"] = facts
    DRILL_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n[drill] 断言：")
    for key, value in report["checks"].items():
        print(f"  {'PASS' if value else 'FAIL'}  {key}")
    print(f"[drill] 总结论：{'PASS' if report['passed'] else 'FAIL'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
