"""RAG index builder task — rebuilds ChromaDB from SQLite."""

import structlog

logger = structlog.get_logger(__name__)


def rebuild_rag_index() -> dict:
    """Rebuild the entire RAG vector index from the SQLite database.

    This is a synchronous function called from Celery tasks.
    """
    try:
        from src.backend.services.db_service import get_db_service
        from src.backend.services.vector_service import VectorService

        db = get_db_service()
        vector = VectorService()

        # Initialize vector service
        success = vector.init()
        if not success:
            logger.error("Failed to initialize vector service for RAG rebuild")
            return {"success": False, "error": "Vector service initialization failed"}

        # Rebuild index
        count = vector.rebuild_from_db(db)
        logger.info(f"RAG index rebuilt with {count} documents")

        return {"success": True, "documents_indexed": count}

    except Exception as e:
        logger.error(f"RAG index rebuild failed: {e}")
        return {"success": False, "error": str(e)}
