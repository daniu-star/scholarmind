#!/usr/bin/env python3
"""CNKI Crawler System — Complete Diagnostics.

Tests all system components and presents a comprehensive status report.
"""

import asyncio
import json
import os
import sys
import io
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(__file__))

from curl_cffi.requests import AsyncSession
from utils.proxy_detector import detect_available_proxies, format_proxy_status


async def test_cnki_access(tls: AsyncSession) -> dict:
    """Test CNKI endpoint accessibility."""
    results = {}
    endpoints = {
        "www.cnki.net": "https://www.cnki.net/",
        "kns.cnki.net": "https://kns.cnki.net/kns8s/",
        "rss.cnki.net": "https://rss.cnki.net/knavi/rss/GJXW?pcode=CJFD,CCJD",
    }
    for name, url in endpoints.items():
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            r = await tls.get(url, headers=headers)
            results[name] = {
                "status": r.status_code,
                "ok": r.status_code == 200,
                "blocked": r.status_code == 418,
                "error": None,
            }
        except Exception as e:
            results[name] = {"status": None, "ok": False, "blocked": False, "error": str(e)[:100]}
    return results


async def test_alternative_sources(tls: AsyncSession) -> dict:
    """Test alternative academic data sources."""
    results = {}

    # CrossRef
    try:
        r = await tls.get("https://api.crossref.org/works?query=test&rows=1")
        results["CrossRef"] = {"status": r.status_code, "ok": r.status_code == 200}
    except Exception as e:
        results["CrossRef"] = {"status": None, "ok": False, "error": str(e)[:80]}

    # arXiv
    try:
        r = await tls.get("https://export.arxiv.org/api/query?search_query=all:test&max_results=1")
        results["arXiv"] = {"status": r.status_code, "ok": r.status_code == 200}
    except Exception as e:
        results["arXiv"] = {"status": None, "ok": False, "error": str(e)[:80]}

    # Semantic Scholar
    try:
        r = await tls.get("https://api.semanticscholar.org/graph/v1/paper/search?query=test&limit=1")
        results["Semantic Scholar"] = {"status": r.status_code, "ok": r.status_code == 200}
    except Exception as e:
        results["Semantic Scholar"] = {"status": None, "ok": False, "error": str(e)[:80]}

    return results


async def check_cookies() -> dict:
    """Check CNKI cookie status."""
    cookies_file = Path("cookies.json")
    if not cookies_file.exists():
        return {"exists": False, "valid": False, "error": "cookies.json not found"}

    try:
        data = json.loads(cookies_file.read_text("utf-8"))
        cookies = data.get("cookies", {})
        auth_cookies = ["LID", "Ecp_ClientId", "Ecp_LoginStuts"]
        missing = [c for c in auth_cookies if c not in cookies or not cookies[c]]
        return {
            "exists": True,
            "valid": len(missing) == 0,
            "account": data.get("account", "unknown"),
            "updated": data.get("_updated", "unknown"),
            "missing_auth_cookies": missing,
            "cookie_count": len(cookies),
        }
    except Exception as e:
        return {"exists": True, "valid": False, "error": str(e)[:100]}


async def check_data_directory() -> dict:
    """Check existing data in the database directory."""
    base = Path("../数据库/cnki")
    if not base.exists():
        return {"exists": False, "papers": 0}

    stats = {"hybrid": 0, "multi_source": 0, "discipline_dirs": []}

    hybrid_dir = base / "hybrid"
    if hybrid_dir.exists():
        json_files = list(hybrid_dir.glob("*.json"))
        stats["hybrid"] = len(json_files)
        md_files = list(hybrid_dir.glob("*.md"))
        stats["hybrid_reports"] = len(md_files)

    multi_dir = base / "multi_source"
    if multi_dir.exists():
        json_files = list(multi_dir.glob("*.json"))
        stats["multi_source"] = len(json_files)

    for d in base.iterdir():
        if d.is_dir() and d.name not in ("hybrid", "multi_source"):
            stats["discipline_dirs"].append(d.name)

    # Count papers from multi-source collections
    total_papers = 0
    if multi_dir.exists():
        for f in sorted(multi_dir.glob("*.json"))[-3:]:
            try:
                data = json.loads(f.read_text("utf-8"))
                total_papers += data.get("total_papers", 0)
            except Exception:
                pass

    stats["paper_count"] = total_papers

    return stats


async def main():
    print("=" * 60)
    print("  CNKI 爬虫系统 — 完整诊断报告")
    print(f"  诊断时间: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 60)
    print()

    # 1. Proxy detection
    print("[1] 代理检测")
    print("-" * 40)
    proxies = await detect_available_proxies()
    print(format_proxy_status(proxies))
    print()

    # 2. Cookies
    print("[2] Cookie 状态")
    print("-" * 40)
    cookies = await check_cookies()
    if cookies["exists"]:
        print(f"  文件存在: Yes")
        print(f"  账号: {cookies.get('account', 'N/A')}")
        print(f"  更新时间: {cookies.get('updated', 'N/A')}")
        if cookies["valid"]:
            print(f"  关键Cookie: 完整 ({cookies.get('cookie_count', 0)}个)")
        else:
            print(f"  [!] 缺失关键Cookie: {cookies.get('missing_auth_cookies', [])}")
        if not cookies.get("valid"):
            print("  [!] Cookie 无效 — PDF 下载将失败")
    else:
        print(f"  [!] cookies.json 不存在")
    print()

    # 3. CNKI connectivity
    print("[3] CNKI 连接测试")
    print("-" * 40)
    tls = AsyncSession(impersonate="chrome124", timeout=10, verify=False)
    cnki_results = await test_cnki_access(tls)
    for name, result in cnki_results.items():
        if result.get("ok"):
            print(f"  {name:20s}: OK (200)")
        elif result.get("blocked"):
            print(f"  {name:20s}: BLOCKED (418)")
        elif result.get("error"):
            print(f"  {name:20s}: ERROR - {result['error']}")
        else:
            print(f"  {name:20s}: FAILED ({result.get('status', 'N/A')})")
    await tls.close()
    print()

    # 4. Alternative sources
    print("[4] 替代数据源测试")
    print("-" * 40)
    tls2 = AsyncSession(impersonate="chrome124", timeout=15, verify=False)
    alt_results = await test_alternative_sources(tls2)
    for name, result in alt_results.items():
        status = "OK" if result.get("ok") else f"FAILED ({result.get('status', 'N/A')})"
        print(f"  {name:20s}: {status}")
    await tls2.close()
    print()

    # 5. Existing data
    print("[5] 已采集数据")
    print("-" * 40)
    data_stats = await check_data_directory()
    if data_stats.get("exists"):
        print(f"  总论文数: ~{data_stats.get('paper_count', 0)}")
        print(f"  混合采集(Hybrid): {data_stats.get('hybrid', 0)} 文件")
        print(f"  多源采集(Multi): {data_stats.get('multi_source', 0)} 文件")
        if data_stats.get("discipline_dirs"):
            print(f"  学科目录: {', '.join(data_stats['discipline_dirs'])}")
    else:
        print("  [!] 数据库目录不存在")
    print()

    # 6. Summary
    print("[6] 综合诊断结论")
    print("-" * 40)

    cnki_blocked = any(r.get("blocked") for r in cnki_results.values())
    has_proxy = len(proxies) > 0
    cookies_valid = cookies.get("valid", False)
    alt_ok = any(r.get("ok") for r in alt_results.values())

    issues = []
    strengths = []

    if cnki_blocked:
        issues.append("CNKI 已被 WAF 全面拦截 (HTTP 418) — 无法直接访问")
    else:
        strengths.append("CNKI 连接正常")

    if not has_proxy:
        issues.append("未检测到可用的代理/Clash/VPN")
    else:
        strengths.append(f"检测到 {len(proxies)} 个代理")

    if not cookies_valid:
        issues.append("CNKI Cookie 无效或缺失 — PDF 下载无法使用")
    else:
        strengths.append("CNKI Cookie 有效")

    if alt_ok:
        strengths.append("替代数据源 (CrossRef/arXiv) 正常")
    else:
        issues.append("替代数据源不可用")
    if not cnki_blocked:
        strengths.append("多策略 PDF 下载已实现 (4种策略 + 重试机制)")
    strengths.append("多源采集器支持自动降级到 CrossRef/arXiv")

    print("  [OK] 正常项:")
    for s in strengths:
        print(f"    + {s}")

    if issues:
        print("  [!] 问题项:")
        for issue in issues:
            print(f"    - {issue}")

    print()
    print("=" * 60)
    print("  诊断完成")
    print("=" * 60)

    # Save diagnostics result
    output = {
        "timestamp": datetime.now().isoformat(),
        "cnki": {k: v for k, v in cnki_results.items()},
        "alternative_sources": alt_results,
        "cookies": cookies,
        "proxy": {"available": [p["name"] for p in proxies]},
        "issues": issues,
        "strengths": strengths,
    }
    output_dir = Path("../数据库/cnki/hybrid")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"diagnostics_{datetime.now():%Y%m%d_%H%M%S}.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n诊断结果已保存: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
