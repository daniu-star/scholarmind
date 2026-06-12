"""
Skills Service 测试
"""
import pytest


def test_skills_service_list_presets():
    """测试预设技能列表"""
    from ...services.skills_service import SkillsService, PRESET_SKILLS
    service = SkillsService()

    skills = service.list_all()
    # 至少包含 8 个预设技能
    assert len(skills) >= len(PRESET_SKILLS)


def test_skills_service_get_preset():
    """测试获取预设技能"""
    from ...services.skills_service import SkillsService
    service = SkillsService()

    skill = service.get_skill("academic-researcher")
    assert skill is not None
    assert skill["display_name"] == "学术研究助手"
    assert skill["enabled"] is True


def test_skills_service_toggle():
    """测试切换技能启用状态"""
    from ...services.skills_service import SkillsService
    service = SkillsService()

    # 切换预设技能
    skill = service.toggle_skill("nature-polishing", True)
    assert skill is not None
    assert skill["enabled"] is True

    # 切回
    skill = service.toggle_skill("nature-polishing", False)
    assert skill["enabled"] is False


def test_skills_service_delete_preset_fails():
    """测试删除预设技能（应该失败）"""
    from ...services.skills_service import SkillsService
    service = SkillsService()

    with pytest.raises(ValueError):
        service.delete_skill("academic-researcher")


def test_create_duplicate_skill_fails():
    """测试创建重复技能（应该失败）"""
    from ...services.skills_service import SkillsService
    service = SkillsService()

    with pytest.raises(ValueError):
        service.create_skill({
            "id": "academic-researcher",
            "display_name": "重复技能",
        })