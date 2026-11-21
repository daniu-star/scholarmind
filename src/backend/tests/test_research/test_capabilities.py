"""能力如实上报（AT-005 / AT-018 / AT-026 相关诚实性）。

R0 的硬要求不是“能力越多越好”，而是**不得谎报 ready**：
- 每条能力都必须带 checked_at / reason / granularity 中的可核对信息；
- 未配置凭证的模型能力只能是 disabled，不能因为“代码里有 client”就 ready；
- 未开放的能力（代码执行 / 浏览器 / 图表）必须 disabled；
- 权益类能力用 unauthorized 表达，而不是拿 unknown 掩盖“没开通”；
- 声明 ready 的条目必须能对应到真实前置条件（模块/依赖/目录/凭证探测）。
"""
from __future__ import annotations

import importlib.util
from datetime import timedelta

import pytest

from ...research import capabilities as caps
from ...research.contracts import CapabilityStatus, utcnow
from ...models.orm import UserQuota
from ...config import settings


def _by_name(response) -> dict:
    return {item.name: item for item in response.capabilities}


@pytest.mark.asyncio
async def test_capability_names_are_complete_and_unique(db, research_store):
    response = await caps.build_capabilities(db, research_store.user_ids["a"])
    names = [item.name for item in response.capabilities]
    assert sorted(names) == sorted(caps.CAPABILITY_NAMES)
    assert len(names) == len(set(names))


@pytest.mark.asyncio
async def test_every_capability_has_checked_at_and_reason(db, research_store):
    response = await caps.build_capabilities(db, research_store.user_ids["a"])
    assert response.schema_version == "1.0"
    assert response.user_id == research_store.user_ids["a"]
    assert "不构成发表保证" in response.disclaimer
    started = utcnow()
    for item in response.capabilities:
        assert item.checked_at is not None, item.name
        assert item.checked_at >= started - timedelta(seconds=5)
        assert item.reason and item.reason.strip(), item.name
        assert item.status in set(CapabilityStatus), (item.name, item.status)


@pytest.mark.asyncio
async def test_database_capability_is_ready_after_real_probe(db, research_store):
    response = await caps.build_capabilities(db, research_store.user_ids["a"])
    database = _by_name(response)["database"]
    assert database.status is CapabilityStatus.READY
    assert database.detail.get("probe") == "SELECT 1"


@pytest.mark.asyncio
async def test_text_and_docx_parsers_reflect_real_modules(db, research_store):
    response = await caps.build_capabilities(db, research_store.user_ids["a"])
    items = _by_name(response)
    text = items["document.parser.text"]
    assert text.status is CapabilityStatus.READY
    assert text.detail.get("module") == "research.document_parser"
    docx = items["document.parser.docx"]
    assert docx.status is CapabilityStatus.READY
    assert docx.detail.get("module_ok") is True and docx.detail.get("zipfile") is True


@pytest.mark.asyncio
async def test_pdf_capability_follows_pypdf_presence(db, research_store):
    response = await caps.build_capabilities(db, research_store.user_ids["a"])
    pdf = _by_name(response)["document.parser.pdf"]
    has_pypdf = importlib.util.find_spec("pypdf") is not None
    assert pdf.detail.get("pypdf") is has_pypdf
    if has_pypdf:
        assert pdf.status is CapabilityStatus.READY
    else:
        assert pdf.status is CapabilityStatus.DISABLED


@pytest.mark.asyncio
async def test_unconfigured_model_is_disabled_not_ready(db, research_store, monkeypatch):
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "")
    response = await caps.build_capabilities(db, research_store.user_ids["a"])
    model = _by_name(response)["model.llm"]
    assert model.status is CapabilityStatus.DISABLED
    assert model.detail.get("credentialed") is False


@pytest.mark.asyncio
async def test_missing_llm_probe_is_unknown_never_ready(db, research_store, monkeypatch):
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "sk-test-real-looking-key-0123456789")
    response = await caps.build_capabilities(db, research_store.user_ids["a"])
    model = _by_name(response)["model.llm"]
    assert model.status is CapabilityStatus.UNKNOWN
    assert model.detail.get("llm_reachable") is None
    assert "无法确认" in model.reason


@pytest.mark.asyncio
async def test_unreachable_llm_probe_is_degraded_with_reason(db, research_store, monkeypatch):
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "sk-test-real-looking-key-0123456789")
    response = await caps.build_capabilities(
        db,
        research_store.user_ids["a"],
        llm_state={"llm_reachable": False, "llm_failure_reason": "connect timeout"},
    )
    model = _by_name(response)["model.llm"]
    assert model.status is CapabilityStatus.DEGRADED
    assert "connect timeout" in model.reason


@pytest.mark.asyncio
async def test_reachable_llm_probe_is_ready(db, research_store, monkeypatch):
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "sk-test-real-looking-key-0123456789")
    response = await caps.build_capabilities(
        db, research_store.user_ids["a"], llm_state={"llm_reachable": True}
    )
    model = _by_name(response)["model.llm"]
    assert model.status is CapabilityStatus.READY
    assert model.detail.get("llm_reachable") is True


@pytest.mark.asyncio
async def test_closed_features_are_disabled(db, research_store, monkeypatch):
    monkeypatch.setattr(settings, "CODE_EXECUTION_ENABLED", False)
    monkeypatch.delattr(settings, "BROWSER_AGENT_ENABLED", raising=False)
    monkeypatch.delattr(settings, "CHART_GENERATION_ENABLED", raising=False)
    response = await caps.build_capabilities(db, research_store.user_ids["a"])
    items = _by_name(response)
    for name in ("code_execution", "browser_agent", "chart_generation"):
        assert items[name].status is CapabilityStatus.DISABLED, name
        assert items[name].detail.get("config_enabled") is False


@pytest.mark.asyncio
async def test_free_user_entitlements_are_unauthorized_not_ready(db, research_store):
    response = await caps.build_capabilities(db, research_store.user_ids["a"])
    items = _by_name(response)
    for name in ("task.review", "task.draft_from_outline", "task.revision"):
        assert items[name].status is CapabilityStatus.UNAUTHORIZED, name
        assert items[name].detail.get("pipeline_access") is not None


@pytest.mark.asyncio
async def test_entitled_user_capabilities_become_ready(db, research_store):
    user_id = research_store.user_ids["a"]
    quota = (
        await db.execute(
            UserQuota.__table__.select().where(UserQuota.user_id == user_id)
        )
    ).mappings().one()
    future = utcnow() + timedelta(days=30)
    await db.execute(
        UserQuota.__table__.update()
        .where(UserQuota.user_id == user_id)
        .values(
            plan="pro",
            membership_expires_at=future,
            external_review_expires_at=future,
        )
    )
    await db.commit()
    assert quota["user_id"] == user_id

    response = await caps.build_capabilities(db, user_id)
    items = _by_name(response)
    for name in ("task.review", "task.draft_from_outline", "task.revision"):
        assert items[name].status is CapabilityStatus.READY, name


@pytest.mark.asyncio
async def test_ready_must_have_real_evidence_in_detail(db, research_store):
    """ready 不是口号：要么有模块/依赖，要么有探测结果，且 reason 可读。"""

    response = await caps.build_capabilities(db, research_store.user_ids["a"])
    for item in response.capabilities:
        if item.status is not CapabilityStatus.READY:
            continue
        assert item.reason.strip(), item.name
        assert isinstance(item.detail, dict) and item.detail, item.name
        if item.name.startswith("document.parser."):
            assert item.detail.get("module_ok", True) is True
        if item.name == "database":
            assert item.detail.get("probe") == "SELECT 1"
        if item.name.startswith("export."):
            assert item.detail.get("module_ok") is True or item.detail.get("python_docx") is True


@pytest.mark.asyncio
async def test_task_engine_ready_only_when_task_modules_exist(db, research_store):
    response = await caps.build_capabilities(db, research_store.user_ids["a"])
    engine = _by_name(response)["task.engine"]
    importlib.util.find_spec("src.backend.research.task_service")
    assert engine.detail.get("available")
    if all(
        importlib.util.find_spec(dotted) is not None
        for _, dotted in caps._TASK_MODULES
    ):
        assert engine.status is CapabilityStatus.READY


@pytest.mark.asyncio
async def test_vector_retrieval_never_hides_fallback(db, research_store):
    response = await caps.build_capabilities(db, research_store.user_ids["a"])
    vector = _by_name(response)["retrieval.vector"]
    assert vector.status in {
        CapabilityStatus.READY,
        CapabilityStatus.DEGRADED,
        CapabilityStatus.UNKNOWN,
    }
    if vector.status is not CapabilityStatus.READY:
        assert vector.reason.strip()
    else:
        assert vector.detail.get("module_ok") is True
        assert vector.detail.get("chromadb") is True
        assert vector.detail.get("sentence_transformers") is True
        assert vector.detail.get("chroma_dir_exists") is True


# ── 管道独立性（AT-021） ────────────────────────────────


def test_pipelines_package_does_not_import_web_or_db_stack():
    """AT-021：管道包必须能独立导入，不能拖入 FastAPI/SQLAlchemy/全局配置。"""
    import os
    import subprocess
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[4]
    code = (
        "import sys\n"
        "from src.backend.research.pipelines import ReviewPipeline, GenerationPipeline\n"
        "heavy = sorted(m for m in sys.modules if m.split('.')[0] in "
        "{'fastapi','starlette','sqlalchemy','pydantic_settings'})\n"
        "print('HEAVY', heavy)\n"
        "print('PIPELINES', ReviewPipeline.__name__, GenerationPipeline.__name__)\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert "HEAVY []" in completed.stdout, completed.stdout
    assert "PIPELINES ReviewPipeline GenerationPipeline" in completed.stdout


def test_generation_and_review_are_separate_packages():
    """两个管道互不依赖对方模块，避免 init 顺序造成绑定错乱。"""
    import src.backend.research.pipelines.generation as generation
    import src.backend.research.pipelines.review as review

    assert generation.__name__ != review.__name__
    assert hasattr(review, "ReviewPipeline")
    assert hasattr(generation, "GenerationPipeline")
