# ScholarMind 架构复杂化升级 v3.0 计划

## 审计日期：2026-06-11

---

## 一、现状审计结论

### 后端：6层架构已完成基础搭建，但存在能力缺口

经过逐文件审查，后端已完成以下工作（旧计划中的任务1-2实际已完工）：

| 层级 | 状态 | 备注 |
|------|------|------|
| 配置层 (config.py) | ✅ | DATABASE_URL、LOG_LEVEL、RATE_LIMIT 等全部字段已就绪 |
| 数据库层 (db/) | ✅ | session.py + 3个Repository + Alembic迁移(c4ddc7870a8f)全部完成 |
| 中间件层 (middleware/) | ✅ | RequestID、Logging、RateLimit、CORS 四个中间件 |
| 核心基础设施 (core/) | ✅ | dependencies/exceptions/events/logging 全部实现 |
| 数据模型层 (models/) | ✅ | ORM(3表) + 7个枚举 + 5个schema文件 |
| 工具层 (utils/) | ✅ | CacheManager + CircuitBreaker |
| 后台任务层 (tasks/) | ✅ | Celery + chart_tasks + BackgroundTasks降级 |
| 路由层 (routers/) | ✅ | 5个router全部使用Depends注入 |
| 服务层 (services/) | ✅ | agent_service注入ConversationRepository+SkillsService，cnki_service注入CacheManager+CircuitBreaker |
| 测试层 (tests/) | ✅ | conftest + 5个router测试 + 3个service测试 |

**发现的Bug（2项）：**
1. `agent_service.py:589` — `_execute_cnki_skill()`方法中直接`CNKIService()`实例化，未注入cache/circuit_breaker，导致CNKI搜索绕过熔断器保护
2. `core/events.py:88` — shutdown函数错误地从routers导入`get_cnki_service`（该函数不存在），应通过`app.state.cnki_service`访问

**缺失的关键能力（6项）：**
3. 无WebSocket支持 — 对话仅支持同步请求/响应，无法实现流式输出(SSE/streaming)
4. 无认证授权 — 没有JWT/OAuth，所有API端点公开
5. 无API版本化 — 路由未使用`/api/v1/`前缀
6. 无结构化错误码 — 仅返回HTTP status + detail字符串
7. `agent_service._execute_chart_skill()`未使用ChartRepository持久化图表记录
8. 无数据库连接池健康监控端点

### 前端：基础设施齐全，组件和页面完全空白

| 层级 | 状态 | 备注 |
|------|------|------|
| Vite项目 | ✅ | package.json、vite.config.js、index.html |
| CSS拆分 | ✅ | variables/base/layout/components/pages.css 共5文件 |
| 工具函数 | ✅ | storage.js、dom.js、constants.js |
| 核心模块 | ✅ | store.js(Proxy响应式)、router.js(12路由)、App.js、main.js |
| API服务层 | ✅ | api.js + agentApi/chartApi/cnkiApi/skillsApi/uploadApi |
| **组件(components/)** | ❌ 空目录 | 0/12组件，App.js和router.js引用的文件全部不存在 |
| **页面(pages/)** | ❌ 空目录 | 0/6页面，router.js引用的文件全部不存在 |

**现状：前端无法启动** — `router.js`导入`../pages/HomePage.js`等文件不存在，`App.js`导入`../components/TopNav.js`不存在。

---

## 二、升级方案总览

### 升级策略

本次升级分为**三个Phase**，按依赖关系顺序执行：

```
Phase 1: 后端补全与加固（Bug修复 + 3项关键能力）
  ├── 1.1 修复已知Bug（2项）
  ├── 1.2 添加WebSocket流式对话
  ├── 1.3 添加API版本化 + 结构化错误码
  └── 1.4 添加连接池监控 + ChartRepository集成

Phase 2: 前端组件与页面迁移（从prototype提取 → 模块化）
  ├── 2.1 创建基础组件（Toast、Modal、TopNav、Breadcrumb）
  ├── 2.2 创建对话组件（ChatBubble、ChatInput、AgentSidebar）
  ├── 2.3 创建功能组件（FileUploadPanel、ChartDialog、CNKIDialog、SkillManager、SettingsPanel）
  └── 2.4 创建页面（HomePage、DisciplinePage、ResearchTypePage、ReadinessPage、AgentPage、SettingsPage）

Phase 3: 前端高级特性
  ├── 3.1 WebSocket客户端 + 流式消息渲染
  ├── 3.2 Markdown渲染 + 代码高亮
  └── 3.3 拖拽文件上传 + 键盘快捷键
```

---

## 三、Phase 1：后端补全与加固

### 1.1 修复已知Bug

#### Bug 1：`agent_service.py` CNKI搜索绕过熔断器

**文件**：`src/backend/services/agent_service.py` 第548-598行

**问题**：`_execute_cnki_skill()`方法内部直接`cnki = CNKIService()`创建新实例，未注入CacheManager和CircuitBreaker，导致CNKI API调用不受熔断器保护且浪费缓存。

**修复方案**：将CNKIService通过构造函数注入，或通过依赖注入获取已配置的实例。

```python
# 当前代码（有问题）：
async def _execute_cnki_skill(self, message: str, session_id: str) -> Optional[list]:
    from ..services.cnki_service import CNKIService
    cnki = CNKIService()  # 裸实例，无缓存/熔断器
    results = await cnki.search(query=keywords, year_filter=year_filter, count=10)
    await cnki.close()

# 修复后：
# 1. 在 __init__ 中添加 cnki_service 参数
# 2. 在 dependencies.py 注入
# 3. 使用 self.cnki_service.search() 替代
```

**修改文件**：
- `src/backend/services/agent_service.py` — 添加`cnki_service`可选参数，修改`_execute_cnki_skill()`
- `src/backend/core/dependencies.py` — `get_agent_service`中注入`cnki_service`

#### Bug 2：`core/events.py` shutdown函数导入错误

**文件**：`src/backend/core/events.py` 第86-93行

**问题**：shutdown中`from ..routers.knowledge import get_cnki_service`试图从router模块导入函数，但该函数不存在于routers中。应通过`app.state`访问。

```python
# 当前代码（有问题）：
async def shutdown(app: FastAPI) -> None:
    try:
        from ..routers.knowledge import get_cnki_service  # 该导入不存在
        cnki = get_cnki_service()
        await cnki.close()
    except Exception:
        pass

# 修复后：
async def shutdown(app: FastAPI) -> None:
    cnki = getattr(app.state, "cnki_service", None)
    if cnki is not None:
        try:
            await cnki.close()
        except Exception:
            pass
```

---

### 1.2 WebSocket流式对话

**目标**：将Agent对话从同步请求/响应升级为WebSocket流式输出，用户可实时看到AI逐字生成过程。

**方案**：

```
新增文件：
  src/backend/routers/ws.py            # WebSocket路由
  src/backend/services/stream_service.py # 流式对话服务

修改文件：
  src/backend/app.py                   # 注册WebSocket路由
  src/backend/services/agent_service.py # 添加stream_chat方法
```

**架构设计**：

```
Client (WebSocket)
  └── ws://localhost:8000/api/v1/ws/chat/{agent_id}?session_id=xxx
        └── WebSocket endpoint
              └── StreamService
                    └── AgentService.stream_chat()  # 使用 AsyncOpenAI stream=True
                          └── 逐token通过WebSocket发送
```

**WebSocket消息协议**：
```json
// 客户端→服务端
{"type": "chat", "message": "用户输入", "context": {...}}

// 服务端→客户端
{"type": "token", "content": "逐", "index": 0}     // 流式token
{"type": "token", "content": "字", "index": 1}
{"type": "done", "skills_used": [...], "options": [...], "chart_info": null}
{"type": "error", "message": "错误描述"}
```

**关键实现**：
- `agent_service.py`添加`async def stream_chat()`方法，使用`stream=True`参数
- `stream_service.py`管理WebSocket连接生命周期、心跳检测(ping/pong)、断线重连
- 支持中途取消（客户端发送`{"type": "cancel"}`）

---

### 1.3 API版本化 + 结构化错误码

**目标**：为所有路由添加`/api/v1/`前缀，统一错误响应格式。

**方案**：

#### 3.1 API版本化

```python
# app.py 修改
# 所有router前缀从 /api/xxx 改为 /api/v1/xxx
app.include_router(chart.router, prefix="/api/v1")      # 原 /api/chart
app.include_router(upload.router, prefix="/api/v1")      # 原 /api/upload
app.include_router(skills.router, prefix="/api/v1")      # 原 /api/skills
app.include_router(knowledge.router, prefix="/api/v1")   # 原 /api/knowledge
app.include_router(agent.router, prefix="/api/v1")       # 原 /api/agent
# WebSocket无需版本化前缀（在路由内部处理）
app.include_router(ws.router, prefix="/api/v1")
```

各router内部的`prefix`参数从`/api/xxx`改为`/xxx`，由`include_router`统一加`/api/v1`前缀。

#### 3.2 结构化错误码

**新增文件**：`src/backend/models/error_codes.py`

```python
from enum import Enum

class ErrorCode(str, Enum):
    # 通用
    INTERNAL_ERROR = "INTERNAL_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"

    # Agent
    AGENT_NOT_FOUND = "AGENT_NOT_FOUND"
    AGENT_CHAT_FAILED = "AGENT_CHAT_FAILED"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"

    # CNKI
    CNKI_SEARCH_FAILED = "CNKI_SEARCH_FAILED"
    CNKI_CONNECTION_FAILED = "CNKI_CONNECTION_FAILED"

    # Chart
    CHART_GENERATION_FAILED = "CHART_GENERATION_FAILED"
    INVALID_CHART_TYPE = "INVALID_CHART_TYPE"

    # Upload
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    INVALID_FILE_TYPE = "INVALID_FILE_TYPE"
    UPLOAD_FAILED = "UPLOAD_FAILED"

    # Skills
    SKILL_NOT_FOUND = "SKILL_NOT_FOUND"
    SKILL_VALIDATION_FAILED = "SKILL_VALIDATION_FAILED"
```

统一错误响应格式：
```json
{
  "success": false,
  "error": {
    "code": "CNKI_SEARCH_FAILED",
    "message": "CNKI搜索失败：连接超时",
    "details": {"query": "...", "retry_after": 30}
  }
}
```

**修改文件**：
- `src/backend/models/error_codes.py` — 新增
- `src/backend/core/exceptions.py` — 添加`AppException`基类
- `src/backend/middleware/error_handler.py` — 更新为统一错误格式
- 5个router文件 — 替换HTTPException为AppException

---

### 1.4 连接池监控 + ChartRepository集成

#### 4.1 数据库连接池健康监控

**修改文件**：`src/backend/app.py`

在`/api/health`端点添加数据库连接池状态：
```python
@app.get("/api/v1/health")
async def health_check(request: Request):
    engine = getattr(request.app.state, "db_engine", None)
    pool_stats = {}
    if engine is not None:
        pool = engine.pool
        pool_stats = {
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "overflow": pool.overflow(),
            "total": pool.size() + pool.overflow(),
        }
    return {
        "status": "ok",
        "version": "3.0.0",
        "database": {"pool": pool_stats},
        "deepseek_connected": bool(settings.DEEPSEEK_API_KEY),
    }
```

#### 4.2 ChartRepository集成

**修改文件**：`src/backend/services/agent_service.py`

`_execute_chart_skill()`方法在生成图表后，将记录写入ChartRepository：

```python
# 在 _execute_chart_skill 最后添加：
if self._use_db and hasattr(self, 'chart_repo'):
    await self.chart_repo.create(ChartRecord(
        chart_id=chart_id,
        chart_type=chart_type,
        title=title,
        filepath=str(chart_filepath),
        session_id=session_id,
    ))
```

同时在`dependencies.py`的`get_agent_service`中注入`ChartRepository`。

---

## 四、Phase 2：前端组件与页面迁移

### 概览

从`prototypes/interactive-prototype.html`（~4600行单文件）提取交互逻辑，按工厂函数模式创建模块化组件。

所有组件遵循统一模式：
```javascript
// components/Xxx.js
import { createElement } from '../utils/dom.js';
import { state, watch } from '../app/store.js';

export function Xxx({ prop1, prop2, onEvent }) {
  const el = createElement('div', { className: 'xxx' });
  // ... 构建DOM
  return el;
}
```

### 2.1 基础组件（4个，按创建顺序）

#### Toast.js
- 功能：全局通知提示，支持success/warning/error/info四种类型
- 位置：固定在页面顶部居中
- 特性：自动消失(3s)、堆叠显示、入场/退场动画

#### Modal.js
- 功能：通用模态对话框，支持标题/内容/确认/取消按钮
- 特性：ESC关闭、点击遮罩关闭、焦点陷阱

#### TopNav.js
- 功能：顶部导航栏，包含品牌logo、Agent切换下拉菜单、设置按钮
- 依赖：store（监听currentPage和discipline）

#### Breadcrumb.js
- 功能：面包屑导航，显示当前页面路径
- 依赖：store（监听currentPage/discipline/researchType/readiness）

### 2.2 对话组件（3个）

#### ChatBubble.js
- 功能：单条消息气泡，支持4种类型：
  - `text`：普通Markdown文本
  - `chart`：嵌入图表图片 + 类型标签
  - `cnki`：CNKI检索结果卡片列表
  - `options`：可点击选项按钮组
- Props：`{ role, content, type, options, chartInfo, cnkiResults, onOptionClick }`

#### ChatInput.js
- 功能：消息输入框 + 发送按钮 + 附件按钮 + 快捷键提示
- 特性：Enter发送(Shift+Enter换行)、自动调整高度、字符计数
- 依赖：store（监听sessionId）

#### AgentSidebar.js
- 功能：Agent对话页右侧边栏
- 包含：对话控制区（撤销记忆/回退/切换Agent）、Skills状态区、RAG进度区、研究进度追踪
- 依赖：store、agentApi

### 2.3 功能组件（5个）

#### FileUploadPanel.js
- 功能：文件上传面板，拖拽或点击上传
- 依赖：uploadApi
- 特性：拖拽区域高亮、文件类型图标、上传进度条、已上传文件列表

#### ChartDialog.js
- 功能：图表生成对话框，选择图表类型 → 预览 → 下载
- 依赖：chartApi、Modal组件
- 特性：12种图表类型网格选择、预览区域、下载按钮

#### CNKIDialog.js
- 功能：CNKI文献检索对话框
- 依赖：cnkiApi、Modal组件
- 特性：搜索框+年份过滤、结果列表（标题/作者/来源/引用数）、核心期刊标记

#### SkillManager.js
- 功能：技能管理面板，启用/禁用/编辑/删除/创建技能
- 依赖：skillsApi、Modal组件
- 特性：分类筛选、开关切换、编辑表单（触发词/规则/关联Agent）

#### SettingsPanel.js
- 功能：设置面板，API地址配置、主题切换、对话参数
- 依赖：store

### 2.4 页面（6个）

#### HomePage.js
- 页面内容：3个学科卡片（工科/理科/人文社科）→ 点击跳转对应学科页
- URL hash：`#homepage`

#### DisciplinePage.js
- 页面内容：仅显示已选学科标题，自动跳转到研究类型页
- Props：`{ discipline }`
- 实际上此页面为简化跳转页，可合并到ResearchTypePage

#### ResearchTypePage.js
- 页面内容：研究类型选择（根据学科显示不同选项）
- Props：`{ discipline }`
- URL hash：`#engineering` / `#science` / `#humanities`

#### ReadinessPage.js
- 页面内容：准备度选择（暂未有思路/已有思路/已写好架构）→ 点击跳转对应Agent
- URL hash：`#readiness`

#### AgentPage.js
- 页面内容：对话主界面，组合 TopNav + Breadcrumb + ChatBubble列表 + ChatInput + AgentSidebar + 各种Dialog
- Props：`{ agentId }`
- URL hash：`#researcher` / `#reviewer` 等

#### SettingsPage.js
- 页面内容：设置界面，组合SettingsPanel
- URL hash：`#settings`

---

## 五、Phase 3：前端高级特性

### 3.1 WebSocket客户端 + 流式消息渲染

**新增文件**：`src/frontend/src/services/wsClient.js`

```javascript
export class WSClient {
  constructor(agentId, sessionId) {
    this.url = `ws://${state.settings.wsHost || 'localhost:8000'}/api/v1/ws/chat/${agentId}?session_id=${sessionId}`;
    this.ws = null;
    this.listeners = new Map();
  }

  connect() {
    this.ws = new WebSocket(this.url);
    this.ws.onmessage = (e) => {
      const data = JSON.parse(e.data);
      this.emit(data.type, data);
    };
    // 心跳、重连逻辑
  }

  send(message, context = {}) {
    this.ws.send(JSON.stringify({ type: 'chat', message, context }));
  }

  on(event, callback) { /* ... */ }
  emit(event, data) { /* ... */ }
  close() { /* ... */ }
}
```

**集成到AgentPage**：在ChatBubble渲染中支持流式token追加，光标闪烁动画。

### 3.2 Markdown渲染 + 代码高亮

使用轻量级marked库（~20KB gzipped）渲染Markdown：
- 标题层级(h1-h6)
- 粗体/斜体/行内代码
- 代码块（带语言标签高亮）
- 表格
- 引用块
- 列表（有序/无序）
- LaTeX数学公式（可选，按需加载KaTeX）

**新增文件**：`src/frontend/src/utils/markdown.js`

### 3.3 拖拽文件上传 + 键盘快捷键

#### 拖拽上传
在AgentPage聊天区域支持拖拽文件直接上传：
- dragenter/dragover: 显示拖拽区域高亮
- drop: 提取文件，调用uploadApi上传
- 支持批量拖拽（最多15个）

#### 键盘快捷键
- `Ctrl+K`：打开CNKI检索
- `Ctrl+G`：打开图表生成
- `Ctrl+S`：打开技能管理
- `Ctrl+Enter`：发送消息
- `Esc`：关闭对话框/侧边栏

---

## 六、实施顺序

```
Phase 1: 后端补全与加固（顺序执行，有依赖）
  ├── Step 1: 修复Bug 1（agent_service.py CNKI注入）      约30行修改
  ├── Step 2: 修复Bug 2（events.py shutdown）              约5行修改
  ├── Step 3: 新增 error_codes.py + exceptions.py         约80行新增
  ├── Step 4: 新增 ws.py + stream_service.py             约150行新增
  ├── Step 5: 改造 routers 为 /api/v1 前缀               约5个文件各改动1行
  ├── Step 6: 改造 error_handler.py 统一错误格式           约30行修改
  └── Step 7: 健康检查增强 + ChartRepository集成           约40行修改

Phase 2: 前端组件与页面迁移（按依赖顺序）
  ├── Step 8:  Toast.js + Modal.js                        约80行/文件
  ├── Step 9:  TopNav.js + Breadcrumb.js                  约100行/文件
  ├── Step 10: ChatBubble.js + ChatInput.js + AgentSidebar.js  约150行/文件
  ├── Step 11: FileUploadPanel.js + ChartDialog.js + CNKIDialog.js  约120行/文件
  ├── Step 12: SkillManager.js + SettingsPanel.js          约130行/文件
  ├── Step 13: HomePage.js + DisciplinePage.js + ResearchTypePage.js  约100行/文件
  ├── Step 14: ReadinessPage.js + AgentPage.js            约200行/文件
  └── Step 15: SettingsPage.js                            约80行

Phase 3: 前端高级特性（在Phase 2完成后）
  ├── Step 16: wsClient.js + 流式渲染                     约120行新增
  ├── Step 17: markdown.js + 集成到ChatBubble              约60行新增
  └── Step 18: 拖拽上传 + 键盘快捷键                       约80行修改
```

---

## 七、文件变更汇总

| 操作 | 数量 | 文件列表 |
|------|------|----------|
| 修改后端 | 8 | agent_service.py, events.py, app.py, error_handler.py, exceptions.py, 5个router |
| 新增后端 | 3 | error_codes.py, ws.py, stream_service.py |
| 新增前端组件 | 12 | Toast/Modal/TopNav/Breadcrumb/ChatBubble/ChatInput/AgentSidebar/FileUploadPanel/ChartDialog/CNKIDialog/SkillManager/SettingsPanel.js |
| 新增前端页面 | 6 | HomePage/DisciplinePage/ResearchTypePage/ReadinessPage/AgentPage/SettingsPage.js |
| 新增前端工具 | 2 | wsClient.js, markdown.js |
| **总代码变更** | **~2500行** | 后端~400行 + 前端~2100行 |

---

## 八、验证步骤

### 后端验证
1. `cd src/backend && python -m pytest tests/ -v` — 所有测试通过
2. `uvicorn src.backend.app:app --reload` — 启动无报错
3. `GET /api/v1/health` — 返回连接池状态
4. WebSocket `ws://localhost:8000/api/v1/ws/chat/researcher` — 可流式对话
5. `GET /api/v1/agent/conversation/{id}` — 从ORM DB返回历史
6. 错误响应格式验证：`POST /api/v1/agent/chat` 无效agent_id → 返回 `{"success": false, "error": {"code": "AGENT_NOT_FOUND", ...}}`

### 前端验证
1. `cd src/frontend && npm install && npm run dev` — Vite启动，无import错误
2. 页面路由：点击学科卡片 → Hash变化 → 对应页面渲染
3. Agent对话页：发送消息 → HTTP/WebSocket请求到后端 → 流式展示回复
4. CNKI检索：打开CNKI对话框 → 搜索 → 结果卡片展示
5. 图表生成：选择图表类型 → 生成 → 预览展示
6. `npm run build` — `dist/` 生成压缩静态文件

---

## 九、架构升级后的最终目录结构

```
src/
├── backend/
│   ├── app.py                        # 工厂函数，注册所有路由+中间件
│   ├── config.py                     # 统一配置（PydanticSettings）
│   ├── alembic.ini                   # Alembic配置
│   ├── requirements.txt
│   ├── core/
│   │   ├── dependencies.py           # FastAPI Depends依赖注入
│   │   ├── events.py                 # 生命周期管理
│   │   ├── exceptions.py             # 自定义异常类
│   │   └── logging_config.py         # 结构化日志
│   ├── db/
│   │   ├── session.py                # 异步引擎+会话工厂
│   │   ├── migrations/               # Alembic迁移
│   │   └── repository/               # 仓储模式
│   │       ├── base.py
│   │       ├── chart.py
│   │       ├── conversation.py
│   │       └── skill.py
│   ├── middleware/
│   │   ├── error_handler.py          # 统一错误处理
│   │   ├── logging.py                # 请求日志
│   │   ├── rate_limit.py             # 速率限制
│   │   └── request_id.py             # 请求ID追踪
│   ├── models/
│   │   ├── error_codes.py            # 【新增】结构化错误码
│   │   ├── enums.py                  # 枚举常量
│   │   ├── orm.py                    # SQLAlchemy ORM模型
│   │   └── schemas/                  # Pydantic请求/响应模型
│   ├── routers/
│   │   ├── agent.py                  # Agent对话API（/api/v1/agent）
│   │   ├── chart.py                  # 图表API（/api/v1/chart）
│   │   ├── knowledge.py             # CNKI知识库API（/api/v1/knowledge）
│   │   ├── skills.py                # 技能API（/api/v1/skills）
│   │   ├── upload.py                # 文件上传API（/api/v1/upload）
│   │   └── ws.py                    # 【新增】WebSocket路由
│   ├── services/
│   │   ├── agent_service.py          # Agent对话服务（含流式）
│   │   ├── stream_service.py         # 【新增】WebSocket流式管理
│   │   ├── cnki_service.py           # CNKI检索服务
│   │   ├── chart_service.py          # 图表生成服务
│   │   ├── skills_service.py         # 技能管理服务
│   │   ├── rag_service.py            # RAG知识库服务
│   │   └── vector_service.py         # 向量数据库服务
│   ├── tasks/
│   │   ├── celery_app.py             # Celery配置
│   │   └── chart_tasks.py            # 异步图表任务
│   └── tests/                        # 测试
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.js
│       ├── app/
│       │   ├── App.js
│       │   ├── store.js
│       │   └── router.js
│       ├── components/               # 12个组件
│       │   ├── Toast.js
│       │   ├── Modal.js
│       │   ├── TopNav.js
│       │   ├── Breadcrumb.js
│       │   ├── ChatBubble.js
│       │   ├── ChatInput.js
│       │   ├── AgentSidebar.js
│       │   ├── FileUploadPanel.js
│       │   ├── ChartDialog.js
│       │   ├── CNKIDialog.js
│       │   ├── SkillManager.js
│       │   └── SettingsPanel.js
│       ├── pages/                    # 6个页面
│       │   ├── HomePage.js
│       │   ├── DisciplinePage.js
│       │   ├── ResearchTypePage.js
│       │   ├── ReadinessPage.js
│       │   ├── AgentPage.js
│       │   └── SettingsPage.js
│       ├── services/                 # API服务层
│       │   ├── api.js
│       │   ├── agentApi.js
│       │   ├── chartApi.js
│       │   ├── cnkiApi.js
│       │   ├── skillsApi.js
│       │   ├── uploadApi.js
│       │   └── wsClient.js          # 【新增】
│       ├── styles/                   # CSS
│       └── utils/                    # 工具
│           ├── storage.js
│           ├── dom.js
│           ├── constants.js
│           └── markdown.js           # 【新增】
```

---

## 十、假设与决策

1. **WebSocket vs SSE**：选择WebSocket（而非Server-Sent Events）因为需要双向通信（客户端可发送cancel命令），且WebSocket更适合后续扩展（如多人协作功能）
2. **API版本化前缀**：使用`/api/v1/`统一前缀模式，各router内部减少一层前缀嵌套
3. **前端保持原生JavaScript**：不引入React/Vue框架，保持轻量级。使用ES模块 + 工厂函数模式实现组件化，这是与Vite原生兼容的最佳轻量方案
4. **Markdown渲染**：使用marked库（轻量，~20KB），不引入重型编辑器库
5. **认证跳过**：当前版本暂不实现JWT认证（需要用户系统+注册登录），保留后续扩展接口