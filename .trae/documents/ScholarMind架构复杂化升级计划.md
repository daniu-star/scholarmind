# ScholarMind 架构复杂化升级计划

## 概述

对 ScholarMind 项目进行系统性架构升级——后端从「简单 FastAPI + 文件存储」升级为「企业级 6 层分层架构」，前端从「单文件 SPA」升级为「模块化组件架构 + Vite 构建」。最终交付一套稳定、可维护、可扩展的学术研究助手系统。

---

## 当前实施进度（截至 2026-06-11）

### ✅ 已完成
| 步骤 | 内容 | 文件 |
|------|------|------|
| Step 1 | 目录结构创建 | middleware/ core/ models/ db/ tasks/ utils/ tests/ 全部已建 |
| Step 2-部分 | 核心基础设施 | `core/exceptions.py` ✅, `core/logging_config.py` ✅, `core/events.py` ✅ |
| - | 包初始化 | 全部 `__init__.py` 已创建 |

### ❌ 未完成（共 15 个步骤，含关键依赖问题）
| 步骤 | 内容 | 状态 |
|------|------|------|
| Step 2-剩余 | `core/dependencies.py` | ❌ 未创建 |
| Step 3 | 中间件层 4 个文件 | ❌ 仅空 `__init__.py` |
| Step 4 | 数据模型层 | ❌ 仅空目录 |
| Step 5 | 数据库层 | ❌ 仅空目录；`events.py` 已依赖 `db.session` 但该模块不存在 |
| Step 6 | 工具层 | ❌ 仅空 `__init__.py` |
| Step 7-10 | 重构 + 后台任务 + 测试 | ❌ |
| Step 11-17 | 前端架构升级 | ❌ 尚未开始 |

### ⚠️ 关键依赖问题（必须修复）
1. **`core/events.py` 引用了尚不存在的 `db.session` 模块**（`create_async_engine`, `create_async_sessionmaker`），导致模块导入失败
2. **`core/events.py` 引用了 `settings.database_url`**，但 [config.py](file:///c:/Users/13067/Desktop/AI产品/src/backend/config.py) 中未定义该字段（仅有 `DB_PATH`）
3. **现有 `app.py` 使用 `@asynccontextmanager lifespan`**，与 `core/events.py` 的 `startup/shutdown` 事件处理方式冲突，需统一
4. **现有 DatabaseService**（[db_service.py](file:///c:/Users/13067/Desktop/AI产品/src/backend/services/db_service.py), SQLite3 同步）和 **VectorService**（[vector_service.py](file:///c:/Users/13067/Desktop/AI产品/src/backend/services/vector_service.py), ChromaDB）需要在迁移中保留兼容

---

## Phase 0: 现状分析（基于实际代码审查）

### 后端现状

**文件清单**（18个Python文件，位于 `src/backend/`）：

| 文件 | 行数 | 职责 |
|------|------|------|
| [app.py](file:///c:/Users/13067/Desktop/AI产品/src/backend/app.py) | 66 | FastAPI 应用入口，CORS，路由注册，静态文件挂载 |
| [config.py](file:///c:/Users/13067/Desktop/AI产品/src/backend/config.py) | 42 | pydantic-settings 配置，.env 读取，目录创建 |
| routers/agent.py | 111 | Agent 对话 API（chat/clear/list/conversation） |
| routers/chart.py | 237 | 图表生成 API（generate/types/get），含数据解析 + 路径安全 |
| routers/upload.py | 232 | 文件上传 API（upload/list/content/delete），含文件类型自动标签 |
| routers/knowledge.py | 105 | CNKI 检索 API（search/status/config） |
| routers/skills.py | 149 | 技能 CRUD API（list/get/create/update/delete/toggle/upload/template） |
| services/agent_service.py | 716 | Agent 业务核心：prompt构建、DeepSeek调用、对话持久化、技能注入、图表/CNKI技能执行 |
| services/chart_service.py | 153 | 图表服务入口：12种图表类型映射 + 生成/回退 |
| services/chart_functions.py | 667 | 12种matplotlib高级图表实现（ribbon/violin/alluvial/bubble_kde等） |
| services/chart_data.py | 97 | 图表数据解析（JSON/CSV/Python对象）+ 辅助函数 |
| services/chart_style.py | 63 | Origin风格配置（academic配色/字体/边框/DPI） |
| services/cnki_service.py | 577 | CNKI检索服务：多级降级（MCP→直连→代理→CrossRef→PubMed）+ 缓存 |
| services/skills_service.py | 241 | 技能管理：8个预设技能 + 自定义技能CRUD + YAML frontmatter解析 |

**已有亮点**：
- 路由/服务分层清晰（5个router + 7个service模块）
- Pydantic v2 请求验证（含 `field_validator`）
- pydantic-settings 配置管理，.env 文件支持
- 异步 HTTP + aiohttp 连接池
- CNKI 多级搜索降级（MCP → 直连 → 代理 → CrossRef → PubMed）
- 图表模块化拆分（4个文件，12种Origin风格图表）
- 对话 JSON 文件持久化 + 内存缓存
- 技能 YAML frontmatter 存储

**关键缺口**：

| 维度 | 当前状态 | 问题 |
|------|----------|------|
| 中间件 | 仅 CORS | 无结构化日志、无统一错误处理、无限流、无请求ID追踪 |
| 依赖注入 | module-level singleton | 非 FastAPI Depends 模式，测试困难，生命周期不可控 |
| 数据库 | JSON/YAML 文件存储 | 无 ORM、无迁移、无事务、并发写不安全 |
| 异常体系 | 散落 `HTTPException` | 无统一异常处理器，错误格式不一致 |
| 后台任务 | 同步阻塞 | 图表生成/CNKI搜索阻塞 HTTP 响应 |
| 可观测性 | 仅 Python logging | 无结构化日志、无指标采集、无请求追踪 |
| 测试 | 零测试文件 | 无法保证重构安全性 |
| API版本 | 无版本化 | 破坏性变更无兼容策略 |

### 前端现状

**文件**：[interactive-prototype.html](file:///c:/Users/13067/Desktop/AI产品/prototypes/interactive-prototype.html)（~4600行单文件）

**已有亮点**：
- 完整交互流程：学科选择 → Agent对话 → 文件上传 → 图表生成 → CNKI检索
- 响应式设计、暗色学术主题
- CSS 设计系统（CSS变量 + 圆角/间距/阴影系统 + 过渡动画）
- localStorage 数据持久化
- Canvas 图表预览渲染
- 已连接后端 API（`API_BASE` 变量指向 `localhost:8000`）

**关键缺口**：

| 维度 | 当前状态 | 问题 |
|------|----------|------|
| 文件组织 | 单一 ~4600行 HTML | CSS/JS/HTML 全部混在一起，难以维护 |
| 模块化 | 无 ES 模块 | 全局函数污染，无导入/导出，无组件复用 |
| 状态管理 | 全局变量 + localStorage | 无集中 store，状态散布各处 |
| 构建工具 | 无 | 无打包、无压缩、无热更新、无代码分割 |
| API 交互 | 部分模拟 + 部分真实 | CNKI搜索结果用mock数据，前后端分离不彻底 |

### 依赖分析

**Python 依赖**（requirements.txt）：fastapi、uvicorn、python-multipart、matplotlib、seaborn、numpy、pandas、scipy、openpyxl、langchain、langchain-community、langgraph、aiohttp、pydantic、pydantic-settings、python-dotenv、openai、pyyaml、pypdf、python-docx

**可添加**：sqlalchemy[asyncio]、aiosqlite、alembic、structlog、httpx（测试）、pytest、pytest-asyncio

---

## Phase 1: 后端架构升级（6 层体系）

```
src/backend/
├── app.py                          # 应用工厂函数（重构）
├── config.py                       # 配置（增强：DB/Celery/Redis配置项）
│
├── middleware/                      # 🆕 中间件层
│   ├── __init__.py
│   ├── logging.py                  # 请求/响应日志 + 耗时（structlog）
│   ├── error_handler.py            # 统一异常处理 → 标准JSON错误响应
│   ├── rate_limit.py               # 令牌桶速率限制（每个session_id每分钟N次）
│   └── request_id.py               # X-Request-ID 注入与透传
│
├── core/                            # 🆕 核心基础设施
│   ├── __init__.py
│   ├── dependencies.py             # FastAPI Depends 依赖注入
│   ├── exceptions.py               # 自定义异常层次
│   ├── logging_config.py           # structlog 结构化日志配置
│   └── events.py                   # 生命周期事件管理
│
├── models/                          # 🆕 数据模型层
│   ├── __init__.py
│   ├── orm.py                      # SQLAlchemy ORM 模型（3个表）
│   ├── schemas/                    # Pydantic DTO
│   │   ├── __init__.py
│   │   ├── agent.py                # ChatRequest/ChatResponse/AgentInfo
│   │   ├── chart.py                # ChartRequest/ChartTypeInfo
│   │   ├── knowledge.py            # CNKISearchRequest/CNKIConfigRequest
│   │   ├── skills.py               # SkillCreate/Update/Toggle
│   │   └── upload.py               # FileUploadResponse/FileInfo
│   └── enums.py                    # AgentType/ChartType/SkillCategory枚举
│
├── db/                              # 🆕 数据库层
│   ├── __init__.py
│   ├── session.py                  # 异步SQLAlchemy引擎 + async_sessionmaker
│   ├── migrations/                 # Alembic迁移目录（alembic init）
│   └── repository/                 # 仓储模式
│       ├── __init__.py
│       ├── base.py                 # 泛型BaseRepository[T]
│       ├── conversation.py         # 对话仓储
│       ├── skill.py                # 技能仓储
│       └── chart.py                # 图表记录仓储
│
├── routers/                         # 路由层（已有，重构为使用 Depends）
│   ├── __init__.py
│   ├── agent.py                    # 重构：singleton → Depends
│   ├── chart.py                    # 保持不变（已较完善）
│   ├── knowledge.py                # 重构：singleton → Depends
│   ├── skills.py                   # 重构：全局service → Depends
│   └── upload.py                   # 保持不变（已较完善）
│
├── services/                        # 服务层（已有，增强）
│   ├── __init__.py
│   ├── agent_service.py            # 增强：注入 repository 替代文件读写
│   ├── chart_service.py            # 保持不变
│   ├── chart_functions.py          # 保持不变
│   ├── chart_data.py               # 保持不变
│   ├── chart_style.py              # 保持不变
│   ├── cnki_service.py             # 增强：注入 cache 工具 + circuit breaker
│   └── skills_service.py           # 增强：注入 repository 替代文件读写
│
├── tasks/                           # 🆕 后台任务层
│   ├── __init__.py
│   ├── celery_app.py               # Celery 配置（Redis broker）
│   └── chart_tasks.py              # 异步图表生成任务
│
├── utils/                           # 🆕 工具层
│   ├── __init__.py
│   ├── circuit_breaker.py          # 熔断器（保护外部API调用）
│   └── cache.py                    # 缓存装饰器（内存 + Redis可选）
│
└── tests/                           # 🆕 测试层
    ├── __init__.py
    ├── conftest.py                 # 测试夹具（async_client/test_db/mock）
    ├── test_routers/
    │   ├── __init__.py
    │   ├── test_agent.py
    │   ├── test_chart.py
    │   ├── test_upload.py
    │   ├── test_knowledge.py
    │   └── test_skills.py
    └── test_services/
        ├── __init__.py
        ├── test_agent_service.py
        ├── test_cnki_service.py
        └── test_skills_service.py
```

### 1.0 配置增强（Step 0，关键前置步骤）

**文件**：[config.py](file:///c:/Users/13067/Desktop/AI产品/src/backend/config.py)

需要新增以下字段以支持新架构：

```python
# 新增数据库配置（用于异步 SQLAlchemy ORM）
DATABASE_URL: str = "sqlite+aiosqlite:///data/scholarmind_orm.db"

# 新增 structlog 配置
LOG_LEVEL: str = "INFO"
LOG_FORMAT: str = "json"  # json | console

# 新增速率限制配置
RATE_LIMIT_REQUESTS: int = 60    # 每分钟最大请求数
RATE_LIMIT_ENABLED: bool = True

# 新增后台任务配置
TASK_BACKEND: str = "background"  # "celery" | "background"
```

**requirements.txt 新增依赖**：
```
sqlalchemy[asyncio]>=2.0
aiosqlite>=0.19.0
alembic>=1.13.0
structlog>=24.1.0
httpx>=0.27.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

### 1.1 中间件层（4个文件，~300行新增代码）

| 文件 | 行数 | 关键实现 |
|------|------|----------|
| `middleware/logging.py` | ~80 | `LoggingMiddleware(BaseHTTPMiddleware)`：dispatch 中记录 method/path/status/duration/request_id，使用 structlog 输出 JSON |
| `middleware/error_handler.py` | ~70 | `register_error_handlers(app)`：注册 `AppException`、`ValidationError`、`HTTPException`、通用 `Exception` 四种处理器，统一返回 `{"error": {"code":..., "message":..., "request_id":...}}` |
| `middleware/rate_limit.py` | ~90 | `RateLimitMiddleware`：基于 session_id 的令牌桶，默认 60次/分钟，响应头 `X-RateLimit-Remaining`/`X-RateLimit-Reset` |
| `middleware/request_id.py` | ~60 | `RequestIDMiddleware`：从 `X-Request-ID` 请求头读取或生成 UUID7，注入到响应头和 `request.state.request_id` |

### 1.2 核心基础设施层（4个文件，~200行新增代码）

| 文件 | 行数 | 关键实现 |
|------|------|----------|
| `core/dependencies.py` | ~60 | `get_db()` → async session；`get_agent_service(db)` → 注入 repository；`get_cnki_service()` → 单例；`get_skills_service(db)` → 注入 repository |
| `core/exceptions.py` | ~50 | `AppException(HTTPException)` → `NotFoundError(404)` / `ValidationError(422)` / `ExternalServiceError(502)` / `RateLimitError(429)` |
| `core/logging_config.py` | ~50 | `configure_logging()`：structlog 配置，JSON 格式输出，支持上下文绑定（request_id、session_id） |
| `core/events.py` | ~40 | **需重构**：当前使用 `add_event_handler` 模式（已弃用），需改为 `async` 函数供 `app.py` 的 `lifespan` 调用。`create_startup(app)` 返回 async callable，初始化 DB 连接池；`create_shutdown(app)` 返回 async callable，关闭 DB 连接和 CNKI session |

### 1.3 数据模型层（ORM + Schema + 枚举，~350行新增代码）

**ORM 模型**（`models/orm.py`，3个表）：

```python
# Conversation: 替代 JSON 文件
class Conversation(Base):
    __tablename__ = "conversations"
    id: int (PK, auto)
    session_id: str (indexed)
    agent_id: str
    role: str          # "user" / "assistant"
    content: Text
    created_at: datetime

# Skill: 替代 YAML 文件（预设技能也入库）
class Skill(Base):
    __tablename__ = "skills"
    id: int (PK, auto)
    skill_id: str (unique)       # "academic-researcher" 等
    display_name: str
    description: str
    category: str
    enabled: bool (default True)
    agents: JSON                  # ["researcher", "architect"]
    triggers: JSON                # ["关键词1", "关键词2"]
    rules: Text
    is_preset: bool
    created_at: datetime
    updated_at: datetime

# ChartRecord: 图表生成记录
class ChartRecord(Base):
    __tablename__ = "chart_records"
    id: int (PK, auto)
    chart_id: str (unique)       # UUID
    chart_type: str
    title: str
    filepath: str
    session_id: str (indexed)
    created_at: datetime
```

**Pydantic Schema**：将当前 router 中散落的 `BaseModel` 提取到 `models/schemas/`，按模块分文件。

**枚举**（`models/enums.py`）：
```python
class AgentType(str, Enum):
    RESEARCHER = "researcher"
    REVIEWER = "reviewer"
    ARCHITECT = "architect"
    SYNTHESIZER = "synthesizer"
    POLISHER = "polisher"

class ChartType(str, Enum):
    RIBBON = "ribbon"
    VIOLIN = "violin"
    # ... 等12种

class SkillCategory(str, Enum):
    CORE = "core"
    ADVANCED = "advanced"
    UTILITY = "utility"
    AUXILIARY = "auxiliary"
    CUSTOM = "custom"
```

### 1.4 数据库层（~350行新增代码）

| 文件 | 行数 | 关键实现 |
|------|------|----------|
| `db/session.py` | ~50 | `create_async_engine(sqlite+aiosqlite)` / `create_async_engine(postgresql+asyncpg)`，`async_sessionmaker`，`get_db()` 上下文管理器 |
| `db/migrations/` | auto | `alembic init migrations` → 配置 `env.py` 指向 ORM 模型 → `alembic revision --autogenerate -m "init"` |
| `db/repository/base.py` | ~80 | 泛型 `BaseRepository[T]`：`get_by_id()`/`list_all()`/`create()`/`update()`/`delete()`/`bulk_create()`，自动 commit/rollback |
| `db/repository/conversation.py` | ~70 | `get_by_session(session_id)` 按时间排序 / `add_message(session_id, agent_id, role, content)` / `clear_session(session_id)` / `get_recent(session_id, limit=40)` |
| `db/repository/skill.py` | ~80 | `list_enabled()` / `list_by_agent(agent_id)` / `toggle_enabled(skill_id)` / `get_by_skill_id(skill_id)` |
| `db/repository/chart.py` | ~50 | `save_record(chart_id, chart_type, title, filepath, session_id)` / `get_by_id(chart_id)` / `list_by_session(session_id)` |

### 1.5 后台任务层（~120行新增代码）

| 文件 | 行数 | 关键实现 |
|------|------|----------|
| `tasks/celery_app.py` | ~40 | `Celery("scholarmind", broker="redis://localhost:6379/0")`，配置任务路由、重试策略 |
| `tasks/chart_tasks.py` | ~80 | `generate_chart_task.delay(chart_type, data, title, ...)` → 异步生成 → 保存PNG → 更新ChartRecord → 返回chart_id（通过WebSocket或轮询通知前端） |

**降级方案**：开发环境不依赖 Redis，使用 FastAPI `BackgroundTasks` 替代 Celery（通过配置切换）。

### 1.6 工具层（~200行新增代码）

| 文件 | 行数 | 关键实现 |
|------|------|----------|
| `utils/circuit_breaker.py` | ~120 | `CircuitBreaker` 类：record_failure/success，failures≥3 → OPEN 30s → HALF_OPEN → 探测成功 → CLOSED。用于 CNKI/DeepSeek API 调用保护 |
| `utils/cache.py` | ~80 | `@cache_result(ttl=300)` 装饰器，基于 dict + TTL（内存模式）/ Redis（生产模式），支持 `cache_key` 自定义。升级 cnki_service 现有 `_cache` 字典 |

### 1.7 路由层重构

**核心变化**：将 module-level singleton 替换为 FastAPI `Depends` 注入。

**agent.py 重构前后对比**：

```python
# 之前：module-level singleton
_agent_service: Optional[AgentService] = None
def get_agent_service() -> AgentService:
    global _agent_service
    if _agent_service is None:
        _agent_service = AgentService(api_key=settings.DEEPSEEK_API_KEY, ...)
    return _agent_service

@router.post("/chat")
async def chat_with_agent(request: ChatRequest):
    service = get_agent_service()  # 手动获取
    result = await service.chat(...)
    ...

# 之后：FastAPI Depends
from ..core.dependencies import get_agent_service

@router.post("/chat")
async def chat_with_agent(
    request: ChatRequest,
    service: AgentService = Depends(get_agent_service),  # DI
):
    result = await service.chat(...)
    ...
```

**app.py 重构为工厂函数**：

```python
def create_app() -> FastAPI:
    app = FastAPI(title="ScholarMind API", version="2.0.0")
    
    # 配置结构化日志
    configure_logging()
    
    # 注册中间件（按优先级顺序）
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(CORSMiddleware, ...)
    
    # 注册异常处理器
    register_error_handlers(app)
    
    # 生命周期事件
    app.add_event_handler("startup", create_startup_handler(app))
    app.add_event_handler("shutdown", create_shutdown_handler(app))
    
    # 注册路由
    app.include_router(chart.router)
    app.include_router(upload.router)
    app.include_router(skills.router)
    app.include_router(knowledge.router)
    app.include_router(agent.router)
    
    return app

app = create_app()
```

### 1.8 服务层增强

**agent_service.py 关键修改**：
- 构造函数变为 `__init__(self, client: AsyncOpenAI, model: str, conversation_repo: ConversationRepository)`
- `_load_all_conversations()` → 替换为 `await conversation_repo.get_by_session(session_id)`
- `_save_conversation()` → 替换为 `await conversation_repo.add_message(...)`
- 移除 `self.conversations` 内存 dict，改为每次从 DB 读取

**cnki_service.py 关键修改**：
- 注入 `CacheManager` 替代 `self._cache` 字典
- 注入 `CircuitBreaker` 保护外部 API 调用

**skills_service.py 关键修改**：
- 注入 `SkillRepository` 替代 YAML 文件读写
- `list_all()` → `await skill_repo.list_all()`
- `create_skill()` / `update_skill()` / `delete_skill()` → 通过 repository

### 1.9 测试层（~300行新增代码）

| 文件 | 行数 | 关键实现 |
|------|------|----------|
| `tests/conftest.py` | ~60 | `async_client`（httpx.AsyncClient + lifespan）、`test_db`（内存SQLite + 自动建表）、`mock_deepseek`（monkeypatch AsyncOpenAI） |
| `tests/test_routers/test_agent.py` | ~60 | 测试：正常对话、无效agent_id、空消息、对话历史 |
| `tests/test_routers/test_chart.py` | ~50 | 测试：12种图表生成、无效chart_type、尺寸边界值 |
| `tests/test_routers/test_upload.py` | ~40 | 测试：单文件上传、多文件上传、超限、不支持的类型 |
| `tests/test_routers/test_knowledge.py` | ~30 | 测试：CNKI搜索、状态检查、配置更新 |
| `tests/test_routers/test_skills.py` | ~40 | 测试：CRUD、toggle、预设技能不可删 |
| `tests/test_services/test_agent_service.py` | ~50 | 测试：prompt构建（含context注入、技能注入）、选项解析、技能检测 |
| `tests/test_services/test_cnki_service.py` | ~40 | 测试：缓存命中、多级降级、HTML解析 |
| `tests/test_services/test_skills_service.py` | ~30 | 测试：预设技能不可删、自定义技能CRUD |

---

## Phase 2: 前端架构升级

### 目标

从「单文件 ~4600 行 SPA」升级为「模块化组件架构 + Vite 构建」，不引入 React/Vue，保持原生 JavaScript。

```
src/frontend/
├── index.html                      # Vite 入口（引用 main.js）
├── package.json                    # 依赖：vite, eslint, prettier
├── vite.config.js                  # Vite 配置 + dev proxy + 构建优化
│
├── public/                         # 静态资源
│   └── favicon.ico
│
├── src/
│   ├── main.js                     # 应用入口
│   │
│   ├── app/                        # 🆕 应用核心
│   │   ├── App.js                  # 根组件：page容器 + 路由切换监听
│   │   ├── store.js                # 集中状态管理（reactive Proxy store）
│   │   ├── router.js               # Hash 路由系统
│   │   └── i18n.js                 # 国际化预留
│   │
│   ├── components/                 # 🆕 可复用组件（11个）
│   │   ├── TopNav.js               # 顶部导航栏
│   │   ├── AgentSidebar.js         # Agent 侧边栏
│   │   ├── Breadcrumb.js           # 面包屑导航
│   │   ├── ChatBubble.js           # 聊天气泡（文本/图表/CNKI/选项按钮）
│   │   ├── ChatInput.js            # 输入框 + 文件/图表/CNKI按钮
│   │   ├── FileUploadPanel.js      # 文件上传面板（拖拽+多选）
│   │   ├── ChartDialog.js          # 图表配置对话框
│   │   ├── CNKIDialog.js           # CNKI 检索对话框
│   │   ├── SkillManager.js         # 技能管理面板
│   │   ├── SettingsPanel.js        # 设置面板
│   │   ├── Toast.js                # Toast 通知
│   │   └── Modal.js                # 通用模态框
│   │
│   ├── pages/                      # 🆕 页面组件（6个）
│   │   ├── HomePage.js             # 首页（学科选择）
│   │   ├── DisciplinePage.js       # 学科选择页（工科/理科/人文社科）
│   │   ├── ResearchTypePage.js     # 研究类型选择
│   │   ├── ReadinessPage.js        # 准备度选择
│   │   ├── AgentPage.js            # Agent 对话页（通用，接收 agent-id）
│   │   └── SettingsPage.js         # 设置页
│   │
│   ├── services/                   # 🆕 API 服务层
│   │   ├── api.js                  # HTTP 客户端（fetch + 拦截器 + 错误处理 + 重试）
│   │   ├── agentApi.js             # Agent 对话 API
│   │   ├── chartApi.js             # 图表生成 API
│   │   ├── cnkiApi.js              # CNKI 检索 API
│   │   ├── skillsApi.js            # 技能 CRUD API
│   │   └── uploadApi.js            # 文件上传 API
│   │
│   ├── styles/                     # 🆕 样式系统（从 prototype CSS 拆分）
│   │   ├── variables.css           # CSS 变量（从 :root 迁移）
│   │   ├── base.css                # 基础重置 + 排版 + 滚动条
│   │   ├── layout.css              # 布局（top-nav, sidebar, page）
│   │   ├── components.css          # 所有组件样式
│   │   ├── pages.css               # 页面特有样式
│   │   └── themes.css              # 主题变量（暗色主题）
│   │
│   └── utils/                      # 🆕 工具函数
│       ├── storage.js              # localStorage 封装（get/set/remove + JSON序列化）
│       ├── dom.js                  # DOM 工具（createElement with attrs, delegate）
│       └── constants.js            # 常量（agent列表、chartTypes、学科/类型选项）
│
└── tests/                          # 前端测试（预留，可选）
    └── ...
```

### 2.1 组件模式（工厂函数 + 事件委托）

每个组件导出工厂函数，接收 props，返回 DOM 元素：

```javascript
// components/ChatBubble.js
export function ChatBubble({ role, content, type, options = [], onOptionClick }) {
  const el = document.createElement('div');
  el.className = `chat-bubble chat-bubble-${role}`;
  
  if (type === 'chart') {
    el.classList.add('chart-bubble');
    el.innerHTML = renderChartContent(content);  // img + caption + actions
  } else if (type === 'cnki') {
    el.classList.add('cnki-chat-bubble');
    el.innerHTML = renderCNKIContent(content);    // 文献卡片列表
  } else {
    el.innerHTML = renderTextContent(content);    // markdown → HTML
  }
  
  // 选项按钮
  if (options.length > 0) {
    const optsDiv = document.createElement('div');
    optsDiv.className = 'chat-options';
    options.forEach((opt, i) => {
      const btn = document.createElement('button');
      btn.className = 'chat-option-btn';
      btn.textContent = opt;
      btn.addEventListener('click', () => onOptionClick?.(opt, i));
      optsDiv.appendChild(btn);
    });
    el.appendChild(optsDiv);
  }
  
  return el;
}
```

### 2.2 状态管理（store.js）

基于 Proxy 的响应式集中状态：

```javascript
// app/store.js
export function createStore(initialState) {
  const listeners = new Map();  // key → Set<callback>
  
  const state = new Proxy({ ...initialState }, {
    set(target, key, value) {
      target[key] = value;
      notify(key, value);
      return true;
    }
  });
  
  function notify(key, value) {
    const cbs = listeners.get(key);
    if (cbs) cbs.forEach(cb => cb(value));
  }
  
  return {
    state,
    watch(key, callback) {
      if (!listeners.has(key)) listeners.set(key, new Set());
      listeners.get(key).add(callback);
      return () => listeners.get(key).delete(callback);  // 返回取消订阅
    },
  };
}

// 初始状态（从 localStorage 恢复）
export const { state, watch } = createStore({
  currentPage: 'homepage',
  discipline: localStorage.getItem('sm_discipline') || null,
  researchType: localStorage.getItem('sm_researchType') || null,
  readiness: localStorage.getItem('sm_readiness') || null,
  uploadedFiles: JSON.parse(localStorage.getItem('sm_uploads') || '{}'),
  currentSessionId: localStorage.getItem('sm_sessionId') || '',
  cnkiResults: [],
  skills: [],
  settings: {
    theme: localStorage.getItem('sm_theme') || 'dark',
    apiBase: localStorage.getItem('sm_apiBase') || 'http://localhost:8000',
  },
});

// 持久化关键状态到 localStorage
watch('discipline', v => localStorage.setItem('sm_discipline', v));
watch('researchType', v => localStorage.setItem('sm_researchType', v));
watch('readiness', v => localStorage.setItem('sm_readiness', v));
watch('settings', v => localStorage.setItem('sm_theme', v.theme));
```

### 2.3 路由系统（router.js）

```javascript
// app/router.js
import { state } from './store.js';
import { HomePage } from '../pages/HomePage.js';
import { AgentPage } from '../pages/AgentPage.js';
import { SettingsPage } from '../pages/SettingsPage.js';
// ... 其他页面

const routes = {
  'homepage':       { title: 'ScholarMind',       render: HomePage },
  'engineering':    { title: '工科 · 研究类型',     render: ResearchTypePage, props: { discipline: 'engineering' } },
  'science':        { title: '理科 · 研究类型',     render: ResearchTypePage, props: { discipline: 'science' } },
  'humanities':     { title: '人文社科 · 研究类型',  render: ResearchTypePage, props: { discipline: 'humanities' } },
  'readiness':      { title: '研究准备度',          render: ReadinessPage },
  'researcher':     { title: '研究员对话',          render: AgentPage, props: { agentId: 'researcher' } },
  'reviewer':       { title: '审查员对话',          render: AgentPage, props: { agentId: 'reviewer' } },
  'architect':      { title: '架构师对话',          render: AgentPage, props: { agentId: 'architect' } },
  'synthesizer':    { title: '综述员对话',          render: AgentPage, props: { agentId: 'synthesizer' } },
  'polisher':       { title: '润色员对话',          render: AgentPage, props: { agentId: 'polisher' } },
  'custom-agent':   { title: '自定义Agent',        render: AgentPage, props: { agentId: 'custom' } },
  'settings':       { title: '设置',               render: SettingsPage },
};

export function navigateTo(pageId, extraState = {}) {
  state.currentPage = pageId;
  Object.assign(state, extraState);
  window.location.hash = pageId;
}

export function initRouter(container) {
  function renderPage(pageId) {
    const route = routes[pageId] || routes['homepage'];
    document.title = route.title + ' - ScholarMind';
    container.innerHTML = '';
    container.appendChild(route.render(route.props || {}));
  }
  
  // 初始渲染
  const initPage = window.location.hash.slice(1) || 'homepage';
  renderPage(initPage);
  
  // 监听 hash 变化
  window.addEventListener('hashchange', () => {
    const pageId = window.location.hash.slice(1) || 'homepage';
    renderPage(pageId);
  });
  
  // 监听 store 变化（跨组件导航）
  watch('currentPage', renderPage);
}
```

### 2.4 API 服务层（api.js + 6个模块）

```javascript
// services/api.js
import { state } from '../app/store.js';

const BASE_URL = () => state.settings.apiBase;

async function request(method, path, body = null) {
  const url = `${BASE_URL()}${path}`;
  const options = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body) options.body = JSON.stringify(body);
  
  const res = await fetch(url, options);
  
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, err.detail || err.error?.message || '请求失败');
  }
  
  // 处理非 JSON 响应（如图表图片）
  const ct = res.headers.get('content-type');
  if (ct && ct.includes('image')) {
    return { blob: await res.blob(), headers: res.headers };
  }
  
  return res.json();
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body) => request('POST', path, body),
  delete: (path) => request('DELETE', path),
};

// services/agentApi.js
import { api } from './api.js';
export const agentApi = {
  chat: (message, agentId, sessionId, context) =>
    api.post('/api/agent/chat', { message, agent_id: agentId, session_id: sessionId, context }),
  getConversation: (sessionId) =>
    api.get(`/api/agent/conversation/${sessionId}`),
  clearConversation: (sessionId) =>
    api.delete(`/api/agent/conversation/${sessionId}`),
  listAgents: () => api.get('/api/agent/agents'),
};
```

### 2.5 Vite 构建配置

```javascript
// vite.config.js
import { defineConfig } from 'vite';

export default defineConfig({
  root: 'src/frontend',
  build: {
    outDir: '../../dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          pages: ['./src/pages/HomePage.js', './src/pages/AgentPage.js'],
        },
      },
    },
    minify: 'terser',
    cssMinify: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
```

### 2.6 CSS 迁移策略

从 `interactive-prototype.html` 的 `<style>` 中拆分：
- `:root` 变量 → `styles/variables.css`
- 基础样式（reset、body、a、button、input） → `styles/base.css`
- 布局样式（.top-nav、.page、.sidebar） → `styles/layout.css`
- 组件样式（导航按钮、聊天气泡、对话框、Toast等） → `styles/components.css`
- 页面特有样式 → `styles/pages.css`
- 主题切换预留 → `styles/themes.css`

### 2.7 页面组件示例

```javascript
// pages/AgentPage.js
import { state, watch } from '../app/store.js';
import { TopNav } from '../components/TopNav.js';
import { AgentSidebar } from '../components/AgentSidebar.js';
import { ChatBubble } from '../components/ChatBubble.js';
import { ChatInput } from '../components/ChatInput.js';
import { agentApi } from '../services/agentApi.js';
import { showToast } from '../components/Toast.js';

const AGENT_NAMES = {
  researcher: { name: '研究员', icon: '🔬', desc: '学术选题与问题建构专家' },
  reviewer: { name: '审查员', icon: '📋', desc: '研究思路审查与优化专家' },
  architect: { name: '架构师', icon: '🏗️', desc: '论文架构审查与优化专家' },
  synthesizer: { name: '综述员', icon: '📚', desc: '文献综述撰写专家' },
  polisher: { name: '润色员', icon: '✨', desc: '学术语言润色与AIGC降重专家' },
};

export function AgentPage({ agentId }) {
  const page = document.createElement('div');
  page.id = agentId;
  page.className = 'page agent-page active';
  
  const agent = AGENT_NAMES[agentId] || { name: agentId, icon: '🤖' };
  
  // 构建布局
  page.innerHTML = `
    <div class="agent-layout">
      <div class="agent-main">
        <div class="chat-header">
          <span class="chat-header-icon">${agent.icon}</span>
          <div>
            <h2>${agent.name}</h2>
            <p class="chat-header-desc">${agent.desc}</p>
          </div>
        </div>
        <div class="chat-messages" id="${agentId}-messages"></div>
        <div class="chat-input-area" id="${agentId}-input"></div>
      </div>
      <div class="agent-sidebar" id="${agentId}-sidebar"></div>
    </div>
  `;
  
  // 挂载子组件
  const messagesContainer = page.querySelector(`#${agentId}-messages`);
  const inputContainer = page.querySelector(`#${agentId}-input`);
  const sidebarContainer = page.querySelector(`#${agentId}-sidebar`);
  
  inputContainer.appendChild(ChatInput({
    placeholder: `向${agent.name}提问...`,
    onSend: async (message) => {
      // 添加用户气泡
      messagesContainer.appendChild(ChatBubble({ role: 'user', content: message }));
      
      // 添加加载动画
      const loadingBubble = ChatBubble({ role: 'ai', content: '', type: 'loading' });
      messagesContainer.appendChild(loadingBubble);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
      
      try {
        const result = await agentApi.chat(message, agentId, state.currentSessionId, {
          discipline: state.discipline,
          research_type: state.researchType,
          readiness: state.readiness,
        });
        
        loadingBubble.remove();
        
        // 添加 AI 回复气泡
        messagesContainer.appendChild(ChatBubble({
          role: 'ai',
          content: result.reply,
          options: result.options,
          onOptionClick: (opt) => inputContainer.querySelector('textarea').value = opt,
        }));
        
        // 如果有图表信息
        if (result.chart_info) {
          // 渲染图表卡片
        }
        
        // 如果有 CNKI 结果
        if (result.cnki_results) {
          messagesContainer.appendChild(ChatBubble({
            role: 'ai', content: result.cnki_results, type: 'cnki'
          }));
        }
      } catch (err) {
        loadingBubble.remove();
        showToast('对话失败：' + err.message, 'error');
      }
      
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    },
  }));
  
  sidebarContainer.appendChild(AgentSidebar({ agentId }));
  
  return page;
}
```

---

## 实施顺序（已根据依赖链修正）

```
Phase 1: 后端架构升级（严格按依赖链顺序，不可并行）
  ├── Step 0: 修复 config.py（增加 database_url 等缺失字段 + structlog/sqlalchemy 依赖）
  ├── Step 1: 数据库层优先（session.py → repository/base.py → repository/具体仓储）
  ├── Step 2: 核心基础设施（修复 events.py → 新建 dependencies.py）
  ├── Step 3: 工具层（cache.py → circuit_breaker.py）
  ├── Step 4: 中间件层（request_id.py → logging.py → error_handler.py → rate_limit.py）
  ├── Step 5: 数据模型层（enums.py → schemas/ → orm.py → Alembic 迁移）
  ├── Step 6: 重构 app.py 为工厂函数（引入 lifespan + 中间件 + 异常处理器）
  ├── Step 7: 重构 routers 为 Depends 注入
  ├── Step 8: 重构 services 注入 repository
  ├── Step 9: 后台任务层（celery_app.py → chart_tasks.py）
  └── Step 10: 测试层（conftest.py → routers测试 → services测试）

Phase 2: 前端架构升级（与 Phase 1 可并行）
  ├── Step 11: 初始化 Vite 项目（package.json + vite.config.js + index.html）
  ├── Step 12: 拆分 CSS（variables.css → base.css → layout.css → components.css → pages.css）
  ├── Step 13: 创建工具函数（storage.js → dom.js → constants.js）
  ├── Step 14: 创建核心模块（store.js → router.js → main.js → App.js）
  ├── Step 15: 创建 API 服务层（api.js → agentApi.js → chartApi.js → cnkiApi.js → skillsApi.js → uploadApi.js）
  ├── Step 16: 迁移组件（Toast → Modal → TopNav → Breadcrumb → ChatBubble → ChatInput → AgentSidebar → FileUploadPanel → ChartDialog → CNKIDialog → SkillManager → SettingsPanel）
  └── Step 17: 迁移页面（HomePage → DisciplinePage → ResearchTypePage → ReadinessPage → AgentPage → SettingsPage）

Phase 1 和 Phase 2 可并行进行。
```

---

## 关键依赖问题解决方案

### 问题 1-2：`core/events.py` 依赖链断裂

**问题**：[events.py](file:///c:/Users/13067/Desktop/AI产品/src/backend/core/events.py) 第 10 行导入了 `from ..db.session import create_async_engine, create_async_sessionmaker`，第 39 行引用了 `settings.database_url`，两者均不存在。

**解决**：在执行 Step 5 之前，将 `core/events.py` 改为延迟导入模式，或按正确的依赖顺序构建：

```
正确的构建顺序（严格依赖链）：
  config.py（增加 database_url 字段）
    → db/session.py（异步引擎 + 会话工厂）
      → core/events.py（引用 db.session）
      → core/dependencies.py（引用 db.session + repository）
        → middleware/（引用 core.exceptions）
        → routers/（引用 core.dependencies）
          → app.py（工厂函数组装全部）
```

### 问题 3：`app.py` lifespan vs events.py 冲突

**问题**：当前 [app.py](file:///c:/Users/13067/Desktop/AI产品/src/backend/app.py) 使用 `@asynccontextmanager lifespan`，而 `core/events.py` 使用 `add_event_handler("startup"/"shutdown")`。FastAPI 推荐使用 lifespan（新版）而非弃用的 `add_event_handler`。

**解决**：重构 `core/events.py`，将其改造成 lifespan 兼容模式：
- 将 `create_startup_handler` / `create_shutdown_handler` 改为返回 async functions
- 在 `app.py` 的 lifespan 中调用它们

### 问题 4：现有服务迁移策略

**解决**：新建的 ORM 层（Conversation/Skill/ChartRecord）与现有 DatabaseService（academic_resources/crawl_logs/hot_keywords）并存，互不冲突：
- 新版 ORM 管理：对话历史、技能配置、图表记录
- 旧版 DatabaseService 继续管理：爬取资源、爬取日志、热搜词
- VectorService（ChromaDB）保持不变

---

## 假设与决策

1. **数据库选型**：开发阶段用 SQLite + aiosqlite（零配置），生产阶段切换 PostgreSQL + asyncpg（通过修改 `db/session.py` 的连接字符串即可，代码无需改动）
2. **任务队列**：生产用 Celery + Redis；开发阶段提供 `BackgroundTasks` 降级模式（配置切换）
3. **前端框架**：保持原生 JavaScript，不引入 React/Vue（匹配当前技术栈），采用工厂函数 + 事件委托 + Proxy 响应式模式
4. **API 协议**：前后端 REST JSON 通信，图表等二进制通过 Blob URL 返回
5. **TypeScript**：暂不引入（复杂度增加但用户未要求），保持 JS + JSDoc 注释
6. **包管理器**：npm（匹配项目现有风格）
7. **预设技能数据迁移**：8个预设技能从 `skills_service.py` 硬编码 → 数据库 seeder 脚本初始化
8. **向后兼容**：API 路径保持不变（`/api/agent/chat` 等），确保前端渐进迁移
9. **生产后端目录**：`src/backend/` 保持不变，dist 输出到 `src/frontend/dist/`
10. **双重数据库并存**：新版 ORM（对话/技能/图表）+ 旧版 DatabaseService（爬取资源/日志/热词）同时运行，互不干扰
11. **Lifespan 模式**：使用 FastAPI 推荐的 `@asynccontextmanager lifespan` 模式，不采用已弃用的 `add_event_handler`

---

## 验证步骤

### 后端验证
1. `cd src/backend && python -m pytest tests/ -v` → 所有测试通过
2. `uvicorn src.backend.app:app --reload` → 启动无报错
3. 访问 `/api/health` → 返回 `{"status":"ok","version":"2.0.0"}`
4. 检查响应头：`X-Request-ID`、`X-RateLimit-Remaining` 存在
5. 发送无效 agent_id → 返回 `{"error":{"code":"VALIDATION_ERROR","message":"..."}}`
6. 连续快速请求 → 触发 429 `{"error":{"code":"RATE_LIMIT","message":"..."}}`
7. `alembic upgrade head` → SQLite 表创建成功
8. `POST /api/agent/chat` → 对话写入 DB → `GET /api/agent/conversation/{id}` 返回历史

### 前端验证
1. `cd src/frontend && npm install && npm run dev` → Vite 启动 `localhost:5173`
2. 页面路由：点击导航 → Hash 变化 → 对应页面组件渲染（UI 与现有 prototype 一致）
3. 组件隔离：修改 ChatBubble 样式 → 仅气泡变化，不影响 TopNav
4. 状态管理：选择学科 → store.discipline 更新 → localStorage 持久化 → 刷新页面状态保留
5. API 集成：发送对话 → 真实 HTTP 请求到 `localhost:8000/api/agent/chat` → 展示回复
6. 热更新：修改 CSS/JS → 浏览器自动刷新
7. `npm run build` → `dist/` 生成压缩后的静态文件 → 可部署到 FastAPI StaticFiles

---

## 文件变更汇总

| 操作 | 数量 | 说明 |
|------|------|------|
| 新增目录 | 8 | middleware/ core/ models/ db/ tasks/ utils/ tests/ src/frontend/ |
| 新增Python文件 | 22 | 中间件4 + 核心4 + 模型5 + DB4 + 任务2 + 工具2 + 测试11 |
| 新增前端文件 | 30 | HTML1 + JS配置2 + 核心4 + 组件11 + 页面6 + 服务5 + 样式5 + 工具3 |
| 修改Python文件 | 8 | app.py + config.py + 5个router + 3个service |
| 修改前端文件 | 0 | 保留 interactive-prototype.html 作为参考 |
| 总计新增代码 | ~3000行 | 后端~1800行 + 前端~1200行 |