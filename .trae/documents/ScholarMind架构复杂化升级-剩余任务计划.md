# ScholarMind 架构复杂化升级 — 剩余任务计划

## 状态总览（2026-06-11 实测）

### 后端：6层架构已基本完成，仅剩服务层改造 + Alembic迁移

| 层级 | 完成度 | 备注 |
|------|--------|------|
| 配置层 (config.py) | ✅ 100% | DATABASE_URL、LOG_LEVEL、RATE_LIMIT等全部已添加 |
| 数据库层 (db/) | ✅ 100% | session.py + 3个repository全部实现 |
| 中间件层 (middleware/) | ✅ 100% | 4个中间件全部实现 |
| 核心基础设施 (core/) | ✅ 100% | dependencies/exceptions/events/logging全部实现 |
| 数据模型层 (models/) | ✅ 100% | ORM(3表) + enums + 5个schema文件 |
| 工具层 (utils/) | ✅ 100% | CacheManager + CircuitBreaker |
| 后台任务层 (tasks/) | ✅ 100% | Celery + BackgroundTasks降级 |
| 测试层 (tests/) | ✅ 100% | conftest + 5个router测试 + 3个service测试 |
| 应用入口 (app.py) | ✅ 100% | 工厂函数 + lifespan + 中间件 + 异常处理器 |
| 路由层 (routers/) | ✅ 100% | 5个router全部重构为Depends注入 |
| **服务层 (services/)** | ⚠️ 60% | **agent_service/cnki_service未注入repository** |
| **Alembic迁移 (db/migrations/)** | ❌ 0% | **未初始化** |

### 前端：尚未开始

| 层级 | 完成度 | 备注 |
|------|--------|------|
| Vite项目初始化 | ❌ 0% | src/frontend/目录不存在 |
| CSS拆分 | ❌ 0% | 仍在prototype.html单文件中 |
| 工具函数 | ❌ 0% | |
| 核心模块 | ❌ 0% | |
| API服务层 | ❌ 0% | |
| 组件迁移 | ❌ 0% | |
| 页面迁移 | ❌ 0% | |

---

## 剩余任务清单

### 任务1：重构 services 注入 repository（后端）

**目标**：让服务层通过构造函数注入仓储，彻底消除文件读写和内部字典缓存。

#### 1.1 agent_service.py 改造

**当前问题**：
- `__init__` 只接受 `api_key, base_url, model`，不接受 `ConversationRepository`
- 使用 `self.conversations: dict` 内存字典 + `_load_all_conversations()` / `_save_conversation()` 文件读写
- `CONVERSATIONS_DIR = Path("data/conversations")` 硬编码路径

**改造方案**：
```python
class AgentService:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        conversation_repo: ConversationRepository | None = None,  # 新增
        skills_service: SkillsService | None = None,               # 新增
    ):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.conversation_repo = conversation_repo
        self.skills_service = skills_service or SkillsService()
        # 移除：self.conversations = {}
        # 移除：self._load_all_conversations()
```

**关键方法改造**：
- `chat()` 中的 `self._get_history(session_id)` → 改为 `await self.conversation_repo.get_by_session(session_id)`
- `chat()` 中的 `self._save_conversation()` → 改为 `await self.conversation_repo.add_message(...)`
- `clear_conversation()` → 改为 `await self.conversation_repo.clear_session(session_id)`
- `get_conversation_history()` → 改为 `await self.conversation_repo.get_by_session(session_id)`
- 移除 `_load_all_conversations()`, `_save_conversation()`, `_get_history()` 方法

**向后兼容**：当 `conversation_repo=None` 时，回退到原有的文件存储模式（保留现有代码作为 fallback）。

#### 1.2 cnki_service.py 改造

**当前问题**：
- 使用 `self._cache: dict` 手动管理缓存
- 无熔断器保护

**改造方案**：
```python
from ..utils.cache import CacheManager
from ..utils.circuit_breaker import CircuitBreaker

class CNKIService:
    def __init__(
        self,
        cache: CacheManager | None = None,          # 新增
        circuit_breaker: CircuitBreaker | None = None,  # 新增
    ):
        self.cache = cache or CacheManager(default_ttl=1800)
        self.circuit_breaker = circuit_breaker
        # 移除：self._cache = {}
        # 移除：self._cache_ttl = 1800
```

**关键方法改造**：
- `search()` 方法中，用 `self.cache.get(cache_key)` / `self.cache.set(cache_key, results)` 替换手动缓存管理
- `search()` 方法中，如果 `self.circuit_breaker` 存在，用 `async with self.circuit_breaker:` 包裹外部API调用

#### 1.3 skills_service.py 改造（已完成大部分）

**当前状态**：已支持可选的 `repository` 参数，但 `list_all()` 等方法在无 DB 时仍回退到文件模式。

**需确认**：当前 `dependencies.py` 中的 `get_skills_service` 在无 DB 时会回退到文件模式，这是正确的向后兼容设计。无需额外改造。

#### 1.4 更新 dependencies.py

修改 `get_agent_service` 依赖，注入 `ConversationRepository`：

```python
async def get_agent_service(request: Request, db: AsyncSession = Depends(get_db)):
    if not hasattr(request.app.state, "agent_service"):
        conversation_repo = ConversationRepository(db)
        skills_service = SkillsService(repository=SkillRepository(db))
        request.app.state.agent_service = AgentService(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            model=settings.DEEPSEEK_MODEL,
            conversation_repo=conversation_repo,
            skills_service=skills_service,
        )
    return request.app.state.agent_service
```

同理更新 `get_cnki_service`，注入 `CacheManager` 和 `CircuitBreaker`。

---

### 任务2：初始化 Alembic 数据库迁移

**目标**：用 Alembic 管理数据库 schema 变更，替代 `init_db()` 的 `create_all` 方式。

**步骤**：
1. 在 `src/backend/` 目录下运行 `alembic init db/migrations`
2. 修改 `db/migrations/env.py`：
   - 导入 `Base` 和所有 ORM 模型
   - 设置 `target_metadata = Base.metadata`
   - 配置 `sqlalchemy.url` 从 `settings.DATABASE_URL` 读取
3. 修改 `alembic.ini`，设置 `sqlalchemy.url`
4. 运行 `alembic revision --autogenerate -m "init"` 生成初始迁移
5. 修改 `core/events.py` 的 `startup()`，开发环境改用 `alembic upgrade head` 替代 `Base.metadata.create_all`

---

### 任务3：前端架构升级（Vite + 模块化组件）

**目标**：将 `prototypes/interactive-prototype.html`（~4600行单文件）拆分为模块化架构。

#### 3.1 初始化 Vite 项目

创建 `src/frontend/` 目录结构：

```
src/frontend/
├── index.html
├── package.json
├── vite.config.js
├── public/
│   └── favicon.ico
└── src/
    ├── main.js
    ├── app/
    │   ├── App.js
    │   ├── store.js
    │   └── router.js
    ├── components/
    │   ├── TopNav.js
    │   ├── AgentSidebar.js
    │   ├── Breadcrumb.js
    │   ├── ChatBubble.js
    │   ├── ChatInput.js
    │   ├── FileUploadPanel.js
    │   ├── ChartDialog.js
    │   ├── CNKIDialog.js
    │   ├── SkillManager.js
    │   ├── SettingsPanel.js
    │   ├── Toast.js
    │   └── Modal.js
    ├── pages/
    │   ├── HomePage.js
    │   ├── DisciplinePage.js
    │   ├── ResearchTypePage.js
    │   ├── ReadinessPage.js
    │   ├── AgentPage.js
    │   └── SettingsPage.js
    ├── services/
    │   ├── api.js
    │   ├── agentApi.js
    │   ├── chartApi.js
    │   ├── cnkiApi.js
    │   ├── skillsApi.js
    │   └── uploadApi.js
    ├── styles/
    │   ├── variables.css
    │   ├── base.css
    │   ├── layout.css
    │   ├── components.css
    │   └── pages.css
    └── utils/
        ├── storage.js
        ├── dom.js
        └── constants.js
```

**package.json** 依赖：
```json
{
  "name": "scholarmind-frontend",
  "version": "2.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "devDependencies": {
    "vite": "^5.4.0"
  }
}
```

**vite.config.js**：
```javascript
import { defineConfig } from 'vite';

export default defineConfig({
  root: 'src/frontend',
  build: {
    outDir: '../../dist',
    emptyOutDir: true,
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

#### 3.2 CSS 拆分

从 `interactive-prototype.html` 的 `<style>` 标签中提取：
- `:root` 变量 → `styles/variables.css`
- reset/base/排版/滚动条 → `styles/base.css`
- 布局（top-nav, sidebar, page容器） → `styles/layout.css`
- 所有组件样式 → `styles/components.css`
- 页面特有样式 → `styles/pages.css`

各文件通过 `@import` 在 `main.js` 中导入，或直接在 `index.html` 中 link。

#### 3.3 工具函数

- `storage.js`：localStorage 封装（get/set/remove + JSON 序列化/反序列化）
- `dom.js`：DOM 工具（`createElement` with attrs/classes, `delegate` 事件委托）
- `constants.js`：Agent 列表、图表类型、学科/研究类型/准备度选项等常量

#### 3.4 核心模块

- `store.js`：基于 Proxy 的响应式集中状态管理，支持 `watch()` 订阅和 localStorage 持久化
- `router.js`：Hash 路由系统，定义 12 个路由映射，监听 `hashchange` 和 store 变化
- `App.js`：根组件，负责页面容器 + 路由切换 + 全局布局（TopNav）
- `main.js`：应用入口，初始化 store/router/App

#### 3.5 API 服务层

- `api.js`：HTTP 客户端（fetch 封装 + 拦截器 + 统一错误处理 + 请求头注入）
- `agentApi.js`：Agent 对话 API（chat/getConversation/clearConversation/listAgents）
- `chartApi.js`：图表生成 API（generate/getTypes/getChart）
- `cnkiApi.js`：CNKI 检索 API（search/status/config）
- `skillsApi.js`：技能 CRUD API（list/get/create/update/delete/toggle/upload/template）
- `uploadApi.js`：文件上传 API（upload/list/content/delete）

#### 3.6 组件迁移（工厂函数模式）

每个组件导出工厂函数，接收 props 对象，返回 DOM 元素。组件模式：
```javascript
export function ComponentName({ prop1, prop2, onEvent }) {
  const el = document.createElement('div');
  el.className = 'component-class';
  // ... 构建 DOM
  return el;
}
```

组件迁移顺序（按依赖关系）：
1. `Toast.js`（无依赖，全局使用）
2. `Modal.js`（无依赖，被多个对话框使用）
3. `TopNav.js`（依赖 store）
4. `Breadcrumb.js`（依赖 store）
5. `ChatBubble.js`（纯视图，支持 text/chart/cnki/options 四种类型）
6. `ChatInput.js`（依赖 store，触发 onSend）
7. `AgentSidebar.js`（依赖 store）
8. `FileUploadPanel.js`（依赖 uploadApi）
9. `ChartDialog.js`（依赖 chartApi + Modal）
10. `CNKIDialog.js`（依赖 cnkiApi + Modal）
11. `SkillManager.js`（依赖 skillsApi + Modal）
12. `SettingsPanel.js`（依赖 store）

#### 3.7 页面迁移

每个页面导出工厂函数，接收 props（如 `{ agentId }`），返回完整的页面 DOM 元素：

1. `HomePage.js`：首页（学科选择卡片）
2. `DisciplinePage.js`：学科选择页（接收 `discipline` prop）
3. `ResearchTypePage.js`：研究类型选择
4. `ReadinessPage.js`：准备度选择
5. `AgentPage.js`：Agent 对话页（接收 `agentId` prop，组合 ChatBubble/ChatInput/AgentSidebar）
6. `SettingsPage.js`：设置页（组合 SettingsPanel）

---

## 实施顺序

```
Phase 1: 后端收尾
  ├── 任务1.1: 改造 agent_service.py（注入 ConversationRepository + SkillsService）
  ├── 任务1.2: 改造 cnki_service.py（注入 CacheManager + CircuitBreaker）
  ├── 任务1.4: 更新 dependencies.py（注入 repository）
  └── 任务2: 初始化 Alembic 迁移

Phase 2: 前端架构升级（与 Phase 1 可并行）
  ├── 任务3.1: 初始化 Vite 项目（package.json + vite.config.js + index.html）
  ├── 任务3.3: 创建工具函数（storage.js → dom.js → constants.js）
  ├── 任务3.2: 拆分 CSS（variables.css → base.css → layout.css → components.css → pages.css）
  ├── 任务3.4: 创建核心模块（store.js → router.js → main.js → App.js）
  ├── 任务3.5: 创建 API 服务层（api.js → 5个API模块）
  ├── 任务3.6: 迁移组件（12个组件，按依赖顺序）
  └── 任务3.7: 迁移页面（6个页面）
```

---

## 验证步骤

### 后端验证
1. `cd src/backend && python -m pytest tests/ -v` → 所有测试通过
2. `uvicorn src.backend.app:app --reload` → 启动无报错
3. `POST /api/agent/chat` → 对话写入 ORM DB → `GET /api/agent/conversation/{id}` 返回历史
4. `alembic upgrade head` → 迁移执行成功

### 前端验证
1. `cd src/frontend && npm install && npm run dev` → Vite 启动 `localhost:5173`
2. 页面路由：点击导航 → Hash 变化 → 对应页面渲染
3. API 集成：发送对话 → 真实 HTTP 请求到后端 → 展示回复
4. `npm run build` → `dist/` 生成压缩静态文件

---

## 文件变更汇总

| 操作 | 数量 | 说明 |
|------|------|------|
| 修改后端文件 | 3 | agent_service.py, cnki_service.py, dependencies.py |
| 新增Alembic文件 | 3+ | alembic.ini, env.py, 初始迁移脚本 |
| 新增前端文件 | 30+ | package.json, vite.config.js, index.html, 12组件, 6页面, 6服务, 5样式, 3工具, 3核心 |
| 总新增代码 | ~2000行 | 后端~200行 + 前端~1800行 |