"""
ScholarMind 技能管理 API 路由
技能 CRUD + 上传 + 模板
"""
from fastapi import APIRouter, UploadFile, File, Depends, Request

from ..services.skills_service import SkillsService
from ..models.schemas.skills import (
    SkillCreateRequest,
    SkillUpdateRequest,
    SkillToggleRequest,
)
from ..core.dependencies import get_skills_service
from ..core.exceptions import (
    SkillNotFoundError,
    SkillAlreadyExistsError,
    SkillValidationError,
)

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("")
async def list_skills(
    service: SkillsService = Depends(get_skills_service),
):
    """List all skills (preset + custom)"""
    skills = service.list_all()
    return {"skills": skills, "count": len(skills)}


@router.get("/{skill_id}")
async def get_skill(
    skill_id: str,
    service: SkillsService = Depends(get_skills_service),
):
    """Get single skill by id"""
    skill = service.get_skill(skill_id)
    if skill is None:
        raise SkillNotFoundError(skill_id)
    return skill


@router.post("")
async def create_skill(
    req: SkillCreateRequest,
    service: SkillsService = Depends(get_skills_service),
):
    """Create custom skill"""
    try:
        skill = service.create_skill(req.model_dump())
    except ValueError as e:
        raise SkillValidationError(str(e))
    return skill


@router.put("/{skill_id}")
async def update_skill(
    skill_id: str,
    req: SkillUpdateRequest,
    service: SkillsService = Depends(get_skills_service),
):
    """Update skill"""
    data = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        skill = service.update_skill(skill_id, data)
    except ValueError as e:
        raise SkillValidationError(str(e))
    return skill


@router.delete("/{skill_id}")
async def delete_skill(
    skill_id: str,
    service: SkillsService = Depends(get_skills_service),
):
    """Delete skill (preset skills cannot be deleted)"""
    try:
        success = service.delete_skill(skill_id)
    except ValueError as e:
        raise SkillValidationError(str(e))
    if not success:
        raise SkillNotFoundError(skill_id)
    return {"id": skill_id, "deleted": True}


@router.post("/{skill_id}/toggle")
async def toggle_skill(
    skill_id: str,
    req: SkillToggleRequest,
    service: SkillsService = Depends(get_skills_service),
):
    """Toggle skill enabled state"""
    try:
        skill = service.toggle_skill(skill_id, req.enabled)
    except ValueError as e:
        raise SkillValidationError(str(e))
    return skill


@router.post("/upload")
async def upload_skill_file(
    file: UploadFile = File(...),
    service: SkillsService = Depends(get_skills_service),
):
    """Upload .md skill file"""
    if not file.filename.endswith(".md"):
        raise SkillValidationError("仅支持 .md 格式的技能文件")

    content = await file.read()
    try:
        skill = service.upload_skill_file(content, file.filename)
    except ValueError as e:
        raise SkillValidationError(str(e))
    return skill


SKILL_TEMPLATE = """---
id: my-custom-skill
display_name: 我的自定义技能
description: 在此描述技能的功能和用途
category: custom
enabled: true
agents:
  - researcher
triggers:
  - 关键词1
  - 关键词2
---

# 技能规则

在此编写技能的具体规则和指导内容。

## 使用场景
- 描述该技能适用的场景

## 执行步骤
1. 第一步操作
2. 第二步操作
3. 第三步操作

## 输出格式
描述该技能的输出格式要求
"""


@router.get("/template")
async def get_skill_template():
    """Get a skill file template for creating custom skills"""
    return {
        "template": SKILL_TEMPLATE,
        "format": "YAML frontmatter + Markdown body",
        "instructions": (
            "1. 复制模板内容，修改 id、display_name、description 等字段\n"
            "2. 在 agents 列表中指定关联的 Agent（researcher/reviewer/architect/synthesizer/polisher）\n"
            "3. 在 triggers 列表中添加触发关键词\n"
            "4. 在正文部分编写技能规则\n"
            "5. 通过 POST /api/skills 或 POST /api/skills/upload 创建技能"
        ),
    }