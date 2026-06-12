# ScholarMind v2 用户视角增强计划

## 概述

以重度AI学术研究使用者身份，对 ScholarMind 交互原型进行了全面遍历审查。基于已有工作（P0/P1 修复已完成），本计划聚焦于**从用户视角发现的新问题**和**业务能力增强**，按优先级分四个阶段实施。

---

## 一、现有状态分析

### 已完成的修复（前一阶段）
- P0：对话框遮挡、后端依赖补充
- P1：聊天持久化（localStorage）、Markdown 渲染（marked.js）、上传进度条（XMLHttpRequest）、错误恢复
- 12种高级图表类型（Canvas + matplotlib）
- CNKI 检索集成（前端 mock + 后端真实 API 分离）
- 自定义 Skills 管理

### 当前仍存在的问题（用户视角发现）

#### 🔴 阻塞性问题（影响核心使用流程）

| # | 问题 | 影响 | 位置 |
|---|------|------|------|
| 1 | **"新建对话"按钮无功能** | 所有 Agent 页面左侧栏的"新建对话"按钮无 onclick，用户无法开始新对话 | 5个 Agent 页面（researcher/reviewer/architect/synthesizer/polisher） |
| 2 | **"导出对话"按钮无功能** | 用户无法导出对话内容，学术写作流程中断 | 同上 |
| 3 | **CNKI 前端使用完全 mock 数据** | mockCNKIDatabase 仅 5 个关键词，用户检索任何内容都返回固定假数据 | `getMockCNKIResults()` 函数 |
| 4 | **Agent 切换后对话上下文丢失** | 从研究员切换到审查员时，之前的对话历史不共享，用户需要重复描述研究背景 | `navigateTo()` 不跨 Agent 传递上下文 |

#### 🟡 体验关键问题

| # | 问题 | 影响 | 位置 |
|---|------|------|------|
| 5 | **无键盘快捷键** | 重度用户无法用 `Ctrl+Enter` 发送、`Esc` 关闭弹窗，效率极低 | 全局 |
| 6 | **研究进度追踪器为静态数据** | 右侧栏的进度追踪（选题→问题建构→文献综述→研究设计→论文撰写）是硬编码状态 | 所有 Agent 页面右侧栏 |
| 7 | **图表对话框无法选择数据类型** | 打开图表生成时，用户只能看到 12 种图表类型，但无法指定用哪份上传的数据生成 | `openChartDialog()` |
| 8 | **文件上传后缺少可视化反馈** | 上传文件后仅在对话中显示文件名，用户看不到文件内容摘要、分类标签 | `handleFileUpload()` |
| 9 | **设置页多个面板为纯展示** | LangGraph 配置、Agent 记忆、主题设置面板仅有 UI 无实际功能 | 设置页 |
| 10 | **移动端三栏布局崩溃** | Agent 对话页在 375px 宽度下左侧栏/右侧栏遮挡对话区 | 响应式 CSS |

#### 🟢 功能增强建议

| # | 建议 | 说明 |
|---|------|------|
| 11 | **对话导出（Markdown/PDF/Word）** | 学术写作核心需求，用户需要将 Agent 对话导出为可编辑文档 |
| 12 | **研究项目管理系统** | 将多次对话、上传文件、生成图表归档到研究项目中，追踪进度 |
| 13 | **写作工作台** | 在 Agent 对话基础上增加 Markdown 编辑器，支持边对话边写作 |
| 14 | **文献引用管理** | CNKI 检索结果可一键保存到个人文献库，支持 BibTeX/EndNote 导出 |
| 15 | **对话历史侧边栏** | 左侧显示历史对话列表，支持搜索和切换 |
| 16 | **Agent 链式协作** | 研究员→审查员→架构师→综述员→润色员的流水线模式 |
| 17 | **图表数据绑定** | 将上传的数据文件与图表生成关联，使用真实数据而非样本数据 |

---

## 二、修复与增强方案

### Phase 1：修复阻塞性问题（P0，必须立即修复）

#### 1.1 实现"新建对话"功能
**文件**：`prototypes/interactive-prototype.html`
**方案**：为所有 Agent 页面的"新建对话"按钮添加 `onclick`，生成新 session_id，清除当前对话显示，保留学科/研究类型上下文。

```javascript
function newConversation(agentId) {
  currentSessionId = 'sm_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
  // 清除对话显示
  var chatMessages = document.querySelector('#' + agentId + ' .chat-messages');
  if (chatMessages) {
    var bubbles = chatMessages.querySelectorAll('.chat-bubble:not(.welcome-bubble)');
    bubbles.forEach(function(b) { b.remove(); });
    chatMessages.querySelectorAll('.chat-options, .typing-indicator').forEach(function(el) { el.remove(); });
    // 显示欢迎消息
    var welcome = document.getElementById(agentId + 'Welcome');
    if (welcome) welcome.style.display = '';
  }
  // 清除 localStorage 中的对话历史
  clearChatHistory(agentId);
  showToast('新对话已创建', 'success');
}
```

#### 1.2 实现"导出对话"功能
**文件**：`prototypes/interactive-prototype.html`
**方案**：为"导出对话"按钮添加 `onclick`，将当前对话导出为 Markdown 文件下载。

```javascript
function exportConversation(agentId) {
  var records = loadChatHistory(agentId);
  if (records.length === 0) {
    showToast('当前对话为空，无法导出', 'warning');
    return;
  }
  
  var md = '# ScholarMind 对话记录\n\n';
  md += '> 导出时间：' + new Date().toLocaleString() + '\n';
  md += '> 学科：' + currentDisciplineName + ' | 研究类型：' + currentResearchTypeName + '\n\n---\n\n';
  
  records.forEach(function(record) {
    if (record.role === 'user') {
      md += '**👤 用户**：\n\n' + record.content + '\n\n';
    } else {
      md += '**🤖 AI**：\n\n' + record.content + '\n\n';
    }
  });
  
  var blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url;
  a.download = 'scholarmind-conversation-' + new Date().toISOString().slice(0, 10) + '.md';
  a.click();
  URL.revokeObjectURL(url);
  showToast('对话已导出为 Markdown', 'success');
}
```

#### 1.3 接入真实 CNKI 后端 API
**文件**：`prototypes/interactive-prototype.html`
**方案**：修改 `getMockCNKIResults` 为优先调用后端 API，fallback 到 mock 数据。
- 修改 `handleCNKIQueryInChat` 中的逻辑，确保后端可用时使用真实数据
- 在 `openCNKIDialog` 中也添加后端优先策略

#### 1.4 跨 Agent 上下文传递
**文件**：`prototypes/interactive-prototype.html`
**方案**：在 `navigateTo()` 中，当切换到另一个 Agent 时，自动将当前研究上下文（学科、研究类型、研究阶段）作为首条系统消息注入新 Agent 的对话中。

---

### Phase 2：体验优化（P1）

#### 2.1 键盘快捷键系统
**文件**：`prototypes/interactive-prototype.html`
**方案**：添加全局键盘事件监听

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Enter` | 发送当前输入框消息 |
| `Esc` | 关闭所有弹窗/对话框 |
| `Ctrl+K` | 打开 CNKI 检索对话框 |
| `Ctrl+G` | 打开图表生成对话框 |
| `Ctrl+N` | 新建对话 |
| `Ctrl+S` | 导出对话 |
| `Ctrl+1~5` | 快速切换 Agent（研究员/审查员/架构师/综述员/润色员） |

#### 2.2 研究进度追踪器动态化
**文件**：`prototypes/interactive-prototype.html`
**方案**：将进度追踪状态保存到 localStorage，在对话中根据用户行为自动推进进度。
- 当用户在研究员对话中明确选题方向后，自动标记"选题方向"为完成
- 当架构师审查通过论文架构后，自动标记"论文架构"为完成
- 进度状态在页面刷新后保持

#### 2.3 图表生成与上传数据绑定
**文件**：`prototypes/interactive-prototype.html`
**方案**：在 `openChartDialog()` 中增加"数据来源"选择：
- 使用上传的文件数据
- 使用示例数据
- 手动输入数据（JSON）

#### 2.4 文件上传后可视化反馈增强
**文件**：`prototypes/interactive-prototype.html`
**方案**：上传完成后在对话中显示文件卡片，包含：
- 文件名、大小、类型标签
- 文件内容预览（前 200 字符）
- 删除按钮

#### 2.5 设置页功能补全
**文件**：`prototypes/interactive-prototype.html`
**方案**：
- **LangGraph 配置**：添加工作流引擎启停按钮、超时设置滑块
- **Agent 记忆**：添加记忆容量调整、清除记忆按钮
- **主题设置**：添加字体大小调整、紧凑/舒适模式切换

---

### Phase 3：功能增强（P2）

#### 3.1 研究项目管理系统
**新增功能**：在首页添加"我的项目"入口，支持：
- 创建研究项目（项目名称、学科、描述）
- 关联对话会话到项目
- 查看项目进度概览
- 项目内文件管理

**实现**：使用 localStorage 存储项目数据，在首页添加项目卡片列表。

#### 3.2 写作工作台
**新增页面**：`writing-workspace`
- 左侧：Markdown 编辑器（使用简单的 contenteditable 或 textarea）
- 右侧：Agent 对话面板（可切换 Agent）
- 支持从对话中引用内容插入到编辑器
- 支持导出为 .md/.docx 文件

**实现**：在 `interactive-prototype.html` 中新增 writing-workspace 页面，使用简单的 Markdown 编辑区。

#### 3.3 对话历史侧边栏
**优化**：在 Agent 页面左侧栏增加"历史对话"列表
- 显示最近 10 条对话摘要（首条用户消息的前 30 字）
- 点击可切换对话
- 支持搜索历史对话

**实现**：使用 localStorage 存储对话元数据，在左侧栏渲染列表。

#### 3.4 文献引用管理
**增强**：在 CNKI 检索结果中增加"保存到文献库"按钮
- 使用 localStorage 存储文献数据
- 在设置页新增"我的文献库"面板
- 支持 BibTeX/EndNote/CSL 格式导出

#### 3.5 移动端响应式优化
**文件**：`prototypes/interactive-prototype.html`
**方案**：
- 在 ≤768px 宽度下，三栏布局改为单栏 + 底部 Tab 切换
- 左侧栏和右侧栏内容折叠为底部弹出面板
- 优化聊天输入区在移动端的触摸体验

---

### Phase 4：业务能力突破

#### 4.1 Agent 链式协作模式
**新增**：在首页增加"一键启动研究流程"按钮
- 用户输入研究主题后，自动按顺序调用：研究员（选题）→ 审查员（审查）→ 架构师（架构）→ 综述员（综述）→ 润色员（润色）
- 每个阶段完成后自动进入下一阶段，用户可在任意阶段介入
- 最终生成完整的研究报告

#### 4.2 智能文献推荐
**增强**：基于用户的研究主题和对话历史，在对话中主动推荐相关文献
- 使用 CNKI 后端 API 进行语义检索
- 在对话气泡中嵌入文献推荐卡片

---

## 三、实施步骤

### Step 1：修复阻塞性问题（~500 行代码）
1. 实现"新建对话"功能 — 为 5 个 Agent 页面按钮添加 onclick
2. 实现"导出对话"功能 — 导出为 Markdown 文件
3. 前端 CNKI 检索优先调用后端 API
4. 跨 Agent 上下文传递

### Step 2：体验优化（~400 行代码）
5. 键盘快捷键系统
6. 研究进度追踪器动态化
7. 图表数据来源选择
8. 文件上传可视化卡片
9. 设置页功能补全

### Step 3：功能增强（~600 行代码）
10. 研究项目管理系统
11. 写作工作台页面
12. 对话历史侧边栏
13. 文献引用管理
14. 移动端响应式优化

### Step 4：验证
15. Playwright 端到端回归测试
16. 后端服务启动验证
17. 跨浏览器兼容性检查

---

## 四、验证清单

- [ ] "新建对话"按钮点击后创建新对话并清除旧消息
- [ ] "导出对话"按钮点击后下载 .md 文件
- [ ] CNKI 检索在后端可用时返回真实数据
- [ ] 从研究员切换到审查员后，审查员了解用户的研究背景
- [ ] `Ctrl+Enter` 可发送消息
- [ ] `Esc` 可关闭所有弹窗
- [ ] 研究进度在对话推进后自动更新
- [ ] 图表生成可选择上传的数据文件
- [ ] 文件上传后显示文件卡片
- [ ] 设置页 LangGraph/记忆/主题面板可操作
- [ ] 研究项目可创建、关联对话
- [ ] 写作工作台可编辑 Markdown 并导出
- [ ] 对话历史侧边栏可切换历史对话
- [ ] 文献库可保存和导出
- [ ] 移动端（375px）可正常使用

---

## 五、技术决策

1. **存储方案**：使用 localStorage 作为前端持久化方案（与现有架构一致），后端保持文件系统 + SQLite 双模式
2. **Markdown 导出**：使用纯 JavaScript 生成 Markdown 文本，通过 Blob 下载，不引入额外依赖
3. **写作工作台**：使用 contenteditable div + 简单的 Markdown 快捷键，不引入完整编辑器框架
4. **移动端适配**：使用 CSS 媒体查询，不引入移动端框架
5. **键盘快捷键**：使用 `keydown` 事件，在输入框聚焦时特殊处理（如 Ctrl+Enter 发送而非换行）