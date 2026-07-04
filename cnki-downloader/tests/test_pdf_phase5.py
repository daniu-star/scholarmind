"""CNKI Cookie 测试脚本 — 阶段 5: PDF 下载测试

从阶段 4 中选 1 篇有 download_url 的论文，运行 download_pdf_with_retry() 测试 PDF 下载。
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

from crawler.hybrid_scraper import CNKIHybridScraper, FullPaperData


async def test_pdf_download():
    """测试 PDF 下载。"""
    print("=" * 70)
    print("阶段 5: PDF 下载测试")
    print("=" * 70)

    cookies = CNKIHybridScraper.load_cookies_from_file(str(PROJECT_ROOT / "cookies.json"))
    print(f"[0] Cookies 加载成功，共 {len(cookies)} 个字段")

    scraper = CNKIHybridScraper(
        cookies=cookies,
        output_dir=str(PROJECT_ROOT / "tests" / "output" / "pdf_test"),
        browser_fallback=False,  # 不启用浏览器降级，纯 HTTP 测试
    )

    result = {
        "phase": "pdf_download",
        "paper": None,
        "download_success": False,
        "strategies_tried": [],
        "errors": [],
        "duration_sec": 0.0,
    }

    # 先预热会话
    print(f"\n[预热] 调用 warmup_session()...")
    warmup_ok = await scraper.warmup_session()
    print(f"[预热] warmup_session() 返回: {warmup_ok}")
    if not warmup_ok:
        print("✗ 会话预热失败，无法继续")
        await scraper.close()
        return result

    # 用 RSS 发现论文并提取详情页
    print(f"\n[RSS] 发现 GJXW 国际新闻界论文...")
    papers_rss = await scraper.discover_papers_rss("GJXW", max_papers=5)
    print(f"[RSS] 发现 {len(papers_rss)} 篇论文")

    if not papers_rss:
        print("✗ RSS 未发现论文")
        await scraper.close()
        return result

    # 选第一篇论文
    rss_item = papers_rss[0]
    print(f"\n[选择] 论文: {rss_item.get('title', '')[:60]}")
    print(f"       URL: {rss_item['link'][:100]}")

    # 提取详情页
    print(f"\n[详情页] 提取详情页元数据...")
    paper = await scraper.extract_detail_page(rss_item["link"], discipline="新闻传播学")
    paper.journal_name = "国际新闻界"

    print(f"       title: {paper.title[:60]}")
    print(f"       filename: {paper.filename}")
    print(f"       dbcode: {paper.dbcode}")
    print(f"       tablename: {paper.tablename}")
    print(f"       filesourcetype: {paper.filesourcetype}")
    print(f"       pdf_order_url: {paper.pdf_order_url[:80] if paper.pdf_order_url else '(无)'}")
    print(f"       caj_order_url: {paper.caj_order_url[:80] if paper.caj_order_url else '(无)'}")
    print(f"       auth_check_url: {paper.auth_check_url[:80] if paper.auth_check_url else '(无)'}")

    if not (paper.pdf_order_url or paper.auth_check_url or paper.filename):
        print("✗ 未找到任何下载 URL，无法测试 PDF 下载")
        result["errors"].append("no download URL found")
        await scraper.close()
        return result

    # 调用 download_pdf_with_retry
    print(f"\n[下载] 调用 download_pdf_with_retry()...")
    print(f"       策略优先级: {scraper._get_strategy_priority()}")

    t0 = time.time()
    try:
        paper = await scraper.download_pdf_with_retry(paper, max_retries=2)
        elapsed = time.time() - t0
        result["duration_sec"] = round(elapsed, 2)

        print(f"\n[结果] 下载耗时: {elapsed:.2f}s")
        print(f"       download_success: {paper.download_success}")
        print(f"       file_path: {paper.file_path}")
        print(f"       file_format: {paper.file_format}")
        print(f"       file_size: {paper.file_size} bytes")
        print(f"       file_checksum: {paper.file_checksum}")
        print(f"       body_text_length: {paper.body_text_length}")
        print(f"       errors: {paper.errors}")

        result["download_success"] = paper.download_success
        result["paper"] = {
            "title": paper.title,
            "filename": paper.filename,
            "dbcode": paper.dbcode,
            "pdf_order_url": paper.pdf_order_url,
            "caj_order_url": paper.caj_order_url,
            "auth_check_url": paper.auth_check_url,
            "download_success": paper.download_success,
            "file_path": paper.file_path,
            "file_format": paper.file_format,
            "file_size": paper.file_size,
            "file_checksum": paper.file_checksum,
            "body_text_length": paper.body_text_length,
            "errors": paper.errors,
        }
        result["errors"] = paper.errors

        # 验证文件魔数（如果下载成功）
        if paper.download_success and paper.file_path:
            file_path = Path(paper.file_path)
            if file_path.exists():
                with open(file_path, "rb") as f:
                    magic = f.read(8)
                print(f"\n[魔数校验] 文件前 8 字节: {magic!r}")
                if magic[:5] == b"%PDF-":
                    print(f"  ✓ 有效 PDF 文件 (%PDF-)")
                    result["magic_check"] = "valid_pdf"
                elif magic[:4] == b"PK\x03\x04":
                    print(f"  ✓ 有效 CAJ/ZIP 文件 (PK)")
                    result["magic_check"] = "valid_caj"
                else:
                    print(f"  ✗ 无效文件格式")
                    result["magic_check"] = f"invalid: {magic!r}"
                    # 检查是否是 HTML
                    if magic[:1] == b"<" or b"<!DOCTYPE" in magic:
                        print(f"  ⚠ 文件是 HTML 而非 PDF")
                        result["magic_check"] = "html_response"
            else:
                print(f"\n[魔数校验] ✗ 文件不存在: {file_path}")
                result["magic_check"] = "file_not_found"
        else:
            result["magic_check"] = "no_file"

    except Exception as e:
        elapsed = time.time() - t0
        result["duration_sec"] = round(elapsed, 2)
        result["errors"].append(f"{type(e).__name__}: {e}")
        print(f"\n✗ 异常: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    # 检查封锁状态
    block_status = scraper.get_cnki_block_status()
    result["block_status"] = block_status
    print(f"\n[封锁状态] 当前代理: {block_status['current_proxy'] or '直连'}")
    print(f"           被封锁代理数: {block_status['blocked_count']}")
    print(f"           可用代理数: {block_status['available_proxies']}")

    # 错误日志
    print(f"\n[错误日志] 共 {len(scraper.error_log)} 条")
    if scraper.error_log:
        for i, err in enumerate(scraper.error_log[:5], 1):
            print(f"  {i}. [{err.get('type', '')}] {err.get('message', '')[:100]}")
        result["error_log"] = scraper.error_log

    # 统计
    print(f"\n[统计] {json.dumps(scraper.stats, ensure_ascii=False, indent=2)}")
    result["stats"] = scraper.stats

    # 保存结果
    output_path = PROJECT_ROOT / "tests" / "output" / "pdf_test_result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n结果已保存: {output_path}")

    await scraper.close()

    print("\n" + "=" * 70)
    print("阶段 5 测试结果摘要")
    print("=" * 70)
    print(f"下载成功: {'是' if result['download_success'] else '否'}")
    print(f"耗时: {result['duration_sec']}s")
    print(f"魔数校验: {result.get('magic_check', 'N/A')}")
    if result["errors"]:
        print(f"错误: {result['errors']}")

    return result


if __name__ == "__main__":
    asyncio.run(test_pdf_download())
