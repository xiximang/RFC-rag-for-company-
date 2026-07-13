"""Celery tasks for document ingestion.

The main task ``process_document`` downloads the original file from MinIO,
parses it with the correct pipeline, creates ``Chunk`` records, annotates
them with keywords, and enqueues ``embed_chunks`` to generate vectors.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.pipelines.factory import PipelineFactory
from app.services.keyword_service import KeywordService
from app.services.sensitive_info_service import SensitiveInfoService
from app.workers.celery_app import celery_app
from app.storage import get_file_storage

logger = logging.getLogger(__name__)


def _create_async_session() -> AsyncSession:
    """Create a fresh async engine bound to the current process.

    Creating the engine inside the task avoids asyncpg connections being
    inherited across Celery prefork worker forks.
    """
    engine = create_async_engine(
        settings.async_database_url,
        echo=False,
        future=True,
        poolclass=NullPool,
    )
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_document(self, doc_id: str) -> Dict[str, Any]:
    """Celery task that ingests a single document end-to-end.

    Lightweight mode (EAGER=true) runs inside the FastAPI request handler.
    We schedule the async coroutine on the running event loop using
    ``create_task`` and return immediately to avoid deadlocking the loop.
    """
    logger.info("Starting ingest for document %s", doc_id)
    try:
        running_loop = asyncio.get_event_loop()
        if running_loop.is_running():
            # EAGER mode inside an async context: fire-and-forget on the
            # running loop. Don't wait on the result - that would deadlock.
            asyncio.ensure_future(_process_document_async_safe(doc_id))
            return {"scheduled": True, "doc_id": doc_id}
        else:
            return asyncio.run(_process_document_async(doc_id))
    except RuntimeError:
        # No loop yet (e.g. standalone Celery worker)
        return asyncio.run(_process_document_async(doc_id))


async def _process_document_async_safe(doc_id: str) -> Dict[str, Any]:
    """Fire-and-forget wrapper around ``_process_document_async`` for EAGER mode.

    Used by ``BackgroundTasks`` so that ingest failures don't bubble back to
    the HTTP client. Status updates still happen through the same DB session
    used by the pipeline.
    """
    try:
        return await _process_document_async(doc_id)
    except Exception:
        logger.exception("Background ingest failed for document %s", doc_id)
        return {}


async def _process_document_async(doc_id: str) -> Dict[str, Any]:
    session = _create_async_session()
    chunk_ids: List[str] = []
    try:
        document = await session.get(Document, UUID(doc_id))
        if document is None:
            raise ValueError(f"Document {doc_id} not found")

        # Update status to processing.
        document.status = "processing"
        document.processing_info = {
            **(document.processing_info or {}),
            "stage": "downloading",
            "message": "Downloading source file",
        }
        await session.commit()

        # Resolve file path.
        file_path = await _download_document(document)

        # Determine pipeline.
        file_type = _resolve_file_type(document)
        pipeline = PipelineFactory.get_pipeline(file_type)

        document.processing_info = {
            **(document.processing_info or {}),
            "stage": "parsing",
            "pipeline": pipeline.__class__.__name__,
        }
        await session.commit()

        # Parse chunks.
        raw_chunks = pipeline.process(
            str(file_path),
            doc_id,
            metadata=dict(document.metadata_ or {}),
        )

        document.processing_info = {
            **(document.processing_info or {}),
            "stage": "annotating",
            "chunks_parsed": len(raw_chunks),
        }
        await session.commit()

        if not raw_chunks:
            document.status = "indexed"
            document.processing_info = {
                **(document.processing_info or {}),
                "stage": "completed",
                "message": "No chunks produced",
            }
            await session.commit()
            return {"doc_id": doc_id, "chunks": 0}

        # Keyword annotation and sensitive information scanning.
        keyword_svc = KeywordService(session)
        sensitive_svc = SensitiveInfoService(session)
        chunk_records: List[Chunk] = []
        for idx, raw in enumerate(raw_chunks):
            chunk = Chunk(
                doc_id=UUID(doc_id),
                content=raw["content"],
                modality=raw.get("modality", "text"),
                chunk_index=raw.get("chunk_index", idx),
                position_info=raw.get("position_info") or {},
                metadata_={},
                status="pending",
                # 2026-07-02: 统一使用 chinese 配置支持中英文分词（之前用 simple 导致索引和查询分词不一致）
                # content_tsv=func.to_tsvector("simple", raw["content"]),
                content_tsv=func.to_tsvector("chinese", raw["content"]),
            )
            await keyword_svc.annotate_chunk(chunk)
            chunk_meta = {
                **(raw.get("metadata") or {}),
                **(chunk.metadata_ or {}),
            }
            chunk.metadata_ = chunk_meta
            chunk_records.append(chunk)

        # Run PII / keyword / NER detection and persist findings in metadata.
        await sensitive_svc.scan_chunks(chunk_records)
        high_severity_count = sum(
            1
            for c in chunk_records
            if (c.metadata_ or {}).get("max_builtin_severity") in {"L3", "L4"}
        )

        session.add_all(chunk_records)
        await session.commit()

        chunk_ids = [str(c.id) for c in chunk_records]

        # Update document status before embedding.
        document.status = "processing"
        document.processing_info = {
            **(document.processing_info or {}),
            "stage": "embedding_queued",
            "chunks_created": len(chunk_records),
            "chunk_ids": chunk_ids,
            "sensitive_scan": {
                "chunks_scanned": len(chunk_records),
                "chunks_with_findings": sum(
                    1 for c in chunk_records if (c.metadata_ or {}).get("has_sensitive_findings")
                ),
                "high_severity_chunks": high_severity_count,
            },
        }
        await session.commit()
    finally:
        await session.close()

    # Enqueue embedding task after the transaction is committed.
    from app.workers.embed_tasks import embed_chunks

    embed_chunks.delay(chunk_ids)
    logger.info("Enqueued embedding for %s chunks of document %s", len(chunk_ids), doc_id)
    return {"doc_id": doc_id, "chunks": len(chunk_ids)}


async def _download_document(document: Document) -> Path:
    """Download the document source to a temporary file."""
    if document.file_type == "LINK":
        # For link documents the storage_key is the URL itself.
        return Path(document.storage_key)

    if not document.storage_key:
        raise ValueError(f"Document {document.id} has no storage_key")

    storage = get_file_storage()
    suffix = Path(document.filename).suffix or ".bin"
    temp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    temp_path = Path(temp_file.name)
    temp_file.close()

    try:
        data = await storage.download(document.storage_key)
        await asyncio.to_thread(temp_path.write_bytes, data)
    except Exception as exc:
        raise RuntimeError(f"Failed to download {document.storage_key}: {exc}") from exc

    return temp_path


def _resolve_file_type(document: Document) -> str:
    if document.file_type == "LINK":
        return "link"
    return (document.file_type or Path(document.filename).suffix).lower().lstrip(".")


async def _mark_failed(
    doc_id: str, error: str, extra: Dict[str, Any] | None = None
) -> None:
    session = _create_async_session()
    try:
        document = await session.get(Document, UUID(doc_id))
        if document is None:
            return
        document.status = "failed"
        document.processing_info = {
            **(document.processing_info or {}),
            "stage": "failed",
            "error": error,
            **(extra or {}),
        }
        await session.commit()
    finally:
        await session.close()
