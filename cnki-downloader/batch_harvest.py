#!/usr/bin/env python3
"""CNKI 批量采集脚本 — 两阶段流程。

阶段 1: 批量采集元数据（快速，不下载 PDF）
阶段 2: 单独下载 PDF（Playwright 浏览器自动化，可选）

用法:
    python batch_harvest.py                            # 默认: 4 期刊各 2 篇，仅元数据
    python batch_harvest.py --journals GJXW,YANJ --papers 3
    python batch_harvest.py --with-pdf                 # 同时下载 PDF
"""
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

from crawler.hybrid_scraper import CNKIHybridScraper, FullPaperData


# 期刊代码映射
JOURNAL_CODE_MAP = {
    "GJXW": ("国际新闻界", "新闻传播学"),
    "YANJ": ("新闻与传播研究", "新闻传播学"),
    "XWDX": ("新闻大学", "新闻传播学"),
    "DACB": ("当代传播", "新闻传播学"),
    "XWJZ": ("新闻记者", "新闻传播学"),
}


async def batch_harvest_metadata(
    journals: list[tuple[str, str, str]],
    papers_per_journal: int,
    output_dir: str,
):
    """阶段 1: 批量采集元数据（不下载 PDF）。"""
    cookies = CNKIHybridScraper.load_cookies_from_file("cookies.json")
    expiry = CNKIHybridScraper.check_cookie_expiry(cookies)
    if expiry["warning"]:
        print(f"[!] {expiry['warning']}")

    scraper = CNKIHybridScraper(
        cookies=cookies,
        output_dir=output_dir,
        browser_fallback=False,  # 阶段 1 不启用浏览器
    )

    all_papers: list[FullPaperData] = []
    start_time = datetime.now()

    try:
        for code, name, discipline in journals:
            print(f"\n{'='*70}")
            print(f"  采集期刊: {name} ({code}) — {discipline}")
            print(f"{'='*70}")

            papers = await scraper.harvest_paper(
                journal_code=code,
                journal_name=name,
                discipline=discipline,
                max_papers=papers_per_journal,
                download_pdfs=False,  # 阶段 1 不下载 PDF
            )
            all_papers.extend(papers)
            print(f"  → 采集 {len(papers)} 篇论文")

    finally:
        scraper.export_error_log_md()
        await scraper.close()

    # 统计
    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n{'='*70}")
    print(f"  阶段 1 完成 — 共 {len(all_papers)} 篇论文，耗时 {elapsed:.0f}s")
    print(f"{'='*70}")

    if all_papers:
        fields = ["title", "authors", "year", "journal_name", "abstract",
                  "keywords", "doi"]
        print("\n字段完整性:")
        for f in fields:
            count = sum(1 for p in all_papers if getattr(p, f, None))
            pct = count / len(all_papers) * 100
            print(f"  {f:15s}: {count}/{len(all_papers)} ({pct:.0f}%)")

    return all_papers


async def batch_download_pdfs(
    papers: list[FullPaperData],
    output_dir: str,
):
    """阶段 2: 使用 Playwright 浏览器自动化下载 PDF。

    策略：
      - 开始前冷却 60 秒（让 CNKI EdgeOne CDN 解除软封锁）
      - 每次下载间隔 10-15 秒（随机抖动，避免触发速率限制）
      - 连续失败 3 次后冷却 60 秒
      - 只下载 PDF，拒绝 CAJ/KDH 格式
    """
    if not papers:
        print("没有论文需要下载 PDF")
        return

    from crawler.browser_fallback import BrowserFallback
    import random

    cookies = CNKIHybridScraper.load_cookies_from_file("cookies.json")
    pdf_dir = Path(output_dir) / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    downloader = BrowserFallback(cookies=cookies, output_dir=str(pdf_dir))

    print(f"\n{'='*70}")
    print(f"  阶段 2: PDF 下载 (Playwright headless)")
    print(f"  目标: {len(papers)} 篇论文")
    print(f"{'='*70}")

    # Phase 2 开始前冷却 60 秒，让 CNKI CDN 解除软封锁
    print(f"\n  [冷却] 等待 60 秒，让 CNKI CDN 解除速率限制...")
    await asyncio.sleep(60)
    print(f"  [冷却] 完成，开始下载\n")

    success_count = 0
    consecutive_failures = 0
    for i, paper in enumerate(papers):
        print(f"  [{i+1}/{len(papers)}] {paper.title[:60]}...")

        if not paper.cnki_url:
            print(f"    跳过: 无 cnki_url")
            continue

        # 如果已经下载成功（断点续传），跳过
        expected_path = pdf_dir / f"{paper.filename or f'paper_{i+1}'}.pdf"
        if expected_path.exists():
            # 验证是否为真正的 PDF
            try:
                with open(expected_path, "rb") as f:
                    magic = f.read(5)
                if magic == b"%PDF-":
                    print(f"    ✓ 已存在 (断点续传): {expected_path.name}")
                    paper.download_success = True
                    paper.file_path = str(expected_path)
                    paper.file_format = "pdf"
                    paper.file_size = expected_path.stat().st_size
                    success_count += 1
                    consecutive_failures = 0
                    continue
            except OSError:
                pass

        try:
            result = await asyncio.wait_for(
                downloader.download_pdf(
                    paper_url=paper.cnki_url,
                    filename=paper.filename or f"paper_{i+1}",
                ),
                timeout=120.0,  # 2 分钟超时
            )

            if result["success"]:
                success_count += 1
                consecutive_failures = 0
                print(f"    ✓ 下载成功: {result['file_path']}")

                # 更新论文数据
                paper.download_success = True
                paper.file_path = result["file_path"]
                paper.file_format = "pdf"
                p = Path(result["file_path"])
                if p.exists():
                    paper.file_size = p.stat().st_size
            else:
                errors = result.get("errors", [])
                print(f"    ✗ 下载失败: {errors[:2]}")
                paper.errors.extend(errors)
                consecutive_failures += 1

                # 连续失败 3 次，冷却 60 秒
                if consecutive_failures >= 3:
                    print(f"    [!] 连续失败 {consecutive_failures} 次，冷却 60 秒...")
                    await asyncio.sleep(60)
                    consecutive_failures = 0
                    print(f"    [冷却完成] 继续下载")

        except asyncio.TimeoutError:
            print(f"    ✗ 超时 (120s)")
            paper.errors.append("pdf_download: timeout (120s)")
            consecutive_failures += 1
            if consecutive_failures >= 3:
                print(f"    [!] 连续失败 {consecutive_failures} 次，冷却 60 秒...")
                await asyncio.sleep(60)
                consecutive_failures = 0
        except Exception as e:
            print(f"    ✗ 异常: {e}")
            paper.errors.append(f"pdf_download: {e}")
            consecutive_failures += 1

        # 每次下载后随机间隔 10-15 秒（最后一次不需要）
        if i < len(papers) - 1:
            delay = random.uniform(10, 15)
            print(f"    [间隔] 等待 {delay:.1f}s...")
            await asyncio.sleep(delay)

    print(f"\n  PDF 下载完成: {success_count}/{len(papers)} 成功")
    return success_count


async def main_async(args):
    # 解析期刊列表
    if args.journals:
        codes = [c.strip() for c in args.journals.split(",")]
        journals = []
        for code in codes:
            name, disc = JOURNAL_CODE_MAP.get(code, (code, "custom"))
            journals.append((code, name, disc))
    else:
        journals = [(c, n, d) for c, (n, d) in JOURNAL_CODE_MAP.items()][:4]

    print(f"批量采集配置:")
    print(f"  期刊: {[j[1] for j in journals]}")
    print(f"  每刊论文数: {args.papers}")
    print(f"  PDF 下载: {'是' if args.with_pdf else '否'}")
    print(f"  输出目录: {args.output}")
    print()

    Path(args.output).mkdir(parents=True, exist_ok=True)

    papers_data_path = Path(args.output) / "papers_data.json"

    # 阶段 1: 元数据采集（或从缓存加载）
    if args.pdf_only and papers_data_path.exists():
        # 从缓存加载论文数据，跳过 Phase 1
        print(f"\n[Phase 1] 从缓存加载论文数据: {papers_data_path}")
        papers_data = json.loads(papers_data_path.read_text(encoding="utf-8"))
        papers = []
        for pd in papers_data:
            p = FullPaperData()
            for k, v in pd.items():
                if hasattr(p, k):
                    setattr(p, k, v)
            papers.append(p)
        print(f"[Phase 1] 加载 {len(papers)} 篇论文")
    else:
        papers = await batch_harvest_metadata(
            journals=journals,
            papers_per_journal=args.papers,
            output_dir=args.output,
        )

        if not papers:
            print("\n没有采集到论文，退出")
            return

        # 保存论文数据到 JSON（供 --pdf-only 复用）
        papers_data = []
        for p in papers:
            d = {}
            for attr in ["title", "authors", "year", "journal_name", "discipline",
                         "issue_number", "abstract", "keywords", "doi", "cnki_url",
                         "filename", "dbcode", "tablename", "filesourcetype",
                         "pdf_order_url", "caj_order_url", "download_success",
                         "file_path", "file_format", "file_size", "is_core", "citations"]:
                val = getattr(p, attr, None)
                if val is not None:
                    d[attr] = val
            papers_data.append(d)
        papers_data_path.write_text(
            json.dumps(papers_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n[Phase 1] 论文数据已保存: {papers_data_path}")

    # 阶段 2: PDF 下载（可选）
    if args.with_pdf or args.pdf_only:
        await batch_download_pdfs(papers, args.output)

    # 保存最终摘要
    summary = {
        "timestamp": datetime.now().isoformat(),
        "journals": [{"code": c, "name": n, "discipline": d} for c, n, d in journals],
        "papers_per_journal": args.papers,
        "total_papers": len(papers),
        "with_pdf": args.with_pdf or args.pdf_only,
        "pdf_downloaded": sum(1 for p in papers if p.download_success),
    }
    summary_path = Path(args.output) / f"batch_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n摘要已保存: {summary_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="CNKI 批量采集")
    parser.add_argument("--journals", type=str, default="",
                        help="期刊代码列表，逗号分隔 (如 GJXW,YANJ)")
    parser.add_argument("--papers", type=int, default=2,
                        help="每个期刊采集论文数 (默认: 2)")
    parser.add_argument("--with-pdf", action="store_true",
                        help="同时下载 PDF (Playwright headless)")
    parser.add_argument("--pdf-only", action="store_true",
                        help="仅运行 Phase 2 (PDF 下载)，从 papers_data.json 加载元数据")
    parser.add_argument("--output", type=str, default="../数据库/cnki/hybrid",
                        help="输出目录")
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
