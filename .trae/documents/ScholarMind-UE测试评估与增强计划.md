# ScholarMind 用户体验测试评估与增强计划

## 一、测试概览

以重度AI学术研究使用者身份，通过 Playwright MCP 对 ScholarMind 交互原型进行了端到端用户体验测试，覆盖以下关键路径：

- 首页 → 学科选择（人文社科）→ 研究类型选择（质化研究）→ 研究阶段选择 → Agent对话
- CNKI文献检索体验
- 图表生成工具交互
- 设置页面（Skills管理、RAG知识库配置）
- 综述员/润色员/自定义Agent页面

---

## 二、当前产品优势

1. **学术暗色主题设计优秀**：暖暗色调 + Source Serif 4 衬线字体的学术氛围营造得当
2. **Agent体系完整**：研究员/审查员/架构师/综述员/润色员五角色覆盖学术全流程
3. **12种高级图表**：缎带图、小提琴图、冲积图等满足专业可视化需求
4. **CNKI集成**：对话中自动检测检索意图，模拟返回结构化文献结果
5. **自定义Skills**：用户可创建自定义技能文件
6. **文件上传**：支持5-15文件/会话，自动分类（研究计划/原始数据/参考文献）
7. **后端架构规范**：6层企业架构（middleware → core → models → db → routes → services）

---

## 三、发现的问题（按严重程度排序）

### 🔴 P0 — 阻塞性问题

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| 1 | **图表对话框未关闭导致页面交互被阻塞** | `chartDialog` overlay 在页面跳转后仍然显示，遮挡所有交互元素 | 用户打开图表对话框后切换页面，无法点击任何按钮 |
| 2 | **后端缺少依赖无法启动** | 缺少 `structlog`、`aiosqlite` 等模块 | 后端服务完全不可用，所有API调用失败 |
| 3 | **CNKI搜索使用Mock数据** | `mockCNKIDatabase` 仅5条预设数据 | 用户检索任何关键词都返回固定假数据，丧失CNKI真实检索能力 |

### 🟡 P1 — 体验关键问题

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| 4 | **聊天消息无持久化** | `sendMessage()` 不调用localStorage保存 | 页面刷新或切换Agent后对话历史全部丢失 |
| 5 | **缺少Markdown渲染** | `aiBubble.textContent = data.reply` | AI返回的学术文本无法展示标题、列表、加粗、引用等格式，阅读体验差 |
| 6 | **无加载状态区分** | 仅显示"思考中"三个点动画 | CNKI检索、图表生成、AI回复三种不同操作使用相同的loading样式 |
| 7 | **缺少错误恢复机制** | 后端不可用时仅显示简单报错 | 用户无法自行重试，不知道何处出问题 |
| 8 | **文件上传缺少进度反馈** | `handleFileUpload` 无进度条 | 上传大文件时用户不知道进度 |

### 🟢 P2 — 功能增强建议

| # | 建议 | 说明 |
|---|------|------|
| 9 | **对话导出功能** | 用户无法将Agent对话导出为Markdown/PDF，对学术写作流程不友好 |
| 10 | **引用管理** | 用户在对话中接收到的CNKI文献结果无法一键添加到文献管理 |
| 11 | **图表数据悬停详情** | Canvas生成的图表无tooltip，无法查看具体数据值 |
| 12 | **研究项目归档** | 多次对话无法组织为项目，缺乏研究进度追踪 |
| 13 | **键盘快捷键** | 缺乏 `Ctrl+Enter` 发送、`Ctrl+K` 搜索等学术工具常用快捷键 |
| 14 | **移动端适配不完整** | Agent对话页在移动端左侧栏/右侧栏布局未充分优化 |

---

## 四、修复与增强方案

### Phase 1 — 修复（P0+P1，立即执行）

#### 1.1 修复图表对话框遮挡问题
**文件**：`prototypes/interactive-prototype.html`
**方案**：在 `navigateTo()` 函数中自动关闭所有打开的对话框/overlay

```javascript
// 在 navigateTo() 函数开头添加
['chartDialog', 'cnkiDialog', 'createSkillDialog', 'confirmDialog'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.classList.add('hidden');
});
```

#### 1.2 修复后端依赖
**文件**：`src/backend/requirements.txt`
**方案**：补充缺失依赖

```
structlog>=24.0.0
aiosqlite>=0.20.0
```

并运行 `pip install -r requirements.txt`

#### 1.3 聊天消息持久化
**文件**：`prototypes/interactive-prototype.html`
**方案**：在 `sendMessage()` 中保存对话到localStorage，在 `navigateTo()` 时恢复

```javascript
// 保存对话
function saveChatHistory(agentId, messages) {
  const key = 'sm_chat_' + agentId;
  localStorage.setItem(key, JSON.stringify(messages.slice(-40))); // 保存最近20轮
}

// 恢复对话
function loadChatHistory(agentId) {
  const key = 'sm_chat_' + agentId;
  const data = localStorage.getItem(key);
  return data ? JSON.parse(data) : [];
}
```

#### 1.4 添加Markdown渲染
**文件**：`prototypes/interactive-prototype.html`
**方案**：引入轻量Markdown解析器（如marked.js CDN），在AI气泡中渲染Markdown

```html
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
```

```javascript
// 在 sendMessage 的 .then() 回调中
const content = data.reply || '抱歉，我暂时无法回复。';
aiBubble.innerHTML = marked.parse(content);
```

#### 1.5 区分加载状态
**文件**：`prototypes/interactive-prototype.html`
**方案**：为不同操作类型显示不同的loading文案和图标

- AI回复："正在思考您的问题..."
- CNKI检索："正在检索CNKI知网文献..."
- 图表生成："正在生成学术图表..."

#### 1.6 文件上传进度条
**文件**：`prototypes/interactive-prototype.html`
**方案**：使用 `XMLHttpRequest` 替代 `fetch` 以获取上传进度

---

### Phase 2 — 功能增强（P2）

#### 2.1 对话导出
**新增**：在Agent对话页右上角添加"导出对话"按钮，支持导出为Markdown和PDF

#### 2.2 研究项目系统
**新增**：允许用户创建"研究项目"，将多次对话、文件、图表归档到一个项目中

#### 2.3 图表交互增强
**优化**：Canvas图表添加tooltip悬浮数据详情、支持缩放和拖拽

#### 2.4 快捷键系统
**新增**：
- `Ctrl+Enter` 发送消息
- `Ctrl+K` 打开CNKI检索
- `Ctrl+G` 打开图表生成
- `Ctrl+N` 新建对话
- `Esc` 关闭所有弹窗

#### 2.5 移动端适配优化
**文件**：`prototypes/interactive-prototype.html`
**方案**：优化Agent对话页的移动端三栏布局，左侧/右侧栏改为底部Tab切换

---

### Phase 3 — 业务能力增强

#### 3.1 学术写作工作流
**新增**：在原型中添加"写作工作台"页面，整合：
- 左侧：文献大纲编辑器
- 中间：Markdown写作区
- 右侧：Agent辅助面板

#### 3.2 研究进度仪表盘
**新增**：在首页添加进度概览卡片，展示：
- 当前项目阶段
- 已检索文献数
- 已完成图表数
- Agent对话轮次

#### 3.3 协作与分享
**新增**：对话分享链接、图表导出为PPT/PDF

---

## 五、实施步骤

### Step 1：修复P0问题（预计覆盖3个文件）
1. `prototypes/interactive-prototype.html` — 对话框关闭 + 导航清理
2. `src/backend/requirements.txt` — 补充依赖
3. 运行 `pip install -r requirements.txt`

### Step 2：修复P1问题（预计覆盖1个文件）
4. `prototypes/interactive-prototype.html` — 消息持久化、Markdown渲染、加载状态、上传进度

### Step 3：P2增强（预计修改1个文件 + 新增功能）
5. `prototypes/interactive-prototype.html` — 导出对话、快捷键、移动端适配
6. 新增研究项目管理功能

### Step 4：验证
7. Playwright端到端回归测试
8. 后端服务启动验证

---

## 六、验证清单

- [ ] 后端服务可正常启动（`uvicorn src.backend.app:app`）
- [ ] 图表对话框关闭后页面交互正常
- [ ] CNKI检索返回真实数据（后端启动后）
- [ ] 对话刷新页面后不丢失
- [ ] AI回复支持Markdown渲染
- [ ] 文件上传有进度反馈
- [ ] 所有页面间导航无残留弹窗
- [ ] 移动端（375px宽度）可正常使用
- [ ] 键盘快捷键正常工作