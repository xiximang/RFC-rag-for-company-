"""Message models for multi-turn chat."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Message(Base):
    """消息表：保存会话中的用户/助手消息。"""

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="消息ID",
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属会话ID",
    )
    role: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="角色：user/assistant",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="消息内容",
    )
    sources: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
        comment="消息引用的来源块",
    )
    feedback_rating: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="反馈评分：1 点赞，-1 点踩，None 未评价",
    )
    feedback_comment: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="反馈备注",
    )
    # 工程师反馈与上下文工程：候选落库 + 候选排序反馈（仅新增字段，不影响现有 feedback 路径）
    candidates: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Rerank 候选列表（已过五级穿透，content 为降级后值）",
    )
    candidate_feedback: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="工程师对候选的排序/评分反馈",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="创建时间",
    )
