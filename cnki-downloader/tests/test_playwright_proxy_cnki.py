# -*- coding: utf-8 -*-
"""Test Playwright + working proxy against CNKI, and check all free node IPs."""
import asyncio
import requests
import time
from curl_cffi import requests as cffi_requests
from urllib.parse import quote


async def test_playwright_with_proxy(http_port, node_name):
    """Test Playwright + proxy against CNKI."""
    from playwright.async_api import async_playwright

    print(f"\n[Playwright + {node_name}] -> CNKI")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", f"--proxy-server=http://127.0.0.1:{http_port}", "--ignore-certificate-errors"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
            ignore_https_errors=True,
        )
        page = await context.new_page()
        try:
            response = await page.goto("https://www.cnki.net/", timeout=30000, wait_until="domcontentloaded")
            status = response.status if response else "N/A"
            print(f"  Status: {status}")
            if status == 200:
                title = await page.title()
                print(f"  Title: {title}")
                print(f"  [SUCCESS] Playwright + proxy bypassed 418!")
                return True
            elif status == 418:
                print(f"  [BLOCKED] 418 even through Playwright + proxy")
                return False
            else:
                print(f"  [UNKNOWN] Status {status}")
                return False
        except Exception as e:
            print(f"  [ERROR] {type(e).__name__}: {str(e)[:200]}")
            return False
        finally:
            await browser.close()


def check_all_free_node_ips():
    """Check what IPs the free nodes resolve to."""
    import socket
    import yaml

    config_path = r"D:\Clash.for.Windows-0.20.16-ikuuu\instances\Node_01\config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    print("\n[Free node IP check]")
    free_nodes = []
    for proxy in config.get("proxies", []):
        name = proxy.get("name", "")
        if "免费" in name:
            server = proxy.get("server", "")
            port = proxy.get("port", 0)
            try:
                ip = socket.gethostbyname(server)
            except:
                ip = "DNS_FAIL"
            free_nodes.append({"name": name, "server": server, "port": port, "ip": ip, "type": proxy.get("type", "?")})
            print(f"  {name}: {server}:{port} -> {ip} ({proxy.get('type', '?')})")

    return free_nodes


def test_all_free_nodes_cnki():
    """Test all free nodes against CNKI."""
    api_port = "9090"
    http_port = "7890"
    group = "🔰 选择节点"
    encoded_group = quote(group)

    free_node_names = [
        "🇯🇵 免费-日本1-Ver.7",
        "🇯🇵 免费-日本2-Ver.8",
        "🇯🇵 免费-日本3-Ver.7",
        "🇯🇵 免费-日本4-Ver.8",
        "🇯🇵 免费-日本5-Ver.9",
        "🇯🇵 免费-日本6-Ver.8",
        "🇯🇵 免费-日本7-Ver.2",
    ]

    print("\n[Testing all free nodes against CNKI]")
    working_proxies = []

    for node_name in free_node_names:
        encoded_node = quote(node_name)
        # Switch node
        try:
            requests.put(
                f"http://127.0.0.1:{api_port}/proxies/{encoded_group}",
                json={"name": node_name},
                timeout=5
            )
        except:
            pass
        time.sleep(1)

        # Test proxy works (httpbin)
        proxies = {"http": f"http://127.0.0.1:{http_port}", "https": f"http://127.0.0.1:{http_port}"}
        try:
            r = cffi_requests.get("https://httpbin.org/ip", proxies=proxies, impersonate="chrome124", timeout=15, verify=False)
            if r.status_code != 200:
                print(f"  {node_name}: proxy FAIL (httpbin status={r.status_code})")
                continue
            proxy_ip = r.json().get("origin", "?")
        except Exception as e:
            print(f"  {node_name}: proxy FAIL ({type(e).__name__})")
            continue

        # Test CNKI
        try:
            r = cffi_requests.get("https://www.cnki.net/", proxies=proxies, impersonate="chrome124", timeout=15, verify=False)
            cnki_status = r.status_code
            cnki_server = r.headers.get("server", "N/A")
            print(f"  {node_name}: proxy_ip={proxy_ip}, CNKI status={cnki_status}, server={cnki_server}")
            if cnki_status == 200:
                print(f"    [BREAKTHROUGH] CNKI accessible through {node_name}!")
                working_proxies.append({"node": node_name, "ip": proxy_ip})
        except Exception as e:
            print(f"  {node_name}: proxy_ip={proxy_ip}, CNKI ERROR: {type(e).__name__}: {str(e)[:80]}")

    return working_proxies


async def main():
    print("=" * 70)
    print("Playwright + Proxy Test & Free Node IP Check")
    print("=" * 70)

    # Check free node IPs
    free_nodes = check_all_free_node_ips()

    # Test all free nodes against CNKI
    working = test_all_free_nodes_cnki()

    # If any working proxy found, test with Playwright
    if working:
        best = working[0]
        # Switch to the working node
        api_port = "9090"
        group = "🔰 选择节点"
        encoded_group = quote(group)
        encoded_node = quote(best["node"])
        try:
            requests.put(
                f"http://127.0.0.1:{api_port}/proxies/{encoded_group}",
                json={"name": best["node"]},
                timeout=5
            )
            time.sleep(1)
        except:
            pass

        await test_playwright_with_proxy("7890", best["node"])
    else:
        # Test Playwright with the known working node (free Japan 3)
        node_name = "🇯🇵 免费-日本3-Ver.7"
        encoded_node = quote(node_name)
        group = "🔰 选择节点"
        encoded_group = quote(group)
        try:
            requests.put(
                f"http://127.0.0.1:9090/proxies/{encoded_group}",
                json={"name": node_name},
                timeout=5
            )
            time.sleep(1)
        except:
            pass

        await test_playwright_with_proxy("7890", node_name)

    print("\n" + "=" * 70)
    print("Test complete.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
