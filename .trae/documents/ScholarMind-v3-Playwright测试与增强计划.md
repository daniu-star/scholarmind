# ScholarMind v3 Playwright端到端测试与增强计划

## 概述

以重度AI学术研究使用者身份，使用 Playwright MCP 对 ScholarMind 智能学术研究助手进行从头到尾的端到端测试。基于测试发现，从用户视角评判功能设计、页面互动、UX/UI，并针对性修复与功能拓展。

---

## 一、现有状态分析

### 1.1 已完成功能确认（代码审查）

| 功能 | 状态 | 位置 |
|------|------|------|
| 研究进度追踪器动态化 | 已完成 | interactive-prototype.html 第3232-3339行 |
| 设置页LangGraph配置（启停/保存） | 已完成 | 第3028-3059行 |
| 设置页Agent记忆管理（删除/清除） | 已完成 | 第3062-3078行 |
| 设置页主题持久化（深色/浅色/字体/强调色） | 已完成 | 第3784-3839行 |
| 移动端底部Tab导航 | 已完成 | 第1158-1190行 CSS |
| 键盘快捷键（Ctrl+K/G/N/S/1~5/Enter/Esc） | 已完成 | 第5882-5931行 |
| CNKI检索结果保存到文献库 | 已完成 | 第5062-5168行 |
| 文献库BibTeX导出 | 已完成 | 第5108-5137行 |
| 研究项目管理系统 | 已完成 | 第4072-4220行 |
| 写作工作台（Markdown编辑器+Agent对话） | 已完成 | 第5758-5870行 |
| 聊天持久化（localStorage） | 已完成 | addChatRecord/loadChatHistory |
| Markdown渲染（marked.js CDN） | 已完成 | 第15行 |
| 文件上传进度条（XMLHttpRequest） | 已完成 | handleFileUpload() |
| 图表对话框（粘贴/文件数据源） | 已完成 | openChartDialog() |
| 跨Agent上下文传递 | 已完成 | navigateTo() |
| 新建对话/导出对话 | 已完成 | newConversation/exportConversation |

### 1.2 需要Playwright验证的关键交互路径

以下路径需要通过Playwright端到端测试验证，而非仅静态代码审查：

1. **首页 → 学科选择 → 研究类型 → Agent对话**：完整用户入门流程
2. **Agent对话 → CNKI检索 → 结果保存**：CNKI集成链路
3. **Agent对话 → 图表生成 → 数据来源选择**：图表功能链路
4. **文件上传 → 进度反馈 → 文件卡片展示**：上传体验链路
5. **设置页面板切换 → LangGraph配置 → 主题切换**：设置功能链路
6. **写作工作台 → Markdown编辑 → 预览切换 → Agent互动**：写作功能链路
7. **研究项目创建 → 关联对话 → 项目卡片展示**：项目管理链路
8. **移动端375px视口 → 底部Tab切换 → 聊天区可用性**：响应式链路
9. **键盘快捷键操作（Ctrl+K/G/N/S/1~5/Enter）**：快捷键链路
10. **localStorage持久化 → 刷新后状态恢复**：数据持久化链路

---

## 二、Playwright端到端测试方案

### Step 1：启动本地HTTP服务器

使用Python的http.server在本地启动静态文件服务器，端口8080：
```bash
cd c:\Users\13067\Desktop\AI产品\prototypes
python -m http.server 8080
```

### Step 2：完整交互路径测试

#### 测试路径A：用户入门流程（首页 → 学科 → 研究类型 → 对话）
1. `browser_navigate` 到 `http://localhost:8080/interactive-prototype.html`
2. `browser_snapshot` 获取首页结构
3. `browser_take_screenshot` 首页截图
4. 点击"人文社科"学科卡片
5. 点击研究类型（如"质化研究"）
6. 点击"我暂未有思路"选项
7. 进入研究员Agent页面
8. 截图对话界面

#### 测试路径B：CNKI检索链路
1. 在Agent页面按 `Ctrl+K` 打开CNKI检索
2. 输入检索关键词
3. 点击搜索
4. 验证搜索结果展示
5. 点击"保存到文献库"按钮
6. 验证Toast提示

#### 测试路径C：图表生成链路
1. 在Agent页面按 `Ctrl+G` 打开图表对话框
2. 选择"粘贴数据"标签
3. 输入测试数据
4. 选择图表类型
5. 点击生成

#### 测试路径D：文件上传链路
1. 点击文件上传按钮
2. 选择测试文件上传
3. 验证进度条展示
4. 验证文件卡片展示

#### 测试路径E：设置页功能
1. 导航到设置页
2. 切换设置面板（LangGraph → 记忆 → Skills → 主题）
3. 修改LangGraph配置并保存
4. 切换主题
5. 调整字体大小

#### 测试路径F：写作工作台
1. 导航到写作工作台
2. 在编辑器输入Markdown文本
3. 切换到预览模式
4. 在对话框发送消息
5. 验证Agent回复

#### 测试路径G：移动端响应式
1. `browser_resize` 到 375x812（iPhone 尺寸）
2. 验证底部Tab导航是否显示
3. 点击各Tab切换
4. 验证聊天输入框在视口内

#### 测试路径H：键盘快捷键
1. Ctrl+1~5 快速切换Agent
2. Ctrl+K 打开CNKI检索
3. Ctrl+G 打开图表生成
4. Ctrl+N 新建对话
5. Ctrl+Enter 发送消息
6. Esc 关闭弹窗

#### 测试路径I：数据持久化
1. 发送一条对话消息
2. 保存主题设置
3. `browser_navigate` 刷新页面
4. 验证对话记录恢复
5. 验证主题设置恢复
6. 验证研究进度恢复

### Step 3：后端服务验证
1. 启动FastAPI后端服务：`cd c:\Users\13067\Desktop\AI产品 && python -m src.backend.app`
2. 验证健康检查端点：`GET /api/v1/health`
3. 验证Agent chat API：`POST /api/v1/agent/chat`
4. 验证文件上传API：`POST /api/v1/upload/`

---

## 三、预期发现的问题（用户视角预测）

### 🔴 高优先级（影响核心体验）

| # | 预测问题 | 验证方法 |
|---|---------|---------|
| 1 | Agent对话选项中"建议生成学术图表"按钮可能无响应（需要mock后端） | 点击对话中的选项按钮 |
| 2 | 跨Agent切换时对话上下文可能丢失 | Ctrl+1~5切换Agent后检查对话区 |
| 3 | 移动端聊天输入框可能被虚拟键盘遮挡 | 测试时focus输入框并检查滚动 |
| 4 | 文件上传超过15个时可能无限制提示 | 上传测试 |

### 🟡 中优先级（影响使用效率）

| # | 预测问题 | 验证方法 |
|---|---------|---------|
| 5 | 写作工作台中Agent对话与主Agent对话可能数据不同步 | 分别测试两处对话 |
| 6 | CNKI检索结果中的"引用到对话"按钮功能完整性 | 点击引用按钮 |
| 7 | 研究项目删除操作缺少二次确认 | 测试删除项目 |
| 8 | 文献库搜索结果过滤功能 | 测试文献库操作 |

### 🟢 低优先级（锦上添花）

| # | 预测问题 | 验证方法 |
|---|---------|---------|
| 9 | 自定义Agent页面功能可能过于简单 | 检查自定义Agent页面 |
| 10 | 知识库面板可能缺少交互引导 | 检查知识库页面 |
| 11 | Toast通知可能堆叠遮挡内容 | 快速连续触发多个Toast |

---

## 四、修复与增强方案

基于Playwright测试实际发现的问题，分为以下两个阶段：

### Phase 1：测试中发现的Bug修复
- 根据Playwright测试截图和snapshot，逐一修复交互Bug
- 修复响应式布局问题
- 修复数据持久化边缘情况
- 修复弹窗/Toast堆叠问题

### Phase 2：用户体验增强
- 优化对话气泡的学术表达（字号、行距、引用格式）
- 增强移动端手势交互（滑动切换Agent）
- 添加首次使用引导（Onboarding tour）
- 优化文献库的标签分类和搜索过滤
- 增强写作工作台的快捷键（Tab缩进、Ctrl+B加粗等）

---

## 五、实施步骤

### Step 1：启动HTTP服务器（~1行命令）
```bash
cd c:\Users\13067\Desktop\AI产品\prototypes && python -m http.server 8080
```

### Step 2：Playwright测试执行（~30次MCP调用）
按测试路径A→I顺序执行，每步截图记录

### Step 3：问题收集与分析
汇总测试截图和snapshot，分类整理发现的问题

### Step 4：针对性修复
在 `interactive-prototype.html` 中修复测试发现的问题

### Step 5：功能增强
基于用户视角的建议，拓展业务能力

### Step 6：回归验证
修复后重新用Playwright验证关键路径

---

## 六、验证清单

- [ ] 首页→学科→研究类型→Agent对话流程完整
- [ ] CNKI检索结果可展示、保存、引用
- [ ] 图表对话框可打开、选择数据源、生成
- [ ] 文件上传有进度反馈
- [ ] 设置页所有面板功能正常
- [ ] 写作工作台编辑/预览/对话功能正常
- [ ] 移动端375px下布局正常
- [ ] 键盘快捷键全部生效
- [ ] 刷新后数据持久化正常
- [ ] 后端服务健康检查通过

---

## 七、技术决策

1. **Playwright测试方式**：使用 MCP `mcp_playwright` 服务器的 `browser_navigate`、`browser_snapshot`、`browser_take_screenshot`、`browser_click`、`browser_type`、`browser_press_key`、`browser_resize` 等工具
2. **测试目标**：本地 `interactive-prototype.html` 静态文件，通过 `python -m http.server` 提供
3. **测试数据**：使用模拟数据（CSV测试文件、模拟对话内容）
4. **截图保存路径**：`c:\Users\13067\Desktop\AI产品\test-results\`
5. **修复策略**：在原有 `interactive-prototype.html` 中修改，不新建文件