"""
Agent 路由测试

P0 Task 3.8：原 test_clear_conversation / test_get_conversation_empty 固化了
"匿名可清空/读取会话"的越权行为。强制鉴权上线后，匿名请求应返回 401。
本文件已修正这些断言。
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_agents(async_client: AsyncClient):
    """测试获取 Agent 列表（P0 Task 3.8：匿名请求返回 401）"""
    response = await async_client.get("/api/v1/agent/agents")
    # P0 Task 3.2：强制鉴权后，匿名请求返回 401（不再返回 200）
    assert response.status_code == 401, (
        f"expected 401 for anonymous /agents, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_chat_with_invalid_agent(async_client: AsyncClient):
    """测试无效 agent_id（P0 Task 3.8：匿名请求返回 401，不再返回 400）"""
    response = await async_client.post(
        "/api/v1/agent/chat",
        json={
            "message": "测试消息",
            "agent_id": "invalid_agent",
            "session_id": "test-session-1",
        },
    )
    # P0 Task 3.2：强制鉴权，匿名请求在 422/400 之前先返回 401
    assert response.status_code == 401, (
        f"expected 401 for anonymous chat, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_chat_with_empty_message(async_client: AsyncClient):
    """测试空消息（P0 Task 3.8：匿名请求返回 401，不再返回 400/422）"""
    response = await async_client.post(
        "/api/v1/agent/chat",
        json={
            "message": "",
            "agent_id": "researcher",
            "session_id": "test-session-1",
        },
    )
    # P0 Task 3.2：强制鉴权，匿名请求在 422/400 之前先返回 401
    assert response.status_code == 401, (
        f"expected 401 for anonymous chat, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_clear_conversation_anonymous_rejected(async_client: AsyncClient):
    """P0 Task 3.8：匿名清空对话被拒（401）

    原断言固化的越权行为（匿名 DELETE 返回 200 success=True）已修正为 401。
    """
    response = await async_client.delete("/api/v1/agent/conversation/test-session-1")
    assert response.status_code == 401, (
        f"expected 401 for anonymous clear_conversation, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_get_conversation_anonymous_rejected(async_client: AsyncClient):
    """P0 Task 3.8：匿名获取对话历史被拒（401）

    原断言固化的越权行为（匿名 GET nonexistent-session 返回 200 message_count=0）
    已修正为 401。
    """
    response = await async_client.get("/api/v1/agent/conversation/nonexistent-session")
    assert response.status_code == 401, (
        f"expected 401 for anonymous get_conversation, got {response.status_code}: {response.text}"
    )
