"""
ScholarMind 测试夹具
使用 httpx.AsyncClient + 内存 SQLite + Mock 服务
"""
from __future__ import annotations

import os

# 测试环境: 禁用速率限制, 避免测试间互相触发 429
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
# P0 Task 3.9: 测试环境注入 JWT_SECRET_KEY（>=32 字符），避免 PyJWT 抛
# InvalidKeyError("HMAC key must not be empty")。settings 在模块导入时读取该 env var。
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-secret-key-for-scholarmind-tests-min-32-characters-long",
)

import pytest
import pytest_asyncio
from typing import AsyncGenerator

from httpx import ASGITransport, AsyncClient

from ..db.session import create_async_engine_from_url, create_async_sessionmaker_from_engine, init_db, Base
from ..db.repository.conversation import ConversationRepository
from ..db.repository.skill import SkillRepository
from ..db.repository.chart import ChartRepository
from ..models.orm import Conversation, Skill, ChartRecord


# ── 测试数据库 ──────────────────────────────────────────────

TEST_DATABASE_URL = "sqlite+aiosqlite:///test_scholarmind.db"


@pytest_asyncio.fixture(scope="function")
async def test_db():
    """创建测试数据库会话"""
    engine = create_async_engine_from_url(TEST_DATABASE_URL)
    await init_db(engine)
    session_factory = create_async_sessionmaker_from_engine(engine)

    async with session_factory() as session:
        yield session
        await session.rollback()

    # 清理
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def conv_repo(test_db):
    """对话仓储 fixture"""
    yield ConversationRepository(test_db)


@pytest_asyncio.fixture(scope="function")
async def skill_repo(test_db):
    """技能仓储 fixture"""
    yield SkillRepository(test_db)


@pytest_asyncio.fixture(scope="function")
async def chart_repo(test_db):
    """图表仓储 fixture"""
    yield ChartRepository(test_db)


# ── HTTP 客户端 ─────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """异步 HTTP 测试客户端"""
    from ..app import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ── Mock 服务 ────────────────────────────────────────────────

@pytest.fixture
def mock_deepseek(monkeypatch):
    """Mock DeepSeek API 调用"""

    class MockResponse:
        class Choice:
            def __init__(self, content):
                self.message = type("Message", (), {"content": content})()

        def __init__(self, content="这是模拟的AI回复"):
            self.choices = [self.Choice(content)]

    class MockChat:
        class Completions:
            async def create(self, **kwargs):
                return MockResponse()

        completions = Completions()

    async def mock_chat_create(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr(
        "openai.resources.chat.completions.AsyncCompletions.create",
        mock_chat_create,
    )