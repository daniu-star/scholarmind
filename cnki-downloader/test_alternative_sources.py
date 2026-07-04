"""Test alternative academic data sources (CrossRef, Semantic Scholar, arXiv)."""
import asyncio
import json
import xml.etree.ElementTree as ET
from curl_cffi.requests import AsyncSession


async def main():
    s = AsyncSession(impersonate="chrome124", timeout=15, verify=False)

    # Test 1: CrossRef
    print("[1] CrossRef API...")
    try:
        r = await s.get(
            "https://api.crossref.org/works?query=artificial+intelligence&rows=3"
        )
        print(f"    HTTP {r.status_code}, size={len(r.content)} bytes")
        if r.status_code == 200:
            data = json.loads(r.text)
            items = data.get("message", {}).get("items", [])
            for item in items:
                titles = item.get("title", ["No title"])
                print(f"    - {titles[0][:80]}")
    except Exception as e:
        print(f"    Error: {e}")

    # Test 2: Semantic Scholar
    print("[2] Semantic Scholar...")
    try:
        r = await s.get(
            "https://api.semanticscholar.org/graph/v1/paper/search?query=media+study&limit=3"
        )
        print(f"    HTTP {r.status_code}")
        if r.status_code == 200:
            data = json.loads(r.text)
            for p in data.get("data", []):
                print(f'    - {p.get("title", "")[:80]}')
    except Exception as e:
        print(f"    Error: {e}")

    # Test 3: arXiv
    print("[3] arXiv API...")
    try:
        r = await s.get(
            "https://export.arxiv.org/api/query?search_query=all:communication&max_results=3"
        )
        print(f"    HTTP {r.status_code}")
        if r.status_code == 200:
            root = ET.fromstring(r.text)
            ns = {"a": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("a:entry", ns):
                title = entry.find("a:title", ns)
                if title is not None:
                    print(f'    - {title.text[:80].strip()}')
    except Exception as e:
        print(f"    Error: {e}")

    # Test 4: Try CNKI via httpx (no impersonation)
    print("[4] CNKI via httpx (plain)...")
    try:
        import httpx
        async with httpx.AsyncClient(verify=False) as hc:
            r = await hc.get(
                "https://www.cnki.net/",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
                timeout=15,
            )
            print(f"    HTTP {r.status_code}")
    except Exception as e:
        print(f"    Error: {e}")

    # Test 5: Try cnki.net via IPv4 vs IPv6
    print("[5] CNKI via requests (with SSL verify=False)...")
    try:
        import urllib3
        urllib3.disable_warnings()
        import requests
        r = requests.get(
            "https://www.cnki.net/",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
            verify=False,
            timeout=15,
        )
        print(f"    HTTP {r.status_code}")
    except Exception as e:
        print(f"    Error: {e}")

    await s.close()


if __name__ == "__main__":
    asyncio.run(main())
