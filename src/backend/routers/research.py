"""研究模块统一 REST / SSE 路由（PRD v1.0 FR-02 / T02 / §8）。

设计要点
--------
- 前缀：``APIRouter(prefix="/research")``。``app.py`` 已用
  ``include_router(research_router.router, prefix="/api/v1")`` 装配，因此最终
  URL 为 ``/api/v1/research/*``，与 ``R0_INTERFACE_SPEC.md`` §4 一致。
- 鉴权：除 SSE 用短会话授权外，所有端点都 ``Depends(require_research_user)``，
  再把 ``int user id`` 包装成 ``Actor``；请求体中的 owner/user 字段不产生授权。
- 错误：领域错误统一 ``ResearchAPIError`` → ``{"error": {code, message,
  details, retryable, request_id}}``。路由级 ``_ResearchAPIRoute`` 把
  ``RequestValidationError`` 转成 422 ``VALIDATION_ERROR``，把权益错误转成 402，
  避免出现 FastAPI 默认的 ``{"detail": ...}`` 结构。
- 真实失败：依赖模块未落地时返回 503 ``DEPENDENCY_NOT_READY``，绝不以假成功
  或空 200 掩盖。
- 分页：``cursor`` + ``limit``（默认 20，最大 100）；游标是服务端生成的不透明
  偏移量，非法游标 422 ``INVALID_CURSOR``。
- 幂等：``Idempotency-Key`` 头按契约校验（8—128 ASCII）；缺失时按
  ``settings.RESEARCH_REQUIRE_IDEMPOTENCY_KEY``（默认 False）决定是否强制，
  非法值一律 422 ``INVALID_IDEMPOTENCY_KEY``。
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import inspect
import json
import mimetypes
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.dependencies import get_optional_user_id, get_db
from ..research import contracts as C
from ..research.capabilities import build_capabilities
from ..research.errors import (
    ResearchAPIError,
    conflict,
    internal,
    invalid,
    not_found,
    payment_required,
    payload_too_large,
    unavailable,
)
from ..research.models import Project, ResearchTask, TaskEvent
from ..research.ownership import require_task

logger = structlog.get_logger(__name__)

__all__ = ["router", "handle_research_error"]


# ──────────────────────────────────────────────────────────────────────
# 常量与异常映射
# ──────────────────────────────────────────────────────────────────

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
_TERMINAL_VALUES = frozenset(
    st.value if hasattr(st, "value") else str(st) for st in C.TERMINAL_STATUSES
)
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _format_validation_error(exc: RequestValidationError) -> ResearchAPIError:
    """把 pydantic/FastAPI 校验失败折叠成统一错误体。"""
    details: List[Dict[str, Any]] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()))
        details.append(
            {
                "loc": loc or "request",
                "msg": str(err.get("msg", ""))[:300],
                "type": str(err.get("type", "")),
            }
        )
    first = details[0] if details else {"loc": "request", "msg": "请求参数不合法", "type": ""}
    return invalid(
        "VALIDATION_ERROR",
        f"请求参数不合法：{first['loc']} {first['msg']}".strip(),
        {"errors": details[:20]},
    )


def _map_service_exception(exc: BaseException) -> Optional[ResearchAPIError]:
    """把既有的权益/额度异常映射为 PRD §8.4 的 402。"""
    try:
        from ..services.entitlement_service import EntitlementError
    except Exception:  # pragma: no cover - 老版本缺少该异常类
        return None
    if not isinstance(exc, EntitlementError):
        return None
    code = str(getattr(exc, "code", "") or "")
    message = str(getattr(exc, "message", "") or "") or str(exc) or "当前账号权益不足。"
    return payment_required(message, {"entitlement_code": code} if code else None)


class _ResearchAPIRoute(APIRoute):
    """路由级错误归一化：校验错误 → 422 统一体；权益错误 → 402。"""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except RequestValidationError as exc:
                raise _format_validation_error(exc) from exc
            except ResearchAPIError:
                raise
            except Exception as exc:  # noqa: BLE001 - 只映射已识别的领域异常
                mapped = _map_service_exception(exc)
                if mapped is not None:
                    raise mapped from exc
                raise

        return handler


# ──────────────────────────────────────────────────────────────────────
# 依赖模块访问（懒加载：模块未落地时诚实返回 503）
# ──────────────────────────────────────────────────────────────────

_MODULE_CACHE: Dict[str, Any] = {}


def _research_module(name: str) -> Any:
    module = _MODULE_CACHE.get(name)
    if module is not None:
        return module
    try:
        # 相对导入必须带前导点，否则会被当作顶层绝对模块名（No module named 'project_service'）。
        dotted = name if name.startswith(".") else f".{name}"
        module = importlib.import_module(dotted, package="src.backend.research")
    except Exception as exc:  # noqa: BLE001 - 依赖模块尚未交付
        logger.error("research_module_missing", module=name, error=str(exc))
        raise unavailable(
            "DEPENDENCY_NOT_READY",
            f"研究模块 {name} 尚未就绪，该功能暂不可用。",
            {"module": name, "error": f"{type(exc).__name__}: {str(exc)[:200]}"},
        )
    _MODULE_CACHE[name] = module
    return module


async def _service_call(module: str, func: str, *args: Any, **kwargs: Any) -> Any:
    """调用服务函数；只传函数签名接受的 kwargs，兼容实现细节差异。"""
    target = getattr(_research_module(module), func, None)
    if target is None:
        raise unavailable(
            "DEPENDENCY_NOT_READY",
            f"研究模块 {module}.{func} 尚未实现，该功能暂不可用。",
            {"module": module, "function": func},
        )
    accepted: Dict[str, Any] = kwargs
    try:
        signature = inspect.signature(target)
        has_var_kw = any(
            param.kind is inspect.Parameter.VAR_KEYWORD
            for param in signature.parameters.values()
        )
        if not has_var_kw:
            accepted = {k: v for k, v in kwargs.items() if k in signature.parameters}
    except (TypeError, ValueError):  # pragma: no cover - 内建/C 函数
        accepted = kwargs
    result = target(*args, **accepted)
    if inspect.isawaitable(result):
        result = await result
    return result


# ──────────────────────────────────────────────────────────────────────
# 小工具：Actor、序列化、分页、幂等
# ──────────────────────────────────────────────────────────────────


def _actor(user_id: int) -> C.Actor:
    return C.Actor(int(user_id))


async def require_research_user(
    user_id: Optional[str] = Depends(get_optional_user_id),
) -> int:
    """研究域鉴权依赖：对外统一 401 错误外壳（PRD §8.2）。

    全局 `get_current_user` 在鉴权失败时抛 HTTPException，会被通用错误处理器
    包装成 `{"success": false, "error": ...}`，与研究域约定的
    `{"error": {code, message, details, retryable, request_id}}` 不一致。
    这里改成先取可选身份，再主动抛 `ResearchAPIError`，保证研究域只有一个
    错误信封（前端只需一套解析逻辑）。
    """
    if not user_id:
        raise _auth_error("需要登录后使用研究功能。")
    try:
        value = int(user_id)
    except (TypeError, ValueError):
        raise _auth_error("认证凭证格式错误。")
    if value <= 0:
        raise _auth_error("认证凭证无效或已过期。")
    return value


def _auth_error(message: str) -> ResearchAPIError:
    """401 错误码沿用全站既有约定 `AUTHENTICATION_FAILED`（前端已有统一续期逻辑），
    只把错误外壳换成研究域信封。"""
    return ResearchAPIError("AUTHENTICATION_FAILED", 401, message, retryable=False)


def _status_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _as_dict(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def _version_id_from_document(document: Dict[str, Any]) -> Optional[str]:
    """从文档详情里取当前版本 ID（``version.id`` 优先，其次顶层字段）。"""

    version = document.get("version")
    if isinstance(version, dict):
        for key in ("version_id", "id"):
            if isinstance(version.get(key), str):
                return version[key]
    for key in ("current_version_id", "version_id"):
        if isinstance(document.get(key), str):
            return document[key]
    return None


async def _commit(db: AsyncSession) -> None:
    """在返回响应前落库。

    ``get_db`` 依赖在响应发出之后才 commit，客户端紧接着读自己刚创建的资源
    （上传后建任务、导出后下载、出图后看图）会撞上 404 竞态；研究域的写端点
    因此显式在请求内提交。
    """
    await db.commit()


def _coerce(model: Any, value: Any) -> Any:
    """把服务层返回的 dict/DTO 收敛到契约模型；忽略契约外的多余字段。"""
    if isinstance(value, model):
        return value
    data = value.model_dump() if hasattr(value, "model_dump") else value
    if isinstance(data, dict):
        allowed = set(getattr(model, "model_fields", {}) or {})
        filtered = {k: v for k, v in data.items() if k in allowed}
        try:
            return model.model_validate(filtered)
        except Exception as exc:  # noqa: BLE001
            raise internal(f"服务层返回与契约不一致：{type(exc).__name__}") from exc
    raise internal("服务层返回了不支持的数据结构。")


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(int(offset)).encode("ascii")).decode("ascii")


def _decode_cursor(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        offset = int(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii"))
        if offset < 0:
            raise ValueError("negative offset")
    except Exception as exc:  # noqa: BLE001
        raise invalid("INVALID_CURSOR", "分页游标无效。") from exc
    return offset


def _page(items: List[Any], *, cursor: Optional[str], limit: int) -> Dict[str, Any]:
    offset = _decode_cursor(cursor)
    if offset > len(items):
        raise invalid(
            "INVALID_CURSOR",
            "分页游标超出数据范围。",
            {"total": len(items), "offset": offset},
        )
    window = items[offset : offset + limit]
    next_offset = offset + limit
    next_cursor = _encode_cursor(next_offset) if next_offset < len(items) else None
    return {
        "items": [_as_dict(item) for item in window],
        "next_cursor": next_cursor,
        "limit": limit,
        "total": len(items),
    }


def _idempotency_key(value: Optional[str]) -> Optional[str]:
    """校验 Idempotency-Key；返回规范化后的键（缺失返回 None）。"""
    if value is None or not str(value).strip():
        if bool(getattr(settings, "RESEARCH_REQUIRE_IDEMPOTENCY_KEY", False)):
            raise invalid(
                "INVALID_IDEMPOTENCY_KEY",
                "缺少 Idempotency-Key 头（8—128 个允许的 ASCII 字符）。",
            )
        return None
    try:
        return C.validate_idempotency_key(str(value))
    except ValueError as exc:
        raise invalid(
            "INVALID_IDEMPOTENCY_KEY",
            "Idempotency-Key 必须是 8—128 个允许的 ASCII 字符（字母/数字/._:-）。",
        ) from exc


def _content_disposition(filename: str) -> str:
    ascii_name = "".join(ch if ch.isascii() and ch > " " else "_" for ch in filename)[:120] or "artifact"
    from urllib.parse import quote

    quoted = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


# ──────────────────────────────────────────────────────────────────────
# 请求模型（只放路由层语义；任务输入直接用契约）
# ──────────────────────────────────────────────────────────────────


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    status: Optional[str] = Field(default=None, min_length=1, max_length=32)


class SourceSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_state_revision: int = Field(ge=1)


class DocumentSearchRequest(BaseModel):
    """私有全文检索请求（只读；范围限定在调用者自己的文档版本内）。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    version_id: Optional[str] = Field(default=None, max_length=128)
    limit: int = Field(default=8, ge=1, le=20)


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version_id: str = Field(min_length=1, max_length=128)
    hunk_ids: List[str] = Field(default_factory=list, max_length=500)


class ChartRequest(BaseModel):
    """POST /research/charts 请求体（T22）。

    数据只能来自已授权文档版本的表格（Markdown 管道表/CSV 块），不接受客户端直接传数，
    避免"图表看起来对、数据其实编造"。
    """

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=128)
    document_version_id: str = Field(min_length=1, max_length=128)
    chart_type: str = Field(min_length=1, max_length=32)
    x_column: str = Field(min_length=1, max_length=128)
    y_columns: list[str] = Field(min_length=1, max_length=8)
    title: Optional[str] = Field(default=None, max_length=200)
    table_index: int = Field(default=0, ge=0, le=50)


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=128)
    document_version_id: str = Field(min_length=1, max_length=128)
    format: str = Field(min_length=1, max_length=8)
    journal_style: str = Field(default="generic", min_length=1, max_length=32)
    # 附章必须显式勾选：默认不追加，避免"只想导出正文"的请求因缺少诊断/改动来源被 422 拦住。
    include_report: bool = False
    include_change_log: bool = False


# ──────────────────────────────────────────────────────────────────────
# 路由
# ──────────────────────────────────────────────────────────────────

router = APIRouter(
    prefix="/research",
    tags=["research"],
    route_class=_ResearchAPIRoute,
)


@router.get("/capabilities", response_model=C.CapabilityResponse)
async def get_capabilities(
    request: Request,
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> C.CapabilityResponse:
    """能力清单：每项状态来自本次请求内的真实检查（FR-01 / AT-005）。"""
    llm_state = {
        "llm_reachable": getattr(request.app.state, "llm_reachable", None),
        "llm_failure_reason": getattr(request.app.state, "llm_failure_reason", None),
    }
    return await build_capabilities(db, int(user_id), llm_state=llm_state)


# ── 产品指标（T19）────────────────────────────────────────


@router.get("/metrics")
async def get_metrics(
    since: Optional[datetime] = None,
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """当前登录用户的研究域聚合指标（T19 / FR-16）。

    只返回聚合数字：不含正文、引文、联系方式等任何逐条文本（见 analytics 模块口径）。
    平台级聚合不对普通用户开放，避免越权看到他人使用量。
    """
    if since is not None and since.tzinfo is not None:
        since = since.astimezone(timezone.utc).replace(tzinfo=None)
    tasks = await _service_call("analytics", "task_metrics", db, owner_id=int(user_id), since=since)
    funnel = await _service_call(
        "analytics", "funnel_metrics", db, owner_id=int(user_id), since=since
    )
    return {
        "scope": "self",
        "since": _iso(since),
        "tasks": _as_dict(tasks),
        "funnel": _as_dict(funnel),
    }


# ── 项目 ────────────────────────────────────────────────────────────


async def _list_projects(
    db: AsyncSession, actor: C.Actor, *, cursor: Optional[str], limit: int
) -> Dict[str, Any]:
    """项目列表：只按 owner 过滤；游标为偏移量（与其它列表一致）。"""
    offset = _decode_cursor(cursor)
    rows = (
        (
            await db.execute(
                select(Project)
                .where(Project.owner_id == actor.user_id)
                .order_by(Project.updated_at.desc(), Project.id.asc())
                .offset(offset)
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    has_more = len(rows) > limit
    window = rows[:limit]
    try:
        counter = getattr(_research_module("project_service"), "project_document_count")
    except Exception:  # noqa: BLE001
        counter = None

    items: List[Dict[str, Any]] = []
    for project in window:
        count = 0
        if counter is not None:
            try:
                count = int(await counter(db, actor.user_id, project.id))
            except Exception:  # noqa: BLE001 - 计数失败不影响列表
                count = 0
        items.append(
            {
                "id": project.id,
                "title": project.title,
                "status": project.status,
                "created_at": _iso(project.created_at),
                "updated_at": _iso(project.updated_at),
                "document_count": count,
            }
        )
    return {
        "items": items,
        "next_cursor": _encode_cursor(offset + limit) if has_more else None,
        "limit": limit,
    }


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreateRequest,
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    result = await _service_call(
        "project_service", "create_project", db, _actor(user_id), payload.title
    )
    await _commit(db)
    return result


@router.get("/projects")
async def list_projects(
    cursor: Optional[str] = Query(default=None, max_length=256),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return await _list_projects(db, _actor(user_id), cursor=cursor, limit=limit)


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return await _service_call("project_service", "get_project", db, _actor(user_id), project_id)


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    if payload.title is None and payload.status is None:
        raise invalid("NO_UPDATE_FIELDS", "没有需要更新的项目字段。")
    result = await _service_call(
        "project_service",
        "update_project",
        db,
        _actor(user_id),
        project_id,
        title=payload.title,
        status=payload.status,
    )
    await _commit(db)
    return result


# ── 文档 ────────────────────────────────────────────────────────────


@router.post("/projects/{project_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    project_id: str,
    file: UploadFile = File(..., description="PDF / DOCX / TXT / Markdown"),
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """上传文档：体积/类型超限在写库前拒绝，解析失败返回 415/422。"""
    filename = file.filename or "untitled"
    size_hint = getattr(file, "size", None)
    if isinstance(size_hint, int) and size_hint > C.MAX_FILE_BYTES:
        raise payload_too_large(
            f"单个文件不得超过 {C.MAX_FILE_BYTES // (1024 * 1024)} MiB。",
            {"max_bytes": C.MAX_FILE_BYTES, "size_bytes": size_hint},
        )
    data = await file.read(C.MAX_FILE_BYTES + 1)
    if len(data) > C.MAX_FILE_BYTES:
        raise payload_too_large(
            f"单个文件不得超过 {C.MAX_FILE_BYTES // (1024 * 1024)} MiB。",
            {"max_bytes": C.MAX_FILE_BYTES, "size_bytes": len(data)},
        )
    if not data:
        raise invalid("EMPTY_FILE", "上传文件为空。")
    mime = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    result = await _service_call(
        "document_service",
        "upload_document",
        db,
        _actor(user_id),
        project_id,
        filename=filename,
        mime=mime,
        data=bytes(data),
    )
    await _commit(db)
    return result


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return await _service_call("document_service", "get_document", db, _actor(user_id), document_id)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _service_call("document_service", "delete_document", db, _actor(user_id), document_id)
    await _commit(db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/documents/{document_id}/blocks")
async def list_document_blocks(
    document_id: str,
    version_id: Optional[str] = Query(default=None, max_length=128),
    cursor: Optional[str] = Query(default=None, max_length=256),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    blocks = await _service_call(
        "document_service",
        "list_blocks",
        db,
        _actor(user_id),
        document_id,
        version_id=version_id,
    )
    return _page(list(blocks or []), cursor=cursor, limit=limit)


@router.post("/documents/{document_id}/search")
async def search_document(
    document_id: str,
    payload: DocumentSearchRequest,
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """在调用者自己的文档版本内检索（FR-05）。

    授权先于检索：``document_service.get_document`` 统一 404，检索只在该版本文本
    内进行。向量后端不可用/模型缺失时降级为词法，并在每条命中与响应头上如实
    标注 ``retrieval_method`` / ``degraded`` / ``degraded_reason``，绝不伪装。
    """

    actor = _actor(user_id)
    document = await _service_call(
        "document_service", "get_document", db, actor, document_id
    )
    payload_doc = _as_dict(document) or {}
    version_id = (
        payload.version_id
        or payload_doc.get("current_version_id")
        or _version_id_from_document(payload_doc)
    )
    if not version_id:
        raise invalid("DOCUMENT_VERSION_MISSING", "该文档没有可检索的正文版本。", None)
    items = await _service_call(
        "retrieval_service",
        "search",
        db,
        actor,
        version_id,
        payload.query,
        limit=payload.limit,
    )
    items = list(items or [])
    methods = {
        str(item.get("retrieval_method") or "").strip() for item in items
    } - {""}
    reasons = {
        str(item.get("degraded_reason") or "").strip() for item in items
    } - {""}
    degraded = any(bool(item.get("degraded")) for item in items)
    if len(methods) == 1:
        method: Optional[str] = next(iter(methods))
    elif methods:
        method = "mixed"
    else:
        method = None
    if not degraded:
        reason_value: Optional[str] = None
    elif len(reasons) == 1:
        reason_value = next(iter(reasons))
    elif reasons:
        reason_value = sorted(reasons)[0]
    else:
        reason_value = None
    return {
        "document_id": document_id,
        "version_id": version_id,
        "query": payload.query,
        "retrieval_method": method,
        "degraded": degraded,
        "degraded_reason": reason_value,
        "items": items,
    }


# ── 来源 ────────────────────────────────────────────────────────────


@router.post("/projects/{project_id}/sources/search")
async def search_sources(
    project_id: str,
    payload: SourceSearchRequest,
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """检索项目内已保存来源；无匹配返回空数组（不伪造文献，AT-018）。"""
    items = await _service_call(
        "evidence_service", "search_sources", db, _actor(user_id), project_id, payload.query
    )
    return {
        "items": [_as_dict(item) for item in list(items or [])],
        "granularity": "metadata_only",
        "next_cursor": None,
    }


@router.post("/projects/{project_id}/sources", status_code=status.HTTP_201_CREATED)
async def create_source(
    project_id: str,
    payload: Dict[str, Any],
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """保存来源元数据（外部来源只存元数据，不承诺全文）。"""
    result = await _service_call(
        "evidence_service", "create_source", db, _actor(user_id), project_id, payload
    )
    await _commit(db)
    return result


# ── 任务 ────────────────────────────────────────────────────────────


@router.post("/tasks", status_code=status.HTTP_202_ACCEPTED, response_model=C.TaskAccepted)
async def create_task(
    payload: C.ResearchTaskInput,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> C.TaskAccepted:
    """统一任务入口（FR-02）。成功 202；非法请求 422；能力不可用 503/422。"""
    if payload.kind is C.TaskKind.CHART:
        raise invalid(
            "CHART_NOT_AVAILABLE",
            "R0 未开放图表生成任务（FR-13）；该 kind 暂不接受。",
            {"kind": _status_value(payload.kind)},
        )
    key = _idempotency_key(idempotency_key)
    accepted = _coerce(
        C.TaskAccepted,
        await _service_call(
            "task_service", "create_task", db, _actor(user_id), payload, idempotency_key=key
        ),
    )
    await _enqueue(db, _actor(user_id), accepted.task_id)
    await _commit(db)
    return accepted


async def _enqueue(db: AsyncSession, actor: C.Actor, task_id: str) -> None:
    """把已登记任务交给执行后端；失败时明确 503 而不是假装已排队。"""
    try:
        module = _research_module("task_service")
    except ResearchAPIError:
        return
    enqueue = getattr(module, "enqueue_task", None)
    if enqueue is None:
        return
    try:
        result = enqueue(db, actor, task_id)
        if inspect.isawaitable(result):
            await result
    except ResearchAPIError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("task_enqueue_failed", task_id=task_id, error=str(exc))
        raise unavailable(
            "TASK_ENQUEUE_FAILED",
            "任务已登记但未能进入执行队列，可用同一 Idempotency-Key 重试。",
            {"task_id": task_id, "error": f"{type(exc).__name__}: {str(exc)[:200]}"},
        ) from exc


@router.get("/tasks/{task_id}", response_model=C.TaskSnapshot)
async def get_task(
    task_id: str,
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> C.TaskSnapshot:
    return _coerce(
        C.TaskSnapshot,
        await _service_call("task_service", "get_task_snapshot", db, _actor(user_id), task_id),
    )


def _resolve_event_cursor(after_sequence: Optional[int], last_event_id: Optional[str]) -> int:
    """合并 ``after_sequence`` 与 ``Last-Event-ID``；两者不一致 → 422。"""
    parsed: Optional[int] = None
    if last_event_id is not None and str(last_event_id).strip():
        raw = str(last_event_id).strip()
        try:
            parsed = int(raw)
            if parsed < 0:
                raise ValueError("negative")
        except ValueError as exc:
            raise invalid(
                "INVALID_EVENT_CURSOR",
                "Last-Event-ID 必须是事件序号（非负整数）。",
                {"last_event_id": raw[:64]},
            ) from exc
    if after_sequence is not None and parsed is not None and after_sequence != parsed:
        raise invalid(
            "EVENT_SEQUENCE_MISMATCH",
            "after_sequence 与 Last-Event-ID 不一致，请只提供其中一个。",
            {"after_sequence": after_sequence, "last_event_id": parsed},
        )
    if after_sequence is not None:
        return int(after_sequence)
    return int(parsed) if parsed is not None else 0


async def _fetch_events(
    session: AsyncSession, task_id: str, after_sequence: int, limit: int = 200
) -> List[Any]:
    result = await session.execute(
        select(TaskEvent)
        .where(TaskEvent.task_id == task_id, TaskEvent.sequence > after_sequence)
        .order_by(TaskEvent.sequence.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def _fetch_task_status(session: AsyncSession, task_id: str) -> str:
    result = await session.execute(select(ResearchTask.status).where(ResearchTask.id == task_id))
    return _status_value(result.scalar_one_or_none())


def _event_frame(event: Any) -> str:
    """SSE 帧：``id: <sequence>\\nevent: <type>\\ndata: <json>\\n\\n``。"""
    payload = event.payload_json if isinstance(event.payload_json, dict) else {}
    data = {
        "schema_version": C.SCHEMA_VERSION,
        "task_id": event.task_id,
        "sequence": int(event.sequence),
        "attempt_no": int(event.attempt_no or 0),
        "created_at": _iso(event.created_at),
        "type": _status_value(event.type),
        "payload": payload,
    }
    body = json.dumps(data, ensure_ascii=False, default=str)
    return f"id: {int(event.sequence)}\nevent: {_status_value(event.type)}\ndata: {body}\n\n"


async def _event_frames(
    factory: Any,
    task_id: str,
    start_sequence: int,
    *,
    max_seconds: float,
    poll_seconds: float,
) -> AsyncIterator[str]:
    """事件流生成器。

    - 有事件就立刻推送；终态任务在没有新事件时立即结束（不无限挂起）；
    - 非终态任务在 ``max_seconds`` 内无新事件后结束，客户端用 Last-Event-ID 续订。
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.5, max_seconds)
    cursor = int(start_sequence)
    while True:
        try:
            async with factory() as session:
                events = await _fetch_events(session, task_id, cursor)
                task_status = await _fetch_task_status(session, task_id)
        except Exception as exc:  # noqa: BLE001 - 事件查询失败如实中断
            logger.error("task_event_poll_failed", task_id=task_id, error=str(exc))
            return
        for event in events:
            cursor = max(cursor, int(event.sequence))
            yield _event_frame(event)
        if task_status in _TERMINAL_VALUES and not events:
            return
        if task_status not in _TERMINAL_VALUES and not events and loop.time() >= deadline:
            return
        if not events:
            await asyncio.sleep(max(0.05, poll_seconds))


@router.get("/tasks/{task_id}/events")
async def stream_task_events(
    task_id: str,
    request: Request,
    after_sequence: Optional[int] = Query(default=None, ge=0),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    user_id: int = Depends(require_research_user),
):
    """任务事件 SSE。终态后无新事件立即结束；不返回其它用户的任务。"""
    actor = _actor(user_id)
    factory = getattr(request.app.state, "db_session_factory", None)
    if factory is None:
        raise unavailable("DB_UNAVAILABLE", "事件流暂不可用：数据库会话工厂未初始化。")
    start = _resolve_event_cursor(after_sequence, last_event_id)
    # 授权用短会话：Task 不存在/不属于当前用户 → 404（不泄露存在性）。
    async with factory() as session:
        await require_task(session, actor, task_id)

    max_seconds = float(getattr(settings, "RESEARCH_SSE_MAX_SECONDS", 60))
    poll_seconds = float(getattr(settings, "RESEARCH_SSE_POLL_SECONDS", 0.5))
    return StreamingResponse(
        _event_frames(
            factory,
            task_id,
            start,
            max_seconds=max_seconds,
            poll_seconds=poll_seconds,
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/tasks/{task_id}/resume", response_model=C.TaskSnapshot)
async def resume_task(
    task_id: str,
    payload: C.ResumeInput,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> C.TaskSnapshot:
    result = _coerce(
        C.TaskSnapshot,
        await _service_call(
            "task_service",
            "resume_task",
            db,
            _actor(user_id),
            task_id,
            payload,
            idempotency_key=_idempotency_key(idempotency_key),
        ),
    )
    await _commit(db)
    return result


@router.post("/tasks/{task_id}/cancel", response_model=C.TaskSnapshot)
async def cancel_task(
    task_id: str,
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> C.TaskSnapshot:
    result = _coerce(
        C.TaskSnapshot,
        await _service_call("task_service", "cancel_task", db, _actor(user_id), task_id),
    )
    await _commit(db)
    return result


@router.post("/tasks/{task_id}/retry", status_code=status.HTTP_202_ACCEPTED, response_model=C.TaskAccepted)
async def retry_task(
    task_id: str,
    payload: RetryRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> C.TaskAccepted:
    # 乐观并发：客户端看到的 state_revision 必须是当前值，否则 409。
    snapshot = _coerce(
        C.TaskSnapshot,
        await _service_call("task_service", "get_task_snapshot", db, _actor(user_id), task_id),
    )
    if int(snapshot.state_revision) != int(payload.expected_state_revision):
        raise conflict(
            "STATE_REVISION_MISMATCH",
            "任务状态已变化，请刷新后重试。",
            {
                "expected_state_revision": payload.expected_state_revision,
                "current_state_revision": int(snapshot.state_revision),
            },
        )
    accepted = _coerce(
        C.TaskAccepted,
        await _service_call(
            "task_service",
            "retry_task",
            db,
            _actor(user_id),
            task_id,
            idempotency_key=_idempotency_key(idempotency_key),
        ),
    )
    await _enqueue(db, _actor(user_id), accepted.task_id)
    await _commit(db)
    return accepted


@router.get("/tasks/{task_id}/findings")
async def list_task_findings(
    task_id: str,
    cursor: Optional[str] = Query(default=None, max_length=256),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    findings = await _service_call("task_service", "list_findings", db, _actor(user_id), task_id)
    return _page([_coerce(C.Finding, item) for item in list(findings or [])], cursor=cursor, limit=limit)


# ── 成果 ────────────────────────────────────────────────────────────


def _artifact_ref(artifact: Any) -> Dict[str, Any]:
    mime = str(getattr(artifact, "mime", "") or "application/octet-stream")
    size = int(getattr(artifact, "size_bytes", 0) or 0)
    return {
        "id": artifact.id,
        "owner_id": int(getattr(artifact, "owner_id", 0) or 0),
        "task_id": artifact.task_id,
        "kind": str(getattr(artifact, "kind", "")),
        "version": int(getattr(artifact, "version", 1) or 1),
        "content_hash": str(getattr(artifact, "content_hash", "") or ""),
        "mime": mime,
        "filename": str(getattr(artifact, "filename", "") or "artifact"),
        "size_bytes": size,
        "validation": dict(getattr(artifact, "validation_json", None) or {}),
        "downloadable": size > 0,
    }


@router.get("/artifacts/{artifact_id}")
async def get_artifact(
    artifact_id: str,
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    artifact = await _service_call("artifact_service", "read_artifact", db, _actor(user_id), artifact_id)
    return _artifact_ref(artifact)


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(
    artifact_id: str,
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
):
    """受控下载：正文取自数据库，文件名不含客户端路径。"""
    artifact = await _service_call("artifact_service", "read_artifact", db, _actor(user_id), artifact_id)
    decode = getattr(_research_module("artifact_service"), "decode_artifact_body", None)
    if decode is None:
        raise unavailable("DEPENDENCY_NOT_READY", "成果下载解码器尚未就绪。")
    body = decode(artifact)
    if isinstance(body, str):
        body = body.encode("utf-8")
    if not body:
        raise not_found("成果正文")
    mime = str(getattr(artifact, "mime", "") or "application/octet-stream")
    filename = str(getattr(artifact, "filename", "") or "artifact")
    return Response(
        content=bytes(body),
        media_type=mime,
        headers={
            "Content-Disposition": _content_disposition(filename),
            "X-Content-Type-Options": "nosniff",
        },
    )


# ── 真实数据图表（T22 / FR-13 / AT-055）─────────────────────────────


@router.post("/charts", status_code=status.HTTP_201_CREATED)
async def create_chart(
    payload: ChartRequest,
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """从已授权文档版本的表格数据生成图表。

    能力关闭时返回 503 ``CHART_CAPABILITY_DISABLED``，渲染失败返回 500
    ``CHART_RENDER_FAILED``；**不会**回退成"图表生成失败"占位图，也不改写数据。
    """
    chart_type = payload.chart_type.strip().lower()
    columns = [item.strip() for item in payload.y_columns if item and item.strip()]
    artifact = await _service_call(
        "chart_service",
        "create_chart",
        db,
        _actor(user_id),
        project_id=payload.project_id,
        document_version_id=payload.document_version_id,
        chart_type=chart_type,
        x_column=payload.x_column.strip(),
        y_columns=columns,
        title=(payload.title or "").strip() or None,
        table_index=int(payload.table_index),
    )
    await _commit(db)
    ref = _artifact_ref(artifact)
    ref["download_url"] = f"/api/v1/research/artifacts/{ref['id']}/download"
    return ref


# ── 修改应用与导出 ──────────────────────────────────────────────────


@router.post("/revision-proposals/{proposal_id}/apply", response_model=C.ApplyResult)
async def apply_revision_proposal(
    proposal_id: str,
    payload: ApplyRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> C.ApplyResult:
    result = await _service_call(
        "revision_service",
        "apply_proposal",
        db,
        _actor(user_id),
        proposal_id,
        expected_version_id=payload.expected_version_id,
        hunk_ids=payload.hunk_ids or None,
        idempotency_key=_idempotency_key(idempotency_key),
    )
    await _commit(db)
    return _coerce(C.ApplyResult, result)


@router.post("/exports", status_code=status.HTTP_201_CREATED)
async def export_document(
    payload: ExportRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(require_research_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """导出：只支持契约声明的格式；未支持的格式 422 而不是降级成别的格式。"""
    fmt = payload.format.strip().lower()
    if fmt not in C.SUPPORTED_EXPORT_FORMATS:
        raise invalid(
            "UNSUPPORTED_EXPORT_FORMAT",
            "暂不支持该导出格式。",
            {"format": fmt, "supported": sorted(C.SUPPORTED_EXPORT_FORMATS)},
        )
    style = payload.journal_style.strip()
    if style not in C.SUPPORTED_JOURNAL_STYLES:
        raise invalid(
            "UNSUPPORTED_JOURNAL_STYLE",
            "暂不支持该期刊格式。",
            {"journal_style": style, "supported": sorted(C.SUPPORTED_JOURNAL_STYLES)},
        )
    artifact = await _service_call(
        "export_service",
        "export",
        db,
        _actor(user_id),
        project_id=payload.project_id,
        document_version_id=payload.document_version_id,
        fmt=fmt,
        journal_style=style,
        include_report=bool(payload.include_report),
        include_change_log=bool(payload.include_change_log),
        idempotency_key=_idempotency_key(idempotency_key),
    )
    await _commit(db)
    ref = _artifact_ref(artifact)
    ref["download_url"] = f"/api/v1/research/artifacts/{ref['id']}/download"
    return ref


# ──────────────────────────────────────────────────────────────────────
# 异常处理器（app.py 可直接复用；当前 app.py 已有等价内联实现）
# ──────────────────────────────────────────────────────────────────


def handle_research_error(request: Request, exc: ResearchAPIError) -> JSONResponse:
    """把 ``ResearchAPIError`` 统一转换成 ``{"error": {...}}`` JSON 响应。

    app.py 现有实现与本函数等价；若后续合并，建议改为
    ``app.add_exception_handler(ResearchAPIError, handle_research_error)``。
    """
    return JSONResponse(
        status_code=int(exc.status_code),
        content=exc.to_payload(request_id=getattr(request.state, "request_id", None)),
    )
