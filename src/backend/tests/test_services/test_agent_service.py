"""
Agent Service 测试
"""
import pytest


@pytest.mark.asyncio
async def test_agent_service_init():
    """测试 AgentService 初始化"""
    from ...services.agent_service import AgentService
    service = AgentService(
        api_key="test-key",
        base_url="https://api.deepseek.com",
    )
    assert service.model == "deepseek-chat"
    assert service.client is not None


@pytest.mark.asyncio
async def test_build_system_prompt_researcher():
    """测试研究员系统提示构建"""
    from ...services.agent_service import AgentService
    service = AgentService(api_key="test-key")
    prompt = await service._build_system_prompt("researcher", None)
    assert "研究员" in prompt
    assert "学术选题" in prompt


@pytest.mark.asyncio
async def test_build_system_prompt_with_context():
    """测试带上下文的系统提示构建"""
    from ...services.agent_service import AgentService
    service = AgentService(api_key="test-key")
    prompt = await service._build_system_prompt(
        "researcher",
        {"discipline": "人文社科", "research_type": "质化研究"},
    )
    assert "人文社科" in prompt
    assert "质化研究" in prompt


@pytest.mark.asyncio
async def test_parse_options():
    """测试选项解析"""
    from ...services.agent_service import AgentService
    service = AgentService(api_key="test-key")

    # 标准格式
    reply = "请选择研究方向\n[选项A|选项B|选项C]"
    options = service._parse_options(reply)
    assert options == ["选项A", "选项B", "选项C"]

    # 无选项
    reply = "这是一个没有选项的回复"
    options = service._parse_options(reply)
    assert options == []


@pytest.mark.asyncio
async def test_detect_skills():
    """测试技能检测"""
    from ...services.agent_service import AgentService
    service = AgentService(api_key="test-key")

    # 图表相关
    reply = "我来为您生成一个和弦图"
    skills = service._detect_skills(reply, "生成图表")
    assert "chart_generation" in skills

    # CNKI 相关
    reply = "建议您检索知网的文献"
    skills = service._detect_skills(reply, "查找文献")
    assert "cnki_search" in skills