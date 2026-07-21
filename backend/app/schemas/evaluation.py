"""Evaluation Pydantic schemas."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class GroundTruthEntry(BaseModel):
    """单条 ground truth。

    标准字段:
    - chunk_ids: 该问题对应的相关 chunk id 列表（用于 recall/mrr/ndcg 评估）
    - answer: 标准答案文本（用于 faithfulness/relevance/coherence 评估）
    - 其它任意字段透传保留，方便扩展。
    """

    chunk_ids: List[str] = Field(default_factory=list)
    answer: Optional[str] = None

    model_config = {"extra": "allow"}


class DatasetItem(BaseModel):
    """标准格式：单条数据 = {question, ground_truth, [可选 metadata]}"""

    question: str = Field(..., min_length=1)
    ground_truth: GroundTruthEntry
    metadata: Optional[Dict[str, Any]] = None

    model_config = {"extra": "ignore"}


class DatasetUploadResponse(BaseModel):
    """上传/校验接口的响应：包含校验结果与解析后的数据。"""

    valid: bool
    name: Optional[str] = None
    kb_id: Optional[UUID] = None
    item_count: int = 0
    items: List[DatasetItem] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class EvaluationDatasetCreate(BaseModel):
    """v1 数据集 schema（兼容老格式）。"""
    kb_id: UUID
    name: str = Field(..., min_length=1, max_length=200)
    questions: List[str] = Field(default_factory=list, min_length=1)
    ground_truths: List[Dict[str, Any]] = Field(default_factory=list)

    @field_validator("questions")
    @classmethod
    def _validate_questions(cls, v: List[str]) -> List[str]:
        cleaned = [q.strip() for q in v if q and q.strip()]
        if not cleaned:
            raise ValueError("questions 列表不能为空（至少包含 1 个非空问题）")
        return cleaned

    @field_validator("ground_truths")
    @classmethod
    def _validate_ground_truths(cls, v: List[Dict[str, Any]], info: Any) -> List[Dict[str, Any]]:
        questions = info.data.get("questions") or []
        if v and len(v) != len(questions):
            raise ValueError(
                f"ground_truths 数量 ({len(v)}) 与 questions 数量 ({len(questions)}) 不一致"
            )
        for idx, gt in enumerate(v):
            chunk_ids = gt.get("chunk_ids") or []
            answer = gt.get("answer")
            if not chunk_ids and not answer:
                raise ValueError(
                    f"ground_truths[{idx}] 必须包含 'chunk_ids' 或 'answer' 至少一项"
                )
            if chunk_ids and not isinstance(chunk_ids, list):
                raise ValueError(f"ground_truths[{idx}].chunk_ids 必须是列表")
            if answer is not None and not isinstance(answer, str):
                raise ValueError(f"ground_truths[{idx}].answer 必须是字符串")
        return v


class EvaluationDatasetResponse(BaseModel):
    id: UUID
    kb_id: UUID
    name: str
    questions: List[str]
    ground_truths: List[Dict[str, Any]]
    created_at: datetime

    class Config:
        from_attributes = True


class EvaluationTaskCreate(BaseModel):
    dataset_id: UUID
    kb_id: UUID
    metrics: Optional[List[str]] = Field(
        default_factory=lambda: [
            "recall@3",
            "mrr",
            "ndcg@3",
            "faithfulness",
            "relevance",
            "coherence",
        ]
    )


class EvaluationTaskResponse(BaseModel):
    id: UUID
    dataset_id: UUID
    kb_id: UUID
    status: str
    metrics: List[str]
    results: Dict[str, Any]
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class EvaluationMetricsResponse(BaseModel):
    metrics: List[Dict[str, Any]]


class QuestionRunResponse(BaseModel):
    """单个问题的执行状态"""

    id: UUID
    task_id: UUID
    question_index: int
    question: str
    status: str  # pending/running/completed/failed/skipped/paused
    retrieved_chunk_ids: List[str] = Field(default_factory=list)
    generated_answer: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    attempts: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# v2 架构对齐数据集 schema（scripts/eval/datasets/ups_v2_arch_aligned.json 格式）
# ---------------------------------------------------------------------------

class EvaluationDatasetV2Create(BaseModel):
    """v2 架构对齐评测数据集（上传入口）。

    顶层结构与 scripts/eval/datasets/ups_v2_arch_aligned.json 完全一致：
      - kb_id: 顶层
      - questions[]: 每个查询含 question / ground_truth / metadata / retrieval_config / quality
      - _dataset_meta: 顶层元数据（携带 rag_arch_fingerprint）
    """
    name: str = Field(..., min_length=1, max_length=200)
    version: str = "v2-arch-aligned"
    kb_id: UUID
    questions: List[Dict[str, Any]] = Field(default_factory=list, min_length=1)
    _dataset_meta: Optional[Dict[str, Any]] = None

    @field_validator("questions")
    @classmethod
    def _validate_v2_questions(cls, v: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not v:
            raise ValueError("questions 不能为空")
        for i, q in enumerate(v):
            if not isinstance(q, dict):
                raise ValueError(f"questions[{i}] 必须是 dict")
            if "question" not in q and "query" not in q:
                raise ValueError(f"questions[{i}] 缺少 question/query 字段")
        return v


class QuestionRunV2Metadata(BaseModel):
    """v2 question run 扩展元数据（透传到 QuestionRunRecord.response_meta）。"""
    category: Optional[str] = None
    difficulty: Optional[str] = None
    tags: Optional[List[str]] = None
    diagnostic_intent: Optional[str] = None
    max_allowed_distance: Optional[float] = None
