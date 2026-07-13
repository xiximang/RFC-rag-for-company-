"""Lightweight prompt-injection classifier (no external model).

The classifier combines multiple lightweight heuristics to produce a 0.0-1.0
risk score. It is intentionally designed to reduce false positives from long
benign queries while still catching obvious injection / jailbreak attempts.
"""

import os
import re
from typing import Dict, List, Tuple


# Weighted static patterns.  Each match contributes to the regex dimension,
# but the final decision is based on the combined score rather than a single
# pattern, which reduces false positives from isolated keyword mentions.
DEFAULT_REGEX_PATTERNS: List[Tuple[str, float]] = [
    (r"ignore\s+(?:the\s+)?(?:above\s+|previous\s+)?instructions?", 1.00),
    (r"disregard\s+(?:the\s+)?(?:above\s+|previous\s+)?(?:system\s+)?prompt?", 1.00),
    (r"you\s+are\s+now\s+(?:in\s+)?(?:.*\s+)?mode", 0.80),
    (r"(?:do\s+anything\s+now|DAN)", 1.00),
    (r"pretend\s+you\s+(?:are|have)", 0.80),
    (r"act\s+as\s+.*\s+(?:no\s+restrictions?|unrestricted)", 0.80),
    (r"new\s+instructions?:", 0.80),
    (r"(?:system|developer|user)\s*:\s*", 0.60),
    (r"jailbreak", 0.80),
    (r"payload\s*:", 0.80),
]

# Phrases that indicate the user is trying to override prior instructions.
INSTRUCTION_OVERRIDE_TOKENS = [
    "ignore",
    "disregard",
    "override",
    "replace",
    "instead",
    "new instructions",
    "forget",
    "previous",
    "above",
    "system prompt",
    "ignore all",
    "do not follow",
    "no restrictions",
    "unrestricted",
]

# Phrases that indicate role-play / persona takeover.
ROLEPLAY_TOKENS = [
    "pretend",
    "act as",
    "you are now",
    "you are",
    "roleplay",
    "assume the role",
    "become a",
    "take on the role",
    "simulation",
    "hypothetical",
]

# Fake boundary / delimiter strings often used in injection payloads.
DELIMITER_TOKENS = [
    "system:",
    "developer:",
    "user:",
    "assistant:",
    "<<<",
    ">>>",
    "[/",
    "[/system]",
    "[/user]",
]


class PromptInjectionClassifier:
    """Score a query for prompt-injection / jailbreak risk.

    The score is computed from four feature groups:

    1. Regex matches: weighted static patterns, but no single match blocks.
    2. Instruction-override keyword density.
    3. Role-play / persona signals.
    4. Delimiter / colon anomalies.

    All features are length-normalized so that long benign documents are not
    misclassified as attacks. Configuration is read from environment variables
    once at import time; instantiate a new object to re-read the environment.
    """

    def __init__(
        self,
        threshold: float | None = None,
        weight_regex: float | None = None,
        weight_override: float | None = None,
        weight_roleplay: float | None = None,
        weight_delimiter: float | None = None,
        regex_patterns: List[Tuple[str, float]] | None = None,
    ) -> None:
        self.threshold = threshold if threshold is not None else float(
            os.getenv("PROMPT_INJECTION_THRESHOLD", "0.7")
        )
        self.weight_regex = weight_regex if weight_regex is not None else float(
            os.getenv("PROMPT_INJECTION_WEIGHT_REGEX", "0.50")
        )
        self.weight_override = weight_override if weight_override is not None else float(
            os.getenv("PROMPT_INJECTION_WEIGHT_OVERRIDE", "0.20")
        )
        self.weight_roleplay = weight_roleplay if weight_roleplay is not None else float(
            os.getenv("PROMPT_INJECTION_WEIGHT_ROLEPLAY", "0.20")
        )
        self.weight_delimiter = weight_delimiter if weight_delimiter is not None else float(
            os.getenv("PROMPT_INJECTION_WEIGHT_DELIMITER", "0.10")
        )
        self.regex_patterns = regex_patterns if regex_patterns is not None else DEFAULT_REGEX_PATTERNS

        total = self.weight_regex + self.weight_override + self.weight_roleplay + self.weight_delimiter
        if total == 0:
            total = 1.0
        self.weight_regex /= total
        self.weight_override /= total
        self.weight_roleplay /= total
        self.weight_delimiter /= total

    def _normalize(self, raw_score: float, text: str, min_len: int = 20) -> float:
        """Length-aware sigmoid-style normalization.

        Long texts receive a downward adjustment to prevent false positives from
        documents that merely mention sensitive words in benign contexts.
        """
        length = max(len(text.strip()), 1)
        # Scale score by length dampening; benign long texts move toward 0
        # while short injection payloads keep most of their raw score.
        factor = min(1.0, min_len / (length ** 0.60))
        return raw_score * factor

    def score(self, query: str) -> float:
        """Return a prompt-injection risk score in the range [0.0, 1.0]."""
        if not query or not query.strip():
            return 0.0

        text = query.lower()
        words = re.findall(r"\b\w+\b", text)
        word_count = max(len(words), 1)

        # 1. Regex matches
        regex_score = 0.0
        matched_patterns: List[str] = []
        for pattern, weight in self.regex_patterns:
            if re.search(pattern, text):
                regex_score += weight
                matched_patterns.append(pattern)
        regex_score = min(regex_score, 1.0)

        # 2. Instruction override keyword density
        override_hits = sum(1 for token in INSTRUCTION_OVERRIDE_TOKENS if token in text)
        override_density = override_hits / word_count
        override_score = min(override_density * 25.0, 1.0)

        # 3. Role-play signals
        roleplay_hits = sum(1 for token in ROLEPLAY_TOKENS if token in text)
        roleplay_density = roleplay_hits / word_count
        roleplay_score = min(roleplay_density * 25.0, 1.0)

        # 4. Delimiter / colon anomalies
        delimiter_hits = sum(1 for token in DELIMITER_TOKENS if token in text)
        delimiter_density = delimiter_hits / word_count
        delimiter_score = min(delimiter_density * 30.0, 1.0)

        raw_score = (
            self.weight_regex * regex_score
            + self.weight_override * override_score
            + self.weight_roleplay * roleplay_score
            + self.weight_delimiter * delimiter_score
        )

        normalized_score = self._normalize(raw_score, text)
        return round(min(max(normalized_score, 0.0), 1.0), 4)

    def classify(self, query: str) -> Dict[str, object]:
        """Return a structured classification result suitable for audit logs.

        Fields:
            score (float): risk score [0.0, 1.0]
            threshold (float): configured decision threshold
            features (dict): per-feature raw scores
            matched_patterns (list): regex patterns that matched
        """
        if not query or not query.strip():
            return {
                "score": 0.0,
                "threshold": self.threshold,
                "features": {
                    "regex": 0.0,
                    "override": 0.0,
                    "roleplay": 0.0,
                    "delimiter": 0.0,
                },
                "matched_patterns": [],
            }

        text = query.lower()
        words = re.findall(r"\b\w+\b", text)
        word_count = max(len(words), 1)

        regex_score = 0.0
        matched_patterns: List[str] = []
        for pattern, weight in self.regex_patterns:
            if re.search(pattern, text):
                regex_score += weight
                matched_patterns.append(pattern)
        regex_score = min(regex_score, 1.0)

        override_hits = sum(1 for token in INSTRUCTION_OVERRIDE_TOKENS if token in text)
        override_score = min((override_hits / word_count) * 25.0, 1.0)

        roleplay_hits = sum(1 for token in ROLEPLAY_TOKENS if token in text)
        roleplay_score = min((roleplay_hits / word_count) * 25.0, 1.0)

        delimiter_hits = sum(1 for token in DELIMITER_TOKENS if token in text)
        delimiter_score = min((delimiter_hits / word_count) * 30.0, 1.0)

        raw_score = (
            self.weight_regex * regex_score
            + self.weight_override * override_score
            + self.weight_roleplay * roleplay_score
            + self.weight_delimiter * delimiter_score
        )
        normalized_score = self._normalize(raw_score, text)
        score = round(min(max(normalized_score, 0.0), 1.0), 4)

        return {
            "score": score,
            "threshold": self.threshold,
            "features": {
                "regex": round(regex_score, 4),
                "override": round(override_score, 4),
                "roleplay": round(roleplay_score, 4),
                "delimiter": round(delimiter_score, 4),
            },
            "matched_patterns": matched_patterns,
        }


# Module-level singleton for the security gateway.
prompt_injection_classifier = PromptInjectionClassifier()
