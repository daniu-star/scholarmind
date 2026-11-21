"""T22 基础图表（bar / line）与分类 x 轴（R2 零成本验收第三轮）。

锁定四件事：

1. 分类表（x 列是文本、y 列是数值）能出图，``validation`` 明确记录
   ``x_mode="categorical"`` 与完整标签，**不把分类悄悄编码成 0/1 数值轴**；
2. 高级图表（12 种灰阶图）仍要求全数值表，分类表只能用于 bar/line；
3. 分类表的坏数据（空标签、y 非数值、x 不是第一列）都有明确 422，且不落 Artifact；
4. 纯函数 ``canonical_series_csv`` / ``series_digest`` 对同样输入稳定可复算。
"""
from __future__ import annotations

import importlib

import pytest
from sqlalchemy import func, select

from ...research.chart_data_source import SeriesTable
from ...research.chart_render import (
    BASIC_CHART_TYPES,
    canonical_series_csv,
    series_digest,
    series_value_ranges,
)
from ...research.models import Artifact
from ..test_research.conftest import (
    assert_error,
    create_project,
    upload_document,
    version_id_of,
)
from .conftest import patch_switch

CATEGORICAL_TABLE = """# 分类数据

| 平台 | 使用时长 | 满意度 |
| --- | --- | --- |
| 短视频 | 30 | 4.1 |
| 直播 | 45 | 3.8 |
| 图文 | 22 | 4.4 |
"""

NUMERIC_TABLE = """# 数值数据

| 年份 | 论文数 |
| --- | --- |
| 2020 | 120 |
| 2021 | 138 |
"""

EMPTY_LABEL_TABLE = """# 空标签

| 平台 | 使用时长 |
| --- | --- |
|  | 30 |
| 直播 | 45 |
"""

BAD_Y_TABLE = """# 坏 y

| 平台 | 使用时长 |
| --- | --- |
| 短视频 | 很多 |
| 直播 | 45 |
"""


def _load_service_modules() -> None:
    """两套包名下的 chart_service 都先落地，打桩才能命中请求路径。"""
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


async def _version_with(client, text: str, filename: str) -> dict:
    project_id = await create_project(client, "基础图表验收")
    doc = await upload_document(client, project_id, filename=filename, text=text)
    return {"project_id": project_id, "document_version_id": version_id_of(doc)}


async def _artifact_count(db) -> int:
    db.expire_all()
    return int((await db.execute(select(func.count()).select_from(Artifact))).scalar_one())


@pytest.mark.asyncio
async def test_bar_chart_renders_categorical_table(client_a, db, charts_enabled):
    base = await _version_with(client_a, CATEGORICAL_TABLE, "categorical.md")
    before = await _artifact_count(db)

    response = await client_a.post(
        "/api/v1/research/charts",
        json={
            "chart_type": "bar",
            "x_column": "平台",
            "y_columns": ["使用时长"],
            **base,
        },
    )
    assert response.status_code == 201, response.text
    artifact = response.json()
    validation = artifact["validation"]

    assert artifact["kind"] == "chart"
    assert artifact["mime"] == "image/png"
    assert validation["chart_type"] == "bar"
    assert validation["x_mode"] == "categorical"
    assert validation["x_column"] == "平台"
    assert validation["x_labels"] == ["短视频", "直播", "图文"]
    assert validation["x_label_count"] == 3
    assert validation["row_count"] == 3
    assert validation["column_count"] == 2
    assert validation["y_columns"] == ["使用时长"]
    assert validation["value_ranges"] == {"使用时长": {"min": 22.0, "max": 45.0}}
    assert "平台" not in validation["value_ranges"]
    assert validation["render_verified"] is True
    assert len(validation["png_sha256"]) == 64
    assert validation["png_width"] > 0 and validation["png_height"] > 0
    assert validation["cleaning"]["missing_value_policy"] == "reject"
    assert await _artifact_count(db) == before + 1

    download = await client_a.get(f"/api/v1/research/artifacts/{artifact['id']}/download")
    assert download.status_code == 200
    assert download.content[:4] == b"\x89PNG"


@pytest.mark.asyncio
async def test_line_chart_with_two_series(client_a, db, charts_enabled):
    base = await _version_with(client_a, CATEGORICAL_TABLE, "categorical.md")

    response = await client_a.post(
        "/api/v1/research/charts",
        json={
            "chart_type": "line",
            "x_column": "平台",
            "y_columns": ["使用时长", "满意度"],
            **base,
        },
    )
    assert response.status_code == 201, response.text
    validation = response.json()["validation"]
    assert validation["chart_type"] == "line"
    assert validation["y_columns"] == ["使用时长", "满意度"]
    assert set(validation["value_ranges"]) == {"使用时长", "满意度"}
    assert validation["x_labels"] == ["短视频", "直播", "图文"]


@pytest.mark.asyncio
async def test_advanced_charts_still_reject_categorical_table(client_a, db, charts_enabled):
    base = await _version_with(client_a, CATEGORICAL_TABLE, "categorical.md")
    before = await _artifact_count(db)

    response = await client_a.post(
        "/api/v1/research/charts",
        json={
            "chart_type": "ribbon",
            "x_column": "平台",
            "y_columns": ["使用时长"],
            **base,
        },
    )
    error = assert_error(response, 422, "CHART_NON_NUMERIC")
    assert error["details"].get("hint")
    assert await _artifact_count(db) == before


@pytest.mark.asyncio
async def test_basic_chart_rejects_empty_label_and_bad_y(client_a, db, charts_enabled):
    empty_label = await _version_with(client_a, EMPTY_LABEL_TABLE, "empty-label.md")
    response = await client_a.post(
        "/api/v1/research/charts",
        json={"chart_type": "bar", "x_column": "平台", "y_columns": ["使用时长"], **empty_label},
    )
    error = assert_error(response, 422, "CHART_NON_NUMERIC")
    assert "分类标签" in error["message"]

    bad_y = await _version_with(client_a, BAD_Y_TABLE, "bad-y.md")
    response = await client_a.post(
        "/api/v1/research/charts",
        json={"chart_type": "bar", "x_column": "平台", "y_columns": ["使用时长"], **bad_y},
    )
    error = assert_error(response, 422, "CHART_NON_NUMERIC")
    assert error["details"]["column"] == "使用时长"


@pytest.mark.asyncio
async def test_basic_chart_requires_first_column_as_x(client_a, db, charts_enabled):
    base = await _version_with(client_a, NUMERIC_TABLE, "numbers.md")
    response = await client_a.post(
        "/api/v1/research/charts",
        json={"chart_type": "bar", "x_column": "论文数", "y_columns": ["论文数"], **base},
    )
    error = assert_error(response, 422, "CHART_TABLE_INVALID")
    assert "第一列" in error["message"]


def test_series_digest_and_ranges_are_deterministic():
    series = SeriesTable(
        x_name="平台",
        x_labels=("短视频", "直播"),
        y_columns=("使用时长",),
        rows=((30.0,), (45.0,)),
        table_index=0,
        source_text_hash="hash",
    )
    other = SeriesTable(
        x_name="平台",
        x_labels=("短视频", "直播"),
        y_columns=("使用时长",),
        rows=((30.0,), (45.0,)),
        table_index=1,
        source_text_hash="another",
    )

    assert canonical_series_csv(series).splitlines()[0] == "平台,使用时长"
    assert series_digest(series) == series_digest(other)
    assert len(series_digest(series)) == 64
    assert series_value_ranges(series) == {"使用时长": {"min": 30.0, "max": 45.0}}

    renamed = SeriesTable(
        x_name="平台",
        x_labels=("短视频", "直播平台"),
        y_columns=("使用时长",),
        rows=((30.0,), (45.0,)),
        table_index=0,
        source_text_hash="hash",
    )
    assert series_digest(renamed) != series_digest(series)
    assert BASIC_CHART_TYPES == frozenset({"bar", "line"})
