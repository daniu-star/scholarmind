"""能力真实性检查（PRD v1.0 FR-01 / AT-005 / 审计问题 01·07·15）。

设计约束（R0_INTERFACE_SPEC.md §4）：

- 每一项能力的 ``status`` 都来自**本次请求内可观察的真实信号**：数据库可查询性、
  模型凭证与近期可达性、解析器/向量依赖可导入性、外部来源配置、浏览器与代码执行
  开关、Skill 目录与 Skill 记录。禁止硬编码 ``ready``。
- 未实现 / 无法验证的能力返回 ``unknown`` 或 ``disabled``，绝不写成 ``ready``；
  ``unauthorized`` 只用于"用户权益不覆盖"，不得用来掩盖"未实现"（FR-01）。
- 检查本身失败（异常）不能拖垮端点：单条失败降级为 ``unknown`` 并记录原因。

对外的稳定入口是 :func:`build_capabilities`。
"""

from __future__ import annotations

import asyncio
import importlib.util
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Dict, List, Mapping, Optional, Tuple

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.orm import Skill, User
from .contracts import CapabilityInfo, CapabilityResponse, CapabilityStatus, utcnow

logger = structlog.get_logger(__name__)

__all__ = ["build_capabilities", "CAPABILITY_NAMES"]

#: 能力名称清单（前端与验收测试可按名字断言）。
CAPABILITY_NAMES: Tuple[str, ...] = (
    "database",
    "model.llm",
    "document.parser.text",
    "document.parser.pdf",
    "document.parser.docx",
    "retrieval.vector",
    "sources.metadata",
    "library.local",
    "task.engine",
    "task.review",
    "task.draft_from_outline",
    "task.revision",
    "export.md",
    "export.docx",
    "skills",
    "code_execution",
    "browser_agent",
    "chart_generation",
)

_ADMIN_ROLES = frozenset({"admin"})


# ──────────────────────────────────────────────────────────────────────
# 小工具
# ──────────────────────────────────────────────────────────────────


def _info(
    name: str,
    status: CapabilityStatus,
    *,
    reason: str = "",
    granularity: str = "",
    detail: Optional[Dict[str, Any]] = None,
    checked_at: Optional[datetime] = None,
) -> CapabilityInfo:
    """构造单条能力信息；``checked_at`` 默认取本次检查时间。"""
    return CapabilityInfo(
        name=name,
        status=status,
        checked_at=checked_at or utcnow(),
        reason=reason,
        granularity=granularity,
        detail=dict(detail or {}),
    )


def _module_state(dotted: str) -> Tuple[bool, str]:
    """检查模块是否可导入（只解析 spec，不执行模块体之外的重活）。"""
    try:
        spec = importlib.util.find_spec(dotted)
    except (ImportError, AttributeError, ValueError, TypeError) as exc:  # 父包缺失等
        return False, f"{type(exc).__name__}: {exc}"
    return (spec is not None), ""


def _spec_state(dotted: str) -> Tuple[bool, str]:
    """检查第三方依赖是否已安装（importlib.util.find_spec）。"""
    try:
        spec = importlib.util.find_spec(dotted)
    except (ImportError, AttributeError, ValueError, TypeError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return (spec is not None), ""


def _configured(value: Optional[str]) -> bool:
    """判断配置值是否真的被填写（复用全局占位符识别）。"""
    if not value:
        return False
    try:
        from ..config import _is_placeholder_key  # 局部导入，复用全局占位符识别
    except Exception:  # pragma: no cover - 配置模块被裁剪时保守处理
        return bool(str(value).strip())
    return not _is_placeholder_key(value)


def _count_local_resources() -> Tuple[str, Any]:
    """本地学术资源库（legacy SQLite ``academic_resources``）真实条数。

    只读打开；文件/表缺失时返回 ("empty"|"missing", 0)，不抛出。
    """
    path = Path(settings.DB_PATH)
    if not path.exists():
        return "missing", 0
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=3.0)
    except sqlite3.Error as exc:  # pragma: no cover - 权限/损坏
        return "unreadable", f"{type(exc).__name__}"
    try:
        row = conn.execute("SELECT COUNT(*) FROM academic_resources").fetchone()
        return "ready", int(row[0]) if row else 0
    except sqlite3.OperationalError:
        return "empty", 0  # 表尚未初始化：库存在但没有数据
    except sqlite3.Error as exc:  # pragma: no cover
        return "unreadable", f"{type(exc).__name__}"
    finally:
        conn.close()


def _count_skill_files() -> int:
    """Skill 目录下的一级条目数量（目录不可读时返回 -1）。"""
    directory = Path(settings.SKILLS_DIR)
    if not directory.is_dir():
        return -1
    try:
        return sum(1 for _ in directory.iterdir())
    except OSError:  # pragma: no cover
        return -1


# ──────────────────────────────────────────────────────────────────────
# 各能力检查
# ──────────────────────────────────────────────────────────────────


async def _check_database(db: AsyncSession) -> CapabilityInfo:
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        return _info(
            "database",
            CapabilityStatus.UNKNOWN,
            reason=f"数据库不可查询：{type(exc).__name__}",
            detail={"error": str(exc)[:200]},
        )
    return _info(
        "database",
        CapabilityStatus.READY,
        reason="数据库连接可查询（SELECT 1 成功）。",
        granularity="单库读写",
        detail={"probe": "SELECT 1"},
    )


async def _check_model_llm(llm_state: Optional[Mapping[str, Any]]) -> CapabilityInfo:
    key = getattr(settings, "DEEPSEEK_API_KEY", "") or ""
    if not _configured(key):
        return _info(
            "model.llm",
            CapabilityStatus.DISABLED,
            reason="未配置真实模型凭证（DEEPSEEK_API_KEY 为空或为占位符），研究任务无法调用模型。",
            granularity="模型推理",
            detail={"model": getattr(settings, "DEEPSEEK_MODEL", ""), "credentialed": False},
        )

    state = dict(llm_state or {})
    reachable = state.get("llm_reachable")
    failure = state.get("llm_failure_reason")
    models = {
        "default": getattr(settings, "DEEPSEEK_MODEL", ""),
        "flash": getattr(settings, "DEEPSEEK_MODEL_FLASH", ""),
        "pro": getattr(settings, "DEEPSEEK_MODEL_PRO", ""),
    }
    if reachable is True:
        return _info(
            "model.llm",
            CapabilityStatus.READY,
            reason="凭证已配置，启动探测已确认模型近期可达。",
            granularity="模型推理（flash/pro）",
            detail={"models": models, "probe": "startup", "llm_reachable": True},
        )
    if reachable is False:
        return _info(
            "model.llm",
            CapabilityStatus.DEGRADED,
            reason=f"凭证已配置，但启动探测不可达：{failure or '未返回原因'}",
            granularity="模型推理（不可用时段内任务会失败并明确报错）",
            detail={
                "models": models,
                "probe": "startup",
                "llm_reachable": False,
                "failure_reason": failure,
            },
        )
    return _info(
        "model.llm",
        CapabilityStatus.UNKNOWN,
        reason="凭证已配置，但本次请求拿不到近期可达性探测结果，无法确认真实可用。",
        granularity="模型推理",
        detail={"models": models, "probe": "not_run", "llm_reachable": None},
    )


async def _check_text_parser() -> CapabilityInfo:
    available, err = _module_state("src.backend.research.document_parser")
    if not available:
        return _info(
            "document.parser.text",
            CapabilityStatus.UNKNOWN,
            reason=f"文档解析模块不可用（{err or '未找到'}）；TXT/Markdown 上传暂不可用。",
            granularity="txt / md",
            detail={"module": "research.document_parser"},
        )
    return _info(
        "document.parser.text",
        CapabilityStatus.READY,
        reason="解析模块可导入，TXT/Markdown 走内置解码路径。",
        granularity="txt / md / 纯文本粘贴",
        detail={"module": "research.document_parser"},
    )


async def _check_pdf_parser() -> CapabilityInfo:
    module_ok, module_err = _module_state("src.backend.research.document_parser")
    dep_ok, dep_err = _spec_state("pypdf")
    detail = {"module_ok": module_ok, "pypdf": dep_ok}
    if not module_ok or not dep_ok:
        return _info(
            "document.parser.pdf",
            CapabilityStatus.DISABLED,
            reason=f"PDF 解析依赖缺失（{module_err or dep_err or 'pypdf 未安装'}）。",
            granularity="pdf",
            detail=detail,
        )
    return _info(
        "document.parser.pdf",
        CapabilityStatus.READY,
        reason="解析模块与 pypdf 均可用；页数上限 %d 页。" % 200,
        granularity="pdf（按页解析，超限拒绝）",
        detail=detail,
    )


async def _check_docx_parser() -> CapabilityInfo:
    module_ok, module_err = _module_state("src.backend.research.document_parser")
    zip_ok, _ = _spec_state("zipfile")
    detail = {"module_ok": module_ok, "zipfile": zip_ok}
    if not module_ok:
        return _info(
            "document.parser.docx",
            CapabilityStatus.UNKNOWN,
            reason=f"文档解析模块不可用（{module_err or '未找到'}）。",
            granularity="docx",
            detail=detail,
        )
    if not zip_ok:
        return _info(
            "document.parser.docx",
            CapabilityStatus.DISABLED,
            reason="缺少 zipfile 支持（Python 运行时不完整）。",
            granularity="docx",
            detail=detail,
        )
    return _info(
        "document.parser.docx",
        CapabilityStatus.READY,
        reason="解析模块可导入，DOCX 通过 zipfile 读取 word/document.xml（不依赖第三方库）。",
        granularity="docx（段落级，超限拒绝）",
        detail=detail,
    )


async def _check_vector_retrieval() -> CapabilityInfo:
    module_ok, module_err = _module_state("src.backend.research.retrieval_service")
    embed_ok, embed_err = _spec_state("sentence_transformers")
    try:
        from .embeddings import local_model_available, normalize_model_name

        model = normalize_model_name(
            getattr(settings, "RESEARCH_EMBEDDING_MODEL", "")
        )
        model_local = local_model_available(model) if model else False
    except Exception:  # pragma: no cover - 探测失败按未配置处理
        model = ""
        model_local = False
    allow_download = bool(
        getattr(settings, "RESEARCH_EMBEDDING_ALLOW_DOWNLOAD", False)
    )
    detail = {
        "module_ok": module_ok,
        "sentence_transformers": embed_ok,
        "embedding_model_configured": model or None,
        "embedding_model_local": model_local,
        "embedding_allow_download": allow_download,
    }
    if not module_ok:
        return _info(
            "retrieval.vector",
            CapabilityStatus.UNKNOWN,
            reason=f"检索服务模块不可用（{module_err or '未找到'}）。",
            granularity="私有文档检索",
            detail=detail,
        )
    if not model:
        # 默认路径：没有配置模型时不要谎称"向量可用"
        return _info(
            "retrieval.vector",
            CapabilityStatus.DEGRADED,
            reason=(
                "未配置 RESEARCH_EMBEDDING_MODEL；检索在同一授权范围内使用词法匹配，"
                "结果标注 retrieval_method=lexical / degraded=true。"
            ),
            granularity="词法检索（未启用向量后端）",
            detail={**detail, "retrieval_fallback": "lexical", "backend": "lexical"},
        )
    if not embed_ok:
        return _info(
            "retrieval.vector",
            CapabilityStatus.DEGRADED,
            reason=(
                f"已配置模型 {model}，但 sentence-transformers 不可用（{embed_err or '未安装'}）；"
                "检索降级为词法匹配。"
            ),
            granularity="词法检索（vector 依赖缺失）",
            detail={**detail, "retrieval_fallback": "lexical", "backend": "lexical"},
        )
    if not model_local and not allow_download:
        return _info(
            "retrieval.vector",
            CapabilityStatus.DEGRADED,
            reason=(
                f"已配置模型 {model}，但本机没有该模型缓存且未允许下载；"
                "检索会降级为词法匹配（不会联网拉模型）。"
            ),
            granularity="词法检索（模型未缓存）",
            detail={**detail, "retrieval_fallback": "lexical", "backend": "lexical"},
        )
    return _info(
        "retrieval.vector",
        CapabilityStatus.READY,
        reason=(
            f"本地 embedding 模型 {model} 可用；检索在同一授权范围内按余弦相似度排序，"
            "调用失败会诚实降级为词法并在结果里标注。" if model_local else
            f"已允许下载 embedding 模型 {model}；首次检索时会加载（失败则降级词法并标注）。"
        ),
        granularity="向量（余弦）+ 同范围词法兜底",
        detail={**detail, "backend": "sentence-transformers"},
    )


async def _check_sources_metadata() -> CapabilityInfo:
    providers: List[str] = []
    missing: List[str] = []
    for label, dotted in (
        ("arxiv", "src.backend.services.arxiv_service"),
        ("semantic_scholar", "src.backend.services.semantic_scholar_service"),
    ):
        ok, err = _module_state(dotted)
        (providers if ok else missing).append(label if ok else f"{label}({err or 'missing'})")
    cnki_enabled = bool(getattr(settings, "CNKI_MASTER_ENABLED", False))
    if cnki_enabled:
        ok, _ = _module_state("src.backend.services.cnki_service")
        providers.append("cnki" if ok else "cnki(not_ready)")
    detail = {
        "providers": providers,
        "cnki_enabled": cnki_enabled,
        "entitlement": "metadata_only",
        "connectivity_probe": "not_run",
    }
    if not providers:
        return _info(
            "sources.metadata",
            CapabilityStatus.DISABLED,
            reason="未接入任何外部文献来源（arXiv / Semantic Scholar 均不可用）。",
            granularity="元数据检索",
            detail={**detail, "missing": missing},
        )
    return _info(
        "sources.metadata",
        CapabilityStatus.DEGRADED,
        reason="仅提供元数据检索（标题/作者/年份/摘要/DOI）；未执行实时连通性探测，全文权限不适用。",
        granularity="metadata_only（不承诺全文）",
        detail={**detail, "missing": missing},
    )


async def _check_local_library() -> CapabilityInfo:
    status, payload = await asyncio.to_thread(_count_local_resources)
    if status == "missing":
        return _info(
            "library.local",
            CapabilityStatus.DISABLED,
            reason=f"本地资源库文件不存在：{settings.DB_PATH}",
            granularity="本地学术资源",
            detail={"db_path": settings.DB_PATH},
        )
    if status == "unreadable":
        return _info(
            "library.local",
            CapabilityStatus.UNKNOWN,
            reason=f"本地资源库不可读：{payload}",
            granularity="本地学术资源",
            detail={"db_path": settings.DB_PATH},
        )
    count = int(payload or 0)
    return _info(
        "library.local",
        CapabilityStatus.READY,
        reason=(
            f"本地资源库可读，已收录 {count} 条元数据。" if count else "本地资源库可读，当前为空（空即为空，不展示虚构文献）。"
        ),
        granularity="本地元数据（来源标记为本地库）",
        detail={"db_path": settings.DB_PATH, "records": count, "empty": count == 0},
    )


_TASK_MODULES = (
    ("task_service", "src.backend.research.task_service"),
    ("task_events", "src.backend.research.task_events"),
)


async def _check_task_engine() -> CapabilityInfo:
    available: List[str] = []
    missing: List[str] = []
    for label, dotted in _TASK_MODULES:
        ok, err = _module_state(dotted)
        if ok:
            available.append(label)
        else:
            missing.append(f"{label}:{err or 'missing'}")
    detail = {"available": available, "missing": missing, "backend": getattr(settings, "TASK_BACKEND", "")}
    if not missing:
        return _info(
            "task.engine",
            CapabilityStatus.READY,
            reason="任务登记与事件流模块均已就位；并发与超时由服务层限流。",
            granularity="统一任务入口（POST /tasks）",
            detail=detail,
        )
    return _info(
        "task.engine",
        CapabilityStatus.UNKNOWN,
        reason="任务执行链路未就绪：缺少 " + "、".join(missing) + "。",
        granularity="任务入口",
        detail=detail,
    )


def _entitlement_status(granted: bool, label: str) -> CapabilityInfo:
    if granted:
        return _info(label, CapabilityStatus.READY, reason="当前权益覆盖该任务类型。", granularity="按权益")
    return _info(
        label,
        CapabilityStatus.UNAUTHORIZED,
        reason="当前会员权益不包含该任务类型（未开通或已过期）。",
        granularity="按权益",
        detail={"required": "pipeline_access"},
    )


async def _check_entitlements(db: AsyncSession, user_id: int) -> List[CapabilityInfo]:
    try:
        from ..services.entitlement_service import EntitlementService

        snapshot = await EntitlementService.get_snapshot(db, user_id)
    except Exception as exc:
        detail = {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        return [
            _info(
                name,
                CapabilityStatus.UNKNOWN,
                reason="权益快照不可读，无法判断用户是否具备该能力。",
                granularity="按权益",
                detail=detail,
            )
            for name in ("task.review", "task.draft_from_outline", "task.revision")
        ]

    access = snapshot.get("pipeline_access") or {}
    detail_base = {
        "plan": snapshot.get("plan"),
        "model_tier": snapshot.get("model_tier"),
        "pipeline_access": dict(access),
        "membership_active": snapshot.get("membership_active"),
    }
    return [
        _entitlement_status(bool(access.get("external_review")), "task.review").model_copy(
            update={"detail": detail_base}
        ),
        _entitlement_status(bool(access.get("generation")), "task.draft_from_outline").model_copy(
            update={"detail": detail_base}
        ),
        _entitlement_status(bool(access.get("modification")), "task.revision").model_copy(
            update={"detail": detail_base}
        ),
    ]


async def _check_exports() -> List[CapabilityInfo]:
    module_ok, module_err = _module_state("src.backend.research.export_service")
    md = _info(
        "export.md",
        CapabilityStatus.READY if module_ok else CapabilityStatus.UNKNOWN,
        reason="导出服务可导入，Markdown 导出可用。" if module_ok else f"导出服务不可用（{module_err}）。",
        granularity="md",
        detail={"formats": ["md"], "module_ok": module_ok},
    )
    docx_ok, docx_err = _spec_state("docx")
    if module_ok and docx_ok:
        docx = _info(
            "export.docx",
            CapabilityStatus.READY,
            reason="导出服务与 python-docx 均可用。",
            granularity="docx",
            detail={"formats": ["docx"], "python_docx": True},
        )
    else:
        docx = _info(
            "export.docx",
            CapabilityStatus.DISABLED if module_ok else CapabilityStatus.UNKNOWN,
            reason=(
                f"python-docx 不可用（{docx_err}），DOCX 导出关闭。"
                if module_ok
                else f"导出服务不可用（{module_err}），DOCX 导出关闭。"
            ),
            granularity="docx",
            detail={"python_docx": docx_ok},
        )
    return [md, docx]


async def _check_skills(db: AsyncSession) -> CapabilityInfo:
    enabled = 0
    db_error: Optional[str] = None
    try:
        row = await db.execute(select(func.count()).select_from(Skill).where(Skill.enabled.is_(True)))
        enabled = int(row.scalar_one() or 0)
    except Exception as exc:
        db_error = f"{type(exc).__name__}: {str(exc)[:160]}"
    files = await asyncio.to_thread(_count_skill_files)
    detail = {
        "skills_dir": str(getattr(settings, "SKILLS_DIR", "")),
        "skills_dir_entries": files,
        "enabled_records": enabled,
        "max_skill_ids": 8,
        "executor": "rules_only",
    }
    if db_error:
        return _info(
            "skills",
            CapabilityStatus.UNKNOWN,
            reason=f"Skill 目录/记录无法确认：{db_error}",
            granularity="规则/提示词类 Skill",
            detail={**detail, "error": db_error},
        )
    if files < 0 and enabled == 0:
        return _info(
            "skills",
            CapabilityStatus.DISABLED,
            reason="Skill 目录不存在且无可用 Skill 记录。",
            granularity="规则/提示词类 Skill",
            detail=detail,
        )
    if enabled == 0:
        return _info(
            "skills",
            CapabilityStatus.DEGRADED,
            reason="Skill 目录存在但无启用记录；本次请求无法选择 Skill。",
            granularity="规则/提示词类 Skill",
            detail=detail,
        )
    return _info(
        "skills",
        CapabilityStatus.READY,
        reason=f"可用 Skill 记录 {enabled} 个；仅规则/提示词类可执行，工具型写操作不开放。",
        granularity="rules_only（工具型 Skill 写操作关闭）",
        detail=detail,
    )


async def _check_code_execution(db: AsyncSession, user_id: int) -> CapabilityInfo:
    enabled = bool(getattr(settings, "CODE_EXECUTION_ENABLED", False))
    if not enabled:
        return _info(
            "code_execution",
            CapabilityStatus.DISABLED,
            reason="代码执行默认关闭（FR-01 / AT-049）；启用后也仅限管理员。",
            granularity="sandbox（仅管理员）",
            detail={"config_enabled": False},
        )
    is_admin = False
    try:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        admin_names = {n.strip() for n in str(getattr(settings, "ADMIN_USERNAMES", "") or "").split(",") if n.strip()}
        is_admin = bool(user) and (
            getattr(user, "role", "") in _ADMIN_ROLES or getattr(user, "username", "") in admin_names
        )
    except Exception:
        return _info(
            "code_execution",
            CapabilityStatus.UNKNOWN,
            reason="已开启代码执行，但无法确认当前用户是否为管理员。",
            granularity="sandbox（仅管理员）",
            detail={"config_enabled": True, "admin": None},
        )
    if not is_admin:
        return _info(
            "code_execution",
            CapabilityStatus.UNAUTHORIZED,
            reason="代码执行已开启，但仅管理员可用（当前账号不是管理员）。",
            granularity="sandbox（仅管理员）",
            detail={"config_enabled": True, "admin": False},
        )
    return _info(
        "code_execution",
        CapabilityStatus.READY,
        reason="代码执行已开启且当前账号为管理员。",
        granularity="sandbox（仅管理员）",
        detail={"config_enabled": True, "admin": True},
    )


async def _check_browser_agent() -> CapabilityInfo:
    enabled = bool(getattr(settings, "BROWSER_AGENT_ENABLED", False))
    module_ok, module_err = _module_state("src.backend.routers.browser_agent")
    detail = {"config_enabled": enabled, "module_ok": module_ok}
    if not enabled:
        return _info(
            "browser_agent",
            CapabilityStatus.DISABLED,
            reason="浏览器代理未在首期开放（FR-13）：开关关闭，正式研究入口不可用。",
            granularity="browser automation（未开放）",
            detail=detail,
        )
    if not module_ok:
        return _info(
            "browser_agent",
            CapabilityStatus.DISABLED,
            reason=f"开关已开启但代理路由不可导入（{module_err}）。",
            granularity="browser automation",
            detail=detail,
        )
    return _info(
        "browser_agent",
        CapabilityStatus.READY,
        reason="开关已开启且代理路由可导入；仅管理员可用。",
        granularity="browser automation（管理员）",
        detail=detail,
    )


async def _check_chart_generation() -> CapabilityInfo:
    enabled = bool(getattr(settings, "ENABLE_VERIFIED_CHARTS", False))
    module_ok, module_err = _module_state("src.backend.research.chart_service")
    detail = {"config_enabled": enabled, "module_ok": module_ok, "matplotlib": _spec_state("matplotlib")[0]}
    if not enabled or not module_ok:
        return _info(
            "chart_generation",
            CapabilityStatus.DISABLED,
            reason=(
                "图表生成未开放（FR-13/T22）：需先通过数据数值、单位与显示范围校验，"
                "并显式打开 ENABLE_VERIFIED_CHARTS。"
            ),
            granularity="chart（未开放）",
            detail={**detail, "module_error": module_err or None},
        )
    return _info(
        "chart_generation",
        CapabilityStatus.READY,
        reason="图表生成开关与确定性校验模块均已就绪；仅接受受授权数据版本与显式列映射。",
        granularity="chart",
        detail=detail,
    )


# ──────────────────────────────────────────────────────────────────────
# 对外入口
# ──────────────────────────────────────────────────────────────────


async def build_capabilities(
    db: AsyncSession,
    user_id: int,
    *,
    llm_state: Optional[Mapping[str, Any]] = None,
) -> CapabilityResponse:
    """汇总能力真实状态。

    ``llm_state`` 由路由层从 ``app.state`` 取（``llm_reachable`` /
    ``llm_failure_reason``，见 ``core/events.py`` 启动探测）。缺省时模型能力
    只能报 ``unknown``，不会假装 ready。
    """
    checked_at = utcnow()

    async def _safe(label: str, awaitable: Awaitable[CapabilityInfo]) -> CapabilityInfo:
        try:
            return await awaitable
        except Exception as exc:  # 单条检查失败不影响整体
            logger.warning("capability_check_failed", capability=label, error=str(exc))
            return _info(
                label,
                CapabilityStatus.UNKNOWN,
                reason=f"检查过程异常，无法确认状态：{type(exc).__name__}",
                detail={"error": str(exc)[:200]},
                checked_at=checked_at,
            )

    capabilities: List[CapabilityInfo] = []
    capabilities.append(await _safe("database", _check_database(db)))
    capabilities.append(await _safe("model.llm", _check_model_llm(llm_state)))
    capabilities.append(await _safe("document.parser.text", _check_text_parser()))
    capabilities.append(await _safe("document.parser.pdf", _check_pdf_parser()))
    capabilities.append(await _safe("document.parser.docx", _check_docx_parser()))
    capabilities.append(await _safe("retrieval.vector", _check_vector_retrieval()))
    capabilities.append(await _safe("sources.metadata", _check_sources_metadata()))
    capabilities.append(await _safe("library.local", _check_local_library()))
    capabilities.append(await _safe("task.engine", _check_task_engine()))

    try:
        capabilities.extend(await _check_entitlements(db, user_id))
    except Exception as exc:  # pragma: no cover - 已内部兜底
        logger.warning("capability_entitlement_failed", error=str(exc))
        capabilities.extend(
            [
                _info(
                    name,
                    CapabilityStatus.UNKNOWN,
                    reason="权益检查异常。",
                    detail={"error": f"{type(exc).__name__}"},
                )
                for name in ("task.review", "task.draft_from_outline", "task.revision")
            ]
        )

    capabilities.extend(await _check_exports())
    capabilities.append(await _safe("skills", _check_skills(db)))
    capabilities.append(await _safe("code_execution", _check_code_execution(db, user_id)))
    capabilities.append(await _safe("browser_agent", _check_browser_agent()))
    capabilities.append(await _safe("chart_generation", _check_chart_generation()))

    return CapabilityResponse(
        schema_version="1.0",
        user_id=int(user_id),
        capabilities=[
            item.model_copy(update={"checked_at": checked_at}) if item.checked_at is None else item
            for item in capabilities
        ],
    )
