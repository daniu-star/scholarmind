"""CNKI 反封锁系统 — 集成验证测试脚本。

验证内容：
  1. 模块导入：FreeProxyFetcher / CNKIBlockTracker / ProxyPool / CNKIHybridScraper
  2. ProxyPool 加载 proxies.json
  3. CNKIBlockTracker 的 mark_blocked / is_blocked / cooldown_remaining
  4. ProxyPool.score_proxy() 评分规则（residential+cnki_ok 最高，cnki_blocked 最低）
  5. CNKIHybridScraper._is_cnki_blocked 逻辑（构造 mock Response）

运行方式：
    python -m tests.test_integration_verify
    或
    python tests/test_integration_verify.py
"""
from __future__ import annotations

import os
import sys
import time
import tempfile
import json
from pathlib import Path
from typing import Optional

# 确保项目根目录在 sys.path 中（支持 python tests/xxx.py 直接运行）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ── 测试结果收集 ──────────────────────────────────────────────
_RESULTS: list[dict] = []


def _record(name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append({
        "name": name,
        "passed": passed,
        "detail": detail,
    })
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


def _section(title: str) -> None:
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


# ── Mock Response 对象（用于 _is_cnki_blocked 测试） ─────────
class MockResponse:
    """模拟 curl_cffi.requests.Response，仅实现 _is_cnki_blocked 所需字段。"""

    def __init__(
        self,
        status_code: int = 200,
        server: str = "",
        content: bytes = b"",
        url: str = "https://www.cnki.net/",
    ) -> None:
        self.status_code = status_code
        self.url = url
        self._content = content
        self._headers = {"server": server} if server else {}

    @property
    def headers(self) -> dict:
        return self._headers

    @property
    def content(self) -> bytes:
        return self._content

    @property
    def text(self) -> str:
        try:
            return self._content.decode("utf-8", errors="replace")
        except Exception:
            return ""


# ── 测试用例 ──────────────────────────────────────────────────

def test_imports() -> None:
    """测试 1: 导入所有新模块。"""
    _section("测试 1: 模块导入")
    errors = []

    try:
        from crawler.free_proxy_fetcher import FreeProxyFetcher
        _record("导入 FreeProxyFetcher", True, f"类: {FreeProxyFetcher.__name__}")
    except Exception as e:
        errors.append(f"FreeProxyFetcher: {e}")
        _record("导入 FreeProxyFetcher", False, str(e))

    try:
        from crawler.block_tracker import CNKIBlockTracker
        _record("导入 CNKIBlockTracker", True, f"类: {CNKIBlockTracker.__name__}")
    except Exception as e:
        errors.append(f"CNKIBlockTracker: {e}")
        _record("导入 CNKIBlockTracker", False, str(e))

    try:
        from crawler.proxy_pool import ProxyPool
        _record("导入 ProxyPool", True, f"类: {ProxyPool.__name__}")
    except Exception as e:
        errors.append(f"ProxyPool: {e}")
        _record("导入 ProxyPool", False, str(e))

    try:
        from crawler.hybrid_scraper import CNKIHybridScraper
        _record("导入 CNKIHybridScraper", True, f"类: {CNKIHybridScraper.__name__}")
    except Exception as e:
        errors.append(f"CNKIHybridScraper: {e}")
        _record("导入 CNKIHybridScraper", False, str(e))

    # 验证关键方法/属性存在
    try:
        from crawler.proxy_pool import ProxyPool
        assert hasattr(ProxyPool, "detect_ip_type"), "ProxyPool.detect_ip_type 缺失"
        assert hasattr(ProxyPool, "score_proxy"), "ProxyPool.score_proxy 缺失"
        assert hasattr(ProxyPool, "next_for_cnki"), "ProxyPool.next_for_cnki 缺失"
        assert hasattr(ProxyPool, "refresh_free_proxies"), "ProxyPool.refresh_free_proxies 缺失"
        assert hasattr(ProxyPool, "mark_cnki_blocked"), "ProxyPool.mark_cnki_blocked 缺失"
        assert hasattr(ProxyPool, "_probe_cnki"), "ProxyPool._probe_cnki 缺失"
        _record("ProxyPool 关键方法齐全", True,
                "detect_ip_type/score_proxy/next_for_cnki/refresh_free_proxies/mark_cnki_blocked/_probe_cnki")
    except AssertionError as e:
        _record("ProxyPool 关键方法齐全", False, str(e))
    except Exception as e:
        _record("ProxyPool 关键方法齐全", False, f"异常: {e}")

    try:
        from crawler.hybrid_scraper import CNKIHybridScraper
        assert hasattr(CNKIHybridScraper, "_is_cnki_blocked"), "_is_cnki_blocked 缺失"
        assert hasattr(CNKIHybridScraper, "_switch_proxy_for_cnki"), "_switch_proxy_for_cnki 缺失"
        assert hasattr(CNKIHybridScraper, "_request_with_cnki_retry"), "_request_with_cnki_retry 缺失"
        assert hasattr(CNKIHybridScraper, "_browser_fallback_with_proxies"), "_browser_fallback_with_proxies 缺失"
        assert hasattr(CNKIHybridScraper, "get_cnki_block_status"), "get_cnki_block_status 缺失"
        _record("CNKIHybridScraper 关键方法齐全", True,
                "_is_cnki_blocked/_switch_proxy_for_cnki/_request_with_cnki_retry/_browser_fallback_with_proxies/get_cnki_block_status")
    except AssertionError as e:
        _record("CNKIHybridScraper 关键方法齐全", False, str(e))
    except Exception as e:
        _record("CNKIHybridScraper 关键方法齐全", False, f"异常: {e}")


def test_proxy_pool_load() -> None:
    """测试 2: ProxyPool 加载 proxies.json。"""
    _section("测试 2: ProxyPool 加载 proxies.json")
    proxies_path = _PROJECT_ROOT / "proxies.json"
    if not proxies_path.exists():
        _record("proxies.json 存在", False, f"路径: {proxies_path}")
        return
    _record("proxies.json 存在", True, f"路径: {proxies_path}")

    try:
        from crawler.proxy_pool import ProxyPool
        pool = ProxyPool()
        count = pool.load(str(proxies_path))
        all_p = pool.all_proxies()
        _record("ProxyPool.load() 返回数量",
                count > 0,
                f"加载 {count} 个代理")
        # 验证字段规范化
        if all_p:
            first = all_p[0]
            required = {"url", "enabled", "fail_count", "ip_type", "cnki_status", "source"}
            missing = required - set(first.keys())
            _record("代理字段规范化",
                    not missing,
                    f"首条代理字段: {sorted(first.keys())}")
        else:
            _record("代理字段规范化", False, "代理列表为空")
    except Exception as e:
        _record("ProxyPool.load() 异常", False, str(e))


def test_block_tracker() -> None:
    """测试 3: CNKIBlockTracker 的 mark_blocked / is_blocked / cooldown_remaining。"""
    _section("测试 3: CNKIBlockTracker 功能")

    # 使用临时文件避免污染正式状态
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "test_block_status.json"
        try:
            from crawler.block_tracker import CNKIBlockTracker
            tracker = CNKIBlockTracker(state_path=state_path, block_duration=60)
        except Exception as e:
            _record("CNKIBlockTracker 实例化", False, str(e))
            return
        _record("CNKIBlockTracker 实例化", True, f"block_duration=60s")

        # 初始状态：无封锁
        try:
            assert tracker.is_blocked("http://1.2.3.4:8080") is False, "初始状态应未封锁"
            _record("初始 is_blocked=False", True)
        except AssertionError as e:
            _record("初始 is_blocked=False", False, str(e))

        # 标记封锁
        test_proxy = "http://9.9.9.9:8080"
        try:
            tracker.mark_blocked(test_proxy)
            assert tracker.is_blocked(test_proxy), "mark_blocked 后应被封锁"
            _record("mark_blocked → is_blocked=True", True)
        except AssertionError as e:
            _record("mark_blocked → is_blocked=True", False, str(e))

        # 冷却剩余时间
        try:
            remaining = tracker.cooldown_remaining(test_proxy)
            assert 0 < remaining <= 60, f"剩余冷却应在 (0, 60]，实际: {remaining}"
            _record("cooldown_remaining 在合理范围", True, f"剩余 {remaining:.1f}s (≤60s)")
        except AssertionError as e:
            _record("cooldown_remaining 在合理范围", False, str(e))

        # 持久化：重新加载应保留封锁状态
        try:
            tracker2 = CNKIBlockTracker(state_path=state_path, block_duration=60)
            assert tracker2.is_blocked(test_proxy), "重新加载后封锁状态应保留"
            _record("持久化加载保留封锁状态", True)
        except AssertionError as e:
            _record("持久化加载保留封锁状态", False, str(e))

        # 手动解除
        try:
            assert tracker.unblock(test_proxy), "unblock 应返回 True"
            assert not tracker.is_blocked(test_proxy), "unblock 后应未封锁"
            _record("unblock 手动解除", True)
        except AssertionError as e:
            _record("unblock 手动解除", False, str(e))

        # blocked_proxies 列表
        try:
            tracker.mark_blocked("http://10.0.0.1:80")
            tracker.mark_blocked("http://10.0.0.2:80")
            blocked = tracker.blocked_proxies()
            assert len(blocked) == 2, f"应有 2 个被封锁，实际: {len(blocked)}"
            _record("blocked_proxies 列表", True, f"{len(blocked)} 个被封锁")
        except AssertionError as e:
            _record("blocked_proxies 列表", False, str(e))

        # 过期自动清理
        try:
            tracker3 = CNKIBlockTracker(state_path=state_path, block_duration=1)
            tracker3.mark_blocked("http://11.0.0.1:80")
            time.sleep(1.2)
            assert not tracker3.is_blocked("http://11.0.0.1:80"), "过期后应自动解除"
            _record("过期自动清理", True, "block_duration=1s, sleep 1.2s 后解除")
        except AssertionError as e:
            _record("过期自动清理", False, str(e))


def test_score_proxy() -> None:
    """测试 4: ProxyPool.score_proxy() 评分规则。"""
    _section("测试 4: ProxyPool.score_proxy() 评分")

    try:
        from crawler.proxy_pool import ProxyPool
        pool = ProxyPool()
    except Exception as e:
        _record("ProxyPool 实例化", False, str(e))
        return

    # 构造不同类型的代理
    residential_ok = {
        "url": "http://1.1.1.1:80",
        "ip_type": "residential",
        "cnki_status": "cnki_ok",
        "fail_count": 0,
    }
    datacenter_ok = {
        "url": "http://2.2.2.2:80",
        "ip_type": "datacenter",
        "cnki_status": "cnki_ok",
        "fail_count": 0,
    }
    residential_blocked = {
        "url": "http://3.3.3.3:80",
        "ip_type": "residential",
        "cnki_status": "cnki_blocked",
        "fail_count": 3,
    }
    unknown_neutral = {
        "url": "http://4.4.4.4:80",
        "ip_type": "unknown",
        "cnki_status": "",
        "fail_count": 0,
    }
    datacenter_blocked = {
        "url": "http://5.5.5.5:80",
        "ip_type": "datacenter",
        "cnki_status": "cnki_blocked",
        "fail_count": 5,
    }

    try:
        score_res_ok = pool.score_proxy(residential_ok)
        score_dc_ok = pool.score_proxy(datacenter_ok)
        score_res_blocked = pool.score_proxy(residential_blocked)
        score_unknown = pool.score_proxy(unknown_neutral)
        score_dc_blocked = pool.score_proxy(datacenter_blocked)

        # 期望：residential+cnki_ok (+40+30+10=80) 最高
        #       datacenter+cnki_ok (+20+30+10=60)
        #       unknown+neutral (+0+0+10=10)
        #       residential+cnki_blocked+fail3 (+40-50-15=-25)
        #       datacenter+cnki_blocked+fail5 (+20-50-25=-55) 最低

        _record("residential+cnki_ok 评分",
                score_res_ok == 80,
                f"score={score_res_ok} (期望 80: +40+30+10)")

        _record("datacenter+cnki_ok 评分",
                score_dc_ok == 60,
                f"score={score_dc_ok} (期望 60: +20+30+10)")

        _record("unknown+neutral 评分",
                score_unknown == 10,
                f"score={score_unknown} (期望 10: +0+0+10)")

        _record("residential+cnki_blocked+fail3 评分",
                score_res_blocked == -25,
                f"score={score_res_blocked} (期望 -25: +40-50-15)")

        _record("datacenter+cnki_blocked+fail5 评分",
                score_dc_blocked == -55,
                f"score={score_dc_blocked} (期望 -55: +20-50-25)")

        # 关键断言：residential+cnki_ok 最高，cnki_blocked 最低
        _record("residential+cnki_ok 评分最高",
                score_res_ok == max(score_res_ok, score_dc_ok, score_res_blocked, score_unknown, score_dc_blocked),
                f"max={max(score_res_ok, score_dc_ok, score_res_blocked, score_unknown, score_dc_blocked)}")

        _record("datacenter+cnki_blocked+fail5 评分最低",
                score_dc_blocked == min(score_res_ok, score_dc_ok, score_res_blocked, score_unknown, score_dc_blocked),
                f"min={min(score_res_ok, score_dc_ok, score_res_blocked, score_unknown, score_dc_blocked)}")

        _record("cnki_blocked 比 cnki_ok 评分低",
                score_res_blocked < score_res_ok,
                f"blocked={score_res_blocked} < ok={score_res_ok}")

    except AssertionError as e:
        _record("评分规则断言", False, str(e))
    except Exception as e:
        _record("评分规则异常", False, str(e))


def test_next_for_cnki_filtering() -> None:
    """测试 5: ProxyPool.next_for_cnki() 跳过 cnki_blocked 代理。"""
    _section("测试 5: ProxyPool.next_for_cnki() 过滤")

    try:
        from crawler.proxy_pool import ProxyPool
        pool = ProxyPool()
        # 手动注入测试代理（绕过 load）
        pool._proxies = [
            {"url": "http://blocked-1:80", "enabled": True, "fail_count": 0,
             "ip_type": "residential", "cnki_status": "cnki_blocked"},
            {"url": "http://blocked-2:80", "enabled": True, "fail_count": 0,
             "ip_type": "residential", "cnki_status": "cnki_blocked"},
            {"url": "http://ok-1:80", "enabled": True, "fail_count": 0,
             "ip_type": "residential", "cnki_status": "cnki_ok"},
        ]

        # next_for_cnki 应仅返回 cnki_ok 的代理
        results = set()
        for _ in range(5):
            url = pool.next_for_cnki()
            if url:
                results.add(url)
        _record("next_for_cnki 仅返回 cnki_ok",
                results == {"http://ok-1:80"},
                f"返回集合: {results}")

        # 全部 blocked 时回退到普通候选（不含 blocked）
        pool._proxies = [
            {"url": "http://blocked-3:80", "enabled": True, "fail_count": 0,
             "ip_type": "residential", "cnki_status": "cnki_blocked"},
            {"url": "http://neutral-1:80", "enabled": True, "fail_count": 0,
             "ip_type": "unknown", "cnki_status": ""},
        ]
        url = pool.next_for_cnki()
        # 无 cnki_ok 时回退到普通候选，但跳过 cnki_blocked
        _record("无 cnki_ok 时回退普通候选",
                url == "http://neutral-1:80",
                f"返回: {url}")

    except Exception as e:
        _record("next_for_cnki 测试异常", False, str(e))


def test_is_cnki_blocked_logic() -> None:
    """测试 6: CNKIHybridScraper._is_cnki_blocked 逻辑。"""
    _section("测试 6: _is_cnki_blocked 检测逻辑")

    try:
        from crawler.hybrid_scraper import CNKIHybridScraper
        # 创建实例（不实际发起请求，仅用其方法）
        scraper = CNKIHybridScraper(cookies={"_test": "1"}, output_dir=str(_PROJECT_ROOT / "tests" / "output"))
    except Exception as e:
        _record("CNKIHybridScraper 实例化", False, str(e))
        return
    _record("CNKIHybridScraper 实例化", True)

    # 测试用例 1: HTTP 418 → 应被识别为封锁
    try:
        resp = MockResponse(status_code=418, server="TencentEdgeOne", content=b"")
        assert scraper._is_cnki_blocked(resp) is True, "418 应识别为封锁"
        _record("HTTP 418 识别为封锁", True)
    except AssertionError as e:
        _record("HTTP 418 识别为封锁", False, str(e))

    # 测试用例 2: server=TencentEdgeOne 且 body 为空 → 封锁
    try:
        resp = MockResponse(status_code=200, server="TencentEdgeOne", content=b"")
        assert scraper._is_cnki_blocked(resp) is True, "EdgeOne+空body 应识别为封锁"
        _record("EdgeOne + 空 body 识别为封锁", True)
    except AssertionError as e:
        _record("EdgeOne + 空 body 识别为封锁", False, str(e))

    # 测试用例 3: HTTP 200 正常响应 → 不封锁
    try:
        resp = MockResponse(
            status_code=200,
            server="nginx",
            content=b"<html><body>CNKI homepage content here, long enough</body></html>"
        )
        assert scraper._is_cnki_blocked(resp) is False, "200 正常响应不应识别为封锁"
        _record("HTTP 200 正常响应不封锁", True)
    except AssertionError as e:
        _record("HTTP 200 正常响应不封锁", False, str(e))

    # 测试用例 4: HTTP 403 → 不视为 CNKI 封锁（418 专用）
    try:
        resp = MockResponse(status_code=403, server="nginx", content=b"<html>forbidden</html>")
        assert scraper._is_cnki_blocked(resp) is False, "403 不应识别为 418 封锁"
        _record("HTTP 403 不识别为 418 封锁", True)
    except AssertionError as e:
        _record("HTTP 403 不识别为 418 封锁", False, str(e))

    # 测试用例 5: 检测到封锁后 stats 应自增
    try:
        before = scraper._stats.get("cnki_blocks_detected", 0)
        resp = MockResponse(status_code=418, server="TencentEdgeOne", content=b"")
        scraper._is_cnki_blocked(resp)
        after = scraper._stats.get("cnki_blocks_detected", 0)
        assert after == before + 1, f"cnki_blocks_detected 应 +1, before={before}, after={after}"
        _record("检测到封锁后 stats 自增", True, f"before={before}, after={after}")
    except AssertionError as e:
        _record("检测到封锁后 stats 自增", False, str(e))


def test_get_cnki_block_status() -> None:
    """测试 7: get_cnki_block_status() 返回结构。"""
    _section("测试 7: get_cnki_block_status() 返回结构")

    try:
        from crawler.hybrid_scraper import CNKIHybridScraper
        scraper = CNKIHybridScraper(cookies={"_test": "1"}, output_dir=str(_PROJECT_ROOT / "tests" / "output"))
        status = scraper.get_cnki_block_status()
        required_keys = {
            "blocked_proxies", "blocked_count", "available_proxies",
            "current_proxy", "current_proxy_blocked", "cooldown_remaining"
        }
        missing = required_keys - set(status.keys())
        _record("返回结构包含所有必需字段",
                not missing,
                f"字段: {sorted(status.keys())}")
        # 验证类型
        _record("blocked_count 为 int",
                isinstance(status["blocked_count"], int),
                f"值: {status['blocked_count']}")
        _record("available_proxies 为 int",
                isinstance(status["available_proxies"], int),
                f"值: {status['available_proxies']}")
    except Exception as e:
        _record("get_cnki_block_status 异常", False, str(e))


def main() -> int:
    """运行所有测试并返回退出码。"""
    print()
    print("#" * 70)
    print("#  CNKI 反封锁系统 — 集成验证测试")
    print(f"#  项目根目录: {_PROJECT_ROOT}")
    print(f"#  时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("#" * 70)

    test_imports()
    test_proxy_pool_load()
    test_block_tracker()
    test_score_proxy()
    test_next_for_cnki_filtering()
    test_is_cnki_blocked_logic()
    test_get_cnki_block_status()

    # 汇总
    _section("测试汇总")
    total = len(_RESULTS)
    passed = sum(1 for r in _RESULTS if r["passed"])
    failed = total - passed
    print(f"  总计: {total}  通过: {passed}  失败: {failed}")
    print()
    if failed:
        print("  失败项:")
        for r in _RESULTS:
            if not r["passed"]:
                print(f"    - {r['name']}: {r['detail']}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
