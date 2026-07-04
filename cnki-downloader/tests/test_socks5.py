"""测试 SOCKS5 代理和 requests 库代理。"""
import asyncio
import requests
from curl_cffi.requests import AsyncSession


SOCKS5_PROXIES = [
    ("7891", "香港", "socks5://127.0.0.1:7891"),
    ("7893", "日本", "socks5://127.0.0.1:7893"),
    ("7895", "新加坡", "socks5://127.0.0.1:7895"),
    ("7897", "美国", "socks5://127.0.0.1:7897"),
]


async def test_curl_cffi_socks5(port, region, proxy_url):
    """测试 curl_cffi + SOCKS5"""
    print(f"\n[{port}/{region}] curl_cffi SOCKS5 → httpbin.org...")
    try:
        s = AsyncSession(impersonate="chrome124", timeout=15, verify=False, proxy=proxy_url)
        r = await s.get("https://httpbin.org/ip")
        print(f"  状态码: {r.status_code} | 响应: {r.text[:200]}")
        await s.close()
        return r.status_code
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return -1


async def test_curl_cffi_socks5_cnki(port, region, proxy_url):
    """测试 curl_cffi + SOCKS5 → CNKI"""
    print(f"[{port}/{region}] curl_cffi SOCKS5 → CNKI...")
    try:
        s = AsyncSession(impersonate="chrome124", timeout=15, verify=False, proxy=proxy_url)
        r = await s.get("https://www.cnki.net/")
        print(f"  状态码: {r.status_code} | 长度: {len(r.text)}")
        await s.close()
        return r.status_code
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return -1


def test_requests_http_proxy(port, region, proxy_url):
    """测试 requests 库 + HTTP 代理"""
    print(f"[{port}/{region}] requests HTTP → httpbin.org...")
    try:
        proxies = {"http": f"http://127.0.0.1:{port}", "https": f"http://127.0.0.1:{port}"}
        r = requests.get("https://httpbin.org/ip", proxies=proxies, timeout=15, verify=False)
        print(f"  状态码: {r.status_code} | 响应: {r.text[:200]}")
        return r.status_code
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return -1


def test_requests_http_proxy_cnki(port, region):
    """测试 requests 库 + HTTP 代理 → CNKI"""
    print(f"[{port}/{region}] requests HTTP → CNKI...")
    try:
        proxies = {"http": f"http://127.0.0.1:{port}", "https": f"http://127.0.0.1:{port}"}
        r = requests.get("https://www.cnki.net/", proxies=proxies, timeout=15, verify=False)
        print(f"  状态码: {r.status_code} | 长度: {len(r.text)}")
        return r.status_code
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return -1


async def main():
    print("=" * 60)
    print("SOCKS5 代理测试 (curl_cffi)")
    print("=" * 60)

    for port, region, url in SOCKS5_PROXIES:
        await test_curl_cffi_socks5(port, region, url)

    print("\n" + "=" * 60)
    print("SOCKS5 代理 → CNKI (curl_cffi)")
    print("=" * 60)

    for port, region, url in SOCKS5_PROXIES:
        await test_curl_cffi_socks5_cnki(port, region, url)

    print("\n" + "=" * 60)
    print("HTTP 代理测试 (requests 库)")
    print("=" * 60)

    http_ports = [("7890", "香港"), ("7892", "日本"), ("7894", "新加坡"), ("7896", "美国")]
    for port, region in http_ports:
        test_requests_http_proxy(port, region, f"http://127.0.0.1:{port}")

    print("\n" + "=" * 60)
    print("HTTP 代理 → CNKI (requests 库)")
    print("=" * 60)

    for port, region in http_ports:
        test_requests_http_proxy_cnki(port, region)


if __name__ == "__main__":
    asyncio.run(main())
