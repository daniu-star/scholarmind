# ScholarMind 24小时学术爬虫与Agent持续进化系统

## 摘要

为 ScholarMind 构建一套 24 小时运行的学术爬虫系统，基于 Celery + Redis 实现分布式定时任务调度，从 CNKI、CrossRef、PubMed、万方、维普五大数据源持续采集学术资源，存入本地数据库并通过 RAG（检索增强生成）机制注入 Agent 对话，实现 Agent 的持续进化。

---

## 一、当前状态分析

### 已有基础设施
- `CNKIService`：三级降级搜索（MCP → CNKI直连 → 代理 → CrossRef/PubMed），30分钟内存缓存
- `AgentService`：5个角色化 Agent，Skills 规则注入，对话持久化
- `SkillsService`：8个预设技能 + 自定义技能 YAML 管理
- FastAPI 应用：5个路由模块，lifespan 管理

### 关键缺口
| 维度 | 现状 | 需要 |
|------|------|------|
| 定时调度 | 完全不存在 | Celery + Redis |
| 数据持久化 | 内存缓存 + JSON 文件 | SQLite（轻量起步） |
| 爬虫能力 | 单次 HTTP + 正则解析 | 多数据源适配器 + 反爬策略 |
| 数据源 | CNKI + CrossRef + PubMed | + 万方 + 维普 |
| RAG | 不存在 | 向量数据库 + 检索注入 |
| Agent 升级 | 仅 prompt 注入 | RAG 检索增强 |

---

## 二、系统架构设计

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

## 三、新增文件与模块

### 3.1 数据层

| 文件 | 职责 |
|------|------|
| `src/backend/services/db_service.py` | SQLite 数据库服务，学术资源 CRUD |
| `src/backend/services/vector_service.py` | ChromaDB 向量数据库服务，RAG 检索 |

### 3.2 爬虫层

| 文件 | 职责 |
|------|------|
| `src/backend/crawlers/__init__.py` | 爬虫模块入口 |
| `src/backend/crawlers/base.py` | 爬虫基类 `BaseCrawler` |
| `src/backend/crawlers/cnki_crawler.py` | CNKI 爬虫适配器 |
| `src/backend/crawlers/crossref_crawler.py` | CrossRef 爬虫适配器 |
| `src/backend/crawlers/pubmed_crawler.py` | PubMed 爬虫适配器 |
| `src/backend/crawlers/wanfang_crawler.py` | 万方爬虫适配器 |
| `src/backend/crawlers/weipu_crawler.py` | 维普爬虫适配器 |

### 3.3 调度层

| 文件 | 职责 |
|------|------|
| `src/backend/scheduler/__init__.py` | 调度模块入口 |
| `src/backend/scheduler/celery_app.py` | Celery 应用配置与初始化 |
| `src/backend/scheduler/tasks.py` | 定时任务定义 |
| `src/backend/scheduler/rag_builder.py` | RAG 索引构建任务 |

### 3.4 RAG 层

| 文件 | 职责 |
|------|------|
| `src/backend/services/rag_service.py` | RAG 检索服务，向量检索 + 上下文组装 |

### 3.5 配置与路由

| 文件 | 修改内容 |
|------|----------|
| `src/backend/config.py` | 新增 Redis、Celery、ChromaDB、爬虫相关配置 |
| `src/backend/routers/knowledge.py` | 新增爬虫状态、RAG 检索端点 |
| `src/backend/services/agent_service.py` | 集成 RAG 检索到 Agent 对话 |
| `src/backend/app.py` | lifespan 中初始化数据库和 RAG 服务 |
| `src/backend/requirements.txt` | 新增依赖 |

---

## 四、各模块详细设计

### 4.1 数据库服务 (`db_service.py`)

使用 SQLite 存储学术资源元数据，轻量无需额外服务。

```python
# 学术资源表
class AcademicResource:
    id: str              # UUID
    title: str           # 标题
    authors: str         # 作者
    year: str            # 年份
    source: str          # 期刊/来源
    source_db: str       # 数据源标识 (cnki/crossref/pubmed/wanfang/weipu)
    abstract: str        # 摘要
    doi: str             # DOI
    citations: int       # 引用数
    is_core: bool        # 是否核心期刊
    keywords: str        # 关键词 (JSON数组)
    url: str             # 原文链接
    full_text_hash: str  # 全文哈希（用于去重）
    crawled_at: str      # 爬取时间
    updated_at: str      # 更新时间

# 爬虫任务日志表
class CrawlLog:
    id: str
    source_db: str       # 数据源
    task_type: str       # hot/latest/keyword
    status: str          # running/success/failed
    items_found: int     # 发现条目数
    items_saved: int     # 保存条目数
    error_msg: str       # 错误信息
    started_at: str
    finished_at: str

# 热门关键词表
class HotKeyword:
    id: str
    keyword: str
    frequency: int       # 出现频率
    source_db: str
    last_seen: str
```

### 4.2 向量数据库服务 (`vector_service.py`)

使用 ChromaDB 存储论文摘要的向量嵌入，支持语义检索。

- 嵌入模型：使用 `sentence-transformers` 的 `paraphrase-multilingual-MiniLM-L12-v2`（支持中英文）
- 集合名称：`academic_papers`
- 每篇论文存储：`title + abstract` 的嵌入向量 + 元数据（id, source, year, keywords）
- 检索时返回 top-k 最相关论文，注入 Agent 上下文

### 4.3 爬虫基类与适配器

```python
# base.py
class BaseCrawler(ABC):
    source_db: str           # 数据源标识
    rate_limit: float        # 请求间隔（秒）
    
    @abstractmethod
    async def crawl_hot(self, count: int) -> list[dict]: ...
    
    @abstractmethod
    async def crawl_latest(self, count: int) -> list[dict]: ...
    
    @abstractmethod
    async def crawl_by_keyword(self, keyword: str, count: int) -> list[dict]: ...
    
    async def run_with_rate_limit(self, task_fn): ...
```

**各数据源适配器**：

| 数据源 | 爬取方式 | 频率限制 | 反爬策略 |
|--------|----------|----------|----------|
| CNKI | HTTP POST + HTML解析 | 3秒/请求 | 随机延迟 + User-Agent轮换 |
| CrossRef | 公开 REST API | 1秒/请求 | 无需（礼貌性延迟） |
| PubMed | E-utilities API | 0.5秒/请求 | 无需（需API Key提升限额） |
| 万方 | HTTP + HTML解析 | 3秒/请求 | 随机延迟 + Cookie管理 |
| 维普 | HTTP + HTML解析 | 3秒/请求 | 随机延迟 + Cookie管理 |

### 4.4 Celery 定时任务

```python
# celery_app.py
app = Celery('scholarmind')
app.conf.update(
    broker_url='redis://localhost:6379/0',
    result_backend='redis://localhost:6379/1',
    timezone='Asia/Shanghai',
)

# tasks.py - 定时任务配置
CELERYBEAT_SCHEDULE = {
    # 每2小时爬取CNKI热门论文
    'crawl-cnki-hot': {
        'task': 'tasks.crawl_source',
        'schedule': crontab(minute=0, hour='*/2'),
        'args': ('cnki', 'hot', 50),
    },
    # 每4小时爬取CrossRef最新论文
    'crawl-crossref-latest': {
        'task': 'tasks.crawl_source',
        'schedule': crontab(minute=30, hour='*/4'),
        'args': ('crossref', 'latest', 100),
    },
    # 每4小时爬取PubMed最新论文
    'crawl-pubmed-latest': {
        'task': 'tasks.crawl_source',
        'schedule': crontab(minute=0, hour='*/4'),
        'args': ('pubmed', 'latest', 100),
    },
    # 每6小时爬取万方热门论文
    'crawl-wanfang-hot': {
        'task': 'tasks.crawl_source',
        'schedule': crontab(minute=0, hour='*/6'),
        'args': ('wanfang', 'hot', 50),
    },
    # 每6小时爬取维普热门论文
    'crawl-weipu-hot': {
        'task': 'tasks.crawl_source',
        'schedule': crontab(minute=30, hour='*/6'),
        'args': ('weipu', 'hot', 50),
    },
    # 每天凌晨3点构建RAG索引
    'build-rag-index': {
        'task': 'tasks.build_rag_index',
        'schedule': crontab(minute=0, hour=3),
    },
    # 每天凌晨4点更新热门关键词
    'update-hot-keywords': {
        'task': 'tasks.update_hot_keywords',
        'schedule': crontab(minute=0, hour=4),
    },
    # 每周日清理过期数据（30天前）
    'cleanup-old-data': {
        'task': 'tasks.cleanup_old_data',
        'schedule': crontab(minute=0, hour=2, day_of_week='sunday'),
    },
}
```

### 4.5 RAG 服务 (`rag_service.py`)

```python
class RAGService:
    def search(self, query: str, top_k: int = 5, filters: dict = None) -> list[dict]:
        """语义检索相关论文，返回标题+摘要+元数据"""
        
    def build_context(self, query: str, agent_id: str, top_k: int = 5) -> str:
        """组装 RAG 上下文字符串，注入 Agent system prompt"""
        
    def rebuild_index(self) -> int:
        """从数据库全量重建向量索引"""
```

### 4.6 Agent 集成 RAG

修改 `agent_service.py` 的 `_build_system_prompt()` 方法：

```python
def _build_system_prompt(self, agent_id: str, context: Optional[dict] = None) -> str:
    prompt = AGENT_PROMPTS[agent_id]
    
    # 1. 用户画像上下文（已有）
    if context: ...
    
    # 2. 技能规则注入（已有）
    skills_rules = self._load_skills_for_agent(agent_id)
    
    # 3. RAG 知识库注入（新增）
    rag_context = self.rag_service.build_context(
        query=last_user_message,  # 最近用户消息
        agent_id=agent_id,
        top_k=5,
    )
    if rag_context:
        prompt += "\n\n── 相关学术资源（来自知识库） ──\n"
        prompt += rag_context
    
    return prompt
```

### 4.7 新增 API 端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/knowledge/crawl/status` | GET | 获取爬虫运行状态 |
| `/api/knowledge/crawl/trigger` | POST | 手动触发爬虫任务 |
| `/api/knowledge/crawl/logs` | GET | 获取爬虫日志 |
| `/api/knowledge/rag/search` | POST | RAG 语义检索 |
| `/api/knowledge/rag/stats` | GET | RAG 索引统计 |
| `/api/knowledge/rag/rebuild` | POST | 手动触发索引重建 |
| `/api/knowledge/keywords/hot` | GET | 获取热门关键词 |

---

## 五、新增依赖

```
# requirements.txt 新增
celery>=5.3.0
redis>=5.0.0
chromadb>=0.4.0
sentence-transformers>=2.2.0
apscheduler>=3.10.0          # 作为 Celery 的补充，用于轻量级调度
beautifulsoup4>=4.12.0       # HTML 解析（替代正则）
lxml>=4.9.0                  # 更快的 XML/HTML 解析
fake-useragent>=1.4.0        # User-Agent 轮换
```

---

## 六、新增配置项

```python
# config.py 新增
REDIS_URL: str = "redis://localhost:6379/0"
CELERY_BROKER_URL: str = "redis://localhost:6379/0"
CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

CHROMA_DIR: str = "data/chroma"           # ChromaDB 持久化目录
DB_PATH: str = "data/scholarmind.db"      # SQLite 数据库路径

CRAWL_RATE_LIMIT: float = 3.0            # 爬虫请求间隔（秒）
CRAWL_MAX_RETRIES: int = 3               # 最大重试次数
CRAWL_DATA_RETENTION_DAYS: int = 30      # 数据保留天数

RAG_TOP_K: int = 5                        # RAG 检索返回数量
RAG_EMBEDDING_MODEL: str = "paraphrase-multilingual-MiniLM-L12-v2"

WANFANG_BASE_URL: str = "https://www.wanfangdata.com.cn"
WEIPU_BASE_URL: str = "https://qikan.cqvip.com"
```

---

## 七、实施步骤

### Step 1: 基础设施搭建
1. 新增依赖到 requirements.txt
2. 新增配置项到 config.py
3. 创建数据库服务 db_service.py（SQLite 表创建 + CRUD）
4. 创建向量数据库服务 vector_service.py（ChromaDB 初始化 + 嵌入）
5. 更新 app.py lifespan 初始化数据库

### Step 2: 爬虫适配器开发
1. 创建 crawlers/base.py 基类
2. 重构 cnki_crawler.py（从 cnki_service.py 提取爬取逻辑）
3. 创建 crossref_crawler.py（从 cnki_service.py 提取 CrossRef 逻辑）
4. 创建 pubmed_crawler.py（从 cnki_service.py 提取 PubMed 逻辑）
5. 创建 wanfang_crawler.py（万方数据爬取）
6. 创建 weipu_crawler.py（维普数据爬取）

### Step 3: Celery 调度系统
1. 创建 scheduler/celery_app.py
2. 创建 scheduler/tasks.py（定时任务定义）
3. 创建 scheduler/rag_builder.py（索引构建任务）

### Step 4: RAG 服务开发
1. 创建 services/rag_service.py
2. 集成到 agent_service.py 的 _build_system_prompt()
3. 新增 knowledge 路由端点

### Step 5: 集成测试
1. 启动 Redis 服务
2. 启动 Celery Worker
3. 启动 Celery Beat
4. 验证定时爬虫任务执行
5. 验证 RAG 检索注入 Agent

---

## 八、启动方式

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

## 九、假设与决策

1. **数据库选择 SQLite**：轻量起步，无需额外服务，后续可迁移 PostgreSQL
2. **向量数据库选择 ChromaDB**：嵌入式，无需独立服务，适合中小规模
3. **嵌入模型选择多语言 MiniLM**：支持中英文，模型小（~470MB），CPU 可运行
4. **万方/维普爬取**：基于 HTTP + HTML 解析，与 CNKI 类似的反爬策略
5. **RAG 注入方式**：在 system prompt 中追加检索结果，而非修改模型权重
6. **Celery 而非 APScheduler**：用户明确选择，支持分布式扩展
7. **保留现有 cnki_service.py**：作为按需搜索的接口，爬虫适配器复用其搜索逻辑
8. **数据去重**：基于 title + year + source_db 组合去重，避免重复存储
