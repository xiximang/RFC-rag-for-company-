"""SQLAlchemy models package."""
from app.models.api_key import ApiKey
from app.models.audit import AuditLog
from app.models.chunk import Chunk
from app.models.collaboration import Bookmark, Comment
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.evaluation import EvaluationDataset, EvaluationQuestionRun, EvaluationTask
from app.models.group import UserGroup
from app.models.keyword import KeywordMatchLog, SensitiveKeyword
from app.models.knowledge_base import KnowledgeBase
from app.models.message import Message
from app.models.permission import (
    DocumentPermission,
    FieldPermission,
    FileTypePermission,
    GroupPermission,
    TagPermission,
)
from app.models.search_history import SearchHistory
from app.models.system_config import SystemConfig
from app.models.tag import Tag, chunk_tags, document_tags
from app.models.user import User

try:
    from app.models.vector import ImageFrameVector, TextChunkVector
except Exception:  # pragma: no cover
    ImageFrameVector = None  # type: ignore
    TextChunkVector = None  # type: ignore

__all__ = [
    "ApiKey",
    "SystemConfig",
    "AuditLog",
    "Bookmark",
    "Chunk",
    "Comment",
    "Conversation",
    "Document",
    "EvaluationDataset",
    "EvaluationQuestionRun",
    "EvaluationTask",
    "UserGroup",
    "KeywordMatchLog",
    "SensitiveKeyword",
    "KnowledgeBase",
    "Message",
    "DocumentPermission",
    "FieldPermission",
    "FileTypePermission",
    "GroupPermission",
    "TagPermission",
    "SearchHistory",
    "Tag",
    "chunk_tags",
    "document_tags",
    "User",
    "TextChunkVector",
    "ImageFrameVector",
]
