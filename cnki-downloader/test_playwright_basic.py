"""Test CNKI access via Playwright with a real browser."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from playwright.async_api import async_playwright


async def test_playwright():
    print("=" * 70)
    print("Test: Playwright browser access to CNKI")
    print("=" * 70)

    async with async_playwright() as p:
        # Launch a visible browser for debugging
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="zh-CN",
        )
        page = await context.new_page()

        # Test 1: Visit CNKI homepage
        print("\n[1] Navigating to www.cnki.net...")
        try:
            await page.goto("https://www.cnki.net/", wait_until="domcontentloaded", timeout=30000)
            print(f"    Status: OK")
            print(f"    URL: {page.url}")
            print(f"    Title: {await page.title()}")
            content = await page.content()
            print(f"    Content length: {len(content)} bytes")

            # Check for blocking
            if "418" in content[:500] or "访问受限" in content or "拦截" in content:
                print("    -> BLOCKED by CNKI anti-bot!")
            elif "中央民族大学" in content or await page.query_selector('[class*="login"]'):
                print("    -> Auth status: checking...")
            else:
                print("    -> Page loaded, checking for search box...")
        except Exception as e:
            print(f"    ERROR: {e}")

        # Test 2: Visit KNS search page
        print("\n[2] Navigating to kns.cnki.net...")
        try:
            await page.goto(
                "https://kns.cnki.net/kns8s/",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            print(f"    URL: {page.url}")
            print(f"    Title: {await page.title()}")
            content = await page.content()
            print(f"    Content length: {len(content)} bytes")
            if "418" in content[:500]:
                print("    -> BLOCKED by CNKI anti-bot!")
        except Exception as e:
            print(f"    ERROR: {e}")

        # Test 3: Load cookies and try auth-check
        print("\n[3] Loading cookies from cookies.json...")
        import json
        cookies_data = json.loads(
            open(
                os.path.join(os.path.dirname(__file__), "cookies.json"),
                encoding="utf-8",
            ).read()
        )["cookies"]

        # Add cookies one by one for all CNKI domains
        for name, value in cookies_data.items():
            if value:
                for domain in [".cnki.net", "www.cnki.net", "kns.cnki.net", ".kns.cnki.net"]:
                    try:
                        await context.add_cookies([
                            {
                                "name": name,
                                "value": value,
                                "domain": domain,
                                "path": "/",
                            }
                        ])
                    except Exception:
                        pass

        print("    Cookies loaded, navigating to CNKI with auth...")
        try:
            await page.goto("https://www.cnki.net/", wait_until="domcontentloaded", timeout=30000)
            print(f"    URL: {page.url}")
            title = await page.title()
            print(f"    Title: {title}")
            content = await page.content()

            if "中央民族大学" in content:
                print("    -> AUTH OK: 中央民族大学图书馆 detected!")
            elif "dx0741" in content:
                print("    -> Auth cookie detected in page")
            elif "418" in content[:500]:
                print("    -> BLOCKED (418)")
            else:
                print(f"    -> Unknown state, length={len(content)}")

            # Print visible text from the page
            body_text = await page.evaluate("() => document.body?.innerText?.substring(0, 500) || 'N/A'")
            print(f"    Body text preview:\n{body_text}")
        except Exception as e:
            print(f"    ERROR: {e}")

        print("\n[4] Browser will stay open for 30s for inspection...")
        print("    (Close the browser window to exit)")
        await asyncio.sleep(30)
        await browser.close()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(test_playwright())
