"""Milvus-backed vector store implementation (pymilvus 2.4+)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.config import Settings, settings
from app.retrieval.vector_store import BaseVectorStore, ChunkT

try:
    from pymilvus import (
        Collection,
        CollectionSchema,
        DataType,
        FieldSchema,
        connections,
        utility,
    )

    _PYMILVUS_AVAILABLE = True
except Exception as exc:  # pragma: no cover
    Collection = None  # type: ignore
    CollectionSchema = None  # type: ignore
    DataType = None  # type: ignore
    FieldSchema = None  # type: ignore
    connections = None  # type: ignore
    utility = None  # type: ignore
    _PYMILVUS_AVAILABLE = False
    logging.getLogger(__name__).warning("pymilvus is not installed: %s", exc)

logger = logging.getLogger(__name__)


class MilvusVectorStore(BaseVectorStore):
    """Concrete vector store backed by Milvus.

    The store maintains two collections:

    * ``{prefix}_text_chunks`` for document chunks with dense (1024-dim) and
      sparse vectors.
    * ``{prefix}_image_frames`` for image/video keyframes with dense 512-dim
      vectors.

    If Milvus cannot be reached the store marks itself unavailable and every
    method returns a safe fallback (empty list / ``False``) after logging a
    warning, so that application startup is not blocked.
    """

    backend_name = "milvus"

    TEXT_DIM = 1024
    IMAGE_DIM = 512

    def __init__(self, milvus_settings: Settings | None = None) -> None:
        self._settings = milvus_settings or settings
        prefix = self._settings.MILVUS_COLLECTION_PREFIX
        self.text_collection_name = f"{prefix}_text_chunks"
        self.image_collection_name = f"{prefix}_image_frames"

        self._available = False
        self._connect()

        if self._available:
            # Best-effort creation so callers do not need to manage schemas.
            try:
                self.create_collection(self.text_collection_name)
                self.create_collection(self.image_collection_name)
            except Exception as exc:  # pragma: no cover
                logger.warning("Failed to ensure Milvus collections: %s", exc)

    # ------------------------------------------------------------------
    # Connection / availability
    # ------------------------------------------------------------------
    def _connect(self) -> None:
        if not _PYMILVUS_AVAILABLE:
            logger.warning("pymilvus is not installed; MilvusVectorStore is unavailable")
            return

        try:
            if connections.has_connection("default"):
                self._available = True
                return

            connections.connect(
                alias="default",
                host=self._settings.MILVUS_HOST,
                port=self._settings.MILVUS_PORT,
                timeout=10,
            )
            self._available = True
            logger.info(
                "Connected to Milvus at %s:%s",
                self._settings.MILVUS_HOST,
                self._settings.MILVUS_PORT,
            )
        except Exception as exc:
            self._available = False
            logger.warning(
                "Failed to connect to Milvus at %s:%s: %s",
                self._settings.MILVUS_HOST,
                self._settings.MILVUS_PORT,
                exc,
            )

    @property
    def is_available(self) -> bool:
        return self._available

    # ------------------------------------------------------------------
    # Schema builders
    # ------------------------------------------------------------------
    def _build_text_fields(self) -> List[FieldSchema]:
        return [
            FieldSchema(
                name="id",
                dtype=DataType.VARCHAR,
                is_primary=True,
                auto_id=False,
                max_length=128,
            ),
            FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="kb_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="modality", dtype=DataType.VARCHAR, max_length=32),
            FieldSchema(name="doc_acl_version", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="max_keyword_level", dtype=DataType.INT32),
            FieldSchema(
                name="tags",
                dtype=DataType.ARRAY,
                element_type=DataType.VARCHAR,
                max_length=64,
                max_capacity=64,
            ),
            FieldSchema(name="created_by", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="status", dtype=DataType.VARCHAR, max_length=32),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.TEXT_DIM),
        ]

    def _build_image_fields(self) -> List[FieldSchema]:
        return [
            FieldSchema(
                name="id",
                dtype=DataType.VARCHAR,
                is_primary=True,
                auto_id=False,
                max_length=128,
            ),
            FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="kb_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="frame_index", dtype=DataType.INT32),
            FieldSchema(name="image_url", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.IMAGE_DIM),
        ]

    def _create_hnsw_index(self, collection: Collection, field: str) -> None:
        index_params = {
            "metric_type": "COSINE",
            "index_type": "HNSW",
            "params": {"M": 16, "efConstruction": 200},
        }
        collection.create_index(field_name=field, index_params=index_params)

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------
    def create_collection(self, collection_name: str, **kwargs: Any) -> bool:
        if not self._available:
            logger.warning("Milvus unavailable; cannot create collection %s", collection_name)
            return False

        try:
            if utility.has_collection(collection_name):
                return True

            if collection_name == self.text_collection_name:
                fields = self._build_text_fields()
                description = "Text chunks with dense 1024-dim and sparse vectors"
            elif collection_name == self.image_collection_name:
                fields = self._build_image_fields()
                description = "Image/video keyframe vectors (512-dim)"
            else:
                raise ValueError(f"Unknown collection: {collection_name}")

            schema = CollectionSchema(
                fields,
                description=description,
                enable_dynamic_field=True,
            )
            collection = Collection(
                name=collection_name,
                schema=schema,
                consistency_level="Bounded",
            )
            self._create_hnsw_index(collection, "embedding")
            collection.load()
            logger.info("Created and loaded Milvus collection %s", collection_name)
            return True
        except Exception as exc:
            logger.exception("Failed to create Milvus collection %s: %s", collection_name, exc)
            return False

    def drop_collection(self, collection_name: str) -> bool:
        if not self._available:
            logger.warning("Milvus unavailable; cannot drop collection %s", collection_name)
            return False

        try:
            collection = self._get_collection(collection_name)
            collection.drop()
            logger.info("Dropped Milvus collection %s", collection_name)
            return True
        except Exception as exc:
            logger.exception("Failed to drop Milvus collection %s: %s", collection_name, exc)
            return False

    def _get_collection(self, collection_name: str) -> Collection:
        collection = Collection(collection_name)
        collection.load()
        return collection

    # ------------------------------------------------------------------
    # Generic CRUD on raw records
    # ------------------------------------------------------------------
    def insert(self, collection_name: str, records: List[Dict[str, Any]]) -> List[str]:
        if not self._available:
            logger.warning("Milvus unavailable; skipping insert into %s", collection_name)
            return []

        if not records:
            return []

        try:
            collection = self._get_collection(collection_name)
            mutation_result = collection.insert(records)
            logger.debug("Inserted %s records into %s", len(records), collection_name)
            return list(mutation_result.primary_keys)
        except Exception as exc:
            logger.exception("Insert into %s failed: %s", collection_name, exc)
            return []

    def search(
        self,
        collection_name: str,
        query_vector: List[float],
        filter_expr: str = "",
        top_k: int = 10,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        if not self._available:
            logger.warning("Milvus unavailable; returning empty search results")
            return []

        try:
            collection = self._get_collection(collection_name)
            anns_field = kwargs.get("anns_field", "embedding")
            metric_type = kwargs.get("metric_type", "COSINE")
            ef = kwargs.get("ef", 64)
            output_fields = kwargs.get(
                "output_fields",
                self._default_output_fields(collection_name),
            )

            search_params = {
                "metric_type": metric_type,
                "params": {"ef": ef},
            }

            results = collection.search(
                data=[query_vector],
                anns_field=anns_field,
                param=search_params,
                limit=top_k,
                expr=filter_expr or None,
                output_fields=output_fields,
            )
            return self._parse_search_results(results)
        except Exception as exc:
            logger.exception("Search in %s failed: %s", collection_name, exc)
            return []

    def update(
        self,
        collection_name: str,
        pk: str,
        data: Dict[str, Any],
    ) -> bool:
        if not self._available:
            logger.warning("Milvus unavailable; skipping update")
            return False

        try:
            collection = self._get_collection(collection_name)
            record = dict(data)
            record.setdefault("id", pk)
            collection.upsert([record])
            logger.debug("Upserted record %s in %s", pk, collection_name)
            return True
        except Exception as exc:
            logger.exception("Update in %s failed: %s", collection_name, exc)
            return False

    def delete_by_doc_id(
        self,
        doc_id: str,
        collection_name: str | None = None,
    ) -> bool:
        if not self._available:
            logger.warning("Milvus unavailable; skipping delete_by_doc_id")
            return False

        expr = self._eq_expr("doc_id", doc_id)
        targets = (
            [collection_name]
            if collection_name
            else [self.text_collection_name, self.image_collection_name]
        )

        success = True
        for name in targets:
            try:
                collection = self._get_collection(name)
                collection.delete(expr)
                logger.info("Deleted records for doc_id=%s from %s", doc_id, name)
            except Exception as exc:
                logger.exception("Failed to delete doc_id=%s from %s: %s", doc_id, name, exc)
                success = False

        return success

    # ------------------------------------------------------------------
    # Chunk-specific helpers
    # ------------------------------------------------------------------
    def insert_chunks(
        self,
        chunks: List[ChunkT],
        embeddings: List[List[float]],
    ) -> List[str]:
        """Insert document chunks into the text collection.

        The ``Chunk`` model only needs to expose the attributes defined by
        ``ChunkLike`` in ``vector_store.py``.
        """
        if not self._available:
            logger.warning("Milvus unavailable; skipping insert_chunks")
            return []

        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) must have the same length"
            )

        records: List[Dict[str, Any]] = []
        for chunk, vector in zip(chunks, embeddings):
            records.append(
                {
                    "id": str(chunk.id),
                    "chunk_id": str(chunk.chunk_id),
                    "doc_id": str(chunk.doc_id),
                    "kb_id": str(chunk.kb_id),
                    "modality": str(chunk.modality) if chunk.modality else "text",
                    "doc_acl_version": str(chunk.doc_acl_version)
                    if chunk.doc_acl_version
                    else "",
                    "max_keyword_level": int(chunk.max_keyword_level)
                    if chunk.max_keyword_level is not None
                    else 0,
                    "tags": list(chunk.tags) if chunk.tags else [],
                    "created_by": str(chunk.created_by) if chunk.created_by else "",
                    "status": str(chunk.status) if chunk.status else "active",
                    "embedding": vector,
                }
            )

        return self.insert(self.text_collection_name, records)

    def search_text(
        self,
        query_embedding: List[float],
        filter_expr: str = "",
        top_k: int = 10,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Dense-vector search over the text chunk collection."""
        return self.search(
            self.text_collection_name,
            query_embedding,
            filter_expr=filter_expr,
            top_k=top_k,
            **kwargs,
        )

    def search_image(
        self,
        image_embedding: List[float],
        filter_expr: str = "",
        top_k: int = 10,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Dense-vector search over the image/video keyframe collection."""
        return self.search(
            self.image_collection_name,
            image_embedding,
            filter_expr=filter_expr,
            top_k=top_k,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Internal utilities
    # ------------------------------------------------------------------
    @staticmethod
    def _eq_expr(field: str, value: str) -> str:
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
        return f'{field} == "{escaped}"'

    @staticmethod
    def _parse_search_results(results: Any) -> List[Dict[str, Any]]:
        parsed: List[Dict[str, Any]] = []
        for hits in results:
            for hit in hits:
                entity = hit.entity.to_dict()
                entity["score"] = hit.score
                parsed.append(entity)
        return parsed

    def _default_output_fields(self, collection_name: str) -> List[str]:
        if collection_name == self.image_collection_name:
            return ["id", "chunk_id", "doc_id", "kb_id", "frame_index", "image_url"]
        return [
            "id",
            "chunk_id",
            "doc_id",
            "kb_id",
            "modality",
            "doc_acl_version",
            "max_keyword_level",
            "tags",
            "created_by",
            "status",
        ]


# Module-level singleton for convenience.
milvus_store = MilvusVectorStore()
