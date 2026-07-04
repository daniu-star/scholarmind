"""快速测试每个 Clash 代理的 CNKI 连通性。"""
import asyncio
import time
from curl_cffi.requests import AsyncSession


PROXIES = [
    ("7890", "香港", "http://127.0.0.1:7890"),
    ("7892", "日本", "http://127.0.0.1:7892"),
    ("7894", "新加坡", "http://127.0.0.1:7894"),
    ("7896", "美国", "http://127.0.0.1:7896"),
]


async def test_proxy(port: str, region: str, proxy_url: str):
    """测试单个代理访问 CNKI。"""
    print(f"\n[{port}/{region}] 测试中...")
    try:
        s = AsyncSession(impersonate="chrome124", timeout=15, verify=False, proxy=proxy_url)
        start = time.time()
        r = await s.get("https://www.cnki.net/")
        elapsed = time.time() - start
        print(f"  状态码: {r.status_code} | 耗时: {elapsed:.2f}s | 内容长度: {len(r.text)} chars")
        if r.status_code == 200:
            print(f"  ✓ 成功！CNKI 可访问")
        elif r.status_code == 418:
            print(f"  ✗ HTTP 418 — 该代理 IP 也被拦截")
        else:
            print(f"  ? 异常状态码: {r.status_code}")
        await s.close()
        return r.status_code
    except Exception as e:
        print(f"  ✗ 连接失败: {e}")
        return -1


async def main():
    print("=" * 60)
    print("Clash 代理 CNKI 连通性测试")
    print("=" * 60)

    results = []
    for port, region, url in PROXIES:
        code = await test_proxy(port, region, url)
        results.append((port, region, code))

    print("\n" + "=" * 60)
    print("汇总:")
    for port, region, code in results:
        status = "✓ 可用" if code == 200 else ("✗ 418" if code == 418 else "✗ 失败")
        print(f"  {port}/{region}: {status}")

    # 同时测试无代理（直连）
    print(f"\n[直连] 测试中...")
    try:
        s = AsyncSession(impersonate="chrome124", timeout=15, verify=False)
        start = time.time()
        r = await s.get("https://www.cnki.net/")
        elapsed = time.time() - start
        print(f"  状态码: {r.status_code} | 耗时: {elapsed:.2f}s")
        if r.status_code == 200:
            print(f"  ✓ 直连也可用！CNKI 已冷却")
        elif r.status_code == 418:
            print(f"  ✗ 直连仍被 418 拦截")
        await s.close()
    except Exception as e:
        print(f"  ✗ 直连失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())
