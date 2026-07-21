# RAG 评测套件

离线检索评测 + 可选 LLM Judge + 加权汇总，对齐字节/火山方舟数据集评测平台风格。

## 设计原则（2026-07-21 确认）

- **两个维度**：检索质量 60% + LLM 评分 40%（= 100%）
- **不含安全维度**：安全拦截由 `backend/tests/test_*_*.py` 独立覆盖，避免重复计分
- **百分制显示**：`final_score_100 = final_score × 100`
- **离线优先**：默认只跑检索，零 LLM 配额消耗
- **采样可选**：LLM Judge 随机采样 20%，独立 key + 串行调用
- **可复现**：采样 seed 来自 query_ids 哈希，跨机器结果一致

## 目录结构

```
scripts/eval/
├── README.md                     # 本文件
├── run_eval.py                   # 一键入口
├── lib/
│   ├── __init__.py
│   ├── config.py                 # 权重/采样/路径
│   ├── sampler.py                # 可复现随机采样
│   ├── retrieval_eval.py         # 离线检索评测（不调 LLM）
│   ├── llm_judge.py              # LLM Judge（独立 key + 串行）
│   ├── scorer.py                 # 加权汇总
│   └── reporter.py               # CSV + Markdown 报告
├── datasets/
│   └── ups_v1.jsonl              # 10 个 UPS 评测 query
└── eval_runs/                    # 每次评测产物（gitignore）
    └── 20260721_140000/
        ├── config.yaml
        ├── metrics_summary.json
        ├── metrics_retrieval.json
        ├── per_query.csv
        ├── failed_queries.jsonl
        ├── llm_judge/
        │   ├── judgments.jsonl
        │   ├── sample_meta.json
        │   └── llm_stats.json
        └── final_report.md
```

## 快速开始

### 1. 只跑离线检索（不调 LLM，推荐）

```bash
cd /home/root1/tjy/RFC-rag-for-company
python3 scripts/eval/run_eval.py \
    --dataset scripts/eval/datasets/ups_v1.jsonl \
    --kb-ids ups-eval-kb \
    --admin-pass 'Admin@123456' \
    --skip-llm
```

### 2. 离线 + LLM 采样 20%

```bash
export RAG_JUDGE_API_URL="https://api.minimaxi.com/v1/chat/completions"
export RAG_JUDGE_API_KEY="<独立评测 key>"
export RAG_JUDGE_MODEL="MiniMax-M3"

python3 scripts/eval/run_eval.py \
    --dataset scripts/eval/datasets/ups_v1.jsonl \
    --kb-ids ups-eval-kb \
    --admin-pass 'Admin@123456' \
    --sample-ratio 0.2
```

### 3. 自定义采样 seed（保证可复现）

```bash
python3 scripts/eval/run_eval.py \
    --dataset scripts/eval/datasets/ups_v1.jsonl \
    --kb-ids ups-eval-kb \
    --admin-pass 'Admin@123456' \
    --sample-ratio 0.3 --seed 42
```

## 数据集格式

每行一条 JSON：

```json
{
  "query_id": "q001",
  "query": "SOH显示电池异常",
  "kb_ids": ["ups-eval-kb"],
  "expected_chunks": ["02_iBattery 3.0 用户手册.pdf_chunk65"],
  "reference_answer": "SOH异常可能由电池老化或测量误差导致...",
  "difficulty": "easy",
  "tags": ["battery", "alarm"]
}
```

必填字段：`query_id`, `query`, `expected_chunks`。
可选字段：`reference_answer`, `generated_answer`, `contexts`（LLM Judge 时用）。

## 权重公式

```
retrieval_score = 0.25×recall@10 + 0.20×mrr + 0.10×ndcg@10 + 0.05×precision@5
                 范围 [0, 0.60]

llm_score      = 0.20×faithfulness + 0.12×relevance + 0.08×helpfulness
                 范围 [0, 0.40]

final_score    = retrieval_score × 0.6 + llm_score × 0.4
                 范围 [0, 1.0]

final_score_100 = final_score × 100
                 范围 [0, 100]
```

## LLM Judge 配额估算

默认 `max_tokens=200`、`temperature=0.0`、串行调用：

- 单次调用：~400 tokens（含 prompt + response）
- 采样 20% × 10 query = 2 次 ≈ 800 tokens
- 对 MiniMax-M3 RPM 200 / TPM 10M 的限额，实际占用 < 0.01%

## 4. 数据集校准（诊断 recall@K 异常）

```bash
PGHOST=localhost PGPORT=5432 PGUSER=rag_user PGPASSWORD=rag_password PGDATABASE=rag_kb \
python3 -m scripts.eval.lib.dataset_validator \
    --dataset scripts/eval/datasets/ups_v1.jsonl \
    --kb-id ups-eval-kb \
    --admin-pass 'Admin@123456' \
    --output eval_runs/<ts>/dataset_validation.json
```

输出：
- 覆盖率（expected_chunks 中能在 KB 找到的比例）
- 每 query 命中状态：`all_hit` / `partial_hit` / `zero_hit`
- 前 20 个 missing 示例
- KB 文档清单与 chunk 数量

**关键意义**：如果 coverage < 100%，说明 `recall@K` 异常可能是因为 expected_chunk 在 KB 里就不存在，**不是检索系统问题**。

也可在 Python 中直接调用：

```python
from scripts.eval.lib.dataset_validator import validate_dataset
report = validate_dataset(queries, api_url, kb_id, token)
print(report["coverage_rate"])
print(report["missing_samples"][:5])
```

## 对比旧的 eval_retrieval_ups.py

| 维度 | 旧 | 新 |
|---|---|---|
| 调用 LLM | 无 | 默认无，可选 |
| 加权汇总 | 无 | final_score (0~1) + 百分制 |
| 输出格式 | txt | JSON + CSV + Markdown |
| 可复现 | 部分 | seed 控制 |
| 失败归集 | 无 | failed_queries.jsonl |
| LLM Judge | 无 | 独立 key + 采样 |
| 配置快照 | 无 | config.yaml |

## 已知约束

1. `--api-url` 必须能访问 FastAPI 服务（默认 `http://localhost:8080`）
2. `--admin-pass` 必须能在后端登录（admin 账号）
3. `--kb-ids` 必须是已存在的知识库 ID（先去 `/api/v1/knowledge-bases` 查）
4. LLM Judge 必须设置 `RAG_JUDGE_API_URL` 和 `RAG_JUDGE_API_KEY`
5. 期望 chunk_id 格式：`{filename}_chunk{N}`（与 `eval_retrieval_ups.py` 一致）
