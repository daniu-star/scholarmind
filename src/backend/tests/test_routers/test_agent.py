"""
Agent 路由测试
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_agents(async_client: AsyncClient):
    """测试获取 Agent 列表"""
    response = await async_client.get("/api/agent/agents")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "agents" in data


@pytest.mark.asyncio
async def test_chat_with_invalid_agent(async_client: AsyncClient):
    """测试无效 agent_id"""
    response = await async_client.post(
        "/api/agent/chat",
        json={
            "message": "测试消息",
            "agent_id": "invalid_agent",
            "session_id": "test-session-1",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_chat_with_empty_message(async_client: AsyncClient):
    """测试空消息"""
    response = await async_client.post(
        "/api/agent/chat",
        json={
            "message": "",
            "agent_id": "researcher",
            "session_id": "test-session-1",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_clear_conversation(async_client: AsyncClient):
    """测试清空对话"""
    response = await async_client.delete("/api/agent/conversation/test-session-1")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["session_id"] == "test-session-1"


@pytest.mark.asyncio
async def test_get_conversation_empty(async_client: AsyncClient):
    """测试获取空对话历史"""
    response = await async_client.get("/api/agent/conversation/nonexistent-session")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message_count"] == 0