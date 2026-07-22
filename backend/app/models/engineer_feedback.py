"""Engineer feedback model for candidate ranking/rating persistence."""
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EngineerFeedback(Base):
    """工程师对检索候选的排序/评分反馈，用于后续分析及缓存写入。

    五级兼容：
    - ``query_embedding`` 复用 pgvector 扩展，与 ``query_cache`` 同维。
    - ``reviewer_security_level`` 记录反馈者的安全等级，下游缓存匹配可据此隔离。
    """

    __tablename__ = "engineer_feedback"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    message_id = Column(
        UUID(as_uuid=True), ForeignKey("messages.id"), nullable=False, index=True
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    chosen_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    ranking = Column(JSONB, nullable=False)  # List[int]
    ratings = Column(JSONB, nullable=True)  # Optional[Dict[int,int]]
    action: Mapped[Optional[str]] = mapped_column(
        String(32), default="rank"
    )  # rank | approve | edit | force_refresh
    edited_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewer_security_level: Mapped[Optional[str]] = mapped_column(
        String(8), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
