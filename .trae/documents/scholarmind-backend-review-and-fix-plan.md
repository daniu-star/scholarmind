# ScholarMind 后端代码审查与修复计划

## 摘要

对 ScholarMind（基于 RAG+LangGraph 的智能学术研究助手）后端代码进行全面审查，围绕四大任务（文生图、文件上传、用户自定义 Skills、知网连接）识别出 **12 个关键问题** 和 **8 个改进建议**，并制定针对性修复方案。

---

## 一、当前状态分析

### 项目架构
```
src/backend/
├── app.py              # FastAPI 入口
├── config.py           # Pydantic Settings 配置
├── routers/
│   ├── agent.py        # Agent 对话路由
│   ├── chart.py        # 图表生成路由
│   ├── knowledge.py    # CNKI 知识库路由
│   ├── skills.py       # 技能管理路由
│   └── upload.py       # 文件上传路由
└── services/
    ├── agent_service.py   # Agent 核心服务（316行）
    ├── chart_service.py   # 图表生成服务（930行）
    ├── cnki_service.py    # CNKI 文献检索服务（459行）
    └── skills_service.py  # 技能管理服务（239行）
```

---

## 二、关键问题（Critical）

### 🔴 C1: 同步 OpenAI 客户端阻塞事件循环
**文件**: `src/backend/services/agent_service.py` L92, L132
**问题**: `AgentService.__init__` 使用同步 `OpenAI()` 客户端，`chat()` 方法中 `self.client.chat.completions.create()` 是同步调用，会阻塞整个 FastAPI 事件循环，导致所有并发请求挂起。
**修复**: 改用 `AsyncOpenAI` 客户端，使用 `await self.client.chat.completions.create()`。

### 🔴 C2: Agent 与图表生成完全未集成
**文件**: `src/backend/services/agent_service.py` L246-266
**问题**: `_detect_skills()` 检测到 "chart_generation" 后仅返回技能名称字符串，从未实际调用 `chart_service` 生成图表。用户与 Agent 讨论数据时，无法自动触发图表生成。
**修复**: 在 `chat()` 方法中增加技能执行逻辑，当检测到 chart_generation 时，调用 chart_service 生成图表并返回图表 URL。

### 🔴 C3: 文件上传最低5个限制不合理
**文件**: `src/backend/routers/upload.py` L19, L49-53
**问题**: `MIN_FILES = 5` 导致用户上传少于5个文件时被拒绝。需求是"支持5-15个文件"，而非"必须至少5个"。应允许1个文件上传，上限15个。
**修复**: 将 `MIN_FILES` 改为 1，或移除最低限制。

### 🔴 C4: 上传文件内容未与 Agent 对话集成
**文件**: `src/backend/routers/upload.py`, `src/backend/services/agent_service.py`
**问题**: 用户上传的文件（原始数据、研究设计等）仅被存储，Agent 对话时无法读取或分析这些文件内容，违背了"便于用户数据分析与讨论"的需求。
**修复**: 在 `chat()` 方法中增加 `session_id` 关联，自动加载该会话的上传文件内容并注入对话上下文。

### 🔴 C5: Skills 规则未注入 Agent 系统提示
**文件**: `src/backend/services/agent_service.py` L171-183
**问题**: `_build_system_prompt()` 仅拼接用户画像上下文，从未加载已启用的 Skills 规则。`_detect_skills()` 返回的技能名称也无后续处理。Skills 系统形同虚设。
**修复**: 在 `_build_system_prompt()` 中加载与当前 Agent 关联且已启用的 Skills 规则，追加到系统提示末尾。

### 🔴 C6: CNKI 直连爬取不可靠，缺少 MCP 集成
**文件**: `src/backend/services/cnki_service.py` L96-134
**问题**:
1. CNKI 有反爬机制（验证码、JS 渲染、频率限制），当前 HTTP POST 爬取在生产环境几乎必然失败
2. `CNKIConfigRequest` 定义了 `api_key` 字段但从未使用
3. 需求要求通过 API 或 MCP 工具连接知网，但当前无 MCP 集成
4. `ssl=False` 禁用了 SSL 验证，存在安全风险
**修复**:
1. 增加 CNKI 开发者 API 支持（如可用）
2. 集成 MCP 工具调用框架
3. 修复 `ssl=False` → 使用默认 SSL 验证
4. 增加请求频率限制和结果缓存

### 🔴 C7: 图表路由存在路径遍历漏洞
**文件**: `src/backend/routers/chart.py` L73-106
**问题**: `_resolve_data()` 接受用户提供的 `file_path` 参数，直接用 `Path(request.file_path)` 读取文件，无任何路径验证。攻击者可读取服务器任意文件（如 `/etc/passwd`、`.env`）。
**修复**: 验证 `file_path` 必须在 `UPLOAD_DIR` 或 `CHARTS_DIR` 内，使用 `resolve().relative_to()` 检查。

### 🔴 C8: pyyaml 未列入依赖
**文件**: `src/backend/requirements.txt`, `src/backend/services/skills_service.py` L1
**问题**: `skills_service.py` 导入了 `yaml`，但 `requirements.txt` 中缺少 `pyyaml` 依赖，运行时会 `ModuleNotFoundError`。
**修复**: 在 `requirements.txt` 中添加 `pyyaml>=6.0`。

### 🔴 C9: chart_service.py 超过 500 行且多处静默吞异常
**文件**: `src/backend/services/chart_service.py` L370-371, L643-651
**问题**:
1. 文件 930 行，远超 500 行上限，应按职责拆分
2. `bubble_kde_chart` 和 `scatter_density_chart` 中 `except Exception: pass` 静默吞掉错误
3. `_safe_array()` 对非数值数据会直接崩溃，无错误处理
**修复**: 拆分为 `chart_style.py`（样式）、`chart_data.py`（数据解析）、`chart_functions.py`（图表实现）、`chart_service.py`（主入口）；增加错误处理和日志。

### 🔴 C10: LangChain/LangGraph 已引入但未使用
**文件**: `src/backend/requirements.txt` L10-12, `src/backend/services/agent_service.py`
**问题**: 依赖中包含 `langchain`, `langchain-community`, `langgraph`，但代码中完全未使用。Agent 服务直接用 OpenAI 客户端，未利用 LangGraph 的状态图编排能力。
**修复**: 要么移除未使用的依赖，要么使用 LangGraph 重构 Agent 编排（推荐后者，与项目描述一致）。

### 🔴 C11: 对话历史存储在内存中，重启即丢失
**文件**: `src/backend/services/agent_service.py` L94
**问题**: `self.conversations: dict[str, list[dict]] = {}` 纯内存存储，服务器重启后所有对话历史丢失。
**修复**: 使用 SQLite 或 Redis 持久化对话历史，或至少增加文件系统持久化。

### 🔴 C12: CORS 配置允许所有来源
**文件**: `src/backend/app.py` L40
**问题**: `allow_origins=settings.CORS_ORIGINS + ["*"]` 等效于允许所有来源，存在 CSRF 攻击风险。
**修复**: 移除 `+ ["*"]`，仅允许配置的来源。

---

## 三、改进建议（Suggestions）

### 🟡 S1: 增加用户创建 Skills 的引导提示
**文件**: `src/backend/routers/skills.py`
**问题**: 当前 API 支持创建自定义 Skills，但缺少引导用户创建的提示机制和模板。
**修复**: 增加 `GET /api/skills/template` 端点返回技能模板，在 Agent 对话中当检测到用户需要新技能时主动提示。

### 🟡 S2: 上传路由未使用全局配置
**文件**: `src/backend/routers/upload.py` L17-21
**问题**: 硬编码 `UPLOAD_BASE`, `MAX_FILE_SIZE`, `MAX_FILES`, `MIN_FILES`, `ALLOWED_EXTENSIONS`，未使用 `config.py` 中的 `settings`。
**修复**: 改为从 `settings` 读取配置。

### 🟡 S3: Skills 目录路径硬编码
**文件**: `src/backend/services/skills_service.py` L6
**问题**: `SKILLS_DIR = "data/skills"` 硬编码，未使用 `settings.SKILLS_DIR`。
**修复**: 改为 `from ..config import settings; SKILLS_DIR = settings.SKILLS_DIR`。

### 🟡 S4: 增加文件内容提取与预览 API
**文件**: `src/backend/routers/upload.py`
**问题**: 上传的 PDF、DOCX 等文件内容无法被提取和预览，限制了 Agent 对上传文件的分析能力。
**修复**: 增加 `GET /api/upload/{session_id}/{file_name}/content` 端点，使用 `pypdf`/`python-docx` 提取文本内容。

### 🟡 S5: 增加 CNKI 搜索结果缓存
**文件**: `src/backend/services/cnki_service.py`
**问题**: 相同查询重复调用外部 API，浪费资源且增加被封禁风险。
**修复**: 使用 `functools.lru_cache` 或简单的 dict 缓存，TTL 30 分钟。

### 🟡 S6: 增加请求频率限制
**文件**: `src/backend/app.py`
**问题**: 无 API 请求频率限制，易被滥用。
**修复**: 集成 `slowapi` 或自定义中间件实现频率限制。

### 🟡 S7: 图表生成缺少 AI 智能推荐
**文件**: `src/backend/services/agent_service.py`
**问题**: 用户需要手动指定图表类型，缺少根据上下文自动推荐合适图表类型的智能机制。
**修复**: 在 Agent 对话中，当检测到 chart_generation 技能时，让 DeepSeek 根据数据特征推荐最合适的图表类型。

### 🟡 S8: 缺少用户认证系统
**文件**: 全局
**问题**: 无用户认证，任何人可访问所有 API 和其他用户的对话/文件。
**修复**: 增加 JWT 认证中间件（后续迭代）。

---

## 四、修复方案（按优先级排序）

### Phase 1: 关键安全与稳定性修复

| # | 修复项 | 涉及文件 | 具体操作 |
|---|--------|----------|----------|
| 1 | 修复事件循环阻塞 | `agent_service.py` | `OpenAI` → `AsyncOpenAI`，`create()` → `await create()` |
| 2 | 修复路径遍历漏洞 | `routers/chart.py` | `_resolve_data()` 增加路径白名单验证 |
| 3 | 修复 CORS 配置 | `app.py` | 移除 `+ ["*"]` |
| 4 | 添加 pyyaml 依赖 | `requirements.txt` | 添加 `pyyaml>=6.0` |
| 5 | 修复 SSL 验证 | `cnki_service.py` | `ssl=False` → `ssl=True`（默认值） |

### Phase 2: 四大任务核心功能补全

| # | 修复项 | 涉及文件 | 具体操作 |
|---|--------|----------|----------|
| 6 | Agent-图表集成 | `agent_service.py` | 增加 `_execute_skills()` 方法，调用 chart_service |
| 7 | 修复文件上传最低限制 | `upload.py` | `MIN_FILES = 5` → `MIN_FILES = 1` |
| 8 | 上传文件与 Agent 对话集成 | `agent_service.py`, `upload.py` | chat() 接收 session_id，自动加载上传文件内容注入上下文 |
| 9 | Skills 规则注入 Agent | `agent_service.py`, `skills_service.py` | `_build_system_prompt()` 加载已启用 Skills 规则 |
| 10 | CNKI MCP 集成 | `cnki_service.py`, `knowledge.py` | 增加 MCP 工具调用支持，增加结果缓存 |

### Phase 3: 代码质量与架构优化

| # | 修复项 | 涉及文件 | 具体操作 |
|---|--------|----------|----------|
| 11 | 拆分 chart_service.py | `services/chart_*.py` | 拆为4个文件，每个 < 300 行 |
| 12 | 上传路由使用全局配置 | `upload.py` | 从 settings 读取配置 |
| 13 | Skills 路径使用全局配置 | `skills_service.py` | 从 settings 读取 |
| 14 | 增加错误日志 | `chart_service.py` | 替换 `except: pass` 为日志记录 |
| 15 | LangGraph 集成或移除 | `agent_service.py`, `requirements.txt` | 使用 LangGraph StateGraph 重构 Agent 编排 |

---

## 五、验证步骤

1. **启动服务**: `cd src/backend && uvicorn app:app --reload`
2. **健康检查**: `GET /api/health` 返回 200
3. **Agent 对话**: `POST /api/agent/chat` 发送含数据关键词的消息，验证图表自动生成
4. **文件上传**: `POST /api/upload/{session_id}` 上传1个文件应成功（不再要求5个）
5. **Skills 注入**: 创建自定义 Skill 并启用，验证 Agent 回复中体现该 Skill 规则
6. **CNKI 搜索**: `POST /api/knowledge/cnki/search` 验证三级降级策略工作
7. **安全测试**: 尝试 `file_path: "../../../etc/passwd"` 应被拒绝
8. **并发测试**: 同时发送多个 Agent 请求，验证不再阻塞

---

## 六、假设与决策

1. **假设**: CNKI 无公开 API，直连爬取不可靠，优先使用 CrossRef/PubMed 降级 + MCP 工具扩展
2. **决策**: Phase 1 先修复安全与稳定性问题，Phase 2 补全四大任务功能，Phase 3 优化代码质量
3. **决策**: 对话持久化暂用 JSON 文件存储（轻量方案），后续迭代再引入数据库
4. **决策**: LangGraph 集成作为 Phase 3 可选项，当前先确保基本功能可用
5. **假设**: 用户上传文件内容提取需要额外依赖（pypdf, python-docx），在 Phase 2 中添加
