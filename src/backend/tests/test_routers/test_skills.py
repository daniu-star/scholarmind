"""
Skills 路由测试
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_skills(async_client: AsyncClient):
    """测试获取技能列表"""
    response = await async_client.get("/api/skills")
    assert response.status_code == 200
    data = response.json()
    assert "skills" in data
    assert "count" in data


@pytest.mark.asyncio
async def test_get_skill_not_found(async_client: AsyncClient):
    """测试获取不存在的技能"""
    response = await async_client.get("/api/skills/nonexistent-skill")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_skill_template(async_client: AsyncClient):
    """测试获取技能模板"""
    response = await async_client.get("/api/skills/template")
    assert response.status_code == 200
    data = response.json()
    assert "template" in data
    assert "format" in data


@pytest.mark.asyncio
async def test_delete_preset_skill(async_client: AsyncClient):
    """测试删除预设技能（应该失败）"""
    response = await async_client.delete("/api/skills/academic-researcher")
    assert response.status_code in (400, 404)


@pytest.mark.asyncio
async def test_create_skill_invalid(async_client: AsyncClient):
    """测试创建无效技能"""
    response = await async_client.post(
        "/api/skills",
        json={"id": "", "display_name": ""},
    )
    assert response.status_code == 422