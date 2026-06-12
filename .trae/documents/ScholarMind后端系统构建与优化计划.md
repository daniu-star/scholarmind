# ScholarMind 后端系统构建与优化计划

## 概述

当前项目为纯前端原型（`interactive-prototype.html`），所有Agent、RAG、图表生成、CNKI检索、文件上传、Skills管理均为前端模拟。本计划将构建完整的Python后端系统，实现4个核心功能，并修复现有前端原型中的bug。

---

## 当前状态分析

### 项目文件结构
```
c:\Users\13067\Desktop\AI产品\
├── .mcp.json                    # 墨刀MCP配置
├── AI产品.docx                  # 产品文档
├── import_to_modao.py           # 墨刀导入脚本
├── import_interactive.py        # 墨刀导入脚本
├── .venv/                       # Python虚拟环境
└── prototypes/
    ├── interactive-prototype.html  # 核心SPA原型（4642行）
    └── legacy/                     # 旧版独立页面
```

### 现有问题清单

| 编号 | 问题 | 严重度 | 位置 |
|------|------|--------|------|
| BUG-1 | 图表生成仅为Canvas前端模拟，无法生成真实Origin风格学术图表 | 严重 | JS行3585-3998 |
| BUG-2 | 文件上传仅前端展示，无后端处理，无文件数量限制提示 | 严重 | JS行3441-3583 |
| BUG-3 | CNKI检索完全为mock数据（`mockCNKIDatabase`），无法连接真实知网 | 严重 | JS行4000-4239 |
| BUG-4 | Skills创建仅保存到localStorage，无法真正加载执行 | 中等 | JS行4305-4501 |
| BUG-5 | Agent对话回复为固定文本，无真实LLM调用 | 严重 | JS行4242-4283 |
| BUG-6 | RAG知识库连接状态为硬编码模拟 | 严重 | 设置页面 |
| BUG-7 | Langgraph工作流配置为静态展示 | 严重 | 设置页面 |
| BUG-8 | 文件上传无数量限制（用户要求5-15个） | 中等 | JS行3465-3526 |

---

## 实施方案

### 任务1：构建Python后端框架

**目标**：建立FastAPI后端，提供API接口供前端调用

**新建文件**：
- `src/backend/app.py` — FastAPI主应用入口
- `src/backend/config.py` — 配置管理（环境变量、API密钥）
- `src/backend/requirements.txt` — Python依赖
- `src/backend/routers/__init__.py` — 路由模块
- `src/backend/routers/chart.py` — 图表生成API
- `src/backend/routers/upload.py` — 文件上传API
- `src/backend/routers/skills.py` — Skills管理API
- `src/backend/routers/knowledge.py` — 知识库/CNKI API
- `src/backend/routers/agent.py` — Agent对话API
- `src/backend/services/chart_service.py` — 图表生成服务
- `src/backend/services/cnki_service.py` — CNKI连接服务
- `src/backend/services/skills_service.py` — Skills加载与执行服务
- `src/backend/services/agent_service.py` — Langgraph Agent编排服务

**依赖**：
```
fastapi>=0.104.0
uvicorn>=0.24.0
python-multipart>=0.0.6
matplotlib>=3.8.0
seaborn>=0.13.0
numpy>=1.24.0
pandas>=2.1.0
scipy>=1.11.0
openpyxl>=3.1.0
plotly>=5.18.0
kaleido>=0.2.1
langgraph>=0.0.30
langchain>=0.1.0
langchain-community>=0.0.10
aiohttp>=3.9.0
pydantic>=2.5.0
pydantic-settings>=2.1.0
python-dotenv>=1.0.0
```

---

### 任务2：Origin风格学术图表生成（文生图）

**目标**：用Python后端生成高级学术图表，替代前端Canvas模拟

**实现方案**：
- 使用 `matplotlib` + `seaborn` 生成12种高级图表
- 通过FastAPI的 `/api/chart/generate` 端点接收参数并返回PNG图片
- 前端通过 `<img>` 标签加载后端生成的图表

**图表类型与实现**：

| 图表ID | 名称 | matplotlib实现方式 |
|--------|------|-------------------|
| ribbon | 缎带图 | `fill_between` + 多层渐变 |
| violin | 小提琴图+内嵌箱线图 | `violinplot` + `boxplot` |
| alluvial | 冲积图 | `matplotlib-sankey` 或自定义 |
| bubble_kde | 气泡散点+KDE | `scatter` + `gaussian_kde` 等高线 |
| gradient_area | 梯度面积图 | `fill_between` + colormap渐变 |
| surface3d | 3D地形图 | `plot_surface` + 自定义colormap |
| parallel | 平行坐标图 | `pandas.plotting.parallel_coordinates` |
| contour | 等高线图 | `contourf` + 地形colormap |
| swarm | 蜂群图 | `swarmplot` (seaborn) |
| scatter_density | 散点密度图 | `scatter` + 2D直方图密度着色 |
| chord | 和弦图 | 自定义弧线绘制 |
| heatmap_dendro | 热力聚类图 | `clustermap` (seaborn) + 树状图 |

**API设计**：
```
POST /api/chart/generate
Body: {
  "chart_type": "ribbon",
  "title": "研究趋势对比",
  "x_axis": "年份",
  "y_axis": "影响因子",
  "data": {...},           # 粘贴的JSON/CSV数据
  "file_path": null,       # 或选择已上传文件路径
  "style": "origin",       # Origin风格
  "width": 1200,
  "height": 800,
  "dpi": 300
}
Response: PNG image (Content-Type: image/png)
```

**Origin风格配置**：
- 白底黑框、粗边框线
- 轴标签≥20pt，标题≥22pt，注释≥15pt
- 使用学术配色方案（非彩虹色）
- 导出为300dpi PNG + 可选PDF

**前端修改**（`interactive-prototype.html`）：
- `generateChart()` 函数改为调用后端API
- 图表显示区域从Canvas改为 `<img>` 标签
- 添加加载状态和错误处理

---

### 任务3：文件上传扩展（5-15个文件）

**目标**：支持多文件上传，后端存储与解析

**实现方案**：
- FastAPI `/api/upload` 端点处理文件上传
- 支持的文件类型：csv, xlsx, json, pdf, docx, md, txt, r, py, ipynb, tex, bib
- 文件数量限制：最少5个，最多15个
- 单文件大小限制：20MB
- 上传目录：`data/uploads/{session_id}/`

**API设计**：
```
POST /api/upload
Body: multipart/form-data (files[])
Response: {
  "uploaded": [
    {"name": "data.csv", "size": "2.3MB", "type": "csv", "tag": "原始数据", "path": "..."}
  ],
  "skipped": [],
  "total": 3,
  "max_files": 15
}

GET /api/upload/{session_id}
Response: 列出已上传文件

DELETE /api/upload/{session_id}/{file_id}
Response: 删除指定文件
```

**前端修改**：
- `handleFileUpload()` 增加文件数量检查（5-15个）
- 添加文件数量提示："已上传 X/15 个文件"
- 上传后调用后端API而非仅前端展示
- 文件选择器添加 `multiple` 属性和数量限制

---

### 任务4：Skills自定义创建与管理

**目标**：用户可创建自定义Skills文件，并加载到Agent中执行

**实现方案**：
- 后端 `/api/skills` 端点管理Skills CRUD
- Skills文件存储在 `data/skills/` 目录，格式为 `.md`（YAML frontmatter + 规则内容）
- 自定义Skills可被Langgraph Agent动态加载

**API设计**：
```
POST /api/skills
Body: {
  "id": "my-custom-skill",
  "display_name": "自定义分析",
  "description": "...",
  "triggers": ["分析", "统计"],
  "agents": ["researcher", "reviewer"],
  "rules": "当用户提到分析时..."
}
Response: { "id": "my-custom-skill", "file_path": "data/skills/my-custom-skill.md" }

GET /api/skills
Response: 列出所有Skills（预设+自定义）

PUT /api/skills/{skill_id}
Body: 更新内容

DELETE /api/skills/{skill_id}

POST /api/skills/{skill_id}/toggle
Body: { "enabled": true }
```

**Skills文件格式**（.md）：
```markdown
---
name: my-custom-skill
display_name: 自定义分析
description: ...
version: 1.0.0
created: 2026-06-10
category: custom
triggers:
  - 分析
  - 统计
agents:
  - researcher
  - reviewer
---

# 规则

当用户提到分析时，执行以下步骤：
1. ...
2. ...
```

**前端修改**：
- `saveCustomSkill()` 改为调用后端API
- 设置页面Skills管理区域从localStorage改为API调用
- 添加"上传Skills文件"功能（用户可上传本地.md文件）

---

### 任务5：CNKI知网数据库连接

**目标**：通过API或MCP工具连接真实知网数据库

**实现方案**：

方案A：CNKI开放API（优先）
- 知网提供CNKI开放API（需申请API Key）
- 端点：`https://cnki.net/api/search`
- 支持关键词检索、高级检索、文献详情获取

方案B：通过MCP工具
- 使用已有的 `mcp_Bright_Data` 或 `mcp_firecrawl-mcp` 爬取知网搜索结果
- 或使用 `nature-academic-search` skill中的PubMed/CrossRef/arXiv MCP工具

方案C：知网网页检索（兜底）
- 使用Playwright/Puppeteer MCP自动化浏览器检索知网
- 解析搜索结果页面获取文献信息

**API设计**：
```
POST /api/knowledge/cnki/search
Body: {
  "query": "网络情绪",
  "year_filter": "2020-2025",
  "source_filter": "核心期刊",
  "count": 20
}
Response: {
  "results": [
    {
      "title": "...",
      "author": "...",
      "year": 2024,
      "source": "新闻与传播研究",
      "citations": 45,
      "core": true,
      "abstract": "...",
      "doi": "..."
    }
  ],
  "total": 156,
  "source": "cnki_api"
}

GET /api/knowledge/status
Response: {
  "cnki": { "connected": true, "method": "api" },
  "wos": { "connected": true, "method": "api" },
  "scopus": { "connected": false },
  "pubmed": { "connected": false }
}
```

**前端修改**：
- `getMockCNKIResults()` 改为调用后端API
- 设置页面RAG知识库状态从硬编码改为API查询
- 添加知网API Key配置入口

---

### 任务6：前端原型修复与后端对接

**目标**：修复现有前端bug，对接后端API

**修改文件**：`prototypes/interactive-prototype.html`

**具体修改**：

1. **图表生成**（行3585-3998）：
   - `generateChart()` 改为 `fetch('/api/chart/generate', ...)` 调用后端
   - 图表显示从Canvas改为 `<img src="/api/chart/...">`
   - 添加生成进度条和错误提示

2. **文件上传**（行3441-3583）：
   - `handleFileUpload()` 改为 `fetch('/api/upload', ...)` 调用后端
   - 添加文件数量限制（5-15个）和提示
   - 上传文件实际存储到后端

3. **CNKI检索**（行4000-4239）：
   - `getMockCNKIResults()` 改为 `fetch('/api/knowledge/cnki/search', ...)`
   - `detectCNKIIntent()` 保持不变（前端意图识别）
   - 检索结果从真实API获取

4. **Skills管理**（行4305-4501）：
   - `saveCustomSkill()` 改为 `fetch('/api/skills', ...)`
   - `getCustomSkills()` 改为从后端API获取
   - 添加"上传Skills文件"按钮

5. **Agent对话**（行4242-4283）：
   - `sendMessage()` 改为 `fetch('/api/agent/chat', ...)` 调用后端
   - 后端通过Langgraph编排Agent回复

6. **设置页面**：
   - RAG知识库状态从API获取
   - Langgraph配置可实际保存
   - CNKI API Key配置入口

---

## 假设与决策

| 决策项 | 选择 | 理由 |
|-------|------|------|
| 后端框架 | FastAPI | 异步支持好，自动生成API文档，适合AI应用 |
| 图表库 | matplotlib + seaborn | 学术图表标准，Origin风格可定制 |
| CNKI连接 | 优先API，兜底MCP爬取 | API最稳定，MCP作为备选 |
| Skills存储 | 文件系统(.md) | 便于用户编辑和版本管理 |
| 文件上传限制 | 5-15个 | 用户明确要求 |
| 前后端通信 | REST API | 简单直接，原型阶段够用 |
| Agent编排 | Langgraph | 用户明确要求 |

---

## 验证步骤

1. **后端启动验证**：`uvicorn src.backend.app:app --reload` 确认服务启动
2. **图表生成验证**：调用 `/api/chart/generate` 生成12种图表，检查Origin风格
3. **文件上传验证**：上传5-15个不同类型文件，检查存储和解析
4. **Skills管理验证**：创建/编辑/删除/启用/禁用自定义Skill
5. **CNKI连接验证**：检索关键词，确认返回真实文献数据
6. **前端对接验证**：在浏览器中操作完整流程，确认所有API调用正常
7. **集成测试**：完整流程测试——上传数据 → 生成图表 → CNKI检索 → Agent对话
