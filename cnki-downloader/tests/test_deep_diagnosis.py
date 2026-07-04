# -*- coding: utf-8 -*-
"""Deep diagnosis: Playwright with ignore_https_errors + HTTP variant."""
import asyncio


async def test_playwright_ignore_cert():
    """Test Playwright with ignore_https_errors=True."""
    from playwright.async_api import async_playwright

    print("\n[Test A] Playwright direct + ignore_https_errors -> CNKI https")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
            ignore_https_errors=True,
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
            # Show first 500 chars
            print(f"  Content preview: {content[:500]}")
            if response and response.status == 200:
                print(f"  [SUCCESS] Got 200 with cert ignored!")
                return True
            elif response and response.status == 418:
                print(f"  [BLOCKED] 418 confirmed - IP blocked")
                return False
        except Exception as e:
            print(f"  [ERROR] {type(e).__name__}: {str(e)[:300]}")
            return False
        finally:
            await browser.close()


async def test_playwright_http():
    """Test Playwright with http:// instead of https://."""
    from playwright.async_api import async_playwright

    print("\n[Test B] Playwright direct -> CNKI http://")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )
        page = await context.new_page()
        try:
            response = await page.goto("http://www.cnki.net/", timeout=30000, wait_until="domcontentloaded")
            print(f"  Status: {response.status if response else 'N/A'}")
            print(f"  URL: {page.url}")
            title = await page.title()
            print(f"  Title: {title}")
            content = await page.content()
            print(f"  Content length: {len(content)}")
            if response and response.status == 200:
                print(f"  [SUCCESS] HTTP works!")
                return True
            elif response and response.status == 418:
                print(f"  [BLOCKED] 418 on HTTP too")
                return False
        except Exception as e:
            print(f"  [ERROR] {type(e).__name__}: {str(e)[:300]}")
            return False
        finally:
            await browser.close()


async def test_curl_cffi_cert():
    """Test what certificate CNKI presents via curl_cffi."""
    from curl_cffi import requests as cffi_requests
    import ssl

    print("\n[Test C] Check CNKI SSL certificate via curl_cffi")
    try:
        r = cffi_requests.get("https://www.cnki.net/", impersonate="chrome124", timeout=15, verify=False)
        print(f"  Status: {r.status_code}")
        print(f"  Headers: {dict(r.headers)}")
        print(f"  Content length: {len(r.content)}")
        print(f"  Content preview: {r.text[:300]}")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")


async def test_curl_cffi_kns():
    """Test CNKI kns subdomain."""
    from curl_cffi import requests as cffi_requests

    print("\n[Test D] curl_cffi -> kns.cnki.net")
    urls = [
        "https://kns.cnki.net/",
        "https://kns.cnki.net/kns8s/defaultresult/index",
        "http://kns.cnki.net/",
    ]
    for url in urls:
        try:
            r = cffi_requests.get(url, impersonate="chrome124", timeout=15, verify=False)
            print(f"  {url} -> Status: {r.status_code}, len: {len(r.content)}")
        except Exception as e:
            print(f"  {url} -> [ERROR] {type(e).__name__}: {str(e)[:150]}")


async def main():
    print("=" * 70)
    print("Deep Diagnosis: CNKI 418 Root Cause Analysis")
    print("=" * 70)

    await test_curl_cffi_cert()
    await test_curl_cffi_kns()
    await test_playwright_ignore_cert()
    await test_playwright_http()

    print("\n" + "=" * 70)
    print("Diagnosis complete.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
