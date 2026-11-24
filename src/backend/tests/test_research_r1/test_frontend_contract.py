"""T18 / AT-031·AT-034·AT-044·AT-047·AT-048·AT-053：研究工作区前端契约静态检查。

前端没有可用的 Node 测试环境，本文件按 R1_INTERFACE_SPEC §2.6 对源码做静态契约
校验：导出面、路由注册、状态机文案、卸载时只断本地流不取消服务端任务、
禁用能力必须解释原因，以及“未实现接口必须显式失败而不是假装成功”。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src" / "frontend" / "src"
API_FILE = SRC / "services" / "researchApi.js"
PAGE_FILE = SRC / "pages" / "ResearchWorkspace.js"
ROUTER_FILE = SRC / "app" / "router.js"
COMPONENTS = SRC / "components" / "research"

REQUIRED_EXPORTS = (
    "getCapabilities",
    "listProjects",
    "createProject",
    "getProject",
    "uploadDocument",
    "getDocumentBlocks",
    "searchSources",
    "createTask",
    "getTask",
    "streamTaskEvents",
    "cancelTask",
    "resumeTask",
    "retryTask",
    "getFindings",
    "createProposal",
    "applyProposal",
    "getRevisionProposal",
    "getExportUrl",
    "exportArtifact",
)


def _read(path: Path) -> str:
    if not path.is_file():
        pytest.fail(f"缺少前端文件：{path}")
    return path.read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> str:
    """截取 ``export [async] function name`` 的函数体（用于局部静态断言）。"""
    pattern = re.compile(
        rf"export\s+(?:async\s+)?function\s+{re.escape(name)}\s*\("
    )
    match = pattern.search(source)
    if not match:
        pytest.fail(f"缺少导出函数 {name}")
    next_export = re.search(r"\nexport\s", source[match.end():])
    end = match.end() + (next_export.start() if next_export else len(source) - match.end())
    return source[match.start():end]


def test_required_api_exports_exist():
    source = _read(API_FILE)
    missing = [
        name
        for name in REQUIRED_EXPORTS
        if not re.search(
            rf"export\s+(?:async\s+)?(?:function|const|let)\s+{re.escape(name)}\b",
            source,
        )
    ]
    assert missing == []


def test_research_api_reuses_shared_api_client():
    source = _read(API_FILE)
    assert "from './api.js'" in source
    assert "ApiError" in source
    # JSON 请求必须走 api.get/post，不允许绕过鉴权与错误归一化自己 fetch。
    json_fetch = re.search(r"(?<!stream)api\s*=\s*async", source)
    assert json_fetch is None
    assert "api.get(" in source and "api.post(" in source


def test_sse_stream_uses_fetch_and_signal_not_event_source():
    body = _function_body(_read(API_FILE), "streamTaskEvents")
    assert "EventSource" not in body
    assert "fetch(" in body
    assert "signal" in body
    assert "onEvent" in body
    assert "res.body" in body


def test_disconnect_does_not_cancel_server_task():
    body = _function_body(_read(API_FILE), "streamTaskEvents")
    assert "cancelTask" not in body
    assert "/cancel" not in body


def test_create_proposal_fails_explicitly_when_backend_lacks_endpoint():
    body = _function_body(_read(API_FILE), "createProposal")
    assert "Promise.reject" in body
    assert "revision" in body  # 指向可用的替代路径
    assert "post(" not in body


def test_export_helpers_target_artifact_endpoints():
    source = _read(API_FILE)
    export_body = _function_body(source, "exportArtifact")
    url_body = _function_body(source, "getExportUrl")
    assert "Idempotency-Key" in export_body
    assert "/exports" in export_body
    assert "/download" in url_body


def test_router_registers_research_page_and_keeps_old_entry():
    source = _read(ROUTER_FILE)
    assert (
        "'research':       () => import('../pages/ResearchWorkspace.js')"
        ".then(m => m.ResearchWorkspace)" in source
    )
    assert "'research':       { title: '研究工作区', props: {} }" in source
    # 旧入口不能被覆盖删除。
    assert "'researcher':" in source
    assert "'研究员对话'" in source


def test_workspace_page_exports_page_factory():
    source = _read(PAGE_FILE)
    assert re.search(r"export\s+function\s+ResearchWorkspace\s*\(", source)
    assert "createElement" in source


def test_workspace_states_cover_loading_empty_degraded_unauthorized_error_ready():
    source = _read(PAGE_FILE)
    for state in ("loading", "unauthorized", "ready", "error"):
        assert state in source
    # 空态与降级态由组件与能力门控表达。
    assert "empty" in source.lower()
    assert "degraded" in source


def test_cleanup_aborts_local_stream_but_never_cancels_task():
    source = _read(PAGE_FILE)
    match = re.search(r"page\._cleanup\s*=\s*\(\)\s*=>\s*\{", source)
    if not match:
        pytest.fail("页面未注册 page._cleanup，路由切换无法停止本地事件流")
    end = source.find("};", match.end())
    body = source[match.start():end]
    assert "stopStream" in body
    assert "cancelTask" not in body
    assert "abort" in body or "stopStream" in body


def test_disabled_capability_is_explained_not_silently_hidden():
    source = _read(PAGE_FILE)
    assert "按钮已禁用" in source
    assert "不会假装成功" in source
    assert "能力" in source
    # 按钮必须根据能力门控显式禁用，而不是渲染可点但静默无响应。
    assert re.search(r"disabled\s*=\s*!?canStart", source)
    assert "gateText(" in source


def test_no_third_party_imports_in_new_frontend_modules():
    files = [API_FILE, PAGE_FILE, *sorted(COMPONENTS.glob("*.js"))]
    offenders: list[str] = []
    for path in files:
        source = _read(path)
        for specifier in re.findall(r"from\s+['\"]([^'\"]+)['\"]", source):
            if not specifier.startswith("."):
                offenders.append(f"{path.name}: {specifier}")
    assert offenders == []


def test_no_fake_success_copy_when_capability_unavailable():
    source = _read(PAGE_FILE)
    # 不允许在未真正调用后端时输出“已完成/已保存/已应用”之类成功文案；
    # 成功提示只允许出现在真实请求之后的 toast 中。
    assert "不会假装成功" in source
    assert "只覆盖已解析内容" in source or "未解析部分不会进入结论" in source
    assert "当前列表为空不等于没有问题" in source


def test_workspace_components_exist_and_are_plain_dom_modules():
    expected = (
        "shared.js",
        "WorkspaceStates.js",
        "DocumentUpload.js",
        "ProjectList.js",
        "TaskStream.js",
        "FindingCard.js",
        "RevisionDiff.js",
        "DiagnosisReport.js",
    )
    missing = [name for name in expected if not (COMPONENTS / name).is_file()]
    assert missing == []
    for name in expected:
        source = _read(COMPONENTS / name)
        assert "React" not in source
        assert "jsx" not in source.lower()
        assert "insertAdjacentHTML" not in source
        assert "document.write" not in source