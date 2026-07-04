"""
Knowledge (CNKI) 路由测试
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_knowledge_status(async_client: AsyncClient):
    """测试获取知识库状态"""
    response = await async_client.get("/api/v1/knowledge/status")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "sources" in data or "services" in data


# ── 历史说明（P0 收尾）──────────────────────────────────────
# 下列两个测试已在 P0 收尾阶段删除：
#   - test_cnki_search_empty_query        访问已删除的 /api/v1/knowledge/cnki/search
#   - test_cnki_config_update_requires_auth 访问已删除的 /api/v1/knowledge/cnki/config
# 这两个端点在 P2-T2 死路由清理时已移除（CNKI 集成下线，改由
# /api/v1/knowledge/academic/search 承接学术检索），但对应测试遗留为
# 「半删除」死测试，导致路由删除/前端调用/测试契约之间出现 API 生命周期
# 不一致。审查报告 §1.1 建议统一删除死 Schema/Service/旧测试，此处据此执行。
# 当前 knowledge 路由真实存在的端点为：
#   GET  /api/v1/knowledge/status
#   POST /api/v1/knowledge/academic/search
#   GET  /api/v1/knowledge/keywords/hot