"""
文件上传路由

提供两个端点：
- POST /upload/{session_id}  Agent 对话附件上传（多文件，字段名 files）
- POST /upload                论文生成/修改链条文件上传（单文件，字段名 file）

历史：
P2-T2 死路由清理时误删了 upload 路由，但前端仍在调用，导致 404 被前端
统一报为"后端未启动"。本文件恢复该路由，并对 docx/pdf 做文本解析，
返回 text 字段供论文修改链条/外审专家卡片填充 paper_text。

P0 Task 5.3-5.6 安全加固：
- session_id 强校验（SESSION_ID_PATTERN），拒绝 ../、绝对路径、URL 编码穿越
- 保存前 containment 检查（resolve().relative_to）
- 原子落盘：先写 .part 再 rename，异常 finally 清理
- 写入前检查 MAX_FILES_PER_SESSION，超限返回 413
"""
from __future__ import annotations

import uuid
import structlog
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, status

from ..config import settings
# P1 Task 12：上传端点改为强制鉴权（原 get_optional_user_id 允许匿名上传持久化文件）
from ..core.dependencies import get_current_user
from ..core.path_safety import validate_session_id, safe_session_path
# Task 27: PDF/DOCX 文本抽取改用 utils/file_parser.py 公共实现
from ..utils.file_parser import extract_pdf, extract_docx

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/upload", tags=["upload"])

# ── 文件扩展名分类（从 config.py ALLOWED_EXTENSIONS 派生）─────
# 文本类：可直接 UTF-8 读取
_TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".py", ".r", ".bib", ".tex"}
# 二进制需解析
_BINARY_EXTENSIONS = {".pdf", ".docx"}
# 注: 新增格式需同步更新 config.py 的 ALLOWED_EXTENSIONS 白名单
assert _TEXT_EXTENSIONS | _BINARY_EXTENSIONS <= {f".{e}" for e in settings.ALLOWED_EXTENSIONS}, \
    "upload.py extension sets must be a subset of config.ALLOWED_EXTENSIONS"

# 单文件大小上限（字节），对齐前端 20MB 限制
_MAX_FILE_BYTES = settings.MAX_FILE_SIZE_MB * 1024 * 1024

# ── 扩展名 → 预期 MIME 映射（Task 21 magic byte 校验）─────
_EXT_TO_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".csv": "text/csv",
    ".json": "application/json",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".py": "text/x-python",
    ".r": "text/x-r",
    ".bib": "application/x-bibtex",
    ".tex": "application/x-tex",
    ".ipynb": "application/x-ipynb+json",
}


def _validate_magic_byte(file_path: str, expected_ext: str) -> bool:
    """通过 magic byte 校验文件实际类型与扩展名是否匹配（Task 21）

    Args:
        file_path: 落盘后的文件绝对路径
        expected_ext: 期望扩展名（含点，小写，如 ".pdf"）

    Returns:
        True 表示匹配或允许通过；False 表示类型不匹配（疑似伪装）
    """
    expected_ext = (expected_ext or "").lower()
    expected_mime = _EXT_TO_MIME.get(expected_ext)
    if expected_mime is None:
        # 未在映射表中登记的扩展名，跳过 magic 校验（不阻断已知白名单扩展名）
        return True
    try:
        # 懒加载：python-magic 未安装时优雅降级（已通过扩展名白名单 + 大小校验）
        import magic
        actual_mime = magic.from_file(file_path, mime=True) or ""
    except Exception as e:
        # magic 库不可用或读取失败：保守放行（已通过扩展名白名单 + 大小校验）
        logger.warning(f"magic_check_unavailable file={file_path} error={e}")
        return True

    # text/* 灵活匹配（不同 OS/库对文本类返回 charset 差异大，统一前缀匹配）
    if expected_mime.startswith("text/") and actual_mime.startswith("text/"):
        return True
    # application/json 兼容 text/plain（部分系统对 .json 返回 text/plain）
    if expected_mime == "application/json" and actual_mime in {"application/json", "text/plain", "application/x-json"}:
        return True
    if expected_mime == actual_mime:
        return True
    # 部分系统对 .docx/.xlsx 等 ZIP 容器返回 application/zip，视为兼容
    if expected_ext in {".docx", ".xlsx"} and actual_mime == "application/zip":
        return True
    return False


def _sanitize_filename_for_log(filename: str) -> str:
    """过滤文件名中的 CRLF，防止日志注入（Task 21）"""
    return (filename or "").replace("\r", "").replace("\n", "")


def _upload_root() -> Path:
    """返回上传根目录（绝对路径，自动创建）"""
    root = Path(settings.UPLOAD_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _extract_text(fp: Path) -> str:
    """从文件提取文本内容（文本类直接读，pdf/docx 调对应解析器）"""
    ext = fp.suffix.lower()
    try:
        if ext in _TEXT_EXTENSIONS:
            return fp.read_text(encoding="utf-8", errors="replace")
        if ext == ".pdf":
            # Task 27: 改用 utils/file_parser.py 公共实现
            return extract_pdf(fp)
        if ext == ".docx":
            # Task 27: 改用 utils/file_parser.py 公共实现
            return extract_docx(fp)
    except Exception as e:
        logger.warning(f"extract_text_failed file={fp.name} error={e}")
        return ""
    return ""


def _validate_extension(filename: str) -> str:
    """校验扩展名白名单，返回小写扩展名（含点），非法则抛 400"""
    ext = Path(filename).suffix.lower()
    if ext.lstrip(".") not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_file_type",
                "message": f"不支持的文件类型：{filename}",
                "allowed_extensions": sorted(settings.ALLOWED_EXTENSIONS),
            },
        )
    return ext


def _validate_size(file_size: int) -> None:
    """校验文件大小，超限抛 413"""
    if file_size > _MAX_FILE_BYTES:
        actual_mb = file_size / (1024 * 1024)
        raise HTTPException(
            # HTTP_413_CONTENT_TOO_LARGE (starlette 新名，旧名 REQUEST_ENTITY_TOO_LARGE 已弃用)
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "error": "file_too_large",
                "message": f"文件大小 {actual_mb:.1f}MB 超过限制 {settings.MAX_FILE_SIZE_MB}MB",
                "max_size_mb": settings.MAX_FILE_SIZE_MB,
                "actual_size_mb": round(actual_mb, 2),
            },
        )


def _count_existing_files(target_dir: Path) -> int:
    """统计 target_dir 中已存在的文件数（排除 .part 临时文件与 .meta 等元数据）"""
    if not target_dir.exists():
        return 0
    count = 0
    for fp in target_dir.iterdir():
        if fp.is_file() and not fp.name.endswith(".part"):
            count += 1
    return count


def _check_file_count_limit(target_dir: Path, incoming: int) -> None:
    """P0 Task 5.6: 写入前检查文件数量限制，超限抛 413。

    incoming 为本次请求将要写入的文件数（多文件上传时 >1）。
    """
    existing = _count_existing_files(target_dir)
    limit = settings.MAX_FILES_PER_SESSION
    if existing + incoming > limit:
        raise HTTPException(
            # HTTP_413_CONTENT_TOO_LARGE (starlette 新名，旧名 REQUEST_ENTITY_TOO_LARGE 已弃用)
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "error": "file_count_exceeded",
                "message": (
                    f"会话已有 {existing} 个文件，本次将新增 {incoming} 个，"
                    f"超过上限 {limit}"
                ),
                "existing": existing,
                "incoming": incoming,
                "limit": limit,
            },
        )


async def _save_upload(file: UploadFile, target_dir: Path) -> tuple[Path, int, str]:
    """保存 UploadFile 到 target_dir，返回 (保存路径, 字节数, 扩展名)。

    P0 Task 5.4/5.5 安全加固：
    - target_dir 已由 safe_session_path() 做 containment 校验，此处直接 mkdir
    - 原子落盘：先写 {stored_name}.part，校验通过后 rename 为 {stored_name}
    - finally 块清理 .part 残留（覆盖写入异常 / 校验失败 / rename 失败）
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    # 用 uuid 防重名
    ext = Path(file.filename or "").suffix.lower()
    stored_name = f"{uuid.uuid4().hex}{ext}"
    final_path = target_dir / stored_name
    temp_path = target_dir / f"{stored_name}.part"

    size = 0
    # 标记是否成功 rename：用于 finally 决定是否清理 temp_path
    renamed = False
    try:
        with temp_path.open("wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                size += len(chunk)
                _validate_size(size)  # 边读边校验，防止超大文件
                f.write(chunk)
        # 全部写入完成且大小校验通过，原子 rename 到最终路径
        temp_path.rename(final_path)
        renamed = True
    finally:
        # P0 Task 5.5: 异常时清理 .part 残留
        # 成功 rename 后 temp_path 不再存在，exists() 为 False，无需清理
        if not renamed and temp_path.exists():
            try:
                temp_path.unlink()
                logger.info(f"cleaned_part_file path={temp_path}")
            except Exception as e:
                logger.warning(f"clean_part_file_failed path={temp_path} error={e}")
    return final_path, size, ext


@router.post("/{session_id}")
async def upload_session_files(
    session_id: str,
    files: list[UploadFile] = File(...),
    user_id: int = Depends(get_current_user),
):
    """Agent 对话附件上传（多文件）

    P1 Task 12：强制鉴权，匿名上传返回 401（原无鉴权可持久化文件到服务器）。

    前端 handleFileUpload 调用，字段名 files，期望响应：
    {session_id, uploaded:[{filename, file_id, size, text_preview}], count, skipped:[{filename, reason}]}
    """
    # P0 Task 5.3: session_id 强校验（拒绝 ../、绝对路径、URL 编码穿越）
    safe_session_id = validate_session_id(session_id)
    # P0 Task 5.4: containment 检查 + 计算 session 目录绝对路径
    upload_root = _upload_root()
    session_dir = safe_session_path(upload_root, safe_session_id)

    # P0 Task 5.6: 写入前检查文件数量限制（按本次请求的文件数预算）
    _check_file_count_limit(session_dir, len(files))

    uploaded = []
    skipped = []

    for file in files:
        filename = file.filename or "unknown"
        # Task 21: 文件名进 logger 前过滤 CRLF，防止日志注入
        safe_filename = _sanitize_filename_for_log(filename)
        try:
            ext = _validate_extension(filename)
            saved_path, size, saved_ext = await _save_upload(file, session_dir)
            # Task 21: 落盘后 magic byte 校验，不匹配则删除文件并返回 400
            if not _validate_magic_byte(str(saved_path), saved_ext):
                try:
                    saved_path.unlink()
                except Exception:
                    pass
                logger.warning(
                    f"magic_byte_mismatch filename={safe_filename} "
                    f"ext={saved_ext}"
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "file_type_mismatch",
                        "message": f"文件类型与扩展名不匹配：{filename}",
                    },
                )
            # 保留原始文件名映射（写入一个 .meta 同名文件便于 _load_upload_context 读取）
            text = _extract_text(saved_path)
            file_id = uuid.uuid4().hex
            uploaded.append({
                "filename": filename,
                "file_id": file_id,
                "stored_name": saved_path.name,
                "extension": ext.lstrip("."),
                "size": size,
                "text_preview": text[:500] if text else "",
            })
        except HTTPException as e:
            skipped.append({"filename": filename, "reason": e.detail.get("message", str(e.detail)) if isinstance(e.detail, dict) else str(e.detail)})
        except Exception as e:
            logger.warning(f"upload_file_failed file={safe_filename} error={e}")
            skipped.append({"filename": filename, "reason": f"上传失败：{e}"})

    return {
        "session_id": safe_session_id,
        "uploaded": uploaded,
        "count": len(uploaded),
        "skipped": skipped,
    }


@router.post("")
async def upload_single_file(
    file: UploadFile = File(...),
    purpose: Optional[str] = Form(default=None),
    user_id: int = Depends(get_current_user),
):
    """单文件上传（论文生成/修改链条/外审专家卡片用）

    P1 Task 12：强制鉴权（原 get_optional_user_id 允许匿名上传以兼容旧前端，
    存在持久化未授权文件风险），匿名上传返回 401。

    前端 showPaperGenerationDialog 等调用，字段名 file，期望响应：
    {file_id, filename, text, ...}
    返回的 text 字段为解析后的全文，前端用于填充 paper_text。
    """
    filename = file.filename or "unknown"
    # Task 21: 文件名进 logger 前过滤 CRLF，防止日志注入
    safe_filename = _sanitize_filename_for_log(filename)
    ext = _validate_extension(filename)

    # 单文件统一存到 single_uploads/ 子目录（标识需满足 SESSION_ID_PATTERN 长度 8-64）
    upload_root = _upload_root()
    single_dir = safe_session_path(upload_root, "single_uploads")

    # P0 Task 5.6: 单文件上传也检查数量限制（按 1 计）
    _check_file_count_limit(single_dir, 1)

    saved_path, size, saved_ext = await _save_upload(file, single_dir)

    # Task 21: 落盘后 magic byte 校验，不匹配则删除文件并返回 400
    if not _validate_magic_byte(str(saved_path), saved_ext):
        try:
            saved_path.unlink()
        except Exception:
            pass
        logger.warning(
            f"magic_byte_mismatch filename={safe_filename} ext={saved_ext}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "file_type_mismatch",
                "message": f"文件类型与扩展名不匹配：{filename}",
            },
        )

    text = _extract_text(saved_path)
    file_id = uuid.uuid4().hex

    return {
        "file_id": file_id,
        "id": file_id,  # 兼容前端读取 id 字段
        "filename": filename,
        "stored_name": saved_path.name,
        "extension": ext.lstrip("."),
        "size": size,
        "text": text,
        "text_preview": text[:500] if text else "",
        "purpose": purpose,
    }
