"""Quick headless Playwright test with SSL errors ignored."""
import asyncio
import json
import os

from playwright.async_api import async_playwright


async def quick_test():
    print("=" * 60)
    print("Quick Playwright Test: CNKI Access (SSL ignored)")
    print("=" * 60)

    async with async_playwright() as p:
        # Launch with SSL errors ignored
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="zh-CN",
            ignore_https_errors=True,
        )
        page = await context.new_page()

        # Test homepage
        try:
            resp = await page.goto("https://www.cnki.net/", wait_until="domcontentloaded", timeout=20000)
            print(f"\n[Homepage] HTTP {resp.status if resp else 'N/A'}")
            print(f"  Final URL: {page.url}")
            title = await page.title()
            print(f"  Title: {title}")
            body = await page.evaluate("() => document.body?.innerText?.substring(0, 400) || ''")
            print(f"  Body: {body}")
        except Exception as e:
            print(f"\n[Homepage] ERROR: {e}")

        # Test kns.cnki.net
        try:
            resp = await page.goto("https://kns.cnki.net/kns8s/", wait_until="domcontentloaded", timeout=20000)
            print(f"\n[KNS] HTTP {resp.status if resp else 'N/A'}")
            print(f"  Final URL: {page.url}")
            title = await page.title()
            print(f"  Title: {title}")
            body = await page.evaluate("() => document.body?.innerText?.substring(0, 400) || ''")
            print(f"  Body: {body}")
        except Exception as e:
            print(f"\n[KNS] ERROR: {e}")

        # Test RSS feed (no cookies needed)
        try:
            resp = await page.goto(
                "https://rss.cnki.net/knavi/rss/GJXW?pcode=CJFD,CCJD",
                wait_until="domcontentloaded",
                timeout=20000,
            )
            print(f"\n[RSS GJXW] HTTP {resp.status if resp else 'N/A'}")
            body = await page.evaluate("() => document.body?.innerText?.substring(0, 500) || ''")
            print(f"  Body: {body}")
        except Exception as e:
            print(f"\n[RSS] ERROR: {e}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(quick_test())
