"""pgvector-backed vector store implementation (sync SQLAlchemy + psycopg2)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Union

from app.config import settings
from app.retrieval.filters import VectorFilter
from app.retrieval.vector_store import BaseVectorStore, ChunkT

try:
    from pgvector.sqlalchemy import Vector
    from sqlalchemy import and_, create_engine, delete, select, text
    from sqlalchemy.orm import Session

    from app.database import Base
    from app.models.vector import ImageFrameVector, TextChunkVector

    _PGVECTOR_AVAILABLE = True
except Exception as exc:  # pragma: no cover
    Vector = None  # type: ignore
    create_engine = None  # type: ignore
    Session = None  # type: ignore
    Base = None  # type: ignore
    TextChunkVector = None  # type: ignore
    ImageFrameVector = None  # type: ignore
    _PGVECTOR_AVAILABLE = False
    logging.getLogger(__name__).warning("pgvector/psycopg2 is not installed: %s", exc)

logger = logging.getLogger(__name__)


class PGVectorStore(BaseVectorStore):
    """Concrete vector store backed by PostgreSQL + pgvector.

    Uses synchronous SQLAlchemy wrapped in ``asyncio.to_thread`` by async
    callers. If PostgreSQL or the pgvector extension is unavailable the store
    marks itself unavailable and every method returns a safe fallback.
    """

    backend_name = "pgvector"

    TEXT_DIM = 1024
    IMAGE_DIM = 512

    def __init__(self) -> None:
        self._available = False
        self._engine = None

        if not _PGVECTOR_AVAILABLE:
            logger.warning("pgvector is not installed; PGVectorStore is unavailable")
            return

        try:
            self._engine = create_engine(
                settings.sync_database_url,
                echo=settings.DEBUG,
                future=True,
                pool_pre_ping=True,
            )
            self._ensure_extension_and_tables()
            self._available = True
            logger.info("PGVectorStore connected to PostgreSQL")
        except Exception as exc:
            self._available = False
            logger.warning("Failed to initialize PGVectorStore: %s", exc)

    # ------------------------------------------------------------------
    # Connection / availability
    # ------------------------------------------------------------------
    @property
    def is_available(self) -> bool:
        return self._available

    def _ensure_extension_and_tables(self) -> None:
        """Best-effort creation of the pgvector extension and tables."""
        if self._engine is None:
            return

        with self._engine.connect() as conn:
            # Check whether the vector extension is installed/available.
            result = conn.execute(
                text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
            )
            if not result.scalar():
                logger.warning("pgvector extension is not available in PostgreSQL")
                raise RuntimeError("pgvector extension is not available")

            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()

        # Create tables/indexes if they do not exist.
        Base.metadata.create_all(
            self._engine,
            tables=[TextChunkVector.__table__, ImageFrameVector.__table__],
            checkfirst=True,
        )

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------
    def create_collection(self, collection_name: str, **kwargs: Any) -> bool:
        if not self._available:
            logger.warning("PGVector unavailable; cannot create collection %s", collection_name)
            return False

        try:
            Base.metadata.create_all(
                self._engine,
                tables=[TextChunkVector.__table__, ImageFrameVector.__table__],
                checkfirst=True,
            )
            return True
        except Exception as exc:
            logger.exception("Failed to create pgvector tables: %s", exc)
            return False

    def drop_collection(self, collection_name: str) -> bool:
        if not self._available:
            logger.warning("PGVector unavailable; cannot drop collection %s", collection_name)
            return False

        try:
            if collection_name in ("text", TextChunkVector.__tablename__):
                TextChunkVector.__table__.drop(self._engine, checkfirst=True)
            elif collection_name in ("image", ImageFrameVector.__tablename__):
                ImageFrameVector.__table__.drop(self._engine, checkfirst=True)
            else:
                # Drop both when collection_name is unknown/generic.
                ImageFrameVector.__table__.drop(self._engine, checkfirst=True)
                TextChunkVector.__table__.drop(self._engine, checkfirst=True)
            return True
        except Exception as exc:
            logger.exception("Failed to drop pgvector tables: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Generic CRUD on raw records
    # ------------------------------------------------------------------
    def insert(self, collection_name: str, records: List[Dict[str, Any]]) -> List[str]:
        if not self._available:
            logger.warning("PGVector unavailable; skipping insert into %s", collection_name)
            return []

        model = self._resolve_model(collection_name)
        if model is None:
            logger.warning("Unknown pgvector collection: %s", collection_name)
            return []

        if not records:
            return []

        try:
            with Session(self._engine) as session:
                session.bulk_insert_mappings(model, records)
                session.commit()
                return [str(r.get("id", "")) for r in records]
        except Exception as exc:
            logger.exception("Insert into %s failed: %s", collection_name, exc)
            return []

    def search(
        self,
        collection_name: str,
        query_vector: List[float],
        filter_expr: str = "",
        top_k: int = 10,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Vector ANN search using cosine distance (pgvector ``<=>``)."""
        model = self._resolve_model(collection_name)
        if model is None or not self._available:
            return []
        return self._search_model(model, query_vector, filter_expr, top_k)

    def update(
        self,
        collection_name: str,
        pk: str,
        data: Dict[str, Any],
    ) -> bool:
        if not self._available:
            logger.warning("PGVector unavailable; skipping update")
            return False

        model = self._resolve_model(collection_name)
        if model is None:
            return False

        try:
            with Session(self._engine) as session:
                session.query(model).filter_by(id=pk).update(data)
                session.commit()
                return True
        except Exception as exc:
            logger.exception("Update in %s failed: %s", collection_name, exc)
            return False

    def delete_by_doc_id(
        self,
        doc_id: str,
        collection_name: str | None = None,
    ) -> bool:
        if not self._available:
            logger.warning("PGVector unavailable; skipping delete_by_doc_id")
            return False

        targets = [TextChunkVector, ImageFrameVector]
        if collection_name:
            model = self._resolve_model(collection_name)
            targets = [model] if model else []

        success = True
        for model in targets:
            if model is None:
                continue
            try:
                with Session(self._engine) as session:
                    session.execute(delete(model).where(model.doc_id == doc_id))
                    session.commit()
                    logger.info("Deleted records for doc_id=%s from %s", doc_id, model.__tablename__)
            except Exception as exc:
                logger.exception("Failed to delete doc_id=%s from %s: %s", doc_id, model.__tablename__, exc)
                success = False

        return success

    # ------------------------------------------------------------------
    # Chunk-specific helpers
    # ------------------------------------------------------------------
    def insert_chunks(
        self,
        chunks: List[ChunkT],
        embeddings: List[List[float]],
    ) -> List[str]:
        """Insert document chunks into the text_chunk_vectors table."""
        if not self._available:
            logger.warning("PGVector unavailable; skipping insert_chunks")
            return []

        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) must have the same length"
            )

        records: List[Dict[str, Any]] = []
        for chunk, vector in zip(chunks, embeddings):
            records.append(
                {
                    "id": str(chunk.id),
                    "chunk_id": str(chunk.chunk_id),
                    "doc_id": str(chunk.doc_id),
                    "kb_id": str(chunk.kb_id) if chunk.kb_id else "",
                    "modality": str(chunk.modality) if chunk.modality else "text",
                    "doc_acl_version": str(chunk.doc_acl_version)
                    if chunk.doc_acl_version
                    else "",
                    "max_keyword_level": int(chunk.max_keyword_level)
                    if chunk.max_keyword_level is not None
                    else 0,
                    "tags": list(chunk.tags) if chunk.tags else [],
                    "created_by": str(chunk.created_by) if chunk.created_by else "",
                    "status": str(chunk.status) if chunk.status else "active",
                    "embedding": vector,
                }
            )

        return self.insert(TextChunkVector.__tablename__, records)

    def search_text(
        self,
        query_embedding: List[float],
        filter_obj_or_expr: Union[VectorFilter, str] = "",
        top_k: int = 10,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Dense-vector search over the text chunk table."""
        return self._search_model(
            TextChunkVector,
            query_embedding,
            filter_obj_or_expr,
            top_k,
        )

    def search_image(
        self,
        image_embedding: List[float],
        filter_obj_or_expr: Union[VectorFilter, str] = "",
        top_k: int = 10,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Dense-vector search over the image frame table."""
        return self._search_model(
            ImageFrameVector,
            image_embedding,
            filter_obj_or_expr,
            top_k,
        )

    # ------------------------------------------------------------------
    # Internal utilities
    # ------------------------------------------------------------------
    def _resolve_model(self, collection_name: str):
        name = collection_name.lower()
        if name in ("text", TextChunkVector.__tablename__):
            return TextChunkVector
        if name in ("image", ImageFrameVector.__tablename__):
            return ImageFrameVector
        return None

    def _filter_clauses(
        self,
        model: Any,
        filter_obj_or_expr: Union[VectorFilter, str],
    ) -> Any:
        """Return SQLAlchemy clauses for a VectorFilter; strings are not supported."""
        if isinstance(filter_obj_or_expr, VectorFilter):
            clauses = filter_obj_or_expr.to_sqlalchemy(model)
            return and_(*clauses) if clauses else None

        if filter_obj_or_expr:
            logger.warning(
                "PGVectorStore received a string filter expression and cannot parse it; "
                "filter will be ignored."
            )
        return None

    def _search_model(
        self,
        model: Any,
        query_vector: List[float],
        filter_obj_or_expr: Union[VectorFilter, str],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        if not self._available:
            logger.warning("PGVector unavailable; returning empty search results")
            return []

        try:
            distance = model.embedding.cosine_distance(query_vector)
            stmt = (
                select(
                    model,
                    distance.label("score"),
                )
                .order_by(distance)
                .limit(top_k)
            )

            where_clause = self._filter_clauses(model, filter_obj_or_expr)
            if where_clause is not None:
                stmt = stmt.where(where_clause)

            with Session(self._engine) as session:
                rows = session.execute(stmt).all()
                return [self._row_to_hit(row, model) for row in rows]
        except Exception as exc:
            logger.exception("PGVector search failed: %s", exc)
            return []

    @staticmethod
    def _row_to_hit(row: Any, model: Any) -> Dict[str, Any]:
        """Convert a SQLAlchemy result row into the Milvus-like hit dict."""
        entity, score = row
        hit: Dict[str, Any] = {
            "id": entity.id,
            "chunk_id": entity.chunk_id,
            "doc_id": entity.doc_id,
            "kb_id": entity.kb_id,
            "score": 1.0 - float(score) if score is not None else 0.0,
        }

        if model is TextChunkVector:
            hit.update(
                {
                    "modality": entity.modality,
                    "doc_acl_version": entity.doc_acl_version,
                    "max_keyword_level": entity.max_keyword_level,
                    "tags": list(entity.tags) if entity.tags else [],
                    "created_by": entity.created_by,
                    "status": entity.status,
                }
            )
        else:
            hit.update(
                {
                    "frame_index": entity.frame_index,
                    "image_url": entity.image_url,
                }
            )

        return hit
