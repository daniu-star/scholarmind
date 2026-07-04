"""
ScholarMind Chart Pydantic Schema
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class ChartRequest(BaseModel):
    """图表生成请求(统一 Schema,router 与 service 共用)"""
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

    @field_validator("chart_type")
    @classmethod
    def validate_chart_type(cls, v: str) -> str:
        """验证图表类型是否在支持的 12 种类型内"""
        # 延迟导入避免循环依赖
        from ...services.chart_service import CHART_FUNCTIONS

        v = v.strip().lower()
        if v not in CHART_FUNCTIONS:
            valid = ", ".join(CHART_FUNCTIONS.keys())
            raise ValueError(f"不支持的图表类型: {v}，支持类型: {valid}")
        return v

    @field_validator("width", "height")
    @classmethod
    def validate_dimensions(cls, v: int) -> int:
        """验证图像尺寸(与 Field 约束双重保障)"""
        if v < 200 or v > 4000:
            raise ValueError("图像尺寸必须在 200-4000 像素之间")
        return v

    @field_validator("dpi")
    @classmethod
    def validate_dpi(cls, v: int) -> int:
        """验证 DPI(与 Field 约束双重保障)"""
        if v < 72 or v > 600:
            raise ValueError("DPI 必须在 72-600 之间")
        return v


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