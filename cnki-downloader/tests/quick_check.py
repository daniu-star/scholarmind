"""快速检测 CNKI 是否已冷却（不再返回 418）。"""
import asyncio
from curl_cffi.requests import AsyncSession


async def test():
    s = AsyncSession(impersonate="chrome124", timeout=10, verify=False)
    try:
        r = await s.get("https://www.cnki.net/")
        print(f"Status: {r.status_code}")
        if r.status_code == 418:
            print("CNKI 仍在 418 拦截中，需要等待更长时间。")
        elif r.status_code == 200:
            print("CNKI 已冷却，可以运行测试！")
        else:
            print(f"CNKI 返回异常状态码: {r.status_code}")
    except Exception as e:
        print(f"请求失败: {e}")
    finally:
        await s.close()


if __name__ == "__main__":
    asyncio.run(test())
