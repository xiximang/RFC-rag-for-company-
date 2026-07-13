"""Agentic RAG API（P2 占位实现）。

所有端点均为最小可运行占位，便于暴露规划与执行接口契约。
后续会替换为 LLM-based planner 与真实工具执行器。
"""

from fastapi import APIRouter, Depends

from app.api.v1.auth import get_current_user
from app.schemas.agentic_rag import (
    AgenticRAGChatRequest,
    AgenticRAGChatResponse,
    AgenticRAGPlanRequest,
    AgenticRAGPlanResponse,
)
from app.schemas.user import UserResponse
from app.services.agentic_rag_service import agentic_rag_service

router = APIRouter(prefix="/agentic-rag", tags=["agentic-rag"])


@router.post("/chat", response_model=AgenticRAGChatResponse)
async def agentic_chat(
    request: AgenticRAGChatRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """端到端 Agentic RAG 对话（占位）。"""
    result = await agentic_rag_service.chat(request.query, request.kb_ids)
    return AgenticRAGChatResponse(**result)


@router.post("/plan", response_model=AgenticRAGPlanResponse)
async def agentic_plan(
    request: AgenticRAGPlanRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """为查询生成 Agentic RAG 执行计划（占位）。"""
    result = await agentic_rag_service.plan(request.query, request.kb_ids)
    return AgenticRAGPlanResponse(**result)
