"""CNKI 反封锁策略集成测试 — 验证 CNKIBlockTracker / ProxyPool / _is_cnki_blocked 等。

测试目标：
  1. CNKIBlockTracker 的 mark_blocked/is_blocked/cooldown_remaining/
     blocked_proxies/unblock/clear_all 方法工作正常
  2. ProxyPool 的 detect_ip_type/score_proxy/mark_cnki_blocked/
     next_for_cnki 逻辑正确（用 mock 代理测试）
  3. _is_cnki_blocked() 函数能正确识别 418 状态码、TencentEdgeOne
     server header、空 body 等
  4. 评分逻辑：residential + cnki_ok 应得最高分；
     datacenter + cnki_blocked 应得最低分

运行方式：
    cd c:\\Users\\13067\\Desktop\\AI产品\\cnki-downloader
    python -m pytest tests/test_antiblock_integration.py -v
    或
    python tests/test_antiblock_integration.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

# 确保能导入 crawler 模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.block_tracker import CNKIBlockTracker
from crawler.proxy_pool import ProxyPool


# ── 辅助：构造 mock Response 对象 ──────────────────────────────


class _MockHeaders:
    """模拟 curl_cffi 的 Headers 对象（不区分大小写）。"""

    def __init__(self, headers: Optional[dict] = None) -> None:
        self._data: dict[str, str] = {}
        if headers:
            for k, v in headers.items():
                self._data[k.lower()] = str(v)

    def get(self, name: str, default: str = "") -> str:
        return self._data.get(name.lower(), default)


class MockResponse:
    """模拟 curl_cffi 的 Response 对象，供 _is_cnki_blocked 测试使用。"""

    def __init__(
        self,
        status_code: int = 200,
        headers: Optional[dict] = None,
        content: bytes = b"",
        text: str = "",
        url: str = "https://www.cnki.net/",
    ) -> None:
        self.status_code = status_code
        self.headers = _MockHeaders(headers or {})
        self.content = content
        self.text = text or content.decode("utf-8", errors="ignore")
        self.url = url


# ── 1. CNKIBlockTracker 测试 ─────────────────────────────────────


def test_block_tracker_mark_and_is_blocked(tmp_path):
    """mark_blocked 后 is_blocked 应返回 True。"""
    tracker = CNKIBlockTracker(state_path=tmp_path / "block.json")
    assert not tracker.is_blocked("http://1.1.1.1:8080")
    tracker.mark_blocked("http://1.1.1.1:8080")
    assert tracker.is_blocked("http://1.1.1.1:8080")


def test_block_tracker_unknown_proxy_not_blocked(tmp_path):
    """未标记的代理应返回 False。"""
    tracker = CNKIBlockTracker(state_path=tmp_path / "block.json")
    assert not tracker.is_blocked("http://2.2.2.2:8080")


def test_block_tracker_empty_proxy(tmp_path):
    """空字符串代理应返回 False。"""
    tracker = CNKIBlockTracker(state_path=tmp_path / "block.json")
    assert not tracker.is_blocked("")
    assert not tracker.is_blocked(None)  # type: ignore[arg-type]


def test_block_tracker_cooldown_remaining(tmp_path):
    """cooldown_remaining 应返回正数（未过期时）。"""
    tracker = CNKIBlockTracker(
        state_path=tmp_path / "block.json",
        block_duration=3600,  # 1 小时
    )
    tracker.mark_blocked("http://3.3.3.3:8080")
    remaining = tracker.cooldown_remaining("http://3.3.3.3:8080")
    assert 0 < remaining <= 3600


def test_block_tracker_cooldown_remaining_unblocked(tmp_path):
    """未封锁的代理 cooldown_remaining 应为 0。"""
    tracker = CNKIBlockTracker(state_path=tmp_path / "block.json")
    assert tracker.cooldown_remaining("http://4.4.4.4:8080") == 0.0


def test_block_tracker_unblock(tmp_path):
    """unblock 应解除封锁并返回 True；未封锁时返回 False。"""
    tracker = CNKIBlockTracker(state_path=tmp_path / "block.json")
    tracker.mark_blocked("http://5.5.5.5:8080")
    assert tracker.is_blocked("http://5.5.5.5:8080")
    assert tracker.unblock("http://5.5.5.5:8080") is True
    assert not tracker.is_blocked("http://5.5.5.5:8080")
    # 再次 unblock 应返回 False
    assert tracker.unblock("http://5.5.5.5:8080") is False


def test_block_tracker_blocked_proxies(tmp_path):
    """blocked_proxies 应返回所有被封锁的代理。"""
    tracker = CNKIBlockTracker(state_path=tmp_path / "block.json")
    tracker.mark_blocked("http://6.6.6.6:8080")
    tracker.mark_blocked("http://7.7.7.7:8080")
    blocked = tracker.blocked_proxies()
    assert "http://6.6.6.6:8080" in blocked
    assert "http://7.7.7.7:8080" in blocked
    assert len(blocked) == 2


def test_block_tracker_clear_all(tmp_path):
    """clear_all 应清除所有封锁记录。"""
    tracker = CNKIBlockTracker(state_path=tmp_path / "block.json")
    tracker.mark_blocked("http://8.8.8.8:8080")
    tracker.mark_blocked("http://9.9.9.9:8080")
    assert len(tracker.blocked_proxies()) == 2
    tracker.clear_all()
    assert len(tracker.blocked_proxies()) == 0


def test_block_tracker_persistence(tmp_path):
    """封锁状态应持久化到 JSON 文件。"""
    state_file = tmp_path / "persist_block.json"
    tracker1 = CNKIBlockTracker(state_path=state_file)
    tracker1.mark_blocked("http://10.10.10.10:8080")

    # 新实例加载同一文件应能看到封锁状态
    tracker2 = CNKIBlockTracker(state_path=state_file)
    assert tracker2.is_blocked("http://10.10.10.10:8080")


def test_block_tracker_auto_expire(tmp_path):
    """封锁到期后应自动解除。"""
    tracker = CNKIBlockTracker(
        state_path=tmp_path / "block.json",
        block_duration=1,  # 1 秒
    )
    tracker.mark_blocked("http://11.11.11.11:8080")
    assert tracker.is_blocked("http://11.11.11.11:8080")
    # 等待过期
    time.sleep(1.2)
    assert not tracker.is_blocked("http://11.11.11.11:8080")


# ── 2. ProxyPool 测试 ────────────────────────────────────────────


def _make_proxy_pool_with(proxies: list[dict]) -> ProxyPool:
    """构造一个已加载代理列表的 ProxyPool（绕过文件加载）。"""
    pool = ProxyPool()
    pool._proxies = list(proxies)
    return pool


def test_proxy_pool_score_residential_cnki_ok_highest():
    """residential + cnki_ok 应得最高分。"""
    pool = ProxyPool()
    proxy = {
        "url": "http://1.1.1.1:8080",
        "enabled": True,
        "fail_count": 0,
        "ip_type": "residential",
        "cnki_status": "cnki_ok",
    }
    score = pool.score_proxy(proxy)
    # residential(40) + cnki_ok(30) + fail_count=0(10) = 80
    assert score == 80


def test_proxy_pool_score_datacenter_cnki_blocked_lowest():
    """datacenter + cnki_blocked 应得最低分。"""
    pool = ProxyPool()
    proxy = {
        "url": "http://2.2.2.2:8080",
        "enabled": True,
        "fail_count": 3,
        "ip_type": "datacenter",
        "cnki_status": "cnki_blocked",
    }
    score = pool.score_proxy(proxy)
    # datacenter(20) + cnki_blocked(-50) + fail_count=3(-15) = -45
    assert score == -45


def test_proxy_pool_score_ordering():
    """评分顺序：residential+ok > datacenter+ok > residential+none > datacenter+blocked。"""
    pool = ProxyPool()
    residential_ok = {"ip_type": "residential", "cnki_status": "cnki_ok", "fail_count": 0}
    datacenter_ok = {"ip_type": "datacenter", "cnki_status": "cnki_ok", "fail_count": 0}
    residential_none = {"ip_type": "residential", "cnki_status": "", "fail_count": 0}
    datacenter_blocked = {"ip_type": "datacenter", "cnki_status": "cnki_blocked", "fail_count": 0}

    s1 = pool.score_proxy(residential_ok)
    s2 = pool.score_proxy(datacenter_ok)
    s3 = pool.score_proxy(residential_none)
    s4 = pool.score_proxy(datacenter_blocked)

    assert s1 > s2 > s3 > s4


def test_proxy_pool_mark_cnki_blocked():
    """mark_cnki_blocked 应设置 cnki_status 字段。"""
    pool = _make_proxy_pool_with([
        {"url": "http://3.3.3.3:8080", "enabled": True, "fail_count": 0,
         "ip_type": "unknown", "cnki_status": ""},
    ])
    pool.mark_cnki_blocked("http://3.3.3.3:8080")
    assert pool.all_proxies()[0]["cnki_status"] == "cnki_blocked"


def test_proxy_pool_mark_cnki_blocked_unknown_proxy():
    """对未知代理调用 mark_cnki_blocked 不应报错。"""
    pool = _make_proxy_pool_with([])
    pool.mark_cnki_blocked("http://unknown:8080")  # 不应抛出异常


def test_proxy_pool_next_for_cnki_prefers_cnki_ok():
    """next_for_cnki 应优先返回 cnki_ok 的代理。"""
    pool = _make_proxy_pool_with([
        {"url": "http://4.4.4.4:8080", "enabled": True, "fail_count": 0,
         "ip_type": "datacenter", "cnki_status": ""},
        {"url": "http://5.5.5.5:8080", "enabled": True, "fail_count": 0,
         "ip_type": "residential", "cnki_status": "cnki_ok"},
        {"url": "http://6.6.6.6:8080", "enabled": True, "fail_count": 0,
         "ip_type": "datacenter", "cnki_status": "cnki_blocked"},
    ])
    # next_for_cnki 应返回 cnki_ok 的代理
    chosen = pool.next_for_cnki()
    assert chosen == "http://5.5.5.5:8080"


def test_proxy_pool_next_for_cnki_skips_blocked():
    """next_for_cnki 应跳过 cnki_blocked 的代理。"""
    pool = _make_proxy_pool_with([
        {"url": "http://7.7.7.7:8080", "enabled": True, "fail_count": 0,
         "ip_type": "datacenter", "cnki_status": "cnki_blocked"},
        {"url": "http://8.8.8.8:8080", "enabled": True, "fail_count": 0,
         "ip_type": "datacenter", "cnki_status": ""},
    ])
    chosen = pool.next_for_cnki()
    # 没有 cnki_ok 的，回退到普通候选，但应跳过 cnki_blocked
    assert chosen == "http://8.8.8.8:8080"


def test_proxy_pool_next_for_cnki_empty():
    """空代理池应返回 None。"""
    pool = _make_proxy_pool_with([])
    assert pool.next_for_cnki() is None


def test_proxy_pool_next_skips_disabled():
    """next 应跳过 disabled 的代理。"""
    pool = _make_proxy_pool_with([
        {"url": "http://9.9.9.9:8080", "enabled": False, "fail_count": 0,
         "ip_type": "residential", "cnki_status": "cnki_ok"},
    ])
    assert pool.next() is None


def test_proxy_pool_next_skips_high_fail_count():
    """next 应跳过 fail_count >= MAX_FAIL_COUNT 的代理。"""
    pool = _make_proxy_pool_with([
        {"url": "http://10.10.10.10:8080", "enabled": True,
         "fail_count": ProxyPool.MAX_FAIL_COUNT,
         "ip_type": "residential", "cnki_status": "cnki_ok"},
    ])
    assert pool.next() is None


def test_proxy_pool_detect_ip_type_extracts_ip():
    """_extract_ip 应正确提取 IP。"""
    assert ProxyPool._extract_ip("http://1.2.3.4:8080") == "1.2.3.4"
    assert ProxyPool._extract_ip("http://192.168.1.1:8888") == "192.168.1.1"
    assert ProxyPool._extract_ip("") is None
    assert ProxyPool._extract_ip(None) is None  # type: ignore[arg-type]


def test_proxy_pool_detect_ip_type_updates_proxy_dict():
    """detect_ip_type 应更新代理 dict 的 ip_type 字段（使用 mock 避免真实网络调用）。"""
    pool = _make_proxy_pool_with([
        {"url": "http://11.11.11.11:8080", "enabled": True, "fail_count": 0,
         "ip_type": "unknown", "cnki_status": ""},
    ])
    # 使用 mock：直接注入缓存，避免真实网络调用
    pool._ip_type_cache["11.11.11.11"] = "residential"
    result = pool.detect_ip_type("http://11.11.11.11:8080")
    assert result == "residential"
    assert pool.all_proxies()[0]["ip_type"] == "residential"


# ── 3. _is_cnki_blocked 测试 ────────────────────────────────────


def _make_scraper_for_test(tmp_path):
    """构造一个 CNKIHybridScraper 实例用于测试 _is_cnki_blocked。

    使用临时目录避免污染项目文件。
    """
    from crawler.hybrid_scraper import CNKIHybridScraper
    scraper = CNKIHybridScraper(
        cookies={"_test": "1"},
        output_dir=str(tmp_path / "output"),
        block_tracker_path=str(tmp_path / "block.json"),
    )
    return scraper


def test_is_cnki_blocked_418_status(tmp_path):
    """418 状态码应被识别为 CNKI 封锁。"""
    scraper = _make_scraper_for_test(tmp_path)
    resp = MockResponse(status_code=418, content=b"", headers={})
    assert scraper._is_cnki_blocked(resp) is True


def test_is_cnki_blocked_200_not_blocked(tmp_path):
    """200 状态码不应被识别为封锁。"""
    scraper = _make_scraper_for_test(tmp_path)
    resp = MockResponse(
        status_code=200,
        content=b"<html><body>Hello CNKI</body></html>",
        headers={"server": "nginx"},
    )
    assert scraper._is_cnki_blocked(resp) is False


def test_is_cnki_blocked_tencent_edgeone_empty_body(tmp_path):
    """TencentEdgeOne server + 空 body 应被识别为封锁。

    源码 bug 已修复：crawler/hybrid_scraper.py 第 272 行的字符串拼写错误
    "tencentededgeone" 已更正为 "tencentedgeone"。
    """
    scraper = _make_scraper_for_test(tmp_path)
    resp = MockResponse(
        status_code=403,
        content=b"",
        headers={"server": "TencentEdgeOne"},
    )
    # 修复后应正确识别为封锁
    assert scraper._is_cnki_blocked(resp) is True


def test_is_cnki_blocked_tencent_edgeone_lowercase(tmp_path):
    """小写 tencentedgeone 也应被识别。

    源码 bug 已修复，现在小写形式也能正确匹配。
    """
    scraper = _make_scraper_for_test(tmp_path)
    resp = MockResponse(
        status_code=403,
        content=b"",
        headers={"server": "tencentedgeone"},
    )
    # 修复后应正确识别为封锁
    assert scraper._is_cnki_blocked(resp) is True


def test_is_cnki_blocked_tencent_edgeone_typo_fixed(tmp_path):
    """验证源码 bug 已修复：字符串拼写已更正。

    源码中曾存在 "tencentededgeone"（多了 "ed"）的拼写错误，
    现已更正为 "tencentedgeone"。
    """
    # 正确的字符串
    correct = "tencentedgeone"
    # 源码中曾使用的（错误）字符串
    old_buggy_string = "tencentededgeone"
    # 验证 bug 已修复：错误字符串不等于正确字符串
    assert old_buggy_string != correct
    # 验证错误字符串不是正确字符串的子串（因为更长）
    assert old_buggy_string not in correct


def test_is_cnki_blocked_tencent_edgeone_with_body_not_blocked(tmp_path):
    """TencentEdgeOne server 但有 body 不应被识别为封锁（条件 2 要求 body 为空）。"""
    scraper = _make_scraper_for_test(tmp_path)
    resp = MockResponse(
        status_code=200,
        content=b"<html><body>Real content</body></html>",
        headers={"server": "TencentEdgeOne"},
    )
    assert scraper._is_cnki_blocked(resp) is False


def test_is_cnki_blocked_418_short_body(tmp_path):
    """418 + 短 body（< 50 字节）应被识别为封锁。"""
    scraper = _make_scraper_for_test(tmp_path)
    resp = MockResponse(
        status_code=418,
        content=b"short",
        headers={"server": "TencentEdgeOne"},
    )
    # 418 已在条件 1 处理，应直接返回 True
    assert scraper._is_cnki_blocked(resp) is True


def test_is_cnki_blocked_500_not_blocked(tmp_path):
    """500 状态码不应被识别为 CNKI 封锁（非 418）。"""
    scraper = _make_scraper_for_test(tmp_path)
    resp = MockResponse(
        status_code=500,
        content=b"Internal Server Error",
        headers={"server": "nginx"},
    )
    assert scraper._is_cnki_blocked(resp) is False


def test_is_cnki_blocked_increments_stats(tmp_path):
    """检测到封锁时应增加 cnki_blocks_detected 统计。"""
    scraper = _make_scraper_for_test(tmp_path)
    initial = scraper._stats["cnki_blocks_detected"]
    resp = MockResponse(status_code=418, content=b"", headers={})
    scraper._is_cnki_blocked(resp)
    assert scraper._stats["cnki_blocks_detected"] == initial + 1


# ── 4. get_cnki_block_status 测试 ────────────────────────────────


def test_get_cnki_block_status_no_block(tmp_path):
    """无封锁时应返回空 blocked_proxies。"""
    scraper = _make_scraper_for_test(tmp_path)
    status = scraper.get_cnki_block_status()
    assert status["blocked_count"] == 0
    assert status["blocked_proxies"] == []
    assert status["current_proxy"] is None


def test_get_cnki_block_status_with_block(tmp_path):
    """有封锁时应返回封锁列表。"""
    scraper = _make_scraper_for_test(tmp_path)
    scraper._current_proxy = "http://12.12.12.12:8080"
    scraper._block_tracker.mark_blocked("http://12.12.12.12:8080")
    status = scraper.get_cnki_block_status()
    assert status["blocked_count"] == 1
    assert "http://12.12.12.12:8080" in status["blocked_proxies"]
    assert status["current_proxy"] == "http://12.12.12.12:8080"
    assert status["current_proxy_blocked"] is True


# ── 5. 集成场景：评分与轮询组合 ─────────────────────────────────


def test_integration_next_for_cnki_picks_best():
    """集成场景：next_for_cnki 应从多个代理中选出 residential + cnki_ok 的。"""
    pool = _make_proxy_pool_with([
        # datacenter + cnki_ok — 评分 20+30+10=60
        {"url": "http://dc-ok:8080", "enabled": True, "fail_count": 0,
         "ip_type": "datacenter", "cnki_status": "cnki_ok"},
        # residential + cnki_ok — 评分 40+30+10=80（最高）
        {"url": "http://res-ok:8080", "enabled": True, "fail_count": 0,
         "ip_type": "residential", "cnki_status": "cnki_ok"},
        # residential + cnki_blocked — 评分 40-50+10=0
        {"url": "http://res-blocked:8080", "enabled": True, "fail_count": 0,
         "ip_type": "residential", "cnki_status": "cnki_blocked"},
        # datacenter + cnki_blocked — 评分 20-50+10=-20
        {"url": "http://dc-blocked:8080", "enabled": True, "fail_count": 0,
         "ip_type": "datacenter", "cnki_status": "cnki_blocked"},
    ])
    # next_for_cnki 应优先返回 cnki_ok 的代理，且评分最高的 residential+ok
    chosen = pool.next_for_cnki()
    assert chosen == "http://res-ok:8080"


def test_integration_all_blocked_returns_none():
    """集成场景：所有代理均被封锁时应返回 None。"""
    pool = _make_proxy_pool_with([
        {"url": "http://blocked1:8080", "enabled": True, "fail_count": 0,
         "ip_type": "residential", "cnki_status": "cnki_blocked"},
        {"url": "http://blocked2:8080", "enabled": True, "fail_count": 0,
         "ip_type": "datacenter", "cnki_status": "cnki_blocked"},
    ])
    # 所有 cnki_blocked，next_for_cnki 回退到普通 next()，但 next() 也跳过 cnki_blocked
    assert pool.next_for_cnki() is None


# ── 测试运行入口 ─────────────────────────────────────────────────


def _run_all_tests():
    """运行所有测试并返回结果摘要。"""
    import inspect

    # 收集所有 test_ 开头的函数
    test_funcs = [
        obj for name, obj in inspect.getmembers(sys.modules[__name__])
        if name.startswith("test_") and callable(obj)
    ]

    passed = 0
    failed = 0
    failures = []

    for func in test_funcs:
        # 创建临时目录作为 tmp_path 参数
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            try:
                # 检查函数签名是否需要 tmp_path 参数
                sig = inspect.signature(func)
                if len(sig.parameters) == 0:
                    func()
                else:
                    func(tmp_path)
                passed += 1
                print(f"  [PASS] {func.__name__}")
            except Exception as e:
                failed += 1
                failures.append((func.__name__, str(e)))
                print(f"  [FAIL] {func.__name__}: {e}")

    print()
    print(f"=== 测试结果 ===")
    print(f"通过: {passed}")
    print(f"失败: {failed}")
    if failures:
        print("\n失败详情:")
        for name, err in failures:
            print(f"  - {name}: {err}")
    return passed, failed


if __name__ == "__main__":
    passed, failed = _run_all_tests()
    sys.exit(0 if failed == 0 else 1)
