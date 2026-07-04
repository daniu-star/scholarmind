"""PDF/CAJ downloader — handles binary file download and verification.

Downloads paper files from CNKI, verifies integrity, supports both PDF and CAJ formats.
"""

from __future__ import annotations

import asyncio
import hashlib
import structlog
import os
import random
import time
from pathlib import Path
from typing import Optional, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = structlog.get_logger()


class PDFDownloader:
    """Downloads paper files (PDF/CAJ) from CNKI and verifies them."""

    # Minimum file size (bytes) to consider a download valid
    MIN_PDF_SIZE = 10 * 1024  # 10 KB
    MAX_DOWNLOAD_TIMEOUT = 120  # seconds

    def __init__(self):
        self._downloaded_count = 0
        self._failed_count = 0

    async def download(
        self,
        page: "Page",
        download_url: str,
        paper_title: str,
        save_dir: Path,
        on_progress: Optional[Callable] = None,
    ) -> Optional[dict]:
        """Download a paper file from CNKI.

        Args:
            page: Playwright page (will open new tab for download)
            download_url: Direct or indirect download URL
            paper_title: Paper title for filename generation
            save_dir: Directory to save the file
            on_progress: Optional progress callback

        Returns:
            dict with path, size, format, checksum or None on failure
        """
        if not download_url:
            logger.warning("no_download_url", title=paper_title[:40])
            self._failed_count += 1
            return None

        save_dir.mkdir(parents=True, exist_ok=True)

        # Open new page for download to keep main page clean
        dl_page = await page.context.new_page()

        try:
            # Set up download listener BEFORE navigation
            download_future: asyncio.Future = asyncio.Future()

            async def handle_download(download):
                try:
                    logger.info("download_started", url=download.url[:80])
                    if not download_future.done():
                        download_future.set_result(download)
                except Exception as e:
                    if not download_future.done():
                        download_future.set_exception(e)

            dl_page.on("download", handle_download)

            # Navigate to download URL
            try:
                await dl_page.goto(
                    download_url,
                    wait_until="commit",
                    timeout=30000,
                )
            except Exception as e:
                # CNKI download pages may throw errors but still trigger download
                logger.debug("download_page_navigation_error", error=str(e)[:100])

            # Wait for download to start
            try:
                download = await asyncio.wait_for(
                    download_future,
                    timeout=self.MAX_DOWNLOAD_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.error("download_timeout", title=paper_title[:40])
                self._failed_count += 1
                return None

            # Determine filename and format
            suggested_filename = download.suggested_filename or ""
            if suggested_filename.lower().endswith(".caj"):
                file_format = "caj"
            elif suggested_filename.lower().endswith(".pdf"):
                file_format = "pdf"
            else:
                # Guess from URL
                if "caj" in download_url.lower():
                    file_format = "caj"
                else:
                    file_format = "pdf"

            # Generate safe filename
            safe_title = self._sanitize_filename(paper_title)
            ext = ".caj" if file_format == "caj" else ".pdf"
            filename = f"{safe_title}{ext}"
            if len(filename) > 200:
                filename = f"{safe_title[:100]}{ext}"

            filepath = save_dir / filename

            # Save the file
            await download.save_as(str(filepath))

            # Verify the file
            file_size = filepath.stat().st_size
            if file_size < self.MIN_PDF_SIZE:
                logger.error(
                    "download_file_too_small",
                    title=paper_title[:40],
                    size=file_size,
                )
                filepath.unlink(missing_ok=True)
                self._failed_count += 1
                return None

            # 校验 PDF 魔数
            # CNKI 可能返回大于 10KB 的 HTML 错误页面，通过大小检查但不是有效 PDF
            with open(filepath, "rb") as f:
                magic = f.read(5)
            if magic[:5] != b"%PDF-" and magic[:4] != b"PK\x03\x04":
                logger.error(
                    "invalid_file_magic",
                    magic=magic[:5],
                    filepath=str(filepath),
                )
                filepath.unlink(missing_ok=True)
                self._failed_count += 1
                return None

            # Calculate checksum
            checksum = self._sha256(filepath)

            self._downloaded_count += 1
            logger.info(
                "download_completed",
                title=paper_title[:40],
                format=file_format,
                size_mb=round(file_size / (1024 * 1024), 2),
                checksum=checksum[:12],
            )

            return {
                "path": str(filepath),
                "filename": filename,
                "format": file_format,
                "size_bytes": file_size,
                "checksum": checksum,
            }

        except Exception as e:
            logger.error(
                "download_failed",
                title=paper_title[:40],
                error=str(e),
            )
            self._failed_count += 1
            return None

        finally:
            # Clean up download page
            try:
                await dl_page.close()
            except Exception:
                pass

    @staticmethod
    def _sanitize_filename(title: str) -> str:
        """Create a safe filename from paper title."""
        # Remove or replace problematic characters
        sanitized = title.replace("/", "-").replace("\\", "-")
        sanitized = sanitized.replace(":", "-").replace("*", "")
        sanitized = sanitized.replace("?", "").replace('"', "")
        sanitized = sanitized.replace("<", "").replace(">", "").replace("|", "-")
        # Replace multiple spaces
        import re
        sanitized = re.sub(r'\s+', '_', sanitized)
        # Limit length
        if len(sanitized) > 100:
            sanitized = sanitized[:100]
        return sanitized.strip("_")

    @staticmethod
    def _sha256(filepath: Path) -> str:
        """Calculate SHA-256 hash of a file."""
        sha = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)
        return sha.hexdigest()

    @property
    def stats(self) -> dict:
        return {
            "downloaded": self._downloaded_count,
            "failed": self._failed_count,
            "total": self._downloaded_count + self._failed_count,
        }

    def reset_stats(self) -> None:
        self._downloaded_count = 0
        self._failed_count = 0
