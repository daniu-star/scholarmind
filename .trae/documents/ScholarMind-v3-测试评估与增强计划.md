# ScholarMind v3 用户视角测试评估与增强计划

## 概述

以重度AI学术研究使用者身份，对 ScholarMind 智能学术研究助手进行全面测试评估。基于 Playwright 端到端测试发现的问题，从用户视角评判功能设计、页面互动、UX/UI，并针对性修复与功能拓展。

---

## 一、现有状态分析

### 1.1 已验证完成的P0/P1修复（代码确认）
| 功能 | 状态 | 位置 |
|------|------|------|
| 新建对话（newConversation） | 已完成 | 第5086行 |
| 导出对话（exportConversation） | 已完成 | 第5110行 |
| CNKI检索后端API优先 | 已完成 | executeCNKISearch() |
| 跨Agent上下文传递 | 已完成 | navigateTo() 第3306行 |
| 文件上传进度条（XMLHttpRequest） | 已完成 | handleFileUpload() 第3711行 |
| 图表数据来源选择（粘贴/文件） | 已完成 | openChartDialog() 第3913行 |
| 文件卡片展示 | 已完成 | handleFileUpload() |
| Markdown渲染（marked.js） | 已完成 | CDN已引入 |
| 聊天持久化（localStorage） | 已完成 | addChatRecord/loadChatHistory |
| 基本键盘快捷键（Ctrl+Enter, Esc） | 已完成 | 第5159行 |
| 研究状态持久化（saveToLocalStorage） | 已完成 | 第3610行 |

### 1.2 当前仍存在的问题（用户视角发现）

#### 🔴 P0 阻塞性 — 影响核心使用流程

| # | 问题 | 影响 | 位置 |
|---|------|------|------|
| 1 | **研究进度追踪器为纯静态展示** | 5个Agent页面的进度追踪器（选题→问题建构→文献综述→研究设计→论文撰写）全部硬编码，无论用户做了什么操作，进度永远显示"问题建构"为当前步骤。用户无法感知研究推进。 | 5个Agent页面的右侧栏 `.progress-tracker-item` |
| 2 | **设置页LangGraph/记忆/主题面板无实际功能** | LangGraph面板仅静态展示工作流图；记忆面板的"删除"按钮无onclick；主题设置选中后不持久化；"清除所有记忆"按钮回调为空函数。用户无法管理自己的数据和偏好。 | 第2854-3080行 |
| 3 | **移动端375px宽度下三栏布局崩溃** | 左侧栏和右侧栏堆叠在对话区上方，对话区只有约200px高度可用，聊天输入框被遮挡无法操作。 | 第1135-1144行 @media (max-width: 768px) |

#### 🟡 P1 体验关键问题

| # | 问题 | 影响 | 位置 |
|---|------|------|------|
| 4 | **缺少扩展键盘快捷键** | Ctrl+K(CNKI)、Ctrl+G(图表)、Ctrl+N(新建)、Ctrl+S(导出)、Ctrl+1~5(切换Agent)未实现，重度用户效率受限 | 第5159-5175行键盘事件 |
| 5 | **CNKI检索结果无"保存到文献库"功能** | 用户检索到相关文献后无法收藏管理，每次需要重新检索 | CNKI检索结果面板 |
| 6 | **文件上传后无法在右侧栏查看文件摘要** | 上传文件后仅在对话中显示文件卡片，右侧栏的"已上传文件"面板（injectFilePanels）与对话中的文件卡片不同步 | handleFileUpload() + injectFilePanels() |
| 7 | **对话历史无法跨会话查看** | 用户关闭页面后重新打开，只能看到当前会话的对话，无法查看历史对话记录 | localStorage 结构 |

#### 🟢 P2 功能增强建议

| # | 建议 | 说明 |
|---|------|------|
| 8 | **研究项目管理系统** | 将多次对话、上传文件、生成图表归档到项目，追踪进度 |
| 9 | **写作工作台** | Markdown编辑器 + Agent对话面板并排，支持边对话边写作 |
| 10 | **对话历史侧边栏** | 左侧栏显示历史对话列表，支持搜索和切换 |
| 11 | **文献引用管理** | CNKI检索结果一键保存到文献库，支持BibTeX导出 |
| 12 | **Agent链式协作模式** | 研究员→审查员→架构师→综述员→润色员的流水线模式 |
| 13 | **智能文献推荐** | 基于对话内容主动推荐相关文献 |

---

## 二、修复与增强方案

### Phase 1：P0 阻塞性修复（必须立即修复）

#### 1.1 研究进度追踪器动态化
**文件**：`prototypes/interactive-prototype.html`

**问题**：5个Agent页面的进度追踪器全部硬编码，`tracker-done`/`tracker-current`/`tracker-pending` 类名静态写死。

**方案**：
1. 创建 `updateProgressTracker(pageId)` 函数，根据用户行为动态更新进度
2. 进度状态保存到 localStorage（key: `scholarmind_progress`）
3. 触发时机：用户在研究员对话中明确选题 → 标记"选题方向"完成；用户在审查员对话中完成审查 → 标记"问题建构"完成；架构师对话中通过架构 → 标记"研究设计"完成
4. 在 `sendMessage()` 中检测用户输入关键词（如"选题""研究问题""文献综述""研究设计""论文"），自动推进进度
5. 页面加载时从 localStorage 恢复进度状态

**进度状态数据结构**：
```javascript
var researchProgress = {
  'topic': 'done',        // 选题方向
  'problem': 'current',   // 问题建构
  'literature': 'pending', // 文献综述
  'design': 'pending',    // 研究设计
  'writing': 'pending'    // 论文撰写
};
```

**实现步骤**：
- 创建 `initProgressTracker()` 从 localStorage 加载进度
- 创建 `updateProgressTracker(agentId)` 根据当前Agent更新所有页面进度条
- 创建 `advanceProgress(stage)` 推进到下一阶段
- 在 `sendMessage()` 中检测关键词自动推进
- 在 `navigateTo()` 中调用 `updateProgressTracker()`

#### 1.2 设置页功能补全
**文件**：`prototypes/interactive-prototype.html`

**LangGraph配置面板**（第2854-2916行）：
- 添加"工作流引擎"启停按钮（toggle开关）
- 将"最大并行检索数""请求超时""重试次数"的 input 值保存到 localStorage
- 保存按钮增加实际保存逻辑

**Agent记忆面板**（第2919-2962行）：
- 为每个记忆项的"删除"按钮添加 onclick 事件
- "清除所有记忆"按钮添加实际清除逻辑（清除所有Agent的localStorage对话记录）
- 记忆使用量从硬编码改为从 localStorage 实际计算

**主题设置面板**（第3065-3080行）：
- `selectThemeCard()` 添加持久化逻辑（保存到 localStorage）
- 页面加载时从 localStorage 恢复主题选择
- 添加字体大小调整滑块（影响到 `html { font-size }`）

#### 1.3 移动端响应式优化
**文件**：`prototypes/interactive-prototype.html`

**方案**：
- 在 `≤768px` 下，将三栏布局改为单栏 + 底部Tab切换
- 左侧栏内容（Agent列表、文献检索）折叠为底部弹出面板
- 右侧栏内容（进度追踪、文件列表）折叠为可滑出的抽屉
- 聊天输入区固定在底部，增大触摸区域
- 添加移动端汉堡菜单按钮切换侧栏
- 在 `≤480px` 下进一步优化字体大小和间距
- 确保 `.chat-input-area` 在移动端不被键盘遮挡

---

### Phase 2：P1 体验优化

#### 2.1 扩展键盘快捷键
**文件**：`prototypes/interactive-prototype.html`

在现有键盘事件监听器（第5159行）中扩展：

| 快捷键 | 功能 | 实现 |
|--------|------|------|
| `Ctrl+K` | 打开CNKI检索对话框 | `openCNKIDialog()` |
| `Ctrl+G` | 打开图表生成对话框 | `openChartDialog(activePage.id)` |
| `Ctrl+N` | 新建对话 | `newConversation(activePage.id)` |
| `Ctrl+S` | 导出对话 | `exportConversation(activePage.id)` |
| `Ctrl+1~5` | 快速切换Agent | `navigateTo(agents[index])` |
| `Ctrl+Shift+F` | 聚焦搜索框 | 聚焦当前页面的文献搜索输入框 |

#### 2.2 CNKI检索结果保存到文献库
**文件**：`prototypes/interactive-prototype.html`

**方案**：
- 在 `createCNKIResultItem()` 中添加"保存到文献库"按钮
- 使用 localStorage 存储文献库（key: `scholarmind_library`）
- 在设置页新增"我的文献库"面板
- 支持文献库导出为 BibTeX 格式
- 在对话中引用文献时自动从文献库检索

#### 2.3 文件面板实时同步
**文件**：`prototypes/interactive-prototype.html`

**问题**：`handleFileUpload()` 在对话中显示文件卡片，但 `injectFilePanels()` 创建的右侧栏文件面板不同步。

**方案**：
- 在 `handleFileUpload()` 上传成功后调用 `updateFilePanel(agentId)` 同步更新
- 右侧栏文件面板显示文件摘要（前100字符预览）
- 文件面板与对话中的文件卡片保持数据一致

---

### Phase 3：P2 功能增强

#### 3.1 研究项目管理系统
**新增功能**：在首页添加"我的项目"入口

**方案**：
- 使用 localStorage 存储项目数据（key: `scholarmind_projects`）
- 项目数据结构：`{ id, name, discipline, description, sessions: [], files: [], charts: [], createdAt, updatedAt }`
- 首页新增"我的项目"卡片区域，显示最近3个项目
- 点击"新建项目"弹窗输入项目信息
- 在Agent页面的"新建对话"按钮旁增加"关联到项目"下拉选择
- 项目页面显示关联的对话、文件、图表

#### 3.2 写作工作台
**新增页面**：`writing-workspace`

**方案**：
- 左侧：Markdown 编辑器（textarea + 预览切换）
- 右侧：Agent对话面板（可切换Agent）
- 支持从对话中引用内容插入到编辑器
- 支持导出为 .md 文件
- 导航栏新增"写作工作台"按钮

**实现**：
- 在 `interactive-prototype.html` 中新增 `writing-workspace` page div
- 添加 `switchToWritingWorkspace()` 函数
- Markdown编辑器使用简单的 textarea + 实时预览
- 对话面板复用现有Agent对话逻辑

#### 3.3 对话历史侧边栏
**优化**：在Agent页面左侧栏增加"历史对话"列表

**方案**：
- 使用 localStorage 存储对话元数据（key: `scholarmind_conversations`）
- 对话元数据：`{ id, agentId, title, preview, messageCount, createdAt }`
- 左侧栏"历史对话"区域显示最近10条对话
- 点击切换会话，加载对应对话记录
- 支持搜索历史对话（按标题/内容关键词）

#### 3.4 文献引用管理
**增强**：完整的文献库管理功能

**方案**：
- localStorage 存储文献库（key: `scholarmind_library`）
- 文献数据结构：`{ id, title, author, year, source, abstract, citations, tags, addedAt }`
- 设置页新增"我的文献库"面板（与RAG知识库并列）
- 文献库面板：列表展示、搜索过滤、标签分类、批量删除
- 导出功能：BibTeX格式下载
- 在对话中通过 `@文献标题` 语法引用文献库中的文献

---

### Phase 4：验证

#### 4.1 Playwright端到端回归测试
**方案**：
- 使用 Playwright MCP 工具进行自动化测试
- 测试路径：首页 → 学科选择 → 研究类型 → Agent对话 → CNKI检索 → 图表生成 → 文件上传 → 导出对话 → 设置页
- 验证移动端响应式布局（设置为375px视口）
- 验证键盘快捷键功能
- 验证localStorage持久化

#### 4.2 后端服务启动验证
**方案**：
- 启动 FastAPI 后端服务
- 验证所有路由注册正确
- 测试 Agent chat API 端点
- 测试文件上传 API 端点
- 测试 CNKI 检索 API 端点

---

## 三、实施步骤

### Step 1：P0 阻塞性修复（~500行代码）
1. 研究进度追踪器动态化 — 创建进度管理函数，绑定到sendMessage和navigateTo
2. 设置页功能补全 — LangGraph启停/记忆删除/主题持久化/字体调整
3. 移动端响应式优化 — 三栏→单栏+底部Tab，聊天输入固定

### Step 2：P1 体验优化（~300行代码）
4. 扩展键盘快捷键 — Ctrl+K/G/N/S/1~5
5. CNKI检索结果保存到文献库
6. 文件面板实时同步

### Step 3：P2 功能增强（~600行代码）
7. 研究项目管理系统 — 首页项目卡片、创建/关联项目
8. 写作工作台 — 新页面Markdown编辑器+Agent对话
9. 对话历史侧边栏 — 左侧栏历史列表
10. 文献引用管理 — 文献库面板、BibTeX导出

### Step 4：验证（~200行代码）
11. Playwright端到端回归测试
12. 后端服务启动验证

---

## 四、验证清单

- [ ] 研究进度在对话推进后自动更新，刷新后保持
- [ ] 设置页LangGraph启停按钮可切换
- [ ] 设置页记忆删除按钮可删除单条记忆
- [ ] 设置页主题选择持久化
- [ ] 移动端375px宽度下三栏变为单栏布局
- [ ] 移动端聊天输入框不被键盘遮挡
- [ ] Ctrl+K打开CNKI检索
- [ ] Ctrl+G打开图表生成
- [ ] Ctrl+N新建对话
- [ ] Ctrl+S导出对话
- [ ] Ctrl+1~5切换Agent
- [ ] CNKI检索结果可保存到文献库
- [ ] 文件上传后右侧栏文件面板同步更新
- [ ] 研究项目可创建、关联对话
- [ ] 写作工作台可编辑Markdown并导出
- [ ] 对话历史侧边栏可切换历史对话
- [ ] 文献库可保存和导出BibTeX
- [ ] 后端服务正常启动，所有路由可访问

---

## 五、技术决策

1. **存储方案**：全部使用 localStorage 作为前端持久化方案，与现有架构（saveToLocalStorage、addChatRecord）保持一致
2. **进度追踪**：基于关键词匹配自动推进 + 用户手动标记，双模式互补
3. **写作工作台**：使用 textarea + 简单Markdown预览，不引入CodeMirror等重型编辑器
4. **移动端适配**：纯CSS媒体查询 + JavaScript动态切换布局，不引入移动端框架
5. **文献库**：localStorage存储，BibTeX纯文本生成，Blob下载
6. **键盘快捷键**：在输入框聚焦时仅Ctrl+Enter生效，避免与文本编辑冲突