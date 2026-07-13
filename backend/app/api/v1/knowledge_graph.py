"""知识图谱 API（P2 占位实现）。

所有端点均为最小可运行占位，便于前端与测试早期对接。
后续会替换为真实 NER、关系抽取与图数据库查询逻辑。
"""

from fastapi import APIRouter, Depends

from app.api.v1.auth import get_current_user
from app.schemas.knowledge_graph import (
    BuildGraphRequest,
    BuildGraphResponse,
    ExtractEntitiesRequest,
    ExtractEntitiesResponse,
    SearchGraphRequest,
    SearchGraphResponse,
)
from app.schemas.user import UserResponse
from app.services.knowledge_graph_service import knowledge_graph_service

router = APIRouter(prefix="/knowledge-graph", tags=["knowledge-graph"])


@router.post("/extract", response_model=ExtractEntitiesResponse)
async def extract_entities(
    request: ExtractEntitiesRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """从文本中抽取实体与关系（占位）。"""
    result = knowledge_graph_service.extract_entities(request.text)
    return ExtractEntitiesResponse(**result)


@router.post("/build", response_model=BuildGraphResponse)
async def build_graph(
    request: BuildGraphRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """基于文档分块构建知识图谱（占位）。"""
    result = knowledge_graph_service.build_graph(request.doc_id, request.chunks)
    return BuildGraphResponse(**result)


@router.post("/search", response_model=SearchGraphResponse)
async def search_graph(
    request: SearchGraphRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """在知识图谱中检索相关子图（占位）。"""
    result = knowledge_graph_service.search_graph(request.query, request.top_k)
    return SearchGraphResponse(**result)
