#!/usr/bin/env python3
"""CNKI Full Pipeline — metadata harvest → browser download → body text extraction.

One-command workflow:
  python run_full_pipeline.py              # Full pipeline (interactive)
  python run_full_pipeline.py --harvest     # Phase 1 only: metadata harvest
  python run_full_pipeline.py --extract     # Phase 3 only: text extraction from existing PDFs

Flow:
  Phase 1 (auto):  RSS → curl_cffi → detail pages → metadata JSON + download list HTML
  Phase 2 (manual): User opens download_list.html in browser, clicks to download PDFs
  Phase 3 (auto):  Scan PDF dir → extract body text → merge with metadata → complete JSON

Requirements:
  pip install curl_cffi pypdf beautifulsoup4 pdfplumber
"""

import sys
import os
import argparse
import asyncio
import json
import time
from pathlib import Path
from datetime import datetime

# Ensure we can import from the project
sys.path.insert(0, os.path.dirname(__file__))

from crawler.hybrid_scraper import CNKIHybridScraper, FullPaperData


# ── Configuration ─────────────────────────────────────────────

DEFAULT_CONFIG = {
    "cookies_file": "cookies.json",
    "output_dir": "../数据库/cnki/hybrid",
    "pdf_dir": "downloads/pdf",
    "journals": [
        {"code": "GJXW", "name": "国际新闻界", "discipline": "新闻传播学"},
        {"code": "YANJ", "name": "新闻与传播研究", "discipline": "新闻传播学"},
        {"code": "XWDX", "name": "新闻大学", "discipline": "新闻传播学"},
        {"code": "DACB", "name": "当代传播", "discipline": "新闻传播学"},
    ],
    "papers_per_journal": 5,
}

# 期刊代码到名称的映射（--journal 参数支持）
JOURNAL_CODE_MAP = {
    "GJXW": ("国际新闻界", "新闻传播学"),
    "YANJ": ("新闻与传播研究", "新闻传播学"),
    "XWDX": ("新闻大学", "新闻传播学"),
    "DACB": ("当代传播", "新闻传播学"),
    "XWJZ": ("新闻记者", "新闻传播学"),
    "ZGXW": ("中国新闻", "新闻传播学"),
    "XWCB": ("新闻传播", "新闻传播学"),
}


# ── Phase 1: Metadata Harvest ─────────────────────────────────

async def phase1_harvest(config: dict) -> list[FullPaperData]:
    """Harvest paper metadata from CNKI via RSS + detail pages."""
    print("=" * 70)
    print("PHASE 1: Metadata Harvest")
    print("=" * 70)
    print()

    # Load cookies
    cookies_file = config["cookies_file"]
    if not os.path.exists(cookies_file):
        print(f"ERROR: cookies.json not found at {os.path.abspath(cookies_file)}")
        print("Please create cookies.json with your CNKI university library cookies.")
        print("Template: see cookies.json in the project root")
        return []

    cookies = CNKIHybridScraper.load_cookies_from_file(cookies_file)

    # Check expiry
    expiry = CNKIHybridScraper.check_cookie_expiry(cookies)
    if expiry["warning"]:
        print(f"[!] {expiry['warning']}")
    if expiry["is_expired"]:
        print("[!] Cookies are EXPIRED. Metadata harvest may still work,")
        print("[!] but PDF downloads will fail.")
        print()
        cont = input("Continue anyway? [y/N]: ")
        if cont.lower() != "y":
            return []

    scraper = CNKIHybridScraper(
        cookies=cookies,
        output_dir=config["output_dir"],
    )

    all_papers: list[FullPaperData] = []

    try:
        for journal in config["journals"]:
            print(f"\n--- {journal['name']} ({journal['code']}) ---")
            papers = await scraper.harvest_paper(
                journal_code=journal["code"],
                journal_name=journal["name"],
                discipline=journal["discipline"],
                max_papers=config["papers_per_journal"],
                download_pdfs=False,  # PDF needs browser JS
            )
            all_papers.extend(papers)
            print(f"  → {len(papers)} papers harvested")

        print(f"\n{'='*70}")
        print(f"Phase 1 Complete: {len(all_papers)} papers from {len(config['journals'])} journals")
        print(f"{'='*70}")

        # Field completeness
        if all_papers:
            fields = ["title", "authors", "year", "journal_name", "abstract", "keywords", "doi"]
            for f in fields:
                count = sum(1 for p in all_papers if getattr(p, f, None))
                print(f"  {f:15s}: {count}/{len(all_papers)}")

        # Generate download resources
        if all_papers:
            scraper.generate_download_html(all_papers)
            scraper.generate_download_bat(all_papers)
            scraper.export_results_summary(all_papers)

        # Save phase 1 completion marker
        marker = {
            "phase": "harvest_complete",
            "timestamp": datetime.now().isoformat(),
            "paper_count": len(all_papers),
            "journals": [j["name"] for j in config["journals"]],
            "output_dir": config["output_dir"],
            "pdf_dir": config["pdf_dir"],
        }
        Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
        Path(config["output_dir"]).joinpath("pipeline_state.json").write_text(
            json.dumps(marker, ensure_ascii=False, indent=2)
        )

    finally:
        scraper.export_error_log_md()
        await scraper.close()

    return all_papers


# ── Phase 3: Text Extraction ──────────────────────────────────

def phase3_extract(config: dict):
    """Extract body text from downloaded PDFs and merge with metadata."""
    print("=" * 70)
    print("PHASE 3: Body Text Extraction + Merge")
    print("=" * 70)
    print()

    from crawler.pdf_text_extractor import PDFTextExtractor

    extractor = PDFTextExtractor(
        pdf_dir=config["pdf_dir"],
        metadata_dir=config["output_dir"],
    )

    stats = extractor.process_all(match_meta=True, merge=True)
    report_path = extractor.export_report()
    print(f"\nReport: {report_path}")

    # Save phase 3 completion marker
    marker = {
        "phase": "extraction_complete",
        "timestamp": datetime.now().isoformat(),
        **stats,
    }
    Path(config["output_dir"]).joinpath("pipeline_state.json").write_text(
        json.dumps(marker, ensure_ascii=False, indent=2)
    )

    return stats


# ── Interactive Full Pipeline ─────────────────────────────────

async def run_full_pipeline(config: dict):
    """Run the complete pipeline interactively."""
    print("╔══════════════════════════════════════════════════════════╗")
    print("║        CNKI Full Pipeline — Browser-Assisted Download   ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    # Phase 1: Harvest metadata
    papers = await phase1_harvest(config)

    if not papers:
        print("\nNo papers harvested. Check cookies and network connection.")
        return

    # Phase 1→2: Instructions for user
    print("\n" + "=" * 70)
    print("PHASE 2: Browser Download (Manual Step)")
    print("=" * 70)
    print()
    print("Please complete the following steps in your browser:")
    print()
    print(f"  1. Open the download page:")
    print(f"     {config['output_dir']}/download_list_*.html")
    print()
    print(f"  2. For each paper, click 'PDF下载' button")
    print(f"     → A new tab will open with the CNKI download page")
    print(f"     → The PDF should start downloading automatically")
    print()
    print(f"  3. Save ALL downloaded PDFs to:")
    print(f"     {os.path.abspath(config['pdf_dir'])}/")
    print()
    print(f"  4. After all downloads are complete, come back here")
    print()

    input("Press ENTER when you have finished downloading all PDFs...")

    # Verify PDFs exist
    pdf_dir = Path(config["pdf_dir"])
    pdfs = list(pdf_dir.rglob("*.pdf")) if pdf_dir.exists() else []
    if not pdfs:
        print(f"\n[!] No PDF files found in {pdf_dir}")
        print(f"[!] Please place downloaded PDFs there and run:")
        print(f"    python run_full_pipeline.py --extract")
        return

    print(f"\nFound {len(pdfs)} PDF files. Proceeding to extraction...\n")

    # Phase 3: Text extraction
    phase3_extract(config)

    # Final summary
    print("\n" + "=" * 70)
    print("PIPELINE COMPLETE!")
    print("=" * 70)
    print()
    print(f"  Metadata JSONs: {config['output_dir']}/")
    print(f"  Complete papers: {config['output_dir']}/complete/")
    print(f"  Error log: {config['output_dir']}/error_log_*.md")
    print(f"  Extraction report: {config['pdf_dir']}/extraction_report_*.md")
    print()


# ── CLI ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CNKI Full Pipeline — harvest metadata + extract body text"
    )
    parser.add_argument(
        "--harvest", action="store_true",
        help="Run Phase 1 only: metadata harvest + download list generation"
    )
    parser.add_argument(
        "--extract", action="store_true",
        help="Run Phase 3 only: extract body text from existing PDFs"
    )
    parser.add_argument(
        "--journal", type=str, default="",
        help="Journal code to harvest (e.g., GJXW). Default: all configured journals"
    )
    parser.add_argument(
        "--papers", type=int, default=0,
        help="Max papers per journal (default: 5)"
    )
    parser.add_argument(
        "--pdf-dir", type=str, default="downloads/pdf",
        help="Directory for downloaded PDFs"
    )
    parser.add_argument(
        "--output", type=str, default="../数据库/cnki/hybrid",
        help="Output directory for metadata and reports"
    )
    args = parser.parse_args()

    config = {**DEFAULT_CONFIG}
    config["pdf_dir"] = args.pdf_dir
    config["output_dir"] = args.output

    if args.papers > 0:
        config["papers_per_journal"] = args.papers

    if args.journal:
        # 从期刊代码映射中查找名称和学科，未找到时使用代码作为名称
        journal_name, discipline = JOURNAL_CODE_MAP.get(
            args.journal, (args.journal, "custom")
        )
        config["journals"] = [{
            "code": args.journal,
            "name": journal_name,
            "discipline": discipline,
        }]

    # Create PDF download directory
    Path(config["pdf_dir"]).mkdir(parents=True, exist_ok=True)

    if args.extract:
        # Phase 3 only
        phase3_extract(config)
    elif args.harvest:
        # Phase 1 only
        asyncio.run(phase1_harvest(config))
    else:
        # Full interactive pipeline
        asyncio.run(run_full_pipeline(config))


if __name__ == "__main__":
    main()
