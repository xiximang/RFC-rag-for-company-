import re
from typing import Dict, Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheManager
from app.core.metrics import rag_permission_intercepts_total
from app.pipelines.keyword_annotator import LEVEL_ORDER
from app.services.keyword_service import KeywordService
from app.services.permission_service import PermissionService
from app.services.prompt_injection_classifier import prompt_injection_classifier


# Common prompt-injection / jailbreak indicators used for lightweight detection.
# These patterns are intentionally conservative to minimize false positives.
PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(?:the\s+)?(?:above\s+|previous\s+)?instructions?",
    r"disregard\s+(?:the\s+)?(?:above\s+|previous\s+)?(?:system\s+)?prompt?",
    r"you\s+are\s+now\s+(?:in\s+)?(?:.*\s+)?mode",
    r"(?:do\s+anything\s+now|DAN)",
    r"pretend\s+you\s+(?:are|have)",
    r"act\s+as\s+.*\s+(?:no\s+restrictions?|unrestricted)",
    r"new\s+instructions?:",
    r"(?:system|developer|user)\s*:\s*",
    r"jailbreak",
    r"payload\s*:",
]


class SecurityGateway:
    """API安全网关：根据文档/查询敏感度决定调用策略"""
    
    async def _fast_level_check(
        self,
        db: AsyncSession,
        user_id: UUID,
        query: str,
    ) -> Dict[str, Any] | None:
        """Fast pre-retrieval check based on user level and query level.

        Returns a ``local_only`` strategy when the user is L4 or the query
        contains L4 keywords, avoiding expensive retrieval. Returns ``None``
        when the fast path cannot decide and full retrieval is needed.
        """
        cache = CacheManager()
        perm_service = PermissionService(db, cache)
        keyword_service = KeywordService(db)

        user_level = await perm_service.get_user_security_level(user_id)
        user_level_value = LEVEL_ORDER.get(user_level, 0)

        annotator = await keyword_service._get_annotator()
        query_result = annotator.annotate(query)
        query_level_value = query_result.max_level_value

        max_level = max(user_level_value, query_level_value)

        if max_level >= 4:
            rag_permission_intercepts_total.labels(
                reason="local_only_high_security_level"
            ).inc()
            return {
                "strategy": "local_only",
                "max_level": max_level,
                "reason": "绝密内容禁止调用外部API",
            }
        return None

    async def decide_api_strategy(
        self,
        db: AsyncSession,
        user_id: UUID,
        context_chunks: list,
        query: str
    ) -> Dict[str, Any]:
        """
        三级策略：
        - L4绝密：本地处理，禁止调用外部API
        - L3机密：实体脱敏后调用API
        - L2及以下：直接调用外部API
        """
        cache = CacheManager()
        perm_service = PermissionService(db, cache)
        keyword_service = KeywordService(db)

        user_level = await perm_service.get_user_security_level(user_id)
        user_level_value = LEVEL_ORDER.get(user_level, 0)

        # 上下文最大敏感级别
        max_ctx_level = 0
        for chunk in context_chunks:
            max_ctx_level = max(
                max_ctx_level,
                chunk.get("max_keyword_level_value") or LEVEL_ORDER.get(chunk.get("max_keyword_level", "L0"), 0)
            )

        # 查询本身敏感级别
        annotator = await keyword_service._get_annotator()
        query_result = annotator.annotate(query)
        query_level_value = query_result.max_level_value

        max_level = max(user_level_value, max_ctx_level, query_level_value)

        if max_level >= 4:
            strategy = "local_only"
            reason = "绝密内容禁止调用外部API"
            rag_permission_intercepts_total.labels(
                reason="local_only_high_security_level"
            ).inc()
        elif max_level == 3:
            strategy = "masked_api"
            reason = "机密内容需实体脱敏后调用API"
        else:
            strategy = "direct_api"
            reason = "可直接调用外部API"

        return {
            "strategy": strategy,
            "max_level": max_level,
            "reason": reason
        }
    
    def detect_prompt_injection(self, query: str) -> bool:
        """Detect prompt-injection / jailbreak attempts.

        Uses a two-stage defence:

        1. Conservative static regex patterns catch obvious prefix attacks.
        2. A lightweight classifier scores the query and blocks when the
           score exceeds ``PROMPT_INJECTION_THRESHOLD`` (default 0.7).

        The classifier reduces false positives from long benign documents
        because its features are keyword-density and length-normalized.
        """
        if not query:
            return False

        text = query.lower()
        static_hit = any(re.search(pattern, text) for pattern in PROMPT_INJECTION_PATTERNS)

        result = prompt_injection_classifier.classify(query)
        classifier_hit = result["score"] >= result["threshold"]

        return static_hit or classifier_hit

    def mask_entities(self, text: str) -> str:
        """L3机密内容：对常见实体做脱敏"""
        text = re.sub(r"1[3-9]\d{9}", "[PHONE]", text)
        text = re.sub(r"\d{17}[\dXx]", "[IDCARD]", text)
        text = re.sub(r"[\w.-]+@[\w.-]+\.[a-zA-Z]{2,}", "[EMAIL]", text)
        text = re.sub(r"\d+\.?\d*\s*[万元]", "[MONEY]", text)
        return text

security_gateway = SecurityGateway()
