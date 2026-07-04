"""CNKI cookie session persistence for the backend.

Saves and loads CNKI cookies to/from disk so that the backend's direct
HTTP search path can reuse previously-acquired session cookies across
restarts, reducing the chance of triggering CAPTCHA challenges.
"""

from __future__ import annotations

import asyncio
import json
import time
import structlog
from pathlib import Path
from typing import Optional

logger = structlog.get_logger(__name__)


class CNKISessionStore:
    """Persist CNKI cookies across backend restarts."""

    def __init__(self, storage_dir: str = "data/cnki_sessions"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    async def save(self, name: str, cookies: list[dict]) -> None:
        """Save cookies to a named session file."""
        filepath = self.storage_dir / f"{name}.json"
        data = {
            "cookies": cookies,
            "saved_at": time.time(),
            "cookie_count": len(cookies),
        }

        def _write():
            filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2))

        await asyncio.to_thread(_write)
        logger.debug(f"cnki_session_saved name={name} count={len(cookies)}")

    async def load(self, name: str) -> Optional[list[dict]]:
        """Load cookies from a named session file.

        Returns None if the file doesn't exist or all cookies have expired.
        """
        filepath = self.storage_dir / f"{name}.json"
        if not filepath.exists():
            return None

        def _read():
            return json.loads(filepath.read_text("utf-8"))

        try:
            data = await asyncio.to_thread(_read)
            cookies = data.get("cookies", [])
            now = time.time()

            # Filter out expired cookies
            valid = [
                c
                for c in cookies
                if c.get("expires", -1) == -1 or c.get("expires", 0) > now
            ]

            if len(valid) < 3:
                # Session is effectively dead — remove it
                filepath.unlink(missing_ok=True)
                logger.info(f"cnki_session_expired name={name} valid_count={len(valid)}")
                return None

            logger.debug(
                f"cnki_session_loaded name={name} total={len(cookies)} valid={len(valid)}"
            )
            return valid

        except Exception as e:
            logger.warning(f"cnki_session_load_failed name={name} error={e}")
            return None

    async def delete(self, name: str) -> None:
        """Delete a named session file."""
        filepath = self.storage_dir / f"{name}.json"
        filepath.unlink(missing_ok=True)

    def list_sessions(self) -> list[dict]:
        """List all available sessions with metadata."""
        results = []
        for fp in self.storage_dir.glob("*.json"):
            try:
                data = json.loads(fp.read_text("utf-8"))
                results.append(
                    {
                        "name": fp.stem,
                        "cookie_count": data.get("cookie_count", 0),
                        "saved_at": data.get("saved_at", 0),
                    }
                )
            except Exception:
                pass
        return sorted(results, key=lambda x: x.get("saved_at", 0), reverse=True)
