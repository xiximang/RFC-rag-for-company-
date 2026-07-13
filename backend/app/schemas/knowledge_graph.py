"""知识图谱 API 请求/响应模型（P2 占位）。"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ExtractEntitiesRequest(BaseModel):
    text: str = Field(..., min_length=1, description="待抽取实体的文本")


class ExtractEntitiesResponse(BaseModel):
    entities: List[Dict[str, Any]] = []
    relations: List[Dict[str, Any]] = []


class BuildGraphRequest(BaseModel):
    doc_id: str = Field(..., min_length=1, description="文档唯一标识")
    chunks: List[str] = Field(default_factory=list, description="文档分块文本列表")


class BuildGraphResponse(BaseModel):
    graph_id: str
    doc_id: str
    node_count: int
    edge_count: int
    sample_nodes: List[Dict[str, Any]] = []
    sample_edges: List[Dict[str, Any]] = []
    status: str


class SearchGraphRequest(BaseModel):
    query: str = Field(..., min_length=1, description="检索查询")
    top_k: int = Field(default=5, ge=1, le=50, description="返回三元组数量上限")


class SearchGraphResponse(BaseModel):
    query: str
    top_k: int
    triples: List[Dict[str, Any]] = []
    expanded_entities: List[str] = []
    status: str
