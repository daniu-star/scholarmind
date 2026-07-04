"""
ScholarMind Word 文档导出 API 路由
支持多种期刊格式（国际新闻界、新闻与传播研究、新闻爱好者、通用学术格式）
"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import io
import structlog

from ..services.journal_formatter import JournalFormatter
from ..core.dependencies import get_current_user

router = APIRouter(prefix="/export", tags=["export"])

logger = structlog.get_logger(__name__)


class ExportRequest(BaseModel):
    content: str
    journal_style: str = "generic"  # gjxwj / xwycbyj / xwahz / generic
    title: Optional[str] = None
    author: Optional[str] = None


@router.post("/docx")
async def export_docx(
    request: ExportRequest,
    user_id: int = Depends(get_current_user),
):
    """导出 Word 文档（按期刊格式化）

    P0 修复: 强制鉴权（get_current_user），匿名请求返回 401；
    user_id 用于导出归属记录与审计日志。
    """
    if not request.content or not request.content.strip():
        raise HTTPException(status_code=400, detail="导出内容不能为空")

    try:
        formatter = JournalFormatter.get_formatter(request.journal_style)
        docx_bytes = formatter.format(
            request.content,
            title=request.title,
            author=request.author,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文档生成失败: {e}")

    # P0 修复: 记录导出归属与审计日志（不阻塞响应）
    try:
        logger.info(
            f"docx_export user_id={user_id} journal_style={request.journal_style} "
            f"title={(request.title or '')[:50]} bytes={len(docx_bytes)}"
        )
    except Exception:
        pass

    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=scholarmind-paper.docx"},
    )
