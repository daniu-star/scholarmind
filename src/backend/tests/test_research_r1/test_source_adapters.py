"""T13 / AT-018·AT-019：来源适配器的归一化、注册表与 DOI 解析。

验证 R1_INTERFACE_SPEC §2.4 的纯函数不变量：
- 只映射提供方真实返回的字段，缺失即空，绝不补造作者/年份/DOI；
- 只有摘要时 ``material_level="abstract"``，有 DOI 不等于读过全文；
- URL 只保留 http(s)，``file:`` 等 scheme 直接丢弃；
- 注册表同名替换、清空后可降级；
- DoiAdapter 只调用注入的 HTTP 客户端，不联网；非 DOI 查询不发请求。
"""
from __future__ import annotations

import json
import re

import pytest

from ...research import source_adapters as sa


class _GetJsonStub:
    """记录调用参数的 get_json 替身。"""

    def __init__(self, payload):
        self.payload = payload
        self.urls: list[str] = []

    async def get_json(self, url):
        self.urls.append(url)
        return self.payload


class _JsonResponse:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


class _GetStub:
    def __init__(self, response):
        self.response = response
        self.urls: list[str] = []

    async def get(self, url, headers=None):
        self.urls.append(url)
        return self.response


class _FetchStub:
    def __init__(self, payload):
        self.payload = payload

    async def fetch(self, url):
        return json.dumps(self.payload).encode("utf-8")


class _BrokenResponse:
    """既不是 dict/bytes/str，也没有 json() 的响应。"""


class _BrokenClient:
    async def get(self, url, headers=None):
        return _BrokenResponse()


class _NoTransport:
    pass


def _crossref_payload() -> dict:
    return {
        "status": "ok",
        "message": {
            "DOI": "10.1234/ABC.2024.001",
            "title": ["<i>Deep</i> Learning for Research Agents"],
            "author": [
                {"given": "Ada", "family": "Lovelace"},
                {"given": "Alan", "family": "Turing"},
            ],
            "issued": {"date-parts": [[2024, 5, 1]]},
            "URL": "https://example.org/paper",
            "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}],
            "abstract": "<jats:p>We study agents &amp; tools.</jats:p>",
        },
    }


class TestNormalizeDoi:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("10.1000/xyz123", "10.1000/xyz123"),
            ("https://doi.org/10.1000/xyz123", "10.1000/xyz123"),
            ("doi:10.1000/xyz123", "10.1000/xyz123"),
            ("DOI 10.1000/xyz123.", "10.1000/xyz123"),
            ("not a doi", None),
            ("", None),
            (None, None),
        ],
    )
    def test_normalize_doi(self, raw, expected):
        assert sa.normalize_doi(raw) == expected


class TestSafeUrl:
    @pytest.mark.parametrize(
        "raw,allowed",
        [
            ("https://example.org/a", True),
            ("http://example.org/a", True),
            ("file:///C:/secret.txt", False),
            ("javascript:alert(1)", False),
            ("ftp://example.org/a", False),
            ("/relative/path", False),
            ("https://", False),
        ],
    )
    def test_safe_source_url(self, raw, allowed):
        result = sa.safe_source_url(raw)
        assert (result is not None) is allowed


class TestEmptyResult:
    def test_empty_lookup_result_is_complete_and_unresolved(self):
        result = sa.empty_lookup_result("manual")

        assert set(result) == set(sa.SOURCE_RESULT_FIELDS)
        assert result["metadata_status"] == sa.METADATA_STATUS_UNRESOLVED
        assert result["material_level"] == sa.MATERIAL_LEVEL_METADATA
        assert result["title"] == ""
        assert result["authors"] == ""
        assert result["year"] is None
        assert result["doi"] is None
        assert result["abstract"] is None
        assert result["retrieved_at"]


class TestNormalizeLookupResult:
    def test_rejects_non_dict_and_results_without_title_or_doi(self):
        assert sa.normalize_lookup_result("not a dict") is None
        assert sa.normalize_lookup_result({}) is None
        assert sa.normalize_lookup_result({"authors": "A. Person"}) is None

    def test_whatever_the_provider_omits_stays_empty(self):
        result = sa.normalize_lookup_result({"title": "Only a title"})

        assert result is not None
        assert result["title"] == "Only a title"
        assert result["authors"] == ""
        assert result["year"] is None
        assert result["doi"] is None
        assert result["license"] == ""
        assert result["url"] is None

    def test_abstract_marks_material_level_abstract(self):
        result = sa.normalize_lookup_result(
            {"title": "T", "abstract": "<p>Summary only</p>", "metadata_status": "resolved"}
        )

        assert result is not None
        assert result["material_level"] == sa.MATERIAL_LEVEL_ABSTRACT
        assert result["abstract"] == "Summary only"

    def test_provider_claiming_full_text_is_kept(self):
        result = sa.normalize_lookup_result(
            {"title": "T", "material_level": "full_text", "doi": "10.1000/x"}
        )

        assert result is not None
        assert result["material_level"] == sa.MATERIAL_LEVEL_FULL_TEXT

    def test_unsafe_url_and_out_of_range_year_are_dropped(self):
        result = sa.normalize_lookup_result(
            {"title": "T", "url": "file:///etc/passwd", "year": 3021}
        )

        assert result is not None
        assert result["url"] is None
        assert result["year"] is None

    def test_authors_are_joined_from_structured_people(self):
        result = sa.normalize_lookup_result(
            {
                "title": "T",
                "authors": [
                    {"given": "Ada", "family": "Lovelace"},
                    {"name": "Alan Turing"},
                ],
            }
        )

        assert result is not None
        assert result["authors"] == "Ada Lovelace; Alan Turing"


class TestMapCrossref:
    def test_maps_real_fields_and_abstract_level(self):
        result = sa.map_crossref_message(_crossref_payload())

        assert result is not None
        # Crossref 标题可能带 JATS 内联标签；适配器负责保留真实标题，
        # 展示层再做安全渲染（此处只断言内容与 DOI 未被改写或补造）。
        assert re.sub(r"<[^>]+>", "", result["title"]) == "Deep Learning for Research Agents"
        assert result["doi"] == "10.1234/ABC.2024.001"
        assert result["authors"] == "Ada Lovelace; Alan Turing"
        assert result["year"] == 2024
        assert result["url"] == "https://example.org/paper"
        assert result["metadata_status"] == sa.METADATA_STATUS_RESOLVED
        assert result["material_level"] == sa.MATERIAL_LEVEL_ABSTRACT
        assert result["abstract"] == "We study agents & tools."
        assert result["license"] == "https://creativecommons.org/licenses/by/4.0/"

    def test_bare_message_and_doi_url_fallback(self):
        result = sa.map_crossref_message(
            {"message": {"title": ["T"], "DOI": "10.1000/xyz"}}
        )

        assert result is not None
        assert result["url"] == "https://doi.org/10.1000/xyz"
        assert result["material_level"] == sa.MATERIAL_LEVEL_METADATA
        assert result["year"] is None

    def test_missing_title_uses_doi_without_fabricating_title(self):
        result = sa.map_crossref_message(
            {"message": {"DOI": "10.1000/xyz", "author": [{"family": "Solo"}]}}
        )

        assert result is not None
        assert result["title"] == ""
        assert result["authors"] == "Solo"
        assert result["doi"] == "10.1000/xyz"

    @pytest.mark.parametrize("payload", [None, {}, {"message": {}}, {"message": "x"}])
    def test_unusable_payload_returns_none(self, payload):
        assert sa.map_crossref_message(payload) is None


@pytest.mark.asyncio
class TestDoiAdapter:
    async def test_requires_injected_client(self):
        with pytest.raises(ValueError):
            sa.DoiAdapter(None)

    async def test_non_doi_query_makes_no_request(self):
        client = _GetJsonStub(_crossref_payload())
        adapter = sa.DoiAdapter(client)

        assert await adapter.lookup("just a title") == []
        assert client.urls == []

    async def test_limit_zero_makes_no_request(self):
        client = _GetJsonStub(_crossref_payload())
        adapter = sa.DoiAdapter(client)

        assert await adapter.lookup("10.1000/x", limit=0) == []
        assert client.urls == []

    async def test_lookup_maps_crossref_payload(self):
        client = _GetJsonStub(_crossref_payload())
        adapter = sa.DoiAdapter(client)

        results = await adapter.lookup("doi:10.1234/ABC.2024.001")

        assert len(results) == 1
        assert re.sub(r"<[^>]+>", "", results[0]["title"]) == "Deep Learning for Research Agents"
        assert client.urls == ["https://api.crossref.org/works/10.1234/ABC.2024.001"]

    async def test_lookup_accepts_object_with_async_json(self):
        adapter = sa.DoiAdapter(_GetStub(_JsonResponse(_crossref_payload())))

        results = await adapter.lookup("10.1234/abc")

        assert results and results[0]["doi"] == "10.1234/ABC.2024.001"

    async def test_lookup_accepts_plain_dict_response(self):
        results = await sa.DoiAdapter(_GetStub(_crossref_payload())).lookup(
            "10.1234/abc"
        )

        assert results and results[0]["doi"] == "10.1234/ABC.2024.001"

    # 回归（原缺陷 B1）：fetch 分支必须与 get_json 一样经过 _response_payload
    # 解码；曾经直接返回原始 bytes/str，导致 DoiAdapter 配 fetch 客户端时静默返回 []。
    async def test_lookup_accepts_fetch_bytes(self):
        results = await sa.DoiAdapter(_FetchStub(_crossref_payload())).lookup(
            "10.1234/abc"
        )

        assert results and results[0]["doi"] == "10.1234/ABC.2024.001"

    async def test_unparseable_response_raises_adapter_error(self):
        adapter = sa.DoiAdapter(_BrokenClient())

        with pytest.raises(sa.SourceAdapterError):
            await adapter.lookup("10.1234/abc")

    async def test_client_without_transport_raises_adapter_error(self):
        adapter = sa.DoiAdapter(_NoTransport())

        with pytest.raises(sa.SourceAdapterError):
            await adapter.lookup("10.1234/abc")


@pytest.mark.asyncio
class TestRegistry:
    def setup_method(self):
        sa.reset_adapters()

    def teardown_method(self):
        sa.reset_adapters()

    async def test_register_rejects_objects_without_contract(self):
        with pytest.raises(TypeError):
            sa.register_adapter(object())

        class NoName:
            async def lookup(self, query, *, limit=10):
                return []

        with pytest.raises(TypeError):
            sa.register_adapter(NoName())

    async def test_register_replaces_same_name_in_place(self):
        class _Adapter:
            def __init__(self, name):
                self.name = name

            async def lookup(self, query, *, limit=10):
                return []

        first, second = _Adapter("one"), _Adapter("two")
        replacement = _Adapter("one")
        sa.register_adapter(first)
        sa.register_adapter(second)
        sa.register_adapter(replacement)

        assert sa.adapter_names() == ("one", "two")
        assert list(sa.list_adapters())[0] is replacement
        assert sa.adapters_available() is True

    async def test_reset_makes_registry_unavailable(self):
        class _Adapter:
            name = "x"

            async def lookup(self, query, *, limit=10):
                return []

        sa.register_adapter(_Adapter())
        assert sa.adapters_available() is True

        sa.reset_adapters()

        assert sa.adapters_available() is False
        assert sa.adapter_names() == ()
        assert sa.list_adapters() == ()