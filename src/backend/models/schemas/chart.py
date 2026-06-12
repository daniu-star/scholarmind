"""
ScholarMind Chart Pydantic Schema
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class ChartRequest(BaseModel):
    """图表生成请求"""
    chart_type: str = Field(
        ..., description="图表类型（ribbon/violin/alluvial/bubble_kde/...）"
    )
    title: str = Field(default="学术研究图表", max_length=200)
    x_label: str = Field(default="", max_length=100)
    y_label: str = Field(default="", max_length=100)
    data: Any = Field(default=None, description="JSON 数据")
    file_path: Optional[str] = Field(default=None, description="上传数据文件路径")
    width: int = Field(default=1200, ge=200, le=4000)
    height: int = Field(default=800, ge=200, le=4000)
    dpi: int = Field(default=300, ge=72, le=600)


class ChartTypeInfo(BaseModel):
    """图表类型信息"""
    type_key: str
    name: str
    description: str


class ChartTypeListResponse(BaseModel):
    """图表类型列表响应"""
    chart_types: list[ChartTypeInfo]
    total: int


class ChartSaveInfo(BaseModel):
    """图表保存信息"""
    chart_id: str
    filename: str
    chart_type: str
    title: str