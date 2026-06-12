"""SQLite database service for academic resource storage."""

import sqlite3
import uuid
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)


class DatabaseService:
    """SQLite database service for academic resources, crawl logs, and hot keywords."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.DB_PATH
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def init_db(self):
        """Create tables if they don't exist."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS academic_resources (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                authors TEXT DEFAULT '',
                year TEXT DEFAULT '',
                source TEXT DEFAULT '',
                source_db TEXT NOT NULL,
                abstract TEXT DEFAULT '',
                doi TEXT DEFAULT '',
                citations INTEGER DEFAULT 0,
                is_core INTEGER DEFAULT 0,
                keywords TEXT DEFAULT '[]',
                url TEXT DEFAULT '',
                full_text_hash TEXT DEFAULT '',
                crawled_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(title, year, source_db)
            );

            CREATE TABLE IF NOT EXISTS crawl_logs (
                id TEXT PRIMARY KEY,
                source_db TEXT NOT NULL,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                items_found INTEGER DEFAULT 0,
                items_saved INTEGER DEFAULT 0,
                error_msg TEXT DEFAULT '',
                started_at TEXT NOT NULL,
                finished_at TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS hot_keywords (
                id TEXT PRIMARY KEY,
                keyword TEXT NOT NULL,
                frequency INTEGER DEFAULT 1,
                source_db TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                UNIQUE(keyword, source_db)
            );

            CREATE INDEX IF NOT EXISTS idx_resources_source_db
                ON academic_resources(source_db);
            CREATE INDEX IF NOT EXISTS idx_resources_crawled_at
                ON academic_resources(crawled_at);
            CREATE INDEX IF NOT EXISTS idx_logs_source_db
                ON crawl_logs(source_db);
            CREATE INDEX IF NOT EXISTS idx_keywords_frequency
                ON hot_keywords(frequency DESC);
        """)
        conn.commit()
        logger.info("Database tables created/verified")

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ── Academic Resources ──────────────────────────────

    def save_resource(self, resource: dict) -> bool:
        """Save a single resource. Returns True if inserted, False if duplicate."""
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO academic_resources
                    (id, title, authors, year, source, source_db, abstract, doi,
                     citations, is_core, keywords, url, full_text_hash,
                     crawled_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                resource.get("id", str(uuid.uuid4())),
                resource["title"],
                resource.get("authors", ""),
                resource.get("year", ""),
                resource.get("source", ""),
                resource["source_db"],
                resource.get("abstract", ""),
                resource.get("doi", ""),
                resource.get("citations", 0),
                int(resource.get("is_core", False)),
                resource.get("keywords", "[]"),
                resource.get("url", ""),
                resource.get("full_text_hash", ""),
                resource.get("crawled_at", datetime.now().isoformat()),
                resource.get("updated_at", datetime.now().isoformat()),
            ))
            conn.commit()
            return conn.total_changes > 0
        except sqlite3.IntegrityError:
            return False

    def save_resources_batch(self, resources: list[dict]) -> int:
        """Batch save resources. Returns the number of newly inserted rows."""
        conn = self._get_conn()
        inserted = 0
        for r in resources:
            try:
                cursor = conn.execute("""
                    INSERT OR IGNORE INTO academic_resources
                        (id, title, authors, year, source, source_db, abstract, doi,
                         citations, is_core, keywords, url, full_text_hash,
                         crawled_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    r.get("id", str(uuid.uuid4())),
                    r["title"],
                    r.get("authors", ""),
                    r.get("year", ""),
                    r.get("source", ""),
                    r["source_db"],
                    r.get("abstract", ""),
                    r.get("doi", ""),
                    r.get("citations", 0),
                    int(r.get("is_core", False)),
                    r.get("keywords", "[]"),
                    r.get("url", ""),
                    r.get("full_text_hash", ""),
                    r.get("crawled_at", datetime.now().isoformat()),
                    r.get("updated_at", datetime.now().isoformat()),
                ))
                if cursor.rowcount > 0:
                    inserted += 1
            except sqlite3.IntegrityError:
                continue
        conn.commit()
        return inserted

    def search_resources(
        self, query: str, source_db: Optional[str] = None, limit: int = 20
    ) -> list[dict]:
        """Search resources by title/abstract keyword match."""
        conn = self._get_conn()
        sql = """
            SELECT * FROM academic_resources
            WHERE (title LIKE ? OR abstract LIKE ?)
        """
        params: list = [f"%{query}%", f"%{query}%"]
        if source_db:
            sql += " AND source_db = ?"
            params.append(source_db)
        sql += " ORDER BY citations DESC, crawled_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_recent_resources(
        self, source_db: Optional[str] = None, limit: int = 50
    ) -> list[dict]:
        """Get recently crawled resources."""
        conn = self._get_conn()
        sql = "SELECT * FROM academic_resources"
        params: list = []
        if source_db:
            sql += " WHERE source_db = ?"
            params.append(source_db)
        sql += " ORDER BY crawled_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_resource_count(self, source_db: Optional[str] = None) -> int:
        """Get total resource count."""
        conn = self._get_conn()
        if source_db:
            row = conn.execute(
                "SELECT COUNT(*) FROM academic_resources WHERE source_db = ?",
                (source_db,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM academic_resources"
            ).fetchone()
        return row[0] if row else 0

    def get_all_resources_for_index(self) -> list[dict]:
        """Get all resources for RAG index building."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM academic_resources ORDER BY crawled_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    # ── Crawl Logs ──────────────────────────────────────

    def log_crawl(self, log: dict):
        """Record a crawl task log."""
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO crawl_logs
                (id, source_db, task_type, status, items_found, items_saved,
                 error_msg, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log.get("id", str(uuid.uuid4())),
            log["source_db"],
            log["task_type"],
            log["status"],
            log.get("items_found", 0),
            log.get("items_saved", 0),
            log.get("error_msg", ""),
            log.get("started_at", datetime.now().isoformat()),
            log.get("finished_at", ""),
        ))
        conn.commit()

    def update_crawl_log(self, log_id: str, **kwargs):
        """Update a crawl log entry."""
        conn = self._get_conn()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [log_id]
        conn.execute(f"UPDATE crawl_logs SET {sets} WHERE id = ?", values)
        conn.commit()

    def get_crawl_logs(
        self, source_db: Optional[str] = None, limit: int = 20
    ) -> list[dict]:
        """Get recent crawl logs."""
        conn = self._get_conn()
        sql = "SELECT * FROM crawl_logs"
        params: list = []
        if source_db:
            sql += " WHERE source_db = ?"
            params.append(source_db)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_latest_crawl_status(self) -> dict:
        """Get the latest crawl status for each source."""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT source_db, status, items_found, items_saved,
                   started_at, finished_at, error_msg
            FROM crawl_logs
            WHERE id IN (
                SELECT id FROM crawl_logs c2
                WHERE c2.source_db = crawl_logs.source_db
                ORDER BY started_at DESC LIMIT 1
            )
        """).fetchall()
        result = {}
        for row in rows:
            r = dict(row)
            result[r["source_db"]] = r
        return result

    # ── Hot Keywords ────────────────────────────────────

    def upsert_keyword(self, keyword: str, source_db: str):
        """Insert or update a keyword's frequency."""
        conn = self._get_conn()
        now = datetime.now().isoformat()
        conn.execute("""
            INSERT INTO hot_keywords (id, keyword, frequency, source_db, last_seen)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(keyword, source_db) DO UPDATE SET
                frequency = frequency + 1,
                last_seen = ?
        """, (str(uuid.uuid4()), keyword, source_db, now, now))
        conn.commit()

    def upsert_keywords_batch(self, keywords: list[str], source_db: str):
        """Batch upsert keywords."""
        for kw in keywords:
            self.upsert_keyword(kw, source_db)

    def get_hot_keywords(self, limit: int = 20) -> list[dict]:
        """Get top keywords by frequency."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM hot_keywords ORDER BY frequency DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    # ── Data Cleanup ────────────────────────────────────

    def cleanup_old_data(self, days: int = 30) -> int:
        """Delete resources older than the specified number of days."""
        conn = self._get_conn()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = conn.execute(
            "DELETE FROM academic_resources WHERE crawled_at < ?", (cutoff,)
        )
        conn.execute(
            "DELETE FROM crawl_logs WHERE started_at < ?", (cutoff,)
        )
        conn.commit()
        deleted = cursor.rowcount
        logger.info(f"Cleaned up {deleted} resources older than {days} days")
        return deleted


# Singleton instance
_db_service: Optional[DatabaseService] = None


def get_db_service() -> DatabaseService:
    global _db_service
    if _db_service is None:
        _db_service = DatabaseService()
        _db_service.init_db()
    return _db_service
