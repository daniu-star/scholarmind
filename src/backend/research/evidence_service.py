"""来源记录与证据（FR-06；T03/T06/T13）。

诚实性约束
==========
- ``validate_evidence`` 强制四字段（``metadata_status`` / ``material_level`` /
  ``support_status`` / ``verification_method``）存在且为合法枚举值，否则 422
  ``EVIDENCE_INCOMPLETE``——不允许用默认值掩盖“未核验”。
- 来源只记录**真实**提供方给出的元数据，不补全、不推断作者/DOI/年份；DOI 存在
  不代表已读全文，材料粒度单独记录在 ``material_level``。
- 解析顺序：显式 ``provider`` 参数 > 已注册 ``SourceAdapter`` > 本库词法匹配
  降级。任何一步失败都只把来源标为 ``metadata_status="unresolved"``，并把
  用户原文（DOI/查询串/引用）逐字放进 ``unresolved``，绝不替换用户文本。
- 只有摘要（``material_level="abstract"``）或元数据（``"metadata"``）的来源，
  不允许支持“原文观点”：``create_evidence`` 会拒绝 ``support_status="supported"``，
  也拒绝比来源更强的材料粒度（AT-020）。
- 无适配器时 ``search_sources`` 只返回本库已保存的来源，并在每条结果与
  ``external_source_status()`` 上标注 degraded；无匹配即返回 ``[]``，绝不伪造。
- 来源 URL 只允许安全 HTTP(S)，阻断本机/私网/链路本地/云元数据地址与 ``file:``
  等危险 scheme，并拦截十进制/十六进制/八进制等变形 IP 与带凭据 URL（AT-049）。
- 所有读取走 ``ownership.require_*``，来源必须属于当前 actor。
"""
from __future__ import annotations

import ipaddress
from typing import Any, Optional
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import (
    Actor,
    MaterialLevel,
    MetadataStatus,
    SupportStatus,
    VerificationMethod,
    new_id,
    normalize_text,
    utcnow,
)
from .errors import ResearchAPIError, invalid, not_found
from .models import Evidence, SourceRecord
from .ownership import require_project, require_task
from .source_adapters import (
    DEFAULT_LOOKUP_LIMIT,
    SourceAdapter,
    adapter_names,
    adapters_available,
    list_adapters,
    normalize_doi,
    normalize_lookup_result,
)

EXTERNAL_SOURCE_UNAVAILABLE = "external_source_unavailable"

METADATA_STATUSES = {item.value for item in MetadataStatus}
MATERIAL_LEVELS = {item.value for item in MaterialLevel}
SUPPORT_STATUSES = {item.value for item in SupportStatus}
VERIFICATION_METHODS = {item.value for item in VerificationMethod}

EVIDENCE_FIELDS = (
    "metadata_status",
    "material_level",
    "support_status",
    "verification_method",
)
_FIELD_ALLOWED = {
    "metadata_status": METADATA_STATUSES,
    "material_level": MATERIAL_LEVELS,
    "support_status": SUPPORT_STATUSES,
    "verification_method": VERIFICATION_METHODS,
}

#: 材料粒度强弱：证据不得声称比来源更强的粒度。
_MATERIAL_RANK = {
    MaterialLevel.METADATA.value: 0,
    MaterialLevel.ABSTRACT.value: 1,
    MaterialLevel.FULL_TEXT.value: 2,
}

_ALLOWED_URL_SCHEMES = {"http", "https"}
_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "metadata",
    "metadata.google.internal",
    "metadata.goog",
    "instance-data",
}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")
_SOURCE_SEARCH_LIMIT = 50
_MAX_CITATIONS = 50


def _iso(value) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _as_text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    return normalize_text(str(value)).strip()[:limit]


def external_source_status() -> dict:
    """供路由/能力接口展示：有适配器即在线解析，否则降级为本库检索。"""

    names = list(adapter_names())
    available = bool(names)
    return {
        "degraded": not available,
        "reason": None if available else EXTERNAL_SOURCE_UNAVAILABLE,
        "detail": (
            "已注册来源适配器：" + "、".join(names) + "；仅解析元数据，不承诺全文。"
            if available
            else "未注册外部文献解析适配器，仅检索本库已保存来源。"
        ),
        "providers": names,
        "available": available,
    }


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------
def _enum_value(payload: dict, field: str) -> str:
    raw = payload.get(field)
    value = str(raw).strip().lower() if raw is not None else ""
    if not value:
        raise invalid(
            "EVIDENCE_INCOMPLETE",
            "证据四字段不完整，缺少必填校验字段。",
            {"missing": [field], "required": list(EVIDENCE_FIELDS)},
        )
    allowed = _FIELD_ALLOWED[field]
    if value not in allowed:
        raise invalid(
            "EVIDENCE_INCOMPLETE",
            "证据字段取值非法，必须使用约定的枚举值。",
            {
                "invalid": [field],
                "value": value,
                "allowed": sorted(allowed),
                "required": list(EVIDENCE_FIELDS),
            },
        )
    return value


def validate_evidence(payload: Any) -> None:
    """四字段必须齐全且合法，否则 422 ``EVIDENCE_INCOMPLETE``。"""

    if not isinstance(payload, dict):
        raise invalid(
            "EVIDENCE_INCOMPLETE",
            "证据载荷必须是对象且包含四个校验字段。",
            {"missing": list(EVIDENCE_FIELDS), "required": list(EVIDENCE_FIELDS)},
        )
    missing = [field for field in EVIDENCE_FIELDS if payload.get(field) in (None, "")]
    if missing:
        raise invalid(
            "EVIDENCE_INCOMPLETE",
            "证据四字段不完整，缺少必填校验字段。",
            {"missing": missing, "required": list(EVIDENCE_FIELDS)},
        )
    for field in EVIDENCE_FIELDS:
        _enum_value(payload, field)


def _clean_str(payload: dict, field: str, *, limit: int) -> Optional[str]:
    raw = payload.get(field)
    if raw is None:
        return None
    value = normalize_text(str(raw)).strip()
    if not value:
        return None
    return value[:limit]


def _payload_year(payload: dict) -> Optional[int]:
    raw = payload.get("year")
    if raw in (None, ""):
        return None
    try:
        year = int(str(raw).strip())
    except (TypeError, ValueError):
        raise invalid("INVALID_SOURCE", "年份必须是整数。", {"field": "year"})
    if not 1000 <= year <= 2999:
        raise invalid(
            "INVALID_SOURCE",
            "年份超出合理范围。",
            {"field": "year", "value": year},
        )
    return year


def _loose_ipv4_literal(hostname: str) -> Optional[ipaddress.IPv4Address]:
    """识别 ``2130706433`` / ``0x7f.0.0.1`` / ``0177.0.0.1`` / ``127.1`` 等变形。

    ``urlparse`` 不会把这些写法当 IP，但 HTTP 客户端/解析器会按 inet_aton 语义
    展开成回环或私网地址，因此必须在落库前按同一语义还原后再判定。
    """

    parts = hostname.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    numbers: list[int] = []
    for part in parts:
        if not part:
            return None
        lowered = part.lower()
        if lowered.startswith("0x"):
            digits = lowered[2:]
            if not digits or any(char not in "0123456789abcdef" for char in digits):
                return None
            numbers.append(int(digits, 16))
        elif len(part) > 1 and part.startswith("0"):
            if any(char not in "01234567" for char in part):
                return None
            numbers.append(int(part, 8))
        elif part.isdigit():
            numbers.append(int(part, 10))
        else:
            return None
    if any(number < 0 for number in numbers):
        return None
    if len(numbers) == 1:
        value = numbers[0]
    else:
        head, last = numbers[:-1], numbers[-1]
        if any(number > 255 for number in head):
            return None
        remaining = 5 - len(numbers)
        if last >= 256**remaining:
            return None
        value = 0
        for number in head:
            value = value * 256 + number
        value = value * (256**remaining) + last
    if 0 <= value <= 0xFFFFFFFF:
        return ipaddress.IPv4Address(value)
    return None


def _parse_host_address(hostname: str) -> Optional[ipaddress._BaseAddress]:
    try:
        return ipaddress.ip_address(hostname)
    except ValueError:
        return _loose_ipv4_literal(hostname)


def _validate_source_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_URL_SCHEMES:
        raise invalid(
            "UNSAFE_SOURCE_URL",
            "来源 URL 只允许 http/https。",
            {"scheme": scheme or None},
        )
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        raise invalid("UNSAFE_SOURCE_URL", "来源 URL 缺少主机名。", {"url": url})
    if parsed.username or parsed.password:
        raise invalid(
            "UNSAFE_SOURCE_URL",
            "来源 URL 不得包含凭据信息。",
            {"host": hostname},
        )
    if "%" in hostname:
        raise invalid(
            "UNSAFE_SOURCE_URL",
            "来源 URL 主机名含区域标识或编码字符，已阻断。",
            {"host": hostname},
        )
    if hostname in _BLOCKED_HOSTNAMES or hostname.endswith(_BLOCKED_SUFFIXES):
        raise invalid(
            "UNSAFE_SOURCE_URL",
            "来源 URL 指向本机或内部网络，已阻断。",
            {"host": hostname},
        )
    address = _parse_host_address(hostname)
    if address is None:
        return url
    blocked = (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        blocked = blocked or address.ipv4_mapped.is_private
    if blocked:
        raise invalid(
            "UNSAFE_SOURCE_URL",
            "来源 URL 指向本机或内部网络，已阻断。",
            {"host": hostname},
        )
    return url


def _source_payload(source: SourceRecord, *, degraded: Optional[bool] = None) -> dict:
    if degraded is None:
        degraded = not adapters_available()
    payload = {
        "id": source.id,
        "project_id": source.project_id,
        "title": source.title,
        "authors": source.authors,
        "year": source.year,
        "doi": source.doi,
        "url": source.url,
        "provider": source.provider,
        "metadata_status": source.metadata_status,
        "material_level": source.material_level,
        "license": source.license,
        "retrieved_at": _iso(source.retrieved_at),
        "degraded": degraded,
        "degraded_reason": EXTERNAL_SOURCE_UNAVAILABLE if degraded else None,
    }
    return payload


# ---------------------------------------------------------------------------
# 适配器解析
# ---------------------------------------------------------------------------
def _resolve_provider_argument(
    provider: Any,
) -> tuple[Optional[SourceAdapter], Optional[str]]:
    """把 ``provider`` 参数归一为（显式适配器, 显式提供方名称）。"""

    if provider is None:
        return None, None
    if isinstance(provider, str):
        name = _as_text(provider, 64)
        return None, name or None
    if isinstance(provider, SourceAdapter) or callable(
        getattr(provider, "lookup", None)
    ):
        name = _as_text(getattr(provider, "name", ""), 64) or None
        return provider, name
    raise invalid(
        "INVALID_PROVIDER",
        "provider 必须是来源适配器实例或提供方名称。",
        {"type": type(provider).__name__},
    )


async def _lookup_with_adapters(
    query: str,
    *,
    limit: int = DEFAULT_LOOKUP_LIMIT,
    adapters: Optional[list] = None,
) -> tuple[Optional[dict], list[str], Optional[str]]:
    """按注册顺序尝试适配器；返回（首个结果, 尝试过的名字, 最后一个错误）。"""

    candidates = list(adapters) if adapters else list(list_adapters())
    attempted: list[str] = []
    error: Optional[str] = None
    for adapter in candidates:
        name = _as_text(getattr(adapter, "name", ""), 64) or type(adapter).__name__
        attempted.append(name)
        try:
            raw_results = await adapter.lookup(query, limit=limit)
        except Exception as exc:  # 适配器失败不得让来源创建 500，只降级为未解析
            error = f"{type(exc).__name__}: {exc}"[:300]
            continue
        for raw in list(raw_results or [])[:limit]:
            normalized = normalize_lookup_result(raw, provider=name)
            if normalized is not None:
                return normalized, attempted, None
    return None, attempted, error


async def _find_existing_source(
    db: AsyncSession,
    actor: Actor,
    project_id: str,
    *,
    doi: Optional[str],
    query: Optional[str],
) -> Optional[SourceRecord]:
    """本库词法降级：同 DOI 或标题/DOI 命中已有来源时复用，不重复新增。"""

    base = select(SourceRecord).where(
        SourceRecord.project_id == project_id,
        SourceRecord.owner_id == actor.user_id,
    )
    if doi:
        result = await db.execute(
            base.where(func.lower(SourceRecord.doi) == doi.lower()).limit(1)
        )
        found = result.scalars().first()
        if found is not None:
            return found
    if query and len(query) >= 4:
        pattern = _like_pattern(query)
        result = await db.execute(
            base.where(
                SourceRecord.title.ilike(pattern, escape="\\")
                | SourceRecord.doi.ilike(pattern, escape="\\")
            )
            .order_by(SourceRecord.retrieved_at.desc(), SourceRecord.id.asc())
            .limit(1)
        )
        return result.scalars().first()
    return None


def _citation_entries(citations: Any) -> list[tuple[str, str]]:
    """把引用列表归一为（用户原文, 检索串）；用户原文永远是逐字原文。"""

    if citations is None:
        return []
    items = list(citations) if isinstance(citations, (list, tuple)) else [citations]
    entries: list[tuple[str, str]] = []
    for item in items[:_MAX_CITATIONS]:
        doi = ""
        if isinstance(item, dict):
            raw_text = _as_text(
                item.get("raw")
                or item.get("text")
                or item.get("citation")
                or item.get("title"),
                500,
            )
            doi = _as_text(item.get("doi"), 200)
        else:
            raw_text = _as_text(item, 500)
        query = doi or raw_text
        if raw_text or query:
            entries.append((raw_text or query, query))
    return entries


async def resolve_citations(
    citations: Any, *, limit: int = DEFAULT_LOOKUP_LIMIT
) -> dict:
    """逐一解析用户已有引用；查不到的原文进 ``unresolved``，绝不替换用户文本。

    返回 ``{"citations": [...], "unresolved": [...], "attempted": [...],
    "degraded": bool}``；``citations`` 里每条都保留 ``raw`` 原文，解析成功的
    另带规范化 ``source``（元数据，未落库）。
    """

    entries = _citation_entries(citations)
    resolved: list[dict] = []
    unresolved: list[str] = []
    attempted: list[str] = []
    for raw_text, query in entries:
        result, tried, error = await _lookup_with_adapters(query, limit=limit)
        for name in tried:
            if name not in attempted:
                attempted.append(name)
        if result is None:
            unresolved.append(raw_text)
            resolved.append(
                {
                    "raw": raw_text,
                    "resolved": False,
                    "metadata_status": MetadataStatus.UNRESOLVED.value,
                    "reason": EXTERNAL_SOURCE_UNAVAILABLE,
                    "error": error,
                }
            )
        else:
            resolved.append(
                {
                    "raw": raw_text,
                    "resolved": True,
                    "metadata_status": result.get("metadata_status"),
                    "source": result,
                }
            )
    return {
        "citations": resolved,
        "unresolved": unresolved,
        "attempted": attempted,
        "degraded": not adapters_available(),
    }


# ---------------------------------------------------------------------------
# 来源
# ---------------------------------------------------------------------------
async def create_source(
    db: AsyncSession,
    actor: Actor,
    project_id: str,
    payload: dict,
    *,
    provider: Any = None,
) -> dict:
    """保存来源元数据。

    解析顺序：显式 ``provider`` 参数（适配器实例/提供方名称）> 已注册适配器 >
    本库词法匹配降级。适配器只补充用户没给的字段，**不覆盖用户原文**；解析失败
    时来源标为 ``unresolved`` 且不写作者/年份/DOI。
    """

    project = await require_project(db, actor, project_id)
    if not isinstance(payload, dict):
        raise invalid("INVALID_SOURCE", "来源载荷必须是对象。")

    explicit_adapter, provider_label = _resolve_provider_argument(provider)
    payload_provider = _clean_str(payload, "provider", limit=64)
    if payload_provider and provider_label is None:
        provider_label = payload_provider
    # 显式提供方（名称）意味着调用方已知道来源平台，不再走适配器。
    use_adapters = explicit_adapter is not None or not provider_label

    # 先做 URL 安全校验：任何外部解析调用之前就拒绝私网/回环/file: 等恶意来源。
    url = _clean_str(payload, "url", limit=800)
    if url is not None:
        url = _validate_source_url(url)

    # 只对 DOI / 显式查询串（以及 doi.org 形式的 URL）做外部解析；纯标题或普通
    # URL 属于用户自述来源，不猜测、不抓取。
    query = _clean_str(payload, "doi", limit=800) or _clean_str(
        payload, "query", limit=800
    )
    if not query and url and "doi.org/" in url.lower():
        query = url
    adapter_result: Optional[dict] = None
    attempted: list[str] = []
    lookup_error: Optional[str] = None
    if query and use_adapters:
        adapter_result, attempted, lookup_error = await _lookup_with_adapters(
            query,
            adapters=[explicit_adapter] if explicit_adapter is not None else None,
        )
    adapter_data = adapter_result or {}

    title = _clean_str(payload, "title", limit=400) or _as_text(
        adapter_data.get("title"), 400
    )
    identifier = (
        _clean_str(payload, "doi", limit=200)
        or _clean_str(payload, "query", limit=200)
        or _clean_str(payload, "url", limit=800)
    )
    if not title:
        # 未解析到标题时保留用户给出的标识符作为标题，不编造标题。
        title = identifier
    if not title:
        raise invalid(
            "INVALID_SOURCE",
            "来源标题不能为空。",
            {"field": "title"},
        )

    authors = _clean_str(payload, "authors", limit=400)
    if authors is None:
        authors = _as_text(adapter_data.get("authors"), 400)
    authors = authors or ""

    raw_doi = _clean_str(payload, "doi", limit=200)
    if raw_doi is None and adapter_data.get("doi"):
        raw_doi = _as_text(adapter_data.get("doi"), 200) or None
    # 存裸 DOI；认不出是 DOI 时保留用户原文，不丢字段也不伪造。
    doi = (normalize_doi(raw_doi) or raw_doi) if raw_doi else None

    if url is None:
        adapter_url = _as_text(adapter_data.get("url"), 800)
        if adapter_url:
            try:
                url = _validate_source_url(adapter_url)
            except ResearchAPIError:
                # 适配器回填了不安全 URL：丢弃该字段，不因此拒绝用户请求。
                url = None

    provider_name = (
        provider_label
        or _as_text(adapter_data.get("provider"), 64)
        or (explicit_adapter.name if explicit_adapter is not None else "")
        or "manual"
    )

    metadata_status = _clean_str(payload, "metadata_status", limit=24)
    if metadata_status is None:
        metadata_status = (
            _as_text(adapter_data.get("metadata_status"), 24)
            or MetadataStatus.UNRESOLVED.value
        )
    if metadata_status not in METADATA_STATUSES:
        raise invalid(
            "INVALID_SOURCE",
            "来源的 metadata_status 取值非法。",
            {"field": "metadata_status", "allowed": sorted(METADATA_STATUSES)},
        )
    material_level = _clean_str(payload, "material_level", limit=24)
    if material_level is None:
        material_level = (
            _as_text(adapter_data.get("material_level"), 24)
            or MaterialLevel.METADATA.value
        )
    if material_level not in MATERIAL_LEVELS:
        raise invalid(
            "INVALID_SOURCE",
            "来源的 material_level 取值非法。",
            {"field": "material_level", "allowed": sorted(MATERIAL_LEVELS)},
        )

    year = _payload_year(payload)
    if year is None:
        adapter_year = adapter_data.get("year")
        year = adapter_year if isinstance(adapter_year, int) else None

    license_name = _clean_str(payload, "license", limit=200) or _as_text(
        adapter_data.get("license"), 200
    )
    abstract = _as_text(adapter_data.get("abstract"), 20000) or None

    fallback_used = bool(query and adapter_result is None and (attempted or adapters_available()))
    resolution = {
        "provider": provider_name,
        "resolved": metadata_status == MetadataStatus.RESOLVED.value,
        "adapter": attempted[0] if attempted else None,
        "attempted": attempted,
        "fallback": "db_lexical" if fallback_used else None,
        "error": lookup_error,
    }

    unresolved: list[str] = []
    if attempted and adapter_result is None and query:
        unresolved.append(query)

    existing = await _find_existing_source(
        db, actor, project.id, doi=doi, query=query
    )
    if existing is not None:
        result = _source_payload(existing)
        result["deduplicated"] = True
        result["resolution"] = resolution
        if unresolved:
            result["unresolved"] = unresolved
        return result

    now = utcnow()
    source = SourceRecord(
        id=new_id("rsrc"),
        owner_id=actor.user_id,
        project_id=project.id,
        title=title,
        authors=authors,
        year=year,
        doi=doi,
        url=url,
        provider=provider_name,
        metadata_status=metadata_status,
        material_level=material_level,
        license=license_name,
        retrieved_at=now,
    )
    db.add(source)
    await db.flush()

    result = _source_payload(source)
    result["resolution"] = resolution
    if abstract:
        # 摘要不落库（R0 表结构无该列），只在本次响应中作为元数据回显。
        result["abstract"] = abstract
        result["abstract_available"] = True

    citations = payload.get("citations")
    if citations is not None:
        citation_report = await resolve_citations(citations)
        result["citations"] = citation_report
        unresolved.extend(citation_report["unresolved"])
    if unresolved:
        result["unresolved"] = unresolved
    return result


def _like_pattern(query: str) -> str:
    escaped = (
        query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return f"%{escaped}%"


async def search_sources(
    db: AsyncSession, actor: Actor, project_id: str, query: str
) -> list[dict]:
    """项目内检索本库已保存来源；无匹配返回 ``[]``，不伪造结果。"""

    project = await require_project(db, actor, project_id)
    text = normalize_text(str(query or "")).strip()
    if not text:
        return []
    pattern = _like_pattern(text)
    result = await db.execute(
        select(SourceRecord)
        .where(
            SourceRecord.project_id == project.id,
            SourceRecord.owner_id == actor.user_id,
            SourceRecord.title.ilike(pattern, escape="\\")
            | SourceRecord.authors.ilike(pattern, escape="\\")
            | SourceRecord.doi.ilike(pattern, escape="\\"),
        )
        .order_by(SourceRecord.retrieved_at.desc(), SourceRecord.id.asc())
        .limit(_SOURCE_SEARCH_LIMIT)
    )
    return [_source_payload(source) for source in result.scalars().all()]


# ---------------------------------------------------------------------------
# 证据
# ---------------------------------------------------------------------------
async def create_evidence(
    db: AsyncSession, actor: Actor, task_id: str, payload: dict
) -> dict:
    task = await require_task(db, actor, task_id)
    if not isinstance(payload, dict):
        raise invalid(
            "EVIDENCE_INCOMPLETE",
            "证据载荷必须是对象且包含四个校验字段。",
            {"missing": list(EVIDENCE_FIELDS), "required": list(EVIDENCE_FIELDS)},
        )

    source_id = _clean_str(payload, "source_id", limit=64)
    if not source_id:
        raise invalid(
            "EVIDENCE_INCOMPLETE",
            "证据必须指向一条已保存来源。",
            {"missing": ["source_id"]},
        )
    source = await db.get(SourceRecord, source_id)
    if source is None or source.owner_id != actor.user_id:
        raise not_found("来源")

    quote = _clean_str(payload, "quote", limit=8000)
    if not quote:
        raise invalid(
            "EVIDENCE_INCOMPLETE",
            "证据必须包含可核对的原文引用（quote）。",
            {"missing": ["quote"]},
        )

    # 四字段先校验，再做任何写入
    validate_evidence(payload)
    declared_material = _enum_value(payload, "material_level")
    declared_support = _enum_value(payload, "support_status")
    verification_method = _enum_value(payload, "verification_method")

    source_rank = _MATERIAL_RANK.get(str(source.material_level or ""), 0)
    declared_rank = _MATERIAL_RANK[declared_material]
    if declared_rank > source_rank:
        raise invalid(
            "EVIDENCE_MATERIAL_CONFLICT",
            "证据声明的材料粒度强于来源已核实的粒度，不能把摘要当作全文。",
            {
                "source_material_level": source.material_level,
                "material_level": declared_material,
                "allowed": sorted(
                    level
                    for level, rank in _MATERIAL_RANK.items()
                    if rank <= source_rank
                ),
            },
        )
    if (
        declared_support == SupportStatus.SUPPORTED.value
        and declared_rank < _MATERIAL_RANK[MaterialLevel.FULL_TEXT.value]
    ):
        raise invalid(
            "EVIDENCE_UNSUPPORTED_MATERIAL",
            "仅有元数据或摘要不足以支持原文观点；请改记为 insufficient/unassessed，或先获取全文。",
            {
                "source_material_level": source.material_level,
                "support_status": declared_support,
                "suggestion": [
                    SupportStatus.INSUFFICIENT.value,
                    SupportStatus.UNASSESSED.value,
                ],
            },
        )
    if (
        declared_support == SupportStatus.SUPPORTED.value
        and verification_method == VerificationMethod.NONE.value
    ):
        raise invalid(
            "EVIDENCE_UNVERIFIED",
            "support_status=supported 必须给出验证方式（tool/model/human），不能是 none。",
            {
                "support_status": declared_support,
                "verification_method": verification_method,
            },
        )

    locator = payload.get("locator")
    if locator is None:
        locator = {}
    if not isinstance(locator, dict):
        raise invalid(
            "EVIDENCE_INCOMPLETE",
            "定位信息 locator 必须是对象。",
            {"field": "locator"},
        )

    evidence = Evidence(
        id=new_id("revd"),
        task_id=task.id,
        owner_id=actor.user_id,
        source_id=source.id,
        locator=locator,
        quote=quote,
        metadata_status=_enum_value(payload, "metadata_status"),
        material_level=declared_material,
        support_status=declared_support,
        verification_method=verification_method,
        created_at=utcnow(),
    )
    db.add(evidence)
    await db.flush()

    return {
        "id": evidence.id,
        "task_id": evidence.task_id,
        "owner_id": evidence.owner_id,
        "source_id": evidence.source_id,
        "locator": evidence.locator,
        "quote": evidence.quote,
        "metadata_status": evidence.metadata_status,
        "material_level": evidence.material_level,
        "support_status": evidence.support_status,
        "verification_method": evidence.verification_method,
        "created_at": _iso(evidence.created_at),
    }


__all__ = [
    "EVIDENCE_FIELDS",
    "EXTERNAL_SOURCE_UNAVAILABLE",
    "METADATA_STATUSES",
    "MATERIAL_LEVELS",
    "SUPPORT_STATUSES",
    "VERIFICATION_METHODS",
    "create_evidence",
    "create_source",
    "external_source_status",
    "resolve_citations",
    "search_sources",
    "validate_evidence",
]
