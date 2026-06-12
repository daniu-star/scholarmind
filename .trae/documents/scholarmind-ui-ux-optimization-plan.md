# ScholarMind UI/UX 系统性优化执行计划 v3

## 概述
对 `prototypes/interactive-prototype.html` 进行系统性 UI/UX 优化，聚焦三个维度：对话气泡素雅感、元素学术表达、交互专业合理性。

---

## 一、当前代码状态（2026-06-11 验证）

### 已完成（上一会话 + 已验证）
| 任务 | 验证行号 | 状态 |
|------|----------|------|
| CSS 变量系统重构 | L20-L71 | ✅ 已完成 |
| 对话气泡样式重写 | L226-244 | ✅ 已完成 |
| 键入指示器优化 | L719-735 | ✅ 已完成 |
| 卡片交互学术化（discipline/vertical/grid） | L165, L948, L965 | ✅ 已完成 |
| grid-card hover 去除 translateY | L965 | ✅ 已完成 |
| 页面切换过渡增强 (navigateTo) | L3143-3185 | ✅ 已完成 |
| 消息发送动画 (sendMessage) | L4435-4441 | ✅ 已完成 |
| Focus 状态增强 (:focus-visible) | L86-99 | ✅ 已完成 |
| 输入区视觉减重 (border-subtle + blur) | L275-278 | ✅ 已完成 |
| Agent 下拉菜单过渡动画 (CSS + JS) | L494-508, L3321-3351 | ✅ 已完成 |
| 学科卡片 SVG 图标 | L1068+ | ✅ 已完成 |
| T2a: 进度追踪器 ✓ → SVG checkmark | 全局 | ✅ 已完成 |
| 触摸目标：chat-send-btn (44px) | L289 | ✅ 已完成 |
| 触摸目标：sidebar-btn (min-height: 44px) | L471 | ✅ 已完成 |
| 触摸目标：btn-back (min-height: 44px) | L216 | ✅ 已完成 |
| 触摸目标：nav-btn (40px) | L135 | ✅ 已完成 |
| range-slider thumb → var(--accent-amber) | L707 | ✅ 已完成 |

### 待完成（本计划实施）

| 任务 ID | 内容 | 优先级 | 行号参考 |
|---------|------|--------|----------|
| T1 | 字体层级微调 (0.9→0.92rem) | P1 | L229 |
| T2b | 设置面板章节图标 📚🌐🔬🏥 → SVG | P1 | L2686-2728 |
| T2c | 清除按钮图标 🗑️🔄 → SVG | P1 | L2851-2852 |
| T2d | 主题卡片图标 🌙☀️ → SVG | P1 | L2963, L2967 |
| T2e | 图表类型选择器 🎀🎻🌊等 → SVG | P1 | L3052-3063 |
| T2f | 文件类型图标映射 → SVG | P1 | L3545-3550 |
| T2g | Toast 图标 ✓✕ℹ⚠ → SVG | P1 | L3516 |
| T2h | 编辑按钮 ✎ → SVG pencil | P2 | L4704 |
| T2i | 剩余内联 emoji 📄📝💡📊⚠ → SVG | P2 | L1697, L2234-2235, L2076, L2294, L1828 |
| T9 | chat-attach-btn 40→44px | P2 | L297 |
| T10 | 硬编码 #D4A574 → var(--accent-amber) | P3 | 多处 CSS |

---

## 二、详细实施步骤

### T1: 字体层级微调
**行号**: L229

当前 `.chat-bubble` font-size 为 `0.9rem`，需改为 `0.92rem` 以增强可读性。

```css
/* L229: */
font-size: 0.92rem; line-height: 1.7;
```

---

### T2b: 设置面板章节图标
**行号**: L2686 (📚), L2708 (🌐), L2718 (🔬), L2728 (🏥)

| 行号 | 当前 | 替换 |
|------|------|------|
| L2686 | `<span style="font-size:1.3rem;">📚</span>` | `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#C49668" stroke-width="1.5"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>` |
| L2708 | `<span style="font-size:1.3rem;">🌐</span>` | `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#C49668" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>` |
| L2718 | `<span style="font-size:1.3rem;">🔬</span>` | `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#C49668" stroke-width="1.5"><path d="M9 3h6M10 3v4M9 7h6M8 21l2-10h4l2 10M12 11v3"/></svg>` |
| L2728 | `<span style="font-size:1.3rem;">🏥</span>` | `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#C49668" stroke-width="1.5"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>` |

---

### T2c: 清除按钮图标
**行号**: L2851 (🗑️), L2852 (🔄)

| 行号 | 当前 | 替换 |
|------|------|------|
| L2851 | `🗑️ 清除所有记忆` | `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:text-bottom;margin-right:4px"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>清除所有记忆` |
| L2852 | `🔄 清除研究进度` | `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:text-bottom;margin-right:4px"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>清除研究进度` |

---

### T2d: 主题卡片图标
**行号**: L2963 (🌙), L2967 (☀️)

| 行号 | 当前 | 替换 |
|------|------|------|
| L2963 | `🌙 深色模式` | `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:text-bottom;margin-right:4px"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>深色模式` |
| L2967 | `☀️ 浅色模式` | `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:text-bottom;margin-right:4px"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>浅色模式` |

---

### T2e: 图表类型选择器 emoji → SVG
**行号**: L3052-3063

将 `chartTypes` 数组的 `icon` 字段改为 SVG 键名，并在 `renderChartTypeCards()` 函数中用 SVG 渲染。

```javascript
// 修改 chartTypes 数组
const chartTypes = [
  { id: 'ribbon', name: '缎带图', svg: 'ribbon', desc: '时间序列趋势对比' },
  { id: 'violin', name: '小提琴图', svg: 'violin', desc: '数据分布与密度' },
  { id: 'alluvial', name: '冲积图', svg: 'alluvial', desc: '流动与变迁分析' },
  { id: 'bubble_kde', name: '气泡散点+KDE', svg: 'bubble', desc: '多维关联分布' },
  { id: 'gradient_area', name: '梯度面积图', svg: 'area', desc: '累积趋势变化' },
  { id: 'surface3d', name: '3D地形图', svg: 'surface', desc: '三维数据表面' },
  { id: 'parallel', name: '平行坐标图', svg: 'parallel', desc: '多维数据对比' },
  { id: 'contour', name: '等高线图', svg: 'contour', desc: '密度与地形' },
  { id: 'swarm', name: '蜂群图', svg: 'swarm', desc: '数据点分布' },
  { id: 'scatter_density', name: '散点密度图', svg: 'density', desc: '大样本密度' },
  { id: 'chord', name: '和弦图', svg: 'chord', desc: '关系网络流动' },
  { id: 'heatmap_dendro', name: '热力聚类图', svg: 'heatmap', desc: '层次聚类分析' }
];
```

同时添加 SVG 图标映射和渲染逻辑修改。

---

### T2f: 文件类型图标映射
**行号**: L3545-3557

将 `typeIcons` emoji 映射改为 SVG 映射，并在 `updateFileListInChat()` 函数中使用。

```javascript
const typeIcons = {
  'csv': '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#58A6FF" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="8" y1="12" x2="16" y2="12"/></svg>',
  'xlsx': '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#3FB950" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><rect x="8" y="8" width="8" height="8"/></svg>',
  'pdf': '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#F85149" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
  'docx': '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#539BF5" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>',
  'json': '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#D4A574" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M8 8v8M12 8v8M16 8v4"/></svg>',
  'md': '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#9B7BD0" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/></svg>',
  'txt': '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#8B949E" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
  'tex': '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#4DB6AC" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
  'bib': '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#C49668" stroke-width="1.5"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>',
  'ipynb': '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#E0554A" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="12" cy="12" r="4"/></svg>',
  'r': '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#539BF5" stroke-width="1.5"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
  'py': '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#3FB950" stroke-width="1.5"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>'
};
```

同时修改 `updateFileListInChat()` 函数中的文件渲染逻辑，使用 `innerHTML` 设置 SVG。

---

### T2g: Toast 图标
**行号**: L3516

```javascript
const icons = {
  success: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>',
  error: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
  info: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
  warning: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
};
```

同时修改 toast 渲染行，将 `toast.innerHTML` 中的 textContent 改为 innerHTML 以支持 SVG。

---

### T2h: 编辑按钮 ✎ → SVG
**行号**: L4704

`✎` 替换为：
```html
<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
```

---

### T2i: 剩余内联 emoji
| 行号 | 当前 | 替换 |
|------|------|------|
| L1697 | `<span>📄</span> 我的研究思路.docx` + L1698 `✓` | SVG file + checkmark |
| L2076 | `📊 文献检索进度` | SVG chart icon |
| L2234 | `📄 上传全文` | SVG file icon |
| L2235 | `📝 粘贴文本` | SVG edit icon |
| L2294 | `💡 文本分析结果` | SVG lightbulb icon |
| L1828 | `⚠ 缺少连接` | SVG warning icon |

---

### T9: chat-attach-btn 触摸目标
**行号**: L297

```css
/* L297: width: 40px; height: 40px; → */
width: 44px; height: 44px;
```

---

### T10: 硬编码色值统一
将 CSS 中所有非渐变用途的 `#D4A574` 替换为 `var(--accent-amber)`。

**需要替换的 CSS 规则**（共约 12 处，渐变中的保持不变）：
- L124: `.nav-logo` color
- L274: `.chat-option-btn:hover` border-color + color
- L477: `.sidebar-btn:hover` border-color
- L538: `.topic-card:hover` border-color
- L563: `.tree-amber` color
- L603: `.form-input:focus` border-color
- L686: `.settings-nav-item.active` color + border-left-color
- L919: `.checkbox-item.checked` border-color

**保持不变**（渐变中的 #D4A574）：
- 所有 `linear-gradient(135deg, #D4A574, #B8860B)` 等渐变声明
- 内联 style 中的渐变（如按钮、头像等）
- SVG `stroke="#D4A574"` 属性

---

## 三、实施顺序

1. **T2b**: 设置面板章节图标（4 个替换）
2. **T2c**: 清除按钮图标（2 个替换）
3. **T2d**: 主题卡片图标（2 个替换）
4. **T2e**: 图表类型选择器（12 个替换 + 渲染逻辑）
5. **T2f**: 文件类型图标映射（12 个 SVG 映射）
6. **T2g**: Toast 图标（4 个替换）
7. **T2h**: 编辑按钮图标（1 个替换）
8. **T2i**: 剩余内联 emoji（6 个替换）
9. **T1**: 字体层级微调
10. **T9**: chat-attach-btn 尺寸
11. **T10**: 硬编码色值 → CSS 变量

---

## 四、验证清单

- [ ] 所有页面无残存功能性 emoji（文件类型 SVG 除外）
- [ ] SVG 图标在大/小尺寸下均清晰可辨
- [ ] hover/click/focus 状态正确
- [ ] 移动端响应式断点（768px, 1200px）正常
- [ ] Agent 下拉菜单过渡流畅
- [ ] 页面切换过渡平滑
- [ ] 消息发送有渐显动画
- [ ] 所有交互元素触摸目标 ≥ 44x44px
- [ ] CSS 色值统一使用变量（渐变除外）
- [ ] 字体层级统一、行高适配
- [ ] 文件类型图标渲染正确（所有 12 种格式）
- [ ] Toast 通知图标正常显示
- [ ] 图表类型选择器图标正常显示
- [ ] 设置面板章节图标正常显示