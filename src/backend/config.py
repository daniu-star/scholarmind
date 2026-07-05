from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

# ── 绝对路径锚点（P0 Task 5.1/5.2）──────────────────────────
# PROJECT_ROOT 指向 src/backend/ 目录，与启动 cwd 无关。
# 所有 data 目录字段在 Settings.model_post_init 中基于 PROJECT_ROOT 解析为绝对 Path。
PROJECT_ROOT: Path = Path(__file__).resolve().parent
WORKSPACE_ROOT: Path = PROJECT_ROOT.parent.parent
DATA_ROOT: Path = PROJECT_ROOT / "data"


def _is_placeholder_key(value: str) -> bool:
    """判断敏感配置值是否为占位符（未配置真实值）

    P0 修复: 通用化占位符识别，覆盖以下模式（不区分大小写）：
    - 空字符串
    - YOUR_ 开头或包含
    - _HERE 包含
    - XXXX 包含
    - your-domain.com 包含
    - example.com 包含
    - placeholder 包含
    - changeme 包含
    - dev-auto- 开头（自动生成的开发密钥）
    """
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    v = value.strip()
    if not v:
        return True
    lower = v.lower()
    if (
        lower.startswith("your_")
        or "your_" in lower
        or "_here" in lower
        or "xxxx" in lower
        or "your-domain.com" in lower
        or "example.com" in lower
        or "placeholder" in lower
        or "changeme" in lower
        or lower.startswith("dev-auto-")
    ):
        return True
    # 全 x（如 xxxxxxxxxxxxxx）
    stripped = v.replace("-", "").replace("_", "")
    if stripped and set(stripped) == {"x"}:
        return True
    return False


class Settings(BaseSettings):
    # ── 版本号(统一管理,避免多处硬编码) ──────────────────
    VERSION: str = "3.0.0"

    # ── 环境配置 ────────────────────────────────────────────
    ENVIRONMENT: str = "development"  # "development" | "production" | "test"
    BASE_URL: str = "http://localhost:8000"  # P0: 生产环境必须配置为公网域名
    # P0 修复：默认 DEBUG=False（fail-secure），开发环境显式设置 DEBUG=true
    DEBUG: bool = False
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    # Flash/Pro 双模型配置（前端 toggle 切换，后端根据 request.model 动态选择）
    DEEPSEEK_MODEL_FLASH: str = "deepseek-v4-flash"
    DEEPSEEK_MODEL_PRO: str = "deepseek-v4-pro"

    # ── LLM 客户端鲁棒性配置 ────────────────────────────────
    LLM_TIMEOUT: int = Field(default=60, ge=5, le=300, description="LLM 调用超时（秒）")
    LLM_MAX_RETRIES: int = Field(default=3, ge=0, le=10, description="LLM 调用最大重试次数")
    LLM_RETRY_INITIAL_DELAY: float = Field(default=1.0, ge=0.1, le=10.0, description="LLM 重试初始退避（秒）")

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

    CORS_ORIGINS: list = [
        "http://localhost:5173", "http://127.0.0.1:5173",  # Vite 前端
        "http://localhost:8080", "http://127.0.0.1:8080",  # 备用
        "http://localhost:8000", "http://127.0.0.1:8000",  # 后端直连
    ]
    CORS_ALLOW_ALL_IN_DEV: bool = False  # P0 修复：默认关闭全放通，开发环境显式开启

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

    # ── CNKI 反爬配置 ──
    CNKI_TLS_IMPERSONATE: str = Field(
        default="chrome124",
        description="curl_cffi TLS 指纹模拟目标 (chrome120/chrome121/chrome123/chrome124)",
    )
    CNKI_MASTER_URL: str = Field(
        default="http://localhost:8100",
        description="cnki-downloader Master 节点地址",
    )
    CNKI_MASTER_ENABLED: bool = Field(
        default=False,
        description="是否启用 cnki-downloader Master 搜索桥接",
    )
    CNKI_CAPTCHA_API_KEY: str = Field(
        default="",
        description="外部打码平台 API Key (capsolver/2captcha)",
    )

    # ── 学术搜索配置 ──
    SEMANTIC_SCHOLAR_API_KEY: Optional[str] = Field(
        default=None,
        description="Semantic Scholar API Key（可选，无 key 使用免费 tier）",
    )
    SEMANTIC_SCHOLAR_BASE_URL: str = Field(
        default="https://api.semanticscholar.org/graph/v1",
        description="Semantic Scholar API 基础 URL",
    )
    ARXIV_BASE_URL: str = Field(
        default="http://export.arxiv.org/api/query",
        description="arXiv API 基础 URL",
    )
    ACADEMIC_SEARCH_TIMEOUT: int = Field(
        default=15,
        ge=5,
        le=60,
        description="学术搜索超时时间（秒）",
    )
    ACADEMIC_SEARCH_MAX_CONCURRENT: int = Field(
        default=5,
        ge=1,
        le=20,
        description="学术搜索最大并发数据源数",
    )
    ACADEMIC_SEARCH_CACHE_TTL: int = Field(
        default=1800,
        ge=60,
        le=7200,
        description="学术搜索缓存 TTL（秒，默认 30 分钟）",
    )

    # ── 新增：异步 ORM 数据库配置 ──────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///data/scholarmind_orm.db"

    # ── 新增：结构化日志配置 ────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # "json" | "console"

    # ── 新增：速率限制配置 ──────────────────────────────────
    RATE_LIMIT_REQUESTS: int = 60     # 每分钟最大请求数
    RATE_LIMIT_ENABLED: bool = True
    # 限流身份解析：受信任代理 IP（逗号分隔），仅当直连客户端 IP 在此集合内时
    # 才信任 X-Forwarded-For 最左值作为真实客户端 IP；默认仅信任本地回环。
    RATE_LIMIT_TRUSTED_PROXIES: str = "127.0.0.1,::1"

    # ── Task 24: Pipeline 与 Agent 配置项（抽取自硬编码常量）──
    MAX_HISTORY_MESSAGES: int = 40
    PIPELINE_MAX_CONCURRENCY: int = 3
    PIPELINE_TIMEOUT_SECONDS: int = 600
    PIPELINE_HEARTBEAT_INTERVAL_SECONDS: int = 15
    PIPELINE_PROGRESS_SYNC_INTERVAL_SECONDS: int = 3

    # ── P0 Task 1.1：代码执行入口总开关 ─────────────────────
    # 默认 False：生产环境必须显式 CODE_EXECUTION_ENABLED=true 才注册
    # /api/v1/code-execution/* 路由，且即便启用也强制管理员鉴权 + 审计日志。
    CODE_EXECUTION_ENABLED: bool = False

    # ── P0 Task 2.1：支付回调总开关 ─────────────────────────
    # 默认 False：生产环境必须显式 PAYMENT_ENABLED=true 才注册
    # /api/v1/payment/{alipay,wechat}/notify 回调路由。
    # PAYMENT_VERIFY_REQUIRED=True 时强制验签；False 仅用于本地联调。
    PAYMENT_ENABLED: bool = False
    PAYMENT_VERIFY_REQUIRED: bool = True

    # ── P0 Task 1.3：管理员用户名白名单 ─────────────────────
    # require_admin 依赖据此判定；逗号分隔。生产环境通过环境变量配置。
    ADMIN_USERNAMES: str = "admin"

    # ── 认证配置 ──
    # Task 16: 移除 default_factory 自动生成逻辑，改为空字符串默认值。
    # 开发环境由 core/events.py startup 检测空值后生成临时密钥并 warning；
    # 生产环境由 validate_production() 强制校验非空且非占位符。
    JWT_SECRET_KEY: str = Field(
        default="",
        description="JWT 签名密钥：生产环境必须通过环境变量显式设置（dev 环境留空将自动生成临时密钥）",
    )
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 天
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    PASSWORD_MIN_LENGTH: int = 8

    # ── 免费配额 ──
    FREE_TIER_TOKEN_LIMIT: int = 1000000  # 1M tokens
    FREE_TIER_MODEL: str = "flash"
    PRO_TIER_TOKEN_LIMIT: int = 10000000  # 10M tokens
    FREE_CHAT_LIMIT: int = 20

    # ── 微信支付 ──
    WECHAT_PAY_APP_ID: str = ""
    WECHAT_PAY_MCH_ID: str = ""
    WECHAT_PAY_PRIVATE_KEY: str = ""
    WECHAT_PAY_CERT_SERIAL_NO: str = ""
    WECHAT_PAY_APIV3_KEY: str = ""
    WECHAT_PAY_PLATFORM_PUBLIC_KEY: str = ""
    WECHAT_PAY_PLATFORM_CERT: str = ""
    WECHAT_PAY_NOTIFY_URL: str = "https://your-domain.com/api/v1/payment/wechat/notify"

    # ── 支付宝 ──
    ALIPAY_APP_ID: str = ""
    ALIPAY_PRIVATE_KEY: str = ""
    ALIPAY_PUBLIC_KEY: str = ""
    ALIPAY_NOTIFY_URL: str = "https://your-domain.com/api/v1/payment/alipay/notify"
    ALIPAY_RETURN_URL: str = ""  # 空则由 BASE_URL 拼接
    ALIPAY_SELLER_ID: str = ""
    ALIPAY_SANDBOX: bool = True

    # P1 Task 17：套餐定价已迁移至 services/entitlement_service.py 的 PRODUCTS 字典
    # （amount_cents 字段，单位：分）。config 不再持有 PRO_MONTHLY_PRICE/PRO_YEARLY_PRICE，
    # 消除"价格双源"导致配置与代码不一致的风险。

    # ── 新增：后台任务配置 ──────────────────────────────────
    TASK_BACKEND: str = "background"  # "celery" | "background"

    # ── 邮箱验证码配置（支持 QQ/163/126/Gmail/Outlook 等主流邮箱）──
    # SMTP_HOST 和 SMTP_PORT 留空（不设环境变量）时，从 SMTP_USER 邮箱域名自动检测
    SMTP_HOST: str = Field(default="", description="留空则自动检测")
    SMTP_PORT: int = Field(default=0, description="0=自动检测，465=SSL，587=STARTTLS")
    SMTP_USER: str = Field(default="", description="发件邮箱地址")
    SMTP_PASSWORD: str = Field(default="", description="邮箱授权码")
    SMTP_FROM_NAME: str = "ScholarMind"
    VERIFICATION_CODE_EXPIRE_MINUTES: int = 5
    VERIFICATION_CODE_LENGTH: int = 6
    VERIFICATION_CODE_RATE_LIMIT_SECONDS: int = 60

    # ── 支付模式（v2.0: 个人收款码已移除，统一走 API 网关 + 回调 + 轮询）─

    # P0 Task 5.2: env_file 使用基于 PROJECT_ROOT 的绝对路径，不依赖进程 cwd。
    model_config = SettingsConfigDict(
        env_file=str(WORKSPACE_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",  # P0 修复: 兼容 CI/CD 注入的 BUILD_ID 等环境变量
    )

    def model_post_init(self, __context) -> None:
        """P0 Task 5.1: 将所有目录字段解析为绝对路径。

        - UPLOAD_DIR / SKILLS_DIR / CHARTS_DIR / CONVERSATIONS_DIR / CHROMA_DIR / DB_PATH
          若为相对路径，则基于 PROJECT_ROOT 解析为绝对路径（等价于原 cwd=src/backend
          时的相对路径行为）。先 expanduser 展开 ~。
        - DATABASE_URL 若为 sqlite 相对路径，则重建为基于 PROJECT_ROOT 的绝对 URL。
        这样无论从哪个 cwd 启动 uvicorn，所有路径都解析到同一绝对位置。
        """
        super().model_post_init(__context)
        _dir_fields = (
            "UPLOAD_DIR",
            "SKILLS_DIR",
            "CHARTS_DIR",
            "CONVERSATIONS_DIR",
            "CHROMA_DIR",
            "DB_PATH",
        )
        for field_name in _dir_fields:
            value = getattr(self, field_name)
            # expanduser 展开 ~ / ~user，避免把 home 目录相对路径误拼到 PROJECT_ROOT 下
            p = Path(value).expanduser()
            if not p.is_absolute():
                p = PROJECT_ROOT / p
            setattr(self, field_name, str(p))

        # SQLite URL 由绝对路径构建（仅处理 sqlite 相对 URL，避免误改 PostgreSQL）
        db_url = self.DATABASE_URL
        if ":///" in db_url:
            prefix, _, path_part = db_url.partition(":///")
            if prefix.startswith("sqlite"):
                p = Path(path_part).expanduser()
                if not p.is_absolute():
                    p = PROJECT_ROOT / p
                # 使用 as_posix() 统一为正斜杠，避免 Windows 反斜杠在 URL 中转义
                self.DATABASE_URL = f"{prefix}:///{p.resolve().as_posix()}"

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
        """获取 CORS 允许的来源列表

        安全策略:
        - 生产环境(ENVIRONMENT=production)强制只使用 CORS_ORIGINS 白名单
        - 开发环境且 CORS_ALLOW_ALL_IN_DEV=True 时返回 ["*"](仅限非生产)
        - 测试环境使用 CORS_ORIGINS 白名单
        """
        # 生产环境强制白名单,忽略 CORS_ALLOW_ALL_IN_DEV
        if self.ENVIRONMENT == "production":
            return self.CORS_ORIGINS

        # 非生产环境,若显式开启且非 test,允许 ["*"](开发便利)
        if self.CORS_ALLOW_ALL_IN_DEV and self.ENVIRONMENT != "test":
            import warnings
            warnings.warn(
                "CORS_ALLOW_ALL_IN_DEV=True 在非生产环境启用,"
                "请确保生产环境不会启用此选项",
                RuntimeWarning,
                stacklevel=2,
            )
            return ["*"]

        return self.CORS_ORIGINS

    def get_cors_allow_credentials(self) -> bool:
        """获取 CORS allow_credentials 配置

        安全策略：当 allow_origins 为 ["*"] 时强制 False，避免浏览器拒绝+CSRF 风险
        """
        if self.get_cors_origins() == ["*"]:
            return False
        return True

    def validate_production(self) -> None:
        """生产环境安全校验：启动时检查关键配置"""
        if self.ENVIRONMENT != "production":
            return
        errors: list[str] = []
        # Task 16.2: 显式校验非空且非占位符（双保险：_is_placeholder_key 已覆盖空字符串，此处显式化便于排查）
        if not self.JWT_SECRET_KEY or _is_placeholder_key(self.JWT_SECRET_KEY):
            errors.append("JWT_SECRET_KEY 未设置或仍为占位符/自动生成的开发密钥，生产环境必须显式设置")
        if len(self.JWT_SECRET_KEY) < 32:
            errors.append("JWT_SECRET_KEY 长度不足 32 字符，存在被暴力破解风险")
        if self.DEBUG:
            errors.append("DEBUG=True 不应在生产环境启用")
        if self.CORS_ALLOW_ALL_IN_DEV:
            errors.append("CORS_ALLOW_ALL_IN_DEV=True 不应在生产环境启用")
        # P0 修复: DEEPSEEK_API_KEY 占位符校验（保留原有校验，使用通用 _is_placeholder_key）
        if _is_placeholder_key(self.DEEPSEEK_API_KEY):
            errors.append("DEEPSEEK_API_KEY 未设置或仍为占位符，生产环境必须显式设置真实密钥")
        if self.PAYMENT_ENABLED:
            payment_fields = (
                "ALIPAY_APP_ID",
                "ALIPAY_PRIVATE_KEY",
                "ALIPAY_PUBLIC_KEY",
                "ALIPAY_SELLER_ID",
                "WECHAT_PAY_APP_ID",
                "WECHAT_PAY_MCH_ID",
                "WECHAT_PAY_PRIVATE_KEY",
                "WECHAT_PAY_CERT_SERIAL_NO",
                "WECHAT_PAY_APIV3_KEY",
            )
            missing = [name for name in payment_fields if not getattr(self, name)]
            if not (self.WECHAT_PAY_PLATFORM_PUBLIC_KEY or self.WECHAT_PAY_PLATFORM_CERT):
                missing.append("WECHAT_PAY_PLATFORM_PUBLIC_KEY/WECHAT_PAY_PLATFORM_CERT")
            if missing:
                errors.append("支付已启用但缺少配置: " + ", ".join(missing))
            if not self.PAYMENT_VERIFY_REQUIRED:
                errors.append("生产环境 PAYMENT_VERIFY_REQUIRED 必须为 true")
            if not self.ALIPAY_NOTIFY_URL.startswith("https://"):
                errors.append("ALIPAY_NOTIFY_URL 必须使用公网 HTTPS")
            if not self.WECHAT_PAY_NOTIFY_URL.startswith("https://"):
                errors.append("WECHAT_PAY_NOTIFY_URL 必须使用公网 HTTPS")
            # P0 修复: 支付相关敏感字段占位符校验
            payment_placeholder_fields = (
                "ALIPAY_APP_ID",
                "ALIPAY_PRIVATE_KEY",
                "WECHAT_PAY_APP_ID",
                "WECHAT_PAY_PRIVATE_KEY",
            )
            placeholder_violations = [
                name for name in payment_placeholder_fields
                if getattr(self, name) and _is_placeholder_key(getattr(self, name))
            ]
            if placeholder_violations:
                errors.append("支付配置仍为占位符，请配置真实值: " + ", ".join(placeholder_violations))
        # P0 修复: 回调 URL 占位符校验（your-domain.com 等）
        if _is_placeholder_key(self.WECHAT_PAY_NOTIFY_URL):
            errors.append("WECHAT_PAY_NOTIFY_URL 仍为占位符（如 your-domain.com），请配置真实公网域名")
        if _is_placeholder_key(self.ALIPAY_NOTIFY_URL):
            errors.append("ALIPAY_NOTIFY_URL 仍为占位符（如 your-domain.com），请配置真实公网域名")
        # P0 修复: SMTP_PASSWORD 占位符校验（仅当 SMTP_USER 非空时）
        if self.SMTP_USER and _is_placeholder_key(self.SMTP_PASSWORD):
            errors.append("SMTP_PASSWORD 仍为占位符，请配置真实邮箱授权码")
        # P1 修复: 生产环境禁止使用 SQLite
        if "sqlite" in self.DATABASE_URL.lower():
            errors.append("生产环境禁止使用 SQLite，请配置 PostgreSQL DATABASE_URL")
        # P1 修复: 支付回调 URL 显式检测 your-domain.com 占位符（_is_placeholder_key 只识别 YOUR_/XXXX，识别不到 your-domain.com）
        for url_field in ("ALIPAY_NOTIFY_URL", "WECHAT_PAY_NOTIFY_URL", "ALIPAY_RETURN_URL"):
            url_value = getattr(self, url_field, "")
            if url_value and "your-domain.com" in url_value:
                errors.append(f"{url_field} 仍为 your-domain.com 占位符，请配置真实公网 HTTPS 域名（如 https://api.quannengyanjiu.cn/...）")
        # P1 修复: 生产环境 CORS_ORIGINS 必须包含真实公网域名，不得仅 localhost
        cors_origins_lower = [o.lower() for o in self.CORS_ORIGINS]
        has_public_origin = any(
            o.startswith("https://") and "localhost" not in o and "127.0.0.1" not in o
            for o in cors_origins_lower
        )
        if not has_public_origin:
            errors.append(
                "CORS_ORIGINS 在生产环境必须包含真实公网 HTTPS 域名"
                "（如 https://quannengyanjiu.cn），不得仅含 localhost"
            )
        if errors:
            raise RuntimeError("生产环境配置校验失败:\n  " + "\n  ".join(errors))


settings = Settings()
# P0/P1 修复: ensure_dirs() 和 validate_production() 移至 core/events.py 的 startup 事件中调用，
# 避免模块导入时的文件系统副作用和生产校验。参见 core/events.py。
