"""Quick headless Playwright test of CNKI access."""
import asyncio
import json
import os

from playwright.async_api import async_playwright


async def quick_test():
    print("=" * 60)
    print("Quick Playwright Test: CNKI Access Check")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="zh-CN",
        )
        page = await context.new_page()

        # Test homepage
        try:
            resp = await page.goto("https://www.cnki.net/", wait_until="domcontentloaded", timeout=20000)
            print(f"\n[Homepage] Status: {resp.status if resp else 'N/A'}")
            print(f"  URL: {page.url}")
            title = await page.title()
            print(f"  Title: {title}")
        except Exception as e:
            print(f"\n[Homepage] ERROR: {e}")

        # Test with cookies
        print("\n[Loading cookies...]")
        cookies_file = os.path.join(os.path.dirname(__file__), "cookies.json")
        cookies_data = json.loads(open(cookies_file, encoding="utf-8").read())["cookies"]
        for name, value in cookies_data.items():
            if value:
                try:
                    await context.add_cookies([{"name": name, "value": value, "domain": ".cnki.net", "path": "/"}])
                except Exception:
                    pass

        try:
            resp = await page.goto("https://www.cnki.net/", wait_until="domcontentloaded", timeout=20000)
            print(f"\n[Homepage + Cookies] Status: {resp.status if resp else 'N/A'}")
            print(f"  URL: {page.url}")
            body_text = await page.evaluate("() => document.body?.innerText?.substring(0, 600) || ''")
            print(f"  Body:\n{body_text[:600]}")
        except Exception as e:
            print(f"  ERROR: {e}")

        # Try KNS search page
        try:
            resp = await page.goto("https://kns.cnki.net/kns8s/", wait_until="domcontentloaded", timeout=20000)
            print(f"\n[KNS Search] Status: {resp.status if resp else 'N/A'}")
            print(f"  URL: {page.url}")
            body_text = await page.evaluate("() => document.body?.innerText?.substring(0, 600) || ''")
            print(f"  Body:\n{body_text[:600]}")
        except Exception as e:
            print(f"  ERROR: {e}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(quick_test())
