# ScholarMind 架构复杂化升级 v5.0 计划

**审计日期：2026-06-11**

---

## 一、现状审计

### 后端（Phase 1 文件已创建，但存在集成缺口）

| 模块 | 文件 | 状态 | 问题 |
|------|------|------|------|
| UnitOfWork | `db/unit_of_work.py` | ✅ 已创建 | ❌ `dependencies.py` 未暴露 `get_uow` 注入函数 |
| Service接口 | `services/interfaces.py` | ✅ 已创建 | ❌ `AgentService` 未继承 `IAgentService`，`dependencies.py` 返回类型未标注为接口 |
| EventBus | `core/event_bus.py` | ✅ 已创建 | ❌ `agent_service.py` 仍直接调用 `_execute_cnki_skill()`，`events.py` 未注册事件处理器 |
| Redis限流 | `middleware/redis_rate_limit.py` | ✅ 已创建 | ❌ `app.py` 未集成，仍只使用内存限流 |
| Prometheus指标 | `core/metrics.py` | ✅ 已创建 | ❌ `app.py` 未注册 `/metrics` 端点 |
| DTO映射层 | `models/dto/response_mapper.py` | ✅ 已创建 | ❌ 所有 router 仍直接构造响应字典，未使用 ResponseMapper |
| 熔断器 | `utils/circuit_breaker.py` | ✅ 已集成 | ✅ `agent_service.py` 的 `chat()` 已使用，但 `stream_chat()` 未使用 |
| API版本化 | 所有 API 文件 | ✅ 已完成 | 前后端均使用 `/api/v1/` 前缀 |

**结论：后端文件已创建，但6个模块存在"文件孤岛"问题——文件存在但未与主流程集成。**

### 前端（基础设施齐全，组件/页面完全空白）

| 层级 | 状态 | 详情 |
|------|------|------|
| 构建工具 | ✅ | Vite 5 + ES模块 |
| CSS | ✅ | 5文件（variables/base/layout/components/pages） |
| 工具函数 | ✅ | storage.js / dom.js / constants.js |
| 核心模块 | ✅ | store.js（Proxy响应式）+ router.js（12路由）+ App.js + main.js |
| API服务层 | ✅ | api.js + 5个领域API（agentApi/chartApi/cnkiApi/skillsApi/uploadApi） |
| **组件** | ❌ 空目录 | App.js 导入 `TopNav.js` 不存在 |
| **页面** | ❌ 空目录 | router.js 导入5个页面全部不存在 |

---

## 二、升级方案总览

```
Phase 1: 后端集成补全（连接6个孤立模块）
  ├── 1.1 Redis分布式限流集成到 app.py
  ├── 1.2 Prometheus /metrics 端点注册
  ├── 1.3 EventBus 事件驱动集成
  ├── 1.4 Service 接口继承 + 依赖注入类型标注
  ├── 1.5 UnitOfWork 依赖注入暴露
  ├── 1.6 DTO ResponseMapper 集成到 Router
  └── 1.7 stream_chat 熔断器保护

Phase 2: 前端架构升级 + 组件页面创建
  ├── 2.1 虚拟DOM渲染引擎（vdom.js）
  ├── 2.2 组件生命周期管理（component.js）
  ├── 2.3 基础组件（Toast + Modal + TopNav + Breadcrumb）
  ├── 2.4 对话组件（ChatBubble + ChatInput + AgentSidebar）
  ├── 2.5 功能组件（FileUploadPanel + ChartDialog + CNKIDialog）
  ├── 2.6 功能组件续（SkillManager + SettingsPanel）
  ├── 2.7 页面（HomePage + ResearchTypePage + ReadinessPage）
  └── 2.8 页面续（AgentPage + SettingsPage）

Phase 3: 前端高级特性
  ├── 3.1 WebSocket客户端 + 流式消息渲染
  ├── 3.2 Markdown渲染 + 代码高亮
  └── 3.3 拖拽上传 + 键盘快捷键
```

---

## 三、Phase 1：后端集成补全

### 1.1 Redis分布式限流集成到 app.py

**目标**：在 `app.py` 中条件注册 RedisRateLimitMiddleware，Redis 不可用时自动降级到内存限流。

**修改文件**：`src/backend/app.py`

```python
# 修改前（仅内存限流）
from src.backend.middleware.rate_limit import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware)

# 修改后（条件注册）
from src.backend.middleware.rate_limit import RateLimitMiddleware
from src.backend.middleware.redis_rate_limit import RedisRateLimitMiddleware

# 尝试 Redis 分布式限流，失败则降级到内存限流
if settings.RATE_LIMIT_ENABLED:
    try:
        import redis
        r = redis.from_url(settings.REDIS_URL, socket_connect_timeout=1)
        r.ping()
        r.close()
        app.add_middleware(
            RedisRateLimitMiddleware,
            redis_url=settings.REDIS_URL,
            max_requests=settings.RATE_LIMIT_REQUESTS,
            window_seconds=60,
        )
        logger.info("Redis rate limiter enabled")
    except Exception:
        app.add_middleware(RateLimitMiddleware)
        logger.warning("Redis unavailable, falling back to in-memory rate limiter")
```

---

### 1.2 Prometheus /metrics 端点注册

**目标**：在 `app.py` 中注册 `/metrics` 端点，暴露 Prometheus 格式指标。

**修改文件**：`src/backend/app.py`

```python
# 在路由注册部分添加
from src.backend.core.metrics import get_metrics

@app.get("/metrics")
async def metrics():
    from fastapi.responses import Response
    return Response(content=get_metrics(), media_type="text/plain")
```

**同时修改**：`src/backend/middleware/logging.py` — 在请求日志中调用 `record_api_metrics()`

---

### 1.3 EventBus 事件驱动集成

**目标**：解耦 `AgentService` 与 `CNKIService`/`ChartService` 的直接调用，通过 EventBus 异步通信。

**修改文件**：
- `src/backend/core/events.py` — `startup()` 中注册事件处理器
- `src/backend/services/agent_service.py` — 发布事件替代直接调用

```python
# events.py startup() 中添加：
from ..core.event_bus import event_bus, EventType
from ..services.cnki_service import CNKIService

# 注册 CNKI 搜索事件处理器
async def handle_cnki_search(message: str, session_id: str, **kwargs):
    cnki = CNKIService()
    results = await cnki.search(query=message, count=10)
    await cnki.close()
    # 结果存入 app.state 供后续查询
    return results

event_bus.subscribe(EventType.CNKI_SEARCH_REQUESTED, handle_cnki_search)
```

```python
# agent_service.py 中：
# 修改前：直接调用
cnki_results = await self._execute_cnki_skill(message, session_id)

# 修改后：发布事件
await event_bus.publish(
    EventType.CNKI_SEARCH_REQUESTED,
    message=message,
    session_id=session_id,
)
# 结果通过事件回调获取（保留同步等待机制）
```

---

### 1.4 Service 接口继承 + 依赖注入类型标注

**目标**：让 `AgentService` 继承 `IAgentService`，`dependencies.py` 返回类型标注为接口。

**修改文件**：
- `src/backend/services/agent_service.py` — `class AgentService(IAgentService)`
- `src/backend/core/dependencies.py` — 返回类型标注为 `IAgentService`

```python
# agent_service.py
from .interfaces import IAgentService

class AgentService(IAgentService):
    ...

# dependencies.py
from ..services.interfaces import IAgentService

async def get_agent_service(...) -> IAgentService:
    ...
```

---

### 1.5 UnitOfWork 依赖注入暴露

**目标**：在 `dependencies.py` 中添加 `get_uow` 依赖注入函数。

**修改文件**：`src/backend/core/dependencies.py`

```python
from ..db.unit_of_work import UnitOfWork

async def get_uow(request: Request) -> AsyncGenerator[UnitOfWork, None]:
    """获取 UnitOfWork 实例（事务管理器）"""
    session_factory = getattr(request.app.state, "db_session_factory", None)
    if session_factory is None:
        raise RuntimeError("Database session factory not initialized")
    async with UnitOfWork(session_factory) as uow:
        yield uow
```

---

### 1.6 DTO ResponseMapper 集成到 Router

**目标**：在 router 中使用 `ResponseMapper` 统一构造响应，替代散落的字典构造。

**修改文件**：所有 5 个 router 文件（agent/chart/upload/skills/knowledge）

```python
# 修改前
return {"success": True, "data": {...}}

# 修改后
from ..models.dto.response_mapper import ResponseMapper
return ResponseMapper.success_response(data=..., message="操作成功")
```

---

### 1.7 stream_chat 熔断器保护

**目标**：为 `stream_chat()` 方法添加与 `chat()` 相同的熔断器保护。

**修改文件**：`src/backend/services/agent_service.py`

```python
# stream_chat() 中，将直接的 API 调用包装在熔断器中
async with deepseek_circuit_breaker:
    stream = await self.client.chat.completions.create(
        model=self.model,
        messages=messages,
        temperature=0.7,
        max_tokens=2048,
        stream=True,
    )
    async for chunk in stream:
        ...
```

---

## 四、Phase 2：前端架构升级 + 组件页面创建

### 2.1 虚拟DOM渲染引擎

**新增文件**：`src/frontend/src/utils/vdom.js`（~150行）

核心API：
- `h(tag, attrs, ...children)` — 创建虚拟节点
- `diff(oldVNode, newVNode)` — 计算差异（节点增删改、属性更新）
- `patch(domNode, patches)` — 应用差异到真实DOM
- `mount(vnode, container)` — 首次挂载

### 2.2 组件生命周期管理

**新增文件**：`src/frontend/src/utils/component.js`（~80行）

生命周期钩子：
- `onMount(el)` — DOM挂载后调用
- `onUpdate(props)` — 属性变化时调用
- `onUnmount()` — DOM移除前调用（清理定时器/事件监听）

基于 `MutationObserver` 检测DOM挂载/卸载。

### 2.3 基础组件（4个）

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
- 功能：顶部导航栏（品牌Logo、Agent切换下拉菜单、设置按钮）
- 依赖：store（currentPage、discipline）

#### Breadcrumb.js
- 文件：`src/frontend/src/components/Breadcrumb.js`
- 功能：面包屑导航，根据 currentPage 自动推导路径

### 2.4 对话组件（3个）

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
- 功能：对话页右侧边栏（对话控制区、Skills状态、研究进度）
- 可折叠/展开

### 2.5 功能组件（5个）

#### FileUploadPanel.js
- 文件：`src/frontend/src/components/FileUploadPanel.js`
- 功能：文件上传面板（拖拽区域高亮、文件类型图标、进度条、已上传列表）
- 依赖：uploadApi

#### ChartDialog.js
- 文件：`src/frontend/src/components/ChartDialog.js`
- 功能：图表生成对话框（12种图表类型网格选择、预览区、下载按钮）
- 依赖：chartApi、Modal

#### CNKIDialog.js
- 文件：`src/frontend/src/components/CNKIDialog.js`
- 功能：CNKI文献检索对话框（搜索框+年份过滤、结果列表、核心期刊标记）
- 依赖：cnkiApi、Modal

#### SkillManager.js
- 文件：`src/frontend/src/components/SkillManager.js`
- 功能：技能管理面板（分类筛选、开关切换、编辑表单）
- 依赖：skillsApi、Modal

#### SettingsPanel.js
- 文件：`src/frontend/src/components/SettingsPanel.js`
- 功能：设置面板（API地址、主题切换、对话参数）
- 依赖：store

### 2.6 页面（5个）

#### HomePage.js
- 文件：`src/frontend/src/pages/HomePage.js`
- 内容：3个学科大卡片（工科/理科/人文社科）+ 底部自定义Agent入口
- 交互：点击卡片 → navigateTo对应学科

#### ResearchTypePage.js
- 文件：`src/frontend/src/pages/ResearchTypePage.js`
- 内容：根据学科显示不同研究类型选项
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

**新增文件**：`src/frontend/src/services/wsClient.js`（~120行）

```javascript
export class WSClient {
  constructor(agentId, sessionId) { ... }
  connect() { /* WebSocket连接 + 心跳 + 自动重连 */ }
  send(message, context) { /* 发送消息 */ }
  on(event, callback) { /* 注册事件监听 */ }
  cancel() { /* 取消当前生成 */ }
  close() { /* 关闭连接 */ }
}
```

**修改文件**：`src/frontend/src/pages/AgentPage.js` — 集成WSClient，实现流式token追加渲染

### 3.2 Markdown渲染 + 代码高亮

**新增文件**：`src/frontend/src/utils/markdown.js`（~60行）

- 使用 marked 库（通过CDN引入或npm安装）
- 支持：标题、粗体/斜体、代码块、表格、引用、列表、链接

**修改文件**：`src/frontend/src/components/ChatBubble.js` — 添加Markdown渲染模式

### 3.3 拖拽上传 + 键盘快捷键

**修改文件**：`src/frontend/src/pages/AgentPage.js`

- 拖拽上传：dragenter/dragover/drop事件处理
- 键盘快捷键：
  - `Ctrl+K`：打开CNKI检索
  - `Ctrl+G`：打开图表生成
  - `Ctrl+S`：打开技能管理
  - `Ctrl+Enter`：发送消息
  - `Esc`：关闭对话框

---

## 六、实施顺序

```
Phase 1: 后端集成补全（共7步，按依赖顺序）
  ├── Step 1: app.py — Redis限流集成 + Prometheus /metrics 端点         ~30行修改
  ├── Step 2: agent_service.py — stream_chat熔断器 + IAgentService继承   ~20行修改
  ├── Step 3: dependencies.py — UnitOfWork注入 + 接口类型标注            ~25行修改
  ├── Step 4: events.py — EventBus事件处理器注册                        ~30行修改
  ├── Step 5: agent_service.py — 事件发布替代直接调用                    ~15行修改
  ├── Step 6: logging.py — Prometheus指标记录集成                       ~10行修改
  └── Step 7: 5个Router — ResponseMapper集成                           每文件~5行修改

Phase 2: 前端架构升级 + 组件页面创建（共8步）
  ├── Step 8:  vdom.js + component.js                                  ~230行新增
  ├── Step 9:  Toast.js + Modal.js + TopNav.js + Breadcrumb.js         ~400行新增
  ├── Step 10: ChatBubble.js + ChatInput.js + AgentSidebar.js          ~450行新增
  ├── Step 11: FileUploadPanel.js + ChartDialog.js + CNKIDialog.js     ~360行新增
  ├── Step 12: SkillManager.js + SettingsPanel.js                      ~260行新增
  ├── Step 13: HomePage.js + ResearchTypePage.js + ReadinessPage.js    ~300行新增
  ├── Step 14: AgentPage.js                                            ~280行新增
  └── Step 15: SettingsPage.js                                         ~80行新增

Phase 3: 前端高级特性（共3步）
  ├── Step 16: wsClient.js + AgentPage流式渲染集成                     ~150行新增
  ├── Step 17: markdown.js + ChatBubble集成                             ~80行新增 + 修改
  └── Step 18: 拖拽上传 + 键盘快捷键                                    ~80行修改
```

---

## 七、文件变更汇总

| 操作 | 数量 | 说明 |
|------|------|------|
| 修改后端 | 10 | app.py / agent_service.py / dependencies.py / events.py / logging.py / 5个Router |
| 新增前端工具 | 3 | vdom.js / component.js / markdown.js |
| 新增前端组件 | 12 | Toast/Modal/TopNav/Breadcrumb/ChatBubble/ChatInput/AgentSidebar/FileUploadPanel/ChartDialog/CNKIDialog/SkillManager/SettingsPanel |
| 新增前端页面 | 5 | HomePage/ResearchTypePage/ReadinessPage/AgentPage/SettingsPage |
| 新增前端服务 | 1 | wsClient.js |
| **总变更** | **~3200行** | 后端~200行修改 + 前端~3000行新增 |

---

## 八、验证步骤

### 后端验证
1. `cd src/backend && python -m pytest tests/ -v` — 所有测试通过
2. `uvicorn src.backend.app:app --reload` — 启动无报错
3. `GET /api/v1/health` — 返回连接池状态
4. `GET /metrics` — 返回Prometheus格式指标
5. Redis限流（若Redis可用）正常工作
6. EventBus事件处理器正确注册和触发

### 前端验证
1. `cd src/frontend && npm install && npm run dev` — Vite启动，无import错误
2. 页面路由：点击学科卡片 → Hash变化 → 对应页面渲染
3. Agent对话页：发送消息 → HTTP请求到后端 → 展示回复
4. CNKI检索：打开CNKI对话框 → 搜索 → 结果卡片展示
5. 图表生成：选择图表类型 → 生成 → 预览展示
6. WebSocket流式对话：token逐字渲染
7. Markdown渲染：富文本格式正确展示
8. `npm run build` — `dist/` 生成压缩静态文件

---

## 九、假设与决策

1. **Redis为可选依赖**：分布式限流在Redis不可用时自动降级到内存令牌桶
2. **EventBus保持进程内实现**：不引入外部消息队列，发布事件后通过回调/state同步获取结果
3. **前端保持原生JavaScript**：不引入React/Vue框架，使用自研轻量虚拟DOM（~150行）
4. **虚拟DOM为简化版**：仅支持节点增删改和属性更新，不支持keyed diff
5. **Markdown渲染使用marked**：轻量级库（~20KB gzipped），通过npm安装
6. **组件生命周期基于MutationObserver**：利用浏览器原生API检测DOM挂载/卸载
7. **AgentPage为最复杂页面**：集成全部对话组件、功能组件、WebSocket、键盘快捷键