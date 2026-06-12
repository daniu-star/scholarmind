"""Base crawler class for academic resource collection."""

import asyncio
import hashlib
import json
import logging
import uuid
import random
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)

# Common User-Agent strings for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
]


class BaseCrawler(ABC):
    """Abstract base class for academic resource crawlers."""

    source_db: str = ""
    rate_limit: float = settings.CRAWL_RATE_LIMIT
    max_retries: int = settings.CRAWL_MAX_RETRIES

    @abstractmethod
    async def crawl_hot(self, count: int = 50) -> list[dict]:
        """Crawl hot/trending papers."""
        ...

    @abstractmethod
    async def crawl_latest(self, count: int = 100) -> list[dict]:
        """Crawl latest papers."""
        ...

    @abstractmethod
    async def crawl_by_keyword(self, keyword: str, count: int = 20) -> list[dict]:
        """Crawl papers by keyword."""
        ...

    async def run_with_rate_limit(self, task_fn, *args, **kwargs):
        """Execute a task with rate limiting and retry logic."""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                result = await task_fn(*args, **kwargs)
                # Add random delay to respect rate limit
                delay = self.rate_limit + random.uniform(0, 1)
                await asyncio.sleep(delay)
                return result
            except Exception as e:
                last_error = e
                logger.warning(
                    f"[{self.source_db}] Attempt {attempt + 1}/{self.max_retries} failed: {e}"
                )
                if attempt < self.max_retries - 1:
                    backoff = (2 ** attempt) * self.rate_limit + random.uniform(0, 2)
                    await asyncio.sleep(backoff)
        logger.error(f"[{self.source_db}] All {self.max_retries} attempts failed: {last_error}")
        raise last_error

    def normalize(self, raw: dict) -> dict:
        """Normalize raw data from any source into a standard format."""
        title = raw.get("title", "")
        return {
            "id": raw.get("id", str(uuid.uuid4())),
            "title": title,
            "authors": raw.get("authors", ""),
            "year": str(raw.get("year", "")),
            "source": raw.get("source", ""),
            "source_db": self.source_db,
            "abstract": raw.get("abstract", ""),
            "doi": raw.get("doi", ""),
            "citations": int(raw.get("citations", 0)),
            "is_core": bool(raw.get("is_core", False)),
            "keywords": json.dumps(raw.get("keywords", []), ensure_ascii=False),
            "url": raw.get("url", ""),
            "full_text_hash": hashlib.md5(title.encode("utf-8")).hexdigest() if title else "",
            "crawled_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

    def normalize_batch(self, raw_list: list[dict]) -> list[dict]:
        """Normalize a batch of raw results."""
        return [self.normalize(r) for r in raw_list if r.get("title")]

    @staticmethod
    def get_random_ua() -> str:
        """Get a random User-Agent string."""
        return random.choice(USER_AGENTS)
