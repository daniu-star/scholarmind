"""
ScholarMind Prometheus 监控指标
暴露 /metrics 端点，提供API延迟分布、请求计数、错误率等可观测性数据。

指标列表：
  - scholarmind_api_requests_total: API请求总数（按method/endpoint/status标签）
  - scholarmind_api_request_duration_seconds: API请求延迟分布（Histogram）
  - scholarmind_active_ws_connections: 活跃WebSocket连接数（Gauge）
  - scholarmind_cnki_search_duration_seconds: CNKI检索延迟分布
  - scholarmind_chart_generation_duration_seconds: 图表生成延迟（按chart_type标签）
  - scholarmind_deepseek_api_errors_total: DeepSeek API错误计数
  - scholarmind_db_pool_connections: 数据库连接池状态（Gauge）
"""
from __future__ import annotations

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
    CONTENT_TYPE_LATEST,
)


# ── API 请求指标 ─────────────────────────────────────────

api_requests_total = Counter(
    "scholarmind_api_requests_total",
    "Total API requests count",
    ["method", "endpoint", "status"],
)

api_request_duration = Histogram(
    "scholarmind_api_request_duration_seconds",
    "API request duration in seconds",
    ["method", "endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# ── 业务指标 ─────────────────────────────────────────────

active_websocket_connections = Gauge(
    "scholarmind_active_ws_connections",
    "Number of active WebSocket connections",
)

cnki_search_total = Counter(
    "scholarmind_cnki_search_total",
    "Total CNKI search requests",
    ["source"],  # "mcp", "direct", "proxy", "crossref", "pubmed"
)

cnki_search_duration = Histogram(
    "scholarmind_cnki_search_duration_seconds",
    "CNKI search duration in seconds",
    ["source"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

chart_generation_total = Counter(
    "scholarmind_chart_generation_total",
    "Total chart generation requests",
    ["chart_type"],
)

chart_generation_duration = Histogram(
    "scholarmind_chart_generation_duration_seconds",
    "Chart generation duration in seconds",
    ["chart_type"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0),
)

deepseek_api_requests_total = Counter(
    "scholarmind_deepseek_api_requests_total",
    "Total DeepSeek API requests",
    ["endpoint"],  # "chat", "stream_chat", "keyword_extract", "chart_analysis"
)

deepseek_api_errors_total = Counter(
    "scholarmind_deepseek_api_errors_total",
    "Total DeepSeek API errors",
    ["error_type"],
)

# ── 数据库指标 ──────────────────────────────────────────

db_pool_size = Gauge(
    "scholarmind_db_pool_size",
    "Database connection pool size",
)

db_pool_checked_in = Gauge(
    "scholarmind_db_pool_checked_in",
    "Database connections checked in",
)

db_pool_overflow = Gauge(
    "scholarmind_db_pool_overflow",
    "Database connection pool overflow",
)

# ── 文件上传指标 ────────────────────────────────────────

files_uploaded_total = Counter(
    "scholarmind_files_uploaded_total",
    "Total files uploaded",
    ["extension"],
)

# ── 会话指标 ────────────────────────────────────────────

active_sessions = Gauge(
    "scholarmind_active_sessions",
    "Number of active conversation sessions",
)

# ── 应用信息 ────────────────────────────────────────────

app_info = Info(
    "scholarmind_app",
    "ScholarMind application info",
)


def record_api_metrics(method: str, endpoint: str, status: int, duration: float) -> None:
    """记录API请求指标（在middleware中调用）"""
    api_requests_total.labels(
        method=method,
        endpoint=_normalize_endpoint(endpoint),
        status=str(status),
    ).inc()
    api_request_duration.labels(
        method=method,
        endpoint=_normalize_endpoint(endpoint),
    ).observe(duration)


def record_deepseek_request(endpoint: str = "chat") -> None:
    """记录DeepSeek API请求"""
    deepseek_api_requests_total.labels(endpoint=endpoint).inc()


def record_deepseek_error(error_type: str = "unknown") -> None:
    """记录DeepSeek API错误"""
    deepseek_api_errors_total.labels(error_type=error_type).inc()


def record_cnki_search(source: str, duration: float) -> None:
    """记录CNKI检索"""
    cnki_search_total.labels(source=source).inc()
    cnki_search_duration.labels(source=source).observe(duration)


def record_chart_generation(chart_type: str, duration: float) -> None:
    """记录图表生成"""
    chart_generation_total.labels(chart_type=chart_type).inc()
    chart_generation_duration.labels(chart_type=chart_type).observe(duration)


def record_file_uploaded(extension: str) -> None:
    """记录文件上传"""
    files_uploaded_total.labels(extension=extension).inc()


def update_db_pool_metrics(size: int, checked_in: int, overflow: int) -> None:
    """更新数据库连接池指标"""
    db_pool_size.set(size)
    db_pool_checked_in.set(checked_in)
    db_pool_overflow.set(overflow)


def set_active_sessions(count: int) -> None:
    """更新活跃会话数"""
    active_sessions.set(count)


def set_app_info(version: str, environment: str = "development") -> None:
    """设置应用信息"""
    app_info.info({"version": version, "environment": environment})


def get_metrics() -> bytes:
    """生成Prometheus格式的指标文本"""
    return generate_latest()


def _normalize_endpoint(endpoint: str) -> str:
    """标准化端点路径（移除动态参数，如 /api/v1/agent/chat → /api/v1/agent/chat）"""
    import re
    # 替换 UUID 和数字路径段
    normalized = re.sub(
        r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
        '/:uuid',
        endpoint,
    )
    normalized = re.sub(r'/\d+(?=/|$)', '/:id', normalized)
    return normalized