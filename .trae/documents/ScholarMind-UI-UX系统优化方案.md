# ScholarMind UI/UX 系统优化方案

## 一、概述

基于 `ui-ux-pro-max` 和 `canvas-design` 设计原则，对 ScholarMind 交互原型（`prototypes/interactive-prototype.html`）进行系统性 UI/UX 优化。目标文件为单一 SPA 原型文件，约 248KB，包含 10 个页面、CSS 变量系统、JavaScript 交互逻辑。

**三大优化方向：**
1. 增强对话气泡的素雅感
2. 增强元素表达的学术性
3. 增强 UX 交互设计的合理性与专业性

---

## 二、当前状态分析

### 2.1 现有设计系统

**色彩系统：** GitHub-style 暗色主题（`--bg-primary: #0D1117`），暖金色为主强调色（`--accent-amber: #C49668`），辅以蓝、绿、红、紫、青。偏向开发者工具风格，缺乏学术产品的温和与克制。

**字体系统：** `Inter`（无衬线）+ `Source Serif 4`（衬线），配对合理但层级运用不够精细，hero 标题仅 2.2rem。

**圆角系统：** 4px-20px（`--radius-xs` 到 `--radius-xl`），整体偏圆，缺少学术产品应有的克制与精确。

**间距系统：** 4px/8px/16px/24px/32px，基于 4px 基准，规范但缺乏微调。

### 2.2 现存问题清单

| 编号 | 问题域 | 具体问题 | 严重度 |
|------|--------|---------|--------|
| P1 | 气泡素雅感 | AI 气泡背景 `#1A1F28` 与页面背景对比不足，像嵌入区块而非独立话语 | 高 |
| P2 | 气泡素雅感 | 用户气泡 `rgba(181,140,100,0.08)` 透明度过低，存在感弱 | 高 |
| P3 | 气泡素雅感 | 气泡 `box-shadow` 过于微弱，缺少空间层次 | 中 |
| P4 | 气泡素雅感 | 气泡内容（如审查进度、建议卡片）嵌套在气泡内，视觉层级混乱 | 高 |
| P5 | 学术性 | 理科页面用文字字符 `∑` 作为图标（违反 ui-ux-pro-max 规则） | 高 |
| P6 | 学术性 | 附件管理中使用 emoji `📄` 作为图标 | 高 |
| P7 | 学术性 | 综述员页面使用 emoji `📊` 作为标题装饰 | 高 |
| P8 | 学术性 | Tree View 使用 Courior New 等宽字体，呈现终端风格而非学术排版 | 高 |
| P9 | 学术性 | Badge 样式过于圆润（`border-radius: 20px`），缺乏学术期刊的规整感 | 中 |
| P10 | 学术性 | Card 边框 hover 时变色为 amber，但缺少学术产品应有的"纸张"质感 | 中 |
| P11 | 学术性 | 整体色彩饱和度偏高，暗色主题对长时间学术阅读不够友好 | 中 |
| P12 | UX 交互 | `chat-chart-btn` 尺寸 36×36px，低于 44px 最小触摸目标 | 高 |
| P13 | UX 交互 | 导航按钮无 aria-label，屏幕阅读器无法识别 | 高 |
| P14 | UX 交互 | 三列布局无可折叠/调整大小功能 | 中 |
| P15 | UX 交互 | Agent 下拉菜单使用内联样式（`style="..."`）与 class 混合，维护性差 | 中 |
| P16 | UX 交互 | Chat 选项按钮缺少 pressed/active 状态反馈 | 中 |
| P17 | UX 交互 | 无键盘快捷键（如 `Ctrl+Enter` 发送消息） | 中 |
| P18 | UX 交互 | 文件上传无拖拽区域，仅依赖点击按钮 | 中 |
| P19 | UX 交互 | 无加载骨架屏（skeleton），消息发送后无过渡状态 | 中 |
| P20 | UX 交互 | 状态栏固定底部遮挡内容，无安全区处理 | 低 |

---

## 三、优化方案

### 3.1 色彩系统重构（学术化暖暗色主题）

**目标：** 从开发者工具风格转向学术研究产品风格，降低饱和度，引入"羊皮纸"暖色基底。

**CSS 变量变更（`:root`）：**

```css
:root {
  /* 背景层次 — 引入暖色微调 */
  --bg-primary: #0F1419;        /* 原 #0D1117，微暖 */
  --bg-card: #1A1F26;           /* 原 #161B22，增加纸张暖感 */
  --bg-card-hover: #1F252C;     /* 原 #1C2128 */
  --bg-input: #0F1419;          /* 同 bg-primary */
  --bg-elevated: #1E242C;       /* 原 #1A1F28，气泡浮层更深 */
  --bg-elevated-hover: #242B34; /* 原 #1F252E */
  --bg-user-bubble: #1E252C;    /* 原 rgba(181,140,100,0.08)，改为实色 */

  /* 边框 */
  --border: #2A3038;            /* 原 #2A3040 */
  --border-hover: #3A414A;      /* 原 #3A4050 */
  --border-subtle: #1E2430;     /* 保持 */

  /* 强调色 — 降低饱和度，更克制 */
  --accent-amber: #B8956A;      /* 原 #C49668，更深沉 */
  --accent-amber-dim: rgba(184, 149, 106, 0.10);
  --accent-amber-glow: rgba(184, 149, 106, 0.20);
  --accent-green: #4A8C50;      /* 原 #46954A */
  --accent-green-dim: rgba(74, 140, 80, 0.12);
  --accent-red: #D05A52;        /* 原 #E0554A */
  --accent-blue: #5C9CE6;       /* 原 #539BF5 */
  --accent-purple: #9B85C8;     /* 原 #9B7BD0 */
  --accent-teal: #52B8AE;       /* 原 #4DB6AC */

  /* 文字 — 提升阅读舒适度 */
  --text-primary: #E8EEF4;      /* 原 #E6EDF3 */
  --text-secondary: #8E98A2;    /* 原 #8B949E */
  --text-tertiary: #6A737D;     /* 原 #636B76 */

  /* 字体 */
  --font-serif: 'Source Serif 4', 'Noto Serif SC', Georgia, serif;
  --font-sans: 'Inter', 'Noto Sans SC', -apple-system, BlinkMacSystemFont, sans-serif;

  /* 圆角系统 — 更克制 */
  --radius-xs: 3px;
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --radius-xl: 18px;
  --radius-full: 9999px;

  /* 间距系统 */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 32px;
  --space-2xl: 48px;

  /* 阴影 — 增强层次 */
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.25);
  --shadow-md: 0 4px 16px rgba(0,0,0,0.35);
  --shadow-lg: 0 8px 32px rgba(0,0,0,0.45);

  /* 过渡 */
  --transition-fast: 0.15s cubic-bezier(0.4, 0, 0.2, 1);
  --transition-normal: 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  --transition-slow: 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}
```

---

### 3.2 对话气泡素雅感优化

#### 3.2.1 气泡样式重构

**文件位置：** `prototypes/interactive-prototype.html` 第 224-268 行

**变更内容：**

```css
/* ========== CHAT BUBBLES ========== */
.chat-container { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.chat-messages { flex: 1; overflow-y: auto; padding: 24px 20px; }

/* 消息分组容器 */
.chat-message-group {
  display: flex; flex-direction: column;
  margin-bottom: 20px;
}

/* 气泡基础 */
.chat-bubble {
  max-width: 68%;                    /* 原 72%，更克制 */
  padding: 14px 18px;                /* 原 12px 16px，更宽松 */
  border-radius: var(--radius-md);   /* 10px */
  font-size: 0.9rem;
  line-height: 1.75;                 /* 原 1.7，提升阅读舒适度 */
  animation: fadeInUp 0.35s ease;    /* 原 0.3s，稍缓 */
  position: relative;
  word-wrap: break-word;
  box-shadow: var(--shadow-sm);
  transition: box-shadow var(--transition-normal);
}

/* AI 气泡 — 左对齐，仿纸张质感 */
.chat-bubble-ai {
  background: var(--bg-elevated);    /* #1E242C */
  border: 1px solid var(--border-subtle);
  border-left: 3px solid var(--accent-amber);
  margin-right: auto;
  border-radius: 4px var(--radius-md) var(--radius-md) 4px; /* 左侧强调线 */
}

/* 用户气泡 — 右对齐，暖色基底 */
.chat-bubble-user {
  background: var(--bg-user-bubble); /* #1E252C */
  border: 1px solid rgba(184, 149, 106, 0.25);
  border-right: 3px solid var(--accent-amber);
  margin-left: auto;
  color: var(--text-primary);
  border-radius: var(--radius-md) 4px 4px var(--radius-md);
}

/* 时间戳 */
.chat-bubble-time {
  font-size: 0.7rem;
  color: var(--text-tertiary);
  margin-top: 6px;
  text-align: right;
  user-select: none;
  font-family: var(--font-sans);
  font-feature-settings: 'tnum';    /* 等宽数字 */
}

/* 操作按钮 — 始终可见但低透明度 */
.chat-bubble-actions {
  display: flex; gap: 4px; margin-top: 8px;
  opacity: 0.4;                      /* 原 0 (hover 才显示) */
  transition: opacity var(--transition-fast);
}
.chat-bubble:hover .chat-bubble-actions {
  opacity: 1;
}
.chat-action-btn {
  padding: 4px 10px;                 /* 原 3px 8px，增大触摸面积 */
  min-height: 28px;
  font-size: 0.72rem;
  background: transparent; color: var(--text-tertiary);
  border: 1px solid transparent; border-radius: var(--radius-xs);
  cursor: pointer; transition: all var(--transition-fast);
  display: flex; align-items: center; gap: 3px;
}
.chat-action-btn:hover {
  color: var(--text-secondary);
  background: rgba(255,255,255,0.04);
  border-color: var(--border-subtle);
}
```

#### 3.2.2 气泡内嵌内容卡片优化

气泡内嵌的审查进度、建议卡片、架构分析等内容，当前直接嵌套在气泡内，视觉层级混乱。优化方案：为内嵌内容增加微妙的左侧边框或背景色区分。

```css
/* 气泡内嵌内容卡片 */
.chat-bubble .bubble-section {
  padding: 12px 0;
  border-top: 1px solid var(--border-subtle);
}
.chat-bubble .bubble-section:first-child {
  padding-top: 0;
  border-top: none;
}
.chat-bubble .bubble-section-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 10px;
  font-family: var(--font-sans);
}
```

#### 3.2.3 打字指示器优化

**当前：** 第 739-756 行，三个渐变色圆点。

**优化：** 改为更学术的"思考中"样式，配合淡入文字。

```css
.typing-indicator {
  display: flex; align-items: center; gap: 8px;
  padding: 14px 18px; max-width: 80%;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-left: 3px solid var(--accent-amber);
  border-radius: 4px var(--radius-md) var(--radius-md) 4px;
  margin-bottom: 20px;
  animation: fadeInUp 0.35s ease;
  box-shadow: var(--shadow-sm);
}
.typing-indicator .typing-text {
  font-size: 0.82rem;
  color: var(--text-secondary);
  font-style: italic;
}
.typing-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: var(--accent-amber);
  animation: typingBounce 1.4s infinite;
}
```

---

### 3.3 元素表达学术性优化

#### 3.3.1 移除所有 emoji 图标，替换为 SVG

**违反规则：** `ui-ux-pro-max` 规则 "No Emoji as Structural Icons"

**受影响位置：**

| 位置 | 当前代码 | 替换方案 |
|------|---------|---------|
| 理科页面 (line ~1235) | `∑` 文字 | 使用 SVG 数学 Sigma 图标 |
| 附件管理 (line ~1696) | `📄` emoji | 使用 SVG 文件图标 |
| 综述员页面 (line ~2076) | `📊` emoji | 使用 SVG 图表图标 |

**实施方式：** 替换为内联 SVG 或 CSS 类引用，保持与现有图标风格一致（stroke-based 线条图标）。

#### 3.3.2 Tree View 学术化

**当前：** `Courier New` 等宽字体，终端/代码风格，色彩使用 `tree-green`、`tree-amber` 等类名。

**优化：** 改为衬线字体 + 结构化布局，更像学术论文的目录结构。

```css
.tree-view {
  font-family: var(--font-serif);    /* 原 Courier New */
  font-size: 0.85rem;
  line-height: 2;
  padding: 16px 20px;
  background: rgba(255,255,255,0.02);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  margin: 12px 0;
}
.tree-view .tree-node {
  display: flex; align-items: baseline;
  padding: 2px 0;
}
.tree-view .tree-indent { padding-left: 20px; }
.tree-view .tree-bullet {
  color: var(--text-tertiary);
  margin-right: 6px;
  font-family: var(--font-sans);
}
.tree-green { color: var(--text-primary); }
.tree-amber { color: var(--accent-amber); font-weight: 600; }
.tree-red { color: var(--accent-red); }
.tree-gray { color: var(--text-tertiary); }
.tree-warning {
  display: inline-block;
  font-size: 0.72rem;
  color: var(--accent-red);
  margin-left: 8px;
  font-family: var(--font-sans);
  font-style: italic;
}
```

#### 3.3.3 Badge 学术化

**当前：** `border-radius: 20px`，过于圆润，像社交平台标签。

**优化：** 改为更规整的小圆角，类似学术期刊的分类标签。

```css
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 3px;               /* 原 20px */
  font-size: 0.7rem;
  font-weight: 600;
  font-family: var(--font-sans);
  letter-spacing: 0.02em;
  text-transform: uppercase;
}
.badge-recommend {
  background: var(--accent-amber-dim);
  color: var(--accent-amber);
  border: 1px solid rgba(184, 149, 106, 0.25);
}
/* 严重度标签保持颜色区分但统一风格 */
.badge-severity-high {
  background: rgba(208, 90, 82, 0.12);
  color: var(--accent-red);
  border: 1px solid rgba(208, 90, 82, 0.25);
}
.badge-severity-medium {
  background: var(--accent-amber-dim);
  color: var(--accent-amber);
  border: 1px solid rgba(184, 149, 106, 0.25);
}
.badge-severity-low {
  background: rgba(74, 140, 80, 0.12);
  color: var(--accent-green);
  border: 1px solid rgba(74, 140, 80, 0.25);
}
```

#### 3.3.4 Card 学术化

**当前：** Card hover 时边框变 amber，但缺少纸张质感。

**优化：** 增加微妙的左边框强调、提升 hover 时 shadow 过渡。

```css
.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);  /* 6px，更克制 */
  padding: 20px;
  transition: all var(--transition-normal);
  cursor: pointer;
  position: relative;
}
.card::before {
  content: '';
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 0;
  background: var(--accent-amber);
  transition: width var(--transition-normal);
  border-radius: var(--radius-sm) 0 0 var(--radius-sm);
}
.card:hover {
  border-color: var(--border-hover);
  box-shadow: var(--shadow-md);
}
.card:hover::before {
  width: 3px;
}
```

#### 3.3.5 字体层级优化

```css
/* 标题层级 */
.hero-title {
  font-family: var(--font-serif);
  font-size: 2.6rem;                /* 原 2.2rem */
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.2;
}
.sub-page-title {
  font-family: var(--font-serif);
  font-size: 1.8rem;                /* 原 1.6rem */
  font-weight: 600;
  margin-bottom: 4px;
  letter-spacing: -0.01em;
}
/* 正文 */
body {
  font-size: 0.925rem;              /* 原 16px/lh1.6 */
  line-height: 1.65;
}
```

#### 3.3.6 新增：引用块样式（学术引用）

为 CNKI 文献结果添加学术引用块样式：

```css
.cnki-result-item {
  padding: 14px 16px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-left: 3px solid var(--border);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  margin-bottom: 10px;
  transition: all var(--transition-fast);
}
.cnki-result-item:hover {
  border-left-color: var(--accent-amber);
  border-color: var(--border-hover);
  border-left-color: var(--accent-amber);
  background: var(--bg-card-hover);
}
```

---

### 3.4 UX 交互设计优化

#### 3.4.1 触摸目标修复

**问题：** `chat-chart-btn` 36×36px，`chat-attach-btn` 40×40px，均低于 44px 最小触摸目标。

```css
.chat-chart-btn {
  width: 44px; height: 44px;        /* 原 36px */
  min-width: 44px; min-height: 44px;
  /* ... 其余不变 */
}
.chat-attach-btn {
  width: 44px; height: 44px;        /* 原 40px */
  min-width: 44px; min-height: 44px;
  /* ... 其余不变 */
}
```

#### 3.4.2 无障碍标签补充

为所有图标按钮添加 `aria-label`：

```html
<!-- 导航按钮 -->
<button class="nav-btn nav-btn-accent" onclick="navigateTo('custom-agent')" aria-label="创建自定义Agent">+</button>
<button class="nav-btn" onclick="navigateTo('settings')" aria-label="打开设置">...</button>

<!-- 聊天操作按钮 -->
<button class="chat-attach-btn" aria-label="上传附件">...</button>
<button class="chat-chart-btn" aria-label="生成学术图表">...</button>
<button class="chat-send-btn" aria-label="发送消息">...</button>
```

#### 3.4.3 键盘快捷键支持

**新增 JavaScript 函数：**

```javascript
// 键盘快捷键
document.addEventListener('keydown', function(e) {
  // Ctrl+Enter / Cmd+Enter 发送消息
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault();
    const activePage = document.querySelector('.page.active');
    if (activePage) {
      sendMessage(activePage.id);
    }
  }
  // Escape 关闭弹窗
  if (e.key === 'Escape') {
    closeChartOverlay();
    closeConfirmDialog();
    closeAgentDropdowns();
  }
});
```

#### 3.4.4 消息发送加载状态

```javascript
function sendMessage(pageId) {
  const input = document.querySelector(`#${pageId} .chat-input`) || 
                document.querySelector(`#${pageId}-input`);
  if (!input) return;
  const text = input.value.trim();
  if (!text) return;
  
  const chatMessages = input.closest('.center-chat').querySelector('.chat-messages');
  
  // 添加用户消息
  const userBubble = document.createElement('div');
  userBubble.className = 'chat-bubble chat-bubble-user';
  userBubble.style.marginLeft = 'auto';
  userBubble.textContent = text;
  chatMessages.appendChild(userBubble);
  
  // 添加打字指示器
  const typingIndicator = document.createElement('div');
  typingIndicator.className = 'typing-indicator';
  typingIndicator.innerHTML = `
    <span class="typing-text">思考中</span>
    <span class="typing-dot"></span>
    <span class="typing-dot"></span>
    <span class="typing-dot"></span>
  `;
  chatMessages.appendChild(typingIndicator);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  
  input.value = '';
  input.focus();
  
  // 模拟 AI 响应
  setTimeout(() => {
    typingIndicator.remove();
    const aiBubble = document.createElement('div');
    aiBubble.className = 'chat-bubble chat-bubble-ai';
    aiBubble.textContent = '感谢你的提问。我正在检索相关文献并进行分析，请稍候...';
    chatMessages.appendChild(aiBubble);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }, 2000);
}
```

#### 3.4.5 文件拖拽上传区域

```javascript
// 为每个 chat-input-area 添加拖拽支持
document.querySelectorAll('.chat-input-area').forEach(area => {
  area.addEventListener('dragover', (e) => {
    e.preventDefault();
    area.style.borderColor = 'var(--accent-amber)';
    area.style.background = 'rgba(184, 149, 106, 0.05)';
  });
  area.addEventListener('dragleave', () => {
    area.style.borderColor = '';
    area.style.background = '';
  });
  area.addEventListener('drop', (e) => {
    e.preventDefault();
    area.style.borderColor = '';
    area.style.background = '';
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      const pageId = area.closest('.page').id;
      handleFileDrop(files, pageId);
    }
  });
});
```

#### 3.4.6 左侧边栏折叠功能

```css
.sidebar-toggle {
  position: absolute; right: -12px; top: 50%;
  transform: translateY(-50%);
  width: 24px; height: 48px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 0 6px 6px 0;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  color: var(--text-secondary);
  z-index: 10;
  transition: all var(--transition-fast);
}
.sidebar-toggle:hover { color: var(--text-primary); background: var(--bg-card-hover); }
.left-sidebar.collapsed { width: 0; min-width: 0; padding: 0; overflow: hidden; }
```

#### 3.4.7 按钮 active 状态

```css
.chat-option-btn {
  padding: 8px 16px;
  background: var(--bg-card-hover);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: 0.85rem;
  transition: all var(--transition-fast);
  cursor: pointer;
  min-height: 44px;
}
.chat-option-btn:hover {
  border-color: var(--accent-amber);
  color: var(--accent-amber);
  background: rgba(184, 149, 106, 0.06);
}
.chat-option-btn:active, .chat-option-btn.selected {
  background: rgba(184, 149, 106, 0.12);
  border-color: var(--accent-amber);
  color: var(--accent-amber);
}
```

---

### 3.5 底部状态栏优化

**当前：** 固定底部遮挡内容，无安全区处理。

**优化：** 在聊天页面隐藏或缩小，或在内容区增加底部 padding。

```css
.status-bar {
  display: flex; align-items: center; gap: 16px;
  padding: 8px 24px;                /* 原 10px */
  background: rgba(15, 20, 25, 0.9); /* 匹配新背景 */
  border-top: 1px solid var(--border);
  font-size: 0.75rem;
  color: var(--text-secondary);
  position: fixed; bottom: 0; left: 0; right: 0;
  backdrop-filter: blur(8px);
  z-index: 90;
}
/* 为页面底部增加安全区 */
.sub-page-content { padding-bottom: 60px; }  /* 原 80px */
.chat-messages { padding-bottom: 16px; }
```

---

## 四、实施计划

### 步骤 1：CSS 变量系统重构
- 修改 `:root` 中所有颜色、圆角、阴影变量
- 影响范围：全局，所有页面

### 步骤 2：对话气泡样式优化
- 修改 `.chat-bubble`、`.chat-bubble-ai`、`.chat-bubble-user` 样式
- 修改 `.typing-indicator` 样式
- 新增 `.chat-message-group`、`.bubble-section` 样式
- 影响范围：第 224-268 行、第 739-756 行

### 步骤 3：元素学术性优化
- 第 1235 行：替换理科页面 `∑` 为 SVG 图标
- 第 1696 行：替换附件管理 `📄` 为 SVG 图标
- 第 2076 行：替换综述员 `📊` 为 SVG 图标
- 修改 `.tree-view` 样式（第 555-565 行）
- 修改 `.badge` 样式（第 190-197 行）
- 修改 `.card` 样式（第 175-187 行）
- 修改 `.cnki-result-item` 样式（第 387-426 行）
- 修改字体层级（`.hero-title`、`.sub-page-title`、`body`）

### 步骤 4：UX 交互优化
- 修改 `.chat-chart-btn`、`.chat-attach-btn` 尺寸（第 296-310 行）
- 新增 `.chat-option-btn` 的 `:active`/`.selected` 状态
- 为所有导航和操作按钮添加 `aria-label` 属性
- 新增键盘快捷键 JavaScript 代码
- 新增文件拖拽上传 JavaScript 代码
- 新增左侧边栏折叠 CSS + HTML
- 修改 `sendMessage` 函数添加加载状态

### 步骤 5：状态栏和布局微调
- 修改 `.status-bar` 样式
- 调整 `.sub-page-content` 底部 padding
- 全局字体大小微调

---

## 五、验证清单

- [ ] 所有页面色彩和谐统一，无明显视觉跳跃
- [ ] 对话气泡 AI/用户双侧有清晰的视觉区分
- [ ] 气泡内嵌内容有明确的层级分隔
- [ ] 所有 emoji 已被 SVG 图标替换
- [ ] Tree View 呈现学术排版风格
- [ ] Badge 标签规整，符合学术产品气质
- [ ] 所有图标按钮尺寸 ≥ 44×44px
- [ ] 所有图标按钮有 `aria-label`
- [ ] `Ctrl+Enter` 可发送消息
- [ ] 文件拖拽到输入区可触发上传
- [ ] 发送消息后出现打字指示器过渡
- [ ] 左侧边栏可折叠/展开
- [ ] 状态栏不遮挡聊天内容
- [ ] 10 个页面（首页、人文社科、工科、理科、交叉学科、思路选择、研究员、审查员、架构师、综述员、润色员、自定义Agent、设置）导航正常
- [ ] 暗色主题下文字对比度 ≥ 4.5:1（WCAG AA）
- [ ] 1600px、1200px、768px 三种宽度下布局正常

---

## 六、假设与决策

1. **不引入外部依赖：** 所有优化在单一 HTML 文件内完成，不使用外部 CSS 框架或 JS 库。
2. **保持暗色主题：** 用户原设计为暗色主题，优化方案在保持暗色基调的前提下提升学术感。
3. **渐进优化：** 不改变页面路由逻辑和数据结构，仅优化 CSS 样式和增强 JS 交互。
4. **保留现有 SVG 图标风格：** 新增 SVG 图标与现有 Feather Icons 风格保持一致（stroke-based, 24×24 viewBox）。
5. **文件大小：** 原文件约 248KB，优化后预计增加 5-10KB（CSS 变量、新增样式、JS 增强）。