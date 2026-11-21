"""R0 研究域测试夹具（verifier 独占文件，不修改 tests/conftest.py）。

设计原则
--------
1. 每个用例一个独立临时 SQLite，并种入两个真实用户 A/B，使跨用户归属断言
   永远在同一数据库上做交叉访问（AT-006/AT-007/AT-010）。
2. 使用真实 ``create_app()``（中间件、异常处理器、路由注册都是产品路径），
   只把 ``app.state`` 的引擎/会话工厂指向临时库。研究路由未挂载时夹具立即
   以可操作的信息失败，而不是让 60 个用例各报一次 404 掩盖半成品。
3. ``create_app()`` 每个测试会话只构建一次（约数秒），每个用例只重建数据库，
   保证 ``pytest src/backend/tests/test_research`` 的整体运行时间可控。

禁止在此文件写入对生产代码的补偿逻辑：夹具只准备环境，产品缺陷由用例暴露。
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import AsyncIterator, Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# 必须在导入 src.backend.config 之前设置；父级 tests/conftest.py 已设置限流/JWT。
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-secret-key-for-scholarmind-tests-min-32-characters-long",
)
os.environ.setdefault("RESEARCH_ENABLED", "true")

from ...db.session import (  # noqa: E402
    create_async_engine_from_url,
    create_async_sessionmaker_from_engine,
    init_db,
)
from ...models.orm import User, UserQuota  # noqa: E402
from ...research.contracts import Actor  # noqa: E402
from ...services.auth_service import create_access_token, get_password_hash  # noqa: E402


CAPABILITIES_PATH = "/api/v1/research/capabilities"


@dataclass
class ResearchStore:
    """独立临时库 + 双用户，不依赖 HTTP 路由是否已挂载。

    纯服务层/纯函数测试（解析、上传、计费、事件）只需要它，这样研究路由
    还没挂载时也能先验证已落地的模块，而不是让所有用例一起失败。
    """

    engine: Any
    session_factory: Any
    user_ids: dict[str, int]
    tokens: dict[str, str]
    db_path: str

    def headers(self, who: str = "a") -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[who]}"}

    def other(self, who: str = "a") -> str:
        return "b" if who == "a" else "a"

    def actor(self, who: str = "a") -> Actor:
        """服务层入口需要的 actor；用户不存在说明夹具种子有问题。"""
        return Actor(user_id=self.user_ids[who])


@dataclass
class ResearchEnv(ResearchStore):
    """一个用例的完整研究域环境：真 app + 临时库 + 双用户 token。"""

    app: Any = None


@pytest.fixture(scope="session")
def research_app() -> Any:
    """整个测试会话只构建一次真实应用（无 lifespan，ASGITransport 不触发 startup）。"""
    from ...app import create_app
    from ...config import settings

    app = create_app()
    # 路由用 getattr(settings, ...) 读这几个开关，但 Settings 里没有声明字段；
    # 直接写实例 __dict__ 可让 getattr 命中，避免排队任务的事件流等待真实 60s。
    settings.__dict__["RESEARCH_SSE_MAX_SECONDS"] = 1.0
    settings.__dict__["RESEARCH_SSE_POLL_SECONDS"] = 0.05
    return app


@pytest_asyncio.fixture
async def research_store() -> AsyncIterator[ResearchStore]:
    """独立临时 SQLite + 用户 A/B（不含 app，供纯服务层用例）。"""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_url = f"sqlite+aiosqlite:///{tmp.name}"
    engine = create_async_engine_from_url(db_url)
    try:
        await init_db(engine)
        session_factory = create_async_sessionmaker_from_engine(engine)
        user_ids: dict[str, int] = {}
        tokens: dict[str, str] = {}
        async with session_factory() as session:
            for key, name in (("a", "research_user_a"), ("b", "research_user_b")):
                user = User(
                    username=name,
                    password_hash=get_password_hash("test_pass_123"),
                    nickname=f"ResearchUser{key.upper()}",
                    is_active=True,
                    plan="free",
                )
                session.add(user)
                await session.flush()
                session.add(UserQuota(user_id=user.id, plan="free"))
                user_ids[key] = user.id
                tokens[key] = create_access_token(
                    {"sub": str(user.id), "username": name}
                )
            await session.commit()

        yield ResearchStore(
            engine=engine,
            session_factory=session_factory,
            user_ids=user_ids,
            tokens=tokens,
            db_path=tmp.name,
        )
    finally:
        await engine.dispose()
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


@pytest_asyncio.fixture
async def research_env(
    research_app: Any, research_store: ResearchStore
) -> AsyncIterator[ResearchEnv]:
    """在 research_store 之上挂真实 app，并校验研究路由确实已注册。"""
    # 把真实应用指向临时库（与 tests/conftest.py authed_async_client 同款做法）。
    research_app.state.db_engine = research_store.engine
    research_app.state.db_session_factory = research_store.session_factory

    registered = {getattr(route, "path", "") for route in research_app.routes}
    if CAPABILITIES_PATH not in registered:
        pytest.fail(
            "研究路由未挂载：create_app() 中没有 "
            f"{CAPABILITIES_PATH}。请检查 src/backend/routers/research.py "
            "是否存在、app.py 是否 include_router，以及 RESEARCH_ENABLED 配置。"
        )

    yield ResearchEnv(
        app=research_app,
        engine=research_store.engine,
        session_factory=research_store.session_factory,
        user_ids=research_store.user_ids,
        tokens=research_store.tokens,
        db_path=research_store.db_path,
    )


@pytest_asyncio.fixture
async def client_a(research_env: ResearchEnv) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=research_env.app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=research_env.headers("a"),
    ) as client:
        yield client


@pytest_asyncio.fixture
async def client_b(research_env: ResearchEnv) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=research_env.app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=research_env.headers("b"),
    ) as client:
        yield client


@pytest_asyncio.fixture
async def anon_client(research_env: ResearchEnv) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=research_env.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def db(research_store: ResearchStore) -> AsyncIterator[Any]:
    """直连临时库的会话，用于断言 DB 行/账本/事件序列（不要求路由已挂载）。"""
    async with research_store.session_factory() as session:
        yield session


# ── 通用 HTTP 帮助函数（供各测试文件复用，断言仍写在用例里）─────────


def error_payload(response: Any) -> dict:
    """返回统一错误结构 {"error": {...}}，结构不符时给出响应原文。"""
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 - 非 JSON 响应要让断言打印原文
        raise AssertionError(
            f"响应不是 JSON（status={response.status_code}）：{response.text[:500]}"
        )
    assert isinstance(payload, dict) and "error" in payload, payload
    return payload["error"]


def assert_error(response: Any, status: int, code: str | None = None) -> dict:
    """统一错误断言：状态码 + 错误码 + 结构。"""
    assert response.status_code == status, (
        f"期望 {status}，实际 {response.status_code}：{response.text[:800]}"
    )
    error = error_payload(response)
    if code is not None:
        assert error.get("code") == code, error
    assert isinstance(error.get("message"), str) and error["message"], error
    return error


def _entity_id(payload: Any, *keys: str) -> str:
    """从响应中取实体 ID，兼容直接对象与单键包裹两种形状。"""
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, dict):
                inner = value.get("id")
                if isinstance(inner, str):
                    return inner
            if isinstance(value, str):
                return value
        if isinstance(payload.get("id"), str):
            return payload["id"]
    raise AssertionError(f"响应中没有可识别的实体 ID：{payload}")


async def create_project(client: AsyncClient, title: str = "R0 验证项目") -> str:
    response = await client.post("/api/v1/research/projects", json={"title": title})
    assert response.status_code in (200, 201), response.text
    return _entity_id(response.json(), "project", "project_id", "id")


def _upload_files(filename: str, data: bytes, mime: str) -> dict:
    return {"file": (filename, data, mime)}


async def upload_document(
    client: AsyncClient,
    project_id: str,
    *,
    filename: str = "paper.md",
    text: str | bytes = "# 标题\n\n正文内容。\n",
    mime: str = "text/markdown",
) -> dict:
    data = text.encode("utf-8") if isinstance(text, str) else text
    response = await client.post(
        f"/api/v1/research/projects/{project_id}/documents",
        files=_upload_files(filename, data, mime),
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


def version_id_of(document_payload: dict) -> str:
    """从上传响应中取版本 ID，兼容 {document, version} 两种包裹。"""
    for container in (
        document_payload.get("version"),
        document_payload.get("document"),
        document_payload,
    ):
        if isinstance(container, dict):
            for key in ("version_id", "current_version_id", "id"):
                value = container.get(key)
                if isinstance(value, str):
                    return value
    raise AssertionError(f"上传响应缺少版本 ID：{document_payload}")


def task_body(
    *,
    project_id: str,
    document_version_id: str,
    kind: str = "review",
    objective: str = "检查全文论证与证据问题",
    **overrides: Any,
) -> dict:
    body: dict[str, Any] = {
        "schema_version": "1.0",
        "project_id": project_id,
        "kind": kind,
        "objective": objective,
        "input": {"document_version_id": document_version_id},
    }
    body.update(overrides)
    return body


async def create_task(
    client: AsyncClient,
    body: dict,
    *,
    idempotency_key: str,
) -> Any:
    """POST /tasks（唯一任务入口），不在此处断言状态码。"""
    return await client.post(
        "/api/v1/research/tasks",
        json=body,
        headers={"Idempotency-Key": idempotency_key},
    )
