"""Prometheus metrics for the RAG backend.

Metrics are defined once at import time and can be imported anywhere in the
application to observe request-level, retrieval, generation and security events.
"""

from prometheus_client import Counter, Histogram

# ---------------------------------------------------------------------------
# API request metrics
# ---------------------------------------------------------------------------
rag_api_requests_total = Counter(
    "rag_api_requests_total",
    "Total number of API requests handled by the backend.",
    ["method", "endpoint", "status"],
)

rag_api_request_duration_seconds = Histogram(
    "rag_api_request_duration_seconds",
    "API request latency in seconds.",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30],
)

# ---------------------------------------------------------------------------
# RAG-specific metrics
# ---------------------------------------------------------------------------
rag_retrieval_duration_seconds = Histogram(
    "rag_retrieval_duration_seconds",
    "End-to-end retrieval latency in seconds.",
    ["mode"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
)

rag_generation_duration_seconds = Histogram(
    "rag_generation_duration_seconds",
    "LLM generation call latency in seconds.",
    ["model", "status"],
    buckets=[0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60],
)

rag_permission_intercepts_total = Counter(
    "rag_permission_intercepts_total",
    "Number of requests intercepted for security or permission reasons.",
    ["reason"],
)

# ---------------------------------------------------------------------------
# RAG retrieval quality metrics (BadCase auto-alerting)
# ---------------------------------------------------------------------------
rag_rerank_reordered_total = Counter(
    "rag_rerank_reordered_total",
    "Number of candidates whose position changed after rerank",
    ["mode"],
)

rag_rerank_total = Counter(
    "rag_rerank_total",
    "Total rerank calls",
    ["mode"],
)

rag_zero_result_total = Counter(
    "rag_zero_result_total",
    "Number of queries returning 0 results",
    ["mode"],
)

rag_top_doc_concentration = Histogram(
    "rag_top_doc_concentration",
    "Concentration of top documents in result (1.0 = all same doc)",
    ["mode"],
    buckets=(0.2, 0.4, 0.6, 0.8, 1.0),
)

rag_rerank_fallback_total = Counter(
    "rag_rerank_fallback_total",
    "Number of times rerank API failed and fell back to original order",
    ["mode"],
)
