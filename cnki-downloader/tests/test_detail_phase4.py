"""CNKI Cookie 测试脚本 — 阶段 4: 详情页提取测试

从阶段 3 发现的论文中选 3 篇，运行 extract_detail_page() 提取详情页元数据。
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from dataclasses import asdict

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.hybrid_scraper import CNKIHybridScraper, FullPaperData


async def test_detail_extraction():
    """测试详情页元数据提取。"""
    print("=" * 70)
    print("阶段 4: 详情页提取测试")
    print("=" * 70)

    cookies = CNKIHybridScraper.load_cookies_from_file(str(PROJECT_ROOT / "cookies.json"))
    print(f"[0] Cookies 加载成功，共 {len(cookies)} 个字段")

    scraper = CNKIHybridScraper(
        cookies=cookies,
        output_dir=str(PROJECT_ROOT / "tests" / "output" / "detail_test"),
        browser_fallback=False,
    )

    # 先预热会话
    print(f"\n[预热] 调用 warmup_session()...")
    warmup_ok = await scraper.warmup_session()
    print(f"[预热] warmup_session() 返回: {warmup_ok}")
    if not warmup_ok:
        print("✗ 会话预热失败，无法继续")
        await scraper.close()
        return None

    # 先用 RSS 发现论文
    print(f"\n[RSS] 发现 GJXW 国际新闻界论文...")
    papers_rss = await scraper.discover_papers_rss("GJXW", max_papers=10)
    print(f"[RSS] 发现 {len(papers_rss)} 篇论文")

    if not papers_rss:
        print("✗ RSS 未发现论文，无法继续")
        await scraper.close()
        return None

    # 选 3 篇论文进行详情页提取
    test_papers = papers_rss[:3]
    print(f"\n[选择] 选 {len(test_papers)} 篇论文进行详情页提取:")
    for i, p in enumerate(test_papers, 1):
        print(f"  {i}. {p.get('title', '')[:60]}")
        print(f"     URL: {p.get('link', '')[:100]}")

    result = {
        "phase": "detail_extraction",
        "papers_tested": [],
        "field_stats": {},
    }

    # 详情页字段完整性统计
    field_names = [
        "title", "authors", "abstract", "keywords", "journal_name",
        "year", "doi", "issue_number", "filename", "dbcode",
        "tablename", "filesourcetype", "pdf_order_url", "caj_order_url",
        "auth_check_url", "is_core", "citations",
    ]
    field_stats = {f: 0 for f in field_names}

    for i, rss_item in enumerate(test_papers, 1):
        paper_url = rss_item["link"]
        print(f"\n[{i}/{len(test_papers)}] 提取详情页: {rss_item.get('title', '')[:60]}")
        print(f"       URL: {paper_url[:100]}")

        paper_result = {
            "rss_title": rss_item.get("title", ""),
            "rss_link": paper_url,
            "fields": {},
            "errors": [],
            "duration_sec": 0.0,
        }

        t0 = time.time()
        try:
            paper = await scraper.extract_detail_page(paper_url, discipline="新闻传播学")
            elapsed = time.time() - t0
            paper_result["duration_sec"] = round(elapsed, 2)

            # 记录每个字段
            fields = {
                "title": paper.title,
                "authors": paper.authors,
                "abstract": paper.abstract,
                "abstract_length": len(paper.abstract),
                "keywords": paper.keywords,
                "journal_name": paper.journal_name,
                "year": paper.year,
                "doi": paper.doi,
                "issue_number": paper.issue_number,
                "filename": paper.filename,
                "dbcode": paper.dbcode,
                "tablename": paper.tablename,
                "filesourcetype": paper.filesourcetype,
                "pdf_order_url": paper.pdf_order_url,
                "caj_order_url": paper.caj_order_url,
                "auth_check_url": paper.auth_check_url,
                "is_core": paper.is_core,
                "citations": paper.citations,
                "errors": paper.errors,
                "extraction_time": paper.extraction_time,
            }
            paper_result["fields"] = fields

            # 更新字段统计
            for f in field_names:
                value = getattr(paper, f, None)
                if value:  # 非空/非零/非空列表
                    field_stats[f] += 1

            # 打印结果
            print(f"       耗时: {elapsed:.2f}s")
            print(f"       title: {'✓' if paper.title else '✗'} {paper.title[:60]}")
            print(f"       authors: {'✓' if paper.authors else '✗'} {paper.authors}")
            print(f"       abstract: {'✓' if paper.abstract else '✗'} (len={len(paper.abstract)})")
            print(f"       keywords: {'✓' if paper.keywords else '✗'} {paper.keywords}")
            print(f"       journal_name: {'✓' if paper.journal_name else '✗'} {paper.journal_name}")
            print(f"       year: {'✓' if paper.year else '✗'} {paper.year}")
            print(f"       doi: {'✓' if paper.doi else '✗'} {paper.doi}")
            print(f"       issue_number: {'✓' if paper.issue_number else '✗'} {paper.issue_number}")
            print(f"       filename: {'✓' if paper.filename else '✗'} {paper.filename}")
            print(f"       dbcode: {'✓' if paper.dbcode else '✗'} {paper.dbcode}")
            print(f"       tablename: {'✓' if paper.tablename else '✗'} {paper.tablename}")
            print(f"       filesourcetype: {'✓' if paper.filesourcetype else '✗'} {paper.filesourcetype}")
            print(f"       pdf_order_url: {'✓' if paper.pdf_order_url else '✗'} {paper.pdf_order_url[:80] if paper.pdf_order_url else ''}")
            print(f"       caj_order_url: {'✓' if paper.caj_order_url else '✗'} {paper.caj_order_url[:80] if paper.caj_order_url else ''}")
            print(f"       auth_check_url: {'✓' if paper.auth_check_url else '✗'} {paper.auth_check_url[:80] if paper.auth_check_url else ''}")
            print(f"       is_core: {'✓' if paper.is_core else '✗'} {paper.is_core}")
            print(f"       citations: {paper.citations}")
            if paper.errors:
                print(f"       错误: {paper.errors}")
                paper_result["errors"] = paper.errors

        except Exception as e:
            elapsed = time.time() - t0
            paper_result["duration_sec"] = round(elapsed, 2)
            paper_result["exception"] = f"{type(e).__name__}: {e}"
            print(f"       ✗ 异常: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

        result["papers_tested"].append(paper_result)

        # 论文间间隔（模拟人类浏览）
        if i < len(test_papers):
            wait = 2
            print(f"       [间隔] 等待 {wait}s...")
            await asyncio.sleep(wait)

    result["field_stats"] = field_stats
    result["total_papers"] = len(test_papers)

    # 保存结果
    output_path = PROJECT_ROOT / "tests" / "output" / "detail_test_result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n结果已保存: {output_path}")

    await scraper.close()

    print("\n" + "=" * 70)
    print("阶段 4 测试结果摘要")
    print("=" * 70)
    print(f"测试论文数: {result['total_papers']}")
    print(f"\n字段完整性统计 (共 {result['total_papers']} 篇):")
    for f, count in field_stats.items():
        pct = count * 100 // result['total_papers'] if result['total_papers'] else 0
        print(f"  {f:20s}: {count}/{result['total_papers']} ({pct}%)")

    return result


if __name__ == "__main__":
    asyncio.run(test_detail_extraction())
