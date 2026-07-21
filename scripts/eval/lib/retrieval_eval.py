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
        qid = q.get("query_id", "")
        query_text = q.get("query", "")
        expected = _expected_set(q.get("expected_chunks", []))

        record = {
            "query_id": qid,
            "query": query_text,
            "expected_chunks": sorted(expected),
            "modes": {},
        }

        any_error = False
        for mode in modes:
            try:
                retrieved = _search(query_text, mode, kb_ids, top_k, headers, base_url)
            except Exception as exc:
                any_error = True
                record["modes"][mode] = {"error": str(exc)}
                per_mode_records[mode].append({"query_id": qid, "error": str(exc)})
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
            per_mode_records[mode].append({
                "query_id": qid,
                "expected": sorted(expected),
                "retrieved": retrieved[:30],
                "metrics": metrics,
            })

        per_query.append(record)
        if any_error and all("error" in record["modes"].get(m, {}) for m in modes):
            failed.append({"query_id": qid, "query": query_text, "reason": "all modes failed"})

    # 汇总
    aggregate: dict = {"per_mode": {}}
    for mode in modes:
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

    return aggregate, per_query, failed
