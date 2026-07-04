"""阶段 2：免费代理抓取与 CNKI 连通性测试。

流程：
  1. 运行 FreeProxyFetcher().fetch_all() 抓取免费代理
  2. 报告抓取到的代理数量
  3. 从抓取到的代理中选取前 20 个，使用 ProxyPool._probe_cnki() 测试 CNKI 连通性
  4. 对能连通 CNKI 的代理，使用 ProxyPool.detect_ip_type() 检测 IP 类型
  5. 报告测试结果

运行方式：
    cd c:\\Users\\13067\\Desktop\\AI产品\\cnki-downloader
    python tests/test_free_proxy_cnki.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# 确保能导入 crawler 模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.free_proxy_fetcher import FreeProxyFetcher
from crawler.proxy_pool import ProxyPool


# 测试参数
MAX_PROXIES_TO_TEST = 20
CNKI_TEST_URL = "https://www.cnki.net/"
PROBE_TIMEOUT = 10  # 秒


def main():
    print("=" * 70)
    print("阶段 2：免费代理抓取与 CNKI 连通性测试")
    print("=" * 70)
    print()

    # ── Step 1: 抓取免费代理 ──
    print("[Step 1] 抓取免费代理...")
    print(f"  数据源: {len(FreeProxyFetcher.SOURCES)} 个")
    for i, src in enumerate(FreeProxyFetcher.SOURCES, 1):
        print(f"    {i}. {src[:80]}...")

    fetcher = FreeProxyFetcher()
    fetch_start = time.time()
    try:
        proxies = fetcher.fetch_all()
    except Exception as e:
        print(f"  [ERROR] 抓取失败: {e}")
        proxies = []
    fetch_elapsed = time.time() - fetch_start

    print(f"\n  抓取完成，耗时 {fetch_elapsed:.1f}s")
    print(f"  抓取到的代理总数: {len(proxies)}")

    if not proxies:
        print("\n[Step 1] 未抓取到任何代理，阶段 2 结束")
        return {
            "fetch_success": False,
            "fetch_error": "未抓取到任何代理",
            "total_fetched": 0,
            "tested": 0,
            "reachable": 0,
            "cnki_blocked": 0,
            "cnki_error": 0,
            "residential": 0,
            "datacenter": 0,
            "unknown_type": 0,
            "proxies_detail": [],
        }

    # 显示前 5 个代理作为样本
    print(f"\n  前 5 个代理样本:")
    for i, p in enumerate(proxies[:5], 1):
        print(f"    {i}. {p['url']}")

    # ── Step 2: 选取前 20 个测试 CNKI 连通性 ──
    print(f"\n[Step 2] 测试前 {min(MAX_PROXIES_TO_TEST, len(proxies))} 个代理对 CNKI 的连通性...")
    test_proxies = proxies[:MAX_PROXIES_TO_TEST]
    print(f"  测试目标: {CNKI_TEST_URL}")
    print(f"  超时: {PROBE_TIMEOUT}s")
    print()

    pool = ProxyPool()
    results = []
    reachable_count = 0
    blocked_count = 0
    error_count = 0

    for i, proxy_info in enumerate(test_proxies, 1):
        url = proxy_info["url"]
        print(f"  [{i}/{len(test_proxies)}] 测试 {url} ...", end=" ", flush=True)
        probe_start = time.time()
        try:
            status, ok = ProxyPool._probe_cnki(url, CNKI_TEST_URL, PROBE_TIMEOUT)
        except Exception as e:
            status, ok = 0, False
            print(f"EXCEPTION: {e}")
        elapsed = time.time() - probe_start

        if ok:
            cnki_status = "cnki_ok"
            reachable_count += 1
            print(f"OK (200, {elapsed:.1f}s)")
        elif status == 418:
            cnki_status = "cnki_blocked"
            blocked_count += 1
            print(f"BLOCKED (418, {elapsed:.1f}s)")
        elif status == 0:
            cnki_status = "cnki_error"
            error_count += 1
            print(f"ERROR (timeout/exception, {elapsed:.1f}s)")
        else:
            cnki_status = "cnki_error"
            error_count += 1
            print(f"ERROR (HTTP {status}, {elapsed:.1f}s)")

        results.append({
            "url": url,
            "status_code": status,
            "cnki_status": cnki_status,
            "reachable": ok,
            "elapsed": round(elapsed, 2),
        })
        print()

    # ── Step 3: 对能连通 CNKI 的代理检测 IP 类型 ──
    print(f"\n[Step 3] 检测可达代理的 IP 类型...")
    reachable_proxies = [r for r in results if r["reachable"]]
    residential_count = 0
    datacenter_count = 0
    unknown_type_count = 0

    if reachable_proxies:
        for i, r in enumerate(reachable_proxies, 1):
            url = r["url"]
            print(f"  [{i}/{len(reachable_proxies)}] 检测 {url} ...", end=" ", flush=True)
            try:
                ip_type = pool.detect_ip_type(url)
            except Exception as e:
                ip_type = "unknown"
                print(f"EXCEPTION: {e}")
            r["ip_type"] = ip_type
            if ip_type == "residential":
                residential_count += 1
                print(f"residential")
            elif ip_type == "datacenter":
                datacenter_count += 1
                print(f"datacenter")
            else:
                unknown_type_count += 1
                print(f"unknown")
    else:
        print("  无可达 CNKI 的代理，跳过 IP 类型检测")

    # ── 汇总报告 ──
    print()
    print("=" * 70)
    print("阶段 2 测试结果汇总")
    print("=" * 70)
    print(f"  抓取到的代理总数: {len(proxies)}")
    print(f"  测试的代理数量: {len(test_proxies)}")
    print(f"  可达 CNKI (200): {reachable_count}")
    print(f"  被 CNKI 封锁 (418): {blocked_count}")
    print(f"  错误/超时: {error_count}")
    print(f"  住宅 IP (residential): {residential_count}")
    print(f"  数据中心 IP (datacenter): {datacenter_count}")
    print(f"  未知类型: {unknown_type_count}")

    summary = {
        "fetch_success": True,
        "total_fetched": len(proxies),
        "tested": len(test_proxies),
        "reachable": reachable_count,
        "cnki_blocked": blocked_count,
        "cnki_error": error_count,
        "residential": residential_count,
        "datacenter": datacenter_count,
        "unknown_type": unknown_type_count,
        "proxies_detail": results,
    }
    return summary


if __name__ == "__main__":
    summary = main()
    # 保存结果到 JSON 文件
    output_file = Path(__file__).parent / "free_proxy_test_results.json"
    output_file.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n结果已保存到: {output_file}")
