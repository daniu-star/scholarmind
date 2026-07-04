"""P0 Task 1.6: 代码执行入口安全回归测试

覆盖 spec Requirement「代码执行入口默认关闭与强制管理员鉴权」的 4 个 Scenario：
1. 生产环境默认关闭：CODE_EXECUTION_ENABLED 未设置时 /run 与 /pip-install 返回 404
2. 开发环境启用但匿名被拒：CODE_EXECUTION_ENABLED=true，匿名 → 401
3. 普通登录用户被拒：普通用户 → 403
4. 管理员可调用：admin 用户 → 200（mock 掉真实 subprocess）
5. pip-install 永久禁用：即便启用 Router，/pip-install 也 404

测试策略：
- 默认关闭用例复用 conftest 的 async_client（settings 默认 CODE_EXECUTION_ENABLED=False）
- 启用用例自建独立 fixture：monkeypatch settings.CODE_EXECUTION_ENABLED=True，
  手动初始化 temp DB 引擎 + init_db + 种子 admin/normal 用户，注入到 app.state，
  避免依赖 lifespan 与 dev DB
- /run 真实执行通过 dependency_overrides 替换 CodeExecutionService 为桩，
  避免 subprocess 副作用
- 所有 logger 调用使用 f-string（project_memory 硬约束）
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ...db.session import (
    create_async_engine_from_url,
    create_async_sessionmaker_from_engine,
    init_db,
)
from ...models.orm import User
from ...services.auth_service import create_access_token, get_password_hash


# ── 辅助：种子用户 ────────────────────────────────────────────


async def _seed_users(session_factory) -> tuple[int, int]:
    """种子一个 admin 用户（username=admin，命中 ADMIN_USERNAMES 白名单）
    与一个普通用户（username=normaluser）。

    返回 (admin_id, normal_id)。
    """
    async with session_factory() as session:
        admin = User(
            username="admin",
            password_hash=get_password_hash("adminpass123"),
            nickname="Admin",
            is_active=True,
            plan="pro",
        )
        normal = User(
            username="normaluser",
            password_hash=get_password_hash("normalpass123"),
            nickname="Normal",
            is_active=True,
            plan="free",
        )
        session.add_all([admin, normal])
        await session.commit()
        await session.refresh(admin)
        await session.refresh(normal)
        return admin.id, normal.id


# ── Fixture：启用代码执行的独立 client ────────────────────────


@pytest_asyncio.fixture(scope="function")
async def enabled_client(tmp_path, monkeypatch):
    """构造一个 CODE_EXECUTION_ENABLED=True 的独立 app + client。

    - 用 tmp_path 下的独立 sqlite 文件隔离 DB
    - 手动 init_db 建表 + 种子 admin/normal 用户
    - 注入 app.state.db_engine / db_session_factory 让 get_db 复用
    - 桩掉 CodeExecutionService.execute_code 避免 subprocess
    """
    # 隔离 DB（每个测试函数独立文件）
    db_file = tmp_path / "test_code_exec.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    monkeypatch.setattr("src.backend.config.settings.DATABASE_URL", db_url)
    monkeypatch.setattr("src.backend.config.settings.CODE_EXECUTION_ENABLED", True)
    # 确保 admin 白名单包含 "admin"
    monkeypatch.setattr("src.backend.config.settings.ADMIN_USERNAMES", "admin")

    engine = create_async_engine_from_url(db_url)
    await init_db(engine)
    session_factory = create_async_sessionmaker_from_engine(engine)
    admin_id, normal_id = await _seed_users(session_factory)

    from src.backend.app import create_app
    from src.backend.routers.code_execution import get_code_execution_service

    app = create_app()
    # 注入 DB 引擎，避免依赖 lifespan
    app.state.db_engine = engine
    app.state.db_session_factory = session_factory

    # 桩 CodeExecutionService：避免真实 subprocess
    # 返回 dict 让 FastAPI 按 response_model=CodeExecuteResponse 校验/序列化
    _stub_exec_result = {
        "success": True,
        "stdout": "stub output",
        "stderr": "",
        "exit_code": 0,
        "duration_ms": 1,
        "error": None,
    }

    class _StubService:
        async def execute_code(self, code, language="python", timeout=30):
            return _stub_exec_result

        async def list_installed_packages(self):
            return {"success": True, "packages": [], "total": 0}

    app.dependency_overrides[get_code_execution_service] = lambda: _StubService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 把 ids 挂在 client 上方便测试取用
        client._admin_id = admin_id  # type: ignore[attr-defined]
        client._normal_id = normal_id  # type: ignore[attr-defined]
        client._app = app  # type: ignore[attr-defined]
        yield client

    await engine.dispose()


def _bearer(user_id: int) -> dict[str, str]:
    """构造 Bearer token 头"""
    token = create_access_token({"sub": str(user_id), "username": "test"})
    return {"Authorization": f"Bearer {token}"}


# ──── Scenario 1: 默认关闭返回 404 ────────────────────────────


@pytest.mark.asyncio
async def test_code_execution_disabled_by_default(async_client: AsyncClient):
    """CODE_EXECUTION_ENABLED 默认 False：/run 返回 404（路由未注册）"""
    response = await async_client.post(
        "/api/v1/code-execution/run",
        json={"code": "print('hello')", "language": "python", "timeout": 5},
    )
    assert response.status_code == 404, (
        f"expected 404 when disabled, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_pip_install_disabled_by_default(async_client: AsyncClient):
    """/pip-install 默认 404（路由未注册）"""
    response = await async_client.post(
        "/api/v1/code-execution/pip-install",
        json={"package": "requests"},
    )
    assert response.status_code == 404, (
        f"expected 404 for pip-install when disabled, got {response.status_code}"
    )


# ──── Scenario 2: 启用但匿名被拒（401）────────────────────────


@pytest.mark.asyncio
async def test_code_execution_enabled_anonymous_rejected(enabled_client: AsyncClient):
    """CODE_EXECUTION_ENABLED=true，无 Authorization 头 → 401"""
    response = await enabled_client.post(
        "/api/v1/code-execution/run",
        json={"code": "print('hello')", "language": "python", "timeout": 5},
    )
    assert response.status_code == 401, (
        f"expected 401 for anonymous, got {response.status_code}: {response.text}"
    )


# ──── Scenario 3: 普通用户被拒（403）──────────────────────────


@pytest.mark.asyncio
async def test_code_execution_enabled_normal_user_forbidden(
    enabled_client: AsyncClient,
):
    """CODE_EXECUTION_ENABLED=true，普通用户 token → 403"""
    headers = _bearer(enabled_client._normal_id)  # type: ignore[attr-defined]
    response = await enabled_client.post(
        "/api/v1/code-execution/run",
        json={"code": "print('hello')", "language": "python", "timeout": 5},
        headers=headers,
    )
    assert response.status_code == 403, (
        f"expected 403 for normal user, got {response.status_code}: {response.text}"
    )


# ──── Scenario 4: 管理员可调用（200）─────────────────────────


@pytest.mark.asyncio
async def test_code_execution_enabled_admin_can_call(enabled_client: AsyncClient):
    """CODE_EXECUTION_ENABLED=true，管理员 token → 200"""
    headers = _bearer(enabled_client._admin_id)  # type: ignore[attr-defined]
    response = await enabled_client.post(
        "/api/v1/code-execution/run",
        json={"code": "print('hello')", "language": "python", "timeout": 5},
        headers=headers,
    )
    assert response.status_code == 200, (
        f"expected 200 for admin, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["success"] is True
    assert body["stdout"] == "stub output"


# ──── Scenario 5: /pip-install 即便启用 Router 也 404 ─────────


@pytest.mark.asyncio
async def test_pip_install_permanently_removed_when_enabled(
    enabled_client: AsyncClient,
):
    """即便 CODE_EXECUTION_ENABLED=true，/pip-install 也 404（端点已移除）"""
    headers = _bearer(enabled_client._admin_id)  # type: ignore[attr-defined]
    response = await enabled_client.post(
        "/api/v1/code-execution/pip-install",
        json={"package": "requests"},
        headers=headers,
    )
    assert response.status_code == 404, (
        f"expected 404 for pip-install even when enabled, "
        f"got {response.status_code}: {response.text}"
    )


# ──── Scenario 6: /packages 也强制管理员鉴权 ─────────────────


@pytest.mark.asyncio
async def test_packages_endpoint_requires_admin(enabled_client: AsyncClient):
    """/api/v1/code-execution/packages 强制管理员：匿名 → 401，普通 → 403，admin → 200"""
    # 匿名
    r1 = await enabled_client.get("/api/v1/code-execution/packages")
    assert r1.status_code == 401

    # 普通用户
    headers_normal = _bearer(enabled_client._normal_id)  # type: ignore[attr-defined]
    r2 = await enabled_client.get(
        "/api/v1/code-execution/packages", headers=headers_normal
    )
    assert r2.status_code == 403

    # admin
    headers_admin = _bearer(enabled_client._admin_id)  # type: ignore[attr-defined]
    r3 = await enabled_client.get(
        "/api/v1/code-execution/packages", headers=headers_admin
    )
    assert r3.status_code == 200, f"admin should get 200, got {r3.status_code}: {r3.text}"
