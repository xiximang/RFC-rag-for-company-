"""PostgreSQL full-text search (BM25-style) client for chunk retrieval."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Sequence
from uuid import UUID

from sqlalchemy import Integer, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document

logger = logging.getLogger(__name__)

try:
    import jieba  # type: ignore

    _JIEBA_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    jieba = None  # type: ignore
    _JIEBA_AVAILABLE = False


class BM25Client:
    """BM25 keyword search backed by PostgreSQL full-text search.

    The ``Chunk`` table is expected to have a ``content_tsv`` ``TSVECTOR``
    column (GIN-indexed).  Queries are tokenised with ``plainto_tsquery`` and
    ranked with ``ts_rank_cd``.  The client is fully async and degrades
    gracefully when the schema is not ready or the query is empty.

    When the ``simple`` tsvector tokenizer cannot match CJK / mixed text
    (e.g. ``"50kVA 功率模块"`` vs. ``"50kVA功率模块"``), the client falls
    back to a jieba-tokenised ``ILIKE`` OR query, and finally to a
    raw ``ILIKE '%query%'`` match.
    """

    def __init__(self, ts_config: str = "chinese") -> None:
        self.ts_config = ts_config
        self._jieba_available = _JIEBA_AVAILABLE

    @staticmethod
    def _normalise_query(query: str) -> str:
        """Remove characters that break ``to_tsquery`` syntax."""
        if not query:
            return ""
        # Keep CJK characters, letters, digits and spaces; drop punctuation.
        cleaned = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", query)
        return " ".join(cleaned.split())

    @staticmethod
    def _tokenize_cjk(query: str) -> List[str]:
        """Tokenise a query using jieba's search-mode cutter.

        Returns an empty list when jieba is unavailable.  Single-character
        tokens and whitespace are filtered out.
        """
        if not jieba:
            return []
        try:
            tokens = [t for t in jieba.cut_for_search(query) if t and t.strip()]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("jieba tokenisation failed: %s", exc)
            return []
        # Filter very short / pure-whitespace tokens to keep query tight.
        return [t for t in tokens if len(t.strip()) >= 1]

    async def search(
        self,
        db: AsyncSession,
        query: str,
        kb_ids: Sequence[UUID | str],
        top_k: int = 20,
        denied_doc_ids: Sequence[str] | None = None,
        denied_tags: Sequence[str] | None = None,
        modalities: Sequence[str] | None = None,
    ) -> List[Dict[str, Any]]:
        """BM25 search over active chunks restricted by knowledge base(s).

        Args:
            db: Async SQLAlchemy session.
            query: Free-text query.
            kb_ids: Knowledge-base IDs to scope the search.
            top_k: Maximum number of hits to return.
            denied_doc_ids: Document IDs the user is explicitly denied.
            denied_tags: Tags the user is explicitly denied.
            modalities: Optional modality filter (e.g. ``["text", "table"]``).

        Returns:
            List of result dicts with ``chunk_id``, ``doc_id``, ``kb_id``,
            ``content``, ``score`` and ``modality``.
        """
        normalised = self._normalise_query(query)
        if not normalised or not kb_ids:
            return []

        # ------------------------------------------------------------------
        # Layer 1: tsvector full-text search (happy path).
        # ------------------------------------------------------------------
        try:
            rank_expr = func.ts_rank_cd(
                Chunk.content_tsv,
                func.plainto_tsquery(self.ts_config, normalised),
                32,  # rank normalization: divide by document length
            ).label("score")

            ts_match = Chunk.content_tsv.op("@@")(
                func.plainto_tsquery(self.ts_config, normalised)
            )

            stmt = (
                select(
                    Chunk.id,
                    Chunk.doc_id,
                    Document.kb_id,
                    Chunk.content,
                    Chunk.modality,
                    rank_expr,
                )
                .join(Document, Chunk.doc_id == Document.id)
                .where(ts_match)
                .where(Chunk.status == "active")
                .where(Document.kb_id.in_(list(kb_ids)))
                .order_by(desc(rank_expr))
                .limit(top_k)
            )

            if modalities:
                stmt = stmt.where(Chunk.modality.in_(list(modalities)))

            if denied_doc_ids:
                stmt = stmt.where(Chunk.doc_id.notin_(denied_doc_ids))

            if denied_tags:
                # Tags on the chunk metadata JSONB are stored as a list of strings
                # under the "tags" key.  Exclude chunks whose tag list overlaps.
                tag_values = [str(t).lower() for t in denied_tags]
                for tag in tag_values:
                    stmt = stmt.where(
                        ~Chunk.metadata_.op("@>")({"tags": [tag]})
                    )

            result = await db.execute(stmt)
            rows = result.all()

            if rows:
                hits: List[Dict[str, Any]] = []
                for row in rows:
                    hits.append(
                        {
                            "chunk_id": str(row.id),
                            "doc_id": str(row.doc_id),
                            "kb_id": str(row.kb_id) if row.kb_id else None,
                            "content": row.content or "",
                            "modality": row.modality or "text",
                            "score": float(row.score or 0.0),
                        }
                    )
                return hits
        except Exception as exc:
            logger.exception("BM25 tsvector search failed: %s", exc)
            # Fall through to fallback layers.

        # ------------------------------------------------------------------
        # Layer 2: CJK client-side tokenisation (jieba) + ILIKE OR query.
        # The PostgreSQL ``simple`` tokenizer cannot split CJK characters, so
        # we replicate the cut on the client and use ILIKE for matching.
        # Score = (matched keyword count) / (total keyword count).
        # ------------------------------------------------------------------
        cjk_tokens = self._tokenize_cjk(normalised) if self._jieba_available else []
        # Deduplicate while preserving order.
        seen: set[str] = set()
        unique_tokens: List[str] = []
        for tok in cjk_tokens:
            if tok not in seen:
                seen.add(tok)
                unique_tokens.append(tok)

        if unique_tokens:
            try:
                like_conditions = [
                    Chunk.content.ilike(f"%{kw}%") for kw in unique_tokens
                ]
                # hit_count = number of keywords matched in the chunk content.
                hit_count_expr = sum(
                    func.cast(cond, Integer) for cond in like_conditions
                )
                stmt = (
                    select(
                        Chunk.id,
                        Chunk.doc_id,
                        Document.kb_id,
                        Chunk.content,
                        Chunk.modality,
                        hit_count_expr.label("hit_count"),
                    )
                    .join(Document, Chunk.doc_id == Document.id)
                    .where(or_(*like_conditions))
                    .where(Chunk.status == "active")
                    .where(Document.kb_id.in_(list(kb_ids)))
                    .order_by(desc("hit_count"))
                    .limit(top_k)
                )

                if modalities:
                    stmt = stmt.where(Chunk.modality.in_(list(modalities)))
                if denied_doc_ids:
                    stmt = stmt.where(Chunk.doc_id.notin_(denied_doc_ids))
                if denied_tags:
                    tag_values = [str(t).lower() for t in denied_tags]
                    for tag in tag_values:
                        stmt = stmt.where(
                            ~Chunk.metadata_.op("@>")({"tags": [tag]})
                        )

                result = await db.execute(stmt)
                rows = result.all()

                if rows:
                    total_kw = len(unique_tokens)
                    hits = []
                    for row in rows:
                        hits.append(
                            {
                                "chunk_id": str(row.id),
                                "doc_id": str(row.doc_id),
                                "kb_id": str(row.kb_id) if row.kb_id else None,
                                "content": row.content or "",
                                "modality": row.modality or "text",
                                "score": float(
                                    (row.hit_count or 0) / total_kw
                                ),
                            }
                        )
                    return hits
            except Exception as exc:
                logger.exception("BM25 jieba ILIKE fallback failed: %s", exc)
                # Fall through to the final raw ILIKE fallback.

        # ------------------------------------------------------------------
        # Layer 3: Raw ``ILIKE '%query%'`` fallback.  This works for
        # space-less CJK strings and short queries, giving a coarse match
        # with a fixed score of 0.5.
        # ------------------------------------------------------------------
        try:
            stmt = (
                select(
                    Chunk.id,
                    Chunk.doc_id,
                    Document.kb_id,
                    Chunk.content,
                    Chunk.modality,
                )
                .join(Document, Chunk.doc_id == Document.id)
                .where(Chunk.content.ilike(f"%{normalised}%"))
                .where(Chunk.status == "active")
                .where(Document.kb_id.in_(list(kb_ids)))
                .order_by(desc(Chunk.created_at))
                .limit(top_k)
            )

            if modalities:
                stmt = stmt.where(Chunk.modality.in_(list(modalities)))
            if denied_doc_ids:
                stmt = stmt.where(Chunk.doc_id.notin_(denied_doc_ids))
            if denied_tags:
                tag_values = [str(t).lower() for t in denied_tags]
                for tag in tag_values:
                    stmt = stmt.where(
                        ~Chunk.metadata_.op("@>")({"tags": [tag]})
                    )

            result = await db.execute(stmt)
            rows = result.all()

            hits = []
            for row in rows:
                hits.append(
                    {
                        "chunk_id": str(row.id),
                        "doc_id": str(row.doc_id),
                        "kb_id": str(row.kb_id) if row.kb_id else None,
                        "content": row.content or "",
                        "modality": row.modality or "text",
                        "score": 0.5,
                    }
                )
            return hits
        except Exception as exc:
            logger.exception("BM25 raw ILIKE fallback failed: %s", exc)
            return []

    async def update_tsv_for_kb(
        self,
        db: AsyncSession,
        kb_ids: Sequence[UUID | str],
    ) -> int:
        """(Re)build ``content_tsv`` for active chunks in given KBs.

        This is useful when ``content_tsv`` is out of sync or needs to be
        regenerated after bulk imports.  Returns the number of rows updated.
        """
        if not kb_ids:
            return 0

        try:
            stmt = (
                Chunk.__table__.update()
                .where(Chunk.doc_id == Document.id)
                .where(Document.kb_id.in_(list(kb_ids)))
                .where(Chunk.status == "active")
                .values(
                    content_tsv=func.to_tsvector(
                        self.ts_config, func.coalesce(Chunk.content, "")
                    )
                )
            )
            result = await db.execute(stmt)
            await db.commit()
            return result.rowcount or 0
        except Exception as exc:
            await db.rollback()
            logger.exception("Failed to update content_tsv: %s", exc)
            return 0


# Module-level singleton for convenience.
bm25_client = BM25Client()
