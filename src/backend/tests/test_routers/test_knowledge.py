"""
Knowledge (CNKI) 路由测试
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_knowledge_status(async_client: AsyncClient):
    """测试获取知识库状态"""
    response = await async_client.get("/api/knowledge/status")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "services" in data


@pytest.mark.asyncio
async def test_cnki_search_empty_query(async_client: AsyncClient):
    """测试空搜索词"""
    response = await async_client.post(
        "/api/knowledge/cnki/search",
        json={"query": "", "count": 10},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_cnki_config_update(async_client: AsyncClient):
    """测试 CNKI 配置更新"""
    response = await async_client.post(
        "/api/knowledge/cnki/config",
        json={"proxy_url": "http://test-proxy:8080"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["proxy_configured"] is True