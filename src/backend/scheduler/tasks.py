"""Celery scheduled tasks for academic resource crawling and maintenance."""

import asyncio
import logging
import uuid
from datetime import datetime

from .celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from sync Celery task context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        # If there's already a running loop, create a new one in a thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)


def _get_crawler(source_db: str):
    """Get a crawler instance by source_db name."""
    from ..crawlers import CRAWLERS
    crawler_cls = CRAWLERS.get(source_db)
    if not crawler_cls:
        raise ValueError(f"Unknown source_db: {source_db}")
    return crawler_cls()


def _get_db_service():
    """Get the database service instance."""
    from ..services.db_service import get_db_service
    return get_db_service()


@celery_app.task(name="src.backend.scheduler.tasks.crawl_source", bind=True)
def crawl_source(self, source_db: str, task_type: str, count: int = 50):
    """Crawl academic resources from a specific source.

    Args:
        source_db: One of cnki, crossref, pubmed, wanfang, weipu
        task_type: One of hot, latest, keyword
        count: Number of items to crawl
    """
    log_id = str(uuid.uuid4())
    db = _get_db_service()

    # Log start
    db.log_crawl({
        "id": log_id,
        "source_db": source_db,
        "task_type": task_type,
        "status": "running",
        "started_at": datetime.now().isoformat(),
    })

    try:
        crawler = _get_crawler(source_db)

        if task_type == "hot":
            coro = crawler.crawl_hot(count)
        elif task_type == "latest":
            coro = crawler.crawl_latest(count)
        elif task_type == "keyword":
            # For keyword tasks, use default hot keywords
            coro = crawler.crawl_hot(count)
        else:
            raise ValueError(f"Unknown task_type: {task_type}")

        results = _run_async(coro)
        items_found = len(results)

        # Save to database
        items_saved = db.save_resources_batch(results)

        # Extract keywords and update hot keywords
        for r in results:
            import json
            try:
                kws = json.loads(r.get("keywords", "[]"))
                if isinstance(kws, list):
                    db.upsert_keywords_batch(kws, source_db)
            except (json.JSONDecodeError, TypeError):
                pass

        # Update log
        db.update_crawl_log(
            log_id,
            status="success",
            items_found=items_found,
            items_saved=items_saved,
            finished_at=datetime.now().isoformat(),
        )

        logger.info(
            f"[{source_db}] {task_type} crawl completed: "
            f"found={items_found}, saved={items_saved}"
        )
        return {
            "source_db": source_db,
            "task_type": task_type,
            "items_found": items_found,
            "items_saved": items_saved,
        }

    except Exception as e:
        logger.error(f"[{source_db}] {task_type} crawl failed: {e}")
        db.update_crawl_log(
            log_id,
            status="failed",
            error_msg=str(e),
            finished_at=datetime.now().isoformat(),
        )
        raise


@celery_app.task(name="src.backend.scheduler.tasks.build_rag_index")
def build_rag_index():
    """Rebuild the RAG vector index from the SQLite database."""
    from .rag_builder import rebuild_rag_index
    return rebuild_rag_index()


@celery_app.task(name="src.backend.scheduler.tasks.update_hot_keywords")
def update_hot_keywords():
    """Update hot keywords from recent crawled resources."""
    db = _get_db_service()

    # Get recent resources and extract keywords
    recent = db.get_recent_resources(limit=200)
    keyword_count = 0
    for r in recent:
        import json
        try:
            kws = json.loads(r.get("keywords", "[]"))
            if isinstance(kws, list):
                db.upsert_keywords_batch(kws, r["source_db"])
                keyword_count += len(kws)
        except (json.JSONDecodeError, TypeError):
            pass

    logger.info(f"Updated {keyword_count} keyword occurrences from {len(recent)} resources")
    return {"keywords_updated": keyword_count, "resources_scanned": len(recent)}


@celery_app.task(name="src.backend.scheduler.tasks.cleanup_old_data")
def cleanup_old_data():
    """Clean up resources older than the configured retention period."""
    from ..config import settings
    db = _get_db_service()
    deleted = db.cleanup_old_data(days=settings.CRAWL_DATA_RETENTION_DAYS)
    return {"deleted": deleted}


@celery_app.task(name="src.backend.scheduler.tasks.crawl_by_keyword")
def crawl_by_keyword(source_db: str, keyword: str, count: int = 20):
    """Manually trigger a keyword crawl for a specific source."""
    crawler = _get_crawler(source_db)
    results = _run_async(crawler.crawl_by_keyword(keyword, count))

    db = _get_db_service()
    items_saved = db.save_resources_batch(results)

    return {
        "source_db": source_db,
        "keyword": keyword,
        "items_found": len(results),
        "items_saved": items_saved,
    }
