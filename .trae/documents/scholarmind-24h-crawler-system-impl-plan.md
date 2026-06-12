# ScholarMind 24小时学术爬虫与Agent持续进化系统 — 实施计划

## 摘要

为 ScholarMind 构建一套 24 小时运行的学术爬虫系统，基于 Celery + Redis 实现分布式定时任务调度，从 CNKI、CrossRef、PubMed、万方、维普五大数据源持续采集学术资源，存入本地数据库并通过 RAG（检索增强生成）机制注入 Agent 对话，实现 Agent 的持续进化。

---

## 一、当前状态分析

### 已有基础设施
- `CNKIService`（[cnki_service.py](file:///c:/Users/13067/Desktop/AI产品/src/backend/services/cnki_service.py)）：三级降级搜索（MCP → CNKI直连 → 代理 → CrossRef/PubMed），30分钟内存缓存
- `AgentService`（[agent_service.py](file:///c:/Users/13067/Desktop/AI产品/src/backend/services/agent_service.py)）：5个角色化 Agent，Skills 规则注入，对话持久化，`_build_system_prompt()` 已有技能注入
- `SkillsService`：8个预设技能 + 自定义技能 YAML 管理
- FastAPI 应用（[app.py](file:///c:/Users/13067/Desktop/AI产品/src/backend/app.py)）：5个路由模块，lifespan 管理
- `KnowledgeRouter`（[knowledge.py](file:///c:/Users/13067/Desktop/AI产品/src/backend/routers/knowledge.py)）：CNKI搜索 + 配置 + 状态检查

### 关键缺口
| 维度 | 现状 | 需要 |
|------|------|------|
| 定时调度 | 完全不存在 | Celery + Redis |
| 数据持久化 | 内存缓存 + JSON 文件 | SQLite（轻量起步） |
| 爬虫能力 | 单次 HTTP + 正则解析 | 多数据源适配器 + 反爬策略 |
| 数据源 | CNKI + CrossRef + PubMed | + 万方 + 维普 |
| RAG | 不存在 | 向量数据库 + 检索注入 |
| Agent 升级 | 仅 prompt 注入 | RAG 检索增强 |

### 实现进度：0%（所有计划模块均未开始）

---

## 二、系统架构

```
┌─────────────────────────────────────────────────────┐
│                   FastAPI 主应用                      │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────────┐  │
│  │Agent │ │Chart │ │Upload│ │Skills│ │Knowledge │  │
│  │Router│ │Router│ │Router│ │Router│ │  Router  │  │
│  └──┬───┘ └──────┘ └──────┘ └──────┘ └────┬─────┘  │
│     │                                      │         │
│     │  ┌──────────────────────────┐        │         │
│     └──┤    RAG 检索服务          │◄───────┘         │
│        │  (向量检索 + 上下文注入)  │                  │
│        └────────────┬─────────────┘                  │
│                     │                                │
│        ┌────────────▼─────────────┐                  │
│        │    学术资源数据库          │                  │
│        │  (SQLite + ChromaDB)      │                  │
│        └────────────▲─────────────┘                  │
└─────────────────────┼───────────────────────────────┘
                      │ 写入
        ┌─────────────▼──────────────┐
        │     Celery Worker 进程      │
        │  ┌───────────────────────┐  │
        │  │  定时爬虫任务调度器    │  │
        │  │  (24h 轮询各数据源)   │  │
        │  └───────────┬───────────┘  │
        │              │               │
        │  ┌───┐ ┌───┐ ┌───┐ ┌───┐   │
        │  │CNK│ │万 │ │维 │ │Crf│   │
        │  │I  │ │方 │ │普 │ │Pm │   │
        │  └───┘ └───┘ └───┘ └───┘   │
        └──────────────────────────────┘
                      ▲
                      │ 消息队列
        ┌─────────────┴──────────────┐
        │         Redis               │
        │  (Broker + 结果后端)         │
        └─────────────────────────────┘
```

---

## 三、新增文件清单（14个新文件）

| 文件路径 | 职责 |
|----------|------|
| `src/backend/services/db_service.py` | SQLite 数据库服务，学术资源 CRUD |
| `src/backend/services/vector_service.py` | ChromaDB 向量数据库服务，RAG 检索 |
| `src/backend/services/rag_service.py` | RAG 检索服务，向量检索 + 上下文组装 |
| `src/backend/crawlers/__init__.py` | 爬虫模块入口 |
| `src/backend/crawlers/base.py` | 爬虫基类 `BaseCrawler` |
| `src/backend/crawlers/cnki_crawler.py` | CNKI 爬虫适配器 |
| `src/backend/crawlers/crossref_crawler.py` | CrossRef 爬虫适配器 |
| `src/backend/crawlers/pubmed_crawler.py` | PubMed 爬虫适配器 |
| `src/backend/crawlers/wanfang_crawler.py` | 万方爬虫适配器 |
| `src/backend/crawlers/weipu_crawler.py` | 维普爬虫适配器 |
| `src/backend/scheduler/__init__.py` | 调度模块入口 |
| `src/backend/scheduler/celery_app.py` | Celery 应用配置与初始化 |
| `src/backend/scheduler/tasks.py` | 定时任务定义 |
| `src/backend/scheduler/rag_builder.py` | RAG 索引构建任务 |

---

## 四、修改文件清单（5个现有文件）

### 4.1 `src/backend/requirements.txt`
新增依赖：
```
celery>=5.3.0
redis>=5.0.0
chromadb>=0.4.0
sentence-transformers>=2.2.0
beautifulsoup4>=4.12.0
lxml>=4.9.0
fake-useragent>=1.4.0
```

### 4.2 `src/backend/config.py`
新增配置项：
```python
REDIS_URL: str = "redis://localhost:6379/0"
CELERY_BROKER_URL: str = "redis://localhost:6379/0"
CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
CHROMA_DIR: str = "data/chroma"
DB_PATH: str = "data/scholarmind.db"
CRAWL_RATE_LIMIT: float = 3.0
CRAWL_MAX_RETRIES: int = 3
CRAWL_DATA_RETENTION_DAYS: int = 30
RAG_TOP_K: int = 5
RAG_EMBEDDING_MODEL: str = "paraphrase-multilingual-MiniLM-L12-v2"
WANFANG_BASE_URL: str = "https://www.wanfangdata.com.cn"
WEIPU_BASE_URL: str = "https://qikan.cqvip.com"
```
同时在 `ensure_dirs()` 中添加 `self.CHROMA_DIR` 和 `Path(self.DB_PATH).parent`。

### 4.3 `src/backend/app.py`
修改 `lifespan()` 函数：
- 启动时初始化 `db_service`（创建表）和 `vector_service`（初始化 ChromaDB）
- 关闭时清理数据库连接和向量服务

### 4.4 `src/backend/services/agent_service.py`
修改 `_build_system_prompt()` 方法（第251-272行）：
- 在技能规则注入之后，新增 RAG 知识库注入
- 使用最近用户消息作为查询，调用 `rag_service.build_context()` 获取相关论文
- 将检索结果追加到 system prompt

### 4.5 `src/backend/routers/knowledge.py`
新增7个端点：
- `GET /api/knowledge/crawl/status` — 爬虫运行状态
- `POST /api/knowledge/crawl/trigger` — 手动触发爬虫
- `GET /api/knowledge/crawl/logs` — 爬虫日志
- `POST /api/knowledge/rag/search` — RAG 语义检索
- `GET /api/knowledge/rag/stats` — RAG 索引统计
- `POST /api/knowledge/rag/rebuild` — 手动触发索引重建
- `GET /api/knowledge/keywords/hot` — 热门关键词

---

## 五、各模块详细设计

### 5.1 数据库服务 (`db_service.py`)

SQLite 存储学术资源元数据，轻量无需额外服务。

**表结构：**

```sql
-- 学术资源表
CREATE TABLE IF NOT EXISTS academic_resources (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    authors TEXT DEFAULT '',
    year TEXT DEFAULT '',
    source TEXT DEFAULT '',        -- 期刊/来源
    source_db TEXT NOT NULL,       -- cnki/crossref/pubmed/wanfang/weipu
    abstract TEXT DEFAULT '',
    doi TEXT DEFAULT '',
    citations INTEGER DEFAULT 0,
    is_core INTEGER DEFAULT 0,     -- 是否核心期刊
    keywords TEXT DEFAULT '[]',    -- JSON数组
    url TEXT DEFAULT '',
    full_text_hash TEXT DEFAULT '', -- 去重用
    crawled_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(title, year, source_db) -- 去重约束
);

-- 爬虫任务日志表
CREATE TABLE IF NOT EXISTS crawl_logs (
    id TEXT PRIMARY KEY,
    source_db TEXT NOT NULL,
    task_type TEXT NOT NULL,       -- hot/latest/keyword
    status TEXT NOT NULL,          -- running/success/failed
    items_found INTEGER DEFAULT 0,
    items_saved INTEGER DEFAULT 0,
    error_msg TEXT DEFAULT '',
    started_at TEXT NOT NULL,
    finished_at TEXT DEFAULT ''
);

-- 热门关键词表
CREATE TABLE IF NOT EXISTS hot_keywords (
    id TEXT PRIMARY KEY,
    keyword TEXT NOT NULL,
    frequency INTEGER DEFAULT 1,
    source_db TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE(keyword, source_db)
);
```

**核心方法：**
- `init_db()` — 创建表
- `save_resource(resource: dict) -> bool` — 保存单条资源（去重）
- `save_resources_batch(resources: list[dict]) -> int` — 批量保存，返回新增数量
- `search_resources(query: str, source_db: str = None, limit: int = 20) -> list[dict]`
- `get_recent_resources(source_db: str = None, limit: int = 50) -> list[dict]`
- `log_crawl(log: dict)` — 记录爬虫日志
- `get_crawl_logs(source_db: str = None, limit: int = 20) -> list[dict]`
- `upsert_keyword(keyword: str, source_db: str)` — 更新关键词频率
- `get_hot_keywords(limit: int = 20) -> list[dict]`
- `cleanup_old_data(days: int = 30) -> int` — 清理过期数据

### 5.2 向量数据库服务 (`vector_service.py`)

ChromaDB 存储论文摘要的向量嵌入，支持语义检索。

- 嵌入模型：`sentence-transformers` 的 `paraphrase-multilingual-MiniLM-L12-v2`（支持中英文，~470MB）
- 集合名称：`academic_papers`
- 每篇论文存储：`title + abstract` 的嵌入向量 + 元数据（id, source_db, year, keywords）
- 检索时返回 top-k 最相关论文

**核心方法：**
- `init()` — 初始化 ChromaDB 客户端和嵌入函数
- `add_documents(documents: list[dict])` — 批量添加文档
- `search(query: str, top_k: int = 5, filters: dict = None) -> list[dict]`
- `get_collection_stats() -> dict` — 返回文档数量等信息
- `rebuild_from_db(db_service)` — 从 SQLite 全量重建索引
- `delete_by_ids(ids: list[str])` — 删除指定文档

### 5.3 RAG 服务 (`rag_service.py`)

组装向量检索结果为 Agent 可用的上下文。

**核心方法：**
- `search(query: str, top_k: int = 5, filters: dict = None) -> list[dict]` — 语义检索
- `build_context(query: str, agent_id: str = None, top_k: int = 5) -> str` — 组装 RAG 上下文字符串
- `rebuild_index() -> int` — 从数据库全量重建向量索引
- `get_stats() -> dict` — 返回索引统计信息

`build_context()` 输出格式：
```
1. [论文标题] (作者, 年份, 期刊) — 引用数: N
   摘要：xxx...
2. [论文标题] ...
```

### 5.4 爬虫基类与适配器

**基类 (`base.py`)：**
```python
class BaseCrawler(ABC):
    source_db: str           # 数据源标识
    rate_limit: float = 3.0  # 请求间隔（秒）

    @abstractmethod
    async def crawl_hot(self, count: int = 50) -> list[dict]: ...

    @abstractmethod
    async def crawl_latest(self, count: int = 100) -> list[dict]: ...

    @abstractmethod
    async def crawl_by_keyword(self, keyword: str, count: int = 20) -> list[dict]: ...

    async def run_with_rate_limit(self, task_fn):
        """执行任务并遵守速率限制"""
        ...

    def normalize(self, raw: dict) -> dict:
        """将各数据源的原始数据统一为标准格式"""
        return {
            "id": str(uuid.uuid4()),
            "title": raw.get("title", ""),
            "authors": raw.get("authors", ""),
            "year": raw.get("year", ""),
            "source": raw.get("source", ""),
            "source_db": self.source_db,
            "abstract": raw.get("abstract", ""),
            "doi": raw.get("doi", ""),
            "citations": raw.get("citations", 0),
            "is_core": raw.get("is_core", False),
            "keywords": json.dumps(raw.get("keywords", []), ensure_ascii=False),
            "url": raw.get("url", ""),
            "full_text_hash": hashlib.md5(raw.get("title", "").encode()).hexdigest(),
            "crawled_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
```

**各数据源适配器：**

| 数据源 | 爬取方式 | 频率限制 | 反爬策略 |
|--------|----------|----------|----------|
| CNKI | HTTP POST + BeautifulSoup 解析 | 3秒/请求 | 随机延迟 + User-Agent轮换 |
| CrossRef | 公开 REST API (`api.crossref.org`) | 1秒/请求 | 无需（礼貌性延迟） |
| PubMed | E-utilities API (`eutils.ncbi.nlm.nih.gov`) | 0.5秒/请求 | 无需（需API Key提升限额） |
| 万方 | HTTP + BeautifulSoup 解析 | 3秒/请求 | 随机延迟 + Cookie管理 |
| 维普 | HTTP + BeautifulSoup 解析 | 3秒/请求 | 随机延迟 + Cookie管理 |

**CNKI 爬虫**：复用现有 `cnki_service.py` 的搜索逻辑，将其 `search()` 方法封装为 `crawl_by_keyword()`。`crawl_hot()` 通过搜索热门关键词列表实现。

**CrossRef 爬虫**：调用 `/works` 端点，按日期排序获取最新论文，按引用数排序获取热门论文。

**PubMed 爬虫**：调用 `esearch.fcgi` + `efetch.fcgi`，按日期获取最新论文。

**万方/维普爬虫**：HTTP 请求 + HTML 解析，与 CNKI 类似的反爬策略。

### 5.5 Celery 定时任务

**`celery_app.py`：**
```python
app = Celery('scholarmind')
app.conf.update(
    broker_url=settings.CELERY_BROKER_URL,
    result_backend=settings.CELERY_RESULT_BACKEND,
    timezone='Asia/Shanghai',
    enable_utc=True,
    task_serializer='json',
    result_serializer='json',
)
```

**`tasks.py` — 定时任务配置：**
```python
CELERYBEAT_SCHEDULE = {
    'crawl-cnki-hot': {
        'task': 'scheduler.tasks.crawl_source',
        'schedule': crontab(minute=0, hour='*/2'),
        'args': ('cnki', 'hot', 50),
    },
    'crawl-crossref-latest': {
        'task': 'scheduler.tasks.crawl_source',
        'schedule': crontab(minute=30, hour='*/4'),
        'args': ('crossref', 'latest', 100),
    },
    'crawl-pubmed-latest': {
        'task': 'scheduler.tasks.crawl_source',
        'schedule': crontab(minute=0, hour='*/4'),
        'args': ('pubmed', 'latest', 100),
    },
    'crawl-wanfang-hot': {
        'task': 'scheduler.tasks.crawl_source',
        'schedule': crontab(minute=0, hour='*/6'),
        'args': ('wanfang', 'hot', 50),
    },
    'crawl-weipu-hot': {
        'task': 'scheduler.tasks.crawl_source',
        'schedule': crontab(minute=30, hour='*/6'),
        'args': ('weipu', 'hot', 50),
    },
    'build-rag-index': {
        'task': 'scheduler.tasks.build_rag_index',
        'schedule': crontab(minute=0, hour=3),
    },
    'update-hot-keywords': {
        'task': 'scheduler.tasks.update_hot_keywords',
        'schedule': crontab(minute=0, hour=4),
    },
    'cleanup-old-data': {
        'task': 'scheduler.tasks.cleanup_old_data',
        'schedule': crontab(minute=0, hour=2, day_of_week='sunday'),
    },
}
```

**`rag_builder.py`：**
- `build_rag_index_task()` — 从 SQLite 全量重建 ChromaDB 索引
- 先清空现有向量集合，再批量添加所有学术资源

### 5.6 Agent 集成 RAG

修改 [agent_service.py](file:///c:/Users/13067/Desktop/AI产品/src/backend/services/agent_service.py) 第251-272行的 `_build_system_prompt()` 方法：

```python
def _build_system_prompt(self, agent_id: str, context: Optional[dict] = None) -> str:
    prompt = AGENT_PROMPTS[agent_id]

    # 1. 用户画像上下文（已有）
    if context:
        for key, template in CONTEXT_TEMPLATES.items():
            value = context.get(key)
            if value:
                prompt += template.format(value=value)

    # 2. 技能规则注入（已有）
    skills_rules = self._load_skills_for_agent(agent_id)
    if skills_rules:
        prompt += "\n\n── 已启用的技能规则 ──\n"
        for skill in skills_rules:
            prompt += f"\n【技能：{skill['display_name']}】\n"
            if skill.get("rules"):
                prompt += skill["rules"] + "\n"

    # 3. RAG 知识库注入（新增）
    if self.rag_service and context and context.get("last_message"):
        rag_context = self.rag_service.build_context(
            query=context["last_message"],
            agent_id=agent_id,
            top_k=settings.RAG_TOP_K,
        )
        if rag_context:
            prompt += "\n\n── 相关学术资源（来自知识库） ──\n"
            prompt += rag_context

    return prompt
```

同时在 `AgentService.__init__()` 中初始化 `self.rag_service`。

---

## 六、实施步骤

### Step 1: 基础设施搭建
1. 更新 `requirements.txt` — 新增7个依赖包
2. 更新 `config.py` — 新增12个配置项 + ensure_dirs 扩展
3. 创建 `db_service.py` — SQLite 表创建 + CRUD
4. 创建 `vector_service.py` — ChromaDB 初始化 + 嵌入 + 检索
5. 更新 `app.py` lifespan — 初始化数据库和向量服务

### Step 2: 爬虫适配器开发
1. 创建 `crawlers/__init__.py`
2. 创建 `crawlers/base.py` — BaseCrawler 基类
3. 创建 `crawlers/cnki_crawler.py` — 复用 cnki_service.py 搜索逻辑
4. 创建 `crawlers/crossref_crawler.py` — CrossRef REST API
5. 创建 `crawlers/pubmed_crawler.py` — PubMed E-utilities API
6. 创建 `crawlers/wanfang_crawler.py` — 万方 HTTP + HTML 解析
7. 创建 `crawlers/weipu_crawler.py` — 维普 HTTP + HTML 解析

### Step 3: Celery 调度系统
1. 创建 `scheduler/__init__.py`
2. 创建 `scheduler/celery_app.py` — Celery 配置
3. 创建 `scheduler/tasks.py` — 8个定时任务
4. 创建 `scheduler/rag_builder.py` — 索引构建任务

### Step 4: RAG 服务与集成
1. 创建 `services/rag_service.py`
2. 修改 `agent_service.py` — 集成 RAG 到 `_build_system_prompt()`
3. 修改 `knowledge.py` — 新增7个 API 端点

### Step 5: 集成测试
1. 验证所有模块导入无误
2. 验证 SQLite 表创建
3. 验证 ChromaDB 初始化
4. 验证爬虫适配器可运行
5. 验证 RAG 检索注入 Agent

---

## 七、启动方式

```bash
# 1. 启动 Redis
redis-server

# 2. 启动 FastAPI 主应用
cd src/backend
uvicorn app:app --host 0.0.0.0 --port 8000

# 3. 启动 Celery Worker（另一个终端）
cd src/backend
celery -A scheduler.celery_app worker --loglevel=info

# 4. 启动 Celery Beat（定时调度，另一个终端）
cd src/backend
celery -A scheduler.celery_app beat --loglevel=info
```

---

## 八、假设与决策

1. **数据库选择 SQLite**：轻量起步，无需额外服务，后续可迁移 PostgreSQL
2. **向量数据库选择 ChromaDB**：嵌入式，无需独立服务，适合中小规模
3. **嵌入模型选择多语言 MiniLM**：支持中英文，模型小（~470MB），CPU 可运行
4. **万方/维普爬取**：基于 HTTP + HTML 解析，与 CNKI 类似的反爬策略
5. **RAG 注入方式**：在 system prompt 中追加检索结果，而非修改模型权重
6. **Celery 而非 APScheduler**：用户明确选择，支持分布式扩展
7. **保留现有 cnki_service.py**：作为按需搜索的接口，爬虫适配器复用其搜索逻辑
8. **数据去重**：基于 title + year + source_db 组合去重，避免重复存储
