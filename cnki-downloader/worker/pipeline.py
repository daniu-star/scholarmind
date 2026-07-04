"""Full CNKI download pipeline orchestrator.

Strings together: journal → issue → paper → download
with anti-anti-crawl checks at every step.
"""

from __future__ import annotations

import asyncio
import structlog
import time
from pathlib import Path
from typing import Optional

from models.task import Task
from models.paper import Paper, PaperMetadata
from models.enums import TaskStatus, ErrorCategory

from crawler.cnki_navigator import CNKINavigator
from crawler.journal_crawler import journal_crawler
from crawler.issue_crawler import IssueCrawler
from crawler.paper_crawler import PaperCrawler
from crawler.pdf_downloader import PDFDownloader

from anti_anti_crawl.browser_manager import get_browser_manager
from anti_anti_crawl.fingerprint_engine import fingerprint_engine
from anti_anti_crawl.behavior_simulator import behavior_simulator
from anti_anti_crawl.captcha_bypass import captcha_bypass
from anti_anti_crawl.rhythm_detector import rhythm_detector
from anti_anti_crawl.proxy_manager import proxy_manager

from utils.retry import RetryManager, CircuitBreaker, CircuitBreakerOpenError

logger = structlog.get_logger()


class DownloadPipeline:
    """Orchestrates the full CNKI paper download pipeline."""

    def __init__(self, worker_id: str, discipline: str, storage_base: Path):
        self.worker_id = worker_id
        self.discipline = discipline
        self.storage_base = storage_base
        self.navigator = CNKINavigator()
        self.issue_crawler = IssueCrawler(self.navigator)
        self.paper_crawler = PaperCrawler(self.navigator)
        self.pdf_downloader = PDFDownloader()

        # Per-discipline circuit breaker
        self.circuit_breaker = CircuitBreaker(
            name=f"cnki-{discipline}",
            failure_threshold=5,
            timeout=300.0,
        )

    async def execute_task(self, task: Task) -> Optional[Paper]:
        """Execute a single download task through the full pipeline.

        Args:
            task: The task to execute

        Returns:
            Paper object on success, None on failure
        """
        task_start = time.time()

        try:
            async with self.circuit_breaker:
                return await self._run_pipeline(task)

        except CircuitBreakerOpenError:
            logger.warning("circuit_breaker_open", discipline=self.discipline)
            task.status = TaskStatus.FAILED
            task.error_type = ErrorCategory.RATE_LIMIT.value
            task.error_message = "Circuit breaker open — cooling down"
            return None

        except Exception as e:
            duration = time.time() - task_start
            logger.error(
                "task_execution_failed",
                task_id=task.task_id,
                duration=round(duration, 1),
                error=str(e),
            )
            task.status = TaskStatus.FAILED
            task.error_type = ErrorCategory.UNKNOWN.value
            task.error_message = str(e)
            return None

    async def _run_pipeline(self, task: Task) -> Optional[Paper]:
        """Internal pipeline execution with anti-crawl checks at each step."""
        bm = get_browser_manager()

        # ── Step 1: Get browser context ± warm session ──
        page = await bm.new_page()
        try:
            # Apply fingerprint randomization
            await fingerprint_engine.randomize_all(page)

            # ── Step 2: Check rhythm before navigation ──
            await rhythm_detector.adapt_delays()

            # ── Step 3: Navigate to issue page ──
            issue_url = task.issue_url or task.journal_url
            if not issue_url:
                logger.error("task_no_url", task_id=task.task_id)
                return None

            success = await self.navigator.safe_navigate(
                page, issue_url,
                wait_selector=".result-table-list, [class*='result'], [class*='paper']",
            )

            if not success:
                state = await rhythm_detector.check(page)
                if state == "captcha":
                    solved = await captcha_bypass.handle_persistent_captcha(page)
                    if not solved:
                        task.status = TaskStatus.FAILED
                        task.error_type = ErrorCategory.CAPTCHA.value
                        task.error_message = "CAPTCHA unsolved"
                        return None
                elif state == "blocked":
                    await proxy_manager.auto_rotate_on_block()
                    task.status = TaskStatus.FAILED
                    task.error_type = ErrorCategory.RATE_LIMIT.value
                    task.error_message = "Blocked by CNKI"
                    return None

            # ── Step 4: Extract papers from issue page ──
            rhythm_state = await rhythm_detector.check(page)
            if rhythm_state in ("captcha", "blocked"):
                await rhythm_detector.adapt_delays()

            # Simulate human reading
            await behavior_simulator.slow_scroll_through(page)

            # If the task has a specific paper URL, go directly to it
            if task.paper_url:
                paper_metadata = await self._download_single_paper(page, task)
                if paper_metadata:
                    return self._build_paper(task, paper_metadata)
                return None

            # Otherwise extract all papers from the issue
            from models.journal import Issue
            issue = Issue(
                journal_name=task.journal_name,
                discipline=task.discipline,
                year=task.year,
                number=task.issue_number,
                url=task.issue_url,
            )

            papers = await self.issue_crawler.crawl_issue(page, issue)

            # ── Step 5: Process papers (brief: Task queue handles individual papers) ──
            # For the pipeline, we return paper metadata for the task system to handle
            logger.info(
                "pipeline_issue_processed",
                journal=task.journal_name,
                year=task.year,
                issue=task.issue_number,
                papers_found=len(papers),
            )

            # Return a summary paper (for task completion tracking)
            return self._build_summary_paper(task, len(papers))

        finally:
            await bm.close_page(page)

    async def _download_single_paper(
        self, page: "playwright.async_api.Page", task: Task
    ) -> Optional[dict]:
        """Download a single paper given its detail URL."""
        paper_info = {
            "title": task.paper_title,
            "year": task.year,
            "journal_name": task.journal_name,
            "discipline": task.discipline,
            "issue_number": task.issue_number,
        }

        # Extract metadata from detail page
        metadata = await self.paper_crawler.crawl_paper(
            page, task.paper_url, paper_info
        )

        if not metadata.get("download_url"):
            task.status = TaskStatus.COMPLETED  # No PDF available but metadata extracted
            task.error_type = ErrorCategory.PDF_UNAVAILABLE.value
            task.error_message = "No download URL found"
            return metadata

        # Build save directory path
        save_dir = (
            self.storage_base /
            task.discipline /
            task.journal_name /
            str(task.year)
        )

        # Download the file
        dl_result = await self.pdf_downloader.download(
            page,
            metadata["download_url"],
            task.paper_title,
            save_dir,
        )

        if dl_result:
            metadata["file_path"] = dl_result["path"]
            metadata["file_format"] = dl_result["format"]
            metadata["file_size"] = dl_result["size_bytes"]
            metadata["checksum"] = dl_result["checksum"]

            # Handle CAJ conversion
            if dl_result["format"] == "caj":
                txt_path = await self._convert_caj_to_txt(
                    dl_result["path"], save_dir
                )
                if txt_path:
                    metadata["txt_path"] = str(txt_path)

        return metadata

    async def _convert_caj_to_txt(self, caj_path: str, save_dir: Path) -> Optional[Path]:
        """Attempt to convert CAJ format to plain text."""
        # Try using cajparser library if available
        try:
            import subprocess
            txt_path = Path(caj_path).with_suffix(".txt")

            # Attempt Python-based CAJ parsing
            try:
                from cajparser import CAJParser
                parser = CAJParser()
                text = parser.parse(caj_path)
                if text:
                    txt_path.write_text(text, encoding="utf-8")
                    logger.info("caj_converted", path=str(txt_path))
                    return txt_path
            except ImportError:
                pass

            # Fallback: try caj2pdf tool (if installed)
            try:
                pdf_path = Path(caj_path).with_suffix(".converted.pdf")
                result = subprocess.run(
                    ["caj2pdf", "convert", caj_path, "-o", str(pdf_path)],
                    capture_output=True, timeout=60,
                )
                if result.returncode == 0 and pdf_path.exists():
                    logger.info("caj2pdf_converted", path=str(pdf_path))
                    return pdf_path
            except Exception:
                pass

            logger.warning("caj_conversion_failed", path=caj_path)
            return None

        except Exception as e:
            logger.error("caj_conversion_error", error=str(e))
            return None

    @staticmethod
    def _build_paper(task: Task, metadata: dict) -> Paper:
        return Paper(
            title=task.paper_title,
            authors=metadata.get("authors", "").split(",") if metadata.get("authors") else [],
            year=task.year,
            journal_name=task.journal_name,
            discipline=task.discipline,
            issue_number=task.issue_number,
            abstract=metadata.get("abstract", ""),
            keywords=metadata.get("keywords", []),
            doi=metadata.get("doi", ""),
            cnki_url=task.paper_url,
            pdf_download_url=metadata.get("download_url", ""),
            file_format=metadata.get("file_format", ""),
            pdf_path=metadata.get("file_path", ""),
            txt_path=metadata.get("txt_path", ""),
            pdf_size_bytes=metadata.get("file_size", 0),
            download_status=TaskStatus.COMPLETED,
        )

    @staticmethod
    def _build_summary_paper(task: Task, paper_count: int) -> Paper:
        return Paper(
            title=f"[ISSUE] {task.journal_name} {task.year}年第{task.issue_number}期",
            year=task.year,
            journal_name=task.journal_name,
            discipline=task.discipline,
            issue_number=task.issue_number,
            pdf_page_count=paper_count,
            download_status=TaskStatus.COMPLETED,
        )
