"""测试 Clash 代理是否正常工作（非 CNKI 网站）。"""
import asyncio
from curl_cffi.requests import AsyncSession


PROXIES = [
    ("7890", "香港", "http://127.0.0.1:7890"),
    ("7892", "日本", "http://127.0.0.1:7892"),
    ("7894", "新加坡", "http://127.0.0.1:7894"),
    ("7896", "美国", "http://127.0.0.1:7896"),
]


async def test_proxy_general(port, region, proxy_url):
    """测试代理访问非 CNKI 网站。"""
    print(f"\n[{port}/{region}] 测试 httpbin.org...")
    try:
        s = AsyncSession(impersonate="chrome124", timeout=15, verify=False, proxy=proxy_url)
        r = await s.get("https://httpbin.org/ip")
        print(f"  状态码: {r.status_code} | 响应: {r.text[:200]}")
        await s.close()
        return r.status_code
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return -1


async def test_proxy_cnki_http(port, region, proxy_url):
    """测试代理访问 CNKI HTTP（非 HTTPS）。"""
    print(f"[{port}/{region}] 测试 CNKI HTTP...")
    try:
        s = AsyncSession(impersonate="chrome124", timeout=15, verify=False, proxy=proxy_url)
        r = await s.get("http://www.cnki.net/")
        print(f"  状态码: {r.status_code} | 长度: {len(r.text)}")
        await s.close()
        return r.status_code
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return -1


async def test_clash_api(port, api_port):
    """测试 Clash API 是否可访问。"""
    print(f"[API {api_port}] 测试 Clash API...")
    try:
        s = AsyncSession(timeout=5, verify=False)
        r = await s.get(f"http://127.0.0.1:{api_port}/proxies")
        if r.status_code == 200:
            import json
            data = json.loads(r.text)
            proxies = data.get("proxies", {})
            # 找到 🔰 选择节点 的当前选择
            select_node = proxies.get("🔰 选择节点", {})
            now = select_node.get("now", "unknown")
            print(f"  ✓ Clash API 可访问 | 当前节点: {now}")
        else:
            print(f"  状态码: {r.status_code}")
        await s.close()
    except Exception as e:
        print(f"  ✗ Clash API 失败: {e}")


async def main():
    print("=" * 60)
    print("Clash 代理通用连通性测试")
    print("=" * 60)

    # 测试 1: 代理访问非 CNKI 网站
    for port, region, url in PROXIES:
        await test_proxy_general(port, region, url)

    # 测试 2: Clash API
    api_ports = [("7890", "9090"), ("7892", "9091"), ("7894", "9092"), ("7896", "9093")]
    for proxy_port, api_port in api_ports:
        await test_clash_api(proxy_port, api_port)

    # 测试 3: 代理访问 CNKI HTTP
    print("\n" + "=" * 60)
    print("代理访问 CNKI HTTP（非 HTTPS）")
    print("=" * 60)
    for port, region, url in PROXIES:
        await test_proxy_cnki_http(port, region, url)


if __name__ == "__main__":
    asyncio.run(main())
