# -*- coding: utf-8 -*-
"""Comprehensive proxy status check after 3-hour cooldown."""
import json
import time
import requests
from curl_cffi import requests as cffi_requests

CLASH_NODES = [
    {"name": "Node_01", "api": "9090", "http": "7890", "socks": "7891", "region": "hk"},
    {"name": "Node_02", "api": "9091", "http": "7892", "socks": "7893", "region": "jp"},
    {"name": "Node_03", "api": "9092", "http": "7894", "socks": "7895", "region": "sg"},
    {"name": "Node_04", "api": "9093", "http": "7896", "socks": "7897", "region": "us"},
]

CNKI_URL = "https://www.cnki.net/"
HTTPBIN_URL = "https://httpbin.org/ip"
BAIDU_URL = "https://www.baidu.com"


def test_clash_api_delay(node):
    """Test node delay via Clash API."""
    api_port = node["api"]
    try:
        # Get current selected proxy
        r = requests.get(f"http://127.0.0.1:{api_port}/proxies/%F0%9F%94%B0%20%E9%80%89%E6%8B%A9%E8%8A%82%E7%82%B9", timeout=5)
        if r.status_code == 200:
            data = r.json()
            now = data.get("now", "N/A")
        else:
            now = f"API error {r.status_code}"
        # Delay test with baidu
        r2 = requests.get(f"http://127.0.0.1:{api_port}/proxies/%F0%9F%94%B0%20%E9%80%89%E6%8B%A9%E8%8A%82%E7%82%B9/delay?timeout=5000&url=http://www.baidu.com", timeout=10)
        if r2.status_code == 200:
            delay = r2.json().get("delay", "N/A")
            return True, f"now={now}, delay={delay}ms"
        else:
            return False, f"now={now}, delay_test_failed: {r2.text[:100]}"
    except Exception as e:
        return False, f"API error: {e}"


def test_proxy_http(url, proxy_port, use_cffi=True, timeout=15):
    """Test proxy connection to a URL."""
    proxies = {"http": f"http://127.0.0.1:{proxy_port}", "https": f"http://127.0.0.1:{proxy_port}"}
    try:
        if use_cffi:
            r = cffi_requests.get(url, proxies=proxies, impersonate="chrome124", timeout=timeout, verify=False)
        else:
            r = requests.get(url, proxies=proxies, timeout=timeout, verify=False)
        return True, f"status={r.status_code}, len={len(r.content)}"
    except Exception as e:
        return False, f"error: {type(e).__name__}: {str(e)[:120]}"


def main():
    print("=" * 70)
    print("Comprehensive Proxy Status Check (after 3-hour cooldown)")
    print("=" * 70)

    # Phase 1: Clash API delay test
    print("\n[Phase 1] Clash API Delay Test (via baidu.com):")
    for node in CLASH_NODES:
        ok, msg = test_clash_api_delay(node)
        status = "OK" if ok else "FAIL"
        print(f"  {node['name']} ({node['region']}): [{status}] {msg}")
        time.sleep(1)

    # Phase 2: Proxy HTTP test to httpbin
    print("\n[Phase 2] Proxy HTTP test to httpbin.org/ip (curl_cffi):")
    for node in CLASH_NODES:
        ok, msg = test_proxy_http(HTTPBIN_URL, node["http"], use_cffi=True, timeout=15)
        status = "OK" if ok else "FAIL"
        print(f"  {node['name']} :{node['http']} -> [{status}] {msg}")
        time.sleep(1)

    # Phase 3: Proxy HTTP test to CNKI
    print("\n[Phase 3] Proxy HTTP test to CNKI (curl_cffi chrome124):")
    for node in CLASH_NODES:
        ok, msg = test_proxy_http(CNKI_URL, node["http"], use_cffi=True, timeout=20)
        status = "OK" if ok else "FAIL"
        print(f"  {node['name']} :{node['http']} -> [{status}] {msg}")
        time.sleep(2)

    # Phase 4: Direct (no proxy) test to CNKI for comparison
    print("\n[Phase 4] Direct (no proxy) test to CNKI (curl_cffi chrome124):")
    try:
        r = cffi_requests.get(CNKI_URL, impersonate="chrome124", timeout=20, verify=False)
        print(f"  Direct -> [OK] status={r.status_code}, len={len(r.content)}")
    except Exception as e:
        print(f"  Direct -> [FAIL] error: {type(e).__name__}: {str(e)[:120]}")

    # Phase 5: requests library test (no impersonation)
    print("\n[Phase 5] requests library test to CNKI via proxy 7890:")
    proxies = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
    try:
        r = requests.get(CNKI_URL, proxies=proxies, timeout=20, verify=False)
        print(f"  requests -> [OK] status={r.status_code}, len={len(r.content)}")
    except Exception as e:
        print(f"  requests -> [FAIL] error: {type(e).__name__}: {str(e)[:120]}")

    print("\n" + "=" * 70)
    print("Diagnosis complete.")
    print("=" * 70)


if __name__ == "__main__":
    main()
