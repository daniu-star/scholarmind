"""
Chart 路由测试
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_chart_types(async_client: AsyncClient):
    """测试获取图表类型列表"""
    response = await async_client.get("/api/chart/types")
    assert response.status_code == 200
    data = response.json()
    assert "chart_types" in data
    assert data["total"] == 12


@pytest.mark.asyncio
async def test_generate_chart_invalid_type(async_client: AsyncClient):
    """测试无效图表类型"""
    response = await async_client.post(
        "/api/chart/generate",
        json={
            "chart_type": "invalid_type",
            "title": "测试图表",
            "data": {"x": [1, 2, 3], "y": [4, 5, 6]},
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_generate_chart_invalid_dimensions(async_client: AsyncClient):
    """测试无效尺寸"""
    response = await async_client.post(
        "/api/chart/generate",
        json={
            "chart_type": "ribbon",
            "title": "测试图表",
            "width": 100,
            "height": 100,
            "data": {"x": [1, 2, 3], "y": [4, 5, 6]},
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_chart_not_found(async_client: AsyncClient):
    """测试获取不存在的图表"""
    response = await async_client.get("/api/chart/nonexistent")
    assert response.status_code == 404