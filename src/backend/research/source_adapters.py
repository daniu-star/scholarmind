"""来源适配器（T13 / FR-06）：把外部提供方的元数据解析成统一结构。

设计约束
========
- **不联网**：本模块自身不做任何真实网络 I/O。HTTP 客户端由构造函数注入，
  生产环境注入经配置的可信检索/解析器，测试注入替身；内置 ``DoiAdapter``
  只调用注入的客户端。
- **不补全**：``lookup`` 只回填提供方真实返回的字段，缺失即留空/``None``；
  绝不编造作者、年份、DOI 或引用量（AT-018/AT-019）。
- **不夸大**：只有摘要文本时 ``material_level="abstract"``；有 DOI 不等于
  已读全文，粒度单独记录，供 ``evidence_service`` 拒绝“摘要支持原文观点”。
- **可降级**：注册表为空时 ``adapters_available()`` 为 ``False``，
  调用方退回本库词法检索并标注 degraded。
- **线程/事件循环安全**：注册表用 ``threading.RLock`` 保护，读路径返回
  快照元组，不绑定任何事件循环（同步测试与多线程 worker 均可安全使用）。
"""
from __future__ import annotations

import html
import inspect
import json
import re
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Optional, Protocol, runtime_checkable
from urllib.parse import quote, urlparse

#: ``lookup`` 统一结果结构的字段顺序（evidence_service 按此读取）。
SOURCE_RESULT_FIELDS = (
    "title",
    "authors",
    "year",
    "doi",
    "url",
    "provider",
    "metadata_status",
    "material_level",
    "license",
    "retrieved_at",
    "abstract",
)

DEFAULT_LOOKUP_LIMIT = 10
MAX_LOOKUP_LIMIT = 50

METADATA_STATUS_RESOLVED = "resolved"
METADATA_STATUS_UNRESOLVED = "unresolved"
METADATA_STATUS_USER_SUPPLIED = "user_supplied"
METADATA_STATUSES = frozenset(
    {METADATA_STATUS_RESOLVED, METADATA_STATUS_UNRESOLVED, METADATA_STATUS_USER_SUPPLIED}
)

MATERIAL_LEVEL_METADATA = "metadata"
MATERIAL_LEVEL_ABSTRACT = "abstract"
MATERIAL_LEVEL_FULL_TEXT = "full_text"
MATERIAL_LEVELS = frozenset(
    {MATERIAL_LEVEL_METADATA, MATERIAL_LEVEL_ABSTRACT, MATERIAL_LEVEL_FULL_TEXT}
)

CROSSREF_ENDPOINT = "https://api.crossref.org/works"
CROSSREF_PROVIDER = "crossref"
_REQUEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "ScholarMind/1.0 (source-fidelity resolver)",
}

_DOI_PATTERN = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)
_DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi:",
    "doi ",
)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


class SourceAdapterError(RuntimeError):
    """适配器自身或注入的 HTTP 客户端无法完成解析。"""


@runtime_checkable
class SourceAdapter(Protocol):
    """来源适配器契约（R1_INTERFACE_SPEC §2.4）。"""

    name: str

    async def lookup(self, query: str, *, limit: int = DEFAULT_LOOKUP_LIMIT) -> list[dict]:
        """把用户输入解析为统一结构的来源元数据列表；无结果返回 ``[]``。"""
        ...


# ---------------------------------------------------------------------------
# 规范化
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    text = str(value).replace("\x00", " ")
    return _SPACE_RE.sub(" ", text).strip()[:limit]


def strip_markup(value: Any) -> str:
    """去掉 JATS/HTML 标签与实体，只留可读摘要文本。"""

    if value is None:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", str(value)))
    return _SPACE_RE.sub(" ", text).strip()


def normalize_doi(value: Any) -> Optional[str]:
    """从 DOI / doi.org URL / 前缀写法中提取裸 DOI；不像 DOI 则返回 ``None``。"""

    text = _clean_text(value, 400)
    if not text:
        return None
    lowered = text.lower()
    for prefix in _DOI_PREFIXES:
        if lowered.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    match = _DOI_PATTERN.search(text)
    if match is None:
        return None
    doi = match.group(0).rstrip(".,;:)]}\"'")
    return doi or None


def safe_source_url(value: Any) -> Optional[str]:
    """只保留 http(s) 绝对 URL；其他 scheme（含 ``file:``）一律丢弃。

    这里做的是“适配器输出”的防御性过滤；落库前的完整 SSRF 校验由
    ``evidence_service._validate_source_url`` 负责（私网/回环/链路本地等）。
    """

    text = _clean_text(value, 800)
    if not text:
        return None
    parsed = urlparse(text)
    if (parsed.scheme or "").lower() not in {"http", "https"}:
        return None
    if not (parsed.hostname or "").strip():
        return None
    return text


def _coerce_year(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        year = int(value)
    else:
        text = _clean_text(value, 16)
        if not text.isdigit():
            return None
        year = int(text)
    return year if 1000 <= year <= 2999 else None


def _coerce_authors(value: Any) -> str:
    if isinstance(value, str):
        return _clean_text(value, 400)
    if isinstance(value, dict):
        value = [value]
    if isinstance(value, (list, tuple, set)):
        names: list[str] = []
        for item in value:
            if isinstance(item, dict):
                joined = " ".join(
                    part
                    for part in (item.get("given"), item.get("family"))
                    if part
                )
                name = item.get("name") or joined
            else:
                name = item
            text = _clean_text(name, 200)
            if text:
                names.append(text)
        return _clean_text("; ".join(names), 400)
    return ""


def _coerce_license(value: Any) -> str:
    if isinstance(value, str):
        return _clean_text(value, 200)
    if isinstance(value, dict):
        return _clean_text(
            value.get("URL") or value.get("url") or value.get("name"), 200
        )
    if isinstance(value, (list, tuple)):
        for item in value:
            text = _coerce_license(item)
            if text:
                return text
    return ""


def empty_lookup_result(provider: str = "unknown") -> dict:
    """所有字段留空的统一结构；用于“确实没有解析到元数据”的显式表达。"""

    return {
        "title": "",
        "authors": "",
        "year": None,
        "doi": None,
        "url": None,
        "provider": _clean_text(provider, 64) or "unknown",
        "metadata_status": METADATA_STATUS_UNRESOLVED,
        "material_level": MATERIAL_LEVEL_METADATA,
        "license": "",
        "retrieved_at": _now_iso(),
        "abstract": None,
    }


def normalize_lookup_result(
    raw: Any,
    *,
    provider: Optional[str] = None,
    retrieved_at: Optional[str] = None,
) -> Optional[dict]:
    """把任意提供方结果映射成统一结构；没有标题也没有 DOI 时返回 ``None``。"""

    if not isinstance(raw, dict):
        return None
    title = _clean_text(raw.get("title"), 400)
    doi = normalize_doi(raw.get("doi"))
    abstract = _clean_text(strip_markup(raw.get("abstract")), 20000)
    if not title and not doi:
        return None

    status = _clean_text(raw.get("metadata_status"), 24).lower()
    if status not in METADATA_STATUSES:
        status = METADATA_STATUS_RESOLVED if title else METADATA_STATUS_UNRESOLVED
    level = _clean_text(raw.get("material_level"), 24).lower()
    if level not in MATERIAL_LEVELS:
        level = MATERIAL_LEVEL_ABSTRACT if abstract else MATERIAL_LEVEL_METADATA
    elif abstract and level == MATERIAL_LEVEL_METADATA:
        level = MATERIAL_LEVEL_ABSTRACT

    return {
        "title": title,
        "authors": _coerce_authors(raw.get("authors")),
        "year": _coerce_year(raw.get("year")),
        "doi": doi,
        "url": safe_source_url(raw.get("url")),
        "provider": _clean_text(raw.get("provider") or provider, 64) or "unknown",
        "metadata_status": status,
        "material_level": level,
        "license": _coerce_license(raw.get("license")),
        "retrieved_at": _clean_text(retrieved_at or raw.get("retrieved_at"), 64)
        or _now_iso(),
        "abstract": abstract or None,
    }


# ---------------------------------------------------------------------------
# 注册表（模块级，线程/事件循环安全）
# ---------------------------------------------------------------------------
_ADAPTERS: list[SourceAdapter] = []
_REGISTRY_LOCK = RLock()


def register_adapter(adapter: SourceAdapter) -> None:
    """注册适配器；同名则原位替换，保持注册顺序（先注册先尝试）。"""

    if not isinstance(adapter, SourceAdapter):
        raise TypeError("adapter 必须实现 name 与 async lookup(query, *, limit)。")
    name = _clean_text(getattr(adapter, "name", ""), 64)
    if not name:
        raise TypeError("adapter.name 不能为空。")
    with _REGISTRY_LOCK:
        for index, existing in enumerate(_ADAPTERS):
            if existing.name == name:
                _ADAPTERS[index] = adapter
                return
        _ADAPTERS.append(adapter)


def reset_adapters() -> None:
    """清空注册表（测试隔离用）；清空后 ``adapters_available()`` 为 ``False``。"""

    with _REGISTRY_LOCK:
        _ADAPTERS.clear()


def list_adapters() -> tuple[SourceAdapter, ...]:
    """返回注册表快照，调用方遍历时不受并发注册影响。"""

    with _REGISTRY_LOCK:
        return tuple(_ADAPTERS)


def adapter_names() -> tuple[str, ...]:
    return tuple(adapter.name for adapter in list_adapters())


def adapters_available() -> bool:
    return bool(list_adapters())


# ---------------------------------------------------------------------------
# 注入的 HTTP 客户端
# ---------------------------------------------------------------------------
async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _response_payload(response: Any) -> Any:
    if isinstance(response, dict):
        return response
    if isinstance(response, (bytes, bytearray)):
        return json.loads(response.decode("utf-8"))
    if isinstance(response, str):
        return json.loads(response)
    json_method = getattr(response, "json", None)
    if callable(json_method):
        return await _maybe_await(json_method())
    raise SourceAdapterError("注入的 HTTP 客户端返回了不可解析的响应。")


async def _request_json(client: Any, url: str, *, headers: dict) -> Any:
    """调用注入客户端，兼容 ``get_json`` / ``get`` / ``fetch`` 三种常见替身形态。"""

    get_json = getattr(client, "get_json", None)
    if callable(get_json):
        return await _response_payload(await _maybe_await(get_json(url)))
    get = getattr(client, "get", None)
    if callable(get):
        try:
            response = await _maybe_await(get(url, headers=headers))
        except TypeError:
            response = await _maybe_await(get(url))
        return await _response_payload(response)
    fetch = getattr(client, "fetch", None)
    if callable(fetch):
        # fetch 形态的替身可能直接返回 bytes/str 正文（未解码），统一走同一条
        # 解析路径，避免 "配置了 fetch 客户端却静默返回空结果"。
        return await _response_payload(await _maybe_await(fetch(url)))
    raise SourceAdapterError("注入的 HTTP 客户端缺少 get_json/get/fetch 方法。")


# ---------------------------------------------------------------------------
# Crossref 风格响应 → 统一结构
# ---------------------------------------------------------------------------
def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return _clean_text(value, 400)
    if isinstance(value, (list, tuple)):
        for item in value:
            text = _first_text(item)
            if text:
                return text
    if isinstance(value, dict):
        return _first_text(value.get("value") or value.get("name"))
    return ""


def _crossref_authors(message: dict) -> str:
    people = message.get("author")
    if not isinstance(people, (list, tuple)):
        return ""
    names: list[str] = []
    for person in people:
        if isinstance(person, dict):
            joined = " ".join(
                part
                for part in (person.get("given"), person.get("family"))
                if isinstance(part, str) and part.strip()
            )
            name = person.get("name") or joined
        else:
            name = person
        text = _clean_text(name, 200)
        if text:
            names.append(text)
    return _clean_text("; ".join(names), 400)


def _crossref_year(message: dict) -> Optional[int]:
    for key in (
        "issued",
        "published-print",
        "published-online",
        "published",
        "created",
        "deposited",
    ):
        block = message.get(key)
        if not isinstance(block, dict):
            continue
        parts = block.get("date-parts")
        if not isinstance(parts, (list, tuple)) or not parts:
            continue
        first = parts[0]
        if not isinstance(first, (list, tuple)) or not first:
            continue
        year = _coerce_year(first[0])
        if year is not None:
            return year
    return None


def map_crossref_message(
    payload: Any,
    *,
    doi: Optional[str] = None,
    provider: str = CROSSREF_PROVIDER,
    retrieved_at: Optional[str] = None,
) -> Optional[dict]:
    """把 Crossref ``works`` 响应（或等价替身）映射成统一结构。

    只使用响应中真实存在的字段：``title`` 缺失时返回 ``None``（未解析到），
    不会用期刊名/容器名冒充标题，也不会补造作者或年份。
    """

    if not isinstance(payload, dict):
        return None
    if str(payload.get("status") or "").strip().lower() in {"failed", "error"}:
        # Crossref 的失败响应形如 {"status": "failed", "message": "..."}，
        # 不能当成元数据；否则会把用户输入的 DOI 回显成“已解析”。
        return None
    message = payload.get("message", payload)
    if not isinstance(message, dict):
        return None
    title = _first_text(message.get("title"))
    provider_doi = normalize_doi(message.get("DOI"))
    if not title and not provider_doi:
        return None
    # 允许用请求的 DOI 兜底，但仅在提供方确实返回了标题时，避免“DOI 回显 =
    # 已解析”的假阳性。
    doi_value = provider_doi or (normalize_doi(doi) if title else None)
    abstract = strip_markup(message.get("abstract"))
    raw = {
        "title": title,
        "authors": message.get("author"),
        "year": _crossref_year(message),
        "doi": doi_value,
        "url": _first_text(message.get("URL"))
        or (f"https://doi.org/{doi_value}" if doi_value else None),
        "provider": provider,
        "metadata_status": METADATA_STATUS_RESOLVED,
        "material_level": (
            MATERIAL_LEVEL_ABSTRACT if abstract else MATERIAL_LEVEL_METADATA
        ),
        "license": message.get("license"),
        "retrieved_at": retrieved_at,
        "abstract": abstract,
    }
    return normalize_lookup_result(raw, provider=provider, retrieved_at=retrieved_at)


class DoiAdapter:
    """通过注入的 HTTP 客户端解析 DOI 元数据（Crossref 风格 JSON）。

    构造函数参数 ``http_client`` 是**替身友好**的：只要它提供 ``get_json(url)``、
    ``get(url)``（返回 dict 或带 ``json()`` 的响应）或 ``fetch(url)`` 之一即可。
    同名的旧特性：``name="doi"``，注册顺序决定解析优先级。
    """

    name = "doi"
    provider = CROSSREF_PROVIDER

    def __init__(
        self,
        http_client: Any,
        *,
        endpoint: str = CROSSREF_ENDPOINT,
        provider: str = CROSSREF_PROVIDER,
    ) -> None:
        if http_client is None:
            raise ValueError("DoiAdapter 需要注入 HTTP 客户端（离线测试请传替身）。")
        self._client = http_client
        self._endpoint = (endpoint or CROSSREF_ENDPOINT).rstrip("/")
        self.provider = provider

    async def lookup(
        self, query: str, *, limit: int = DEFAULT_LOOKUP_LIMIT
    ) -> list[dict]:
        if limit <= 0:
            return []
        doi = normalize_doi(query)
        if doi is None:
            return []
        url = f"{self._endpoint}/{quote(doi, safe='/')}"
        payload = await _request_json(self._client, url, headers=_REQUEST_HEADERS)
        result = map_crossref_message(
            payload, doi=doi, provider=self.provider
        )
        return [result] if result is not None else []


__all__ = [
    "CROSSREF_ENDPOINT",
    "CROSSREF_PROVIDER",
    "DEFAULT_LOOKUP_LIMIT",
    "DoiAdapter",
    "MATERIAL_LEVELS",
    "MATERIAL_LEVEL_ABSTRACT",
    "MATERIAL_LEVEL_FULL_TEXT",
    "MATERIAL_LEVEL_METADATA",
    "MAX_LOOKUP_LIMIT",
    "METADATA_STATUSES",
    "METADATA_STATUS_RESOLVED",
    "METADATA_STATUS_UNRESOLVED",
    "METADATA_STATUS_USER_SUPPLIED",
    "SOURCE_RESULT_FIELDS",
    "SourceAdapter",
    "SourceAdapterError",
    "adapter_names",
    "adapters_available",
    "empty_lookup_result",
    "list_adapters",
    "map_crossref_message",
    "normalize_doi",
    "normalize_lookup_result",
    "register_adapter",
    "reset_adapters",
    "safe_source_url",
    "strip_markup",
]
