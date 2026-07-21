"""生成 per_query.csv / final_report.md 报告。"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path


def _fmt(x, default="-"):
    if x is None or x == "":
        return default
    if isinstance(x, float):
        return f"{x:.4f}"
    return str(x)


def generate_per_query_csv(per_query: list[dict]) -> str:
    """生成 CSV：query_id, query, expected, mode, recall@10, mrr, ndcg@10, precision@5, top_retrieved。"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "query_id", "query", "expected_count",
        "mode", "recall_at_10", "mrr", "ndcg_at_10", "precision_at_5", "hit_count",
        "top_retrieved",
    ])
    for rec in per_query:
        for mode, m in (rec.get("modes") or {}).items():
            if "error" in m:
                writer.writerow([
                    rec["query_id"], rec["query"], len(rec["expected_chunks"]),
                    mode, "ERR", "ERR", "ERR", "ERR", "ERR", m["error"],
                ])
                continue
            writer.writerow([
                rec["query_id"], rec["query"], len(rec["expected_chunks"]),
                mode,
                _fmt(m.get("recall_at_10")),
                _fmt(m.get("mrr")),
                _fmt(m.get("ndcg_at_10")),
                _fmt(m.get("precision_at_5")),
                m.get("hit_count", 0),
                "|".join(m.get("top_retrieved", [])[:10]),
            ])
    return buf.getvalue()


def generate_final_report(final: dict, args, retrieval_aggregate: dict,
                           llm_stats: dict | None = None) -> str:
    """生成 Markdown 报告。"""
    lines: list[str] = []
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    lines.append("# RAG 评测报告")
    lines.append("")
    lines.append(f"- 运行时间：{ts}")
    lines.append(f"- 数据集：`{args.dataset}`")
    lines.append(f"- 知识库：`{', '.join(args.kb_ids)}`")
    lines.append(f"- 目标 API：`{args.api_url}`")
    lines.append(f"- LLM 采样比例：{args.sample_ratio * 100:.0f}%")
    if args.skip_llm:
        lines.append("- LLM Judge：**已跳过**（--skip-llm）")
    else:
        lines.append("- LLM Judge：**已运行**")
    lines.append("")

    # 总分
    fs = final["final_score"]
    fs100 = final["final_score_100"]
    lines.append(f"## 🎯 最终分：**{fs}** / 1.000（百分制 **{fs100}**）")
    lines.append("")
    lines.append(f"> {final.get('security_note', '')}")
    lines.append("")

    # 分维度
    bd = final["breakdown"]
    lines.append("| 维度 | 权重 | 维度分 | 加权分 |")
    lines.append("|---|---|---|---|")
    lines.append(f"| 检索质量 | {bd['retrieval']['weight']:.0%} | "
                 f"{bd['retrieval']['score']:.4f} | {bd['retrieval']['weighted']:.4f} |")
    lines.append(f"| LLM 评分 | {bd['llm']['weight']:.0%} | "
                 f"{bd['llm']['score']:.4f} | {bd['llm']['weighted']:.4f} |")
    lines.append("")

    # 向量化精准度（v2 模板专用，独立报告，不计入最终分）
    ep = final.get("embedding_precision") or {}
    if ep and ep.get("samples", 0) > 0:
        lines.append("## 🔬 向量化精准度（v2 模板专用）")
        lines.append("")
        if ep.get("precision") is None:
            lines.append("> 数据集未提供 max_allowed_distance，跳过精准度评估")
        else:
            mean_d = ep.get("mean_distance", 0)
            max_d = ep.get("max_distance", 0)
            precision = ep.get("precision", 0)
            pass_cnt = ep.get("pass_threshold_count", 0)
            fail_cnt = ep.get("fail_threshold_count", 0)
            total_cnt = pass_cnt + fail_cnt
            lines.append(f"- 通过阈值：**{pass_cnt}/{total_cnt} ({precision*100:.1f}%)**")
            lines.append(f"- 平均 cosine 距离：**{mean_d:.4f}**（越小越精准）")
            lines.append(f"- 最大 cosine 距离：**{max_d:.4f}**")
            if ep.get("fail_queries"):
                lines.append("")
                lines.append("### ⚠️ 未通过阈值的 query")
                lines.append("")
                lines.append("| ID | 问题 | 距离 | 阈值 | 诊断意图 |")
                lines.append("|---|---|---|---|---|")
                for fq in ep["fail_queries"]:
                    lines.append(f"| {fq.get('id','-')} | {fq.get('question','-')[:30]}... | "
                                 f"{fq.get('distance',0):.4f} | {fq.get('threshold',0):.4f} | "
                                 f"`{fq.get('diagnostic_intent','-')}` |")
            lines.append("")
            lines.append("> 该维度**不计入最终分**，仅用于诊断向量化模型的精度短板。")
            lines.append("")

    # 检索细分
    lines.append(f"## 检索指标（{retrieval_aggregate.get('primary_mode', 'hybrid')} 模式）")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    for k in ["recall_at_10", "recall_at_30", "mrr", "ndcg_at_10", "precision_at_5"]:
        lines.append(f"| {k} | {_fmt(retrieval_aggregate.get(k, 0))} |")
    lines.append("")

    # 各模式对比
    if "per_mode" in retrieval_aggregate:
        lines.append("### 各模式对比")
        lines.append("")
        lines.append("| 模式 | Recall@10 | MRR | NDCG@10 | Precision@5 |")
        lines.append("|---|---|---|---|---|")
        for mode, m in retrieval_aggregate["per_mode"].items():
            if "error" in m:
                lines.append(f"| {mode} | ERR | ERR | ERR | ERR |")
                continue
            lines.append(f"| {mode} | {_fmt(m.get('recall_at_10'))} | {_fmt(m.get('mrr'))} "
                         f"| {_fmt(m.get('ndcg_at_10'))} | {_fmt(m.get('precision_at_5'))} |")
        lines.append("")

    # LLM
    llm = bd["llm"]
    lines.append(f"## LLM Judge（{llm['parts']['faithfulness'].get('value', 0):.2f} 归一化）")
    lines.append("")
    lines.append(f"采样 {llm.get('samples_judged', 0)} / {llm.get('total_samples', 0)}")
    lines.append("")
    lines.append("| 指标 | 值 | 权重 | 加权 |")
    lines.append("|---|---|---|---|")
    for k in ["faithfulness", "relevance", "helpfulness"]:
        p = llm["parts"][k]
        lines.append(f"| {k} | {p['value']:.4f} | {p['weight']:.2f} | {p['weighted']:.4f} |")
    if llm_stats:
        lines.append("")
        lines.append(f"Token 用量：{llm_stats.get('total_tokens', 0)}，"
                     f"成功 {llm_stats.get('total_calls', 0) - llm_stats.get('failed_calls', 0)}/{llm_stats.get('total_calls', 0)}")
    lines.append("")

    # 加权公式
    lines.append("## 计算明细")
    lines.append("")
    lines.append("```")
    lines.append(f"retrieval_score = "
                 f"0.25×recall@10 + 0.20×mrr + 0.10×ndcg@10 + 0.05×precision@5")
    lines.append(f"               = {bd['retrieval']['parts']['recall_at_10']['weighted']:.4f}"
                 f" + {bd['retrieval']['parts']['mrr']['weighted']:.4f}"
                 f" + {bd['retrieval']['parts']['ndcg_at_10']['weighted']:.4f}"
                 f" + {bd['retrieval']['parts']['precision_at_5']['weighted']:.4f}"
                 f" = {bd['retrieval']['score']:.4f}")
    lines.append(f"weighted = {bd['retrieval']['score']:.4f} × 0.6 = {bd['retrieval']['weighted']:.4f}")
    lines.append("")
    if not args.skip_llm and llm.get("samples_judged", 0) > 0:
        lines.append(f"llm_score = 0.20×faithfulness + 0.12×relevance + 0.08×helpfulness")
        lines.append(f"          = {bd['llm']['parts']['faithfulness']['weighted']:.4f}"
                     f" + {bd['llm']['parts']['relevance']['weighted']:.4f}"
                     f" + {bd['llm']['parts']['helpfulness']['weighted']:.4f}"
                     f" = {bd['llm']['score']:.4f}")
        lines.append(f"weighted = {bd['llm']['score']:.4f} × 0.4 = {bd['llm']['weighted']:.4f}")
    else:
        lines.append("llm_score = 0（skip-llm 或采样为 0）")
        lines.append("weighted = 0 × 0.4 = 0")
    lines.append("")
    lines.append(f"final_score = {bd['retrieval']['weighted']:.4f} + {bd['llm']['weighted']:.4f} = {fs:.4f}")
    lines.append(f"final_score_100 = {fs100}")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)
