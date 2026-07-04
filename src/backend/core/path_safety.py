r"""
路径安全工具（P0 Task 5.3/5.4/5.7）

提供上传路径 containment 校验与 session_id 合法性校验，供：
- routers/upload.py：保存上传文件前校验
- services/agent_service.py：_load_upload_context 读取上传目录前校验

设计要点：
- SESSION_ID_PATTERN 强校验，拒绝 `..` / `/` / `\` / URL 编码穿越
- safe_session_path() 做 resolve().relative_to() containment 检查，确保最终路径在 upload_root 之内
- 所有 logger 调用使用 f-string（project_memory 硬约束）
"""
from __future__ import annotations

import re
import structlog
from pathlib import Path
from urllib.parse import unquote

from fastapi import HTTPException, status

logger = structlog.get_logger(__name__)

# P0 Task 5.3: session_id 仅允许字母/数字/下划线/连字符，长度 8-64。
# 拒绝包含 / \ .. % 等 traversal 字符的值。
SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")


def validate_session_id(session_id: str) -> str:
    """校验 session_id 合法性，返回清洗后的值；非法抛 400。

    先做 URL 解码（防 %2e%2e%2f 等编码穿越），再用正则匹配。
    解码后的值若仍含 path 分隔符或 .. 会被正则拒绝。
    """
    if not isinstance(session_id, str) or not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_session_id",
                "message": "session_id 不能为空",
            },
        )
    # 防 URL 编码穿越：先解码再校验
    decoded = unquote(session_id)
    if not SESSION_ID_PATTERN.match(decoded):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_session_id",
                "message": (
                    "session_id 仅允许字母、数字、下划线、连字符，"
                    "长度 8-64 字符；禁止包含路径分隔符或 .."
                ),
                "received": session_id[:32],  # 仅记录前 32 字符用于排错，避免日志注入
            },
        )
    return decoded


def safe_session_path(upload_root: Path, session_id: str) -> Path:
    """计算 session 上传目录的绝对路径并做 containment 校验。

    流程：
    1. 先 validate_session_id 拒绝非法 session_id（含 .. / 绝对路径 / URL 编码穿越）
    2. target_dir = (upload_root / safe_session_id).resolve()
    3. containment 检查：target_dir 必须是 upload_root.resolve() 自身或其子目录
    4. 不通过则抛 400，不创建任何目录或文件

    返回的 target_dir 已 resolve()，调用方可直接 mkdir(parents=True, exist_ok=True)。
    """
    safe_session_id = validate_session_id(session_id)
    root_resolved = upload_root.resolve()
    target_dir = (root_resolved / safe_session_id).resolve()

    # containment 检查：target_dir 必须等于 root 或在 root 之下
    try:
        target_dir.relative_to(root_resolved)
    except ValueError:
        logger.warning(
            f"path_traversal_blocked session_id={session_id!r} "
            f"target={target_dir!r} root={root_resolved!r}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "path_traversal_blocked",
                "message": "session_id 解析后的路径超出上传根目录",
            },
        )
    return target_dir
