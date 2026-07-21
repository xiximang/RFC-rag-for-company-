"""数据集校准器：验证 expected_chunks 是否在 KB 中真实存在。

用法：

  from scripts.eval.lib.dataset_validator import validate_dataset

  report = validate_dataset(
      queries=[{"query_id": "q1", "query": "...", "expected_chunks": ["x.pdf_chunk1"]}, ...],
      api_url="http://localhost:8080",
      kb_id="...",   # 或 kb_name，自动解析
      token="...",
  )

  print(report["coverage_rate"])
  print(report["missing"][:10])
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


# ---------------------------------------------------------------------------
# KB 索引：从后端 API 拉 documents + chunks，建立双向索引
# ---------------------------------------------------------------------------

def _resolve_kb_id(api_url: str, kb_id_or_name: str, headers: dict) -> str:
    """KB name → UUID（已是 UUID 直接返回）。"""
    uuid_pat = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
    )
    if uuid_pat.match(kb_id_or_name):
        return kb_id_or_name
    resp = requests.get(
        f"{api_url.rstrip('/')}/api/v1/knowledge-bases",
        headers=headers, timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    items = data if isinstance(data, list) else data.get("items", [])
    match = next((k for k in items if k.get("name") == kb_id_or_name), None)
    if not match:
        raise RuntimeError(f"找不到知识库：{kb_id_or_name}")
    return match["id"]


def _fetch_documents(api_url: str, kb_id: str, headers: dict, limit: int = 200) -> list[dict]:
    """列出一个 KB 的所有文档（最多 limit）。

    端点：GET /api/v1/documents/{kb_id}?limit=&offset=
    """
    out = []
    offset = 0
    page = 100
    while len(out) < limit:
        url = f"{api_url.rstrip('/')}/api/v1/documents/{kb_id}"
        params = {"limit": page, "offset": offset}
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        if resp.status_code == 404:
            return out
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", []) if isinstance(data, dict) else data
        if not items:
            break
        out.extend(items)
        if len(items) < page:
            break
        offset += page
    return out[:limit]


def _fetch_chunks_for_doc(api_url: str, doc_id: str, headers: dict,
                          limit: int = 500) -> list[dict]:
    """获取某文档的所有 chunk。

    端点：GET /api/v1/documents/detail/{doc_id}/preview  含 content + chunk_index
    """
    try:
        url = f"{api_url.rstrip('/')}/api/v1/documents/detail/{doc_id}/preview"
        resp = requests.get(url, params={"limit": limit}, headers=headers, timeout=30)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        # preview 返回 {chunks: [...]} 或 {items: [...]}
        return data.get("chunks", data.get("items", []))
    except Exception:
        return []


def build_kb_index(api_url: str, kb_id_or_name: str, headers: dict) -> dict:
    """建立 KB 的全文索引。

    优先用 PostgreSQL 直连（更快、完整）。
    失败时回落到 API（仅 documents，无 chunks）。

    返回：
        {
          "kb_id": "...",
          "documents": [{"id", "filename", "chunk_count"}],
          "by_filename_chunk": {"filename_chunkN": "chunk_uuid", ...},
          "by_chunk_id": {"chunk_uuid": {"filename", "chunk_index"}, ...},
          "all_filenames": ["...", ...],
        }
    """
    kb_id = _resolve_kb_id(api_url, kb_id_or_name, headers)

    # 优先：直连 PostgreSQL
    try:
        return _build_kb_index_from_db(kb_id)
    except Exception as e:
        print(f"  [warn] DB direct connection failed: {e}; fallback to API")
        return _build_kb_index_from_api(api_url, kb_id, headers)


def _build_kb_index_from_db(kb_id: str) -> dict:
    """直连 PostgreSQL 拉 KB 索引（绕过 API）。"""
    import os
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5432")),
        user=os.environ.get("PGUSER", "rag_user"),
        password=os.environ.get("PGPASSWORD", "rag_password"),
        dbname=os.environ.get("PGDATABASE", "rag_kb"),
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. 文档清单
            cur.execute("""
                SELECT id, filename
                FROM documents
                WHERE kb_id = %s
                ORDER BY filename
            """, (kb_id,))
            docs = cur.fetchall()

            by_filename_chunk: dict[str, str] = {}
            by_chunk_id: dict[str, dict] = {}
            doc_summaries: list[dict] = []

            for d in docs:
                # 2. 每个文档的 chunk
                cur.execute("""
                    SELECT id, chunk_index, position_info->>'source' AS src
                    FROM chunks
                    WHERE doc_id = %s
                """, (d["id"],))
                for c in cur.fetchall():
                    if c["chunk_index"] is None:
                        continue
                    src = c["src"] or d["filename"]
                    key = f"{src}_chunk{c['chunk_index']}"
                    by_filename_chunk[key.lower()] = str(c["id"])
                    by_chunk_id[str(c["id"])] = {
                        "filename": src,
                        "chunk_index": c["chunk_index"],
                        "doc_id": str(d["id"]),
                    }
                doc_summaries.append({
                    "id": str(d["id"]),
                    "filename": d["filename"],
                    "chunk_count": len([x for x in by_chunk_id.values() if x["doc_id"] == str(d["id"])]),
                })

        return {
            "kb_id": kb_id,
            "documents": doc_summaries,
            "by_filename_chunk": by_filename_chunk,
            "by_chunk_id": by_chunk_id,
            "all_filenames": [d["filename"] for d in doc_summaries],
        }
    finally:
        conn.close()


def _build_kb_index_from_api(api_url: str, kb_id: str, headers: dict) -> dict:
    """回退方案：仅从 API 拿 documents（拿不到 chunks）。"""
    docs = _fetch_documents(api_url, kb_id, headers)
    return {
        "kb_id": kb_id,
        "documents": [
            {
                "id": d.get("id") or d.get("doc_id"),
                "filename": d.get("filename") or d.get("name") or "",
                "chunk_count": 0,
            }
            for d in docs
        ],
        "by_filename_chunk": {},
        "by_chunk_id": {},
        "all_filenames": [d.get("filename", "") for d in docs],
    }


# ---------------------------------------------------------------------------
# expected_chunks 解析
# ---------------------------------------------------------------------------

_FILENAME_CHUNK_RE = None  # 改用 _split_filename_chunk
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


def _split_filename_chunk(s):
    """把 'filename_chunkN' 拆成 (filename, n)，找不到返回 None。"""
    idx = s.lower().rfind("_chunk")
    if idx <= 0:
        return None
    filename = s[:idx]
    n_str = s[idx + len("_chunk"):]
    if not n_str.isdigit():
        return None
    return filename, int(n_str)


def _parse_expected(expected_chunks: Iterable[str], index: dict) -> list[dict]:
    """解析一组 expected_chunk 字符串，返回 [{expected, format, hit, resolved}]。"""
    out = []
    for raw in expected_chunks or []:
        s = str(raw).strip()
        if not s:
            continue
        if _UUID_RE.match(s):
            hit = s in index["by_chunk_id"]
            out.append({
                "expected": s,
                "format": "uuid",
                "hit": hit,
                "resolved_filename": (
                    index["by_chunk_id"][s]["filename"]
                    if hit else None
                ),
                "resolved_chunk_index": (
                    index["by_chunk_id"][s]["chunk_index"]
                    if hit else None
                ),
            })
            continue
        # filename_chunkN 格式
        m = _split_filename_chunk(s)
        if m:
            key = s.lower()
            uuid_ = index["by_filename_chunk"].get(key)
            out.append({
                "expected": s,
                "format": "filename_chunk",
                "hit": uuid_ is not None,
                "resolved_chunk_id": uuid_,
            })
            continue
        # 既不是 UUID 也不是 filename_chunkN
        out.append({
            "expected": s,
            "format": "unknown",
            "hit": False,
            "reason": "无法解析（既不是 UUID 也不是 {filename}_chunk{N} 格式）",
        })
    return out


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def validate_dataset(
    queries: list[dict],
    api_url: str,
    kb_id_or_name: str,
    token: str,
) -> dict:
    """对一组 query 做数据集校准。

    返回：
        {
          "kb_id": "...",
          "kb_documents": 4,
          "kb_chunks_indexed": 278,
          "queries_total": 5000,
          "expected_total": 12345,
          "expected_resolved": 8000,
          "expected_missing": 4345,
          "coverage_rate": 0.648,
          "queries_with_all_hits": 4500,
          "queries_with_any_hit": 4900,
          "queries_with_zero_hits": 100,
          "missing": [{query_id, query, expected_chunks}, ...],
          "unparseable": [...],
        }
    """
    headers = {"Authorization": f"Bearer {token}"}
    index = build_kb_index(api_url, kb_id_or_name, headers)

    total_expected = 0
    total_resolved = 0
    queries_all_hit = 0
    queries_any_hit = 0
    queries_zero_hit = 0
    missing: list[dict] = []
    unparseable: list[dict] = []
    by_format = {"uuid": {"total": 0, "hit": 0},
                 "filename_chunk": {"total": 0, "hit": 0},
                 "unknown": {"total": 0, "hit": 0}}

    per_query = []
    for q in queries:
        expected = q.get("expected_chunks") or []
        parsed = _parse_expected(expected, index)
        hits = []
        misses = []
        for p in parsed:
            if p["hit"]:
                hits.append(p)
            else:
                misses.append(p)
        total_expected += len(parsed)
        total_resolved += len(hits)
        for p in parsed:
            by_format[p["format"]]["total"] += 1
            if p["hit"]:
                by_format[p["format"]]["hit"] += 1

        if not parsed:
            status = "no_expected"
        elif not misses:
            queries_all_hit += 1
            queries_any_hit += 1
            status = "all_hit"
        elif hits:
            queries_any_hit += 1
            status = "partial_hit"
        else:
            queries_zero_hit += 1
            status = "zero_hit"

        record = {
            "query_id": q.get("query_id"),
            "query": q.get("query"),
            "status": status,
            "expected_count": len(parsed),
            "hit_count": len(hits),
            "missing_count": len(misses),
            "missing": [p["expected"] for p in misses],
        }
        per_query.append(record)

        if misses:
            missing.append({
                "query_id": q.get("query_id"),
                "query": q.get("query"),
                "missing_expected": [p["expected"] for p in misses],
            })
        for p in parsed:
            if p["format"] == "unknown":
                unparseable.append({
                    "query_id": q.get("query_id"),
                    "expected": p["expected"],
                    "reason": p.get("reason"),
                })

    coverage_rate = round(total_resolved / total_expected, 4) if total_expected else 0.0

    return {
        "kb_id": index["kb_id"],
        "kb_documents": len(index["documents"]),
        "kb_chunks_indexed": len(index["by_chunk_id"]),
        "queries_total": len(queries),
        "expected_total": total_expected,
        "expected_resolved": total_resolved,
        "expected_missing": total_expected - total_resolved,
        "coverage_rate": coverage_rate,
        "queries_all_hit": queries_all_hit,
        "queries_any_hit": queries_any_hit,
        "queries_zero_hit": queries_zero_hit,
        "by_format": by_format,
        "missing": missing,
        "missing_samples": missing[:20],   # 前 20 条
        "unparseable": unparseable[:20],
        "per_query": per_query,
        "documents_summary": index["documents"],
    }


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(__import__("json").loads(line))
    return out


def _load_dataset_questions(path: Path) -> tuple[list[dict], dict]:
    """加载数据集，返回 (questions 列表, 元数据 dict)。

    支持三种格式：
      - .jsonl: 每行一个 query 对象（JSONL 格式，无元数据）
      - .json: 顶层是数组
      - .json: 顶层是 dict，含 questions 字段（v2 架构对齐格式）

    元数据 dict 始终有这些字段：
      - format: 'jsonl' | 'json_array' | 'json_v2'
      - name / version / kb_id / _dataset_meta
    """
    import json as _json
    if path.suffix == ".jsonl":
        return _load_jsonl(path), {"format": "jsonl"}

    raw = _json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw, {"format": "json_array"}

    if isinstance(raw, dict):
        if "questions" in raw and isinstance(raw["questions"], list):
            # v2 格式：剥离 _dataset_meta 等顶层元数据
            meta = {
                "format": "json_v2",
                "name": raw.get("name"),
                "version": raw.get("version"),
                "kb_id": raw.get("kb_id"),
                "_dataset_meta": raw.get("_dataset_meta", {}),
            }
            return raw["questions"], meta

    raise ValueError(
        f"未知的数据集格式: {path}，要求 .jsonl / .json(数组) / .json(顶层带 questions 字段)"
    )


def validate_dataset_file(
    dataset_path: str,
    api_url: str,
    kb_id_or_name: str,
    admin_user: str = "admin",
    admin_pass: str = "...",
) -> dict:
    """封装：登录 + 加载数据集 + 校准。支持 v1 JSONL + v2 JSON 顶层格式。"""
    token_resp = requests.post(
        f"{api_url.rstrip('/')}/api/v1/auth/login",
        data={"username": admin_user, "password": admin_pass},
        timeout=30,
    )
    token_resp.raise_for_status()
    token = token_resp.json()["access_token"]

    queries, ds_meta = _load_dataset_questions(Path(dataset_path))
    report = validate_dataset(queries, api_url, kb_id_or_name, token)
    # 把数据集元数据附加到报告（便于前端展示 v2 模板的版本号、校准状态等）
    report["dataset_meta"] = ds_meta
    return report


def _print_summary(report: dict) -> None:
    print("=" * 60)
    print("Dataset Validation Report")
    print("=" * 60)
    print(f"KB              : {report['kb_id']}")
    print(f"KB documents    : {report['kb_documents']}")
    print(f"KB chunks       : {report['kb_chunks_indexed']}")
    print(f"Queries total   : {report['queries_total']}")
    print(f"Expected total  : {report['expected_total']}")
    print(f"  Resolved      : {report['expected_resolved']}")
    print(f"  Missing       : {report['expected_missing']}")
    print(f"Coverage rate   : {report['coverage_rate']*100:.2f}%")
    print()
    print(f"Queries all_hit : {report['queries_all_hit']}")
    print(f"Queries any_hit : {report['queries_any_hit']}")
    print(f"Queries zero_hit: {report['queries_zero_hit']}")
    print()
    print("By format:")
    for fmt, stat in report["by_format"].items():
        rate = stat["hit"] / stat["total"] * 100 if stat["total"] else 0
        print(f"  {fmt:18s}: {stat['hit']:5d} / {stat['total']:5d} ({rate:.2f}%)")
    print()
    if report["missing_samples"]:
        print("Sample missing (first 10):")
        for m in report["missing_samples"][:10]:
            print(f"  - {m['query_id']}: {m['query'][:50]}")
            for me in m["missing_expected"][:3]:
                print(f"      x {me}")
    print("=" * 60)


if __name__ == "__main__":
    import argparse, json
    parser = argparse.ArgumentParser(description="数据集校准")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--kb-id", required=True)
    parser.add_argument("--api-url", default="http://localhost:8080")
    parser.add_argument("--admin-user", default="admin")
    parser.add_argument("--admin-pass", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    report = validate_dataset_file(
        dataset_path=args.dataset,
        api_url=args.api_url,
        kb_id_or_name=args.kb_id,
        admin_user=args.admin_user,
        admin_pass=args.admin_pass,
    )
    _print_summary(report)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n详细报告已写入：{args.output}")
