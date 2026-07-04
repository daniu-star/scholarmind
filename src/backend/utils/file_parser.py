"""
ScholarMind 文件文本抽取工具（Task 27 抽取自 agent_service.py / routers/upload.py）

提供 PDF / DOCX 文件文本抽取的统一实现，消除 agent_service.py 与
routers/upload.py 之间的重复定义。

设计要点：
- 延迟导入 pypdf / python-docx，避免在模块加载阶段强依赖
- 抽取失败统一返回空字符串，由调用方决定如何处理
"""
from __future__ import annotations

import structlog
from pathlib import Path

logger = structlog.get_logger(__name__)


def extract_pdf(file_path: str | Path) -> str:
    """从 PDF 文件抽取文本（基于 pypdf）

    Args:
        file_path: PDF 文件路径

    Returns:
        抽取到的文本（多个 page 用 \\n 连接）；导入失败或抽取异常时返回空字符串
    """
    fp = Path(file_path)
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(fp))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n".join(pages)
    except ImportError:
        logger.warning("pypdf not installed, cannot extract PDF content")
        return ""
    except Exception as e:
        logger.warning(f"Failed to extract PDF {fp.name}: {e}")
        return ""


def extract_docx(file_path: str | Path) -> str:
    """从 DOCX 文件抽取文本（基于 python-docx）

    Args:
        file_path: DOCX 文件路径

    Returns:
        抽取到的段落文本（用 \\n 连接）；导入失败或抽取异常时返回空字符串
    """
    fp = Path(file_path)
    try:
        from docx import Document
        doc = Document(str(fp))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except ImportError:
        logger.warning("python-docx not installed, cannot extract DOCX content")
        return ""
    except Exception as e:
        logger.warning(f"Failed to extract DOCX {fp.name}: {e}")
        return ""
