"""深度诊断 CNKI 418 拦截根因。

测试维度：
1. 无 cookie 直连（排除 cookie 影响）
2. 不同 TLS 指纹（排除指纹检测）
3. Playwright 真实浏览器（排除 TLS 指纹问题）
4. 不同 CNKI 端点（排除端点特定封锁）
5. 带原始 cookie 直连（确认 cookie 状态）
"""
import asyncio
import time
import json
from pathlib import Path

from curl_cffi.requests import AsyncSession


async def test_no_cookie_direct():
    """测试 1: 无 cookie 直连 CNKI"""
    print("\n[测试 1] 无 cookie 直连 (chrome124)")
    s = AsyncSession(impersonate="chrome124", timeout=15, verify=False)
    r = await s.get("https://www.cnki.net/")
    print(f"  状态码: {r.status_code} | 长度: {len(r.text)}")
    if r.status_code == 200:
        print(f"  ✓ 成功！418 是 cookie 触发的")
    elif r.status_code == 418:
        print(f"  ✗ 仍 418 — 非 cookie 问题，是 TLS 指纹或 IP 问题")
    await s.close()
    return r.status_code


async def test_different_fingerprints():
    """测试 2: 不同 TLS 指纹"""
    fingerprints = ["chrome120", "chrome116", "edge99", "safari17_0"]
    print("\n[测试 2] 不同 TLS 指纹直连")
    for fp in fingerprints:
        try:
            s = AsyncSession(impersonate=fp, timeout=15, verify=False)
            r = await s.get("https://www.cnki.net/")
            print(f"  {fp}: 状态码 {r.status_code}")
            await s.close()
        except Exception as e:
            print(f"  {fp}: 错误 {e}")


async def test_different_endpoints():
    """测试 3: 不同 CNKI 端点"""
    endpoints = [
        ("首页", "https://www.cnki.net/"),
        ("搜索页", "https://kns.cnki.net/kns8s/"),
        ("RSS", "https://rss.cnki.net/knavi/rss/GJXW?pcode=CJFD,CCJD"),
    ]
    print("\n[测试 3] 不同 CNKI 端点 (chrome124, 无 cookie)")
    for name, url in endpoints:
        try:
            s = AsyncSession(impersonate="chrome124", timeout=15, verify=False)
            r = await s.get(url)
            print(f"  {name} ({url[:40]}...): 状态码 {r.status_code} | 长度 {len(r.text)}")
            await s.close()
        except Exception as e:
            print(f"  {name}: 错误 {e}")


async def test_with_cookies():
    """测试 4: 带原始 cookie 直连"""
    print("\n[测试 4] 带 cookie 直连 (chrome124)")
    cookies_path = Path("cookies.json")
    if not cookies_path.exists():
        print("  cookies.json 不存在，跳过")
        return

    cookies = json.loads(cookies_path.read_text(encoding="utf-8"))
    if isinstance(cookies, list):
        cookie_dict = {c["name"]: c["value"] for c in cookies if c.get("name") and c.get("value")}
    elif isinstance(cookies, dict):
        cookie_dict = cookies
    else:
        print("  cookies.json 格式未知")
        return

    s = AsyncSession(impersonate="chrome124", timeout=15, verify=False)
    for domain in [".cnki.net", "cnki.net"]:
        for name, value in cookie_dict.items():
            if value:
                s.cookies.set(name, value, domain=domain)

    r = await s.get("https://www.cnki.net/")
    print(f"  状态码: {r.status_code} | 长度: {len(r.text)}")
    if r.status_code == 200:
        print(f"  ✓ 带 cookie 成功！418 是无 cookie 触发的")
    elif r.status_code == 418:
        print(f"  ✗ 带 cookie 仍 418 — cookie 可能已被标记")
    await s.close()
    return r.status_code


async def test_playwright():
    """测试 5: Playwright 真实浏览器"""
    print("\n[测试 5] Playwright 真实浏览器 (无 cookie)")
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                response = await page.goto("https://www.cnki.net/", wait_until="domcontentloaded", timeout=20000)
                print(f"  状态码: {response.status} | URL: {page.url}")
                content = await page.content()
                print(f"  内容长度: {len(content)} chars")
                if response.status == 200:
                    print(f"  ✓ Playwright 成功！418 是 curl_cffi TLS 指纹问题")
                elif response.status == 418:
                    print(f"  ✗ Playwright 也 418 — 可能是 IP 级封锁")
                else:
                    print(f"  ? 异常状态码: {response.status}")
            finally:
                await browser.close()
    except Exception as e:
        print(f"  Playwright 测试失败: {e}")


async def test_playwright_with_proxy():
    """测试 6: Playwright + 代理"""
    print("\n[测试 6] Playwright + 香港代理 (7890)")
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                proxy={"server": "http://127.0.0.1:7890"},
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = await browser.new_page()
            try:
                response = await page.goto("https://www.cnki.net/", wait_until="domcontentloaded", timeout=20000)
                print(f"  状态码: {response.status} | URL: {page.url}")
                content = await page.content()
                print(f"  内容长度: {len(content)} chars")
                if response.status == 200:
                    print(f"  ✓ Playwright + 代理成功！")
                elif response.status == 418:
                    print(f"  ✗ Playwright + 代理也 418")
                else:
                    print(f"  ? 异常状态码: {response.status}")
            finally:
                await browser.close()
    except Exception as e:
        print(f"  Playwright + 代理测试失败: {e}")


async def main():
    print("=" * 70)
    print("CNKI 418 拦截根因深度诊断")
    print("=" * 70)

    await test_no_cookie_direct()
    await test_different_fingerprints()
    await test_different_endpoints()
    await test_with_cookies()
    await test_playwright()
    await test_playwright_with_proxy()

    print("\n" + "=" * 70)
    print("诊断完成。请根据以上结果判断 418 根因。")


if __name__ == "__main__":
    asyncio.run(main())
