import asyncio
import json
import logging
from typing import Any, Dict, List

import httpx

from app.config import settings
from app.core.runtime_config import get_model_config

logger = logging.getLogger(__name__)


class RerankClient:
    """用户提供的Re-rank模型HTTP客户端"""

    def __init__(self):
        self.timeout = 60.0
        self.max_retries = 3
        self.base_delay = 1.0

    def _should_retry(self, exc: Exception) -> bool:
        """Return True for transient network/rate-limit errors."""
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            return code == 429 or code >= 500
        return isinstance(exc, (httpx.NetworkError, httpx.TimeoutException))

    def _config(self):
        cfg = get_model_config()
        return {
            "api_url": cfg.get("RERANK_API_URL") or settings.RERANK_SERVICE_URL,
            "model": cfg.get("RERANK_MODEL") or settings.RERANK_MODEL,
            "api_key": cfg.get("RERANK_API_KEY") or settings.RERANK_API_KEY,
        }

    @staticmethod
    def _extract_results_list(data: Any) -> List[Dict[str, Any]]:
        """从各种响应包装中提取出 results 列表。

        支持：
        - {"results": [...]}
        - {"output": {"results": [...]}}  (DashScope)
        - {"data": [...]}                  (部分厂商)
        - {"items": [...]}
        - [...]                            (顶层列表)
        """
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("results", "items", "data"):
                if key in data and isinstance(data[key], list):
                    return data[key]
            if isinstance(data.get("output"), dict):
                out = data["output"]
                for key in ("results", "items", "data"):
                    if key in out and isinstance(out[key], list):
                        return out[key]
        return []

    def _parse_rerank_response(
        self, data: Any, documents: List[Dict[str, Any]], top_k: int
    ) -> List[Dict[str, Any]]:
        """解析多种 rerank 响应格式，返回带有 rerank_score 的 results 列表。

        返回的 results 不在此处排序，由调用方统一排序。
        """
        results: List[Dict[str, Any]] = []

        # 兼容顶层列表：[score, score, ...]
        if isinstance(data, list) and data and all(
            isinstance(x, (int, float)) for x in data
        ):
            for i, score in enumerate(data):
                if i < len(documents):
                    item = documents[i].copy()
                    item["rerank_score"] = float(score)
                    item["rerank_status"] = "ok"
                    results.append(item)
            return results

        # 标准对象结构：results / output.results / items / data 等
        entries = self._extract_results_list(data)

        if entries and all(
            isinstance(e, (int, float)) for e in entries
        ):
            for i, score in enumerate(entries):
                if i < len(documents):
                    item = documents[i].copy()
                    item["rerank_score"] = float(score)
                    item["rerank_status"] = "ok"
                    results.append(item)
            return results

        # entries 是 dict 列表（最常见的 qwen3-rerank / Cohere / DashScope 格式）
        if entries and all(isinstance(e, dict) for e in entries):
            for r in entries:
                idx = r.get("index")
                if idx is None:
                    idx = r.get("document_index")
                if idx is None:
                    # 退化为按出现顺序
                    idx = len(results)
                if not isinstance(idx, int) or idx < 0 or idx >= len(documents):
                    continue
                score = (
                    r.get("relevance_score")
                    if r.get("relevance_score") is not None
                    else r.get("score")
                )
                if score is None:
                    continue
                item = documents[idx].copy()
                item["rerank_score"] = float(score)
                item["rerank_status"] = "ok"
                results.append(item)
            return results

        return results

    async def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        if not documents:
            return []

        logger.info(
            "Rerank START: query=%r docs=%d top_k=%d",
            query, len(documents), top_k,
        )

        cfg = self._config()
        headers = {"Content-Type": "application/json"}
        if cfg["api_key"]:
            headers["Authorization"] = f"Bearer {cfg['api_key']}"

        payload = {
            "model": cfg["model"],
            "query": query,
            "documents": [d.get("content", "") for d in documents],
            "top_n": max(top_k, 1),  # yunwu requires top_n >= 1
        }

        # 原始顺序的签名，用于检测是否真正重排
        original_order = [(d.get("id"), d.get("content", "")[:40]) for d in documents]

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        cfg["api_url"], json=payload, headers=headers
                    )
                    status_code = resp.status_code
                    try:
                        data = resp.json()
                    except Exception:
                        data = resp.text

                    # 响应日志
                    if isinstance(data, dict):
                        logger.info(
                            "Rerank response: status=%s keys=%s",
                            status_code, list(data.keys()),
                        )
                        # 调试日志：完整响应（可能很大，默认 debug）
                        logger.debug(
                            "Rerank response body: %s",
                            json.dumps(data, ensure_ascii=False)[:2000],
                        )
                    else:
                        logger.info(
                            "Rerank response: status=%s type=%s preview=%r",
                            status_code, type(data).__name__, str(data)[:300],
                        )

                    resp.raise_for_status()

                    parsed = self._parse_rerank_response(data, documents, top_k)

                    if not parsed:
                        logger.warning(
                            "Rerank response format unrecognized; using original order with placeholder scores"
                        )
                        fallback_results: List[Dict[str, Any]] = []
                        for d in documents[:top_k]:
                            d_copy = d.copy()
                            d_copy["rerank_score"] = d.get("score", 0.0)
                            d_copy["rerank_status"] = "fallback_no_change"
                            fallback_results.append(d_copy)
                        return sorted(
                            fallback_results,
                            key=lambda x: x.get("rerank_score", 0),
                            reverse=True,
                        )[:top_k]

                    # 检查是否完整覆盖了所有 candidate
                    got_indexes = {
                        next(
                            (i for i, d in enumerate(documents)
                             if d.get("id") == r.get("id")),
                            -1,
                        )
                        for r in parsed
                        if r.get("id") is not None
                    }
                    covered = len(parsed) < len(documents)

                    # 候选分数预览（前 3 个）
                    preview = []
                    for r in parsed[:3]:
                        preview.append(
                            (r.get("score"), r.get("rerank_score"))
                        )
                    logger.info(
                        "Rerank candidates: parsed=%d/%d preview(old,new)=%s",
                        len(parsed), len(documents), preview,
                    )

                    # 检测是否真正改变了顺序
                    new_order_ids = [r.get("id") for r in parsed]
                    original_ids = [d.get("id") for d in documents]
                    reordered = (
                        len(new_order_ids) == len(original_ids)
                        and new_order_ids != original_ids[: len(new_order_ids)]
                    )
                    logger.debug(
                        "Rerank reorder check: reordered=%s new_order=%s original=%s",
                        reordered, new_order_ids, original_ids,
                    )

                    # 标记 partial / ok
                    if covered:
                        # 给未命中的 candidate 补充占位结果（用原 score）
                        seen_ids = {r.get("id") for r in parsed if r.get("id") is not None}
                        for d in documents:
                            if d.get("id") not in seen_ids and len(parsed) < top_k:
                                d_copy = d.copy()
                                d_copy["rerank_score"] = d.get("score", 0.0)
                                d_copy["rerank_status"] = "partial"
                                parsed.append(d_copy)

                    # 最终排序 + 截断
                    sorted_results = sorted(
                        parsed,
                        key=lambda x: x.get("rerank_score", 0),
                        reverse=True,
                    )[:top_k]

                    reordered_count = sum(
                        1 for i, r in enumerate(sorted_results)
                        if i < len(original_order)
                        and (
                            r.get("id") != original_order[i][0]
                            and (r.get("content", "")[:40] != original_order[i][1])
                        )
                    )
                    logger.info(
                        "Rerank END: reordered=%d/%d",
                        reordered_count, len(sorted_results),
                    )

                    return sorted_results

            except Exception as e:
                last_exc = e
                if attempt < self.max_retries and self._should_retry(e):
                    delay = self.base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "Rerank API attempt %s/%s failed (%s); retrying in %.1fs",
                        attempt,
                        self.max_retries,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                break

        logger.exception("Rerank API call failed after %s attempts: %s", self.max_retries, last_exc)
        # 整链路失败兜底
        fallback_results: List[Dict[str, Any]] = []
        for d in sorted(
            documents, key=lambda x: x.get("score", 0), reverse=True
        )[:top_k]:
            d_copy = d.copy()
            d_copy["rerank_score"] = d.get("score", 0.0)
            d_copy["rerank_status"] = "fallback_no_change"
            fallback_results.append(d_copy)
        return sorted(
            fallback_results,
            key=lambda x: x.get("rerank_score", 0),
            reverse=True,
        )[:top_k]


rerank_client = RerankClient()