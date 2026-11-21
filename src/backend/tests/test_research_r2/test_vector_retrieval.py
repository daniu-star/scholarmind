"""研究域私有检索的向量后端（FR-05）验收。

覆盖三件事：

1. **默认诚实**：未配置 ``RESEARCH_EMBEDDING_MODEL`` 时检索必须走词法并可解释
   （``retrieval_method="lexical"``、``degraded=True``、``degraded_reason`` 非空）。
2. **注入即生效**：注入 provider 后同一范围改用余弦，``retrieval_method="vector"``；
   provider 抛 ``EmbeddingUnavailable`` 时降级为词法并保留机器可读原因。
3. **能力如实**：``/capabilities`` 的 ``retrieval.vector`` 在未配置时是 DEGRADED，
   只有本机缓存了模型才 READY；真实模型能编码出归一化向量且语义相近的更相似。

真实模型用例在本机没有缓存时自动跳过（CI 无模型目录也不假装通过）。
"""

from __future__ import annotations

import pytest

from ...research import capabilities as caps
from ...research import retrieval_service as retrieval
from ...research.capabilities import CapabilityStatus
from ...research.contracts import Actor
from ...research.embeddings import (
    EmbeddingUnavailable,
    SentenceTransformerEmbeddingProvider,
    local_model_available,
)
from .conftest import create_project, patch_switch, upload_document, version_id_of

LOCAL_MODEL = "BAAI/bge-small-zh-v1.5"
LOCAL_MODEL_READY = local_model_available(LOCAL_MODEL)
skip_without_model = pytest.mark.skipif(
    not LOCAL_MODEL_READY, reason=f"本机没有缓存的 embedding 模型 {LOCAL_MODEL}"
)

DOC_TEXT = """# 引言

平台算法改变了新闻消费的入口，推荐系统决定了用户看到什么。

# 方法

研究采用问卷与日志结合的混合设计，样本来自 1200 名用户。

# 结论

算法可见性影响信息接触结构，需要进一步检验其长期效应。
"""


async def _version_id(client, db, who: str = "a") -> str:
    project_id = await create_project(client, "向量检索验收项目")
    payload = await upload_document(
        client, project_id, filename="vector.md", text=DOC_TEXT, mime="text/markdown"
    )
    return version_id_of(payload)


def _chr_vector(text: str) -> list[float]:
    """确定性"伪向量"：按字符计数，仅用于验证注入链路与排序方向。"""

    counts = [float(text.count(ch)) for ch in "平台算法推荐新闻消费问卷日志结论"]
    counts.append(1.0)
    return counts


# ── 1. 默认诚实降级 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_lexical_fallback_is_labeled_when_no_model_configured(
    db, client_a, research_env, monkeypatch
):
    retrieval.reset_embedding_provider()
    patch_switch(monkeypatch, "RESEARCH_EMBEDDING_MODEL", None)
    version_id = await _version_id(client_a, db)

    results = await retrieval.search(
        db, research_env.actor("a"), version_id, "平台算法与新闻消费", limit=3
    )

    assert results, "词法检索至少应命中文档正文"
    assert all(item["retrieval_method"] == "lexical" for item in results)
    assert all(item["degraded"] is True for item in results)
    assert all(item["degraded_reason"] for item in results)
    retrieval.reset_embedding_provider()


# ── 2. 注入 provider ────────────────────────────────────────


@pytest.mark.asyncio
async def test_injected_provider_switches_to_vector(db, client_a, research_env):
    version_id = await _version_id(client_a, db)
    retrieval.configure_embedding_provider(lambda texts: [_chr_vector(t) for t in texts])
    try:
        results = await retrieval.search(
            db, research_env.actor("a"), version_id, "平台算法与新闻消费", limit=3
        )
    finally:
        retrieval.reset_embedding_provider()

    assert results
    assert all(item["retrieval_method"] == "vector" for item in results)
    assert all(item["degraded"] is False for item in results)
    assert all(item["degraded_reason"] is None for item in results)
    # 余弦分数在 [0, 1] 内且已按降序排列
    scores = [item["score"] for item in results]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= score <= 1.0 for score in scores)


@pytest.mark.asyncio
async def test_provider_failure_degrades_lexically_with_reason(
    db, client_a, research_env
):
    version_id = await _version_id(client_a, db)

    def broken(_texts):
        raise EmbeddingUnavailable("embedding_model_not_cached", "模型未缓存")

    retrieval.configure_embedding_provider(broken)
    try:
        results = await retrieval.search(
            db, research_env.actor("a"), version_id, "平台算法与新闻消费", limit=3
        )
    finally:
        retrieval.reset_embedding_provider()

    assert results
    assert all(item["retrieval_method"] == "lexical" for item in results)
    assert all(item["degraded"] is True for item in results)
    assert all(
        "embedding_model_not_cached" in (item["degraded_reason"] or "")
        for item in results
    )


# ── 3. 能力如实 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_capability_reports_lexical_when_model_missing(
    db, research_env, monkeypatch
):
    patch_switch(monkeypatch, "RESEARCH_EMBEDDING_MODEL", None)
    response = await caps.build_capabilities(db, research_env.user_ids["a"])
    entry = {item.name: item for item in response.capabilities}["retrieval.vector"]

    assert entry.status is CapabilityStatus.DEGRADED
    assert "词法" in entry.reason
    assert entry.detail.get("embedding_model_configured") is None
    assert entry.detail.get("backend") == "lexical"


@skip_without_model
@pytest.mark.asyncio
async def test_capability_ready_when_local_model_configured(
    db, research_env, monkeypatch
):
    patch_switch(monkeypatch, "RESEARCH_EMBEDDING_MODEL", LOCAL_MODEL)
    patch_switch(monkeypatch, "RESEARCH_EMBEDDING_ALLOW_DOWNLOAD", False)
    response = await caps.build_capabilities(db, research_env.user_ids["a"])
    entry = {item.name: item for item in response.capabilities}["retrieval.vector"]

    assert entry.status is CapabilityStatus.READY
    assert entry.detail.get("embedding_model_configured") == LOCAL_MODEL
    assert entry.detail.get("embedding_model_local") is True
    assert entry.detail.get("backend") == "sentence-transformers"


# ── 4. 真实本地模型 ────────────────────────────────────────


@skip_without_model
def test_local_model_encodes_normalized_vectors_with_semantic_order():
    provider = SentenceTransformerEmbeddingProvider(LOCAL_MODEL, batch_size=8)
    vectors = provider(
        [
            "平台算法如何改变新闻消费的入口",
            "推荐系统决定了用户看到哪些新闻",
            "本机风扇转速与室温的关系",
        ]
    )

    assert len(vectors) == 3
    dims = {len(vector) for vector in vectors}
    assert len(dims) == 1 and dims.pop() > 0
    # 归一化向量：模长 ≈ 1
    norm = sum(value * value for value in vectors[0]) ** 0.5
    assert norm == pytest.approx(1.0, abs=1e-3)

    def cosine(left, right):
        return sum(a * b for a, b in zip(left, right))

    related = cosine(vectors[0], vectors[1])
    unrelated = cosine(vectors[0], vectors[2])
    assert related > unrelated, "语义相近的句子应当更相似"
    assert related > 0.5


@skip_without_model
@pytest.mark.asyncio
async def test_configure_from_settings_uses_local_model(
    db, client_a, research_env, monkeypatch
):
    patch_switch(monkeypatch, "RESEARCH_EMBEDDING_MODEL", LOCAL_MODEL)
    provider = retrieval.configure_from_settings()
    try:
        assert provider is not None
        version_id = await _version_id(client_a, db)
        results = await retrieval.search(
            db, research_env.actor("a"), version_id, "平台算法与新闻消费", limit=3
        )
        assert results
        assert all(item["retrieval_method"] == "vector" for item in results)
        assert all(item["degraded"] is False for item in results)
    finally:
        retrieval.reset_embedding_provider()


def _actorless_smoke() -> None:
    """保持 import 有意义：Actor 在类型提示里使用。"""

    assert Actor(user_id=1, role="user") is not None


# ── 5. HTTP 端点（POST /documents/{id}/search）────────────


@pytest.mark.asyncio
async def test_search_endpoint_labels_lexical_by_default(client_a, db, monkeypatch):
    from .conftest import modules_named, patch_switch

    patch_switch(monkeypatch, "RESEARCH_EMBEDDING_MODEL", None)
    for module in modules_named("research.retrieval_service"):
        module.reset_embedding_provider()

    project_id = await create_project(client_a, "检索端点验收项目")
    payload = await upload_document(
        client_a, project_id, filename="endpoint.md", text=DOC_TEXT, mime="text/markdown"
    )
    document_id = payload.get("document", {}).get("id") or payload.get("id")
    assert document_id

    response = await client_a.post(
        f"/api/v1/research/documents/{document_id}/search",
        json={"query": "平台算法与新闻消费", "limit": 3},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["retrieval_method"] == "lexical"
    assert body["degraded"] is True
    assert body["degraded_reason"]
    assert body["items"] and all(
        item["retrieval_method"] == "lexical" for item in body["items"]
    )


@pytest.mark.asyncio
async def test_search_endpoint_uses_vector_when_provider_injected(client_a, db):
    from .conftest import modules_named

    modules = modules_named("research.retrieval_service")
    assert modules, "检索模块应已随应用加载"
    for module in modules:
        module.configure_embedding_provider(
            lambda texts: [_chr_vector(t) for t in texts]
        )
    try:
        project_id = await create_project(client_a, "检索端点向量项目")
        payload = await upload_document(
            client_a,
            project_id,
            filename="endpoint-vector.md",
            text=DOC_TEXT,
            mime="text/markdown",
        )
        document_id = payload.get("document", {}).get("id") or payload.get("id")
        response = await client_a.post(
            f"/api/v1/research/documents/{document_id}/search",
            json={"query": "平台算法与新闻消费", "limit": 3},
        )
    finally:
        for module in modules:
            module.reset_embedding_provider()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["retrieval_method"] == "vector"
    assert body["degraded"] is False
    assert body["degraded_reason"] is None
    assert body["items"]

