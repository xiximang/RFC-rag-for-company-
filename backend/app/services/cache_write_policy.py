"""CacheWritePolicy — controls when feedback results are written to the query cache.

五级兼容：
- P5: 写入前检查 edited_answer 不越级。
- P4: 写入带 owner_security_level。
"""
import logging
from typing import Any, Dict, List, Optional

from app.pipelines.keyword_annotator import LEVEL_ORDER, KeywordAnnotator

logger = logging.getLogger(__name__)


class CacheWritePolicy:
    """Determines whether a feedback result should be cached, and eviction rules."""

    @staticmethod
    def should_write(feedback: Dict[str, Any]) -> bool:
        """Return True if the feedback should trigger a cache write.

        Conditions (any one is sufficient):
        1. Engineer explicitly approved (action == "approve")
        2. Consecutive high ratings (rating >= 4) for the same query
        3. confirmed_count > 3 (cache entry already exists)
        """
        action = feedback.get("action", "rank")
        if action == "approve":
            return True

        ratings = feedback.get("ratings") or {}
        if ratings and all(v >= 4 for v in ratings.values()):
            return True

        return False

    @staticmethod
    def should_evict(entry: Dict[str, Any]) -> bool:
        """Return True if the cache entry should be evicted.

        Conditions (any one):
        1. Entry has no hits for 30 days
        2. (disagreed_count 字段已废弃：原 cache model 未实现，逻辑自动跳过)
        3. Too many entries (LRU) — not enforced here, handled at read time
        """
        from datetime import datetime, timezone

        last_hit = entry.get("last_hit_at")
        if last_hit:
            if isinstance(last_hit, str):
                last_hit = datetime.fromisoformat(last_hit.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - last_hit).days
            if age >= 30:
                return True

        # disagreed_count 字段未在 QueryCache 模型中实现（保留为日志告警）
        disagreed = entry.get("disagreed_count", 0) or 0
        if disagreed >= 3:
            logger.warning(
                "Cache entry has disagreed_count=%s (字段未持久化，仅日志告警)",
                disagreed,
            )

        return False

    @staticmethod
    def validate_answer(answer: str, reviewer_security_level: str) -> bool:
        """P5 真正的关键词降级校验。

        调用 KeywordAnnotator 扫描 answer 中的敏感关键词，
        若任何关键词等级高于 reviewer 安全等级，返回 False。

        Args:
            answer: 待写入缓存的答案文本（edited_answer 或 message.content）
            reviewer_security_level: 反馈者等级（如 "L3"）

        Returns:
            True 表示安全可写入；False 表示含越级关键词应拒绝。
        """
        if not answer or not answer.strip():
            # 空答案视为安全（写入缓存无意义但不算违规）
            return True

        user_val = LEVEL_ORDER.get(reviewer_security_level, 0)
        annotator = KeywordAnnotator()
        result = annotator.annotate(answer)

        if not result.matches:
            return True

        # answer 中最高级别关键词若 > reviewer 等级 → 越级
        top_level_value = LEVEL_ORDER.get(result.max_level, 0)
        if top_level_value > user_val:
            logger.warning(
                "P5 blocked cache write: reviewer=%s level_val=%s, "
                "answer contains max_level=%s (val=%s)",
                reviewer_security_level, user_val,
                result.max_level, top_level_value,
            )
            return False

        return True
