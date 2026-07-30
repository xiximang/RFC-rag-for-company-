from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SourceItem(BaseModel):
    doc_id: Optional[str]
    chunk_id: Optional[str]
    content: str
    score: float
    modality: str
    position_info: Optional[Dict[str, Any]] = None
    page: Optional[int] = None
    sheet: Optional[str] = None
    timestamp: Optional[str] = None


class CandidateItem(BaseModel):
    """Rerank 候选项（已过五级权限穿透，content 为降级后的值）。

    工程师反馈闭环的展示单元。content 必须直接取 retrieval_service 返回的
    item["content"]（L5 降级后已是占位符），绝不可按 chunk_id 反查原文，
    否则绕过 L5 关键词降级，向低权限用户暴露敏感原文。
    """
    rank: int
    chunk_id: Optional[str] = None
    doc_id: Optional[str] = None
    content: str
    rerank_score: Optional[float] = None
    max_keyword_level: str = "L0"
    filtered: bool = False


class ChatRequest(BaseModel):
    query: str
    kb_ids: List[UUID]
    conversation_id: Optional[UUID] = None
    modalities: Optional[List[str]] = None
    top_k: Optional[int] = 10
    rerank_top_k: Optional[int] = 5
    max_context_tokens: Optional[int] = 4000
    stream: Optional[bool] = False
    # SSE 断线重连
    stream_id: Optional[str] = None       # 客户端生成的流 ID，重连时复用
    last_event_id: Optional[int] = -1     # 客户端已收到的最后事件 ID，-1 表示新请求


class ChatResponse(BaseModel):
    answer: str
    intercepted: bool = False
    sources: List[SourceItem] = []
    strategy: Optional[Dict[str, Any]] = None
    conversation_id: Optional[UUID] = None
    candidates: Optional[List[CandidateItem]] = None


class ConversationCreate(BaseModel):
    title: Optional[str] = "新会话"
    kb_ids: List[UUID]


class ConversationResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    kb_ids: List[UUID]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    sources: List[SourceItem] = []
    feedback_rating: Optional[int] = None
    feedback_comment: Optional[str] = None
    # 工程师反馈与上下文工程：候选落库回看 + 候选排序反馈（可选，不影响现有字段）
    candidates: Optional[List[CandidateItem]] = None
    candidate_feedback: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChatWithHistoryRequest(BaseModel):
    conversation_id: UUID
    query: str
    kb_ids: Optional[List[UUID]] = None
    modalities: Optional[List[str]] = None
    top_k: Optional[int] = 10
    rerank_top_k: Optional[int] = 5
    max_context_tokens: Optional[int] = 4000


class FeedbackCreate(BaseModel):
    rating: int = Field(..., ge=-1, le=1)
    comment: Optional[str] = None


class CandidateFeedbackRequest(BaseModel):
    """工程师提交的候选排序/评分反馈"""
    ranking: List[int]
    chosen_rank: int
    ratings: Optional[Dict[int, int]] = None
    comment: Optional[str] = None
    action: str = "rank"
    edited_answer: Optional[str] = None
