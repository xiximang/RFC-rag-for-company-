"""Query cache model for caching retrieval results with security-level isolation."""
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# pgvector 类型用于 query_embedding
class QueryCache(Base):
    """缓存高频查询的检索结果，支持安全等级隔离和 freshness 自动失效。

    五级兼容：
    - owner_security_level 确保低权限用户不会命中高权限缓存（P4）。
    - best_answer 写入时已过 L5 降级（P5）。
    - best_chunk_ids / best_answer 来自已穿透的结果，不反查原文（P1/P2）。
    """

    __tablename__ = "query_cache"
    __allow_unmapped__ = True

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    query_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    query_keywords = mapped_column(JSONB, nullable=True)
    best_chunk_ids = mapped_column(JSONB, nullable=False)
    best_rerank_order = mapped_column(JSONB, nullable=False)
    best_answer: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed_count: Mapped[int] = mapped_column(Integer, default=1)
    owner_security_level: Mapped[Optional[str]] = mapped_column(
        String(8), nullable=False
    )
    source_doc_ids = mapped_column(JSONB, nullable=True)
    last_hit_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
