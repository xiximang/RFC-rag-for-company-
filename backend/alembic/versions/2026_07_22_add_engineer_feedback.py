"""add engineer_feedback table

Revision ID: 20260722_eng_fb
Revises: 20260721_msg_cands
Create Date: 2026-07-22 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "20260722_eng_fb"
down_revision: Union[str, None] = "20260721_msg_cands"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "engineer_feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("message_id", UUID(as_uuid=True), sa.ForeignKey("messages.id"), nullable=False, index=True),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("chosen_rank", sa.Integer, nullable=False),
        sa.Column("ranking", JSONB, nullable=False),
        sa.Column("ratings", JSONB, nullable=True),
        sa.Column("action", sa.String(32), default="rank"),
        sa.Column("edited_answer", sa.Text, nullable=True),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("reviewer_security_level", sa.String(8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_ef_user", "engineer_feedback", ["user_id"])
    op.create_index("idx_ef_created", "engineer_feedback", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_ef_created", table_name="engineer_feedback")
    op.drop_index("idx_ef_user", table_name="engineer_feedback")
    op.drop_table("engineer_feedback")
