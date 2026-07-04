"""
ScholarMind 写作分析 API 路由
提供深度写作分析（不调用 LLM，快速返回结构化结果）
"""
import re
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Dict, Any

from ..core.dependencies import get_current_user

router = APIRouter(prefix="/writing", tags=["writing"])


class WritingAnalysisRequest(BaseModel):
    content: str
    analysis_type: str = "full"  # full / structure / grammar / academic


@router.post("/analyze")
async def analyze_writing(
    request: WritingAnalysisRequest,
    user_id: int = Depends(get_current_user),
):
    """深度写作分析（基础规则分析，不调用 LLM）

    P1: 增加鉴权，防止匿名调用消耗服务器资源。
    """
    content = request.content or ""

    # 基础统计
    result = {
        "word_count": _count_chars(content),
        "chinese_chars": len(re.findall(r'[\u4e00-\u9fa5]', content)),
        "english_words": len(re.findall(r'[A-Za-z]+(?:[-\'][A-Za-z]+)*', content)),
        "paragraphs": content.count('\n\n') + 1 if content.strip() else 0,
        "headings": _extract_headings(content),
        "suggestions": [],
    }

    # 检测段落过长
    paragraphs = [p for p in content.split('\n\n') if p.strip()]
    for i, p in enumerate(paragraphs):
        if len(p) > 500:
            result["suggestions"].append(f"第{i + 1}段较长（{len(p)}字），建议拆分")

    # 检测缺少标题
    if '#' not in content and content.strip():
        result["suggestions"].append("建议添加标题层级结构（使用 Markdown # 语法）")

    # 检测引用
    citations = re.findall(r'\[(\d+(?:[-,，\s*\d]+)*)\]', content)
    if not citations and len(content) > 300:
        result["suggestions"].append("未检测到文献引用，学术论文应包含充分的引用")

    # 检测参考文献章节
    has_references = bool(re.search(r'^#{1,6}\s*(参考文献|References|REFERENCES|文献|Bibliography)', content, re.MULTILINE))
    if citations and not has_references:
        result["suggestions"].append("存在引用标记但缺少参考文献章节")

    # 检测摘要
    if len(content) > 500 and not re.search(r'(摘要|Abstract|ABSTRACT)', content):
        result["suggestions"].append("未检测到摘要，学术论文通常需要包含摘要")

    return result


def _count_chars(content: str) -> int:
    """统计字符数（去除空白）"""
    return len(re.sub(r'\s', '', content)) if content else 0


def _extract_headings(content: str) -> List[Dict[str, Any]]:
    """提取 Markdown 标题"""
    headings = []
    if not content:
        return headings
    for match in re.finditer(r'^(#{1,6})\s+(.+?)\s*#*\s*$', content, re.MULTILINE):
        headings.append({
            "level": len(match.group(1)),
            "text": match.group(2).strip(),
        })
    return headings
