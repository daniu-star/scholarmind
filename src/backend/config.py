import os
from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    DEBUG: bool = True
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    UPLOAD_DIR: str = "data/uploads"
    SKILLS_DIR: str = "data/skills"
    CHARTS_DIR: str = "data/charts"
    CONVERSATIONS_DIR: str = "data/conversations"

    MAX_FILES_PER_SESSION: int = 15
    MIN_FILES_PER_SESSION: int = 1
    MAX_FILE_SIZE_MB: int = 20

    ALLOWED_EXTENSIONS: set = {
        "csv", "xlsx", "json", "pdf", "docx",
        "md", "txt", "r", "py", "ipynb", "tex", "bib"
    }

    CORS_ORIGINS: list = ["http://localhost:8080", "http://127.0.0.1:8080", "http://localhost:8000"]
    CORS_ALLOW_ALL_IN_DEV: bool = True  # 开发模式下允许所有来源

    # Redis & Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # 数据库 & 向量数据库
    CHROMA_DIR: str = "data/chroma"
    DB_PATH: str = "data/scholarmind.db"

    # 爬虫配置
    CRAWL_RATE_LIMIT: float = 3.0       # 请求间隔（秒）
    CRAWL_MAX_RETRIES: int = 3          # 最大重试次数
    CRAWL_DATA_RETENTION_DAYS: int = 30 # 数据保留天数

    # RAG 配置
    RAG_TOP_K: int = 5
    RAG_EMBEDDING_MODEL: str = "paraphrase-multilingual-MiniLM-L12-v2"

    # 数据源 URL
    WANFANG_BASE_URL: str = "https://www.wanfangdata.com.cn"
    WEIPU_BASE_URL: str = "https://qikan.cqvip.com"

    # ── 新增：异步 ORM 数据库配置 ──────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///data/scholarmind_orm.db"

    # ── 新增：结构化日志配置 ────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # "json" | "console"

    # ── 新增：速率限制配置 ──────────────────────────────────
    RATE_LIMIT_REQUESTS: int = 60     # 每分钟最大请求数
    RATE_LIMIT_ENABLED: bool = True

    # ── 新增：后台任务配置 ──────────────────────────────────
    TASK_BACKEND: str = "background"  # "celery" | "background"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def ensure_dirs(self):
        for d in [self.UPLOAD_DIR, self.SKILLS_DIR, self.CHARTS_DIR,
                  self.CONVERSATIONS_DIR, self.CHROMA_DIR]:
            Path(d).mkdir(parents=True, exist_ok=True)
        # 确保 DB_PATH 的父目录存在
        Path(self.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        # 确保 ORM 数据库父目录存在
        Path(self.DATABASE_URL.replace("sqlite+aiosqlite:///", "")).parent.mkdir(
            parents=True, exist_ok=True
        )

    def get_cors_origins(self) -> list:
        """获取 CORS 允许的来源列表"""
        if self.CORS_ALLOW_ALL_IN_DEV:
            return ["*"]
        return self.CORS_ORIGINS


settings = Settings()
settings.ensure_dirs()
