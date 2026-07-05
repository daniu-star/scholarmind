"""
P0 Task 5.9: 上传安全回归测试

覆盖 spec 中的 4 个 Scenario：
1. 路径穿越被拒（../、绝对路径、URL 编码穿越返回 400）
2. 上传失败无 .part 残留（21MB 超限后磁盘无 .part 残留）
3. 文件数量限制生效（超过 MAX_FILES_PER_SESSION 返回 413）
4. 启动目录无关（从不同 cwd 启动时 DATABASE_URL 解析为同一绝对路径）

测试策略：
- 路径穿越同时用「单元测试」（直接调 validate_session_id/safe_session_path 断言抛 400）
  和「HTTP 集成测试」（断言 400 或 404——Starlette URL 规范化会提前把 ../etc 变成
  /api/v1/etc 返回 404，这同样是"被拒"且更早，不创建任何目录）。
- 所有 logger 调用使用 f-string（project_memory 硬约束）。
"""
from __future__ import annotations

import io
import os
import sys
import subprocess
from pathlib import Path

import pytest
from httpx import AsyncClient

# 本测试位于 tests/test_routers/ 下，相对导入需要三个点回到 backend 包顶层
# （与 tests/conftest.py 的 .. 风格一致）。
from ...config import PROJECT_ROOT as BACKEND_PROJECT_ROOT
from ...core.path_safety import (
    validate_session_id,
    safe_session_path,
    SESSION_ID_PATTERN,
)
from fastapi import HTTPException


# ── 辅助：构造一个最小合法的 session_id（满足 ^[a-zA-Z0-9_-]{8,64}$）──
VALID_SESSION_ID = "testsession01"  # 13 chars


# ──── Scenario 1a: 单元测试 validate_session_id / safe_session_path ────


@pytest.mark.parametrize(
    "malicious_session_id",
    [
        "../etc",                       # 相对穿越
        "..%2f..%2fetc",                # URL 编码穿越（/ 编码）—— unquote 后是 ../../etc
        "%2e%2e%2f%2e%2e%2fetc",        # 全 URL 编码穿越（. 和 / 都编码）
        "..\\..\\windows",              # Windows 反斜杠穿越（含 \ 不在白名单）
        "/etc/passwd",                  # 绝对路径（含 / 不在白名单）
        "%2fetcpasswd",                 # URL 编码绝对路径
        "..",                           # 单纯 .. （长度 2 < 8 且含 .)
        "a/../../b",                    # 嵌套穿越（含 /)
        "valid_but_with/slash",         # 含斜杠
        "short",                        # 长度 5 < 8
        "a" * 65,                       # 长度 65 > 64
        "has space",                    # 含空格
        "has.dot",                      # 含点
    ],
)
def test_validate_session_id_rejects_traversal(malicious_session_id):
    """validate_session_id 对所有穿越/非法 session_id 抛 HTTPException(400)"""
    with pytest.raises(HTTPException) as exc_info:
        validate_session_id(malicious_session_id)
    assert exc_info.value.status_code == 400, (
        f"expected 400 for {malicious_session_id!r}, got {exc_info.value.status_code}"
    )


def test_safe_session_path_rejects_traversal(tmp_path):
    """safe_session_path 对穿越 session_id 抛 400，不创建任何目录"""
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    with pytest.raises(HTTPException) as exc_info:
        safe_session_path(upload_root, "../../etc")
    assert exc_info.value.status_code == 400
    # 断言未在 upload_root 之外创建目录
    assert not (tmp_path / "etc").exists(), "traversal dir leaked outside upload_root"


def test_validate_session_id_accepts_valid():
    """合法 session_id 通过校验"""
    valid_ids = [
        "testsession01",
        "abc12345",
        "user_12345",
        "session-2024",
        "a" * 8,
        "a" * 64,
    ]
    for sid in valid_ids:
        assert SESSION_ID_PATTERN.match(sid), f"valid session_id rejected: {sid}"
        assert validate_session_id(sid) == sid


# ──── Scenario 1b: HTTP 集成测试 — 路径穿越被拒 ──────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malicious_session_id",
    [
        "../etc",                       # 相对穿越（Starlette 规范化为 /api/v1/etc → 404）
        "..%2f..%2fetc",                # URL 编码穿越
        "%2e%2e%2f%2e%2e%2fetc",        # 全 URL 编码穿越
        "..\\..\\windows",              # Windows 反斜杠穿越（到 handler → 400）
        "/etc/passwd",                  # 绝对路径
        "valid_but_with/slash",         # 含斜杠（多段路径 → 404）
    ],
)
async def test_path_traversal_rejected_via_http(
    authed_async_client: AsyncClient,
    malicious_session_id: str,
    tmp_path: Path,
    monkeypatch,
):
    """HTTP 层：路径穿越 session_id 被拒（400 或 404 均算被拒），不创建任何穿越目录。

    说明：Starlette 在路由匹配前会规范化 URL，把 ../etc 解析为 /api/v1/etc，
    此时路由不匹配返回 404——这同样是"被拒"且更早（请求根本到不了 handler）。
    对于无法被规范化的（如反斜杠 ..\\..\\windows），到达 handler 后被
    validate_session_id 拒绝返回 400。两种情况都不应创建穿越目录。

    P1 Task 12：upload 端点改为强制鉴权，本测试改用 authed_async_client
    通过 dependency_overrides 覆盖 get_current_user 返回 user_id=1。
    """
    monkeypatch.setattr("src.backend.routers.upload.settings.UPLOAD_DIR", str(tmp_path))

    response = await authed_async_client.post(
        f"/api/v1/upload/{malicious_session_id}",
        files=[("files", ("sample.txt", io.BytesIO(b"hello"), "text/plain"))],
    )
    # 400（handler 拒绝）或 404（Starlette URL 规范化提前拒绝）都算"被拒"
    assert response.status_code in (400, 404), (
        f"expected 400 or 404 for session_id={malicious_session_id!r}, "
        f"got {response.status_code}: {response.text}"
    )
    # 关键断言：tmp_path 下未创建穿越目录（etc/、windows/、passwd 等）
    if tmp_path.exists():
        for entry in tmp_path.iterdir():
            # _upload_root 可能创建 uploads 根目录，但不应有穿越子目录
            assert ".." not in entry.name, f"traversal dir leaked: {entry.name}"
            assert entry.name not in ("etc", "windows", "passwd"), (
                f"traversal artifact created: {entry.name}"
            )


# ──── Scenario 2: 21MB 上传失败无 .part 残留 ─────────────────


@pytest.mark.asyncio
async def test_oversized_upload_no_part_residue(
    authed_async_client: AsyncClient,
    tmp_path: Path,
    monkeypatch,
):
    """21MB 上传超限后磁盘无 .part 残留文件"""
    monkeypatch.setattr("src.backend.routers.upload.settings.UPLOAD_DIR", str(tmp_path))
    # MAX_FILE_SIZE_MB 默认 20，上传 21MB 触发超限
    oversized_bytes = b"\x00" * (21 * 1024 * 1024)

    response = await authed_async_client.post(
        f"/api/v1/upload/{VALID_SESSION_ID}",
        files=[("files", ("big.bin", io.BytesIO(oversized_bytes), "application/octet-stream"))],
    )
    # 多文件上传端点：单个文件超限被捕获到 skipped，HTTP 仍 200
    assert response.status_code == 200, f"unexpected status: {response.status_code}: {response.text}"
    body = response.json()
    assert len(body["skipped"]) >= 1, "oversized file should be in skipped"
    assert body["count"] == 0, "no file should be uploaded"

    # 关键断言：tmp_path 下（含 session 子目录）无任何 .part 残留
    part_files = list(tmp_path.rglob("*.part"))
    assert part_files == [], f".part residue found: {part_files}"


# ──── Scenario 3: 文件数量限制生效 ───────────────────────────


@pytest.mark.asyncio
async def test_file_count_limit_enforced(
    authed_async_client: AsyncClient,
    tmp_path: Path,
    monkeypatch,
):
    """超过 MAX_FILES_PER_SESSION 限制返回 413，不写入新文件"""
    monkeypatch.setattr("src.backend.routers.upload.settings.UPLOAD_DIR", str(tmp_path))
    # 把限制调小到 3，便于测试（避免上传 16 个文件）
    monkeypatch.setattr("src.backend.routers.upload.settings.MAX_FILES_PER_SESSION", 3)

    # 先上传 3 个合法文件（达到上限）
    files_batch = [
        ("files", (f"file{i}.txt", io.BytesIO(f"content{i}".encode()), "text/plain"))
        for i in range(3)
    ]
    response = await authed_async_client.post(
        f"/api/v1/upload/{VALID_SESSION_ID}",
        files=files_batch,
    )
    assert response.status_code == 200, f"first batch failed: {response.text}"
    assert response.json()["count"] == 3

    # 再次上传 1 个文件，应被拒（413）
    response2 = await authed_async_client.post(
        f"/api/v1/upload/{VALID_SESSION_ID}",
        files=[("files", ("overflow.txt", io.BytesIO(b"overflow"), "text/plain"))],
    )
    assert response2.status_code == 413, (
        f"expected 413 for overflow, got {response2.status_code}: {response2.text}"
    )
    # error_handler 把 HTTPException detail 转成 {"success":false,"error":{"message": str(detail)}}
    # 检查 error.message 字符串包含 file_count_exceeded 与 超过上限
    body2 = response2.json()
    assert body2["success"] is False
    error_msg = body2["error"]["message"]
    assert "file_count_exceeded" in error_msg or "超过上限" in error_msg, (
        f"error message mismatch: {error_msg}"
    )

    # 断言 overflow.txt 未写入（磁盘上仍只有 3 个文件）
    session_dir = tmp_path / VALID_SESSION_ID
    saved_files = [
        f.name for f in session_dir.iterdir()
        if f.is_file() and not f.name.endswith(".part")
    ]
    assert len(saved_files) == 3, f"expected 3 files, got {saved_files}"
    assert all(not f.startswith("overflow") for f in saved_files), (
        f"overflow file written: {saved_files}"
    )


# ──── Scenario 4: 从不同 cwd 启动时数据库绝对路径一致 ────────


def test_database_url_invariant_across_cwd():
    """从项目根、src/backend、C:\\ 三个 cwd 启动时，DATABASE_URL/UPLOAD_DIR/DB_PATH 一致"""
    venv_python = sys.executable
    # BACKEND_PROJECT_ROOT = src/backend；项目根 = parent.parent
    project_root = str(BACKEND_PROJECT_ROOT.parent.parent)
    backend_dir = str(BACKEND_PROJECT_ROOT)

    check_script = (
        "import sys; "
        f"sys.path.insert(0, {project_root!r}); "
        "from src.backend.config import settings; "
        "print(settings.DATABASE_URL); "
        "print(settings.UPLOAD_DIR); "
        "print(settings.DB_PATH)"
    )

    env = {**os.environ, "RATE_LIMIT_ENABLED": "false"}

    # 从项目根 cwd 运行
    r1 = subprocess.run(
        [venv_python, "-c", check_script],
        cwd=project_root,
        capture_output=True,
        text=True,
        env=env,
    )
    assert r1.returncode == 0, f"from project root failed: {r1.stderr}"

    # 从 src/backend cwd 运行
    r2 = subprocess.run(
        [venv_python, "-c", check_script],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        env=env,
    )
    assert r2.returncode == 0, f"from backend dir failed: {r2.stderr}"

    # 从 C:\ cwd 运行（完全无关的 cwd）
    r3 = subprocess.run(
        [venv_python, "-c", check_script],
        cwd=os.environ.get("SystemDrive", "C:\\") + "\\",
        capture_output=True,
        text=True,
        env=env,
    )
    assert r3.returncode == 0, f"from C:\\ failed: {r3.stderr}"

    # 三个 cwd 下输出必须完全一致
    assert r1.stdout == r2.stdout == r3.stdout, (
        f"path differs across cwd:\n"
        f"  project_root: {r1.stdout!r}\n"
        f"  backend_dir:  {r2.stdout!r}\n"
        f"  C:\\:          {r3.stdout!r}"
    )

    # 解析出的路径必须是绝对路径
    lines = r1.stdout.strip().splitlines()
    db_url, upload_dir, db_path = lines[0], lines[1], lines[2]
    assert Path(upload_dir).is_absolute(), f"UPLOAD_DIR not absolute: {upload_dir}"
    assert Path(db_path).is_absolute(), f"DB_PATH not absolute: {db_path}"
    # DATABASE_URL 形如 sqlite+aiosqlite:///C:/abs/path.db
    db_path_in_url = db_url.split(":///", 1)[1]
    assert Path(db_path_in_url).is_absolute(), f"DATABASE_URL path not absolute: {db_url}"
