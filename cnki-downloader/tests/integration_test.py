"""End-to-end integration test for CNKI downloader pipeline.

Tests: Playwright launch → journal page → issue extraction → paper detail → PDF download.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from config.journals import get_journals_for

from crawler.cnki_navigator import CNKINavigator
from crawler.journal_crawler import journal_crawler
from crawler.issue_crawler import IssueCrawler
from crawler.paper_crawler import PaperCrawler
from crawler.pdf_downloader import PDFDownloader

from anti_anti_crawl.browser_manager import BrowserManager, shutdown_browser_manager
from anti_anti_crawl.fingerprint_engine import fingerprint_engine
from anti_anti_crawl.behavior_simulator import behavior_simulator
from anti_anti_crawl.rhythm_detector import rhythm_detector
from anti_anti_crawl.proxy_manager import proxy_manager
from anti_anti_crawl.session_manager import session_manager

from models.journal import Journal, Issue
from storage.file_manager import file_manager

# ── Setup ───────────────────────────────────────────────

TEST_DISCIPLINE = "新闻传播学"
TEST_JOURNAL_NAME = "国际新闻界"
TEST_YEAR = 2024
OUTPUT_DIR = Path(settings.STORAGE_BASE) / TEST_DISCIPLINE / TEST_JOURNAL_NAME / str(TEST_YEAR)

async def main():
    results = {
        "test": "CNKI Downloader Integration Test",
        "started_at": datetime.now().isoformat(),
        "steps": {},
    }

    print("=" * 60)
    print("CNKI Downloader Integration Test")
    print(f"Target: {TEST_JOURNAL_NAME} ({TEST_DISCIPLINE}), {TEST_YEAR}")
    print(f"Proxy: {settings.PROXY_ENABLED} ({settings.PROXY_URL})")
    print("=" * 60)

    bm = BrowserManager()
    navigator = CNKINavigator()
    issue_crawler = IssueCrawler(navigator)
    paper_crawler = PaperCrawler(navigator)
    pdf_downloader = PDFDownloader()

    try:
        # ── Step 1: Browser Launch ──────────────────────
        print("\n[Step 1] Launching browser...")
        step_start = time.time()
        await bm.initialize()
        results["steps"]["browser_init"] = {
            "success": True,
            "duration_s": round(time.time() - step_start, 1),
        }
        print(f"  OK — Browser launched ({(time.time() - step_start):.1f}s)")

        # ── Step 2: Proxy Check ─────────────────────────
        print("\n[Step 2] Checking proxy...")
        proxy_healthy = await proxy_manager.verify()
        results["steps"]["proxy_check"] = {
            "success": proxy_healthy,
            "ip": proxy_manager._last_ip,
        }
        print(f"  {'OK' if proxy_healthy else 'SKIP'} — Proxy IP: {proxy_manager._last_ip}")

        # ── Step 3: Journal Homepage ─────────────────────
        print("\n[Step 3] Navigating to journal homepage...")
        page = await bm.new_page()

        # Get journal config
        journals = get_journals_for(TEST_DISCIPLINE)
        target_journal = next((j for j in journals if j.name == TEST_JOURNAL_NAME), journals[0])
        journal = Journal(
            name=target_journal.name,
            discipline=TEST_DISCIPLINE,
            cnki_pcode=target_journal.cnki_pcode,
        )

        print(f"  Journal URL: {journal.navi_url}")

        step_start = time.time()
        success = await navigator.safe_navigate(
            page,
            journal.navi_url,
            wait_selector=".year-list, .issue-list, [class*='year'], [class*='issue']",
            timeout=20000,
        )

        if not success:
            # Check page content
            try:
                title = await page.title()
                url = page.url
                print(f"  FAILED — Page title: {title}")
                print(f"  Current URL: {url}")

                body_text = await page.evaluate("() => document.body.innerText.slice(0, 300)")
                print(f"  Body preview: {body_text[:200]}...")
            except Exception as e:
                print(f"  Error reading page: {e}")

            results["steps"]["journal_navigate"] = {
                "success": False,
                "duration_s": round(time.time() - step_start, 1),
            }
        else:
            results["steps"]["journal_navigate"] = {
                "success": True,
                "duration_s": round(time.time() - step_start, 1),
            }
            print(f"  OK — Navigated successfully ({(time.time() - step_start):.1f}s)")

            # Apply fingerprint and simulate reading
            await fingerprint_engine.randomize_all(page)
            await behavior_simulator.slow_scroll_through(page)

            # ── Step 4: Extract Issues ───────────────────
            print(f"\n[Step 4] Extracting issues for {TEST_YEAR}...")
            step_start = time.time()

            # Use the JournalCrawler to extract issues
            issues = await journal_crawler.crawl_journal(page, journal)

            # Filter for test year
            year_issues = [i for i in issues if i.year == TEST_YEAR]
            results["steps"]["issue_extraction"] = {
                "success": len(year_issues) > 0,
                "total_issues_found": len(issues),
                "year_issues_found": len(year_issues),
                "duration_s": round(time.time() - step_start, 1),
            }
            print(f"  OK — Found {len(issues)} total issues, {len(year_issues)} for {TEST_YEAR}")

            if year_issues:
                print(f"  Issues: {', '.join(f'{i.year}No.{i.number}' for i in year_issues[:5])}")

                # ── Step 5: Extract Papers from First Issue ──
                test_issue = year_issues[0]
                print(f"\n[Step 5] Extracting papers from: {test_issue.display_name}")
                print(f"  URL: {test_issue.url}")

                step_start = time.time()
                papers = await issue_crawler.crawl_issue(page, test_issue)
                results["steps"]["paper_extraction"] = {
                    "success": len(papers) > 0,
                    "papers_found": len(papers),
                    "duration_s": round(time.time() - step_start, 1),
                }
                print(f"  OK — Found {len(papers)} papers")

                if papers:
                    # Show first 5 papers
                    for i, p in enumerate(papers[:5]):
                        print(f"  [{i+1}] {p.get('title', 'N/A')[:60]}...")
                        print(f"      Authors: {p.get('authors', 'N/A')[:40]}")

                    # ── Step 6: Paper Detail + Download ──
                    test_paper = papers[0]
                    if test_paper.get("paper_url"):
                        print(f"\n[Step 6] Fetching paper detail: {test_paper.get('title', '')[:50]}...")

                        step_start = time.time()
                        metadata = await paper_crawler.crawl_paper(
                            page, test_paper["paper_url"], test_paper
                        )
                        results["steps"]["paper_detail"] = {
                            "success": bool(metadata.get("abstract") or metadata.get("download_url")),
                            "has_abstract": bool(metadata.get("abstract")),
                            "has_download_url": bool(metadata.get("download_url")),
                            "download_url": metadata.get("download_url", "")[:80],
                            "file_format": metadata.get("file_format", ""),
                            "duration_s": round(time.time() - step_start, 1),
                        }
                        print(f"  Abstract length: {len(metadata.get('abstract', ''))} chars")
                        print(f"  Keywords: {metadata.get('keywords', [])}")
                        print(f"  Download URL: {metadata.get('download_url', 'N/A')[:80]}")
                        print(f"  Format: {metadata.get('file_format', 'unknown')}")

                        # ── Step 7: Download PDF/CAJ ──
                        if metadata.get("download_url"):
                            print(f"\n[Step 7] Downloading file...")
                            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

                            step_start = time.time()
                            dl_result = await pdf_downloader.download(
                                page,
                                metadata["download_url"],
                                test_paper.get("title", "untitled"),
                                OUTPUT_DIR,
                            )
                            results["steps"]["file_download"] = {
                                "success": dl_result is not None,
                                "duration_s": round(time.time() - step_start, 1),
                            }

                            if dl_result:
                                results["steps"]["file_download"].update({
                                    "path": dl_result["path"],
                                    "format": dl_result["format"],
                                    "size_bytes": dl_result["size_bytes"],
                                    "size_mb": round(dl_result["size_bytes"] / (1024 * 1024), 2),
                                })
                                print(f"  OK — Downloaded: {dl_result['filename']}")
                                print(f"  Format: {dl_result['format']}")
                                print(f"  Size: {dl_result['size_bytes']} bytes ({dl_result['size_bytes']/(1024*1024):.2f} MB)")

                                # Verify file
                                import hashlib
                                fpath = Path(dl_result["path"])
                                if fpath.exists():
                                    print(f"  File exists: YES")
                                    if dl_result["format"] == "caj":
                                        print(f"  Note: CAJ format — conversion to TXT needed")
                            else:
                                print(f"  FAILED — Could not download file")
                        else:
                            print(f"\n[Step 7] SKIP — No download URL available")
                            print(f"  (This paper may only have abstract on CNKI)")
                    else:
                        print(f"\n[Step 6] SKIP — No paper detail URL")

        # Close page
        await bm.close_page(page)

    except Exception as e:
        import traceback
        print(f"\n[ERROR] {e}")
        traceback.print_exc()
        results["error"] = str(e)

    finally:
        # ── Cleanup ────────────────────────────────────
        print("\n[Cleanup] Shutting down browser...")
        await shutdown_browser_manager()

        # ── Summary ────────────────────────────────────
        print("\n" + "=" * 60)
        print("TEST RESULTS")
        print("=" * 60)
        for step, data in results["steps"].items():
            status = "✓" if data.get("success") else "✗"
            print(f"  {status} {step}: {data}")

        # Save results
        results["completed_at"] = datetime.now().isoformat()
        result_path = OUTPUT_DIR / f"integration_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"\nResults saved to: {result_path}")

        # Check output directory
        print(f"\n[Output Check] Files in {OUTPUT_DIR}:")
        if OUTPUT_DIR.exists():
            for f in OUTPUT_DIR.iterdir():
                size = f.stat().st_size
                print(f"  {f.name} ({size:,} bytes)")
        else:
            print("  (directory does not exist)")


if __name__ == "__main__":
    asyncio.run(main())
