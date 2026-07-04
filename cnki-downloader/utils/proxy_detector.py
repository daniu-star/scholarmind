"""Proxy detection and availability checker.

Auto-detects available proxies (Clash, VPN, system proxy) for CNKI access.
"""

import asyncio
import socket
from typing import Optional


def check_clash_proxy(host: str = "127.0.0.1", port: int = 7890) -> bool:
    """Check if Clash for Windows proxy is available."""
    try:
        sock = socket.create_connection((host, port), timeout=2)
        sock.close()
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def check_port(host: str, port: int, timeout: float = 1.5) -> bool:
    """Check if a TCP port is open on a host."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


COMMON_PROXIES = {
    "Clash (default)": {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
    "Clash (alt)": {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"},
    "Clash Verge": {"http": "http://127.0.0.1:7899", "https": "http://127.0.0.1:7899"},
    "V2Ray": {"http": "http://127.0.0.1:10809", "https": "http://127.0.0.1:10809"},
    "SS/SSR": {"http": "http://127.0.0.1:1080", "https": "http://127.0.0.1:1080"},
    "System Proxy": {"http": "http://127.0.0.1:8888", "https": "http://127.0.0.1:8888"},
    "VPN (TUN)": {},  # Virtual network adapter, no proxy URL needed
}


async def detect_available_proxies() -> list[dict]:
    """Scan for available proxy services on common ports.

    Returns list of proxy configs sorted by likelihood of working.
    """
    available = []

    for name, config in COMMON_PROXIES.items():
        if not config:
            continue
        http_url = config.get("http", "")
        if not http_url:
            continue
        # Extract host:port
        try:
            parts = http_url.replace("http://", "").split(":")
            host = parts[0]
            port = int(parts[1])
            if check_port(host, port):
                available.append({
                    "name": name,
                    "config": config,
                    "http": http_url,
                })
        except (IndexError, ValueError):
            continue

    return available


async def get_best_proxy() -> Optional[dict]:
    """Get the best available proxy configuration.

    Returns None if no proxy is available.
    """
    proxies = await detect_available_proxies()
    if proxies:
        return proxies[0]
    return None


def format_proxy_status(available: list[dict]) -> str:
    """Format proxy detection results for display."""
    if not available:
        return "  [!] No proxy detected (Clash/V2Ray/SS not running)"

    lines = ["  [i] Available proxies:"]
    for p in available:
        lines.append(f"      - {p['name']}: {p['http']}")
    return "\n".join(lines)
