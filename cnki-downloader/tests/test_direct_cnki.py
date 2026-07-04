"""阶段 3 & 4 辅助：直接连接 CNKI 测试当前 IP 是否被封锁。"""
from curl_cffi.requests import Session

print("=== 直接连接 CNKI 测试 ===")
try:
    with Session(impersonate="chrome124", timeout=15, verify=False) as s:
        resp = s.get("https://www.cnki.net/")
        print(f"Status: {resp.status_code}")
        server = resp.headers.get("server", "") or resp.headers.get("Server", "")
        print(f"Server: {server}")
        print(f"Body length: {len(resp.content)}")
        preview = resp.text[:200] if resp.text else "(empty)"
        print(f"Body preview: {preview!r}")

        if resp.status_code == 418:
            print("\n[结论] 当前 IP 被 CNKI 封锁 (HTTP 418)")
        elif resp.status_code == 200:
            print("\n[结论] 当前 IP 可访问 CNKI (HTTP 200)")
        else:
            print(f"\n[结论] CNKI 返回非预期状态码: {resp.status_code}")
except Exception as e:
    print(f"EXCEPTION: {type(e).__name__}: {e}")
    print("\n[结论] 无法连接到 CNKI（网络异常）")
