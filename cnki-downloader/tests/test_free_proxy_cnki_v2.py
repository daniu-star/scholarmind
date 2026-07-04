"""阶段 2（增强版）：使用 GitHub 备用源抓取免费代理并测试 CNKI 连通性。

由于 FreeProxyFetcher 配置的源（ProxyScrape v2 + proxy-list.download）在
当前网络环境下不可达（ProxyScrape 超时，proxy-list.download 返回 502），
本脚本使用 GitHub raw 备用源抓取代理用于测试目的。

注意：此脚本仅用于测试，不修改 crawler/free_proxy_fetcher.py 源码。
      测试结果可指导后续将备用源添加到 FreeProxyFetcher.SOURCES。

运行方式：
    cd c:\\Users\\13067\\Desktop\\AI产品\\cnki-downloader
    python tests/test_free_proxy_cnki_v2.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# 确保能导入 crawler 模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from curl_cffi.requests import Session
from crawler.proxy_pool import ProxyPool


# 测试参数
MAX_PROXIES_TO_TEST = 20
CNKI_TEST_URL = "https://www.cnki.net/"
PROBE_TIMEOUT = 10  # 秒

# GitHub 备用代理源（测试用，不修改 FreeProxyFetcher 源码）
GITHUB_PROXY_SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
]


def fetch_proxies_from_github() -> list[dict]:
    """从 GitHub 备用源抓取代理列表。"""
    seen: set[str] = set()
    proxies: list[dict] = []

    for url in GITHUB_PROXY_SOURCES:
        print(f"  抓取: {url[:70]}...")
        try:
            with Session(impersonate="chrome124", timeout=15, verify=False) as s:
                resp = s.get(url)
                if resp.status_code != 200:
                    print(f"    HTTP {resp.status_code}, 跳过")
                    continue
                lines = resp.text.splitlines()
                print(f"    获取 {len(lines)} 行")
                for line in lines:
                    line = line.strip()
                    if not line or "://" in line:
                        # 已带 scheme 或空行，跳过（简化处理）
                        if "://" in line:
                            proxy_url = line
                        else:
                            continue
                    else:
                        # 形如 ip:port
                        host, _, port = line.rpartition(":")
                        if not host or not port.isdigit():
                            continue
                        proxy_url = f"http://{line}"

                    if proxy_url not in seen:
                        seen.add(proxy_url)
                        proxies.append({
                            "url": proxy_url,
                            "enabled": True,
                            "fail_count": 0,
                            "source": "github_free",
                            "ip_type": "unknown",
                        })
        except Exception as e:
            print(f"    EXCEPTION: {type(e).__name__}: {str(e)[:100]}")

    return proxies


def main():
    print("=" * 70)
    print("阶段 2（增强版）：免费代理抓取与 CNKI 连通性测试")
    print("(使用 GitHub 备用源，因 FreeProxyFetcher 配置源不可达)")
    print("=" * 70)
    print()

    # ── Step 1: 抓取免费代理 ──
    print("[Step 1] 从 GitHub 备用源抓取免费代理...")
    fetch_start = time.time()
    proxies = fetch_proxies_from_github()
    fetch_elapsed = time.time() - fetch_start

    print(f"\n  抓取完成，耗时 {fetch_elapsed:.1f}s")
    print(f"  抓取到的代理总数（去重后）: {len(proxies)}")

    if not proxies:
        print("\n[Step 1] 未抓取到任何代理，阶段 2 结束")
        return {
            "fetch_success": False,
            "fetch_error": "GitHub 备用源也未抓取到代理",
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
    test_count = min(MAX_PROXIES_TO_TEST, len(proxies))
    print(f"\n[Step 2] 测试前 {test_count} 个代理对 CNKI 的连通性...")
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
            print(f"EXCEPTION: {str(e)[:80]}")
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
                print(f"EXCEPTION: {str(e)[:80]}")
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
    print("阶段 2（增强版）测试结果汇总")
    print("=" * 70)
    print(f"  数据源: GitHub 备用源（FreeProxyFetcher 配置源不可达）")
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
        "source": "github_backup",
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
    output_file = Path(__file__).parent / "free_proxy_test_results_v2.json"
    output_file.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n结果已保存到: {output_file}")
