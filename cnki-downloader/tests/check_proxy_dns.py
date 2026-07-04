# -*- coding: utf-8 -*-
"""Check which proxy servers resolve to real IPs and test connectivity."""
import socket
import yaml
import json

CONFIG_PATH = r"D:\Clash.for.Windows-0.20.16-ikuuu\instances\Node_01\config.yaml"


def check_dns_and_connectivity(server_domain, port, timeout=5):
    """Check DNS resolution and TCP connectivity."""
    try:
        # DNS resolution
        ip = socket.gethostbyname(server_domain)
        if ip == "127.127.127.1":
            return {"domain": server_domain, "ip": ip, "status": "BLACKHOLE", "connectable": False}
        # TCP connectivity test
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((ip, port))
            sock.close()
            return {"domain": server_domain, "ip": ip, "port": port, "status": "OK", "connectable": True}
        except socket.timeout:
            return {"domain": server_domain, "ip": ip, "port": port, "status": "TIMEOUT", "connectable": False}
        except ConnectionRefusedError:
            return {"domain": server_domain, "ip": ip, "port": port, "status": "REFUSED", "connectable": False}
        except Exception as e:
            return {"domain": server_domain, "ip": ip, "port": port, "status": f"ERROR: {type(e).__name__}", "connectable": False}
    except socket.gaierror as e:
        return {"domain": server_domain, "ip": "N/A", "status": f"DNS_FAIL: {e}", "connectable": False}


def main():
    print("=" * 70)
    print("Proxy Server DNS & Connectivity Check")
    print("=" * 70)

    # Load Clash config
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    proxies = config.get("proxies", [])
    print(f"\nTotal proxy nodes in config: {len(proxies)}")

    real_ip_nodes = []
    blackhole_nodes = []
    dns_fail_nodes = []

    for proxy in proxies:
        name = proxy.get("name", "?")
        server = proxy.get("server", "")
        port = proxy.get("port", 0)
        ptype = proxy.get("type", "?")

        if not server or ptype not in ("ss", "vmess", "trojan", "vless", "ssr"):
            continue

        result = check_dns_and_connectivity(server, port, timeout=5)
        result["name"] = name
        result["type"] = ptype

        if result["status"] == "OK":
            real_ip_nodes.append(result)
            print(f"  [OK]      {name} -> {server}:{port} -> {result['ip']} (connectable)")
        elif result["status"] == "BLACKHOLE":
            blackhole_nodes.append(result)
            print(f"  [BLACK]   {name} -> {server}:{port} -> 127.127.127.1")
        elif result["status"] == "TIMEOUT":
            real_ip_nodes.append(result)
            print(f"  [TIMEOUT] {name} -> {server}:{port} -> {result['ip']} (DNS OK, TCP timeout)")
        elif result["status"] == "REFUSED":
            real_ip_nodes.append(result)
            print(f"  [REFUSED] {name} -> {server}:{port} -> {result['ip']} (DNS OK, TCP refused)")
        else:
            dns_fail_nodes.append(result)
            print(f"  [FAIL]    {name} -> {server}:{port} -> {result['status']}")

    print(f"\n{'=' * 70}")
    print(f"Summary:")
    print(f"  Connectable (TCP OK): {len([n for n in real_ip_nodes if n['status'] == 'OK'])}")
    print(f"  Real IP but TCP fail: {len([n for n in real_ip_nodes if n['status'] != 'OK'])}")
    print(f"  Blackhole (127.127.127.1): {len(blackhole_nodes)}")
    print(f"  DNS fail: {len(dns_fail_nodes)}")

    # List connectable nodes
    connectable = [n for n in real_ip_nodes if n["status"] == "OK"]
    if connectable:
        print(f"\nConnectable proxy nodes:")
        for n in connectable:
            print(f"  - {n['name']} ({n['type']}) -> {n['ip']}:{n['port']}")

    # Save results
    results = {
        "connectable": connectable,
        "real_ip_but_tcp_fail": [n for n in real_ip_nodes if n["status"] != "OK"],
        "blackhole": blackhole_nodes,
        "dns_fail": dns_fail_nodes,
    }
    with open("proxy_check_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to proxy_check_results.json")


if __name__ == "__main__":
    main()
