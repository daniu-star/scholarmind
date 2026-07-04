# -*- coding: utf-8 -*-
"""Check all available Clash proxy nodes and try switching."""
import requests
import json
import time

CLASH_APIS = [
    {"name": "Node_01", "port": "9090"},
    {"name": "Node_02", "port": "9091"},
    {"name": "Node_03", "port": "9092"},
    {"name": "Node_04", "port": "9093"},
]


def get_all_proxies(api_port):
    """Get all available proxies from Clash API."""
    try:
        r = requests.get(f"http://127.0.0.1:{api_port}/proxies", timeout=5)
        if r.status_code == 200:
            data = r.json()
            proxies = data.get("proxies", {})
            # Filter out groups and direct/reject
            actual_nodes = {}
            groups = {}
            for name, info in proxies.items():
                ptype = info.get("type", "")
                if ptype in ("Selector", "URLTest", "Fallback", "LoadBalance", "Relay"):
                    groups[name] = info
                elif ptype not in ("Direct", "Reject") and name not in ("DIRECT", "REJECT", "GLOBAL"):
                    actual_nodes[name] = info
            return actual_nodes, groups
        return None, None
    except Exception as e:
        print(f"  Error getting proxies from {api_port}: {e}")
        return None, None


def test_node_delay(api_port, node_name, url="http://www.baidu.com", timeout=5000):
    """Test a specific proxy node's delay."""
    try:
        from urllib.parse import quote
        encoded = quote(node_name)
        r = requests.get(
            f"http://127.0.0.1:{api_port}/proxies/{encoded}/delay?timeout={timeout}&url={url}",
            timeout=10
        )
        if r.status_code == 200:
            return True, r.json().get("delay", "N/A")
        else:
            return False, r.text[:100]
    except Exception as e:
        return False, str(e)[:100]


def switch_proxy(api_port, group_name, node_name):
    """Switch the selected proxy node in a group."""
    try:
        from urllib.parse import quote
        encoded_group = quote(group_name)
        r = requests.put(
            f"http://127.0.0.1:{api_port}/proxies/{encoded_group}",
            json={"name": node_name},
            timeout=5
        )
        return r.status_code == 204 or r.status_code == 200
    except Exception as e:
        print(f"  Switch error: {e}")
        return False


def main():
    print("=" * 70)
    print("Clash Available Proxy Nodes Check")
    print("=" * 70)

    for api in CLASH_APIS:
        print(f"\n[{api['name']}] API port {api['port']}:")
        nodes, groups = get_all_proxies(api["port"])
        if nodes is None:
            print("  Failed to get proxies")
            continue

        print(f"  Available proxy nodes: {len(nodes)}")
        print(f"  Proxy groups: {len(groups)}")

        # Show first 10 actual proxy nodes
        node_names = list(nodes.keys())[:15]
        print(f"  Sample nodes (first 15):")
        for name in node_names:
            info = nodes[name]
            ptype = info.get("type", "?")
            history = info.get("history", [])
            if history:
                last_delay = history[-1].get("delay", "N/A")
                print(f"    - {name} ({ptype}) last_delay={last_delay}ms")
            else:
                print(f"    - {name} ({ptype}) no_history")

        # Show groups and their current selection
        print(f"  Groups:")
        for gname, ginfo in groups.items():
            now = ginfo.get("now", "N/A")
            all_opts = ginfo.get("all", [])
            print(f"    - {gname}: now={now}, options={len(all_opts)}")

        # Try testing a few different nodes
        print(f"\n  Testing delays for first 5 nodes:")
        test_nodes = list(nodes.keys())[:5]
        for node_name in test_nodes:
            ok, result = test_node_delay(api["port"], node_name)
            status = "OK" if ok else "FAIL"
            print(f"    {node_name}: [{status}] {result}")
            time.sleep(0.5)

    print("\n" + "=" * 70)
    print("Check complete.")
    print("=" * 70)


if __name__ == "__main__":
    main()
