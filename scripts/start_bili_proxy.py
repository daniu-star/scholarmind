"""启动/停止 ScholarMind 的 billion-context（ACP 上下文压缩代理）。

用法：
    python scripts/start_bili_proxy.py                # 前台启动（Ctrl+C 停止）
    python scripts/start_bili_proxy.py --detach       # 后台启动（写 tmp/bili-proxy.pid）
    python scripts/start_bili_proxy.py --status       # 查看状态
    python scripts/start_bili_proxy.py --stop         # 停止后台实例
    python scripts/start_bili_proxy.py --print-env    # 只打印需要写进 .env 的两行

设计取舍：
- 代理入口从 DSH 的 profile 目录里找（本机已随 DSH 安装 billion-context），可用 BILI_ENTRY 覆盖；
- 会话数据目录默认放在项目 ``tmp/bili-data``（通过 XDG_DATA_HOME 隔离），
  避免和 DSH 自带的代理共用 ~/.local/share/billion-context 里的大库；
- 启动前先探测端口，避免像其它项目那样静默抢占/失败；
- 健康检查失败时直接退出并打印代理日志尾部，不假装启动成功；
- 只打印 env，不修改 .env（配置由使用者决定，避免把本地端口写进仓库）。
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
PID_FILE = PROJECT_ROOT / "tmp" / "bili-proxy.pid"
LOG_FILE = PROJECT_ROOT / "tmp" / "bili-proxy.log"
DATA_DIR = PROJECT_ROOT / "tmp" / "bili-data"
DEFAULT_CONFIG = CONFIG_DIR / "billion-context.json"
UPSTREAM = "https://api.deepseek.com"


def find_entry() -> Path:
    """定位 billion-context 的 dist/index.js。"""
    override = os.environ.get("BILI_ENTRY")
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return path
        raise SystemExit(f"BILI_ENTRY 指向的文件不存在：{path}")

    candidates: list[Path] = []
    dsh_home = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))
    profiles = dsh_home / "profiles"
    if profiles.is_dir():
        candidates.extend(sorted(profiles.glob("*/node_modules/billion-context/dist/index.js")))
    candidates.extend(sorted((Path.home() / "AppData/Roaming/npm/node_modules").glob("billion-context/dist/index.js")))
    candidates.extend(sorted(Path("/usr/lib/node_modules").glob("billion-context/dist/index.js")))

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit(
        "找不到 billion-context。请先安装（npm i -g billion-context），"
        "或用 BILI_ENTRY 指向 dist/index.js。"
    )


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def health_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/__bili/health"


def wait_health(host: str, port: int, timeout: float = 40.0) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health_url(host, port), timeout=2) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(0.5)
    return None


def print_env(host: str, port: int, config: Path) -> None:
    base = f"http://{host}:{port}/bili/{UPSTREAM}/v1"
    print("# 把下面两行写入 .env（或部署环境变量）即可让 ScholarMind 走压缩代理：")
    print(f"LLM_PROXY_BASE_URL={base}")
    print("LLM_PROXY_SESSION_HEADER=x-acp-session")
    print(f"# 代理配置文件：{config}")


def cmd_status(host: str, port: int) -> int:
    payload = wait_health(host, port, timeout=3)
    if not payload:
        print(f"未运行：{health_url(host, port)} 不可达")
        return 1
    print(f"运行中：{health_url(host, port)}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_stop() -> int:
    if not PID_FILE.is_file():
        print("没有找到 pid 文件，可能未以 --detach 启动")
        return 1
    pid = int(PID_FILE.read_text(encoding="utf-8").strip() or "0")
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False, capture_output=True)
        else:
            os.kill(pid, 15)
    finally:
        PID_FILE.unlink(missing_ok=True)
    print(f"已停止进程 {pid}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="启动 billion-context 压缩代理")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="代理配置 JSON")
    parser.add_argument("--port", type=int, default=None, help="覆盖配置里的端口")
    parser.add_argument("--host", default=None, help="覆盖配置里的监听地址")
    parser.add_argument("--detach", action="store_true", help="后台启动")
    parser.add_argument("--status", action="store_true", help="查看状态")
    parser.add_argument("--stop", action="store_true", help="停止后台实例")
    parser.add_argument("--print-env", action="store_true", help="只打印 env")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="代理会话数据目录（XDG_DATA_HOME）")
    parser.add_argument("--no-auto-update", action="store_true", default=True, help="透传给 bili")
    args = parser.parse_args()

    config = args.config if args.config.is_absolute() else (PROJECT_ROOT / args.config)
    if not config.is_file():
        raise SystemExit(f"代理配置不存在：{config}")
    raw = json.loads(config.read_text(encoding="utf-8"))
    host = args.host or raw.get("host") or "127.0.0.1"
    port = args.port or int(raw.get("port") or 8790)

    if args.stop:
        return cmd_stop()
    if args.status:
        return cmd_status(host, port)
    if args.print_env:
        print_env(host, port, config)
        return 0

    if not port_free(host, port):
        print(f"端口 {host}:{port} 已被占用；先 --status 确认是否已有实例，或用 --port 换端口。", file=sys.stderr)
        return 2

    entry = find_entry()
    command = ["node", str(entry), "start", "--host", host, "--port", str(port), "--config", str(config)]
    if args.no_auto_update:
        command.append("--no-auto-update")

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    data_dir = args.data_dir if args.data_dir.is_absolute() else (PROJECT_ROOT / args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["XDG_DATA_HOME"] = str(data_dir)

    stdout = LOG_FILE.open("a", encoding="utf-8")
    print(f"启动：{' '.join(command)}")
    print(f"数据目录：{data_dir}")
    process = subprocess.Popen(
        command, cwd=str(PROJECT_ROOT), stdout=stdout, stderr=subprocess.STDOUT, env=env
    )

    payload = wait_health(host, port)
    if not payload:
        process.poll()
        print("代理未在 40s 内就绪，日志尾部：", file=sys.stderr)
        tail = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
        print("\n".join(tail), file=sys.stderr)
        if process.poll() is None:
            process.terminate()
        return 3

    print(f"就绪：{health_url(host, port)} version={payload.get('version')}")
    if args.detach:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(process.pid), encoding="utf-8")
        print(f"已后台运行，pid={process.pid}，pid 文件：{PID_FILE}")
    else:
        print("前台运行中，Ctrl+C 停止")
    print_env(host, port, config)

    if args.detach:
        return 0
    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        return 0


if __name__ == "__main__":
    sys.exit(main())
