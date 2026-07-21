"""LLM Judge：使用独立 key + 串行调用 + 自动熔断。

约束：
- 使用独立评测 key（环境变量 RAG_JUDGE_API_KEY），不与生产共用
- 强制串行（采样量小，无需并发）
- 任一调用失败给中性 0.5 分，不污染主指标流
- 累计 token 用量供后续成本分析

Prompt 模板要求 LLM 输出严格 JSON，1~5 分（faithfulness/relevance/helpfulness）。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any

from .config import (
    DEFAULT_JUDGE_MAX_TOKENS,
    DEFAULT_JUDGE_TEMPERATURE,
)


PROMPT_TEMPLATE = """你是 RAG 系统的质量评估专家。请基于以下三个维度对生成的答案进行评分，每个维度 1~5 分。

【用户问题】
{query}

【参考答案】
{reference}

【生成的答案】
{generated}

【检索到的上下文】（片段）
{contexts}

请按以下 JSON 格式输出（不要其他文字、不要 markdown 代码块）：
{{
  "faithfulness": <1~5>,   // 答案是否忠实于上下文（无幻觉/无编造）
  "relevance":    <1~5>,   // 答案与用户问题的相关程度
  "helpfulness":  <1~5>,   // 答案是否实际解决了用户问题
  "reasoning":    "<一句话理由>"
}}"""


class LLMJudge:
    """LLM Judge 封装。"""

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float = DEFAULT_JUDGE_TEMPERATURE,
        max_tokens: int = DEFAULT_JUDGE_MAX_TOKENS,
        timeout: int = 30,
    ):
        self.api_url = api_url or os.environ.get("RAG_JUDGE_API_URL")
        self.api_key = api_key or os.environ.get("RAG_JUDGE_API_KEY")
        self.model   = model   or os.environ.get("RAG_JUDGE_MODEL", "MiniMax-M3")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

        if not self.api_url or not self.api_key:
            raise RuntimeError(
                "LLM Judge 需要 RAG_JUDGE_API_URL 与 RAG_JUDGE_API_KEY 环境变量"
            )

        self.lock = threading.Lock()
        self.total_calls = 0
        self.total_tokens = 0
        self.failed_calls = 0

    def judge(self, query: str, reference: str, generated: str,
              contexts: list[str] | None = None) -> dict:
        """返回 {scores: {faithfulness, relevance, helpfulness}, tokens, error}。"""
        contexts = contexts or []
        contexts_str = "\n".join(contexts[:3]) if contexts else "（无上下文）"
        prompt = PROMPT_TEMPLATE.format(
            query=query,
            reference=reference or "（无参考答案）",
            generated=generated or "（无生成答案）",
            contexts=contexts_str,
        )

        with self.lock:
            self.total_calls += 1

        try:
            import requests
            resp = requests.post(
                self.api_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens", 0)

            scores = self._parse_scores(content)
            with self.lock:
                self.total_tokens += tokens
            return {"scores": scores, "tokens": tokens, "raw": content}
        except Exception as exc:
            with self.lock:
                self.failed_calls += 1
            # 失败给中性 0.5
            return {
                "scores": {"faithfulness": 0.5, "relevance": 0.5, "helpfulness": 0.5},
                "tokens": 0,
                "error": str(exc),
            }

    def _parse_scores(self, content: str) -> dict[str, float]:
        """从 LLM 输出中提取 1~5 分，归一化到 0~1。"""
        # 尝试提取 JSON
        match = re.search(r"\{[\s\S]*?\}", content)
        if match:
            try:
                data = json.loads(match.group(0))
                return {
                    "faithfulness": max(0.0, min(1.0, float(data["faithfulness"]) / 5)),
                    "relevance":    max(0.0, min(1.0, float(data["relevance"])    / 5)),
                    "helpfulness":  max(0.0, min(1.0, float(data["helpfulness"])  / 5)),
                }
            except (json.JSONDecodeError, KeyError, ValueError):
                pass
        # 失败给中性分
        return {"faithfulness": 0.5, "relevance": 0.5, "helpfulness": 0.5}

    def stats(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "failed_calls": self.failed_calls,
            "total_tokens": self.total_tokens,
            "success_rate": round(
                (self.total_calls - self.failed_calls) / max(self.total_calls, 1), 4
            ),
        }


def _extract_reference_answer(q: dict) -> str:
    """从 query 中提取参考答案，兼容 v1/v2 格式。

    v1 JSONL: reference_answer 字段
    v2 JSON 顶层: ground_truth.answer 字段
    """
    # v2 格式：ground_truth.answer
    gt = q.get("ground_truth")
    if isinstance(gt, dict):
        ans = gt.get("answer")
        if ans:
            return ans
    # v1 格式
    return q.get("reference_answer", "") or q.get("answer", "")


def _extract_query_text(q: dict) -> str:
    return q.get("query") or q.get("question") or ""


def _extract_query_id(q: dict) -> str:
    return q.get("query_id") or q.get("id") or ""


def judge_batch(judge: LLMJudge, queries: list[dict], on_progress=None) -> tuple[dict, list[dict]]:
    """批量评分。

    queries 每项应包含：
        v1: query, reference_answer, generated_answer, contexts, query_id
        v2: question, ground_truth.answer, generated_answer, contexts, id
        兼容: 同时支持 query/reference_answer/answer 等别名
    返回：
        aggregate: {faithfulness, relevance, helpfulness, samples_judged, total_samples}
        judgments: 每条记录的明细
    """
    judgments = []
    faith_sum = rel_sum = help_sum = 0.0
    n = 0

    for i, q in enumerate(queries, 1):
        result = judge.judge(
            query=_extract_query_text(q),
            reference=_extract_reference_answer(q),
            generated=q.get("generated_answer", ""),
            contexts=q.get("contexts", []),
        )
        # 同时记录 v2 元数据（category / difficulty / diagnostic_intent）
        record = {
            "query_id": _extract_query_id(q),
            "scores": result["scores"],
            "tokens": result["tokens"],
        }
        # v2 元数据透传
        v2_meta = q.get("metadata") or {}
        if v2_meta.get("category"):
            record["category"] = v2_meta["category"]
        if v2_meta.get("difficulty"):
            record["difficulty"] = v2_meta["difficulty"]
        if (q.get("quality") or {}).get("diagnostic_intent"):
            record["diagnostic_intent"] = q["quality"]["diagnostic_intent"]
        if "error" in result:
            record["error"] = result["error"]
        judgments.append(record)

        faith_sum += result["scores"]["faithfulness"]
        rel_sum   += result["scores"]["relevance"]
        help_sum  += result["scores"]["helpfulness"]
        n += 1

        if on_progress:
            on_progress(i, len(queries), _extract_query_id(q))

    if n == 0:
        return {
            "faithfulness": 0.0, "relevance": 0.0, "helpfulness": 0.0,
            "samples_judged": 0, "total_samples": len(queries),
        }, []

    # 按 category 分桶（v2 才有意义）
    by_category = {}
    for j in judgments:
        cat = j.get("category") or "unknown"
        if cat not in by_category:
            by_category[cat] = {"count": 0, "faithfulness": 0.0, "relevance": 0.0, "helpfulness": 0.0}
        by_category[cat]["count"] += 1
        by_category[cat]["faithfulness"] += j["scores"]["faithfulness"]
        by_category[cat]["relevance"]    += j["scores"]["relevance"]
        by_category[cat]["helpfulness"]  += j["scores"]["helpfulness"]
    for cat, st in by_category.items():
        cnt = st["count"]
        st["faithfulness"] = round(st["faithfulness"] / cnt, 4)
        st["relevance"]    = round(st["relevance"] / cnt, 4)
        st["helpfulness"]  = round(st["helpfulness"] / cnt, 4)

    return {
        "faithfulness": round(faith_sum / n, 4),
        "relevance":    round(rel_sum   / n, 4),
        "helpfulness":  round(help_sum  / n, 4),
        "samples_judged": n,
        "total_samples":  len(queries),
        "by_category": by_category,  # v2 才有数据
    }, judgments
