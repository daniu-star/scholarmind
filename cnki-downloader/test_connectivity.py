"""Test CNKI connectivity with various approaches."""
import asyncio
import json
from curl_cffi.requests import AsyncSession


async def test_impersonation():
    results = []

    versions = ["chrome120", "chrome124", "chrome124_auto", "safari17_0", "edge99"]
    for imp in versions:
        try:
            s = AsyncSession(impersonate=imp, timeout=15, verify=False)
            r = await s.get(
                "https://www.cnki.net/",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,application/signed-exchange;v=b3;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                    "Sec-Ch-Ua-Mobile": "?0",
                    "Sec-Ch-Ua-Platform": '"Windows"',
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1",
                    "Upgrade-Insecure-Requests": "1",
                },
            )
            results.append(f"{imp}: HTTP {r.status_code}, URL: {r.url}")
            await s.close()
        except Exception as e:
            results.append(f"{imp}: Error - {str(e)[:80]}")

    for r in results:
        print(r)


async def test_minimal_headers():
    """Test with minimal headers to see if CNKI is checking header patterns."""
    s = AsyncSession(impersonate="chrome124", timeout=15, verify=False)
    # Minimal browser-like headers
    r = await s.get(
        "https://www.cnki.net/",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    print(f"Minimal headers: HTTP {r.status_code}, URL: {r.url}")
    await s.close()


async def test_with_cookies():
    """Test with cookies from cookies.json."""
    cookies = json.loads(
        open(
            r"C:\Users\13067\Desktop\AI产品\cnki-downloader\cookies.json",
            encoding="utf-8",
        ).read()
    )["cookies"]

    s = AsyncSession(impersonate="chrome124", timeout=15, verify=False)
    for name, value in cookies.items():
        if value:
            s.cookies.set(name, value, domain=".cnki.net")

    r = await s.get(
        "https://www.cnki.net/",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    print(f"With cookies: HTTP {r.status_code}, URL: {r.url}")
    await s.close()


async def test_rss():
    """Test RSS feed access."""
    s = AsyncSession(impersonate="chrome124", timeout=15, verify=False)
    r = await s.get(
        "https://rss.cnki.net/knavi/rss/GJXW?pcode=CJFD,CCJD",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        },
    )
    print(f"RSS GJXW: HTTP {r.status_code}")
    if r.status_code == 200:
        print(f"  Content: {r.text[:300]}")
    await s.close()


async def test_kns():
    """Test kns.cnki.net with cookies."""
    cookies = json.loads(
        open(
            r"C:\Users\13067\Desktop\AI产品\cnki-downloader\cookies.json",
            encoding="utf-8",
        ).read()
    )["cookies"]

    s = AsyncSession(impersonate="chrome124", timeout=15, verify=False)
    for name, value in cookies.items():
        if value:
            s.cookies.set(name, value, domain=".kns.cnki.net")

    r = await s.get(
        "https://kns.cnki.net/kns8s/",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    print(f"kns.cnki.net with cookies: HTTP {r.status_code}, URL: {r.url}")
    if r.status_code == 200:
        if "中央民族大学" in r.text or "dx0741" in r.text:
            print("  -> Auth OK: 中央民族大学 detected")
        else:
            print(f"  -> Response size: {len(r.text)} bytes, preview: {r.text[:200]}")
    await s.close()


async def main():
    print("=== Test 1: Different TLS impersonation versions ===")
    await test_impersonation()

    print("\n=== Test 2: Minimal headers ===")
    await test_minimal_headers()

    print("\n=== Test 3: With cookies from cookies.json ===")
    await test_with_cookies()

    print("\n=== Test 4: RSS feed ===")
    await test_rss()

    print("\n=== Test 5: KNS with cookies ===")
    await test_kns()


if __name__ == "__main__":
    asyncio.run(main())
