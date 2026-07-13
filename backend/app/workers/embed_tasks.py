"""Celery tasks for chunk embedding and index persistence.

``embed_chunks`` fetches pending chunks from PostgreSQL, calls the user-provided
embedding HTTP service, writes dense vectors to Milvus and full-text records to
Meilisearch, then updates each chunk with ``vector_id`` and ``status=active``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models.chunk import Chunk
from app.models.document import Document
from app.retrieval.embedding_client import embedding_client
from app.retrieval.meilisearch_client import MeilisearchFulltextStore
from app.retrieval.vector_store import get_vector_store
from app.workers.celery_app import celery_app

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


class _ChunkWrapper:
    """Lightweight adapter exposing the fields expected by vector/fulltext stores."""

    def __init__(
        self,
        chunk: Chunk,
        doc: Document,
        kb_id: UUID | None,
    ) -> None:
        self._chunk = chunk
        self._doc = doc
        self._kb_id = kb_id

    def __getattr__(self, name: str) -> Any:
        if name == "id":
            return str(self._chunk.id)
        if name == "chunk_id":
            return str(self._chunk.id)
        if name == "doc_id":
            return str(self._chunk.doc_id)
        if name == "kb_id":
            return str(self._kb_id) if self._kb_id else ""
        if name == "modality":
            return self._chunk.modality or "text"
        if name == "doc_acl_version":
            return ""
        if name == "max_keyword_level":
            meta = self._chunk.metadata_ or {}
            level = meta.get("max_keyword_level_value") or meta.get("max_keyword_level", 0)
            if isinstance(level, str):
                from app.pipelines.keyword_annotator import LEVEL_ORDER
                return LEVEL_ORDER.get(level, 0)
            return level
        if name == "tags":
            info = self._doc.processing_info or {}
            return info.get("tags", []) or []
        if name == "created_by":
            return str(self._doc.created_by) if self._doc.created_by else ""
        if name == "status":
            # Chunks are only inserted into vector stores once embedding is
            # complete, so they are immediately searchable/active.
            return "active"
        if name == "text":
            return self._chunk.content
        if name == "title":
            return self._doc.filename
        return getattr(self._chunk, name)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def embed_chunks(self, chunk_ids: List[str]) -> Dict[str, Any]:
    """Embed a batch of chunks and persist them to vector/fulltext stores.

    In lightweight EAGER mode we must not block the FastAPI event loop;
    dispatch as a fire-and-forget task instead.
    """
    logger.info("Embedding %s chunks (retry=%s)", len(chunk_ids), self.request.retries)
    try:
        running_loop = asyncio.get_event_loop()
        if running_loop.is_running():
            asyncio.ensure_future(_embed_chunks_async_safe(chunk_ids))
            return {"scheduled": True, "chunk_count": len(chunk_ids)}
        else:
            return asyncio.run(_embed_chunks_async(chunk_ids))
    except RuntimeError:
        return asyncio.run(_embed_chunks_async(chunk_ids))


async def _embed_chunks_async_safe(chunk_ids: List[str]) -> Dict[str, Any]:
    """Fire-and-forget wrapper for EAGER mode."""
    try:
        return await _embed_chunks_async(chunk_ids)
    except Exception:
        logger.exception("Background embed failed for chunk_ids=%s", chunk_ids)
        return {}


async def _embed_chunks_async(chunk_ids: List[str]) -> Dict[str, Any]:
    vector_store = get_vector_store()
    meili = MeilisearchFulltextStore()

    session = _create_async_session()
    try:
        stmt = select(Chunk).where(Chunk.id.in_([UUID(cid) for cid in chunk_ids]))
        result = await session.execute(stmt)
        chunks = list(result.scalars().all())

        if not chunks:
            logger.warning("No chunks found for ids %s", chunk_ids)
            return {"embedded": 0}

        # Group by document to load parent documents efficiently.
        doc_ids = {c.doc_id for c in chunks}
        doc_stmt = select(Document).where(Document.id.in_(doc_ids))
        doc_result = await session.execute(doc_stmt)
        documents = {d.id: d for d in doc_result.scalars().all()}

        # Prepare payloads for the embedding service.
        payloads = []
        for chunk in chunks:
            payload: Dict[str, Any] = {
                "id": str(chunk.id),
                "content": chunk.content,
                "modality": chunk.modality or "text",
            }
            if chunk.modality in ("image", "video"):
                frame_path = (chunk.position_info or {}).get("frame_path")
                if frame_path:
                    payload["image_path"] = frame_path
            payloads.append(payload)

        # Use the OpenAI-compatible embedding client (supports external APIs).
        texts = [p["content"] for p in payloads]
        embeddings = await embedding_client.embed_batch(texts)
        if len(embeddings) != len(chunks):
            raise RuntimeError(
                f"Embedding count mismatch: expected {len(chunks)}, got {len(embeddings)}"
            )

        # Build wrappers for index stores.
        wrapped_chunks = []
        for chunk in chunks:
            doc = documents.get(chunk.doc_id)
            wrapped = _ChunkWrapper(chunk, doc, doc.kb_id if doc else None)
            wrapped_chunks.append(wrapped)

        # Insert into the configured vector store.
        vector_ids: List[str] = []
        if vector_store.is_available:
            try:
                vector_ids = vector_store.insert_chunks(
                    wrapped_chunks,
                    embeddings,
                )
                logger.info(
                    "Inserted %s chunks into %s",
                    len(vector_ids),
                    vector_store.backend_name,
                )
            except Exception as exc:
                logger.exception("%s insert failed: %s", vector_store.backend_name, exc)

        # Index full-text in Meilisearch.
        if meili.is_available:
            try:
                meili.index_chunks(wrapped_chunks)
                logger.info("Indexed %s chunks in Meilisearch", len(wrapped_chunks))
            except Exception as exc:
                logger.exception("Meilisearch index failed: %s", exc)

        # Update chunk records.
        for idx, chunk in enumerate(chunks):
            chunk.status = "active"
            if idx < len(vector_ids):
                chunk.vector_id = vector_ids[idx]

        await session.commit()

        # Mark documents as indexed once all their chunks are active.
        doc_ids = {c.doc_id for c in chunks}
        for doc_id in doc_ids:
            pending_count = await session.scalar(
                select(func.count(Chunk.id)).where(
                    Chunk.doc_id == doc_id,
                    Chunk.status != "active",
                )
            )
            if pending_count == 0:
                doc = await session.get(Document, doc_id)
                if doc is not None:
                    doc.status = "indexed"
                    doc.processing_info = {
                        **(doc.processing_info or {}),
                        "stage": "completed",
                        "message": "Embedding finished",
                    }
        await session.commit()
    finally:
        await session.close()

    return {"embedded": len(chunks)}


