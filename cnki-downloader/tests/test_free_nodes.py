# -*- coding: utf-8 -*-
"""Switch Clash to free Japan nodes and test proxy connectivity."""
import requests
import time
from curl_cffi import requests as cffi_requests
from urllib.parse import quote

CLASH_NODES = [
    {"name": "Node_01", "api": "9090", "http": "7890"},
    {"name": "Node_02", "api": "9091", "http": "7892"},
    {"name": "Node_03", "api": "9092", "http": "7894"},
    {"name": "Node_04", "api": "9093", "http": "7896"},
]

FREE_NODES = [
    "🇯🇵 免费-日本1-Ver.7",
    "🇯🇵 免费-日本2-Ver.8",
    "🇯🇵 免费-日本3-Ver.7",
    "🇯🇵 免费-日本4-Ver.8",
    "🇯🇵 免费-日本5-Ver.9",
    "🇯🇵 免费-日本6-Ver.8",
    "🇯🇵 免费-日本7-Ver.2",
]


def switch_and_test(api_port, http_port, node_name, test_url="https://httpbin.org/ip"):
    """Switch Clash to a node and test proxy."""
    group = "🔰 选择节点"
    encoded_group = quote(group)
    encoded_node = quote(node_name)

    # Switch node
    try:
        r = requests.put(
            f"http://127.0.0.1:{api_port}/proxies/{encoded_group}",
            json={"name": node_name},
            timeout=5
        )
        if r.status_code not in (200, 204):
            return False, f"Switch failed: {r.status_code} {r.text[:100]}"
    except Exception as e:
        return False, f"Switch error: {e}"

    time.sleep(1)

    # Test delay
    try:
        r = requests.get(
            f"http://127.0.0.1:{api_port}/proxies/{encoded_node}/delay?timeout=8000&url=http://www.baidu.com",
            timeout=12
        )
        if r.status_code == 200:
            delay = r.json().get("delay", "N/A")
            delay_ok = True
            delay_msg = f"delay={delay}ms"
        else:
            delay_ok = False
            delay_msg = f"delay_test: {r.text[:80]}"
    except Exception as e:
        delay_ok = False
        delay_msg = f"delay_error: {e}"

    # Test actual proxy connection
    proxies = {"http": f"http://127.0.0.1:{http_port}", "https": f"http://127.0.0.1:{http_port}"}
    try:
        r = cffi_requests.get(test_url, proxies=proxies, impersonate="chrome124", timeout=20, verify=False)
        proxy_ok = r.status_code == 200
        proxy_msg = f"status={r.status_code}, len={len(r.content)}"
        if proxy_ok and len(r.content) > 0:
            try:
                ip_info = r.json()
                proxy_msg += f", ip={ip_info.get('origin', 'N/A')}"
            except:
                pass
    except Exception as e:
        proxy_ok = False
        proxy_msg = f"error: {type(e).__name__}: {str(e)[:100]}"

    return delay_ok and proxy_ok, f"{delay_msg} | proxy: {proxy_msg}"


def main():
    print("=" * 70)
    print("Free Japan Nodes Proxy Test")
    print("=" * 70)

    # Test each free node on Node_01
    api_port = "9090"
    http_port = "7890"

    for node_name in FREE_NODES:
        print(f"\n[{node_name}]")
        ok, msg = switch_and_test(api_port, http_port, node_name)
        status = "OK" if ok else "FAIL"
        print(f"  -> [{status}] {msg}")
        if ok:
            # If this node works, test CNKI through it
            print(f"  Testing CNKI through this node...")
            proxies = {"http": f"http://127.0.0.1:{http_port}", "https": f"http://127.0.0.1:{http_port}"}
            try:
                r = cffi_requests.get("https://www.cnki.net/", proxies=proxies, impersonate="chrome124", timeout=20, verify=False)
                print(f"  CNKI -> status={r.status_code}, len={len(r.content)}, server={r.headers.get('server', 'N/A')}")
                if r.status_code == 200:
                    print(f"  [BREAKTHROUGH] CNKI accessible through {node_name}!")
            except Exception as e:
                print(f"  CNKI -> error: {type(e).__name__}: {str(e)[:120]}")
            break
        time.sleep(1)

    # Also test a few paid nodes to confirm they're expired
    print(f"\n[Testing paid nodes for comparison]")
    paid_tests = ["🇭🇰 香港W01", "🇯🇵 日本W01 | IEPL", "🇺🇲 美国W01 | IEPL | x1.5"]
    for node_name in paid_tests:
        print(f"\n[{node_name}]")
        ok, msg = switch_and_test(api_port, http_port, node_name)
        status = "OK" if ok else "FAIL"
        print(f"  -> [{status}] {msg}")
        time.sleep(1)

    print("\n" + "=" * 70)
    print("Test complete.")
    print("=" * 70)


if __name__ == "__main__":
    main()
