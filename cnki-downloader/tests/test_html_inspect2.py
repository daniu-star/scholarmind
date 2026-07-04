"""CNKI Cookie 测试脚本 — 阶段 7 辅助: 查看详情页 HTML 结构（使用已知 URL）

使用阶段 4 保存的论文 URL 来检查 HTML 结构。
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.hybrid_scraper import CNKIHybridScraper
from bs4 import BeautifulSoup


# 使用阶段 4 保存的论文 URL
PAPER_URL = "https://kns.cnki.net/kcms2/article/abstract?v=tjV0JOkNcjBH_mWbfCj13QLJroH-BaqjVgMd6AHbUFkoJ3E7yzn5WrZsWX1MdkPx2t8HSaieh364hotD8gL9rYKVq1zN5cTz0b9C090HFCMZcS-1Ds--9KjU-UXSVTIOmuQQJYSvUUHIJOGnhS-TCJ9yT8bWFiYRkwEIyCXEVy0cuBa_837v0Q==&uniplatform=NZKPT&language=CHS"


async def inspect_detail_html():
    """检查详情页 HTML 结构。"""
    print("=" * 70)
    print("阶段 7 辅助: 检查详情页 HTML 结构")
    print("=" * 70)

    cookies = CNKIHybridScraper.load_cookies_from_file(str(PROJECT_ROOT / "cookies.json"))
    scraper = CNKIHybridScraper(
        cookies=cookies,
        output_dir=str(PROJECT_ROOT / "tests" / "output" / "html_inspect"),
        browser_fallback=False,
    )

    await scraper.warmup_session()

    print(f"论文 URL: {PAPER_URL[:100]}")

    tls = await scraper._get_tls()
    resp = await tls.get(PAPER_URL, headers=scraper.default_headers)
    print(f"status: {resp.status_code}")
    print(f"content_length: {len(resp.content)}")

    html = resp.text
    # 保存 HTML
    debug_dir = PROJECT_ROOT / "tests" / "output" / "html_inspect"
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "detail_page.html").write_text(html, encoding="utf-8")
    print(f"HTML 已保存: {debug_dir / 'detail_page.html'}")

    soup = BeautifulSoup(html, "html.parser")

    # 1. 检查 title
    print("\n" + "=" * 50)
    print("[1] Title 检查")
    print("=" * 50)
    title_el = (
        soup.select_one("h1")
        or soup.select_one(".title")
        or soup.select_one('[class*="title"]')
        or soup.select_one("h2")
    )
    if title_el:
        print(f"title 元素文本: {title_el.get_text(strip=True)[:200]}")
        print(f"元素 tag: {title_el.name}")
        print(f"元素 class: {title_el.get('class', [])}")
        # 检查子元素
        for child in title_el.children:
            if hasattr(child, 'name') and child.name:
                print(f"  子元素: <{child.name} class={child.get('class', [])}> text={child.get_text(strip=True)[:50]}")
    else:
        print("✗ 未找到 title 元素")

    # 搜索 "附视频"
    if "附视频" in html:
        print(f"\n⚠ HTML 中包含 '附视频'")
        for m in re.finditer(r'.{0,80}附视频.{0,80}', html):
            print(f"  上下文: ...{m.group(0)[:200]}...")

    # 2. 检查 authors
    print("\n" + "=" * 50)
    print("[2] Authors 检查")
    print("=" * 50)
    author_el = (
        soup.select_one(".author")
        or soup.select_one('[class*="author"]')
        or soup.select_one('[class*="writer"]')
    )
    if author_el:
        print(f"author 元素文本: {author_el.get_text(strip=True)[:200]}")
        print(f"元素 tag: {author_el.name}")
        print(f"元素 class: {author_el.get('class', [])}")
        print(f"元素 HTML (前 800 字符): {str(author_el)[:800]}")
        # 检查子元素
        for child in author_el.find_all(['a', 'span', 'em', 'sup', 'sub']):
            print(f"  子元素: <{child.name} class={child.get('class', [])}> text={child.get_text(strip=True)[:50]}")
    else:
        print("✗ 未找到 author 元素")
        if "周俊" in html:
            for m in re.finditer(r'.{0,100}周俊.{0,100}', html):
                print(f"  上下文: ...{m.group(0)[:200]}...")

    # 3. 检查 journal_name
    print("\n" + "=" * 50)
    print("[3] Journal Name 检查")
    print("=" * 50)
    journal_el = (
        soup.select_one(".source")
        or soup.select_one('[class*="source"]')
        or soup.select_one(".journal")
        or soup.select_one('[class*="journal"]')
    )
    if journal_el:
        print(f"journal 元素文本: {journal_el.get_text(strip=True)[:200]}")
        print(f"元素 class: {journal_el.get('class', [])}")
    else:
        print("✗ 未找到 .source/[class*='source']/.journal 元素")
        if "国际新闻界" in html:
            for m in re.finditer(r'.{0,100}国际新闻界.{0,100}', html):
                print(f"  上下文: ...{m.group(0)[:200]}...")

    # 4. 检查 issue_number
    print("\n" + "=" * 50)
    print("[4] Issue Number 检查")
    print("=" * 50)
    found_issue = False
    for m in re.finditer(r'.{0,50}第?\d+\s*期.{0,50}', html):
        print(f"  期号上下文: ...{m.group(0)[:150]}...")
        found_issue = True
    for m in re.finditer(r'.{0,50}No\.?\s*\d+.{0,50}', html, re.IGNORECASE):
        print(f"  No.上下文: ...{m.group(0)[:150]}...")
        found_issue = True
    if not found_issue:
        print("  ✗ 未找到期号相关文本")

    # 5. 检查 abstract
    print("\n" + "=" * 50)
    print("[5] Abstract 检查")
    print("=" * 50)
    abstract_el = (
        soup.select_one(".abstract-text")
        or soup.select_one('[class*="abstract"]')
        or soup.select_one("#abstract")
    )
    if abstract_el:
        text = abstract_el.get_text(strip=True)
        print(f"abstract 元素文本 (前 300 字符): {text[:300]}")
        print(f"abstract 元素 class: {abstract_el.get('class', [])}")
        print(f"abstract 元素 HTML (前 500 字符): {str(abstract_el)[:500]}")
    else:
        print("✗ 未找到 abstract 元素")

    # 6. 检查 keywords
    print("\n" + "=" * 50)
    print("[6] Keywords 检查")
    print("=" * 50)
    kw_elements = soup.select(
        ".keywords a, [class*='keyword'] a, .keywords span, [class*='keyword'] span"
    )
    print(f"找到 {len(kw_elements)} 个 keyword 元素")
    for kw_el in kw_elements[:5]:
        print(f"  <{kw_el.name} class={kw_el.get('class', [])}> text={kw_el.get_text(strip=True)}")

    # 7. 检查 download URLs
    print("\n" + "=" * 50)
    print("[7] Download URLs 检查")
    print("=" * 50)
    order_urls = re.findall(
        r'bar\.cnki\.net/bar/download/order\?id=([^"\'&\s]+)', html
    )
    print(f"找到 {len(order_urls)} 个 bar.cnki.net order URLs")
    for i, url in enumerate(order_urls[:5], 1):
        print(f"  {i}. id={url[:80]}...")

    if len(order_urls) >= 2:
        print(f"\n  前 2 个 URL 是否相同: {order_urls[0] == order_urls[1]}")
        print(f"  URL[0] (前 120 字符): {order_urls[0][:120]}")
        print(f"  URL[1] (前 120 字符): {order_urls[1][:120]}")

    # 8. 检查 citations
    print("\n" + "=" * 50)
    print("[8] Citations 检查")
    print("=" * 50)
    cite_match = re.search(
        r'(?:被引|引用|cited?)\s*[：:]\s*(\d+)', html, re.IGNORECASE
    )
    if cite_match:
        print(f"找到被引次数: {cite_match.group(1)}")
    else:
        print("✗ 未找到被引次数")
        for m in re.finditer(r'.{0,50}被引.{0,50}', html):
            print(f"  上下文: ...{m.group(0)[:150]}...")

    # 9. 检查 year
    print("\n" + "=" * 50)
    print("[9] Year 检查")
    print("=" * 50)
    # 搜索年份相关
    for m in re.finditer(r'(?:发表年份|出版年份|年份)[：:]\s*(\d{4})', html):
        print(f"  发表年份: {m.group(1)}")
    for m in re.finditer(r'2026', html):
        start = max(0, m.start() - 50)
        end = min(len(html), m.end() + 50)
        print(f"  2026 上下文: ...{html[start:end]}...")

    await scraper.close()


if __name__ == "__main__":
    asyncio.run(inspect_detail_html())
