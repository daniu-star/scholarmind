"""把 Vercel 前端的 API 指向一个新的后端地址。

用法::

    python scripts/point_backend.py https://xxxx.trycloudflare.com

脚本会改写两处（其余不动）：

* ``vercel.json`` 里 ``/api/*`` 的 rewrite 目标（浏览器请求经 Vercel 代理转发）；
* ``api/platform-status.js`` 的 ``DEFAULT_BACKEND_ORIGIN``（状态页探测的后端）。

改完需要重新构建并部署前端，例如::

    npm run build:frontend
    bash /c/vtmp/vc.sh build --prod
    bash /c/vtmp/vc.sh deploy --prebuilt --prod --yes

为什么需要这个脚本：Cloudflare 快速隧道每次重启都会换域名，换域名就必须让
Vercel 的 rewrite 跟着换，否则 ``/api/*`` 会打到旧域名上返回 404。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERCEL_JSON = REPO_ROOT / "vercel.json"
STATUS_JS = REPO_ROOT / "api" / "platform-status.js"
ORIGIN_RE = re.compile(r"const DEFAULT_BACKEND_ORIGIN = '[^']*';")


def normalize(url: str) -> str:
    value = url.strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        raise SystemExit(f"后端地址必须以 http:// 或 https:// 开头：{url!r}")
    return value


def patch_vercel(path: Path, backend: str) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    patched = False
    for rewrite in data.get("rewrites", []):
        if str(rewrite.get("source", "")).startswith("/api/"):
            rewrite["destination"] = f"{backend}/api/$1"
            patched = True
    if not patched:
        raise SystemExit("vercel.json 里没有找到 /api/* 的 rewrite 规则")
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return data["rewrites"][0]["destination"]


def patch_status(path: Path, backend: str) -> str:
    source = path.read_text(encoding="utf-8")
    if not ORIGIN_RE.search(source):
        raise SystemExit("platform-status.js 里没有找到 DEFAULT_BACKEND_ORIGIN")
    updated = ORIGIN_RE.sub(f"const DEFAULT_BACKEND_ORIGIN = '{backend}';", source, count=1)
    path.write_bytes(updated.replace("\r\n", "\n").encode("utf-8"))
    return backend


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把 Vercel 前端的 API 指向新的后端地址")
    parser.add_argument("backend", help="后端基地址，例如 https://xxx.trycloudflare.com")
    args = parser.parse_args(argv)

    backend = normalize(args.backend)
    rewrite = patch_vercel(VERCEL_JSON, backend)
    origin = patch_status(STATUS_JS, backend)

    print(f"vercel.json rewrite -> {rewrite}")
    print(f"platform-status origin -> {origin}")
    print("下一步：npm run build:frontend && vc build --prod && vc deploy --prebuilt --prod --yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
