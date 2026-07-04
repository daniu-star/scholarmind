"""CNKI Cookie 测试脚本 — 阶段 3: RSS 论文发现测试

测试 discover_papers_rss() 的论文发现能力。
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.hybrid_scraper import CNKIHybridScraper


async def test_rss_discovery():
    """测试 RSS 论文发现。"""
    print("=" * 70)
    print("阶段 3: RSS 论文发现测试")
    print("=" * 70)

    cookies = CNKIHybridScraper.load_cookies_from_file(str(PROJECT_ROOT / "cookies.json"))
    print(f"[0] Cookies 加载成功，共 {len(cookies)} 个字段")

    scraper = CNKIHybridScraper(
        cookies=cookies,
        output_dir=str(PROJECT_ROOT / "tests" / "output" / "rss_test"),
        browser_fallback=False,
    )

    result = {
        "phase": "rss_discovery",
        "journals_tested": [],
        "blocked": False,
    }

    # 测试多个新闻传播学期刊
    journals_to_test = [
        ("GJXW", "国际新闻界", 20),
        ("XWDX", "新闻大学", 20),
    ]

    for journal_code, journal_name, max_papers in journals_to_test:
        print(f"\n[测试] 期刊: {journal_name} (code={journal_code}), max_papers={max_papers}")
        journal_result = {
            "journal_code": journal_code,
            "journal_name": journal_name,
            "max_papers": max_papers,
            "papers_found": 0,
            "papers": [],
            "blocked": False,
            "error": None,
            "duration_sec": 0.0,
        }

        # 先预热会话
        print(f"  [预热] 调用 warmup_session()...")
        t0 = time.time()
        warmup_ok = await scraper.warmup_session()
        warmup_elapsed = time.time() - t0
        print(f"  [预热] warmup_session() 返回: {warmup_ok}, 耗时: {warmup_elapsed:.2f}s")
        journal_result["warmup_success"] = warmup_ok
        journal_result["warmup_duration_sec"] = round(warmup_elapsed, 2)

        if not warmup_ok:
            journal_result["error"] = "warmup_session 失败"
            result["journals_tested"].append(journal_result)
            continue

        # 调用 discover_papers_rss
        rss_url = f"https://rss.cnki.net/knavi/rss/{journal_code}?pcode=CJFD,CCJD"
        print(f"  [RSS] 请求 URL: {rss_url}")

        t0 = time.time()
        try:
            papers = await scraper.discover_papers_rss(journal_code, max_papers)
            elapsed = time.time() - t0
            journal_result["duration_sec"] = round(elapsed, 2)
            journal_result["papers_found"] = len(papers)

            print(f"  [RSS] 发现 {len(papers)} 篇论文, 耗时: {elapsed:.2f}s")

            if papers:
                # 检查元数据字段完整性
                field_stats = {
                    "title": 0,
                    "link": 0,
                    "author": 0,
                    "description": 0,
                    "pub_date": 0,
                }
                for p in papers:
                    for field in field_stats:
                        if p.get(field):
                            field_stats[field] += 1

                journal_result["field_completeness"] = field_stats
                print(f"  [字段完整性] {field_stats}")

                # 打印前 3 篇论文的摘要
                for i, p in enumerate(papers[:3], 1):
                    print(f"\n  论文 {i}:")
                    print(f"    title: {p.get('title', '')[:80]}")
                    print(f"    link: {p.get('link', '')[:100]}")
                    print(f"    author: {p.get('author', '')[:80]}")
                    print(f"    pub_date: {p.get('pub_date', '')}")
                    desc = p.get('description', '')
                    print(f"    description: {desc[:100]}{'...' if len(desc) > 100 else ''}")

                # 保存完整论文列表
                journal_result["papers"] = papers
            else:
                print(f"  ✗ 未发现论文")
                # 检查是否被拦截
                if scraper.error_log:
                    journal_result["error_log"] = scraper.error_log[-3:]
                    print(f"  错误日志: {scraper.error_log[-3:]}")

        except Exception as e:
            elapsed = time.time() - t0
            journal_result["duration_sec"] = round(elapsed, 2)
            journal_result["error"] = f"{type(e).__name__}: {e}"
            print(f"  ✗ 异常: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

        result["journals_tested"].append(journal_result)

        # 检查封锁状态
        block_status = scraper.get_cnki_block_status()
        if block_status["blocked_count"] > 0:
            result["blocked"] = True
            print(f"\n  ⚠ 检测到封锁: {block_status}")

        # 期刊间间隔
        if journal_code != journals_to_test[-1][0]:
            print(f"\n  [间隔] 等待 3 秒...")
            await asyncio.sleep(3)

    # 保存结果
    output_path = PROJECT_ROOT / "tests" / "output" / "rss_test_result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n结果已保存: {output_path}")

    await scraper.close()

    print("\n" + "=" * 70)
    print("阶段 3 测试结果摘要")
    print("=" * 70)
    for j in result["journals_tested"]:
        print(f"  {j['journal_name']} ({j['journal_code']}): 发现 {j['papers_found']} 篇, 耗时 {j['duration_sec']}s")
        if "field_completeness" in j:
            print(f"    字段完整性: {j['field_completeness']}")

    return result


if __name__ == "__main__":
    asyncio.run(test_rss_discovery())
