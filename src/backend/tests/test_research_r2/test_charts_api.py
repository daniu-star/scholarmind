"""T22 真实数据图表接口（R2 / AT-044–AT-047）。

这组用例锁定四件事：

1. 开关关闭时 ``POST /research/charts`` 返回 503，而不是生成占位图；
2. 数值校验、列映射校验都有明确错误码，且失败**不落 Artifact**；
3. 成功路径的 ``validation`` 记录来源、列映射、值域与 PNG 摘要，可复算；
4. 越权/不存在一律 404，不泄露存在性。
"""
from __future__ import annotations

import importlib

import pytest
from sqlalchemy import func, select

from ...research.chart_data_source import TableData
from ...research.chart_render import data_digest, value_ranges
from ...research.models import Artifact
from ..test_research.conftest import (
    assert_error,
    create_project,
    upload_document,
    version_id_of,
)
from .conftest import patch_in_modules, patch_switch


NUMERIC_TABLE = """# 数据

| 年份 | 论文数 | 平均页数 |
| --- | --- | --- |
| 2020 | 120 | 12.5 |
| 2021 | 138 | 13.1 |
| 2022 | 152 | 13.8 |
| 2023 | 168 | 14.2 |
"""

CATEGORICAL_TABLE = """# 数据

| 变量 | 使用时长 |
| --- | --- |
| 短视频 | 30 |
| 直播 | 45 |
"""


def _load_service_modules() -> None:
    """让两套包名下的 chart_service 都先落地，后续打桩才能命中请求路径。"""
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


async def _numeric_version(client) -> dict:
    project_id = await create_project(client, "图表验收")
    doc = await upload_document(
        client, project_id, filename="numbers.md", text=NUMERIC_TABLE
    )
    return {"project_id": project_id, "document_version_id": version_id_of(doc)}


async def _artifact_count(db) -> int:
    db.expire_all()
    return int(
        (await db.execute(select(func.count()).select_from(Artifact))).scalar_one()
    )


@pytest.mark.asyncio
async def test_disabled_capability_returns_503(client_a, db, monkeypatch):
    patch_switch(monkeypatch, "ENABLE_VERIFIED_CHARTS", False)
    base = await _numeric_version(client_a)
    before = await _artifact_count(db)

    response = await client_a.post(
        "/api/v1/research/charts",
        json={
            "chart_type": "gradient_area",
            "x_column": "年份",
            "y_columns": ["论文数"],
            **base,
        },
    )
    assert_error(response, 503, "CHART_CAPABILITY_DISABLED")
    assert await _artifact_count(db) == before


@pytest.mark.asyncio
async def test_success_records_verifiable_validation(client_a, charts_enabled):
    base = await _numeric_version(client_a)

    response = await client_a.post(
        "/api/v1/research/charts",
        json={
            "chart_type": "gradient_area",
            "x_column": "年份",
            "y_columns": ["论文数", "平均页数"],
            "title": "逐年论文数",
            **base,
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["kind"] == "chart"
    assert payload["mime"] == "image/png"
    assert payload["download_url"].endswith("/download")

    validation = payload["validation"]
    assert validation["render_verified"] is True
    # FR-13：清洗/缺失值策略必须显式留痕（哪怕就是"拒绝、不清洗"）。
    cleaning = validation["cleaning"]
    assert cleaning["missing_value_policy"] == "reject"
    assert cleaning["filtered_rows"] == 0
    assert isinstance(cleaning["steps"], list)
    assert validation["encoding"] == "base64"
    assert len(validation["png_sha256"]) == 64
    assert validation["png_width"] > 0 and validation["png_height"] > 0
    assert validation["source_document_version_id"] == base["document_version_id"]
    assert validation["x_column"] == "年份"
    assert validation["y_columns"] == ["论文数", "平均页数"]
    ranges = validation["value_ranges"]
    assert ranges["年份"] == {"min": 2020.0, "max": 2023.0}
    assert ranges["论文数"] == {"min": 120.0, "max": 168.0}
    assert ranges["平均页数"] == {"min": 12.5, "max": 14.2}
    assert len(validation["data_digest"]) == 64

    download = await client_a.get(payload["download_url"])
    assert download.status_code == 200
    assert download.content[:4] == b"\x89PNG"


@pytest.mark.asyncio
async def test_non_numeric_table_has_actionable_hint(client_a, charts_enabled):
    project_id = await create_project(client_a, "分类轴")
    doc = await upload_document(
        client_a, project_id, filename="cat.md", text=CATEGORICAL_TABLE
    )

    response = await client_a.post(
        "/api/v1/research/charts",
        json={
            "project_id": project_id,
            "document_version_id": version_id_of(doc),
            "chart_type": "gradient_area",
            "x_column": "变量",
            "y_columns": ["使用时长"],
        },
    )
    error = assert_error(response, 422, "CHART_NON_NUMERIC")
    assert error["details"].get("hint")


@pytest.mark.asyncio
async def test_unknown_column_and_bad_type(client_a, charts_enabled):
    base = await _numeric_version(client_a)

    unknown = await client_a.post(
        "/api/v1/research/charts",
        json={
            "chart_type": "gradient_area",
            "x_column": "年份",
            "y_columns": ["不存在"],
            **base,
        },
    )
    assert_error(unknown, 422, "CHART_UNKNOWN_COLUMN")

    bad_type = await client_a.post(
        "/api/v1/research/charts",
        json={
            "chart_type": "bar",
            "x_column": "年份",
            "y_columns": ["论文数"],
            **base,
        },
    )
    assert_error(bad_type, 422, "CHART_UNSUPPORTED_TYPE")


@pytest.mark.asyncio
async def test_cross_owner_returns_404(client_a, client_b, charts_enabled):
    base = await _numeric_version(client_a)

    response = await client_b.post(
        "/api/v1/research/charts",
        json={
            "chart_type": "gradient_area",
            "x_column": "年份",
            "y_columns": ["论文数"],
            **base,
        },
    )
    assert_error(response, 404)
    assert base["document_version_id"] not in response.text


@pytest.mark.asyncio
async def test_render_failure_leaves_no_artifact(
    client_a, db, charts_enabled, monkeypatch
):
    base = await _numeric_version(client_a)
    before = await _artifact_count(db)

    def _boom(*args, **kwargs):
        raise RuntimeError("renderer exploded")

    patched = patch_in_modules(
        monkeypatch, "research.chart_service", "render_chart_png", _boom
    )
    assert patched >= 1

    response = await client_a.post(
        "/api/v1/research/charts",
        json={
            "chart_type": "gradient_area",
            "x_column": "年份",
            "y_columns": ["论文数"],
            **base,
        },
    )
    assert_error(response, 500, "CHART_RENDER_FAILED")
    assert response.json()["error"]["retryable"] is True
    assert await _artifact_count(db) == before


def test_digest_and_ranges_are_deterministic():
    table = TableData(
        columns=("年份", "论文数"),
        rows=[[2020, 120], [2021, 138]],
        table_index=0,
        source_text_hash="a" * 64,
    )
    assert data_digest(table) == data_digest(table)
    assert len(data_digest(table)) == 64
    assert value_ranges(table)["论文数"] == {"min": 120.0, "max": 138.0}
