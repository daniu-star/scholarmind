"""代码执行沙箱路由

P0 Task 1.3/1.4/1.5 安全加固：
- 所有端点强制 `Depends(require_admin)` 鉴权（非管理员 → 401/403）
- `/pip-install` 端点已永久移除（P0 止血：任何环境都不可用）
- `/run` 写入审计日志（含 user_id 与 code 的 sha256 前 16 字符）
- Router 本身的注册由 `app.py` 中的 `settings.CODE_EXECUTION_ENABLED` 控制，
  默认 False（关闭）；即便启用也在此处强制管理员鉴权。
"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends

from ..core.dependencies import require_admin
from ..core.logging_config import get_logger
from ..models.schemas.code_execution import (
    CodeExecuteRequest,
    CodeExecuteResponse,
    PackageListResponse,
)
from ..services.code_execution_service import (
    CodeExecutionService,
    get_code_execution_service,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/code-execution", tags=["code-execution"])


@router.post("/run", response_model=CodeExecuteResponse)
async def run_code(
    request: CodeExecuteRequest,
    user_id: int = Depends(require_admin),
    service: CodeExecutionService = Depends(get_code_execution_service),
):
    """执行 Python 代码

    在后端沙箱中执行用户提交的 Python 代码，支持爬虫脚本、数据分析脚本等。
    使用 subprocess + 临时文件方式，带超时控制。

    安全策略：
    - 强制管理员鉴权（require_admin）
    - 写入审计日志（user_id + code 的 sha256 前 16 字符）
    """
    code_hash = hashlib.sha256(request.code.encode("utf-8")).hexdigest()[:16]
    logger.info(
        f"code_execution invoked user_id={user_id} code_hash={code_hash} "
        f"language={request.language} timeout={request.timeout}"
    )
    result = await service.execute_code(
        code=request.code,
        language=request.language,
        timeout=request.timeout,
    )
    return result


@router.get("/packages", response_model=PackageListResponse)
async def list_packages(
    user_id: int = Depends(require_admin),
    service: CodeExecutionService = Depends(get_code_execution_service),
):
    """列出已安装的 Python 包（管理员）

    P0 Task 1.3：强制管理员鉴权，避免匿名/普通用户枚举运行时环境。
    """
    logger.info(f"code_execution list_packages invoked user_id={user_id}")
    result = await service.list_installed_packages()
    return result


# P0 Task 1.4: `/pip-install` 端点已永久移除。
# 旧端点允许任意登录用户通过 `pip install` 写入运行时依赖（持久化到容器/主机），
# 是一条匿名/低权限 RCE 入口。任何环境都不可用：
#   - Router 默认不注册（CODE_EXECUTION_ENABLED=False → 404）
#   - 即便启用，本文件也不再声明该端点
# 如确需在受控环境中安装依赖，请在镜像构建阶段固化到 requirements.txt。
