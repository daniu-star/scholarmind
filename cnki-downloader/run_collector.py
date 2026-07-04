#!/usr/bin/env python3
"""Multi-Source Paper Collector — cookie-free baseline + optional CNKI enrichment.

Usage:
  python run_collector.py                          # Collect from all sources
  python run_collector.py --rss-only               # CNKI RSS only (no cookies needed)
  python run_collector.py --journal GJXW,YANJ      # Specific journals
  python run_collector.py --search "人工智能"       # Add keyword search
"""

import asyncio
import sys
import os
import argparse
import io
from pathlib import Path

# Fix terminal encoding for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))

from crawler.multi_source_collector import MultiSourceCollector


DEFAULT_JOURNALS = [
    "GJXW",  # 国际新闻界
    "YANJ",  # 新闻与传播研究
    "XWDX",  # 新闻大学
    "DACB",  # 当代传播
]

DEFAULT_QUERIES = [
    "media communication",
    "artificial intelligence",
    "large language model news",
]

# Journal name → ISSN mapping for CrossRef searches
JOURNAL_ISSN_MAP = {
    "GJXW": "1002-5685",   # 国际新闻界
    "YANJ": "1005-2577",   # 新闻与传播研究
    "XWDX": "1006-1460",   # 新闻大学
    "DACB": "1009-5322",   # 当代传播
}


async def main():
    parser = argparse.ArgumentParser(description="Multi-Source Academic Paper Collector")
    parser.add_argument("--rss-only", action="store_true", help="CNKI RSS only (no cookies)")
    parser.add_argument("--no-cnki-enrich", action="store_true", help="Skip CNKI detail page enrichment")
    parser.add_argument("--journal", type=str, default="", help="Comma-separated journal codes")
    parser.add_argument("--search", type=str, default="", help="Additional search query")
    parser.add_argument("--no-search", action="store_true", help="Skip CrossRef/Semantic Scholar")
    parser.add_argument("--output", type=str, default="../数据库/cnki/multi_source", help="Output directory")
    args = parser.parse_args()

    # Load cookies if available
    cookies = {}
    cookies_file = Path("cookies.json")
    if cookies_file.exists() and not args.rss_only:
        import json
        try:
            data = json.loads(cookies_file.read_text("utf-8"))
            cookies = data.get("cookies", {})
            from crawler.hybrid_scraper import CNKIHybridScraper
            expiry = CNKIHybridScraper.check_cookie_expiry(cookies)
            if expiry["warning"]:
                print(f"[!] {expiry['warning']}")
            if expiry["is_expired"]:
                print("[!] CNKI detail enrichment disabled (cookies expired)")
                cookies = {}
            else:
                print(f"[i] Cookies valid, CNKI detail enrichment enabled")
        except Exception:
            pass

    if not cookies:
        print("[i] No valid cookies — CNKI detail enrichment disabled")
        print("[i] RSS + CrossRef + Semantic Scholar will still work")

    # Parse journals
    journals = args.journal.split(",") if args.journal else DEFAULT_JOURNALS

    # Parse search queries
    if args.rss_only:
        queries = []
    else:
        queries = DEFAULT_QUERIES.copy()
        if args.search:
            queries.append(args.search)
        if args.no_search:
            queries = []

    # Add ISSN-filtered searches for Chinese journals using CrossRef
    issn_queries = []
    for j in journals:
        if j in JOURNAL_ISSN_MAP:
            issn_queries.append(f"issn:{JOURNAL_ISSN_MAP[j]}")

    print(f"\nConfiguration:")
    print(f"  Journals: {journals}")
    print(f"  Search queries: {queries if queries else '(none)'}")
    print(f"  ISSN queries: {issn_queries if issn_queries and not args.rss_only else '(none)'}")
    print(f"  CNKI enrichment: {bool(cookies) and not args.no_cnki_enrich}")
    print()

    # Collect
    collector = MultiSourceCollector(
        cookies=cookies,
        output_dir=args.output,
    )

    try:
        all_queries = queries + issn_queries if queries else (issn_queries or None)

        papers = await collector.collect(
            journal_codes=journals,
            search_queries=all_queries,
            enrich_with_cnki=bool(cookies) and not args.no_cnki_enrich,
            force_skip_cnki=args.rss_only,
        )

        # Save
        output_path = collector.save_results(papers)

        # Report
        print(f"\n{collector.quality_report(papers)}")
        print(f"\nResults saved: {output_path}")

        # Show sample papers
        if papers:
            print(f"\nTop papers by quality:")
            for i, p in enumerate(papers[:5], 1):
                print(f"\n  [{i}] {p.title[:80]}")
                print(f"      Authors: {', '.join(p.authors[:3])}")
                print(f"      Journal: {p.journal} ({p.year})")
                if p.doi:
                    print(f"      DOI: {p.doi}")
                if p.keywords:
                    print(f"      Keywords: {', '.join(p.keywords[:5])}")
                if p.abstract:
                    print(f"      Abstract: {p.abstract[:150]}...")
                print(f"      Quality: {p.data_quality}/10 | Source: {p.source}")

    finally:
        await collector.close()


if __name__ == "__main__":
    asyncio.run(main())
