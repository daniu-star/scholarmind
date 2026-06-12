# ScholarMind 后端系统构建与优化计划（最终版）

## 概述

当前项目为纯前端原型，后端代码完成度0%。本计划将构建完整Python后端，实现4个核心功能：Origin风格图表生成、5-15文件上传、Skills自定义管理、CNKI知网MCP爬取连接。

---

## 当前状态

- **后端代码**：完全不存在，需从零构建
- **前端原型**：`prototypes/interactive-prototype.html`（4702行SPA），所有功能为前端模拟
- **DeepSeek API Key**：`sk-a6f692b99ffe4120bc4cf6e49ebf5134`（v4-flash模型）
- **CNKI连接方式**：MCP爬取（Bright Data / Firecrawl）
- **虚拟环境**：`.venv/` 已存在，仅含基础包

---

## 实施步骤

### 步骤1：创建后端框架与配置

**新建文件**：

- `src/backend/__init__.py` — 包初始化
- `src/backend/app.py` — FastAPI主应用，挂载所有路由，CORS配置，静态文件服务
- `src/backend/config.py` — Pydantic Settings配置（DeepSeek API Key、上传限制、数据目录等）
- `src/backend/requirements.txt` — Python依赖清单
- `src/backend/routers/__init__.py` — 路由包
- `src/backend/services/__init__.py` — 服务包
- `.env` — 环境变量（DEEPSEEK_API_KEY等）
- `data/uploads/` — 上传文件存储目录
- `data/skills/` — Skills文件存储目录
- `data/charts/` — 生成的图表缓存目录

**requirements.txt 内容**：
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
langchain>=0.1.0
langchain-community>=0.1.0
langgraph>=0.0.30
aiohttp>=3.9.0
pydantic>=2.5.0
pydantic-settings>=2.1.0
python-dotenv>=1.0.0
openai>=1.6.0
```

---

### 步骤2：Origin风格学术图表生成服务

**新建文件**：
- `src/backend/services/chart_service.py` — 12种高级图表生成逻辑
- `src/backend/routers/chart.py` — 图表API路由

**API端点**：
```
POST /api/chart/generate
Body: {
  "chart_type": "ribbon",      # 12种之一
  "title": "研究趋势对比",
  "x_label": "年份",
  "y_label": "影响因子",
  "data": [[2019,3.2],[2020,3.5],...],  # 或CSV字符串
  "file_path": null,           # 或已上传文件路径
  "width": 1200, "height": 800, "dpi": 300
}
Response: PNG图片 (Content-Type: image/png)

GET /api/chart/{chart_id}
Response: 获取已生成的图表
```

**12种图表实现**（全部使用matplotlib+seaborn，Origin风格：白底黑框、粗边框、大字号）：

| ID | 名称 | 实现方式 |
|----|------|---------|
| ribbon | 缎带图 | `fill_between` 多层渐变+阴影 |
| violin | 小提琴图+内嵌箱线图 | `violinplot` + `boxplot` overlay |
| alluvial | 冲积图 | 自定义弧线+渐变色带 |
| bubble_kde | 气泡散点+KDE | `scatter`(气泡大小映射) + `gaussian_kde`等高线 |
| gradient_area | 梯度面积图 | `fill_between` + colormap渐变填充 |
| surface3d | 3D地形图 | `Axes3D.plot_surface` + terrain colormap |
| parallel | 平行坐标图 | `parallel_coordinates` + 彩色线条 |
| contour | 等高线地形图 | `contourf` + terrain colormap + 等高线标注 |
| swarm | 蜂群图 | `swarmplot` + 分组着色 |
| scatter_density | 散点密度图 | `scatter` + 2D直方图密度映射颜色 |
| chord | 和弦图 | 自定义弧线+贝塞尔曲线连接 |
| heatmap_dendro | 热力聚类图 | `clustermap` + 树状图 + 色标 |

**Origin风格统一配置**：
- 背景：纯白 `#FFFFFF`
- 边框：黑色粗线 `linewidth=2`
- 轴标签：≥20pt，标题：≥22pt，注释：≥15pt
- 字体：SimHei（中文）+ Arial（英文）
- 配色：学术色板（非彩虹色）
- 导出：300dpi PNG

---

### 步骤3：文件上传服务（5-15个）

**新建文件**：
- `src/backend/routers/upload.py` — 上传API路由

**API端点**：
```
POST /api/upload/{session_id}
Body: multipart/form-data (files[])
Response: {
  "uploaded": [{"name":"data.csv","size":"2.3MB","type":"csv","tag":"原始数据","path":"..."}],
  "skipped": [],
  "total": 3, "max_files": 15
}

GET /api/upload/{session_id}
Response: 列出已上传文件

DELETE /api/upload/{session_id}/{file_name}
Response: 删除指定文件
```

**规则**：
- 支持12种文件类型：csv, xlsx, json, pdf, docx, md, txt, r, py, ipynb, tex, bib
- 单文件最大20MB
- 每个session最少5个、最多15个文件
- 文件自动分类标签：原始数据/研究计划/研究设计/参考文献/文档
- 存储路径：`data/uploads/{session_id}/`

---

### 步骤4：Skills自定义管理服务

**新建文件**：
- `src/backend/services/skills_service.py` — Skills CRUD逻辑
- `src/backend/routers/skills.py` — Skills API路由

**API端点**：
```
POST /api/skills — 创建自定义Skill
GET /api/skills — 列出所有Skills（预设8个+自定义）
GET /api/skills/{skill_id} — 获取单个Skill详情
PUT /api/skills/{skill_id} — 更新Skill
DELETE /api/skills/{skill_id} — 删除Skill
POST /api/skills/{skill_id}/toggle — 启用/禁用
POST /api/skills/upload — 上传.md格式的Skill文件
```

**Skills文件格式**（存储在 `data/skills/` 目录）：
```markdown
---
name: my-custom-skill
display_name: 自定义分析
description: ...
version: 1.0.0
category: custom
triggers: [分析, 统计]
agents: [researcher, reviewer]
---

# 规则
当用户提到分析时...
```

**预设8个Skills**（硬编码在代码中，不可删除但可禁用）：
academic-researcher, systematic-literature-review, scientific-thinking-literature-review, nature-polishing, reduce-aigc-rate, nature-writing, nature-citation, nature-figure

---

### 步骤5：CNKI知网MCP爬取连接

**新建文件**：
- `src/backend/services/cnki_service.py` — CNKI检索服务（调用MCP工具）
- `src/backend/routers/knowledge.py` — 知识库API路由

**实现方案**：通过后端Python调用已有的MCP工具爬取知网搜索结果

**API端点**：
```
POST /api/knowledge/cnki/search
Body: {"query": "网络情绪", "year_filter": "2020-2025", "count": 20}
Response: {
  "results": [
    {"title":"...", "author":"...", "year":2024, "source":"新闻与传播研究",
     "citations":45, "core":true, "abstract":"...", "doi":"..."}
  ],
  "total": 156, "source": "cnki_mcp"
}

GET /api/knowledge/status
Response: 各知识库连接状态

POST /api/knowledge/cnki/config
Body: {"api_key": "..."} — 配置知网访问参数
```

**CNKI爬取流程**：
1. 后端接收检索请求
2. 构造知网搜索URL：`https://scholar.cnki.net/home/search?sw={query}`
3. 调用 `mcp_Bright_Data.scrape_as_markdown` 或 `mcp_firecrawl-mcp.firecrawl_scrape` 获取页面内容
4. 解析Markdown内容提取文献信息（标题、作者、年份、来源、摘要）
5. 结构化返回结果

**兜底方案**：若MCP爬取失败，使用PubMed/CrossRef/arXiv等开放学术API作为补充

---

### 步骤6：Agent对话服务（DeepSeek + Langgraph）

**新建文件**：
- `src/backend/services/agent_service.py` — Langgraph Agent编排 + DeepSeek调用
- `src/backend/routers/agent.py` — Agent对话API

**API端点**：
```
POST /api/agent/chat
Body: {
  "message": "我想研究短视频对认知的影响",
  "agent_id": "researcher",
  "session_id": "xxx",
  "context": {
    "discipline": "humanities",
    "research_type": "qualitative",
    "readiness": "no_idea"
  }
}
Response: {
  "reply": "你好！让我帮你...",
  "options": ["我有大致方向", "完全没有头绪", ...],
  "skills_used": ["academic-researcher"],
  "cnki_results": null
}
```

**DeepSeek调用**：
- 模型：`deepseek-chat`（通过OpenAI兼容API）
- Base URL：`https://api.deepseek.com`
- API Key：`sk-a6f692b99ffe4120bc4cf6e49ebf5134`
- System Prompt：根据agent_id动态生成（研究员/审查员/架构师/综述员/润色员各有不同）

**Langgraph工作流**：
- 线性流程：选题→审查→架构→综述→润色
- 每个节点对应一个Agent
- 条件边：根据用户选择跳转到对应Agent

---

### 步骤7：前端对接修改

**修改文件**：`prototypes/interactive-prototype.html`

**6处关键修改**：

1. **图表生成**（L3585-3998）：
   - `generateChart()` → `fetch('/api/chart/generate', ...)` 调用后端
   - 图表显示从Canvas改为 `<img>` 标签
   - 添加生成中loading状态

2. **文件上传**（L3441-3583）：
   - `handleFileUpload()` → `fetch('/api/upload/{session_id}', ...)` 调用后端
   - 添加5-15文件数量限制检查
   - 显示"已上传 X/15 个文件"

3. **CNKI检索**（L4000-4239）：
   - `getMockCNKIResults()` → `fetch('/api/knowledge/cnki/search', ...)` 调用后端
   - 删除 `mockCNKIDatabase` 模拟数据

4. **Skills管理**（L4305-4501）：
   - `saveCustomSkill()` → `fetch('/api/skills', ...)` 调用后端
   - `getCustomSkills()` → `fetch('/api/skills', ...)` 从后端获取
   - 添加"上传Skills文件"按钮

5. **Agent对话**（L4242-4283）：
   - `sendMessage()` → `fetch('/api/agent/chat', ...)` 调用后端
   - 解析后端返回的reply、options、skills_used等

6. **设置页面**：
   - RAG知识库状态 → `fetch('/api/knowledge/status')`
   - CNKI配置入口

---

## 验证步骤

1. `pip install -r src/backend/requirements.txt` 安装依赖
2. `uvicorn src.backend.app:app --reload --port 8000` 启动后端
3. 访问 `http://localhost:8000/docs` 查看API文档
4. 测试图表生成：POST `/api/chart/generate` 生成缎带图
5. 测试文件上传：POST `/api/upload/test-session` 上传5个文件
6. 测试Skills：POST `/api/skills` 创建自定义Skill
7. 测试CNKI：POST `/api/knowledge/cnki/search` 检索"网络情绪"
8. 测试Agent：POST `/api/agent/chat` 发送消息
9. 打开前端原型，验证完整交互流程
