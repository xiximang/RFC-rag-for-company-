"""add query_cache table

Revision ID: 20260722_qcache
Revises: 20260722_eng_fb
Create Date: 2026-07-22 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260722_qcache"
down_revision: Union[str, None] = "20260722_eng_fb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "query_cache",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("query_hash", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("query_keywords", JSONB, nullable=True),
        sa.Column("best_chunk_ids", JSONB, nullable=False),
        sa.Column("best_rerank_order", JSONB, nullable=False),
        sa.Column("best_answer", sa.Text, nullable=False),
        sa.Column("confirmed_count", sa.Integer, server_default="1"),
        sa.Column("owner_security_level", sa.String(8), nullable=False),
        sa.Column("source_doc_ids", JSONB, nullable=True),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("query_cache")
