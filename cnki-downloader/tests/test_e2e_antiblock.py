"""阶段 4：端到端测试 — 验证反封锁策略在真实 CNKI 环境下的表现。

由于阶段 2/3 未找到可用代理，但直接连接 CNKI 返回 200（当前 IP 未被封锁），
本脚本测试直连模式下的反封锁功能：
  1. warmup_session() — 会话预热（验证 _is_cnki_blocked 在真实请求中的表现）
  2. discover_papers_rss() — RSS 发现（验证 418 自动检测与重试）
  3. extract_detail_page() — 详情页提取（验证反封锁逻辑）
  4. get_cnki_block_status() — 封锁状态报告

注意：使用 browser_fallback=False 避免在测试环境中打开浏览器窗口。

运行方式：
    cd c:\\Users\\13067\\Desktop\\AI产品\\cnki-downloader
    python tests/test_e2e_antiblock.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# 确保能导入 crawler 模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.hybrid_scraper import CNKIHybridScraper


async def main():
    print("=" * 70)
    print("阶段 4：端到端测试 — 反封锁策略验证")
    print("=" * 70)
    print()

    # 加载 cookies
    try:
        cookies = CNKIHybridScraper.load_cookies_from_file("cookies.json")
        print("[0] Cookies 加载成功")
    except FileNotFoundError:
        print("[0] cookies.json 未找到，使用 fallback cookies")
        cookies = {
            "_c_WBKFRo": "vx7kYIApPT34yebAB2MBy5vLlRPtOf0EKg8vA1ME",
            "cnkiUserKey": "491cb460-3573-3ad7-a2d7-b2af30c2634f",
            "Ecp_loginuserbk": "dx0741",
            "Ecp_loginuserjf": "dx0741",
            "Ecp_ClientId": "e78899f8ed56aab5b3373cc6276273240VN81Etde6",
            "SID": "zhuye091002",
            "Ecp_session": "1",
            "Ecp_notFirstLogin": "Ly4MHj",
        }

    # 检查 cookie 过期状态
    expiry = CNKIHybridScraper.check_cookie_expiry(cookies)
    if expiry["warning"]:
        print(f"  [!] {expiry['warning']}")

    # 创建 scraper 实例（不启用浏览器降级，避免打开窗口）
    output_dir = str(Path(__file__).parent / "output" / "e2e_test")
    scraper = CNKIHybridScraper(
        cookies=cookies,
        output_dir=output_dir,
        browser_fallback=False,  # 不启用浏览器降级
    )

    results = {
        "warmup": None,
        "rss_discovery": None,
        "detail_page": None,
        "block_status": None,
        "stats": None,
    }

    try:
        # ── Step 1: 会话预热 ──
        print("\n[Step 1] 会话预热 (warmup_session)...")
        print("  访问 CNKI 首页 + 搜索页，验证 _is_cnki_blocked 在真实请求中的表现")
        warmup_start = time.time()
        warmup_ok = await scraper.warmup_session()
        warmup_elapsed = time.time() - warmup_start
        print(f"  结果: {'成功' if warmup_ok else '失败'} (耗时 {warmup_elapsed:.1f}s)")
        results["warmup"] = {
            "success": warmup_ok,
            "elapsed": round(warmup_elapsed, 2),
        }

        if not warmup_ok:
            print("  [!] 会话预热失败，可能是 IP 被封锁或网络问题")
            print("  [!] 跳过后续 RSS 和详情页测试")
        else:
            # ── Step 2: RSS 发现 ──
            print("\n[Step 2] RSS 论文发现 (discover_papers_rss)...")
            print("  期刊: 国际新闻界 (GJXW), max_papers=3")
            rss_start = time.time()
            rss_papers = await scraper.discover_papers_rss("GJXW", max_papers=3)
            rss_elapsed = time.time() - rss_start
            print(f"  结果: 发现 {len(rss_papers)} 篇论文 (耗时 {rss_elapsed:.1f}s)")
            if rss_papers:
                for i, p in enumerate(rss_papers, 1):
                    print(f"    {i}. {p.get('title', '(no title)')[:60]}")
            results["rss_discovery"] = {
                "success": len(rss_papers) > 0,
                "count": len(rss_papers),
                "elapsed": round(rss_elapsed, 2),
                "papers": [{"title": p.get("title", "")[:100]} for p in rss_papers],
            }

            # ── Step 3: 详情页提取（仅测试第一篇） ──
            if rss_papers:
                print("\n[Step 3] 详情页提取 (extract_detail_page)...")
                first_paper_url = rss_papers[0].get("link", "")
                if first_paper_url:
                    print(f"  URL: {first_paper_url[:80]}...")
                    detail_start = time.time()
                    paper = await scraper.extract_detail_page(
                        first_paper_url, discipline="新闻传播学"
                    )
                    detail_elapsed = time.time() - detail_start
                    fields_present = sum([
                        bool(paper.title), bool(paper.authors), paper.year > 0,
                        bool(paper.journal_name), bool(paper.abstract),
                        bool(paper.keywords), bool(paper.doi),
                    ])
                    print(f"  结果: {fields_present}/7 字段已提取 (耗时 {detail_elapsed:.1f}s)")
                    print(f"    标题: {paper.title[:60]}")
                    print(f"    作者: {', '.join(paper.authors[:3])}")
                    print(f"    年份: {paper.year}")
                    print(f"    DOI: {paper.doi}")
                    if paper.errors:
                        print(f"    错误: {paper.errors[:2]}")
                    results["detail_page"] = {
                        "success": fields_present >= 3,
                        "fields_present": fields_present,
                        "elapsed": round(detail_elapsed, 2),
                        "title": paper.title[:100],
                        "year": paper.year,
                        "has_doi": bool(paper.doi),
                        "has_abstract": bool(paper.abstract),
                        "errors": paper.errors[:3],
                    }

        # ── Step 4: 封锁状态报告 ──
        print("\n[Step 4] CNKI 封锁状态报告 (get_cnki_block_status)...")
        block_status = scraper.get_cnki_block_status()
        print(f"  被封锁代理数: {block_status['blocked_count']}")
        print(f"  可用代理数: {block_status['available_proxies']}")
        print(f"  当前代理: {block_status['current_proxy'] or '直连'}")
        print(f"  当前代理被封锁: {block_status['current_proxy_blocked']}")
        results["block_status"] = block_status

        # ── Step 5: 统计信息 ──
        print("\n[Step 5] 爬虫统计信息...")
        stats = scraper.stats
        print(f"  总尝试: {stats['total_attempted']}")
        print(f"  详情页成功/失败: {stats['detail_success']}/{stats['detail_failed']}")
        print(f"  CNKI 418 拦截次数: {stats['cnki_blocks_detected']}")
        print(f"  代理切换次数: {stats['proxy_switches']}")
        print(f"  总错误数: {stats['total_errors']}")
        results["stats"] = stats

    finally:
        await scraper.close()

    # ── 汇总 ──
    print()
    print("=" * 70)
    print("阶段 4 端到端测试结果汇总")
    print("=" * 70)
    print(f"  会话预热: {'✓ 成功' if results['warmup'] and results['warmup']['success'] else '✗ 失败'}")
    if results["rss_discovery"]:
        rss = results["rss_discovery"]
        print(f"  RSS 发现: {'✓' if rss['success'] else '✗'} {rss['count']} 篇论文")
    if results["detail_page"]:
        dp = results["detail_page"]
        print(f"  详情页提取: {'✓' if dp['success'] else '✗'} {dp['fields_present']}/7 字段")
    bs = results["block_status"]
    print(f"  封锁状态: {bs['blocked_count']} 个代理被封锁, 当前 {'被封锁' if bs['current_proxy_blocked'] else '未封锁'}")
    st = results["stats"]
    print(f"  418 拦截: {st['cnki_blocks_detected']} 次")
    print(f"  代理切换: {st['proxy_switches']} 次")

    return results


if __name__ == "__main__":
    results = asyncio.run(main())
    # 保存结果
    output_file = Path(__file__).parent / "e2e_test_results.json"
    output_file.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\n结果已保存到: {output_file}")
