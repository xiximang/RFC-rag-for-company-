"""CacheService — data access layer for query_cache (raw SQL)."""
import hashlib, json, logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class CacheService:
    """Low-level data access for query_cache using raw SQL."""

    async def get_by_hash(self, db: AsyncSession, query_hash: str) -> Optional[Dict[str, Any]]:
        sql = text("""
            SELECT id, query, query_hash, query_keywords, best_chunk_ids,
                   best_rerank_order, best_answer, confirmed_count,
                   owner_security_level, source_doc_ids, last_hit_at,
                   created_at, updated_at
            FROM query_cache WHERE query_hash = :h
        """)
        row = (await db.execute(sql, {"h": query_hash})).fetchone()
        if not row:
            return None
        return dict(row._mapping)

    async def upsert(self, db: AsyncSession, entry: Dict[str, Any]) -> Dict[str, Any]:
        existing = await self.get_by_hash(db, entry["query_hash"])
        now = datetime.now(timezone.utc)
        eid = entry.get("id", str(uuid4()))

        if existing:
            eid = existing["id"]
            sql = text("""
                UPDATE query_cache SET
                    best_chunk_ids = CAST(:bci AS jsonb),
                    best_rerank_order = CAST(:bro AS jsonb),
                    best_answer = :ba,
                    confirmed_count = :cc,
                    owner_security_level = :osl,
                    updated_at = :ua
                WHERE id = :id
            """)
            await db.execute(sql, {
                "bci": json.dumps(entry.get("best_chunk_ids", existing["best_chunk_ids"])),
                "bro": json.dumps(entry.get("best_rerank_order", existing["best_rerank_order"])),
                "ba": entry.get("best_answer", existing["best_answer"]),
                "cc": entry.get("confirmed_count", existing["confirmed_count"]),
                "osl": entry.get("owner_security_level", existing["owner_security_level"]),
                "ua": now, "id": eid,
            })
        else:
            sql = text("""
                INSERT INTO query_cache (id, query, query_hash, query_keywords,
                    best_chunk_ids, best_rerank_order, best_answer, confirmed_count,
                    owner_security_level, source_doc_ids, last_hit_at, created_at, updated_at)
                VALUES (:id, :q, :qh, CAST(:qk AS jsonb), CAST(:bci AS jsonb),
                    CAST(:bro AS jsonb), :ba, :cc, :osl, CAST(:sdi AS jsonb), :lha, :ca, :ua)
            """)
            await db.execute(sql, {
                "id": eid, "q": entry["query"], "qh": entry["query_hash"],
                "qk": json.dumps(entry.get("query_keywords", [])),
                "bci": json.dumps(entry["best_chunk_ids"]),
                "bro": json.dumps(entry["best_rerank_order"]),
                "ba": entry["best_answer"], "cc": entry.get("confirmed_count", 1),
                "osl": entry.get("owner_security_level", "L0"),  # 默认 L0（最低权限），强制调用方显式传入
                "sdi": json.dumps(entry.get("source_doc_ids", [])),
                "lha": None, "ca": now, "ua": now,
            })
        await db.commit()
        return await self.get_by_hash(db, entry["query_hash"]) or {}

    async def update_hit_time(self, db: AsyncSession, cache_id: str) -> None:
        await db.execute(
            text("UPDATE query_cache SET last_hit_at = :now WHERE id = :id"),
            {"now": datetime.now(timezone.utc), "id": cache_id},
        )
        await db.commit()

    @staticmethod
    def compute_hash(query: str) -> str:
        return hashlib.sha256(query.encode("utf-8")).hexdigest()
