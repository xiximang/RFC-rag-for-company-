"""add candidates and candidate_feedback to messages

Revision ID: 20260721_msg_cands
Revises: 20260624_add_pgvector_vectors
Create Date: 2026-07-21 00:00:00.000000

仅新增两列，不改不删现有列。candidates 存的是已过五级穿透的降级后候选，
candidate_feedback 存工程师排序/评分反馈。downgrade 仅 DROP 本迁移新增列。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260721_msg_cands"
down_revision = "20260624_add_pgvector_vectors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "candidates",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Rerank 候选列表（已过五级穿透，content 为降级后值）",
        ),
    )
    op.add_column(
        "messages",
        sa.Column(
            "candidate_feedback",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="工程师对候选的排序/评分反馈",
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "candidate_feedback")
    op.drop_column("messages", "candidates")
