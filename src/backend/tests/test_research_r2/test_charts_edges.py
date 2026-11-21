"""R2 图表拒绝路径与"可核对"约束（T22 / FR-13 / AT-055 子项）。

补齐 ``test_charts_api.py`` 未覆盖的边界：

* ``CHART_NO_TABLE``：正文里没有任何表；``table_index`` 越界（契约里与"无表"
  同码，details 给出 ``tables_found``，便于前端提示"本文档只有 N 张表"）；
* ``CHART_EMPTY_DATA``：只有表头、没有数据行；
* ``CHART_TOO_MANY_ROWS``（413）：把 ``RESEARCH_CHART_MAX_ROWS`` 临时压到 1，
  不构造几千行真实数据；
* ``ChartRequest`` 的 ``extra="forbid"``：多余字段被请求模型直接拒绝；
* 成功路径的可核对性：``data_digest`` 用同一列选择复算一致、``value_ranges``
  与表数据一致、行/列数正确、下载 PNG 的 sha256 与尺寸都与 ``validation`` 对齐；
* 跨项目引用（自己的项目 + 别人的文档版本）同样 404。

每个失败用例都断言 ``research_artifacts`` 没有新增行：失败既不落成果，也不
回退到占位图。
"""
from __future__ import annotations

import hashlib
import importlib

import pytest
from sqlalchemy import func, select

from ...research.chart_data_source import load_table, select_columns
from ...research.chart_render import data_digest
from ...research.models import Artifact
from ..test_research.conftest import (
    assert_error,
    create_project,
    upload_document,
    version_id_of,
)
from .conftest import patch_switch

pytestmark = pytest.mark.asyncio

NUMERIC_TABLE = """# 数据

| 年份 | 论文数 | 平均页数 |
| --- | --- | --- |
| 2020 | 120 | 12.5 |
| 2021 | 138 | 13.1 |
| 2022 | 152 | 13.8 |
| 2023 | 168 | 14.2 |
"""

TEXT_ONLY = """# 记录

这一版只有文字说明，没有任何表格；图表接口应当明确拒绝，而不是猜一张表。
"""

HEADER_ONLY = """# 空表

| 年份 | 论文数 |
| --- | --- |
"""


def _load_service_modules() -> None:
    """让两套包名下的 chart_service 都先落地，后续打补丁才能命中请求路径。"""
    for name in (
        "backend.research.chart_service",
        "src.backend.research.chart_service",
    ):
        try:
            importlib.import_module(name)
        except Exception:  # pragma: no cover - 其中一套可能未启用
            pass


@pytest.fixture()
def charts_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _load_service_modules()
    patch_switch(monkeypatch, "ENABLE_VERIFIED_CHARTS", True)


async def _document(client, text: str, *, title: str = "图表边界") -> dict:
    project_id = await create_project(client, title)
    doc = await upload_document(client, project_id, filename="table.md", text=text)
    return {"project_id": project_id, "document_version_id": version_id_of(doc)}


def _chart_body(base: dict, **overrides) -> dict:
    body = {
        "chart_type": "gradient_area",
        "x_column": "年份",
        "y_columns": ["论文数"],
        **base,
    }
    body.update(overrides)
    return body


async def _artifact_count(db) -> int:
    db.expire_all()
    return int(
        (await db.execute(select(func.count()).select_from(Artifact))).scalar_one()
    )


async def test_document_without_table_is_rejected(client_a, db, charts_enabled):
    base = await _document(client_a, TEXT_ONLY)
    before = await _artifact_count(db)

    response = await client_a.post(
        "/api/v1/research/charts", json=_chart_body(base)
    )
    error = assert_error(response, 422, "CHART_NO_TABLE")
    assert error["details"]["tables_found"] == 0
    assert await _artifact_count(db) == before


async def test_table_index_out_of_range_is_rejected(client_a, db, charts_enabled):
    base = await _document(client_a, NUMERIC_TABLE)
    before = await _artifact_count(db)

    response = await client_a.post(
        "/api/v1/research/charts", json=_chart_body(base, table_index=3)
    )
    error = assert_error(response, 422, "CHART_NO_TABLE")
    assert error["details"] == {"table_index": 3, "tables_found": 1}
    assert await _artifact_count(db) == before


async def test_header_only_table_reports_empty_data(client_a, db, charts_enabled):
    base = await _document(client_a, HEADER_ONLY)
    before = await _artifact_count(db)

    response = await client_a.post(
        "/api/v1/research/charts", json=_chart_body(base)
    )
    assert_error(response, 422, "CHART_EMPTY_DATA")
    assert await _artifact_count(db) == before


async def test_too_many_rows_returns_413(
    client_a, db, charts_enabled, monkeypatch: pytest.MonkeyPatch
):
    # 不生成几千行数据：直接把上限压到 1 行，验证 413 与大表拒绝逻辑。
    patch_switch(monkeypatch, "RESEARCH_CHART_MAX_ROWS", 1)
    base = await _document(client_a, NUMERIC_TABLE)
    before = await _artifact_count(db)

    response = await client_a.post(
        "/api/v1/research/charts", json=_chart_body(base)
    )
    error = assert_error(response, 413, "CHART_TOO_MANY_ROWS")
    assert error["details"]["row_count"] == 4
    assert error["details"]["max_rows"] == 1
    assert await _artifact_count(db) == before


async def test_extra_field_is_rejected_by_request_model(client_a, charts_enabled):
    base = await _document(client_a, NUMERIC_TABLE)

    response = await client_a.post(
        "/api/v1/research/charts",
        json={**_chart_body(base), "unknown_field": "surprise"},
    )
    # 请求模型校验失败由全局处理器转成统一信封：VALIDATION_ERROR + loc 线索。
    error = assert_error(response, 422, "VALIDATION_ERROR")
    errors = error["details"]["errors"]
    assert any("unknown_field" in str(item.get("loc")) for item in errors)


async def test_success_is_recomputable_and_download_matches_digest(
    client_a, db, research_store, charts_enabled
):
    base = await _document(client_a, NUMERIC_TABLE)

    response = await client_a.post(
        "/api/v1/research/charts", json=_chart_body(base)
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    validation = payload["validation"]

    # 1) 用同一列选择在服务端复算摘要，必须与响应里的 data_digest 一致。
    actor = research_store.actor("a")
    table = await load_table(
        db, actor, document_version_id=base["document_version_id"], table_index=0
    )
    selected = select_columns(table, x_column="年份", y_columns=["论文数"])
    assert validation["data_digest"] == data_digest(selected)
    assert validation["data_digest_scope"] == "selected_table"

    # 2) 值域、行列数与表数据严格一致（AT-055：图中值可核对）。
    assert validation["value_ranges"] == {
        "年份": {"min": 2020.0, "max": 2023.0},
        "论文数": {"min": 120.0, "max": 168.0},
    }
    assert validation["row_count"] == 4
    assert validation["column_count"] == 2
    assert validation["x_column"] == "年份"
    assert validation["render_verified"] is True
    assert validation["renderer"]["dpi"] == 300

    # 3) 下载字节的 sha256、PNG 尺寸必须与 validation 记录一致。
    download = await client_a.get(payload["download_url"])
    assert download.status_code == 200
    png = download.content
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert hashlib.sha256(png).hexdigest() == validation["png_sha256"]
    width = int.from_bytes(png[16:20], "big")
    height = int.from_bytes(png[20:24], "big")
    assert (width, height) == (validation["png_width"], validation["png_height"])

    # 4) 落库的 Artifact 与响应同源，且正文是 base64（不是服务器路径）。
    db.expire_all()
    row = (
        await db.execute(select(Artifact).where(Artifact.id == payload["id"]))
    ).scalar_one()
    assert row.mime == "image/png"
    assert row.validation_json == validation
    assert row.size_bytes == len(row.body.encode("utf-8"))
    assert "/" not in row.filename or row.filename.endswith(".png")


async def test_same_input_is_render_stable(client_a, charts_enabled):
    """同一份数据、同一列映射：摘要与 PNG 摘要必须稳定（R2_INTERFACE_SPEC §2.2）。"""
    base = await _document(client_a, NUMERIC_TABLE)

    first = await client_a.post("/api/v1/research/charts", json=_chart_body(base))
    second = await client_a.post("/api/v1/research/charts", json=_chart_body(base))
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text

    left, right = first.json()["validation"], second.json()["validation"]
    assert left["data_digest"] == right["data_digest"]
    assert left["png_sha256"] == right["png_sha256"]
    assert (left["png_width"], left["png_height"]) == (
        right["png_width"],
        right["png_height"],
    )


async def test_project_version_mismatch_is_404(client_a, client_b, charts_enabled):
    """自己的项目 + 别人的文档版本：不能借项目 id 绕过版本归属校验。"""
    mine = await _document(client_a, NUMERIC_TABLE)
    other_project = await create_project(client_b, "另一个项目")

    response = await client_b.post(
        "/api/v1/research/charts",
        json=_chart_body(
            {
                "project_id": other_project,
                "document_version_id": mine["document_version_id"],
            }
        ),
    )
    error = assert_error(response, 404)
    assert mine["document_version_id"] not in response.text
    assert "project_id" not in (error.get("details") or {})
