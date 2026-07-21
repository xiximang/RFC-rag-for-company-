#!/usr/bin/env python3
"""RAG 评测一键入口：离线检索评测 + 可选 LLM Judge + 加权汇总。

使用示例：

  # 只跑离线检索（不调 LLM）
  python3 scripts/eval/run_eval.py \
      --dataset scripts/eval/datasets/ups_v1.jsonl \
      --kb-ids ups-eval-kb \
      --admin-pass 'Admin@123456' \
      --skip-llm

  # 离线 100% + LLM 采样 20%
  RAG_JUDGE_API_URL=https://api.minimaxi.com/v1/chat/completions \
  RAG_JUDGE_API_KEY=sk-judge-only \
  python3 scripts/eval/run_eval.py \
      --dataset scripts/eval/datasets/ups_v1.jsonl \
      --kb-ids ups-eval-kb \
      --admin-pass 'Admin@123456' \
      --sample-ratio 0.2
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import requests

from scripts.eval.lib.config import (
    DEFAULT_SAMPLE_RATIO,
    EVAL_RUNS_DIR,
)
from scripts.eval.lib.retrieval_eval import run_retrieval_eval
from scripts.eval.lib.sampler import ReproducibleSampler
from scripts.eval.lib.scorer import compute_final_score
from scripts.eval.lib.reporter import generate_per_query_csv, generate_final_report


def login(api_url, username, password):
    resp = requests.post(
        f"{api_url.rstrip('/')}/api/v1/auth/login",
        data={"username": username, "password": password},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def resolve_kb_ids(api_url, headers, kb_ids_or_names):
    """把 KB name 或 UUID 都解析为 UUID。

    - 看起来是 UUID 的直接保留
    - 否则调 /api/v1/knowledge-bases 找到对应 name 的 id
    """
    import re
    uuid_pat = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
    resolved = []
    for x in kb_ids_or_names:
        if uuid_pat.match(x):
            resolved.append(x)
            continue
        # 视为 name，调用 API 查询
        resp = requests.get(
            f"{api_url.rstrip('/')}/api/v1/knowledge-bases",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data if isinstance(data, list) else data.get("items", [])
        match = next((k for k in items if k.get("name") == x), None)
        if not match:
            raise RuntimeError(f"找不到知识库：name={x}")
        resolved.append(match["id"])
    return resolved


def load_queries(dataset_path):
    queries = []
    for line in Path(dataset_path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        queries.append(json.loads(line))
    return queries


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(
        description="RAG 评测：离线检索 + 可选 LLM Judge + 加权汇总",
    )
    parser.add_argument("--dataset", required=True, help="数据集 JSONL 路径")
    parser.add_argument("--kb-ids", nargs="+", required=True, help="知识库 ID 列表")
    parser.add_argument("--api-url", default="http://localhost:8080")
    parser.add_argument("--admin-user", default="admin")
    parser.add_argument("--admin-pass", required=True)
    parser.add_argument("--sample-ratio", type=float, default=DEFAULT_SAMPLE_RATIO)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM Judge")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--primary-mode", default="hybrid",
                        choices=["semantic", "keyword", "hybrid"])
    args = parser.parse_args()

    if args.output_dir:
        out = Path(args.output_dir)
    else:
        ts = time.strftime("%Y%m%d_%H%M%S")
        out = Path(EVAL_RUNS_DIR) / ts
    out.mkdir(parents=True, exist_ok=True)
    (out / "llm_judge").mkdir(exist_ok=True)

    write_json(out / "config.yaml", {
        "dataset":      args.dataset,
        "kb_names":     args.kb_ids,
        "kb_uuids":     None,  # 在登录后回填
        "api_url":      args.api_url,
        "admin_user":   args.admin_user,
        "sample_ratio": args.sample_ratio,
        "seed":         args.seed,
        "skip_llm":     args.skip_llm,
        "primary_mode": args.primary_mode,
        "timestamp":    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })

    queries = load_queries(args.dataset)
    print(f"[1/4] Loaded {len(queries)} queries from {args.dataset}")

    token = login(args.api_url, args.admin_user, args.admin_pass)
    headers = {"Authorization": f"Bearer {token}"}
    print(f"[2/4] Logged in as {args.admin_user} @ {args.api_url}")

    kb_uuids = resolve_kb_ids(args.api_url, headers, args.kb_ids)
    print(f"      KB: {args.kb_ids} -> {kb_uuids}")
    # 回写 config.yaml 的 kb_uuids
    cfg_path = out / "config.yaml"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["kb_uuids"] = kb_uuids
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[3/4] Running retrieval eval on {len(queries)} queries...")
    retrieval_aggregate, per_query, failed = run_retrieval_eval(
        queries=queries,
        kb_ids=kb_uuids,
        headers=headers,
        base_url=args.api_url,
        primary_mode=args.primary_mode,
    )
    print(f"      [{args.primary_mode}] Recall@10={retrieval_aggregate['recall_at_10']:.3f}, "
          f"MRR={retrieval_aggregate['mrr']:.3f}, "
          f"NDCG@10={retrieval_aggregate['ndcg_at_10']:.3f}")

    write_json(out / "metrics_retrieval.json", retrieval_aggregate)
    Path(out / "per_query.csv").write_text(generate_per_query_csv(per_query), encoding="utf-8")
    write_json(out / "failed_queries.jsonl", failed if failed else [])

    llm_metrics = {"samples_judged": 0, "total_samples": len(queries)}
    llm_stats = None
    if not args.skip_llm and queries:
        try:
            from scripts.eval.lib.llm_judge import LLMJudge, judge_batch
            sampler = ReproducibleSampler(args.sample_ratio, args.seed)
            sampled, _, seed = sampler.sample(queries)
            print(f"[4/4] Running LLM Judge on {len(sampled)} samples "
                  f"({args.sample_ratio * 100:.0f}% of {len(queries)}, seed={seed})...")

            judge = LLMJudge()
            llm_metrics, judgments = judge_batch(
                judge, sampled,
                on_progress=lambda i, n, qid: print(f"      [{i}/{n}] {qid}"),
            )

            write_json(out / "llm_judge" / "judgments.jsonl", judgments)
            write_json(out / "llm_judge" / "sample_meta.json", {
                "sample_ratio": args.sample_ratio,
                "seed": seed,
                "sampled_query_ids": [q["query_id"] for q in sampled],
                "total_samples": len(queries),
            })
            llm_stats = judge.stats()
            write_json(out / "llm_judge" / "llm_stats.json", llm_stats)
        except Exception as exc:
            print(f"[4/4] LLM Judge failed: {exc}", file=sys.stderr)
            print("      继续以 llm_score=0 完成最终汇总")
    else:
        print(f"[4/4] Skipped LLM Judge")

    final = compute_final_score(retrieval_aggregate, llm_metrics)
    write_json(out / "metrics_summary.json", final)
    Path(out / "final_report.md").write_text(
        generate_final_report(final, args, retrieval_aggregate, llm_stats),
        encoding="utf-8",
    )

    print()
    print("=" * 60)
    print(f"Final score: {final['final_score']} / 1.000  "
          f"(percent: {final['final_score_100']})")
    print(f"   - retrieval: {final['breakdown']['retrieval']['weighted']:.4f}")
    print(f"   - llm:       {final['breakdown']['llm']['weighted']:.4f}")
    print(f"   output dir: {out}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
