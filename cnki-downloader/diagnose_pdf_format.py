#!/usr/bin/env python3
"""诊断 CNKI PDF 下载格式问题 — 检查 #pdfDown 按钮的实际下载行为。"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

from crawler.hybrid_scraper import CNKIHybridScraper


async def diagnose():
    cookies = CNKIHybridScraper.load_cookies_from_file("cookies.json")

    # 获取论文 URL
    scraper = CNKIHybridScraper(cookies=cookies, browser_fallback=False)
    try:
        papers = await scraper.harvest_paper(
            journal_code="GJXW", journal_name="国际新闻界",
            discipline="新闻传播学", max_papers=1, download_pdfs=False,
        )
        paper = papers[0]
        print(f"论文: {paper.title[:60]}")
        print(f"URL: {paper.cnki_url[:100]}")
        print(f"pdf_order_url: {paper.pdf_order_url[:100] if paper.pdf_order_url else 'None'}")
        print(f"caj_order_url: {paper.caj_order_url[:100] if paper.caj_order_url else 'None'}")
    finally:
        await scraper.close()

    from playwright.async_api import async_playwright

    pw_cookies = []
    for name, value in cookies.items():
        if value:
            pw_cookies.append({"name": name, "value": str(value), "domain": ".cnki.net", "path": "/"})

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            accept_downloads=True,
        )
        await context.add_cookies(pw_cookies)

        page = await context.new_page()
        await page.goto(paper.cnki_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        # 检查所有下载相关按钮的 href
        print("\n=== 下载按钮 href 分析 ===")
        for sel in ["#pdfDown", "#cajDown", 'a[href*="bar.cnki.net"]', 'a[href*="download"]']:
            els = await page.query_selector_all(sel)
            for el in els:
                href = await el.get_attribute("href")
                text = await el.text_content()
                if href:
                    print(f"  {sel}: text='{text}', href={href[:120]}")
                    # 检查 URL 中是否有格式参数
                    if "format" in href.lower() or "type" in href.lower():
                        print(f"    ^^^ 包含格式参数!")

        # 检查页面中是否有其他 PDF 下载方式
        print("\n=== 页面中 PDF 相关链接 ===")
        all_links = await page.query_selector_all("a")
        for link in all_links:
            href = await link.get_attribute("href")
            text = await link.text_content()
            if href and text:
                text = text.strip()
                if "pdf" in text.lower() or "PDF" in href or "pdf" in href.lower():
                    print(f"  text='{text}', href={href[:120]}")

        # 尝试点击 #pdfDown 并检查下载的文件
        print("\n=== 测试 #pdfDown 下载 ===")
        downloads = []
        async def on_download(download):
            print(f"[下载事件] filename={download.suggested_filename}")
            # 获取下载 URL
            dl_url = download.url
            print(f"[下载事件] url={dl_url[:150]}")
            # 保存到临时文件检查格式
            import tempfile
            tmp = Path(tempfile.gettempdir()) / f"test_{download.suggested_filename}"
            await download.save_as(str(tmp))
            with open(tmp, "rb") as f:
                magic = f.read(10)
            print(f"[下载事件] magic={magic!r}")
            print(f"[下载事件] size={tmp.stat().st_size} bytes")
            downloads.append(download)

        page.on("download", lambda d: asyncio.create_task(on_download(d)))
        context.on("page", lambda pg: pg.on("download", lambda d: asyncio.create_task(on_download(d))))

        btn = await page.query_selector("#pdfDown")
        if btn:
            href = await btn.get_attribute("href")
            print(f"#pdfDown href: {href[:150]}")
            await btn.click(timeout=5000)
            await asyncio.sleep(15)

            if not downloads:
                print("未触发下载事件!")
        else:
            print("#pdfDown 按钮不存在!")

        await browser.close()

    print("\n=== 诊断完成 ===")


if __name__ == "__main__":
    from pathlib import Path
    asyncio.run(diagnose())
