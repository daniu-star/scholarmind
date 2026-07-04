# -*- coding: utf-8 -*-
"""Test if Playwright (real browser) can bypass CNKI 418 block."""
import asyncio
import sys
import os

async def test_playwright_direct():
    """Test 1: Playwright direct access to CNKI (no proxy)."""
    from playwright.async_api import async_playwright

    print("\n[Test 1] Playwright direct (no proxy) -> CNKI homepage")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )
        page = await context.new_page()
        try:
            response = await page.goto("https://www.cnki.net/", timeout=30000, wait_until="domcontentloaded")
            print(f"  Status: {response.status if response else 'N/A'}")
            print(f"  URL: {page.url}")
            title = await page.title()
            print(f"  Title: {title}")
            content = await page.content()
            print(f"  Content length: {len(content)}")
            if response and response.status == 200:
                print(f"  [SUCCESS] Playwright bypassed 418!")
                # Check if it's real CNKI content
                if "cnki" in content.lower() or "知网" in content:
                    print(f"  [CONFIRMED] Real CNKI content received")
                return True
            elif response and response.status == 418:
                print(f"  [BLOCKED] 418 even with Playwright - IP is blocked")
                return False
            else:
                print(f"  [UNKNOWN] Status {response.status if response else 'N/A'}")
                return False
        except Exception as e:
            print(f"  [ERROR] {type(e).__name__}: {e}")
            return False
        finally:
            await browser.close()


async def test_playwright_search():
    """Test 2: Playwright access to CNKI search page."""
    from playwright.async_api import async_playwright

    print("\n[Test 2] Playwright direct -> CNKI search endpoint")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )
        page = await context.new_page()
        try:
            # Try the search endpoint
            response = await page.goto("https://kns.cnki.net/kns8s/defaultresult/index", timeout=30000, wait_until="domcontentloaded")
            print(f"  Status: {response.status if response else 'N/A'}")
            print(f"  URL: {page.url}")
            title = await page.title()
            print(f"  Title: {title}")
            content = await page.content()
            print(f"  Content length: {len(content)}")
            if response and response.status == 200:
                print(f"  [SUCCESS] Search page accessible!")
                return True
            elif response and response.status == 418:
                print(f"  [BLOCKED] 418 on search page too")
                return False
            else:
                print(f"  [UNKNOWN] Status {response.status if response else 'N/A'}")
                return False
        except Exception as e:
            print(f"  [ERROR] {type(e).__name__}: {e}")
            return False
        finally:
            await browser.close()


async def test_playwright_with_proxy():
    """Test 3: Playwright with Clash proxy (7890)."""
    from playwright.async_api import async_playwright

    print("\n[Test 3] Playwright + proxy 7890 -> CNKI")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--proxy-server=http://127.0.0.1:7890"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )
        page = await context.new_page()
        try:
            response = await page.goto("https://www.cnki.net/", timeout=30000, wait_until="domcontentloaded")
            print(f"  Status: {response.status if response else 'N/A'}")
            print(f"  URL: {page.url}")
            if response and response.status == 200:
                print(f"  [SUCCESS] Playwright + proxy bypassed 418!")
                return True
            elif response and response.status == 418:
                print(f"  [BLOCKED] 418 even with Playwright + proxy")
                return False
            else:
                print(f"  [UNKNOWN] Status {response.status if response else 'N/A'}")
                return False
        except Exception as e:
            print(f"  [ERROR] {type(e).__name__}: {str(e)[:200]}")
            return False
        finally:
            await browser.close()


async def test_playwright_non_cnki():
    """Test 4: Playwright access to non-CNKI site (control test)."""
    from playwright.async_api import async_playwright

    print("\n[Test 4] Playwright direct -> baidu.com (control test)")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()
        try:
            response = await page.goto("https://www.baidu.com", timeout=20000, wait_until="domcontentloaded")
            print(f"  Status: {response.status if response else 'N/A'}")
            title = await page.title()
            print(f"  Title: {title}")
            if response and response.status == 200:
                print(f"  [OK] Browser works for non-CNKI sites")
            return response and response.status == 200
        except Exception as e:
            print(f"  [ERROR] {type(e).__name__}: {e}")
            return False
        finally:
            await browser.close()


async def main():
    print("=" * 70)
    print("Playwright Browser Test - Can real browser bypass CNKI 418?")
    print("=" * 70)

    # Control test first
    await test_playwright_non_cnki()

    # Test 1: Direct access
    direct_ok = await test_playwright_direct()

    # Test 2: Search page
    if direct_ok:
        await test_playwright_search()

    # Test 3: With proxy (only if direct fails or for comparison)
    if not direct_ok:
        await test_playwright_with_proxy()

    print("\n" + "=" * 70)
    print("Summary:")
    if direct_ok:
        print("  - Playwright (real browser) CAN bypass 418 directly")
        print("  - Strategy: Use browser_fallback.py as primary method")
    else:
        print("  - Playwright direct also gets 418 - IP is blocked")
        print("  - Need working proxy or alternative network")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
