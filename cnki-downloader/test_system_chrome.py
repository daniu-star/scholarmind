"""Test CNKI access with system Chrome via Playwright (visible browser)."""
import asyncio
from playwright.async_api import async_playwright


async def test():
    print("=" * 60)
    print("Testing CNKI with System Chrome (visible browser)")
    print("=" * 60)

    async with async_playwright() as p:
        # Try system Chrome first, fall back to bundled Chromium
        try:
            browser = await p.chromium.launch(
                headless=False,
                channel="chrome",
            )
            print("[OK] Using system Chrome")
        except Exception:
            print("[OK] Using bundled Chromium")
            browser = await p.chromium.launch(headless=False)

        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
            ignore_https_errors=True,
        )
        page = await context.new_page()

        print("\n[1] Opening CNKI homepage...")
        try:
            resp = await page.goto(
                "https://www.cnki.net/",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            print(f"    HTTP {resp.status if resp else 'N/A'}")
            print(f"    URL: {page.url}")
            title = await page.title()
            print(f"    Title: {title}")
            body = await page.evaluate('() => document.body?.innerText?.substring(0, 600) || ""')
            print(f"    Body: {body[:600]}")
        except Exception as e:
            print(f"    Error: {e}")

        print("\n[2] Opening KNS search page...")
        try:
            resp = await page.goto(
                "https://kns.cnki.net/kns8s/",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            print(f"    HTTP {resp.status if resp else 'N/A'}")
            print(f"    URL: {page.url}")
            title = await page.title()
            print(f"    Title: {title}")
            body = await page.evaluate('() => document.body?.innerText?.substring(0, 600) || ""')
            print(f"    Body: {body[:600]}")
        except Exception as e:
            print(f"    Error: {e}")

        print("\n[3] Browser open for 60s for manual inspection...")
        print("    (Close browser window to exit)")
        await asyncio.sleep(60)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test())
