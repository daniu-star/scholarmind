# ScholarMind 架构复杂化升级 v4.0 计划

## 审计日期：2026-06-11

---

## 一、现状审计

### 后端（6层架构，Phase 1 已完成）

| 层级 | 状态 | 详情 |
|------|------|------|
| 配置层 | ✅ | PydanticSettings，支持 .env，含数据库/Redis/Celery/日志/限流全部配置 |
| 数据库层 | ✅ | 异步SQLAlchemy + 3个Repository（Conversation/Skill/Chart）+ Alembic迁移 |
| 中间件层 | ✅ | RequestID + Logging + RateLimit + CORS + ErrorHandler（5个中间件） |
| 核心层 | ✅ | dependencies.py（依赖注入）+ events.py（生命周期）+ exceptions.py（15种异常类）+ logging_config.py（structlog） |
| 模型层 | ✅ | 3个ORM表 + 7个枚举 + 5个Pydantic Schema文件 + 结构化错误码 |
| 路由层 | ✅ | 6个Router（agent/chart/upload/skills/knowledge/ws），全部使用Depends注入 |
| 服务层 | ✅ | 7个Service（agent/cnki/chart/skills/rag/vector/stream），含熔断器+缓存 |
| 工具层 | ✅ | CacheManager + CircuitBreaker（全局实例） |
| 任务层 | ✅ | Celery配置 + chart_tasks + BackgroundTasks降级 |
| 测试层 | ✅ | conftest + 5个router测试 + 3个service测试 |

**已具备的能力：**
- WebSocket流式对话（ws.py + stream_service.py）
- API版本化（/api/v1/ 前缀）
- 统一错误码（ErrorCode枚举 + AppException体系）
- 数据库连接池健康监控
- ChartRepository集成（图表生成持久化）
- 速率限制（令牌桶算法，内存实现）
- 路径遍历防护（upload/chart路由）

**架构缺陷（企业级深化方向）：**

| 缺陷 | 影响 | 优先级 |
|------|------|--------|
| 无事务管理抽象 | Repository各自管理session，跨Repository操作无事务保证 | 🔴高 |
| 服务层无接口抽象 | 所有Service为具体类，无法替换实现（如Mock测试） | 🔴高 |
| 限流为内存实现 | 多进程部署时各进程独立计数，无法全局限流 | 🟡中 |
| 无事件总线 | 服务间耦合（如AgentService直接调用CNKIService），无法解耦 | 🟡中 |
| 无监控指标 | 无法观测API延迟分布、错误率、吞吐量 | 🟡中 |
| DeepSeek API无熔断器 | 仅CNKI有熔断器，DeepSeek调用无保护 | 🟡中 |
| 无请求/响应DTO映射层 | Schema直接暴露内部模型，API契约与内部模型耦合 | 🟢低 |
| 无后台任务监控 | Celery任务状态不可见，无重试策略可视化 | 🟢低 |

### 前端（基础设施齐全，组件/页面完全空白）

| 层级 | 状态 | 详情 |
|------|------|------|
| 构建工具 | ✅ | Vite 5 + ES模块 + Terser压缩 |
| CSS | ✅ | 5文件拆分（variables/base/layout/components/pages） |
| 工具函数 | ✅ | storage.js（localStorage封装）+ dom.js（createElement/delegate/$）+ constants.js |
| 核心模块 | ✅ | store.js（Proxy响应式）+ router.js（12路由Hash路由）+ App.js + main.js |
| API服务层 | ✅ | api.js（fetch封装）+ 5个领域API（agentApi/chartApi/cnkiApi/skillsApi/uploadApi） |
| **组件** | ❌ | 目录为空，router.js和App.js引用的12个组件文件不存在 |
| **页面** | ❌ | 目录为空，router.js引用的6个页面文件不存在 |

**现状：前端无法启动** — `App.js` 导入 `../components/TopNav.js` 不存在，`router.js` 导入的所有页面文件不存在。

**架构缺陷（前端深化方向）：**

| 缺陷 | 影响 | 优先级 |
|------|------|------|
| 无虚拟DOM/高效渲染 | 直接操作innerHTML，重复渲染时性能差 | 🔴高 |
| 无组件生命周期 | 组件无法在挂载/更新/卸载时执行清理逻辑 | 🔴高 |
| 前端API路径未版本化 | agentApi.js仍使用 `/api/agent/` 而非 `/api/v1/agent/` | 🔴高 |
| 无WebSocket客户端 | 无法使用后端的流式对话能力 | 🟡中 |
| 无Markdown渲染 | 对话内容为纯文本，无法展示富文本 | 🟡中 |
| CSS为静态文件 | 无CSS模块化/Tailwind/动态样式 | 🟢低 |

---

## 二、升级方案总览

```
Phase 1: 后端企业级模式深化
  ├── 1.1 Unit of Work（事务管理抽象）
  ├── 1.2 Service接口抽象（ABC协议）
  ├── 1.3 EventBus（事件驱动解耦）
  ├── 1.4 Redis分布式限流（升级内存限流）
  ├── 1.5 Prometheus监控指标
  ├── 1.6 DeepSeek API熔断器集成
  └── 1.7 DTO响应映射层

Phase 2: 前端架构升级 + 组件页面创建
  ├── 2.1 前端API路径版本化修复
  ├── 2.2 虚拟DOM渲染引擎（vdom.js）
  ├── 2.3 组件生命周期管理（component.js）
  ├── 2.4 基础组件（Toast + Modal + TopNav + Breadcrumb）
  ├── 2.5 对话组件（ChatBubble + ChatInput + AgentSidebar）
  ├── 2.6 功能组件（FileUploadPanel + ChartDialog + CNKIDialog + SkillManager + SettingsPanel）
  ├── 2.7 页面（HomePage + ResearchTypePage + ReadinessPage + AgentPage + SettingsPage）

Phase 3: 前端高级特性
  ├── 3.1 WebSocket客户端 + 流式消息渲染
  ├── 3.2 Markdown渲染 + 代码高亮
  └── 3.3 拖拽上传 + 键盘快捷键
```

---

## 三、Phase 1：后端企业级模式深化

### 1.1 Unit of Work（事务管理抽象）

**目标**：统一管理跨Repository的事务边界，确保多个Repository操作在同一事务中执行。

**新增文件**：`src/backend/db/unit_of_work.py`

```python
class UnitOfWork:
    """工作单元：管理事务边界和Repository实例化
    
    用法：
        async with UnitOfWork(session_factory) as uow:
            uow.conversations.add_message(...)
            uow.charts.save_record(...)
            await uow.commit()  # 统一提交
    
    自动回滚：如果async with块内抛出异常，自动回滚
    """
    
    def __init__(self, session_factory):
        self.session_factory = session_factory
        self._session = None
    
    async def __aenter__(self):
        self._session = self.session_factory()
        self.conversations = ConversationRepository(self._session)
        self.skills = SkillRepository(self._session)
        self.charts = ChartRepository(self._session)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            await self._session.rollback()
        await self._session.close()
    
    async def commit(self):
        await self._session.commit()
    
    async def rollback(self):
        await self._session.rollback()
```

**修改文件**：
- `src/backend/core/dependencies.py` — 添加 `get_uow` 依赖注入函数
- `src/backend/services/agent_service.py` — 流式对话中使用UoW替代单独Repository

---

### 1.2 Service接口抽象（ABC协议）

**目标**：为关键Service定义抽象基类，支持多实现替换（如Mock测试、不同LLM提供商）。

**新增文件**：`src/backend/services/interfaces.py`

```python
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional

class IAgentService(ABC):
    """Agent对话服务接口"""
    @abstractmethod
    async def chat(self, message: str, agent_id: str, session_id: str, context: Optional[dict] = None) -> dict: ...
    @abstractmethod
    async def stream_chat(self, message: str, agent_id: str, session_id: str, context: Optional[dict] = None) -> AsyncGenerator: ...
    @abstractmethod
    async def clear_conversation(self, session_id: str) -> bool: ...
    @abstractmethod
    def list_agents(self) -> list[dict]: ...

class ICNKIService(ABC):
    """CNKI检索服务接口"""
    @abstractmethod
    async def search(self, query: str, year_filter: str = "", count: int = 20) -> list: ...
    @abstractmethod
    async def check_connection(self) -> dict: ...
    @abstractmethod
    async def close(self): ...

class IChartService(ABC):
    """图表生成服务接口"""
    @abstractmethod
    def generate_chart(self, chart_type: str, data, title: str, **kwargs) -> bytes: ...
```

**修改文件**：
- `src/backend/services/agent_service.py` — `class AgentService(IAgentService)`
- `src/backend/services/cnki_service.py` — `class CNKIService(ICNKIService)`
- `src/backend/services/chart_service.py` — 添加接口标记
- `src/backend/core/dependencies.py` — 返回类型标注为接口

---

### 1.3 EventBus（事件驱动解耦）

**目标**：解耦AgentService与CNKIService/ChartService的直接调用，通过事件总线异步通信。

**新增文件**：`src/backend/core/event_bus.py`

```python
import asyncio
from enum import Enum
from typing import Callable, Awaitable

class EventType(str, Enum):
    CNKI_SEARCH_REQUESTED = "cnki.search.requested"
    CHART_GENERATION_REQUESTED = "chart.generation.requested"
    SKILL_DETECTED = "skill.detected"
    CONVERSATION_UPDATED = "conversation.updated"

class EventBus:
    """轻量级进程内事件总线
    
    支持同步和异步处理器，按事件类型分发
    """
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = {}
    
    def subscribe(self, event_type: EventType, handler: Callable[..., Awaitable]):
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
    
    async def publish(self, event_type: EventType, **data):
        handlers = self._handlers.get(event_type, [])
        tasks = [handler(**data) for handler in handlers]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

# 全局单例
event_bus = EventBus()
```

**修改文件**：
- `src/backend/core/events.py` — startup中注册事件处理器
- `src/backend/services/agent_service.py` — 发布事件替代直接调用 `_execute_cnki_skill()`
- `src/backend/services/cnki_service.py` — 添加事件处理器方法

---

### 1.4 Redis分布式限流

**目标**：将内存令牌桶升级为Redis滑动窗口限流，支持多进程/多服务器部署。

**新增文件**：`src/backend/middleware/redis_rate_limit.py`

```python
class RedisRateLimitMiddleware(BaseHTTPMiddleware):
    """基于Redis的分布式滑动窗口限流
    
    使用 Sorted Set 实现滑动窗口：
    - key: ratelimit:{session_id}
    - score: 请求时间戳
    - member: 请求唯一ID
    
    降级：Redis不可用时自动回退到内存令牌桶
    """
    def __init__(self, app, redis_url: str, max_requests: int = 60, window_seconds: int = 60):
        ...
```

**修改文件**：
- `src/backend/app.py` — 条件注册RedisRateLimitMiddleware或内存RateLimitMiddleware
- `src/backend/config.py` — 添加 `REDIS_ENABLED` 配置项

---

### 1.5 Prometheus监控指标

**目标**：暴露 `/metrics` 端点，提供API延迟分布、请求计数、错误率等可观测性数据。

**新增文件**：`src/backend/core/metrics.py`

```python
from prometheus_client import Counter, Histogram, Gauge, generate_latest

# API请求指标
api_requests_total = Counter(
    "scholarmind_api_requests_total",
    "Total API requests",
    ["method", "endpoint", "status"]
)
api_request_duration = Histogram(
    "scholarmind_api_request_duration_seconds",
    "API request duration",
    ["method", "endpoint"]
)

# 业务指标
active_websocket_connections = Gauge(
    "scholarmind_active_ws_connections",
    "Active WebSocket connections"
)
cnki_search_duration = Histogram(
    "scholarmind_cnki_search_duration_seconds",
    "CNKI search duration"
)
chart_generation_duration = Histogram(
    "scholarmind_chart_generation_duration_seconds",
    "Chart generation duration",
    ["chart_type"]
)
deepseek_api_errors = Counter(
    "scholarmind_deepseek_api_errors_total",
    "DeepSeek API errors"
)
```

**修改文件**：
- `src/backend/app.py` — 添加 `/metrics` 端点
- `src/backend/middleware/logging.py` — 记录Prometheus指标
- `src/backend/requirements.txt` — 添加 `prometheus-client`

---

### 1.6 DeepSeek API熔断器集成

**目标**：为DeepSeek API调用添加熔断器保护，防止API故障时雪崩。

**修改文件**：`src/backend/services/agent_service.py`

```python
# 在 __init__ 中添加：
from ..utils.circuit_breaker import deepseek_circuit_breaker

# 在 chat() 和 stream_chat() 中包装 API 调用：
async with deepseek_circuit_breaker:
    response = await self.client.chat.completions.create(...)
```

---

### 1.7 DTO响应映射层

**目标**：将ORM模型到API响应的转换逻辑集中管理，避免在router中散落转换代码。

**新增文件**：`src/backend/models/dto/response_mapper.py`

```python
class ResponseMapper:
    """统一响应映射：ORM模型 → API响应字典"""
    
    @staticmethod
    def conversation_to_response(conv: Conversation) -> dict:
        return {
            "id": conv.id,
            "session_id": conv.session_id,
            "role": conv.role,
            "content": conv.content,
            "created_at": conv.created_at.isoformat(),
        }
    
    @staticmethod
    def skill_to_response(skill: Skill) -> dict:
        return {
            "skill_id": skill.skill_id,
            "display_name": skill.display_name,
            "description": skill.description,
            "category": skill.category,
            "enabled": skill.enabled,
            "agents": skill.agents,
            "triggers": skill.triggers,
            "is_preset": skill.is_preset,
        }
```

---

## 四、Phase 2：前端架构升级 + 组件页面创建

### 2.1 前端API路径版本化修复

**目标**：修复前端API路径与后端 `/api/v1/` 前缀不匹配的问题。

**修改文件**：`src/frontend/src/services/agentApi.js`

```javascript
// 修改前
chat: (message, agentId, sessionId, context) =>
    api.post('/api/agent/chat', {...}),

// 修改后
chat: (message, agentId, sessionId, context) =>
    api.post('/api/v1/agent/chat', {...}),
```

**修改文件**：
- `src/frontend/src/services/agentApi.js` — 4个端点
- `src/frontend/src/services/chartApi.js` — 3个端点
- `src/frontend/src/services/cnkiApi.js` — 3个端点
- `src/frontend/src/services/skillsApi.js` — 7个端点
- `src/frontend/src/services/uploadApi.js` — 4个端点

---

### 2.2 虚拟DOM渲染引擎

**目标**：实现轻量级虚拟DOM，提供高效的DOM diff和patch，避免直接innerHTML操作。

**新增文件**：`src/frontend/src/utils/vdom.js`

```javascript
// 轻量虚拟DOM（~150行）
// 核心API：
//   h(tag, attrs, ...children)  — 创建虚拟节点
//   diff(oldVNode, newVNode)     — 计算差异
//   patch(domNode, patches)      — 应用差异到真实DOM
//   mount(vnode, container)      — 首次挂载

export function h(tag, attrs = {}, ...children) {
  return { tag, attrs, children: children.flat(), key: attrs.key };
}

export function diff(oldVNode, newVNode) { /* ... */ }
export function patch(domNode, patches) { /* ... */ }
export function mount(vnode, container) {
  const dom = createDomNode(vnode);
  container.appendChild(dom);
  return dom;
}
```

---

### 2.3 组件生命周期管理

**目标**：为所有组件提供统一的挂载/更新/卸载生命周期。

**新增文件**：`src/frontend/src/utils/component.js`

```javascript
// 组件基类/工厂
// 生命周期钩子：
//   onMount(el)    — DOM挂载后调用
//   onUpdate(props) — 属性变化时调用
//   onUnmount()    — DOM移除前调用（清理定时器/事件监听）

export function defineComponent({ render, onMount, onUpdate, onUnmount }) {
  return (props = {}) => {
    const el = render(props);
    el._lifecycle = { onMount, onUpdate, onUnmount, props, mounted: false };
    
    // 使用MutationObserver检测DOM挂载
    const observer = new MutationObserver(() => {
      if (document.contains(el) && !el._lifecycle.mounted) {
        el._lifecycle.mounted = true;
        onMount?.(el);
        observer.disconnect();
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    
    return el;
  };
}
```

---

### 2.4 基础组件创建（4个）

#### Toast.js
- 文件：`src/frontend/src/components/Toast.js`
- 功能：全局通知提示，支持 success/warning/error/info
- API：`Toast.show({ type, message, duration })`、`Toast.success(msg)` 等静态方法
- 特性：自动消失(3s)、堆叠显示、CSS动画

#### Modal.js
- 文件：`src/frontend/src/components/Modal.js`
- 功能：通用模态对话框
- Props：`{ title, content, onConfirm, onCancel, confirmText, cancelText }`
- 特性：ESC关闭、点击遮罩关闭、focus-trap

#### TopNav.js
- 文件：`src/frontend/src/components/TopNav.js`
- 功能：顶部导航栏
- 包含：品牌Logo、Agent切换下拉菜单、设置按钮
- 依赖：store（currentPage、discipline）

#### Breadcrumb.js
- 文件：`src/frontend/src/components/Breadcrumb.js`
- 功能：面包屑导航
- 依赖：store（currentPage → 自动推导路径）

---

### 2.5 对话组件创建（3个）

#### ChatBubble.js
- 文件：`src/frontend/src/components/ChatBubble.js`
- 功能：单条消息气泡
- 支持类型：text（Markdown）、chart（图表图片+标签）、cnki（检索结果卡片）、options（选项按钮组）
- Props：`{ role, content, type, chartInfo, cnkiResults, options, onOptionClick }`

#### ChatInput.js
- 文件：`src/frontend/src/components/ChatInput.js`
- 功能：消息输入框
- 特性：Enter发送/Shift+Enter换行、自动高度、字符计数、附件按钮
- Props：`{ onSend, onAttach, placeholder, disabled }`

#### AgentSidebar.js
- 文件：`src/frontend/src/components/AgentSidebar.js`
- 功能：对话页右侧边栏
- 包含：对话控制区（撤销/回退/切换Agent）、Skills状态、研究进度
- 可折叠/展开

---

### 2.6 功能组件创建（5个）

#### FileUploadPanel.js
- 文件：`src/frontend/src/components/FileUploadPanel.js`
- 功能：文件上传面板
- 特性：拖拽区域高亮、文件类型图标、进度条、已上传列表
- 依赖：uploadApi

#### ChartDialog.js
- 文件：`src/frontend/src/components/ChartDialog.js`
- 功能：图表生成对话框
- 特性：12种图表类型网格选择、预览区、下载按钮
- 依赖：chartApi、Modal

#### CNKIDialog.js
- 文件：`src/frontend/src/components/CNKIDialog.js`
- 功能：CNKI文献检索对话框
- 特性：搜索框+年份过滤、结果列表（标题/作者/来源/引用数）、核心期刊标记
- 依赖：cnkiApi、Modal

#### SkillManager.js
- 文件：`src/frontend/src/components/SkillManager.js`
- 功能：技能管理面板
- 特性：分类筛选、开关切换、编辑表单（触发词/规则/关联Agent）
- 依赖：skillsApi、Modal

#### SettingsPanel.js
- 文件：`src/frontend/src/components/SettingsPanel.js`
- 功能：设置面板
- 包含：API地址、主题切换、对话参数
- 依赖：store

---

### 2.7 页面创建（5个）

#### HomePage.js
- 文件：`src/frontend/src/pages/HomePage.js`
- 内容：3个学科大卡片（工科/理科/人文社科）+ 底部自定义Agent入口
- 交互：点击卡片 → navigateTo对应学科

#### ResearchTypePage.js
- 文件：`src/frontend/src/pages/ResearchTypePage.js`
- 内容：根据学科显示不同研究类型选项（人文社科显示6种，工科/理科显示简化的4种）
- Props：`{ discipline }`

#### ReadinessPage.js
- 文件：`src/frontend/src/pages/ReadinessPage.js`
- 内容：3个准备度选项卡片（暂未有思路/已有思路/已写好架构）
- 交互：点击 → navigateTo对应Agent

#### AgentPage.js
- 文件：`src/frontend/src/pages/AgentPage.js`
- 内容：对话主界面（组合TopNav + Breadcrumb + ChatBubble列表 + ChatInput + AgentSidebar + 各种Dialog）
- 这是最复杂的页面（~250行），核心交互逻辑
- Props：`{ agentId }`

#### SettingsPage.js
- 文件：`src/frontend/src/pages/SettingsPage.js`
- 内容：设置界面（组合SettingsPanel + 关于信息）

---

## 五、Phase 3：前端高级特性

### 3.1 WebSocket客户端 + 流式消息渲染

**新增文件**：`src/frontend/src/services/wsClient.js`

```javascript
export class WSClient {
  constructor(agentId, sessionId) {
    this.url = `ws://localhost:8000/api/v1/ws/chat/${agentId}?session_id=${sessionId}`;
    this.ws = null;
    this.listeners = { token: [], done: [], error: [], ping: [] };
    this.reconnectAttempts = 0;
    this.maxReconnect = 5;
  }
  
  connect() { /* WebSocket连接 + 心跳 + 自动重连 */ }
  send(message, context) { /* 发送消息 */ }
  on(event, callback) { /* 注册事件监听 */ }
  cancel() { /* 取消当前生成 */ }
  close() { /* 关闭连接 */ }
}
```

**修改文件**：`src/frontend/src/pages/AgentPage.js` — 集成WSClient，实现流式token追加渲染

---

### 3.2 Markdown渲染

**新增文件**：`src/frontend/src/utils/markdown.js`

- 使用marked库（ES模块导入）
- 支持：标题、粗体/斜体、代码块（带语言高亮）、表格、引用、列表、链接
- 集成到ChatBubble.js中

**修改文件**：`src/frontend/src/components/ChatBubble.js` — 添加Markdown渲染模式

---

### 3.3 拖拽上传 + 键盘快捷键

**修改文件**：`src/frontend/src/pages/AgentPage.js`

- 拖拽上传：dragenter/dragover/drop事件处理，调用uploadApi
- 键盘快捷键：
  - `Ctrl+K`：打开CNKI检索
  - `Ctrl+G`：打开图表生成
  - `Ctrl+S`：打开技能管理
  - `Ctrl+Enter`：发送消息
  - `Esc`：关闭对话框

---

## 六、实施顺序

```
Phase 1: 后端企业级模式深化（按依赖顺序，共7步）
  ├── Step 1: UnitOfWork（db/unit_of_work.py）           ~80行新增
  ├── Step 2: Service接口（services/interfaces.py）      ~60行新增
  ├── Step 3: EventBus（core/event_bus.py）              ~90行新增
  ├── Step 4: Redis限流（middleware/redis_rate_limit.py） ~100行新增
  ├── Step 5: Prometheus指标（core/metrics.py）          ~80行新增
  ├── Step 6: DeepSeek熔断器集成（agent_service.py修改）  ~20行修改
  └── Step 7: DTO映射层（models/dto/response_mapper.py）  ~80行新增

Phase 2: 前端架构升级 + 组件页面创建（按依赖顺序，共8步）
  ├── Step 8: API路径版本化修复（5个API文件）            每文件~5行修改
  ├── Step 9: vdom.js + component.js                     ~230行新增
  ├── Step 10: 基础组件（Toast + Modal + TopNav + Breadcrumb） ~400行新增
  ├── Step 11: 对话组件（ChatBubble + ChatInput + AgentSidebar） ~450行新增
  ├── Step 12: 功能组件（FileUploadPanel + ChartDialog + CNKIDialog） ~360行新增
  ├── Step 13: 功能组件续（SkillManager + SettingsPanel）  ~260行新增
  ├── Step 14: 页面（HomePage + ResearchTypePage + ReadinessPage） ~300行新增
  └── Step 15: 页面续（AgentPage + SettingsPage）         ~330行新增

Phase 3: 前端高级特性（在Phase 2完成后，共3步）
  ├── Step 16: wsClient.js + 流式渲染集成                ~150行新增
  ├── Step 17: markdown.js + ChatBubble集成               ~80行新增
  └── Step 18: 拖拽上传 + 键盘快捷键                      ~80行修改
```

---

## 七、文件变更汇总

| 操作 | 数量 | 说明 |
|------|------|------|
| 新增后端 | 5 | UnitOfWork / interfaces / EventBus / redis_rate_limit / metrics / response_mapper |
| 修改后端 | 4 | app.py / dependencies.py / events.py / agent_service.py |
| 新增前端工具 | 2 | vdom.js / component.js |
| 新增前端组件 | 12 | Toast/Modal/TopNav/Breadcrumb/ChatBubble/ChatInput/AgentSidebar/FileUploadPanel/ChartDialog/CNKIDialog/SkillManager/SettingsPanel |
| 新增前端页面 | 5 | HomePage/ResearchTypePage/ReadinessPage/AgentPage/SettingsPage |
| 新增前端服务 | 1 | wsClient.js |
| 新增前端工具 | 1 | markdown.js |
| 修改前端 | 5 | 5个API服务文件 |
| **总变更** | **~3100行** | 后端~600行 + 前端~2500行 |

---

## 八、验证步骤

### 后端验证
1. `cd src/backend && python -m pytest tests/ -v` — 所有测试通过
2. `uvicorn src.backend.app:app --reload` — 启动无报错
3. `GET /api/v1/health` — 返回连接池状态 + 新增指标
4. `GET /metrics` — 返回Prometheus格式指标
5. WebSocket流式对话正常
6. Redis限流（若Redis可用）正常工作

### 前端验证
1. `cd src/frontend && npm install && npm run dev` — Vite启动，无import错误
2. 页面路由：点击学科卡片 → Hash变化 → 对应页面渲染
3. Agent对话页：发送消息 → HTTP请求到后端 → 展示回复
4. CNKI检索：打开CNKI对话框 → 搜索 → 结果卡片展示
5. 图表生成：选择图表类型 → 生成 → 预览展示
6. `npm run build` — `dist/` 生成压缩静态文件

---

## 九、假设与决策

1. **Redis为可选依赖**：分布式限流和Prometheus指标均为可选增强，Redis不可用时自动降级到内存实现
2. **EventBus为进程内实现**：不引入外部消息队列（Kafka/RabbitMQ），保持架构简洁
3. **前端保持原生JavaScript**：不引入React/Vue框架，使用自研轻量虚拟DOM（~150行），保持与Vite原生ES模块兼容
4. **虚拟DOM为简化版**：仅支持节点增删改和属性更新，不支持keyed diff（组件数量少，无需此优化）
5. **Markdown渲染使用marked**：轻量级库（~20KB gzipped），不引入重型编辑器
6. **组件生命周期基于MutationObserver**：利用浏览器原生API检测DOM挂载/卸载，无需框架