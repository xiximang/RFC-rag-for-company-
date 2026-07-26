"""Sensitive keyword annotation using Aho-Corasick automaton."""
import re
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from app.models.chunk import Chunk
from app.models.keyword import SensitiveKeyword

try:
    import ahocorasick
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "pyahocorasick is required for keyword annotation. "
        "Install it with: pip install pyahocorasick"
    ) from exc

# L0 = public, L4 = top secret
LEVEL_ORDER = {
    "L0": 0,
    "L1": 1,
    "L2": 2,
    "L3": 3,
    "L4": 4,
}


@dataclass
class Match:
    """A single keyword match."""

    keyword_id: uuid.UUID
    keyword: str
    level: str
    category: Optional[str]
    matched_variant: str
    matched_text: str
    confidence: float = 1.0
    start: int = 0
    end: int = 0
    apply_to_modalities: List[str] = field(default_factory=list)


@dataclass
class AnnotationResult:
    """Result of annotating a piece of text."""

    max_level: Optional[str] = "L0"
    max_level_value: int = 0
    matches: List[Match] = field(default_factory=list)
    categories: Set[str] = field(default_factory=set)

    @property
    def keyword_ids(self) -> Set[uuid.UUID]:
        return {m.keyword_id for m in self.matches}


class KeywordAnnotator:
    """Annotate text/chunks with sensitive keywords via Aho-Corasick matching.

    Features:
    * Case-insensitive multi-pattern matching (powered by pyahocorasick).
    * Keyword variant expansion (e.g. "薪资" -> "工资", "薪酬", "月收入").
    * Regex keyword support for advanced patterns.
    * Modality-aware filtering when annotating chunks.
    """

    def __init__(self) -> None:
        self._keywords: List[SensitiveKeyword] = []
        self._automaton: Optional[ahocorasick.Automaton] = None
        self._regex_patterns: List[Dict] = []
        self._last_result: Optional[AnnotationResult] = None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load_keywords(self, keywords: List[SensitiveKeyword]) -> "KeywordAnnotator":
        """Build the automaton from a list of ``SensitiveKeyword`` records."""
        self._keywords = list(keywords)
        self._automaton = ahocorasick.Automaton()
        self._regex_patterns = []

        for kw in self._keywords:
            if not kw.keyword:
                continue

            if kw.match_type == "regex":
                self._load_regex_keyword(kw)
            else:
                self._load_literal_keyword(kw)

        if self._automaton:
            self._automaton.make_automaton()
        return self

    def _load_literal_keyword(self, kw: SensitiveKeyword) -> None:
        """Add a keyword and its variants to the Aho-Corasick automaton."""
        patterns = {kw.keyword}
        patterns.update(kw.variants or [])

        for raw in patterns:
            pattern = raw.strip().lower()
            if not pattern:
                continue
            value = {
                "keyword_id": kw.id,
                "keyword": kw.keyword,
                "level": kw.level,
                "category": kw.category,
                "variant": raw.strip(),
                "apply_to_modalities": list(kw.apply_to_modalities or []),
            }
            # If the same normalized pattern appears for different keywords,
            # keep a list so all of them are reported.
            if pattern in self._automaton:
                existing = self._automaton[pattern]
                if isinstance(existing, list):
                    existing.append(value)
                else:
                    self._automaton[pattern] = [existing, value]
            else:
                self._automaton.add_word(pattern, value)

    def _load_regex_keyword(self, kw: SensitiveKeyword) -> None:
        """Compile a regex-type keyword (and its variants)."""
        patterns = [kw.keyword]
        patterns.extend(kw.variants or [])

        for raw in patterns:
            pattern = raw.strip()
            if not pattern:
                continue
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
            except re.error:
                # Skip malformed regex patterns rather than crashing ingestion.
                continue
            self._regex_patterns.append(
                {
                    "compiled": compiled,
                    "keyword_id": kw.id,
                    "keyword": kw.keyword,
                    "level": kw.level,
                    "category": kw.category,
                    "variant": pattern,
                    "apply_to_modalities": list(kw.apply_to_modalities or []),
                }
            )

    # ------------------------------------------------------------------
    # Annotation
    # ------------------------------------------------------------------
    def annotate(self, text: str) -> AnnotationResult:
        """Scan ``text`` and return all matched keyword information."""
        if not text:
            return AnnotationResult()

        result = AnnotationResult()
        lower_text = text.lower()
        seen: set = set()

        if self._automaton:
            for end_index, payload in self._automaton.iter(lower_text):
                entries = payload if isinstance(payload, list) else [payload]
                for value in entries:
                    variant_norm = value["variant"].lower()
                    start = end_index - len(variant_norm) + 1
                    if start < 0:
                        continue
                    end = end_index + 1
                    key = (value["keyword_id"], start, end)
                    if key in seen:
                        continue
                    seen.add(key)

                    matched_variant = text[start:end]
                    matched_text = self._snippet(text, start, end)
                    self._append_match(result, value, matched_variant, matched_text, start, end)

        for item in self._regex_patterns:
            for m in item["compiled"].finditer(text):
                start, end = m.start(), m.end()
                key = (item["keyword_id"], start, end)
                if key in seen:
                    continue
                seen.add(key)
                matched_variant = m.group(0)
                matched_text = self._snippet(text, start, end)
                self._append_match(
                    result,
                    item,
                    matched_variant,
                    matched_text,
                    start,
                    end,
                    confidence=1.0,
                )

        if result.matches:
            top_match = max(
                result.matches, key=lambda m: LEVEL_ORDER.get(m.level, -1)
            )
            result.max_level = top_match.level
            result.max_level_value = LEVEL_ORDER[result.max_level]
            result.categories = {m.category for m in result.matches if m.category}
        else:
            result.max_level = "L0"
            result.max_level_value = 0

        return result

    @staticmethod
    def _snippet(text: str, start: int, end: int, window: int = 10) -> str:
        """Extract a short snippet around a match."""
        snippet_start = max(0, start - window)
        snippet_end = min(len(text), end + window)
        return text[snippet_start:snippet_end]

    def _append_match(
        self,
        result: AnnotationResult,
        value: Dict,
        matched_variant: str,
        matched_text: str,
        start: int,
        end: int,
        confidence: float = 1.0,
    ) -> None:
        result.matches.append(
            Match(
                keyword_id=value["keyword_id"],
                keyword=value["keyword"],
                level=value["level"],
                category=value.get("category"),
                matched_variant=matched_variant,
                matched_text=matched_text,
                confidence=confidence,
                start=start,
                end=end,
                apply_to_modalities=value.get("apply_to_modalities", []),
            )
        )

    # ------------------------------------------------------------------
    # Chunk annotation
    # ------------------------------------------------------------------
    def annotate_chunk(self, chunk: Chunk) -> Chunk:
        """Annotate a ``Chunk`` and persist the result in ``metadata_``."""
        if chunk is None:
            return chunk

        result = self.annotate(chunk.content or "")

        # Filter by chunk modality if the keyword specifies applicable modalities.
        modality = chunk.modality
        filtered = [
            m
            for m in result.matches
            if not m.apply_to_modalities
            or (modality is not None and modality in m.apply_to_modalities)
        ]

        if filtered:
            top_match = max(
                filtered, key=lambda m: LEVEL_ORDER.get(m.level, -1)
            )
            max_level = top_match.level
            categories = {m.category for m in filtered if m.category}
            keyword_ids = {str(m.keyword_id) for m in filtered}
        else:
            max_level = "L0"
            categories = set()
            keyword_ids = set()

        metadata = chunk.metadata_ or {}
        metadata["max_keyword_level"] = max_level
        metadata["max_keyword_level_value"] = LEVEL_ORDER.get(max_level, 0)
        metadata["sensitive_keywords"] = sorted(keyword_ids)
        metadata["sensitive_categories"] = sorted(categories)
        metadata["keyword_match_count"] = len(filtered)
        chunk.metadata_ = metadata

        self._last_result = AnnotationResult(
            max_level=max_level,
            max_level_value=LEVEL_ORDER.get(max_level, 0),
            matches=filtered,
            categories=categories,
        )
        return chunk

    @property
    def last_annotation_result(self) -> Optional[AnnotationResult]:
        """Return the result produced by the last ``annotate_chunk`` call."""
        return self._last_result


# ---------------------------------------------------------------------------
# 公共工具：用于 cache_matcher / cache_service 复用的 token 化
# ---------------------------------------------------------------------------
STOPWORDS: Set[str] = {
    "的", "了", "是", "什么", "怎么", "如何", "有", "在", "和", "就",
    "不", "也", "都", "而", "与", "或",
}


# ---------------------------------------------------------------------------
# 修正：上面 tokenize 用了 \w+ 不支持中文，改用 unicode 区间（与
# evaluation_service._tokenize_query 一致）。
# ---------------------------------------------------------------------------
def tokenize(text: str) -> Set[str]:
    """把文本 token 化为小写字符集合（中文+英文+数字），去除停用词。

    中文按 [\u4e00-\u9fff] 单字/词保留。
    """
    if not text:
        return set()
    return set(re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", text.lower())) - STOPWORDS
