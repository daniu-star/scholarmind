"""
ScholarMind 图表生成 API 路由
提供12种学术图表的生成、查询和类型列表接口
"""

import os
import uuid
from pathlib import Path
from typing import Optional, Any

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, field_validator

from ..services import chart_service
from ..config import settings
from ..core.exceptions import (
    ChartGenerationError,
    InvalidChartTypeError,
    ValidationError,
    NotFoundError,
)

router = APIRouter(prefix="/chart", tags=["chart"])


# ── 请求/响应模型 ────────────────────────────────────────

class ChartRequest(BaseModel):
    chart_type: str  # 12种图表类型之一
    title: str = "学术研究图表"
    x_label: str = ""
    y_label: str = ""
    data: Any = None  # JSON 数据
    file_path: Optional[str] = None  # 上传数据文件路径
    width: int = 1200
    height: int = 800
    dpi: int = 300

    @field_validator("chart_type")
    @classmethod
    def validate_chart_type(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in chart_service.CHART_FUNCTIONS:
            valid = ", ".join(chart_service.CHART_FUNCTIONS.keys())
            raise ValueError(f"不支持的图表类型: {v}，支持类型: {valid}")
        return v

    @field_validator("width", "height")
    @classmethod
    def validate_dimensions(cls, v: int) -> int:
        if v < 200 or v > 4000:
            raise ValueError("图像尺寸必须在 200-4000 像素之间")
        return v

    @field_validator("dpi")
    @classmethod
    def validate_dpi(cls, v: int) -> int:
        if v < 72 or v > 600:
            raise ValueError("DPI 必须在 72-600 之间")
        return v


class ChartTypeInfo(BaseModel):
    type_key: str
    name: str
    description: str


# ── 辅助函数 ──────────────────────────────────────────────

def _ensure_charts_dir():
    """确保图表存储目录存在"""
    charts_dir = Path(settings.CHARTS_DIR)
    charts_dir.mkdir(parents=True, exist_ok=True)
    return charts_dir


def _resolve_data(request: ChartRequest) -> Any:
    """
    解析图表数据来源
    优先使用 request.data，其次读取 request.file_path
    file_path 必须在上传目录或图表目录内，防止路径遍历
    """
    if request.data is not None:
        return request.data

    if request.file_path:
        file_path = Path(request.file_path).resolve()

        # 安全检查：file_path 必须在允许的目录内
        allowed_dirs = [
            Path(settings.UPLOAD_DIR).resolve(),
            Path(settings.CHARTS_DIR).resolve(),
        ]
        if not any(
            _is_subpath(file_path, allowed_dir) for allowed_dir in allowed_dirs
        ):
            raise ValidationError("数据文件路径必须在允许的目录内（上传目录或图表目录）")

        if not file_path.exists():
            raise ValidationError(f"数据文件不存在: {request.file_path}")

        suffix = file_path.suffix.lower()
        try:
            if suffix == ".json":
                import json
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            elif suffix == ".csv":
                import pandas as pd
                df = pd.read_csv(file_path)
                return df.to_dict(orient="list")
            elif suffix in (".xlsx", ".xls"):
                import pandas as pd
                df = pd.read_excel(file_path)
                return df.to_dict(orient="list")
            else:
                with open(file_path, "r", encoding="utf-8") as f:
                    return f.read()
        except Exception as e:
            raise ValidationError(f"数据文件解析失败: {str(e)}")

    raise ValidationError("必须提供 data 或 file_path 参数")


def _is_subpath(path: Path, parent: Path) -> bool:
    """检查 path 是否在 parent 目录内"""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


# ── API 端点 ──────────────────────────────────────────────

@router.post("/generate")
async def generate_chart(request: ChartRequest):
    """
    生成学术图表并返回 PNG 图像

    - **chart_type**: 图表类型（ribbon/violin/alluvial/bubble_kde/gradient_area/surface3d/parallel/contour/swarm/scatter_density/chord/heatmap_dendro）
    - **data**: JSON 格式的图表数据
    - **file_path**: 可选，数据文件路径（支持 .json/.csv/.xlsx）
    - **title**: 图表标题
    - **x_label**: X轴标签
    - **y_label**: Y轴标签
    - **width**: 图像宽度（像素）
    - **height**: 图像高度（像素）
    - **dpi**: 分辨率
    """
    # 解析数据
    data = _resolve_data(request)

    # 生成图表
    try:
        png_bytes = chart_service.generate_chart(
            chart_type=request.chart_type,
            data=data,
            title=request.title,
            x_label=request.x_label,
            y_label=request.y_label,
            width=request.width,
            height=request.height,
            dpi=request.dpi,
        )
    except Exception as e:
        raise ChartGenerationError(str(e), chart_type=request.chart_type)

    # 保存到文件
    chart_id = str(uuid.uuid4())
    charts_dir = _ensure_charts_dir()
    chart_path = charts_dir / f"{chart_id}.png"

    try:
        with open(chart_path, "wb") as f:
            f.write(png_bytes)
    except Exception as e:
        raise ChartGenerationError(f"图表保存失败: {str(e)}")

    # 返回 PNG 图像
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "X-Chart-ID": chart_id,
            "Content-Disposition": f'inline; filename="{chart_id}.png"',
        },
    )


@router.get("/types")
async def list_chart_types():
    """
    列出所有可用的图表类型

    返回12种图表的类型键、中文名称和描述
    """
    types = []
    for key in chart_service.CHART_FUNCTIONS:
        types.append(ChartTypeInfo(
            type_key=key,
            name=chart_service.CHART_NAMES.get(key, key),
            description=chart_service.CHART_DESCRIPTIONS.get(key, ""),
        ))
    return {"chart_types": types, "total": len(types)}


@router.get("/{chart_id}")
async def get_chart(chart_id: str):
    """
    根据 ID 获取已生成的图表

    - **chart_id**: 图表 UUID（由 /generate 接口返回的 X-Chart-ID 头部获取）
    """
    # 防止路径遍历攻击
    safe_id = chart_id.replace("/", "").replace("\\", "").replace("..", "")
    if not safe_id or safe_id != chart_id:
        raise ValidationError("无效的图表 ID")

    charts_dir = _ensure_charts_dir()
    chart_path = charts_dir / f"{safe_id}.png"

    if not chart_path.exists():
        raise NotFoundError("图表", chart_id)

    try:
        with open(chart_path, "rb") as f:
            png_bytes = f.read()
    except Exception as e:
        raise ChartGenerationError(f"图表读取失败: {str(e)}")

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "Content-Disposition": f'inline; filename="{safe_id}.png"',
        },
    )
