"""Create Chinese-named demo knowledge bases and distribute sample documents.

This script sets up a clean demo environment with Chinese-named KBs
covering common business scenarios (HR, finance, legal, technical,
sales, product) so the system can be demonstrated end-to-end without
manually creating knowledge bases via the UI.

Usage:
    RAG_API_URL=http://localhost:8080 \\
    RAG_ADMIN_USER=admin RAG_ADMIN_PASS=admin123 \\
    python scripts/demo/seed_chinese_kbs.py

It is idempotent: existing KBs with the same name are reused.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Optional

import requests

API_URL = os.environ.get("RAG_API_URL", "http://localhost:8080")
USERNAME = os.environ.get("RAG_ADMIN_USER", "admin")
PASSWORD = os.environ.get("RAG_ADMIN_PASS")

if not PASSWORD:
    print("[ERROR] Set RAG_ADMIN_PASS environment variable to the admin password.")
    sys.exit(1)

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"

# Mapping: Chinese KB name -> (description, [sample filenames])
KB_PLAN = {
    "演示知识库": (
        "系统演示与综合中文样例",
        [
            "01-企业RAG产品介绍.md",
            "02-企业RAG产品介绍.txt",
            "03-产品功能说明.pdf",
        ],
    ),
    "人力资源": (
        "员工手册、HR 制度、培训资料",
        ["09-员工手册.md"],
    ),
    "财务制度": (
        "财务报销、预算管理、成本控制",
        ["10-财务报销制度.md", "04-财务数据样例.xlsx"],
    ),
    "法务合规": (
        "数据安全、合规要求、合同模板",
        ["11-数据安全合规手册.md", "13-销售合同模板.md"],
    ),
    "技术规范": (
        "研发规范、API 设计、数据库、安全",
        ["12-IT技术规范.md", "05-技术白皮书.docx"],
    ),
    "销售与客户": (
        "客户案例、FAQ、销售合同、定价",
        ["14-客户案例与产品FAQ.md", "08-项目计划表.xlsx"],
    ),
    "产品文档": (
        "产品介绍、操作手册、功能说明",
        ["15-产品操作指南.md", "07-客户服务FAQ.md", "06-组织架构图.png"],
    ),
}


def login() -> str:
    r = requests.post(
        f"{API_URL}/api/v1/auth/login",
        data={"username": USERNAME, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    r.raise_for_status()
    print(f"[OK] Logged in as {USERNAME}")
    return r.json()["access_token"]


def list_kbs(token: str) -> list[dict]:
    r = requests.get(
        f"{API_URL}/api/v1/knowledge-bases?limit=100",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def create_kb(token: str, name: str, description: str) -> str:
    r = requests.post(
        f"{API_URL}/api/v1/knowledge-bases",
        json={"name": name, "description": description},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=10,
    )
    r.raise_for_status()
    kb_id = r.json()["id"]
    print(f"[OK] Created KB '{name}': {kb_id}")
    return kb_id


def upload_file(token: str, kb_id: str, path: Path) -> Optional[str]:
    with path.open("rb") as f:
        r = requests.post(
            f"{API_URL}/api/v1/documents",
            data={"kb_id": kb_id},
            files={"file": (path.name, f, "application/octet-stream")},
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )
    if r.status_code == 201:
        doc_id = r.json().get("id", "")
        print(f"  [OK] {path.name}  -> {doc_id[:8]}")
        return doc_id
    body = r.text[:120] if r.text else ""
    print(f"  [WARN] {path.name}  [{r.status_code}] {body}")
    return None


def main() -> int:
    token = login()
    kbs = list_kbs(token)
    name_to_id = {k["name"]: k["id"] for k in kbs}

    print("\n=== Seeding Chinese-named KBs ===")
    for name, (desc, files) in KB_PLAN.items():
        kb_id = name_to_id.get(name)
        if kb_id is None:
            kb_id = create_kb(token, name, desc)
        else:
            print(f"[--] KB exists: '{name}'  {kb_id}")

        for fname in files:
            path = SAMPLES_DIR / fname
            if not path.exists():
                print(f"  [SKIP] {fname} (not in samples/)")
                continue
            upload_file(token, kb_id, path)

    print("\n[DONE] Demo KBs ready. Open http://localhost:3002 to verify.")
    return 0


if __name__ == "__main__":
    sys.exit(main())