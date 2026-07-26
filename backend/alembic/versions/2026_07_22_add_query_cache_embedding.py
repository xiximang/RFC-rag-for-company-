"""add query_embedding vector column and indexes to query_cache

Revision ID: 20260722_qcache_v2
Revises: 20260722_qcache
Create Date: 2026-07-22 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260722_qcache_v2"
down_revision: Union[str, None] = "20260722_qcache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # 1024 维：与 text-embedding-3-large + HNSW 余弦距离一致
    # (cache_matcher.py:99 与 feedback.py:184 都按 1024 写入)
    op.execute("ALTER TABLE query_cache ADD COLUMN query_embedding vector(1024)")
    op.create_index("idx_qc_embedding", "query_cache", ["query_embedding"], postgresql_using="ivfflat", postgresql_with={"lists": 100})
    op.create_index("idx_qc_keywords", "query_cache", ["query_keywords"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("idx_qc_embedding", table_name="query_cache")
    op.drop_index("idx_qc_keywords", table_name="query_cache")
    op.drop_column("query_cache", "query_embedding")
