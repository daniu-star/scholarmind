from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import PlainTextResponse
from typing import List, Optional
import uuid
from pathlib import Path

from ..config import settings

router = APIRouter(prefix="/upload", tags=["upload"])

# File type to tag mapping
TYPE_LABELS = {
    'csv': '原始数据', 'xlsx': '数据表格', 'json': '数据文件',
    'pdf': '研究文档', 'docx': '研究计划', 'md': '研究笔记',
    'txt': '文本文件', 'r': 'R脚本', 'py': 'Python脚本',
    'ipynb': 'Jupyter', 'tex': 'LaTeX', 'bib': '参考文献'
}

# 从全局配置读取参数
ALLOWED_EXTENSIONS = settings.ALLOWED_EXTENSIONS
MAX_FILE_SIZE = settings.MAX_FILE_SIZE_MB * 1024 * 1024
MAX_FILES = settings.MAX_FILES_PER_SESSION
MIN_FILES = 1  # 允许上传1个文件，不再强制5个

UPLOAD_BASE = Path(settings.UPLOAD_DIR)


def get_file_tag(filename: str, ext: str) -> str:
    """Auto-classify file tag based on name and extension"""
    lower = filename.lower()
    if any(kw in lower for kw in ['计划', 'proposal', 'plan']):
        return '研究计划'
    if any(kw in lower for kw in ['设计', 'design']):
        return '研究设计'
    if ext in ['csv', 'xlsx', 'json']:
        return '原始数据'
    if ext == 'bib':
        return '参考文献'
    return '文档'


def _safe_session_path(session_id: str) -> Path:
    """Validate session_id and return the upload directory path."""
    if not session_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="无效的 session_id")
    return UPLOAD_BASE / session_id


@router.post("/{session_id}")
async def upload_files(session_id: str, files: List[UploadFile] = File(...)):
    """Upload files (1-15 per session)"""
    if len(files) < MIN_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"至少需要上传 {MIN_FILES} 个文件，当前 {len(files)} 个"
        )
    if len(files) > MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"最多上传 {MAX_FILES} 个文件，当前 {len(files)} 个"
        )

    session_dir = _safe_session_path(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    # Count existing files
    existing = list(session_dir.iterdir()) if session_dir.exists() else []
    if len(existing) + len(files) > MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"会话文件总数不能超过 {MAX_FILES} 个（已有 {len(existing)} 个，本次上传 {len(files)} 个）"
        )

    uploaded = []
    for f in files:
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型: .{ext}，允许的类型: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )

        # Read content to check size
        content = await f.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"文件 {f.filename} 超过大小限制 ({settings.MAX_FILE_SIZE_MB}MB)"
            )

        # Generate unique filename to avoid collision
        file_id = uuid.uuid4().hex[:8]
        safe_name = f"{file_id}_{f.filename}"
        dest = session_dir / safe_name

        with open(dest, "wb") as out:
            out.write(content)

        tag = get_file_tag(f.filename, ext)
        uploaded.append({
            "file_id": file_id,
            "filename": f.filename,
            "stored_name": safe_name,
            "extension": ext,
            "size": len(content),
            "tag": tag,
            "type_label": TYPE_LABELS.get(ext, "文档"),
        })

    return {"session_id": session_id, "uploaded": uploaded, "count": len(uploaded)}


@router.get("/{session_id}")
async def list_files(session_id: str):
    """List uploaded files for a session"""
    session_dir = _safe_session_path(session_id)

    if not session_dir.exists():
        return {"session_id": session_id, "files": [], "count": 0}

    files = []
    for fp in sorted(session_dir.iterdir()):
        if not fp.is_file():
            continue
        ext = fp.suffix.lstrip(".").lower()
        parts = fp.name.split("_", 1)
        original_name = parts[1] if len(parts) > 1 else fp.name
        file_id = parts[0] if len(parts) > 1 else ""

        tag = get_file_tag(original_name, ext)
        files.append({
            "file_id": file_id,
            "filename": original_name,
            "stored_name": fp.name,
            "extension": ext,
            "size": fp.stat().st_size,
            "tag": tag,
            "type_label": TYPE_LABELS.get(ext, "文档"),
        })

    return {"session_id": session_id, "files": files, "count": len(files)}


@router.get("/{session_id}/{file_name}/content")
async def get_file_content(session_id: str, file_name: str):
    """Extract and return text content of an uploaded file"""
    session_dir = _safe_session_path(session_id)

    # Prevent path traversal in file_name
    if "/" in file_name or "\\" in file_name or ".." in file_name:
        raise HTTPException(status_code=400, detail="无效的文件名")

    target = session_dir / file_name

    try:
        target.resolve().relative_to(session_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的文件路径")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    ext = target.suffix.lstrip(".").lower()
    content = _extract_text_content(target, ext)

    if content is None:
        raise HTTPException(
            status_code=422,
            detail=f"无法提取 .{ext} 文件的文本内容"
        )

    return PlainTextResponse(content=content)


def _extract_text_content(filepath: Path, ext: str) -> Optional[str]:
    """Extract text content from various file types"""
    try:
        if ext in ("txt", "md", "csv", "json", "py", "r", "bib", "tex", "ipynb"):
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                return f.read()

        if ext == "pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(filepath))
                pages = []
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        pages.append(text)
                return "\n\n".join(pages)
            except ImportError:
                return None

        if ext == "docx":
            try:
                from docx import Document
                doc = Document(str(filepath))
                return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            except ImportError:
                return None

        if ext in ("xlsx", "xls"):
            import pandas as pd
            df = pd.read_excel(filepath)
            return df.to_string()

    except Exception:
        return None

    return None


@router.delete("/{session_id}/{file_name}")
async def delete_file(session_id: str, file_name: str):
    """Delete a specific file"""
    session_dir = _safe_session_path(session_id)

    if "/" in file_name or "\\" in file_name or ".." in file_name:
        raise HTTPException(status_code=400, detail="无效的文件名")

    target = session_dir / file_name

    try:
        target.resolve().relative_to(session_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的文件路径")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    target.unlink()
    return {"session_id": session_id, "deleted": file_name, "success": True}
