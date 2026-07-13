"""Re-trigger ingestion on documents that are stuck in ``processing`` or ``failed``.

Lightweight deployments run Celery in ``EAGER`` mode (no separate worker
container), so if the backend restarts mid-ingest the document status
can stay in ``processing`` forever. This script:

1. Lists all KBs and their documents
2. Resets any document in ``processing`` state to ``failed`` directly in Postgres
3. Calls ``POST /documents/{id}/reprocess`` which re-runs the pipeline

Usage:
    docker exec rag-lw-postgres psql -U rag_user -d rag_kb -c "..."   # OR
    python scripts/demo/reingest_demo_docs.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import requests

API_URL = os.environ.get("RAG_API_URL", "http://localhost:8080")
USERNAME = os.environ.get("RAG_ADMIN_USER", "admin")
PASSWORD = os.environ.get("RAG_ADMIN_PASS")
PG_CONTAINER = os.environ.get("PG_CONTAINER", "rag-lw-postgres")

if not PASSWORD:
    print("[ERROR] Set RAG_ADMIN_PASS environment variable.")
    sys.exit(1)


def login() -> str:
    r = requests.post(
        f"{API_URL}/api/v1/auth/login",
        data={"username": USERNAME, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def psql(sql: str) -> str:
    """Run SQL inside the Postgres container."""
    proc = subprocess.run(
        ["docker", "exec", PG_CONTAINER,
         "psql", "-U", "rag_user", "-d", "rag_kb",
         "-c", sql],
        capture_output=True, text=True,
    )
    return proc.stdout + proc.stderr


def get_all_kbs(token: str) -> list[dict]:
    out, skip = [], 0
    while True:
        r = requests.get(
            f"{API_URL}/api/v1/knowledge-bases?limit=50&skip={skip}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        r.raise_for_status()
        page = r.json()
        out.extend(page)
        if len(page) < 50:
            break
        skip += 50
    return out


def list_docs(token: str, kb_id: str) -> list[dict]:
    r = requests.get(
        f"{API_URL}/api/v1/documents/{kb_id}?limit=100",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("items", [])


def trigger(token: str, doc_id: str) -> bool:
    try:
        r = requests.post(
            f"{API_URL}/api/v1/documents/{doc_id}/reprocess",
            json={},
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            timeout=10,
        )
        return r.status_code in (200, 201, 400)  # 400 = already processing
    except Exception as e:
        print(f"  [ERR] trigger {doc_id}: {e}")
        return False


def main() -> int:
    token = login()
    kbs = get_all_kbs(token)

    reset = []
    for kb in kbs:
        for d in list_docs(token, kb["id"]):
            if d.get("status") == "processing":
                reset.append((kb["name"], d["filename"], d["id"]))

    if not reset:
        print("[OK] No documents stuck in 'processing' state.")
        return 0

    print(f"[!] Found {len(reset)} stuck documents, resetting via DB...\n")
    for kb_name, fname, doc_id in reset:
        psql(f"UPDATE documents SET status='failed' WHERE id='{doc_id}';")
        print(f"  reset: {kb_name} / {fname}")

    print(f"\n[*] Triggering reprocess via API...")
    for kb_name, fname, doc_id in reset:
        ok = trigger(token, doc_id)
        print(f"  {kb_name} / {fname}  -> {ok}")

    print(f"\n[*] Waiting 30s for indexing...")
    time.sleep(30)
    print("[DONE] Check status with scripts/demo/check_demo_status.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())