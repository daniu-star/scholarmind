"""
ScholarMind 知识库 API 路由
CNKI 检索、状态检查、配置管理
"""
from fastapi import APIRouter, HTTPException, Depends, Request

from ..services.cnki_service import CNKIService
from ..models.schemas.knowledge import CNKISearchRequest, CNKIConfigRequest
from ..core.dependencies import get_cnki_service

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("/cnki/search")
async def search_cnki(
    request: CNKISearchRequest,
    service: CNKIService = Depends(get_cnki_service),
):
    """Search CNKI academic database"""
    try:
        results = await service.search(
            query=request.query,
            year_filter=request.year_filter,
            count=request.count,
        )
        return {
            "success": True,
            "query": request.query,
            "count": len(results),
            "results": [r.to_dict() for r in results],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CNKI search failed: {str(e)}")


@router.get("/status")
async def get_knowledge_status(
    service: CNKIService = Depends(get_cnki_service),
):
    """Get connection status of all knowledge bases"""
    try:
        status = await service.check_connection()
        return {
            "success": True,
            "services": status,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Status check failed: {str(e)}"
        )


@router.post("/cnki/config")
async def configure_cnki(
    request: CNKIConfigRequest,
    service: CNKIService = Depends(get_cnki_service),
):
    """Configure CNKI connection parameters"""
    try:
        if request.proxy_url is not None:
            service.configure_proxy(proxy_url=request.proxy_url)
        if request.api_key is not None:
            service.configure_api_key(api_key=request.api_key)
        if request.mcp_tools is not None:
            service.configure_mcp(tools=request.mcp_tools)

        return {
            "success": True,
            "message": "CNKI configuration updated",
            "proxy_configured": request.proxy_url is not None,
            "api_key_configured": request.api_key is not None,
            "mcp_configured": request.mcp_tools is not None,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Configuration failed: {str(e)}"
        )