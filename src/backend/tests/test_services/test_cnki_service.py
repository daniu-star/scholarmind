"""
CNKI Service 测试
"""


def test_cnki_result_to_dict():
    """测试 CNKIResult 序列化"""
    from ...services.cnki_service import CNKIResult

    result = CNKIResult(
        title="测试文献",
        author="张三",
        year="2024",
        source="测试期刊",
        citations=10,
        core=True,
        abstract="这是一篇测试文献的摘要",
        doi="10.1234/test",
    )

    d = result.to_dict()
    assert d["title"] == "测试文献"
    assert d["citations"] == 10
    assert d["core"] is True


def test_cnki_service_cache_key():
    """测试缓存键生成"""
    from ...services.cnki_service import CNKIService
    service = CNKIService()

    key1 = service._cache_key("人工智能", "2024", 20)
    key2 = service._cache_key("人工智能", "2024", 20)
    key3 = service._cache_key("机器学习", "2024", 20)

    assert key1 == key2
    assert key1 != key3


def test_cnki_service_cache():
    """测试缓存机制"""
    from ...services.cnki_service import CNKIService, CNKIResult
    service = CNKIService()

    results = [CNKIResult(
        title="缓存测试", author="李四", year="2025",
        source="Nature", citations=100, core=True, abstract="测试"
    )]

    key = "cache_test_key"
    cached = service._get_cached(key)
    assert cached is None

    service._set_cached(key, results)
    cached = service._get_cached(key)
    assert cached is not None
    assert cached[0].title == "缓存测试"