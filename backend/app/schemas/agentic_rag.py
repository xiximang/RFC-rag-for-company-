"""Agentic RAG API 请求/响应模型（P2 占位）。"""

from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AgenticRAGChatRequest(BaseModel):
    query: str = Field(..., min_length=1, description="用户查询")
    kb_ids: List[UUID] = Field(..., min_length=1, description="目标知识库 ID 列表")


class AgenticRAGPlanRequest(BaseModel):
    query: str = Field(..., min_length=1, description="用户查询")
    kb_ids: List[UUID] = Field(..., min_length=1, description="目标知识库 ID 列表")


class AgenticRAGPlanResponse(BaseModel):
    query: str
    kb_ids: List[str]
    steps: List[Dict[str, Any]] = []
    status: str


class AgenticRAGChatResponse(BaseModel):
    query: str
    kb_ids: List[str]
    plan: Optional[Dict[str, Any]] = None
    execution: Optional[Dict[str, Any]] = None
    answer: str
    status: str
