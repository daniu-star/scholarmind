"""PDF text extractor — scans downloaded PDFs, extracts body text, merges with metadata.

Works in conjunction with hybrid_scraper.py:
  1. hybrid_scraper harvests metadata + generates download list
  2. User downloads PDFs via browser → saves to downloads/pdf/
  3. This module scans the PDF directory, extracts text, and merges with metadata

Usage:
  python -m crawler.pdf_text_extractor --pdf-dir downloads/pdf --meta-dir 数据库/cnki/hybrid
"""

import json
import re
import hashlib
import sys
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional
from io import BytesIO


@dataclass
class ExtractionResult:
    """Result of extracting text from a single PDF."""
    pdf_path: str = ""
    filename: str = ""
    body_text: str = ""
    char_count: int = 0
    word_count: int = 0
    page_count: int = 0
    success: bool = False
    error: str = ""
    checksum: str = ""
    matched_metadata: Optional[str] = None  # Path to matching metadata JSON


class PDFTextExtractor:
    """Scans PDF directory, extracts body text, merges with paper metadata."""

    def __init__(self, pdf_dir: str = "downloads/pdf", metadata_dir: str = "../数据库/cnki/hybrid"):
        self.pdf_dir = Path(pdf_dir)
        self.metadata_dir = Path(metadata_dir)
        self.results: list[ExtractionResult] = []
        self._stats = {"total_pdfs": 0, "success": 0, "failed": 0, "matched": 0, "unmatched": 0}

    # ── PDF Scanning ──────────────────────────────────────────

    def scan_pdfs(self) -> list[Path]:
        """Recursively find all PDF files in the PDF directory."""
        if not self.pdf_dir.exists():
            raise FileNotFoundError(
                f"PDF directory not found: {self.pdf_dir.resolve()}\n"
                f"Please create this directory and place downloaded PDFs there."
            )

        pdfs = list(self.pdf_dir.rglob("*.pdf"))
        self._stats["total_pdfs"] = len(pdfs)
        return pdfs

    # ── Text Extraction ───────────────────────────────────────

    def extract_text(self, pdf_path: Path) -> ExtractionResult:
        """Extract text from a single PDF using pypdf (primary) + pdfplumber (fallback)."""
        result = ExtractionResult(
            pdf_path=str(pdf_path),
            filename=pdf_path.name,
        )

        try:
            content = pdf_path.read_bytes()

            # Validate it's a PDF
            if content[:5] != b"%PDF-":
                result.error = "Not a valid PDF file"
                self._stats["failed"] += 1
                return result

            result.checksum = hashlib.sha256(content).hexdigest()[:12]

            # Try pypdf
            text = self._extract_with_pypdf(content)

            # Fallback to pdfplumber if pypdf gives too little text
            if not text or len(text) < 200:
                text2 = self._extract_with_pdfplumber(content)
                if text2 and len(text2) > len(text):
                    text = text2

            # Clean up extracted text
            text = self._clean_text(text)

            result.body_text = text
            result.char_count = len(text)
            result.word_count = len(text.split()) if text else 0
            result.success = bool(text and len(text) > 50)

            if result.success:
                self._stats["success"] += 1
            else:
                self._stats["failed"] += 1
                if not result.error:
                    result.error = f"Extracted text too short ({len(text)} chars)"

        except Exception as e:
            result.error = str(e)[:200]
            self._stats["failed"] += 1

        self.results.append(result)
        return result

    @staticmethod
    def _extract_with_pypdf(content: bytes) -> str:
        """Extract text using pypdf library."""
        try:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(content))
            pages = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text)
            return "\n\n".join(pages)
        except ImportError:
            return ""
        except Exception:
            return ""

    @staticmethod
    def _extract_with_pdfplumber(content: bytes) -> str:
        """Extract text using pdfplumber library (more accurate but slower)."""
        try:
            import pdfplumber
            with pdfplumber.open(BytesIO(content)) as pdf:
                pages = []
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        pages.append(page_text)
                return "\n\n".join(pages)
        except ImportError:
            return ""
        except Exception:
            return ""

    @staticmethod
    def _clean_text(text: str) -> str:
        """Clean extracted PDF text."""
        if not text:
            return ""

        # Remove excessive whitespace
        text = re.sub(r"[ \t]+", " ", text)
        # Collapse multiple newlines (keep at most 2)
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Remove page numbers (standalone digits on their own line)
        text = re.sub(r"^\d{1,4}$", "", text, flags=re.MULTILINE)
        # Remove form feeds
        text = text.replace("\f", "\n")
        # Strip leading/trailing whitespace
        text = text.strip()

        return text

    # ── Metadata Matching ────────────────────────────────────

    def match_metadata(self, result: ExtractionResult) -> Optional[Path]:
        """Match a PDF to its metadata JSON file by comparing filename/title similarity."""
        if not self.metadata_dir.exists():
            return None

        # Strategy 1: Match by filename substring (e.g., "GJXW202603005" in PDF filename)
        meta_files = list(self.metadata_dir.rglob("*_metadata.json"))
        if not meta_files:
            meta_files = list(self.metadata_dir.rglob("*.json"))

        for meta_path in meta_files:
            try:
                meta = json.loads(meta_path.read_text("utf-8"))
                # Check if filename/cnki filename appears in PDF filename or vice versa
                cnki_fn = meta.get("filename", "")
                if cnki_fn and cnki_fn.lower() in result.filename.lower():
                    self._stats["matched"] += 1
                    result.matched_metadata = str(meta_path)
                    return meta_path
            except (json.JSONDecodeError, KeyError):
                continue

        # Strategy 2: Match by title similarity
        for meta_path in meta_files:
            try:
                meta = json.loads(meta_path.read_text("utf-8"))
                title = meta.get("title", "")
                if title and len(title) > 5:
                    # Check if parts of the title appear in the PDF filename
                    title_words = set(title[:20])
                    filename_chars = set(result.filename)
                    if len(title_words & filename_chars) >= 3:
                        self._stats["matched"] += 1
                        result.matched_metadata = str(meta_path)
                        return meta_path
            except (json.JSONDecodeError, KeyError):
                continue

        self._stats["unmatched"] += 1
        return None

    def merge_and_save(
        self, result: ExtractionResult, meta_path: Path, output_dir: Optional[str] = None
    ) -> Optional[Path]:
        """Merge extracted body text with metadata and save as complete paper JSON."""
        try:
            meta = json.loads(meta_path.read_text("utf-8"))
        except Exception:
            return None

        # Merge body text
        meta["body_text"] = result.body_text
        meta["body_text_length"] = result.char_count
        meta["body_text_word_count"] = result.word_count
        meta["file_path"] = str(result.pdf_path)
        meta["file_checksum"] = result.checksum
        meta["extraction_date"] = datetime.now().isoformat()
        meta["data_complete"] = True

        # Save merged data
        if output_dir:
            out_path = Path(output_dir)
        else:
            out_path = meta_path.parent / "complete"

        out_path.mkdir(parents=True, exist_ok=True)

        safe_title = re.sub(r'[<>:"/\\|?*]', "_", meta.get("title", "untitled"))[:60]
        output_file = out_path / f"{safe_title}_complete.json"
        output_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        return output_file

    # ── Batch Processing ──────────────────────────────────────

    def process_all(self, match_meta: bool = True, merge: bool = True) -> dict:
        """Scan, extract, match, and merge all PDFs. Returns summary stats."""
        pdfs = self.scan_pdfs()
        if not pdfs:
            print(f"No PDFs found in {self.pdf_dir}")
            return self._stats

        print(f"Found {len(pdfs)} PDFs to process\n")

        for i, pdf_path in enumerate(pdfs, 1):
            print(f"[{i}/{len(pdfs)}] {pdf_path.name[:60]}...")
            result = self.extract_text(pdf_path)

            if result.success:
                print(f"    Text: {result.char_count} chars, ~{result.word_count} words")

                if match_meta:
                    meta_path = self.match_metadata(result)
                    if meta_path:
                        print(f"    Matched: {meta_path.name[:60]}")

                        if merge:
                            merged = self.merge_and_save(result, meta_path)
                            if merged:
                                print(f"    Merged → {merged.name[:60]}")
                    else:
                        print(f"    No matching metadata found")
            else:
                print(f"    FAILED: {result.error[:100]}")

            print()

        # Print summary
        print("=" * 60)
        print("Extraction Summary")
        print("=" * 60)
        print(f"  Total PDFs:    {self._stats['total_pdfs']}")
        print(f"  Text success:  {self._stats['success']}")
        print(f"  Text failed:   {self._stats['failed']}")
        print(f"  Metadata match:{self._stats['matched']}")
        print(f"  Unmatched:     {self._stats['unmatched']}")

        return self._stats

    def export_report(self, output_path: Optional[str] = None) -> str:
        """Export extraction results as markdown report."""
        if output_path is None:
            output_path = str(self.pdf_dir / f"extraction_report_{datetime.now():%Y%m%d_%H%M%S}.md")

        lines = [
            "# PDF Text Extraction Report",
            "",
            f"**Date**: {datetime.now():%Y-%m-%d %H:%M:%S}",
            f"**PDF Directory**: {self.pdf_dir.resolve()}",
            f"**Metadata Directory**: {self.metadata_dir.resolve()}",
            "",
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total PDFs | {self._stats['total_pdfs']} |",
            f"| Text Extracted | {self._stats['success']} |",
            f"| Extraction Failed | {self._stats['failed']} |",
            f"| Metadata Matched | {self._stats['matched']} |",
            f"| Unmatched | {self._stats['unmatched']} |",
            "",
            "## Detailed Results",
            "",
            "| # | File | Chars | Words | Status |",
            "|---|------|-------|-------|--------|",
        ]

        for i, r in enumerate(self.results, 1):
            status = "OK" if r.success else f"FAIL: {r.error[:40]}"
            lines.append(
                f"| {i} | {r.filename[:50]} | {r.char_count} | {r.word_count} | {status} |"
            )

        md = "\n".join(lines)
        Path(output_path).write_text(md, encoding="utf-8")
        return output_path


# ── CLI Entry Point ──────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract body text from downloaded CNKI PDFs and merge with metadata"
    )
    parser.add_argument(
        "--pdf-dir", default="downloads/pdf",
        help="Directory containing downloaded PDF files"
    )
    parser.add_argument(
        "--meta-dir", default="../数据库/cnki/hybrid",
        help="Directory containing metadata JSON files from hybrid_scraper"
    )
    parser.add_argument(
        "--no-match", action="store_true",
        help="Skip metadata matching"
    )
    parser.add_argument(
        "--no-merge", action="store_true",
        help="Skip merging with metadata (extract text only)"
    )
    args = parser.parse_args()

    extractor = PDFTextExtractor(
        pdf_dir=args.pdf_dir,
        metadata_dir=args.meta_dir,
    )

    stats = extractor.process_all(
        match_meta=not args.no_match,
        merge=not args.no_merge,
    )

    report_path = extractor.export_report()
    print(f"\nReport saved: {report_path}")

    return stats


if __name__ == "__main__":
    main()
