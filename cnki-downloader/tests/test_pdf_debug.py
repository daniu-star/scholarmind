"""CNKI Cookie 测试脚本 — 阶段 5 调试: 查看 PDF 下载返回的 HTML 内容

用于分析 PDF 下载失败的根本原因。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.hybrid_scraper import CNKIHybridScraper


async def debug_pdf_download():
    """调试 PDF 下载，查看返回的 HTML 内容。"""
    print("=" * 70)
    print("阶段 5 调试: 查看 PDF 下载返回的 HTML 内容")
    print("=" * 70)

    cookies = CNKIHybridScraper.load_cookies_from_file(str(PROJECT_ROOT / "cookies.json"))
    scraper = CNKIHybridScraper(
        cookies=cookies,
        output_dir=str(PROJECT_ROOT / "tests" / "output" / "pdf_debug"),
        browser_fallback=False,
    )

    # 预热
    await scraper.warmup_session()

    # 发现论文
    papers_rss = await scraper.discover_papers_rss("GJXW", max_papers=3)
    if not papers_rss:
        print("✗ RSS 未发现论文")
        await scraper.close()
        return

    rss_item = papers_rss[0]
    print(f"论文: {rss_item.get('title', '')[:60]}")

    # 提取详情页
    paper = await scraper.extract_detail_page(rss_item["link"], discipline="新闻传播学")
    print(f"filename: {paper.filename}")
    print(f"pdf_order_url: {paper.pdf_order_url}")
    print(f"auth_check_url: {paper.auth_check_url}")

    tls = await scraper._get_tls()

    # 1. 测试 bar.cnki.net 下载
    print("\n" + "=" * 50)
    print("[1] bar.cnki.net 下载测试")
    print("=" * 50)
    if paper.pdf_order_url:
        headers = {
            **scraper.default_headers,
            "Referer": paper.cnki_url,
            "Accept": "application/pdf,text/html,*/*",
        }
        resp = await tls.get(paper.pdf_order_url, headers=headers)
        print(f"status: {resp.status_code}")
        print(f"final_url: {resp.url}")
        print(f"content_type: {resp.headers.get('Content-Type', '') or resp.headers.get('content-type', '')}")
        print(f"content_length: {len(resp.content)}")
        print(f"server: {resp.headers.get('server', '') or resp.headers.get('Server', '')}")
        # 保存 HTML 内容
        debug_dir = PROJECT_ROOT / "tests" / "output" / "pdf_debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "bar_response.html").write_bytes(resp.content)
        print(f"HTML 已保存: {debug_dir / 'bar_response.html'}")
        # 打印前 2000 字符
        text = resp.text
        print(f"\n--- HTML 内容 (前 2000 字符) ---")
        print(text[:2000])
        print("--- end ---")

    # 2. 测试 x.cnki.net auth-check
    print("\n" + "=" * 50)
    print("[2] x.cnki.net auth-check 测试")
    print("=" * 50)
    if paper.filename:
        auth_url = (
            f"https://x.cnki.net/web/page/auth-check"
            f"?redirectsource=zkjbj&redirectjump=yxread"
            f"&filesourcetype={paper.filesourcetype or '1'}"
            f"&dbcode={paper.dbcode or 'CJFQ'}"
            f"&tablename={paper.tablename}"
            f"&filename={paper.filename}"
        )
        print(f"URL: {auth_url}")
        headers = {
            **scraper.default_headers,
            "Referer": paper.cnki_url,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        resp = await tls.get(auth_url, headers=headers)
        print(f"status: {resp.status_code}")
        print(f"final_url: {resp.url}")
        print(f"content_type: {resp.headers.get('Content-Type', '') or resp.headers.get('content-type', '')}")
        print(f"content_length: {len(resp.content)}")
        (debug_dir / "auth_check_response.html").write_bytes(resp.content)
        print(f"HTML 已保存: {debug_dir / 'auth_check_response.html'}")
        text = resp.text
        print(f"\n--- HTML 内容 (前 2000 字符) ---")
        print(text[:2000])
        print("--- end ---")

    # 3. 测试 gateway.cnki.net
    print("\n" + "=" * 50)
    print("[3] gateway.cnki.net 测试")
    print("=" * 50)
    if paper.filename:
        gw_url = f"https://gateway.cnki.net/web/page/download?filename={paper.filename}&dbcode={paper.dbcode or 'CJFQ'}"
        print(f"URL: {gw_url}")
        headers = {
            **scraper.default_headers,
            "Referer": paper.cnki_url,
            "Accept": "application/pdf,text/html,*/*",
        }
        resp = await tls.get(gw_url, headers=headers)
        print(f"status: {resp.status_code}")
        print(f"final_url: {resp.url}")
        print(f"content_type: {resp.headers.get('Content-Type', '') or resp.headers.get('content-type', '')}")
        print(f"content_length: {len(resp.content)}")
        (debug_dir / "gateway_response.html").write_bytes(resp.content)
        print(f"HTML 已保存: {debug_dir / 'gateway_response.html'}")
        text = resp.text
        print(f"\n--- HTML 内容 (前 2000 字符) ---")
        print(text[:2000])
        print("--- end ---")

    # 4. 测试 legacy kcms/detail
    print("\n" + "=" * 50)
    print("[4] legacy kcms/detail 测试")
    print("=" * 50)
    if paper.filename:
        legacy_url = f"https://kns.cnki.net/kcms/detail/detail.aspx?dbcode={paper.dbcode or 'CJFQ'}&filename={paper.filename}&flag=download"
        print(f"URL: {legacy_url}")
        headers = {
            **scraper.default_headers,
            "Referer": paper.cnki_url,
            "Accept": "application/pdf,text/html,*/*",
        }
        resp = await tls.get(legacy_url, headers=headers)
        print(f"status: {resp.status_code}")
        print(f"final_url: {resp.url}")
        print(f"content_type: {resp.headers.get('Content-Type', '') or resp.headers.get('content-type', '')}")
        print(f"content_length: {len(resp.content)}")
        (debug_dir / "legacy_response.html").write_bytes(resp.content)
        print(f"HTML 已保存: {debug_dir / 'legacy_response.html'}")
        text = resp.text
        print(f"\n--- HTML 内容 (前 2000 字符) ---")
        print(text[:2000])
        print("--- end ---")

    await scraper.close()


if __name__ == "__main__":
    asyncio.run(debug_pdf_download())
