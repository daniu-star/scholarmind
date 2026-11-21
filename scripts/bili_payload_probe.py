"""验证 billion-context 在“正常流量”下是否原样转发（零注入、零改写）。

做法：起一个仅记录请求的 mock OpenAI 上游，再让 bili 指向它，同一份 payload 分别
直连 mock 与经代理发出，比较上游实际收到的 messages / tools。

退出码：0 = 完全一致（零开销转发）；1 = 存在注入或改写（打印差异）；2 = 环境不满足；
3 = 代理未就绪。

用法：python scripts/bili_payload_probe.py [--turns 12]
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAPTURED: list[dict] = []


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802 - http.server 约定
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        CAPTURED.append(body)
        payload = {
            "id": "chatcmpl-probe",
            "object": "chat.completion",
            "created": 0,
            "model": body.get("model") or "probe",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        return


def find_entry() -> Path | None:
    override = os.environ.get("BILI_ENTRY")
    if override and Path(override).is_file():
        return Path(override)
    dsh_home = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))
    for candidate in sorted((dsh_home / "profiles").glob("*/node_modules/billion-context/dist/index.js")):
        if candidate.is_file():
            return candidate
    return None


def build_payload(turns: int) -> dict:
    messages = [{"role": "system", "content": "你是 ScholarMind 的论文写作助手。"}]
    for index in range(turns):
        messages.append({"role": "user", "content": f"第{index + 1}轮：请给出论证与文献建议。"})
        messages.append({"role": "assistant", "content": f"第{index + 1}轮：建议补充稳健性检验与对照实验。"})
    messages.append({"role": "user", "content": "最后：请总结一下重点。"})
    return {"model": "deepseek-v4-flash", "messages": messages, "max_tokens": 64}


def post_json(url: str, payload: dict, session: str) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "x-acp-session": session},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        response.read()


def wait_health(port: int, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/__bili/health", timeout=2) as response:
                return json.loads(response.read().decode("utf-8")).get("ok") is True
        except Exception:  # noqa: BLE001 - 探测期允许任何失败
            time.sleep(0.5)
    return False


def summarize(body: dict) -> dict:
    messages = body.get("messages") or []
    return {
        "n_messages": len(messages),
        "tools": [t.get("function", {}).get("name") for t in (body.get("tools") or [])],
        "chars": sum(len(json.dumps(item, ensure_ascii=False)) for item in messages),
        "roles": [item.get("role") for item in messages],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 bili 是否原样转发")
    parser.add_argument("--turns", type=int, default=12)
    args = parser.parse_args()

    entry = find_entry()
    if not entry:
        print("找不到 billion-context 的 dist/index.js（npm i -g billion-context 或设置 BILI_ENTRY）", file=sys.stderr)
        return 2
    if not shutil_which_node():
        print("PATH 里没有 node", file=sys.stderr)
        return 2

    mock_port = free_port()
    bili_port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", mock_port), MockHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    config = {
        "port": bili_port,
        "host": "127.0.0.1",
        "sessionHeader": "x-acp-session",
        "providers": {
            f"http://127.0.0.1:{mock_port}": {
                "models": {"deepseek-v4-flash": {"context": 131072, "output": 8192}}
            }
        },
        "compress": {"modelContextLimit": 131072, "maxContextLimit": "60%", "emergencyThresholdPercent": "92%"},
    }
    work_dir = Path(tempfile.mkdtemp(prefix="bili-probe-"))
    config_path = work_dir / "bili-probe.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

    data_dir = work_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["XDG_DATA_HOME"] = str(data_dir)
    process = subprocess.Popen(
        ["node", str(entry), "start", "--port", str(bili_port), "--config", str(config_path), "--no-auto-update"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        if not wait_health(bili_port):
            print("bili 未就绪", file=sys.stderr)
            return 3

        payload = build_payload(args.turns)
        post_json(f"http://127.0.0.1:{mock_port}/v1/chat/completions", payload, "probe-direct")
        post_json(f"http://127.0.0.1:{bili_port}/bili/http://127.0.0.1:{mock_port}/v1/chat/completions", payload, "probe-proxy")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        server.shutdown()
        import shutil

        try:
            process.wait(timeout=5)
        except Exception:  # noqa: BLE001 - 清理阶段不再强调错误
            pass
        shutil.rmtree(work_dir, ignore_errors=True)

    if len(CAPTURED) < 2:
        print(f"只捕获到 {len(CAPTURED)} 个请求，无法比较", file=sys.stderr)
        return 3
    direct, proxied = summarize(CAPTURED[0]), summarize(CAPTURED[1])
    print("直连：", json.dumps(direct, ensure_ascii=False))
    print("经代理：", json.dumps(proxied, ensure_ascii=False))

    same = (
        direct["n_messages"] == proxied["n_messages"]
        and direct["chars"] == proxied["chars"]
        and direct["tools"] == proxied["tools"]
        and direct["roles"] == proxied["roles"]
    )
    if same:
        print("结论：代理原样转发（零注入、零改写）")
        return 0
    print("结论：代理改写了 payload，差异如下：", file=sys.stderr)
    for key in ("n_messages", "chars", "tools", "roles"):
        if direct[key] != proxied[key]:
            print(f"  {key}: direct={direct[key]} proxy={proxied[key]}", file=sys.stderr)
    return 1


def shutil_which_node() -> bool:
    from shutil import which

    return which("node") is not None


if __name__ == "__main__":
    sys.exit(main())
