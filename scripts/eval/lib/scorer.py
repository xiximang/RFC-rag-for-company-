"""加权汇总：retrieval × 0.6 + llm × 0.4。

输出同时给原始 0~1 与百分制 final_score_100，便于人类直观阅读。

安全维度不计入（由 backend/tests/test_*_*.py 独立覆盖）。
"""
from __future__ import annotations

from .config import WEIGHTS, RETRIEVAL_BREAKDOWN, LLM_BREAKDOWN


def _weighted_sum(metrics: dict, breakdown: dict) -> tuple[float, dict]:
    """对一组指标按权重求加权和。"""
    parts = {}
    total = 0.0
    for k, w in breakdown.items():
        v = float(metrics.get(k, 0.0))
        parts[k] = {"value": round(v, 4), "weight": w, "weighted": round(v * w, 4)}
        total += v * w
    return total, parts


def compute_final_score(retrieval_metrics: dict, llm_metrics: dict | None = None) -> dict:
    """计算最终权重分。

    retrieval_metrics: 来自 retrieval_eval（必填）
    llm_metrics: 来自 llm_judge（None 或缺字段视为 0）
    """
    llm_metrics = llm_metrics or {}

    retrieval_score, retrieval_parts = _weighted_sum(retrieval_metrics, RETRIEVAL_BREAKDOWN)
    llm_score, llm_parts = _weighted_sum(llm_metrics, LLM_BREAKDOWN)

    final = retrieval_score * WEIGHTS["retrieval"] + llm_score * WEIGHTS["llm"]

    return {
        "final_score": round(final, 4),
        "final_score_100": round(final * 100, 2),
        "breakdown": {
            "retrieval": {
                "weight": WEIGHTS["retrieval"],
                "score": round(retrieval_score, 4),
                "weighted": round(retrieval_score * WEIGHTS["retrieval"], 4),
                "parts": retrieval_parts,
            },
            "llm": {
                "weight": WEIGHTS["llm"],
                "score": round(llm_score, 4),
                "weighted": round(llm_score * WEIGHTS["llm"], 4),
                "parts": llm_parts,
                "samples_judged": llm_metrics.get("samples_judged", 0),
                "total_samples": llm_metrics.get("total_samples", 0),
            },
        },
        "security_note": "安全拦截由 backend/tests/test_*_*.py 独立覆盖，不计入此分",
    }
