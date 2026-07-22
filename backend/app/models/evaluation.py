"""Evaluation models."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EvaluationDataset(Base):
    """评测数据集表。"""

    __tablename__ = "evaluation_datasets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="数据集ID",
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属知识库ID",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="数据集名称",
    )
    questions: Mapped[list] = mapped_column(
        JSONB,
        default=lambda: [],
        nullable=False,
        comment="问题列表",
    )
    ground_truths: Mapped[list] = mapped_column(
        JSONB,
        default=lambda: [],
        nullable=False,
        comment="标准答案与相关片段ID列表",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="创建用户ID",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="创建时间",
    )


class EvaluationTask(Base):
    """评测任务表。"""

    __tablename__ = "evaluation_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="任务ID",
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_datasets.id", ondelete="CASCADE"),
        nullable=False,
        comment="数据集ID",
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        comment="评测目标知识库ID",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        comment="状态：pending/running/completed/failed",
    )
    metrics: Mapped[list] = mapped_column(
        JSONB,
        default=lambda: [],
        nullable=False,
        comment="待评测指标列表",
    )
    results: Mapped[dict] = mapped_column(
        JSONB,
        default=lambda: {},
        nullable=False,
        comment="评测结果",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="创建用户ID",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="创建时间",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="完成时间",
    )


class EvaluationQuestionRun(Base):
    """单个问题的执行单元——细粒度调度、断点续测、暂停/恢复基于此表。"""

    __tablename__ = "evaluation_question_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="问题执行ID",
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属评测任务",
    )
    question_index: Mapped[int] = mapped_column(
        nullable=False,
        comment="问题在数据集中的下标（0-based）",
    )
    question: Mapped[str] = mapped_column(
        String(2000),
        nullable=False,
        comment="问题文本",
    )
    ground_truth: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
        comment="ground_truth dict（chunk_ids / answer）",
    )
    # pending / running / completed / failed / skipped / paused
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
        comment="状态",
    )
    retrieved_chunk_ids: Mapped[list] = mapped_column(
        JSONB,
        default=lambda: [],
        nullable=False,
        comment="检索到的 chunk id 列表",
    )
    generated_answer: Mapped[str | None] = mapped_column(
        nullable=True,
        comment="生成的答案",
    )
    metrics: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
        comment="每个指标的得分",
    )
    error: Mapped[str | None] = mapped_column(
        String(2000),
        nullable=True,
        comment="失败原因",
    )
    attempts: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        comment="尝试次数",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
