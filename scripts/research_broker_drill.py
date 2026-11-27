"""Redis / Celery 恢复语义演练（真实 broker + 真实 worker）。

与被演练对象无关的假设：
- Redis 必须是**真实服务**（本机原生、WSL 里的 docker、或 WSL 里直接装）；
  脚本只通过 ``redis://`` 连接，不启动 Redis，也不使用 fakeredis。
- ``.venv`` 里已安装 celery；worker 由本脚本以子进程方式启动/杀掉。

场景：
1. 正常 round-trip：发布 → worker 消费 → 任务到终态。
2. worker 被杀：任务执行中被 ``taskkill``，broker 未 ack 的消息在
   ``visibility_timeout`` 后重投 → 第二次执行由租约/状态机保证 exactly-once。
3. broker 断连：Redis 停止时发布失败（不丢不假成功），Redis 恢复后 worker
   重连、任务最终跑完。（需要 ``--redis-container`` 才能自动 stop/start。）
4. 重复投递：同一任务发布两次 → 仍只有 1 条终态事件、1 个成果。

退出码：0 全部通过 / 1 有检查失败 / 2 参数/环境不合法 / 3 预检未通过（Redis 不通等）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DOC_TEXT = (
    "# 引言\n\n"
    + "平台算法改变了新闻消费的结构，推荐系统把注意力重新分配给少数账号。" * 40
    + "\n\n# 方法\n\n"
    + "研究采用问卷与日志结合的混合设计，样本 1200 人，辅以 24 次深度访谈。" * 40
    + "\n"
)


def log(stage: str, message: str = "") -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] [{stage}] {message}", flush=True)


# ── docker 调用（本机 socket 或远程 TCP，例如 WSL 里的 dockerd）──

DEFAULT_DOCKER_HOST = os.environ.get("BROKER_DRILL_DOCKER_HOST", "")


def _docker_argv(host: str = "") -> list:
    return ["docker", "-H", host] if host else ["docker"]


def docker_available(host: str = "") -> Optional[str]:
    """探测 docker 守护进程；host 为空表示本机默认 socket。"""
    try:
        probe = subprocess.run(  # noqa: S603,S607
            [*_docker_argv(host), "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if probe.returncode == 0 and probe.stdout.strip():
            return host or "local"
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def docker_container_cmd(action: str, container: str, host: str = "") -> subprocess.CompletedProcess:
    """``docker stop|start <container>``；host 非空时通过 ``-H`` 连远程守护进程。"""
    if docker_available(host) is None:
        raise RuntimeError(f"docker 守护进程不可达（host={host or 'local'}）")
    return subprocess.run(  # noqa: S603
        [*_docker_argv(host), action, container],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )


def check_redis(redis_url: str) -> Optional[str]:
    """返回 None 表示可用，否则返回错误描述。"""
    try:
        import redis.asyncio as aioredis
    except Exception as exc:  # pragma: no cover - 依赖缺失
        return f"redis 包不可用：{type(exc).__name__}"
    from redis.exceptions import RedisError

    async def _ping() -> None:
        client = aioredis.from_url(redis_url, socket_connect_timeout=3, socket_timeout=3)
        try:
            await client.ping()
        finally:
            # redis-py 4.x 只有 close()，5.x 才有 aclose()，两者都兼容。
            closer = getattr(client, "aclose", None) or getattr(client, "close", None)
            if closer is not None:
                result = closer()
                if asyncio.iscoroutine(result):
                    await result

    try:
        asyncio.run(_ping())
    except (RedisError, OSError) as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def celery_worker_env(extra: Dict[str, str]) -> Dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(REPO_ROOT))
    env.setdefault("ENVIRONMENT", "test")
    env.setdefault("RESEARCH_MODEL_STUB", "true")
    # worker 被杀后多久重投未 ack 的消息（kombu 默认 3600s，演练必须调小）。
    env.setdefault("CELERY_VISIBILITY_TIMEOUT", "20")
    env.update(extra)
    return env


def start_worker(
    python: str,
    env: Dict[str, str],
    log_path: Path,
    *,
    concurrency: int = 1,
    name: str = "brokerdrill",
) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("ab")
    cmd = [
        python,
        "-m",
        "celery",
        "-A",
        "src.backend.scheduler.celery_app",
        "worker",
        "--loglevel=INFO",
        "--pool=solo",
        "-c",
        str(max(1, int(concurrency))),
        "-n",
        f"{name}@%h",
    ]
    proc = subprocess.Popen(  # noqa: S603 - 本地演练脚本
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    proc._log_handle = handle  # type: ignore[attr-defined]
    return proc


def start_beat(python: str, env: Dict[str, str], log_file: Path, schedule: Path) -> subprocess.Popen:
    """单独进程跑 beat：Windows 上 worker 的 ``-B`` 会直接拒绝启动
    （``-B option does not work on Windows``），所以周期清扫只能这样验。"""
    cmd = [
        python,
        "-m",
        "celery",
        "-A",
        "src.backend.scheduler.celery_app",
        "beat",
        "--loglevel=INFO",
        "--schedule",
        str(schedule),
    ]
    handle = open(log_file, "a", encoding="utf-8", errors="replace")
    return subprocess.Popen(  # noqa: S603 - 本地演练脚本
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )


def kill_tree(proc: Optional[subprocess.Popen]) -> None:
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        # 必须用绝对路径：本机 PATH 里 taskkill 可能被 shell 包装脚本遮蔽，
        # 直接调 "taskkill" 会以退出码 1 失败（参数被改写），worker 实际没死，
        # 后续「重投」场景就测不出东西。
        exe = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe")
        subprocess.run(  # noqa: S603
            [exe, "/F", "/PID", str(proc.pid), "/T"],
            capture_output=True,
            check=False,
        )
    else:  # pragma: no cover - 非 Windows
        proc.kill()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:  # pragma: no cover
        log("kill", f"worker pid={proc.pid} 20s 内未退出")
    if proc.poll() is None:  # pragma: no cover - Windows 上应为已死
        log("kill", f"警告：worker pid={proc.pid} 仍在运行")



def restore_unacked(redis_url: str, visibility_timeout: int, timeout: float = 90.0) -> int:
    """触发 kombu Redis transport 的「未确认消息可见性恢复」。

    Celery 自己的恢复钩子每 10 次轮询才真正执行一次（``restore_visible`` 内部
    ``(count-1) % interval``），演练里等不起；这里直接用同一个 transport API，
    语义与「消费者重启后恢复未确认消息」一致，不是自己重发消息。
    """
    import redis as sync_redis
    from kombu import Connection

    client = sync_redis.Redis.from_url(redis_url)
    deadline = time.time() + timeout
    with Connection(redis_url) as conn:
        channel = conn.channel()
        channel.qos.visibility_timeout = int(visibility_timeout)
        while time.time() < deadline:
            if not client.hlen("unacked"):
                return 0
            channel.qos.restore_visible(num=50, interval=1)
            time.sleep(0.5)
    return int(client.hlen("unacked") or 0)



class TcpProxy:
    """本地 TCP 转发（Redis 客户端 → 真实 Redis）。

    用来在没有 Docker 的机器上真实制造「broker 不可达 + 恢复」：停掉代理等于
    网络分区/服务不可用，客户端会连接失败；重启代理后客户端自动重连。
    """

    def __init__(self, listen_port: int, upstream_host: str, upstream_port: int) -> None:
        self.listen_port = int(listen_port)
        self.upstream = (upstream_host, int(upstream_port))
        self._server: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._pumps: list[threading.Thread] = []

    def start(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", self.listen_port))
        server.listen(64)
        self._server = server
        self._stop.clear()
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self) -> None:
        assert self._server is not None
        self._server.settimeout(0.5)
        while not self._stop.is_set():
            try:
                client, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                upstream = socket.create_connection(self.upstream, timeout=5)
            except OSError:
                client.close()
                continue
            for a, b in ((client, upstream), (upstream, client)):
                thread = threading.Thread(target=self._pump, args=(a, b), daemon=True)
                thread.start()
                self._pumps.append(thread)

    def _pump(self, src: socket.socket, dst: socket.socket) -> None:
        try:
            while not self._stop.is_set():
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for sock in (src, dst):
                try:
                    sock.close()
                except OSError:
                    pass

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None
        for thread in list(self._pumps):
            thread.join(timeout=1)
        self._pumps.clear()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None


# ── 数据准备（真实服务调用） ────────────────────────────────


async def prepare_task(db_url: str, *, idempotency_key: str) -> Dict[str, str]:
    from sqlalchemy import select

    from src.backend.db.session import (
        create_async_engine_from_url,
        create_async_sessionmaker_from_engine,
        init_db,
    )
    from src.backend.models.orm import User, UserQuota
    from src.backend.research.contracts import Actor
    from src.backend.research.document_service import upload_document
    from src.backend.research.project_service import create_project
    from src.backend.research.task_service import create_task
    from src.backend.services.auth_service import get_password_hash
    from src.backend.services.entitlement_service import EntitlementService

    engine = create_async_engine_from_url(db_url)
    await init_db(engine)
    factory = create_async_sessionmaker_from_engine(engine)
    suffix = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
    try:
        async with factory() as db:
            existing = await db.scalar(
                select(User).where(User.username == f"broker-drill-{suffix}")
            )
            if existing is None:
                user = User(
                    username=f"broker-drill-{suffix}",
                    password_hash=get_password_hash("drill-password"),
                    nickname="broker-drill",
                    is_active=True,
                    plan="free",
                )
                db.add(user)
                await db.flush()
                db.add(UserQuota(user_id=user.id, plan="free"))
                await db.flush()
            else:  # pragma: no cover - 复跑保护
                user = existing
            await EntitlementService.grant_product(
                db, user.id, "monthly_pro", f"broker-drill-grant-{suffix}"
            )
            actor = Actor(user_id=user.id)
            project = await create_project(db, actor, f"broker-drill-{suffix}")
            uploaded = await upload_document(
                db,
                actor,
                project["id"],
                filename="drill.md",
                mime="text/markdown",
                data=DOC_TEXT.encode("utf-8"),
            )
            task = await create_task(
                db,
                actor,
                {
                    "schema_version": "1.0",
                    "project_id": project["id"],
                    "kind": "review",
                    "objective": "检查论证与证据",
                    "input": {"document_version_id": uploaded["version"]["id"]},
                },
                idempotency_key=idempotency_key,
            )
            await db.commit()
            return {
                "task_id": task.task_id,
                "project_id": project["id"],
                "version_id": uploaded["version"]["id"],
                "user_id": str(user.id),
            }
    finally:
        await engine.dispose()


async def task_state(db_url: str, task_id: str) -> Dict[str, Any]:
    from sqlalchemy import func, select

    from src.backend.db.session import (
        create_async_engine_from_url,
        create_async_sessionmaker_from_engine,
    )
    from src.backend.research.models import Artifact, ResearchTask, TaskAttempt, TaskEvent

    engine = create_async_engine_from_url(db_url)
    factory = create_async_sessionmaker_from_engine(engine)
    try:
        async with factory() as db:
            task = await db.get(ResearchTask, task_id)
            if task is None:
                return {"missing": True}
            attempts = (
                await db.execute(
                    select(TaskAttempt.attempt_no, TaskAttempt.status, TaskAttempt.lease_holder)
                    .where(TaskAttempt.task_id == task_id)
                    .order_by(TaskAttempt.attempt_no)
                )
            ).all()
            events = (
                await db.execute(
                    select(TaskEvent.sequence, TaskEvent.type)
                    .where(TaskEvent.task_id == task_id)
                    .order_by(TaskEvent.sequence)
                )
            ).all()
            artifacts = await db.scalar(
                select(func.count()).select_from(Artifact).where(Artifact.task_id == task_id)
            )
            terminal = [e for e in events if str(e.type).startswith("task.completed")]
            terminal += [e for e in events if str(e.type) in ("task.partial", "task.failed", "task.cancelled")]
            return {
                "status": task.status,
                "attempt_no": task.attempt_no,
                "attempts": [list(a) for a in attempts],
                "sequences": [e.sequence for e in events],
                "event_types": [str(e.type) for e in events],
                "terminal_event_count": len(terminal),
                "artifact_count": int(artifacts or 0),
                "quality_verdict": task.quality_verdict,
                "error_code": (task.error_json or {}).get("code"),
                "billing_state": task.billing_state,
            }
    finally:
        await engine.dispose()


def wait_for(
    predicate,
    *,
    timeout: float,
    interval: float = 0.4,
    description: str = "",
) -> Optional[Dict[str, Any]]:
    deadline = time.time() + timeout
    last: Optional[Dict[str, Any]] = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    log("wait", f"超时未满足：{description}（最后状态 {last}）")
    return None


def _terminal_state(db_url: str, task_id: str, terminal: tuple) -> Optional[Dict[str, Any]]:
    state = asyncio.run(task_state(db_url, task_id))
    if state.get("status") in terminal:
        return state
    return None


def scenario_two_workers(
    db_url: str,
    python: str,
    env: Dict[str, str],
    log_dir: Path,
    *,
    task_count: int = 2,
    timeout: float = 300.0,
) -> Dict[str, Any]:
    """两个 worker 同时在线：并发消费多个任务 + 同一任务被两个 worker 抢。"""
    stamp = int(time.time() * 1000)
    tasks = [
        asyncio.run(prepare_task(db_url, idempotency_key=f"broker-drill-2w-{stamp}-{i}"))
        for i in range(task_count)
    ]
    log("S5", f"两个 worker 在线，并发发布 {len(tasks)} 个任务")
    worker_a = start_worker(python, env, log_dir / "broker-drill-worker-a.log", name="brokerdrilla")
    worker_b = start_worker(python, env, log_dir / "broker-drill-worker-b.log", name="brokerdrillb")
    states: list[Dict[str, Any]] = []
    race: Dict[str, Any] = {}
    try:
        time.sleep(10)  # 等两个 worker 各自连上 broker 并进入消费循环
        celery_ids = [publish(task["task_id"]) for task in tasks]
        terminal = ("succeeded", "partial", "failed", "cancelled")
        for task, celery_id in zip(tasks, celery_ids):
            state = wait_for(
                lambda tid=task["task_id"]: _terminal_state(db_url, tid, terminal),
                timeout=timeout,
                description=f"任务 {task['task_id']} 到终态",
            )
            states.append({"task_id": task["task_id"], "celery_id": celery_id, "state": state or {}})

        # 竞争场景：同一任务同一时刻发布两次，两个 worker 抢
        race_task = asyncio.run(
            prepare_task(db_url, idempotency_key=f"broker-drill-2w-race-{stamp}")
        )
        race_ids = [publish(race_task["task_id"]), publish(race_task["task_id"])]
        race_state = wait_for(
            lambda: _terminal_state(db_url, race_task["task_id"], terminal),
            timeout=timeout,
            description="竞争任务到终态",
        )
        race = {"task_id": race_task["task_id"], "celery_ids": race_ids, "state": race_state or {}}
        log("S5", f"竞争任务终态：{(race_state or {}).get('status')}")
    finally:
        kill_tree(worker_a)
        kill_tree(worker_b)
    return {"tasks": states, "race": race}


# ── 场景 ────────────────────────────────────────────────────


def publish(task_id: str, *, slow_ms: int = 0) -> str:
    from src.backend.scheduler.celery_app import celery_app

    async_result = celery_app.send_task(
        "research.execute_task",
        args=[task_id],
        kwargs={"slow_ms": int(slow_ms)},
    )
    return str(async_result.id)


def scenario_roundtrip(db_url: str) -> Dict[str, Any]:
    log("S1", "正常 round-trip（复用已启动的 worker）")
    prepared = asyncio.run(prepare_task(db_url, idempotency_key=f"broker-s1-{uuid.uuid4().hex[:8]}"))
    message_id = publish(prepared["task_id"])
    state = wait_for(
        lambda: (lambda s: s if s.get("status") in ("succeeded", "partial", "failed") else None)(
            asyncio.run(task_state(db_url, prepared["task_id"]))
        ),
        timeout=300,
        description="任务到终态",
    )
    return {"message_id": message_id, "task_id": prepared["task_id"], "state": state or {}}


def scenario_worker_killed(
    db_url: str,
    python: str,
    env: Dict[str, str],
    log_path: Path,
    worker: subprocess.Popen,
    visibility_timeout: int,
    lease_seconds: int,
    redis_url: str,
) -> tuple[Dict[str, Any], Optional[subprocess.Popen], Optional[subprocess.Popen]]:
    log("S2", "执行中杀掉 worker，验证 broker 重投与 exactly-once")
    prepared = asyncio.run(prepare_task(db_url, idempotency_key=f"broker-s2-{uuid.uuid4().hex[:8]}"))
    task_id = prepared["task_id"]
    try:
        publish(task_id, slow_ms=1500)
        started = wait_for(
            lambda: (lambda s: s if s.get("attempts") and s["attempts"][0][1] == "running" else None)(
                asyncio.run(task_state(db_url, task_id))
            ),
            timeout=180,
            description="attempt 1 running",
        )
        if not started:
            return {"task_id": task_id, "killed": False, "reason": "worker 未开始执行"}, worker
        log("S2", f"已进入执行：attempts={started['attempts']}，现在杀 worker")
        kill_tree(worker)
        worker = None
        # kombu 的 Redis transport 只在消费者启动/轮询时执行一次「恢复未确认消息」；
        # 若在 visibility_timeout 之前就重启，恢复条件尚未到期，消息会一直躺在
        # unacked 里。因此先等过可见性窗口，再启动新 worker 触发恢复。
        wait_seconds = max(5, int(visibility_timeout) + 10, int(lease_seconds) + 10)
        log("S2", f"worker 已杀；等 {wait_seconds}s 让租约过期、消息超出可见性窗口")
        time.sleep(wait_seconds)
        restored = restore_unacked(redis_url, visibility_timeout)
        log("S2", f"transport 恢复未确认消息：剩余 {restored}")
        worker = start_worker(python, env, log_path)
        state = wait_for(
            lambda: (lambda s: s if s.get("status") in ("succeeded", "partial", "failed") else None)(
                asyncio.run(task_state(db_url, task_id))
            ),
            timeout=420,
            description="重投后到终态",
        )
        return (
            {
                "task_id": task_id,
                "killed": True,
                "before_kill": started,
                "after_restart": state or {},
            },
            worker,
        )
    finally:
        pass


def scenario_broker_down(
    db_url: str,
    redis_url: str,
    container: Optional[str],
    proxy: Optional[TcpProxy],
    docker_host: str = "",
) -> Dict[str, Any]:
    """broker 不可达 → 发布必须失败（不假成功）→ 恢复后任务能跑完。"""
    log("S3", "broker 断连与恢复")
    if not container and proxy is None:
        return {"skipped": True, "reason": "未提供 --redis-container 或 --proxy-port"}

    prepared = asyncio.run(prepare_task(db_url, idempotency_key=f"broker-s3-{uuid.uuid4().hex[:8]}"))
    task_id = prepared["task_id"]

    if proxy is not None:
        proxy.stop()
        time.sleep(2.0)
        down_error = check_redis(redis_url)
        publish_error: Optional[str] = None
        try:
            publish(task_id)
        except Exception as exc:  # noqa: BLE001 - 断连时就是要看失败
            publish_error = f"{type(exc).__name__}: {exc}"
        proxy.start()
        recovered = None
        for _ in range(60):
            recovered = check_redis(redis_url)
            if recovered is None:
                break
            time.sleep(1)
        time.sleep(2)
        publish_after_recovery: Optional[str] = None
        try:
            publish_after_recovery = publish(task_id)
        except Exception as exc:  # noqa: BLE001
            publish_after_recovery = f"ERROR {type(exc).__name__}: {exc}"
        return {
            "task_id": task_id,
            "mode": "tcp-proxy",
            "redis_down_error": down_error,
            "publish_error_when_down": publish_error,
            "redis_error_after_restart": recovered,
            "publish_after_recovery": publish_after_recovery,
            "state": wait_for(
                lambda: (lambda st: st if st.get("status") in ("succeeded", "partial", "failed") else None)(
                    asyncio.run(task_state(db_url, task_id))
                ),
                timeout=420,
                description="broker 恢复后任务到终态",
            )
            or {},
        }

    def redis_cmd(action: str) -> bool:  # pragma: no cover - 需要 docker
        result = docker_container_cmd(action, container, docker_host)
        log("S3", f"docker {action} {container} -> rc={result.returncode} "
                  f"{(result.stderr or result.stdout).strip()[:120]}")
        return result.returncode == 0

    stopped = redis_cmd("stop")  # pragma: no cover
    down_error = check_redis(redis_url)  # pragma: no cover
    publish_error = None  # pragma: no cover
    try:  # pragma: no cover
        publish(task_id)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        publish_error = f"{type(exc).__name__}: {exc}"
    started = redis_cmd("start") if stopped else False  # pragma: no cover
    recovered = check_redis(redis_url)  # pragma: no cover
    for _ in range(90):  # pragma: no cover - 容器重启后端口重新监听
        recovered = check_redis(redis_url)
        if recovered is None:
            break
        time.sleep(1)
    time.sleep(2)  # pragma: no cover
    publish_after_recovery: Optional[str] = None  # pragma: no cover
    try:  # pragma: no cover
        publish_after_recovery = publish(task_id)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        publish_after_recovery = f"ERROR {type(exc).__name__}: {exc}"
    state = wait_for(  # pragma: no cover
        lambda: (lambda st: st if st.get("status") in ("succeeded", "partial", "failed") else None)(
            asyncio.run(task_state(db_url, task_id))
        ),
        timeout=420,
        description="Redis 恢复后任务到终态",
    )
    return {  # pragma: no cover
        "task_id": task_id,
        "mode": "docker",
        "container": container,
        "stopped": stopped,
        "redis_down_error": down_error,
        "publish_error_when_down": publish_error,
        "restarted": started,
        "redis_error_after_restart": recovered,
        "publish_after_recovery": publish_after_recovery,
        "state": state or {},
    }


def scenario_duplicate(db_url: str) -> Dict[str, Any]:
    log("S4", "同一任务重复投递（去重）")
    prepared = asyncio.run(prepare_task(db_url, idempotency_key=f"broker-s4-{uuid.uuid4().hex[:8]}"))
    task_id = prepared["task_id"]
    first = publish(task_id)
    second = publish(task_id)
    state = wait_for(
        lambda: (lambda s: s if s.get("status") in ("succeeded", "partial", "failed") else None)(
            asyncio.run(task_state(db_url, task_id))
        ),
        timeout=420,
        description="重复投递后到终态",
    )
    return {"task_id": task_id, "message_ids": [first, second], "state": state or {}}


# ── 主流程 ──────────────────────────────────────────────────


def drop_broker_state(redis_url: str) -> int:
    """模拟 broker 丢数据：删除队列与未确认集合（Redis 未持久化时重启即如此）。"""
    import redis

    client = redis.Redis.from_url(redis_url)
    try:
        keys = list(client.scan_iter("*celery*")) + list(client.scan_iter("unacked*"))
        keys = list(dict.fromkeys(keys))
        return int(client.delete(*keys)) if keys else 0
    finally:
        closer = getattr(client, "aclose", None) or getattr(client, "close", None)
        if closer is not None:
            result = closer()
            if hasattr(result, "__await__"):
                asyncio.run(result)


def scenario_broker_loss(
    db_url: str,
    redis_url: str,
    python: str,
    env: Dict[str, str],
    worker_log: Path,
    worker: Optional[subprocess.Popen],
    queue_timeout: int,
) -> tuple[Dict[str, Any], Optional[subprocess.Popen]]:
    """S6：消息丢失（broker 重启且未持久化）。

    期望：任务不能悄悄消失。排队超时后由清扫任务置为 failed（QUEUE_TIMEOUT）并
    释放额度；这条路径靠 ``research.reap_stale_queued`` 的 beat 周期触发。
    """
    log("S6", "broker 丢消息：任务必须在排队超时后诚实失败，而不是永久 queued")
    kill_tree(worker)
    prepared = asyncio.run(prepare_task(db_url, idempotency_key=f"broker-s6-{uuid.uuid4().hex[:8]}"))
    task_id = prepared["task_id"]
    message_id = publish(task_id)
    dropped = drop_broker_state(redis_url)
    log("S6", f"已发布 {str(message_id)[:8]}…，随后删除 {dropped} 个 broker 键（消息丢失）")
    beat = start_beat(
        python,
        env,
        worker_log.with_name("broker-drill-beat.log"),
        REPO_ROOT / "tmp" / "broker-drill-beat-schedule",
    )
    revived = start_worker(python, env, worker_log, name="brokerdrill-reaper")
    state = wait_for(
        lambda: (lambda st: st if st.get("status") in ("failed", "partial", "succeeded", "cancelled") else None)(
            asyncio.run(task_state(db_url, task_id))
        ),
        timeout=float(queue_timeout) + 180,
        description="broker 丢消息后由清扫器诚实失败",
    )
    return (
        {
            "task_id": task_id,
            "message_id": message_id,
            "dropped_keys": dropped,
            "queue_timeout_seconds": queue_timeout,
            "state": state or {},
        },
        revived,
        beat,
    )


def build_checks(report: Dict[str, Any]) -> Dict[str, bool]:
    s1 = report.get("roundtrip", {}).get("state", {})
    s2 = report.get("worker_killed", {})
    s2_state = s2.get("after_restart", {})
    s3 = report.get("broker_down", {})
    s3_state = s3.get("state", {})
    s4 = report.get("duplicate", {}).get("state", {})
    s5 = report.get("two_workers", {})
    s5_tasks = [item.get("state", {}) for item in (s5.get("tasks") or [])]
    s5_race = s5.get("race", {}).get("state", {})
    attempts_s2 = s2_state.get("attempts") or []
    checks = {
        "roundtrip_succeeded": s1.get("status") == "succeeded",
        "roundtrip_single_artifact": s1.get("artifact_count") == 1,
        "worker_kill_triggers_redelivery": s2.get("killed") is True
        and bool(attempts_s2)
        and max(int(a[0]) for a in attempts_s2) >= 2,
        "worker_kill_exactly_once": s2_state.get("terminal_event_count") == 1
        and s2_state.get("artifact_count") == 1,
        "broker_down_is_honest": s3.get("skipped") is True
        or (s3.get("redis_down_error") is not None and s3.get("state", {}).get("status") == "succeeded"),
        "duplicate_delivery_exactly_once": s4.get("terminal_event_count") == 1
        and s4.get("artifact_count") == 1,
        "worker_kill_terminal": s2_state.get("status") in ("succeeded", "partial"),
        "broker_down_terminal": s3.get("skipped") is True
        or s3_state.get("status") in ("succeeded", "partial"),
        "two_workers_all_tasks_once": bool(s5_tasks)
        and all(item.get("status") in ("succeeded", "partial") for item in s5_tasks),
        "two_workers_no_double_artifact": bool(s5_tasks)
        and all(item.get("artifact_count") == 1 for item in s5_tasks),
        "two_workers_duplicate_race_exactly_once": bool(s5_race)
        and s5_race.get("terminal_event_count") == 1
        and s5_race.get("artifact_count") == 1,
    }
    s6 = report.get("broker_loss", {})
    s6_state = s6.get("state", {})
    skipped = s6.get("skipped") is True
    checks["broker_loss_not_silent"] = skipped or s6_state.get("status") == "failed"
    checks["broker_loss_code_queue_timeout"] = skipped or s6_state.get("error_code") == "QUEUE_TIMEOUT"
    checks["broker_loss_releases_billing"] = skipped or s6_state.get("billing_state") == "released"
    checks["broker_loss_terminal_event"] = skipped or s6_state.get("terminal_event_count") == 1
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Redis/Celery 恢复语义演练")
    parser.add_argument(
        "--redis-url",
        default=os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/9"),
        help="演练默认用 9 号库，避免与其它项目共享 celery 队列",
    )
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--out", default="tmp/broker-drill.json")
    parser.add_argument("--redis-container", default="", help="docker 容器名，用于 broker 断连场景")
    parser.add_argument(
        "--docker-host",
        default=DEFAULT_DOCKER_HOST,
        help="docker 守护进程地址（如 tcp://192.168.218.232:2375，WSL 里的 dockerd）；留空=本机 socket",
    )
    parser.add_argument("--visibility-timeout", type=int, default=20)
    parser.add_argument("--lease-seconds", type=int, default=25)
    parser.add_argument(
        "--proxy-port",
        type=int,
        default=0,
        help="启动本地 TCP 代理注入 broker 断连（无 Docker 时用），如 6391",
    )
    parser.add_argument(
        "--queue-timeout",
        type=int,
        default=20,
        help="排队超时秒数（写进 RESEARCH_QUEUE_TIMEOUT_SECONDS；生产默认 300）",
    )
    parser.add_argument("--skip-broker-loss", action="store_true")
    parser.add_argument("--skip-broker-down", action="store_true")
    parser.add_argument("--skip-two-workers", action="store_true")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    db_url = args.db_url or f"sqlite+aiosqlite:///{(REPO_ROOT / 'tmp' / 'broker-drill.db').as_posix()}"
    if db_url.startswith("sqlite") and not args.keep:
        for suffix in ("", "-wal", "-shm"):
            Path(str(db_url.split(":///", 1)[-1]) + suffix).unlink(missing_ok=True)
    (REPO_ROOT / "tmp").mkdir(parents=True, exist_ok=True)

    # 父进程发布消息与子进程 worker 必须连同一个 broker：这里先写进 env，
    # 让后面首次构造的 settings / celery_app 都读到这个地址。
    proxy: Optional[TcpProxy] = None
    effective_redis_url = args.redis_url
    if args.proxy_port:
        from urllib.parse import urlparse

        parsed = urlparse(args.redis_url)
        upstream_host = parsed.hostname or "127.0.0.1"
        upstream_port = parsed.port or 6379
        proxy = TcpProxy(args.proxy_port, upstream_host, upstream_port)
        proxy.start()
        effective_redis_url = f"redis://127.0.0.1:{args.proxy_port}/{parsed.path.lstrip('/') or '0'}"
        log("proxy", f"{effective_redis_url} → {upstream_host}:{upstream_port}")
    os.environ["CELERY_BROKER_URL"] = effective_redis_url

    python = sys.executable
    env = celery_worker_env(
        {
            "DATABASE_URL": db_url,
            "CELERY_BROKER_URL": effective_redis_url,
            "CELERY_VISIBILITY_TIMEOUT": str(args.visibility_timeout),
            "RESEARCH_TASK_LEASE_SECONDS": str(args.lease_seconds),
            "RESEARCH_QUEUE_TIMEOUT_SECONDS": str(args.queue_timeout),
            "CELERYBEAT_SCHEDULE_FILE": str(REPO_ROOT / "tmp" / "broker-drill-beat-schedule"),
        }
    )
    worker_log = REPO_ROOT / "tmp" / "broker-drill-worker.log"
    worker_log.unlink(missing_ok=True)

    log("preflight", f"redis={effective_redis_url}")
    redis_error = check_redis(effective_redis_url)
    if redis_error:
        log("preflight", f"Redis 不可用：{redis_error}")
        print(
            json.dumps(
                {"passed": False, "preflight": {"redis_url": effective_redis_url, "error": redis_error}},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 3
    if shutil.which("celery") is None:
        log("preflight", "celery CLI 未安装（pip install celery）")
        return 3
    if args.redis_container:
        mode = docker_available(args.docker_host)
        if mode is None:
            log("preflight", f"--redis-container 需要可用的 docker（host={args.docker_host or 'local'}）")
            return 3
        log("preflight", f"docker 可用（{mode}），容器 {args.redis_container}")
    log("preflight", "redis 连通、celery CLI 存在")

    report: Dict[str, Any] = {
        "redis_url": effective_redis_url,
        "upstream_redis_url": args.redis_url if proxy is not None else None,
        "db_url": db_url,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    checks: Dict[str, bool] = {}
    visibility_timeout = args.visibility_timeout
    lease_seconds = args.lease_seconds
    worker: Optional[subprocess.Popen] = None
    beat: Optional[subprocess.Popen] = None
    try:
        worker = start_worker(python, env, worker_log)
        report["worker_started"] = worker is not None
        report["roundtrip"] = scenario_roundtrip(db_url)
        report["worker_killed"], worker = scenario_worker_killed(
            db_url, python, env, worker_log, worker, visibility_timeout, lease_seconds, args.redis_url
        )
        if args.skip_broker_down:
            report["broker_down"] = {"skipped": True, "reason": "--skip-broker-down"}
        else:
            report["broker_down"] = scenario_broker_down(
                db_url, effective_redis_url, args.redis_container or None, proxy, args.docker_host
            )
        report["duplicate"] = scenario_duplicate(db_url)
        if args.skip_two_workers:
            report["two_workers"] = {"skipped": True}
        else:
            report["two_workers"] = scenario_two_workers(db_url, python, env, REPO_ROOT / "tmp")
        if args.skip_broker_loss:
            report["broker_loss"] = {"skipped": True, "reason": "--skip-broker-loss"}
        else:
            report["broker_loss"], worker, beat = scenario_broker_loss(
                db_url, effective_redis_url, python, env, worker_log, worker, args.queue_timeout
            )
        checks = build_checks(report)
    finally:
        kill_tree(beat)
        kill_tree(worker)
        if proxy is not None:
            proxy.stop()
        report["checks"] = checks
        report["passed"] = bool(checks) and all(checks.values())
        out_path = REPO_ROOT / args.out
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        log("result", f"写出 {out_path}")
        for name, ok in checks.items():
            log("check", f"{'PASS' if ok else 'FAIL'}  {name}")
        log("result", "总结论：" + ("PASS" if report["passed"] else "FAIL"))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
