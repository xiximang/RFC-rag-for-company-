"""Show knowledge-base status, document counts and indexing health.

Quick diagnostic for the demo environment: prints all KBs with their
doc count and the per-document status (pending / processing / indexed /
failed) so operators can spot stuck ingestion jobs.

Usage:
    RAG_API_URL=http://localhost:8080 \\
    RAG_ADMIN_USER=admin RAG_ADMIN_PASS=admin123 \\
    python scripts/demo/check_demo_status.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

import requests

API_URL = os.environ.get("RAG_API_URL", "http://localhost:8080")
USERNAME = os.environ.get("RAG_ADMIN_USER", "admin")
PASSWORD = os.environ.get("RAG_ADMIN_PASS")

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


def list_docs(token: str, kb_id: str, limit: int = 100) -> list[dict]:
    r = requests.get(
        f"{API_URL}/api/v1/documents/{kb_id}?limit={limit}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("items", [])


def main() -> int:
    token = login()
    kbs = get_all_kbs(token)

    print(f"\n=== {len(kbs)} knowledge bases ===\n")
    print(f"{'name':<35} {'docs':>5}  {'status distribution'}")
    print("-" * 90)

    grand_total = 0
    for kb in kbs:
        docs = list_docs(token, kb["id"])
        bucket: dict[str, int] = defaultdict(int)
        for d in docs:
            bucket[d.get("status", "?")] += 1
        dist = ", ".join(f"{k}:{v}" for k, v in sorted(bucket.items()))
        print(f"{kb['name']:<35} {len(docs):>5}  {dist}")
        grand_total += len(docs)

    print("-" * 90)
    print(f"{'TOTAL':<35} {grand_total:>5}")

    failed = []
    for kb in kbs:
        for d in list_docs(token, kb["id"]):
            if d.get("status") in ("failed", "processing"):
                failed.append((kb["name"], d["filename"], d.get("status")))
    if failed:
        print(f"\n[!] {len(failed)} stuck documents (need manual re-ingest):")
        for kb_name, fname, st in failed:
            print(f"    [{st}] {kb_name} / {fname}")
    return 0


if __name__ == "__main__":
    sys.exit(main())