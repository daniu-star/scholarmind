"""T13 / AT-018·AT-019·AT-020·AT-049：来源与证据的诚实性不变量。

覆盖 R1_INTERFACE_SPEC §2.4：
- 无适配器时只做本库词法检索，并显式 degraded；
- 适配器只能补全提供方真实返回的字段，不得覆盖用户原文、不得补造作者/年份/DOI；
- 适配器失败/无结果时来源为 ``unresolved``，用户输入逐字进入 ``unresolved``；
- 只有摘要或元数据时不允许声称支持原文（AT-020）；
- URL 只允许安全 HTTP(S)，私网/回环/凭据/``file:`` 一律拒绝（AT-049）；
- 用户已有引用解析不到时保留原文，绝不替换。
"""
from __future__ import annotations

import pytest

from ...research import evidence_service, source_adapters
from ...research.contracts import Actor, new_id
from ...research.errors import ResearchAPIError
from ...research.models import Project, ResearchTask

pytestmark = pytest.mark.asyncio


class _StubAdapter:
    """可控的离线适配器：记录调用，返回固定结果或抛错。"""

    def __init__(self, name: str = "stub", *, results=None, error: Exception | None = None):
        self.name = name
        self.results = list(results or [])
        self.error = error
        self.calls: list[tuple[str, int]] = []

    async def lookup(self, query: str, *, limit: int = 10):
        self.calls.append((query, limit))
        if self.error is not None:
            raise self.error
        return list(self.results)


def _adapter_result(**overrides) -> dict:
    payload = {
        "title": "Adapter Title",
        "authors": "Ada Lovelace",
        "year": 2024,
        "doi": "10.1234/adapter",
        "url": "https://example.org/adapter",
        "provider": "stub",
        "metadata_status": "resolved",
        "material_level": "metadata",
    }
    payload.update(overrides)
    return payload


@pytest.fixture(autouse=True)
def _isolate_registry():
    source_adapters.reset_adapters()
    yield
    source_adapters.reset_adapters()


async def _project(db, owner_id: int) -> Project:
    project = Project(id=new_id("rproj"), owner_id=owner_id, title="来源验证项目")
    db.add(project)
    await db.flush()
    return project


async def _task(db, owner_id: int, project_id: str, task_id: str = "rtask_src") -> ResearchTask:
    task = ResearchTask(
        id=task_id,
        owner_id=owner_id,
        project_id=project_id,
        kind="review",
        objective="来源验证",
        billing_group_id="bg_src",
    )
    db.add(task)
    await db.flush()
    return task


class TestSourceHonesty:
    async def test_title_only_source_is_unresolved(self, db, research_store):
        project = await _project(db, research_store.user_ids["a"])
        actor = research_store.actor("a")

        result = await evidence_service.create_source(
            db, actor, project.id, {"title": "用户手填标题"}
        )

        assert result["title"] == "用户手填标题"
        assert result["metadata_status"] == "unresolved"
        assert result["material_level"] == "metadata"
        assert result["authors"] == ""
        assert result["year"] is None
        assert result["doi"] is None
        assert result["url"] is None
        assert result["provider"] == "manual"

    async def test_registered_adapter_fills_only_provider_fields(self, db, research_store):
        project = await _project(db, research_store.user_ids["a"])
        adapter = _StubAdapter(results=[_adapter_result()])
        source_adapters.register_adapter(adapter)

        result = await evidence_service.create_source(
            db, research_store.actor("a"), project.id, {"doi": "10.1234/adapter"}
        )

        assert adapter.calls and adapter.calls[0][0] == "10.1234/adapter"
        assert result["title"] == "Adapter Title"
        assert result["authors"] == "Ada Lovelace"
        assert result["year"] == 2024
        assert result["doi"] == "10.1234/adapter"
        assert result["metadata_status"] == "resolved"
        assert result["resolution"]["adapter"] == "stub"

    async def test_adapter_cannot_overwrite_user_title(self, db, research_store):
        project = await _project(db, research_store.user_ids["a"])
        source_adapters.register_adapter(
            _StubAdapter(results=[_adapter_result(title="Provider Title")])
        )

        result = await evidence_service.create_source(
            db,
            research_store.actor("a"),
            project.id,
            {"title": "用户自己的标题", "doi": "10.1234/adapter"},
        )

        assert result["title"] == "用户自己的标题"

    async def test_adapter_failure_degrades_without_fabrication(self, db, research_store):
        project = await _project(db, research_store.user_ids["a"])
        source_adapters.register_adapter(
            _StubAdapter(error=RuntimeError("provider is down"))
        )

        result = await evidence_service.create_source(
            db, research_store.actor("a"), project.id, {"query": "某条不确定的引用"}
        )

        assert result["title"] == "某条不确定的引用"
        assert result["metadata_status"] == "unresolved"
        assert result["authors"] == ""
        assert result["year"] is None
        assert result["doi"] is None
        assert result["unresolved"] == ["某条不确定的引用"]
        assert "provider is down" in (result["resolution"]["error"] or "")

    async def test_adapter_no_result_keeps_user_identifier(self, db, research_store):
        project = await _project(db, research_store.user_ids["a"])
        source_adapters.register_adapter(_StubAdapter(results=[]))

        result = await evidence_service.create_source(
            db, research_store.actor("a"), project.id, {"doi": "10.9999/not-found"}
        )

        assert result["title"] == "10.9999/not-found"
        assert result["metadata_status"] == "unresolved"
        assert result["unresolved"] == ["10.9999/not-found"]

    async def test_adapter_unsafe_url_is_dropped_but_source_saved(self, db, research_store):
        project = await _project(db, research_store.user_ids["a"])
        source_adapters.register_adapter(
            _StubAdapter(
                results=[_adapter_result(url="http://127.0.0.1/admin", doi="10.1234/x")]
            )
        )

        result = await evidence_service.create_source(
            db, research_store.actor("a"), project.id, {"doi": "10.1234/x"}
        )

        assert result["url"] is None
        assert result["title"] == "Adapter Title"

    async def test_abstract_only_source_is_marked_abstract(self, db, research_store):
        project = await _project(db, research_store.user_ids["a"])
        source_adapters.register_adapter(
            _StubAdapter(
                results=[_adapter_result(abstract="Only the abstract is available.")]
            )
        )

        result = await evidence_service.create_source(
            db, research_store.actor("a"), project.id, {"doi": "10.1234/adapter"}
        )

        assert result["material_level"] == "abstract"
        assert result["abstract_available"] is True

    async def test_same_doi_is_deduplicated(self, db, research_store):
        project = await _project(db, research_store.user_ids["a"])
        actor = research_store.actor("a")
        payload = {"title": "可去重来源", "doi": "10.1234/dup"}

        first = await evidence_service.create_source(db, actor, project.id, payload)
        second = await evidence_service.create_source(db, actor, project.id, payload)

        assert second["id"] == first["id"]
        assert second["deduplicated"] is True


class TestSourceUrlSafety:
    @pytest.mark.parametrize(
        "url",
        [
            "file:///C:/Windows/win.ini",
            "ftp://example.org/data",
            "http://localhost/admin",
            "http://127.0.0.1/admin",
            "http://10.0.0.5/internal",
            "http://169.254.169.254/latest/meta-data",
            "https://user:pass@example.org/x",
            "http://[::1]/admin",
        ],
    )
    async def test_unsafe_urls_are_rejected(self, db, research_store, url):
        project = await _project(db, research_store.user_ids["a"])

        with pytest.raises(ResearchAPIError) as excinfo:
            await evidence_service.create_source(
                db,
                research_store.actor("a"),
                project.id,
                {"title": "危险来源", "url": url},
            )

        assert excinfo.value.code == "UNSAFE_SOURCE_URL"
        assert excinfo.value.status_code == 422

    async def test_public_https_url_is_kept(self, db, research_store):
        project = await _project(db, research_store.user_ids["a"])

        result = await evidence_service.create_source(
            db,
            research_store.actor("a"),
            project.id,
            {"title": "公开来源", "url": "https://example.org/paper?id=1"},
        )

        assert result["url"] == "https://example.org/paper?id=1"


class TestCitationResolution:
    async def test_unresolved_citations_keep_user_text_verbatim(self, db, research_store):
        class _OnlyGoodDoi:
            name = "stub"

            async def lookup(self, query, *, limit=10):
                if "10.1234/good" in query:
                    return [_adapter_result(doi="10.1234/good")]
                return []

        source_adapters.register_adapter(_OnlyGoodDoi())
        citations = [
            "10.1234/good",
            "张志强. 不存在的文献[J]. 2020, 1(1): 1-10.",
        ]

        report = await evidence_service.resolve_citations(citations)

        assert report["degraded"] is False
        assert report["citations"][0]["resolved"] is True
        assert report["citations"][0]["raw"] == "10.1234/good"
        assert report["citations"][1]["resolved"] is False
        assert report["citations"][1]["raw"] == citations[1]
        assert report["unresolved"] == [citations[1]]

    async def test_without_adapters_everything_is_degraded_and_verbatim(self):
        citations = ["10.9999/none", "Some Missing Paper (1999)"]

        report = await evidence_service.resolve_citations(citations)

        assert report["degraded"] is True
        assert report["unresolved"] == citations
        assert [item["raw"] for item in report["citations"]] == citations
        assert all(item["resolved"] is False for item in report["citations"])

    async def test_citation_dict_preserves_raw_and_uses_doi_query(self, db, research_store):
        seen: list[str] = []

        class _Recorder:
            name = "stub"

            async def lookup(self, query, *, limit=10):
                seen.append(query)
                return []

        source_adapters.register_adapter(_Recorder())

        report = await evidence_service.resolve_citations(
            [{"raw": "原始引用文本", "doi": "10.1234/q"}]
        )

        assert seen == ["10.1234/q"]
        assert report["citations"][0]["raw"] == "原始引用文本"
        assert report["unresolved"] == ["原始引用文本"]


class TestSearchAndStatus:
    async def test_search_without_match_returns_empty_list(self, db, research_store):
        project = await _project(db, research_store.user_ids["a"])

        results = await evidence_service.search_sources(
            db, research_store.actor("a"), project.id, "不存在的关键词"
        )

        assert results == []

    async def test_search_finds_saved_source_and_marks_degraded(self, db, research_store):
        project = await _project(db, research_store.user_ids["a"])
        actor = research_store.actor("a")
        await evidence_service.create_source(
            db, actor, project.id, {"title": "深度学习在教育中的应用"}
        )

        results = await evidence_service.search_sources(
            db, actor, project.id, "深度学习"
        )

        assert len(results) == 1
        assert results[0]["title"] == "深度学习在教育中的应用"
        assert results[0]["degraded"] is True
        assert results[0]["degraded_reason"] == evidence_service.EXTERNAL_SOURCE_UNAVAILABLE

    async def test_external_status_reflects_registry(self):
        empty = evidence_service.external_source_status()
        assert empty["degraded"] is True
        assert empty["providers"] == []

        source_adapters.register_adapter(_StubAdapter(name="doi"))
        ready = evidence_service.external_source_status()

        assert ready["degraded"] is False
        assert ready["providers"] == ["doi"]


class TestEvidenceMaterialHonesty:
    async def _source(
        self, db, actor: Actor, project_id: str, *, material_level: str, title: str = "来源"
    ) -> dict:
        return await evidence_service.create_source(
            db,
            actor,
            project_id,
            {"title": title, "material_level": material_level},
        )

    async def _evidence(self, db, actor, task_id, source_id, **overrides):
        payload = {
            "source_id": source_id,
            "quote": "原文摘录",
            "metadata_status": "resolved",
            "material_level": "abstract",
            "support_status": "insufficient",
            "verification_method": "model",
        }
        payload.update(overrides)
        return await evidence_service.create_evidence(db, actor, task_id, payload)

    async def test_abstract_cannot_support_original_claim(self, db, research_store):
        project = await _project(db, research_store.user_ids["a"])
        actor = research_store.actor("a")
        await _task(db, actor.user_id, project.id)
        source = await self._source(
            db, actor, project.id, material_level="abstract", title="只有摘要"
        )

        with pytest.raises(ResearchAPIError) as excinfo:
            await self._evidence(
                db, actor, "rtask_src", source["id"], support_status="supported"
            )

        assert excinfo.value.code == "EVIDENCE_UNSUPPORTED_MATERIAL"

    async def test_evidence_cannot_claim_stronger_material_than_source(
        self, db, research_store
    ):
        project = await _project(db, research_store.user_ids["a"])
        actor = research_store.actor("a")
        await _task(db, actor.user_id, project.id)
        source = await self._source(
            db, actor, project.id, material_level="abstract", title="只有摘要"
        )

        with pytest.raises(ResearchAPIError) as excinfo:
            await self._evidence(
                db,
                actor,
                "rtask_src",
                source["id"],
                material_level="full_text",
                support_status="insufficient",
            )

        assert excinfo.value.code == "EVIDENCE_MATERIAL_CONFLICT"

    async def test_supported_requires_a_verification_method(self, db, research_store):
        project = await _project(db, research_store.user_ids["a"])
        actor = research_store.actor("a")
        await _task(db, actor.user_id, project.id)
        source = await self._source(
            db, actor, project.id, material_level="full_text", title="全文来源"
        )

        with pytest.raises(ResearchAPIError) as excinfo:
            await self._evidence(
                db,
                actor,
                "rtask_src",
                source["id"],
                material_level="full_text",
                support_status="supported",
                verification_method="none",
            )

        assert excinfo.value.code == "EVIDENCE_UNVERIFIED"

    async def test_fulltext_supported_evidence_is_accepted(self, db, research_store):
        project = await _project(db, research_store.user_ids["a"])
        actor = research_store.actor("a")
        await _task(db, actor.user_id, project.id)
        source = await self._source(
            db, actor, project.id, material_level="full_text", title="全文来源"
        )

        result = await self._evidence(
            db,
            actor,
            "rtask_src",
            source["id"],
            material_level="full_text",
            support_status="supported",
            verification_method="human",
        )

        assert result["material_level"] == "full_text"
        assert result["support_status"] == "supported"
        assert result["source_id"] == source["id"]

    async def test_missing_enums_are_rejected_before_write(self, db, research_store):
        project = await _project(db, research_store.user_ids["a"])
        actor = research_store.actor("a")
        await _task(db, actor.user_id, project.id)
        source = await self._source(db, actor, project.id, material_level="metadata")

        with pytest.raises(ResearchAPIError) as excinfo:
            await evidence_service.create_evidence(
                db,
                actor,
                "rtask_src",
                {"source_id": source["id"], "quote": "摘录"},
            )

        assert excinfo.value.code == "EVIDENCE_INCOMPLETE"
        assert set(excinfo.value.details["missing"]) == set(
            evidence_service.EVIDENCE_FIELDS
        )

    async def test_other_users_source_is_not_found(self, db, research_store):
        project = await _project(db, research_store.user_ids["b"])
        other = research_store.actor("b")
        await _task(db, research_store.user_ids["a"], project.id)
        source = await self._source(db, other, project.id, material_level="full_text")

        with pytest.raises(ResearchAPIError) as excinfo:
            await self._evidence(db, research_store.actor("a"), "rtask_src", source["id"])

        assert excinfo.value.code == "NOT_FOUND"