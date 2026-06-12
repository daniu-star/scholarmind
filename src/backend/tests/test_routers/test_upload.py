"""
Upload 路由测试
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_empty_files(async_client: AsyncClient):
    """测试获取空会话文件列表"""
    response = await async_client.get("/api/upload/empty-session")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0


@pytest.mark.asyncio
async def test_upload_no_files(async_client: AsyncClient):
    """测试上传空文件列表"""
    response = await async_client.post("/api/upload/test-session", files=[])
    assert response.status_code == 422 or response.status_code == 400


@pytest.mark.asyncio
async def test_delete_nonexistent_file(async_client: AsyncClient):
    """测试删除不存在的文件"""
    response = await async_client.delete("/api/upload/test-session/nonexistent.txt")
    assert response.status_code == 404