"""SQLAlchemy ORM models for pgvector-backed vector tables.

These models exist primarily so that Alembic metadata includes the vector
schema; the ``PGVectorStore`` uses the same tables via synchronous SQLAlchemy.
"""
from __future__ import annotations

from sqlalchemy import Column, Index, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY

from app.database import Base

try:
    from pgvector.sqlalchemy import Vector

    _PGVECTOR_AVAILABLE = True
except Exception:  # pragma: no cover
    Vector = None  # type: ignore
    _PGVECTOR_AVAILABLE = False


if _PGVECTOR_AVAILABLE:

    class TextChunkVector(Base):
        """Dense vectors for document chunks (1024-dim, text-embedding-3-large)."""

        __tablename__ = "text_chunk_vectors"

        __table_args__ = (
            Index("idx_text_chunk_kb_id", "kb_id"),
            Index("idx_text_chunk_doc_id", "doc_id"),
            Index("idx_text_chunk_modality", "modality"),
            Index("idx_text_chunk_status", "status"),
            Index(
                "idx_text_chunk_embedding_hnsw",
                "embedding",
                postgresql_using="hnsw",
                postgresql_with={"m": 16, "ef_construction": 200},
                postgresql_ops={"embedding": "vector_cosine_ops"},
            ),
        )

        id = Column(String(128), primary_key=True)
        chunk_id = Column(String(128), nullable=False, index=True)
        doc_id = Column(String(128), nullable=False, index=True)
        kb_id = Column(String(128), nullable=False, index=True)
        modality = Column(String(32), nullable=False, index=True)
        doc_acl_version = Column(String(128), nullable=True)
        max_keyword_level = Column(Integer, nullable=True)
        tags = Column(ARRAY(String(64)), nullable=True)
        created_by = Column(String(128), nullable=True)
        status = Column(String(32), nullable=False, default="active")
        embedding = Column(Vector(1024), nullable=False)

    class ImageFrameVector(Base):
        """Dense vectors for image/video keyframes (512-dim by default)."""

        __tablename__ = "image_frame_vectors"

        __table_args__ = (
            Index("idx_image_frame_kb_id", "kb_id"),
            Index("idx_image_frame_doc_id", "doc_id"),
            Index(
                "idx_image_frame_embedding_hnsw",
                "embedding",
                postgresql_using="hnsw",
                postgresql_with={"m": 16, "ef_construction": 200},
                postgresql_ops={"embedding": "vector_cosine_ops"},
            ),
        )

        id = Column(String(128), primary_key=True)
        chunk_id = Column(String(128), nullable=False, index=True)
        doc_id = Column(String(128), nullable=False, index=True)
        kb_id = Column(String(128), nullable=False, index=True)
        frame_index = Column(Integer, nullable=True)
        image_url = Column(String(512), nullable=True)
        embedding = Column(Vector(512), nullable=False)
