"""D1：上传 CSV/XLSX 数据文件后可以直接出图（R2 图表验收补丁）。

这组用例锁定：
1. ``.xlsx`` / ``.csv`` 上传被解析成 Markdown 管道表，图表接口能按
   ``table_index`` 选表并给出正确的 ``value_ranges``；
2. 非数值表仍是 422 且带可操作 hint（不是 500、不是空表）；
3. 坏工作簿 / 非法编码是 422，不泄露 500；
4. 行数上限仍由图表侧 ``RESEARCH_CHART_MAX_ROWS`` 判定为 413。
"""
from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from ..test_research.conftest import (
    assert_error,
    create_project,
    upload_document,
    version_id_of,
)
from .conftest import patch_switch
from .test_charts_api import charts_enabled as charts_enabled  # noqa: F401  (夹具复用)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx_bytes(sheets: list[tuple[str, list[list[object]]]]) -> bytes:
    """把 ``[(sheet 名, 行)]`` 写成一份真实的 xlsx 字节流。"""
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets:
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


async def _upload(client, filename: str, data: bytes, mime: str) -> dict:
    project_id = await create_project(client, "数据文件出图")
    document = await upload_document(
        client, project_id, filename=filename, text=data, mime=mime
    )
    return {
        "project_id": project_id,
        "document_version_id": version_id_of(document),
        "document": document,
    }


async def _chart(client, base: dict, **overrides):
    body = {
        "project_id": base["project_id"],
        "document_version_id": base["document_version_id"],
        "chart_type": "gradient_area",
        "x_column": "年份",
        "y_columns": ["论文数"],
        **overrides,
    }
    return await client.post("/api/v1/research/charts", json=body)


@pytest.mark.asyncio
async def test_xlsx_upload_charts_with_correct_value_ranges(client_a, charts_enabled):
    data = _xlsx_bytes(
        [
            (
                "逐年统计",
                [
                    ["年份", "论文数", "平均页数"],
                    [2020, 120, 12.5],
                    [2021, 138, 13.1],
                    [2022, 152, 13.8],
                ],
            )
        ]
    )
    base = await _upload(client_a, "stats.xlsx", data, XLSX_MIME)
    assert base["document"]["version"]["parse_status"] == "complete"

    response = await _chart(client_a, base, y_columns=["论文数", "平均页数"])
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["kind"] == "chart"
    ranges = payload["validation"]["value_ranges"]
    assert ranges["年份"] == {"min": 2020.0, "max": 2022.0}
    assert ranges["论文数"] == {"min": 120.0, "max": 152.0}
    # 小数不能被 e 记数法/浮点抖动毁掉：12.5 就是 12.5。
    assert ranges["平均页数"] == {"min": 12.5, "max": 13.8}


@pytest.mark.asyncio
async def test_csv_upload_charts(client_a, charts_enabled):
    data = "年份;论文数\n2020;120\n2021;138\n".encode("utf-8-sig")
    base = await _upload(client_a, "stats.csv", data, "text/csv")

    response = await _chart(client_a, base)
    assert response.status_code == 201, response.text
    ranges = response.json()["validation"]["value_ranges"]
    assert ranges["论文数"] == {"min": 120.0, "max": 138.0}


@pytest.mark.asyncio
async def test_non_numeric_xlsx_has_actionable_hint(client_a, charts_enabled):
    data = _xlsx_bytes([("分类", [["变量", "使用时长"], ["短视频", 30], ["直播", 45]])])
    base = await _upload(client_a, "cat.xlsx", data, XLSX_MIME)

    response = await _chart(client_a, base, x_column="变量", y_columns=["使用时长"])
    error = assert_error(response, 422, "CHART_NON_NUMERIC")
    assert error["details"].get("hint")


@pytest.mark.asyncio
async def test_broken_xlsx_is_422_not_500(client_a):
    project_id = await create_project(client_a, "坏工作簿")
    response = await client_a.post(
        f"/api/v1/research/projects/{project_id}/documents",
        files={"file": ("broken.xlsx", b"PK\\x03\\x04not-a-workbook", XLSX_MIME)},
    )
    error = assert_error(response, 422)
    assert error["code"] in {"PARSE_FAILED", "UNSUPPORTED_MEDIA_TYPE"}
    assert "500" not in response.text


@pytest.mark.asyncio
async def test_second_sheet_is_selectable_by_table_index(client_a, charts_enabled):
    data = _xlsx_bytes(
        [
            ("第一表", [["年份", "论文数"], [2000, 10], [2001, 11]]),
            ("第二表", [["年份", "论文数"], [2020, 120], [2021, 138]]),
        ]
    )
    base = await _upload(client_a, "two-sheets.xlsx", data, XLSX_MIME)

    first = await _chart(client_a, base)
    assert first.status_code == 201, first.text
    assert first.json()["validation"]["value_ranges"]["论文数"] == {
        "min": 10.0,
        "max": 11.0,
    }

    second = await _chart(client_a, base, table_index=1)
    assert second.status_code == 201, second.text
    assert second.json()["validation"]["value_ranges"]["论文数"] == {
        "min": 120.0,
        "max": 138.0,
    }


@pytest.mark.asyncio
async def test_row_limit_still_413(client_a, charts_enabled, monkeypatch):
    patch_switch(monkeypatch, "RESEARCH_CHART_MAX_ROWS", 3)
    rows: list[list[object]] = [["年份", "论文数"]]
    rows += [[2000 + offset, 10 + offset] for offset in range(8)]
    base = await _upload(client_a, "many-rows.xlsx", _xlsx_bytes([("长表", rows)]), XLSX_MIME)

    response = await _chart(client_a, base)
    assert_error(response, 413, "CHART_TOO_MANY_ROWS")


@pytest.mark.asyncio
async def test_csv_is_415_when_mime_and_extension_disagree(client_a):
    """既不是 CSV 也不是受支持类型的二进制仍走 415（不新增放行面）。"""
    project_id = await create_project(client_a, "伪装扩展名")
    response = await client_a.post(
        f"/api/v1/research/projects/{project_id}/documents",
        files={"file": ("payload.bin", b"\\x89PNG\\r\\n\\x1a\\n", "application/octet-stream")},
    )
    assert_error(response, 415, "UNSUPPORTED_MEDIA_TYPE")
