"""加权汇总：retrieval × 0.6 + llm × 0.4 + embedding_precision（独立报告）。

输出同时给原始 0~1 与百分制 final_score_100，便于人类直观阅读。

安全维度不计入（由 backend/tests/test_*_*.py 独立覆盖）。
"""
from __future__ import annotations

from pathlib import Path

from .config import WEIGHTS, RETRIEVAL_BREAKDOWN, LLM_BREAKDOWN

BASELINE_PATH = Path("scripts/eval/baselines/baseline.json")


def _weighted_sum(metrics: dict, breakdown: dict) -> tuple[float, dict]:
    """对一组指标按权重求加权和。"""
    parts = {}
    total = 0.0
    for k, w in breakdown.items():
        v = float(metrics.get(k, 0.0))
        parts[k] = {"value": round(v, 4), "weight": w, "weighted": round(v * w, 4)}
        total += v * w
    return total, parts


def compute_by_category(per_query: list[dict]) -> dict:
    """按 category 分桶汇总检索指标（v2 模板专用）。

    每个 category 输出：count + recall@10 + mrr + ndcg@10 (primary mode 平均)
    """
    buckets: dict[str, dict] = {}
    for q in per_query:
        cat = q.get("category") or "unknown"
        primary_mode_metrics = next(
            (v for v in q.get("modes", {}).values() if "recall_at_10" in v),
            None,
        )
        if not primary_mode_metrics:
            continue
        if cat not in buckets:
            buckets[cat] = {"count": 0, "sum_recall_at_10": 0, "sum_mrr": 0, "sum_ndcg_at_10": 0}
        buckets[cat]["count"] += 1
        buckets[cat]["sum_recall_at_10"] += primary_mode_metrics.get("recall_at_10", 0)
        buckets[cat]["sum_mrr"]          += primary_mode_metrics.get("mrr", 0)
        buckets[cat]["sum_ndcg_at_10"]   += primary_mode_metrics.get("ndcg_at_10", 0)

    result = {}
    for cat, st in buckets.items():
        n = st["count"]
        result[cat] = {
            "count": n,
            "recall_at_10": round(st["sum_recall_at_10"] / n, 4) if n else 0,
            "mrr":          round(st["sum_mrr"] / n, 4) if n else 0,
            "ndcg_at_10":   round(st["sum_ndcg_at_10"] / n, 4) if n else 0,
        }
    return result


def load_baseline(path: Path = BASELINE_PATH) -> dict | None:
    """加载 baseline JSON（如果存在）。"""
    import json as _json
    p = Path(path)
    if not p.exists():
        return None
    try:
        return _json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def compare_with_baseline(current: dict, baseline: dict) -> dict:
    """对比当前评测与 baseline。

    返回：
      - deltas: 每个指标的变化（正数=改进，负数=退化）
      - regressed: 退化指标列表
      - improved:  改进指标列表
    """
    cur_metrics = current.get("breakdown", {}) or {}
    cur_ret = cur_metrics.get("retrieval", {}).get("score", 0)
    cur_llm = cur_metrics.get("llm", {}).get("score", 0)
    cur_emb = (current.get("embedding_precision") or {}).get("precision")

    base_metrics = baseline.get("breakdown", {}) or {}
    base_ret = base_metrics.get("retrieval", {}).get("score", 0)
    base_llm = base_metrics.get("llm", {}).get("score", 0)
    base_emb = (baseline.get("embedding_precision") or {}).get("precision")

    deltas = {
        "retrieval_score": round(cur_ret - base_ret, 4),
        "llm_score":       round(cur_llm - base_llm, 4),
        "embedding_precision": round((cur_emb or 0) - (base_emb or 0), 4),
    }
    regressed = []
    improved = []
    for k, v in deltas.items():
        if v > 0.005:
            improved.append({"metric": k, "delta": v})
        elif v < -0.005:
            regressed.append({"metric": k, "delta": v})
    return {"deltas": deltas, "improved": improved, "regressed": regressed}


def compute_embedding_precision(per_query: list[dict]) -> dict:
    """向量化精准度：直接量化 cosine 距离 vs 阈值。

    输入 per_query: 每条 query 的评测结果，必须包含：
      - quality.max_allowed_distance: 该 query 允许的最大 cosine 距离
      - top1_cosine_distance: 实际检索 Top-1 的 cosine 距离

    输出：
      - precision: 通过阈值的比例 (0~1)
      - mean_distance: 平均距离
      - max_distance: 最大距离
      - fail_queries: 未通过阈值的 query 列表
    """
    if not per_query:
        return {
            "precision": 1.0,
            "samples": 0,
            "mean_distance": 0.0,
            "max_distance": 0.0,
            "pass_threshold_count": 0,
            "fail_threshold_count": 0,
            "fail_queries": [],
            "note": "无 per_query 数据",
        }

    distances = []
    fail_queries = []
    pass_count = 0

    for q in per_query:
        quality = q.get("quality") or {}
        threshold = quality.get("max_allowed_distance")
        distance = q.get("top1_cosine_distance")

        # 兼容：阈值可能写在 metadata_eval.scores.max_allowed_distance
        if threshold is None:
            threshold = (q.get("metadata_eval") or {}).get("scores", {}).get("max_allowed_distance")
        # 兼容：distance 也可能在 metadata_eval.scores
        if distance is None:
            distance = (q.get("metadata_eval") or {}).get("scores", {}).get("top1_cosine_distance")

        if distance is None or threshold is None:
            continue

        distance = float(distance)
        threshold = float(threshold)
        distances.append(distance)

        if distance <= threshold:
            pass_count += 1
        else:
            fail_queries.append({
                "id": q.get("id"),
                "question": q.get("question", "")[:60],
                "distance": round(distance, 4),
                "threshold": threshold,
                "diagnostic_intent": quality.get("diagnostic_intent", "unknown"),
            })

    if not distances:
        return {
            "precision": None,
            "samples": 0,
            "mean_distance": None,
            "max_distance": None,
            "pass_threshold_count": 0,
            "fail_threshold_count": 0,
            "fail_queries": [],
            "note": "未发现 max_allowed_distance / top1_cosine_distance 字段，跳过",
        }

    return {
        "precision": round(pass_count / len(distances), 4),
        "samples": len(distances),
        "mean_distance": round(sum(distances) / len(distances), 4),
        "max_distance": round(max(distances), 4),
        "pass_threshold_count": pass_count,
        "fail_threshold_count": len(distances) - pass_count,
        "fail_queries": fail_queries,
    }


def compute_final_score(retrieval_metrics: dict, llm_metrics: dict | None = None,
                        per_query: list[dict] | None = None) -> dict:
    """计算最终权重分。

    retrieval_metrics: 来自 retrieval_eval（必填）
    llm_metrics: 来自 llm_judge（None 或缺字段视为 0）
    per_query: 每条 query 的完整评测结果（用于计算 embedding_precision，可选）
    """
    llm_metrics = llm_metrics or {}
    per_query = per_query or []

    retrieval_score, retrieval_parts = _weighted_sum(retrieval_metrics, RETRIEVAL_BREAKDOWN)
    llm_score, llm_parts = _weighted_sum(llm_metrics, LLM_BREAKDOWN)

    final = retrieval_score * WEIGHTS["retrieval"] + llm_score * WEIGHTS["llm"]

    embedding_precision = compute_embedding_precision(per_query)
    by_category = compute_by_category(per_query)

    # baseline 对比（可选）
    baseline_compare = None
    baseline = load_baseline()
    if baseline:
        baseline_compare = compare_with_baseline(
            current={
                "breakdown": {
                    "retrieval": {"score": retrieval_score},
                    "llm":       {"score": llm_score},
                },
                "embedding_precision": embedding_precision,
            },
            baseline=baseline,
        )

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
                "by_category": llm_metrics.get("by_category", {}),
            },
        },
        "embedding_precision": embedding_precision,
        "by_category": by_category,
        "baseline_compare": baseline_compare,
        "security_note": "安全拦截由 backend/tests/test_*_*.py 独立覆盖，不计入此分",
    }
