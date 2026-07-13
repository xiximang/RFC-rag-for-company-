"""知识图谱服务（P2 占位实现）。

当前实现返回硬编码/随机生成的占位数据结构，便于前端/测试早期对接。
后续替换点：
- 接入 NER 模型（如 spaCy、HanLP、LLM-based extractor）抽取实体与关系。
- 使用图数据库（Neo4j、NebulaGraph 或 NetworkX + pgvector）持久化三元组。
- 实现子图检索、实体链接与知识增强生成（KGRAG）。
"""

import uuid
from typing import Any, Dict, List


class KnowledgeGraphService:
    """知识图谱构建与查询服务（占位）。"""

    def extract_entities(self, text: str) -> Dict[str, Any]:
        """从文本中抽取实体与关系（占位实现）。

        后续替换为真实 NER + 关系抽取模型，返回标准 {
            "entities": [...],
            "relations": [...]
        } 结构。

        Args:
            text: 输入文本。

        Returns:
            占位实体关系字典。
        """
        # 占位：按简单分词模拟实体，实际应调用模型服务。
        tokens = [t.strip("，。、；：！？\"'（）") for t in text.split() if t.strip()]
        entities = [
            {
                "id": f"ent-{uuid.uuid4().hex[:8]}",
                "name": token[:10] or "未知实体",
                "type": "GENERIC",
                "confidence": 0.85,
            }
            for token in tokens[:5]
        ]
        relations = []
        if len(entities) >= 2:
            relations = [
                {
                    "source": entities[0]["id"],
                    "target": entities[1]["id"],
                    "relation": "related_to",
                    "confidence": 0.7,
                }
            ]
        return {"entities": entities, "relations": relations}

    def build_graph(self, doc_id: str, chunks: List[str]) -> Dict[str, Any]:
        """基于文档分块构建知识图谱（占位实现）。

        后续替换为：
        1. 对 chunks 批量抽取实体关系。
        2. 实体消歧/对齐。
        3. 写入图数据库并建立 doc_id -> 子图索引。

        Args:
            doc_id: 文档唯一标识。
            chunks: 文档分块文本列表。

        Returns:
            占位建图结果，包含节点/边数量与示例三元组。
        """
        graph_id = f"kg-{doc_id}"
        nodes = []
        edges = []
        for idx, chunk in enumerate(chunks[:3]):
            extraction = self.extract_entities(chunk)
            for ent in extraction["entities"]:
                ent["chunk_index"] = idx
                nodes.append(ent)
            edges.extend(extraction["relations"])
        return {
            "graph_id": graph_id,
            "doc_id": doc_id,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "sample_nodes": nodes[:3],
            "sample_edges": edges[:3],
            "status": "placeholder_built",
        }

    def search_graph(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        """基于查询在知识图谱中检索相关子图（占位实现）。

        后续替换为：
        - 对 query 做实体链接。
        - 在图数据库中执行多跳邻居查询或子图匹配。
        - 返回与查询最相关的三元组路径。

        Args:
            query: 查询文本。
            top_k: 最多返回的三元组数量。

        Returns:
            占位检索结果。
        """
        triples = [
            {
                "subject": f"实体_{i}",
                "predicate": "related_to",
                "object": f"实体_{i + 1}",
                "score": 1.0 - i * 0.1,
            }
            for i in range(min(top_k, 5))
        ]
        return {
            "query": query,
            "top_k": top_k,
            "triples": triples,
            "expanded_entities": [t["subject"] for t in triples],
            "status": "placeholder_search",
        }


knowledge_graph_service = KnowledgeGraphService()
