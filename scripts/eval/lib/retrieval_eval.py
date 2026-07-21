"""离线检索评测：不调用任何 LLM。

输入：queries 列表（每项含 expected_chunks）+ kb_ids + auth_headers
输出：(aggregate_metrics, per_query_records, failed_records)

指标：Recall@10, MRR, NDCG@10, Precision@5

兼容已有的 eval_retrieval_ups.py 数据集格式（filename_chunkN）。
"""
from __future__ import annotations

import json
import math
from typing import Iterable

import requests

from .config import DEFAULT_MODES, DEFAULT_TOP_K, HYBRID_MODE


def _normalize_chunk_id(s: str) -> str:
    """标准化 chunk_id：去空白、转小写。"""
    return str(s).strip().lower()


def _expected_set(expected_chunks: Iterable[str]) -> set[str]:
    return {_normalize_chunk_id(c) for c in (expected_chunks or []) if str(c).strip()}


def _search(query: str, mode: str, kb_ids: list[str], top_k: int, headers: dict,
            base_url: str, timeout: int = 30) -> list[str]:
    """调用 /api/v1/search，返回命中的 chunk_id 列表（按相关度排序）。

    chunk_id 构造规则：
      优先使用 SearchResponse 的 position_info.source + position_info.chunk_index
      拼出 "{filename}_chunk{N}"，与 eval_retrieval_ups.py / datasets/ups_v1.jsonl 保持一致。
    """
    url = f"{base_url.rstrip('/')}/api/v1/search"
    payload = {
        "query": query,
        "kb_ids": kb_ids,
        "mode": mode,
        "top_k": top_k,
        "rerank_top_k": max(3, min(top_k, 10)),
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    chunks: list[str] = []
    for item in data.get("results", []) or data.get("items", []):
        pos = item.get("position_info") or {}
        filename = pos.get("source") or ""
        chunk_index = pos.get("chunk_index")
        if filename and chunk_index is not None:
            chunk_id = f"{filename}_chunk{chunk_index}"
        else:
            chunk_id = item.get("chunk_id") or item.get("id") or ""
        if chunk_id:
            chunks.append(_normalize_chunk_id(chunk_id))
    return chunks


def _recall_at_k(retrieved: list[str], expected: set[str], k: int) -> float:
    if not expected:
        return 0.0
    return len(set(retrieved[:k]) & expected) / len(expected)


def _mrr(retrieved: list[str], expected: set[str]) -> float:
    if not expected:
        return 0.0
    for i, chunk in enumerate(retrieved, start=1):
        if chunk in expected:
            return 1.0 / i
    return 0.0


def _ndcg_at_k(retrieved: list[str], expected: set[str], k: int) -> float:
    if not expected:
        return 0.0
    dcg = 0.0
    for i, chunk in enumerate(retrieved[:k], start=1):
        if chunk in expected:
            dcg += 1.0 / math.log2(i + 1)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(expected), k) + 1))
    return dcg / ideal if ideal > 0 else 0.0


def _precision_at_k(retrieved: list[str], expected: set[str], k: int) -> float:
    if k == 0:
        return 0.0
    return len(set(retrieved[:k]) & expected) / k


def run_retrieval_eval(
    queries: list[dict],
    kb_ids: list[str],
    headers: dict,
    base_url: str = "http://localhost:8080",
    modes: list[str] | None = None,
    top_k: int = DEFAULT_TOP_K,
    primary_mode: str = HYBRID_MODE,
) -> tuple[dict, list[dict], list[dict]]:
    """主入口。

    返回：
        aggregate_metrics: {
            "recall_at_10": ..., "mrr": ..., "ndcg_at_10": ..., "precision_at_5": ...,
            "per_mode": {"semantic": {...}, "keyword": {...}, "hybrid": {...}}
        }
        per_query: 每个 query 一条记录（含各模式的命中情况）
        failed: 失败的 query（含错误原因）
    """
    modes = modes or DEFAULT_MODES
    per_query: list[dict] = []
    failed: list[dict] = []

    # 预聚合（按 mode 区分）
    per_mode_records: dict[str, list[dict]] = {m: [] for m in modes}

    for q in queries:
        # v2 兼容：id 字段、question 字段
        qid = q.get("query_id") or q.get("id") or ""
        query_text = q.get("query") or q.get("question") or ""
        # v2 兼容：expected_chunks 在 ground_truth.chunk_ids
        expected_raw = q.get("expected_chunks")
        if expected_raw is None:
            gt = q.get("ground_truth") or {}
            expected_raw = gt.get("chunk_ids") or gt.get("chunks") or []
        expected = _expected_set(expected_raw)

        # v2: per-query retrieval_config 覆盖（mode / top_k / rerank_top_k）
        cfg = q.get("retrieval_config") or {}

        record = {
            "query_id": qid,
            "query": query_text,
            "expected_chunks": sorted(expected),
            "modes": {},
        }

        # v2 元数据透传
        meta = q.get("metadata") or {}
        if meta.get("category"):
            record["category"] = meta["category"]
        if meta.get("difficulty"):
            record["difficulty"] = meta["difficulty"]
        if meta.get("tags"):
            record["tags"] = meta["tags"]
        if (q.get("quality") or {}).get("diagnostic_intent"):
            record["diagnostic_intent"] = q["quality"]["diagnostic_intent"]
            record["rationale"] = (q.get("quality") or {}).get("rationale")
        if (q.get("quality") or {}).get("max_allowed_distance") is not None:
            record["max_allowed_distance"] = q["quality"]["max_allowed_distance"]

        any_error = False
        # 默认用 v2 提供的 mode，否则跑全集
        query_modes = [cfg.get("mode")] if cfg.get("mode") else modes
        query_top_k = cfg.get("top_k") or top_k

        for mode in query_modes:
            try:
                retrieved = _search(query_text, mode, kb_ids, query_top_k, headers, base_url)
                # 记录 Top-1 cosine 距离（如果可以从 score 推算：score=1-distance）
                top1_distance = None
                for r_meta, r_chunk in [(i, retrieved[i]) for i in range(min(1, len(retrieved)))]:
                    pass
                # 我们暂时无法从 search 响应直接拿到 distance，需要后端 /search 返回 1 - score
                # 但 search 返回的是 rerank_score（cosine 相似度），所以 1 - score ≈ distance
                # 这里先由 run_eval.py 提供 top1_distance（如有 _search_extended 接口）
            except Exception as exc:
                any_error = True
                record["modes"][mode] = {"error": str(exc)}
                per_mode_records.setdefault(mode, []).append({"query_id": qid, "error": str(exc)})
                continue

            metrics = {
                "recall_at_10":   round(_recall_at_k(retrieved, expected, 10), 4),
                "recall_at_30":   round(_recall_at_k(retrieved, expected, 30), 4),
                "mrr":            round(_mrr(retrieved, expected), 4),
                "ndcg_at_10":     round(_ndcg_at_k(retrieved, expected, 10), 4),
                "precision_at_5": round(_precision_at_k(retrieved, expected, 5), 4),
                "top_retrieved": retrieved[:10],
                "hit_count": len(set(retrieved) & expected),
            }
            record["modes"][mode] = metrics
            per_mode_records.setdefault(mode, []).append({
                "query_id": qid,
                "expected": sorted(expected),
                "retrieved": retrieved[:30],
                "metrics": metrics,
            })

        per_query.append(record)
        if any_error and all("error" in record["modes"].get(m, {}) for m in query_modes):
            failed.append({
                "query_id": qid,
                "query": query_text,
                "reason": "all modes failed",
                "diagnostic_intent": record.get("diagnostic_intent"),
            })

    # 汇总（用所有出现过的 mode 一起聚合）
    all_modes = set(per_mode_records.keys())
    aggregate: dict = {"per_mode": {}}
    for mode in all_modes:
        records = per_mode_records[mode]
        if not records:
            aggregate["per_mode"][mode] = {"error": "no successful queries"}
            continue
        ok = [r for r in records if "metrics" in r]
        if not ok:
            aggregate["per_mode"][mode] = {"error": "all queries failed"}
            continue
        aggregate["per_mode"][mode] = {
            "recall_at_10":   round(sum(r["metrics"]["recall_at_10"]   for r in ok) / len(ok), 4),
            "recall_at_30":   round(sum(r["metrics"]["recall_at_30"]   for r in ok) / len(ok), 4),
            "mrr":            round(sum(r["metrics"]["mrr"]            for r in ok) / len(ok), 4),
            "ndcg_at_10":     round(sum(r["metrics"]["ndcg_at_10"]     for r in ok) / len(ok), 4),
            "precision_at_5": round(sum(r["metrics"]["precision_at_5"] for r in ok) / len(ok), 4),
            "queries_ok":     len(ok),
            "queries_total":  len(records),
        }

    # 用 primary_mode（默认 hybrid）作为 final_score 的输入
    primary = aggregate["per_mode"].get(primary_mode, {})
    aggregate["primary_mode"] = primary_mode
    aggregate["recall_at_10"]   = primary.get("recall_at_10",   0.0)
    aggregate["recall_at_30"]   = primary.get("recall_at_30",   0.0)
    aggregate["mrr"]            = primary.get("mrr",            0.0)
    aggregate["ndcg_at_10"]     = primary.get("ndcg_at_10",     0.0)
    aggregate["precision_at_5"] = primary.get("precision_at_5", 0.0)

    # 按 category 分桶（v2 才有意义）
    by_category: dict[str, dict] = {}
    for pq in per_query:
        cat = pq.get("category") or "unknown"
        if cat not in by_category:
            by_category[cat] = {"count": 0, "queries": []}
        by_category[cat]["count"] += 1
        by_category[cat]["queries"].append(pq["query_id"])
    aggregate["by_category"] = by_category
    aggregate["by_diagnostic_intent"] = {}
    for pq in per_query:
        di = pq.get("diagnostic_intent") or "unknown"
        if di not in aggregate["by_diagnostic_intent"]:
            aggregate["by_diagnostic_intent"][di] = {"count": 0}
        aggregate["by_diagnostic_intent"][di]["count"] += 1

    return aggregate, per_query, failed
