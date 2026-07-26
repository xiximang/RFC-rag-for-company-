"""QueryCacheMatcher — three-layer cache matching with security isolation.

五级兼容：
- P4: _is_level_compatible 保证低权限用户不命中高权限缓存（用户等级隔离）。
- P1/P2: 命中后 _validate_doc_access 校验 best_chunk_ids 对当前用户是否仍可访问
  （文档级黑名单 / 字段级权限 / 标签黑名单 全部重新穿透检查）。
"""
import json, logging, re
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.pipelines.keyword_annotator import LEVEL_ORDER, tokenize
from app.services.cache_service import CacheService
from app.services.permission_service import PermissionService
from app.core.cache import CacheManager

logger = logging.getLogger(__name__)

SEMANTIC_THRESHOLD = 0.92
KEYWORD_THRESHOLD = 0.60


class CacheHitResult:
    def __init__(self, entry: Dict[str, Any], match_type: str, similarity: float):
        self.entry = entry
        self.match_type = match_type
        self.similarity = similarity
        self.best_answer = entry.get("best_answer", "")
        self.best_chunk_ids = entry.get("best_chunk_ids", [])
        self.best_rerank_order = entry.get("best_rerank_order", [])


class QueryCacheMatcher:
    def __init__(self, cache_service: Optional[CacheService] = None):
        self.cache_svc = cache_service or CacheService()

    async def _validate_doc_access(
        self,
        db: AsyncSession,
        entry: Dict[str, Any],
        user_id: UUID,
    ) -> bool:
        """P1/P2 校验：缓存命中的 best_chunk_ids 对当前 user_id 是否仍可访问。

        流程：
        1. 取 entry.owner_security_level + best_chunk_ids
        2. 用户等级隔离（level 隔离）已通过 _is_level_compatible
        3. 文档黑名单：chunk 关联的 doc_id 若在用户 denied_docs 中 → 拒绝
        4. 标签黑名单：chunk metadata_.tags 若与 denied_tags 相交 → 拒绝
        5. 字段级权限：check_field_permission 若拒绝 → 拒绝

        Returns:
            True 表示所有 chunk 都仍可访问；False 表示至少 1 个 chunk 已无权访问。
        """
        chunk_ids = entry.get("best_chunk_ids") or []
        if not chunk_ids:
            # 没有 chunk_id（feedback 写入时可能硬编码 []）
            # 此时只能返回 best_answer，无法做高亮和验证
            # 但 best_answer 内容已经过 P5 校验，可以安全返回
            logger.debug(
                "Cache entry has empty best_chunk_ids, "
                "skipping doc-level validation (user=%s)", user_id,
            )
            return True

        cache = CacheManager()
        perm_service = PermissionService(db, cache)
        denied_docs = await perm_service.get_user_denied_documents(user_id)
        denied_tags = await perm_service.get_user_denied_tags(user_id)

        # 查询每个 chunk 的 doc_id 与 tags
        for chunk_id in chunk_ids:
            chunk_row = (
                await db.execute(
                    text("SELECT doc_id, metadata FROM chunks WHERE id = :cid"),
                    {"cid": chunk_id},
                )
            ).fetchone()
            if not chunk_row:
                # chunk 已被删除 → 缓存命中但内容已不存在
                logger.warning(
                    "Cache entry chunk %s no longer exists in DB (user=%s)",
                    chunk_id, user_id,
                )
                return False

            doc_id = str(chunk_row[0]) if chunk_row[0] else None
            meta = chunk_row[1] or {}
            if not isinstance(meta, dict):
                meta = {}

            # 文档黑名单
            if doc_id and doc_id in denied_docs:
                logger.warning(
                    "P1/P2 blocked: chunk %s doc_id %s in user %s denied_docs",
                    chunk_id, doc_id, user_id,
                )
                return False

            # 标签黑名单
            chunk_tags = set(meta.get("tags") or [])
            if chunk_tags and chunk_tags & denied_tags:
                logger.warning(
                    "P1/P2 blocked: chunk %s tags %s in user %s denied_tags",
                    chunk_id, chunk_tags & denied_tags, user_id,
                )
                return False

            # 字段级权限
            from app.models.chunk import Chunk
            chunk_obj = Chunk(
                id=chunk_id, doc_id=doc_id, metadata_=meta, content=""
            )
            if not await perm_service.check_field_permission(user_id, chunk_obj):
                logger.warning(
                    "P1/P2 blocked: chunk %s field-level permission denied for user %s",
                    chunk_id, user_id,
                )
                return False

        return True

    async def find_match(
        self,
        db: AsyncSession,
        query: str,
        query_embedding: Optional[List[float]],
        user_security_level: str,
        user_id: Optional[UUID] = None,
    ) -> Optional[CacheHitResult]:
        """三层匹配 + 安全隔离。

        Args:
            user_id: 必需参数，用于文档级权限校验（P1/P2）。
                      若为 None 则跳过文档级校验（仅做用户等级隔离）。
        """
        # Layer 1: exact hash
        qhash = CacheService.compute_hash(query)
        entry = await self.cache_svc.get_by_hash(db, qhash)
        if entry and self._is_level_compatible(entry, user_security_level):
            if user_id is not None:
                if not await self._validate_doc_access(db, entry, user_id):
                    return None
            return CacheHitResult(entry, "exact_hash", 1.0)

        # Layer 2: semantic vector
        if query_embedding:
            semantic_matches = await self._search_by_embedding(db, query_embedding, 5)
            for entry_dict, sim in semantic_matches:
                if (sim >= SEMANTIC_THRESHOLD
                        and self._is_level_compatible(entry_dict, user_security_level)):
                    if user_id is not None:
                        if not await self._validate_doc_access(db, entry_dict, user_id):
                            continue
                    return CacheHitResult(entry_dict, "semantic", sim)

        # Layer 3: keyword Jaccard
        query_tokens = tokenize(query)
        if query_tokens:
            recent = await self._list_recent(db, 50)
            for entry_dict in recent:
                if not self._is_level_compatible(entry_dict, user_security_level):
                    continue
                entry_tokens = set(entry_dict.get("query_keywords") or []) if entry_dict.get("query_keywords") else tokenize(entry_dict.get("query", ""))
                jaccard = self._jaccard(query_tokens, entry_tokens)
                if jaccard >= KEYWORD_THRESHOLD:
                    if user_id is not None:
                        if not await self._validate_doc_access(db, entry_dict, user_id):
                            continue
                    return CacheHitResult(entry_dict, "keyword_jaccard", jaccard)

        return None

    async def find_near_miss(
        self, db: AsyncSession, query_embedding: List[float],
        user_security_level: str, threshold_low: float = 0.80,
    ) -> Optional[Dict[str, Any]]:
        matches = await self._search_by_embedding(db, query_embedding, 3)
        for entry_dict, sim in matches:
            if threshold_low <= sim < SEMANTIC_THRESHOLD:
                if self._is_level_compatible(entry_dict, user_security_level):
                    return {"query": entry_dict["query"], "similarity": sim, "best_answer": entry_dict["best_answer"]}
        return None

    @staticmethod
    def _is_level_compatible(entry, user_level: str) -> bool:
        """Check if ``user_level`` has sufficient clearance for ``entry``.
        Accepts both dict and ORM objects (``_search_by_embedding`` returns ORM
        instances, while other paths use dicts).
        """
        user_val = LEVEL_ORDER.get(user_level, 0)
        if isinstance(entry, dict):
            owner_val = LEVEL_ORDER.get(entry.get("owner_security_level", "L0"), 0)
        else:
            owner_val = LEVEL_ORDER.get(getattr(entry, "owner_security_level", "L0"), 0)
        return user_val >= owner_val

    async def _search_by_embedding(self, db: AsyncSession, embedding: List[float], top_k: int = 5) -> List[tuple]:
        import json as _json
        emb_str = _json.dumps(embedding, ensure_ascii=False)
        sql = text("""
            SELECT query_hash, 1 - (query_embedding <=> CAST(:emb AS vector(1024))) AS sim
            FROM query_cache
            WHERE query_embedding IS NOT NULL
            ORDER BY query_embedding <=> CAST(:emb AS vector(1024))
            LIMIT :lim
        """)
        rows = (await db.execute(sql, {"emb": emb_str, "lim": top_k})).fetchall()
        if not rows:
            return []
        results = []
        for row in rows:
            entry = await self.cache_svc.get_by_hash(db, row[0]) if row[0] else None
            if entry:
                results.append((entry, float(row[1])))
        return results

    async def _list_recent(self, db: AsyncSession, limit: int = 50) -> List[Dict[str, Any]]:
        sql = text("""
            SELECT id, query, query_hash, query_keywords, best_chunk_ids,
                   best_rerank_order, best_answer, confirmed_count,
                   owner_security_level, source_doc_ids, last_hit_at,
                   created_at, updated_at
            FROM query_cache ORDER BY last_hit_at DESC NULLS LAST LIMIT :lim
        """)
        rows = (await db.execute(sql, {"lim": limit})).fetchall()
        return [dict(r._mapping) for r in rows]

    @staticmethod
    def _jaccard(a: Set[str], b: Set[str]) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)
