# Demo / POC scripts

Utilities for setting up a working demo environment and inspecting its
state. Use these whenever you need to bootstrap a fresh deployment for
a sales call, internal evaluation or hands-on tutorial.

## Prerequisites

- The lightweight Docker stack is running (`docker compose -f docker-compose.lightweight.yml up -d`)
- Admin credentials available via `RAG_ADMIN_USER` / `RAG_ADMIN_PASS`
- Python 3.11+ with `requests`

## Scripts

### `seed_chinese_kbs.py`

Create seven Chinese-named knowledge bases (演示知识库 / 人力资源 / 财务制度 /
法务合规 / 技术规范 / 销售与客户 / 产品文档) and upload the corresponding
sample documents from `samples/`. Idempotent: existing KBs with the same
name are reused.

```bash
RAG_API_URL=http://localhost:8080 \
RAG_ADMIN_USER=admin RAG_ADMIN_PASS=admin123 \
python scripts/demo/seed_chinese_kbs.py
```

### `check_demo_status.py`

Print a one-line summary for every KB with its document count and the
distribution of document statuses (`pending` / `processing` / `indexed` /
`failed`). Lists documents stuck in `processing` for manual recovery.

```bash
RAG_ADMIN_PASS=admin123 python scripts/demo/check_demo_status.py
```

### `reingest_demo_docs.py`

Reset documents stuck in `processing` and trigger reprocessing via the
`/documents/{id}/reprocess` endpoint. Requires direct access to the
Postgres container (used by Docker).

```bash
RAG_ADMIN_PASS=admin123 python scripts/demo/reingest_demo_docs.py
```

## Typical workflow

```bash
# 1. Start the stack
docker compose -f docker-compose.lightweight.yml up -d

# 2. Seed demo KBs and upload samples
python scripts/demo/seed_chinese_kbs.py

# 3. Inspect progress
python scripts/demo/check_demo_status.py

# 4. If any document is stuck, recover it
python scripts/demo/reingest_demo_docs.py
```