"""
UPS 文档检索质量评估脚本

测试 samples_2 目录下的 UPS 相关文档的检索效果。
参考 scripts/eval_retrieval.py 的逻辑。
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import requests


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 查询改写权威实现位于 backend/app/retrieval/query_rewriter.py，
# 这里按文件加载以避免拖入整个 backend 依赖栈，保持 eval 脚本独立性。
import importlib.util as _ilu
_qr_spec = _ilu.spec_from_file_location(
    "_query_rewriter", PROJECT_ROOT / "backend" / "app" / "retrieval" / "query_rewriter.py"
)
_qr_mod = _ilu.module_from_spec(_qr_spec)
_qr_spec.loader.exec_module(_qr_mod)
rewrite_query = _qr_mod.rewrite_query
SAMPLES_DIR = PROJECT_ROOT / "samples_2"

BASE_URL = os.environ.get("RAG_API_URL", "http://localhost:8080")
ADMIN_USER = os.environ.get("RAG_ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("RAG_ADMIN_PASS")

if not ADMIN_PASS:
    print(
        "[ERROR] RAG_ADMIN_PASS environment variable is not set. "
        "Set it to the admin password before running this script."
    )
    sys.exit(1)

EVAL_KB_NAME = "ups-eval-kb"
EVAL_KB_DESC = "Dedicated knowledge base for UPS document retrieval evaluation"

# Documents to use for the evaluation corpus. All files must exist under samples_2/.
SAMPLE_FILES = [
    "01_iBattery 3.0 快速指南.pdf",
    "02_iBattery 3.0 用户手册.pdf",
    "03_UPS5000-E-(20kVA-40kVA) 用户手册 (一体化UPS 2.0, 武汉工行).pdf",
    "04_UPS5000-E-(20kVA-80kVA) 快速指南 (一体化UPS, 208V).pdf",
    "05_UPS5000-E-(20kVA-80kVA) 用户手册 (一体化UPS, 208V).pdf",
    "06_UPS5000-E-(25kVA-75kVA)-BF 模块化电池柜 快速指南.pdf",
    "07_UPS5000-E-(25kVA-75kVA)-BF 用户手册.pdf",
    "08_UPS5000-E-(25kVA-75kVA)-SM 快速指南 (半柜高).pdf",
    "09_UPS5000-E-(25kVA-75kVA) V100R003C01 培训资料.ppt",
    "10_UPS5000-E 监控模块 用户手册.pdf",
    "11_UPS5000-E 维护指南.pdf",
    "12_UPS5000-E 资料全景图.pdf",
    "13_UPS5000&SmartLi FAQ.pdf",
    "14_UPS5000&SmartLi 机柜底座接口图.xlsx",
    "15_UPS5000 上出风边柜 用户手册.pdf",
    "16_UPS5000 产品介绍 培训资料 (50K特性, 40K&50K切换场景).ppt",
    "17_UPS5000 反灌保护卡 用户手册 (0302080427, 03021KQQ).pdf",
    "18_UPS5000 告警参考.pdf",
    "19_UPS5000 安全须知.pdf",
    "20_UPS5000 干接点扩展卡 用户手册 (03021RKN).pdf",
]

# Annotated queries. Each entry maps a natural-language query to the set of
# sample filenames that are considered relevant for that query.
QUERY_ANNOTATIONS: List[Dict[str, Any]] = [
    {
        "query": "SOH显示电池异常，电池放电电压较低。",
        "expected_files": [
            "02_iBattery 3.0 用户手册.pdf_chunk65",
        ],
    },
    {
        "query": "iBOX的RF_Z指示灯不亮了",
        "expected_files": [
            "01_iBattery 3.0 快速指南.pdf_chunk14",
            "02_iBattery 3.0 用户手册.pdf_chunk55",
            "02_iBattery 3.0 用户手册.pdf_chunk77",
        ],
    },
    {
        "query": "下发电池电压低关机的命令是什么",
        "expected_files": [
            "03_UPS5000-E-(20kVA-40kVA) 用户手册 (一体化UPS 2.0, 武汉工行).pdf_chunk185",
            "03_UPS5000-E-(20kVA-40kVA) 用户手册 (一体化UPS 2.0, 武汉工行).pdf_chunk186",
            "03_UPS5000-E-(20kVA-40kVA) 用户手册 (一体化UPS 2.0, 武汉工行).pdf_chunk187",
            "05_UPS5000-E-(20kVA-80kVA) 用户手册 (一体化UPS, 208V).pdf_chunk197",
            "05_UPS5000-E-(20kVA-80kVA) 用户手册 (一体化UPS, 208V).pdf_chunk198",
        ],
    },
    {
        "query": "输出开关断开，是什么问题",
        "expected_files": [
            "18_UPS5000 告警参考.pdf_chunk654",
            "18_UPS5000 告警参考.pdf_chunk655",
        ],
    },
    {
        "query": "UPS5000E工作模式_维修旁路是什么",
        "expected_files": [
            "09_UPS5000-E-(25kVA-75kVA) V100R003C01 培训资料.ppt_chunk1",
            "09_UPS5000-E-(25kVA-75kVA) V100R003C01 培训资料.ppt_chunk2",
        ],
    },
    {
        "query": "怎么连接出风边柜电源线",
        "expected_files": [
            "15_UPS5000 上出风边柜 用户手册.pdf_chunk13",
            "15_UPS5000 上出风边柜 用户手册.pdf_chunk14",
        ],
    },
    {
        "query": "MDU显示屏接口有哪些",
        "expected_files": [
            "07_UPS5000-E-(25kVA-75kVA)-BF 用户手册.pdf_chunk83",
            "07_UPS5000-E-(25kVA-75kVA)-BF 用户手册.pdf_chunk84",
        ],
    },
    {
        "query": "母线电压未升起，UPS整流器无法工作",
        "expected_files": [
            "07_UPS5000-E-(25kVA-75kVA)-BF 用户手册.pdf_chunk178",
            "11_UPS5000-E 维护指南.pdf_chunk67",
            "18_UPS5000 告警参考.pdf_chunk308",
        ],
    },
    {
        "query": "支脚机柜2400*850（四柜）的底座是如何并联的",
        "expected_files": [
            "14_UPS5000&SmartLi 机柜底座接口图.xlsx_chunk2",    # 选型目录: 支脚机柜2400*850（四柜）规格行
            "14_UPS5000&SmartLi 机柜底座接口图.xlsx_chunk13",   # P6: 支脚机柜2400*850（四柜）图纸 + 技术要求(含螺栓并联)
        ],
    },
    {
        "query": "电池冷启动操作步骤",
        "expected_files": [
            "07_UPS5000-E-(25kVA-75kVA)-BF 用户手册.pdf_chunk164",   # 电池冷启动操作步骤
        ],
    },
    # =====================================================================
    # 新增 10 条 query（2026-07-22）：覆盖更多文档与问题类型
    # =====================================================================
    {
        "query": "UPS5000安装对环境有什么要求？",
        "expected_files": [
            "19_UPS5000 安全须知.pdf_chunk0",   # 环境要求：清洁干燥、通风良好、防尘防凝露
        ],
    },
    {
        "query": "UPS出现0060-027逆变器异常告警应如何处理？",
        "expected_files": [
            "13_UPS5000&SmartLi FAQ.pdf_chunk5",   # 处理方法1：输出空开断开 → 插拔模块
            "13_UPS5000&SmartLi FAQ.pdf_chunk6",   # 处理方法2：无输出空开 → 更换功率模块
        ],
    },
    {
        "query": "如何对UPS电池进行浅放电测试？",
        "expected_files": [
            "11_UPS5000-E 维护指南.pdf_chunk60",   # 自动浅放电测试（铅酸电池）
            "11_UPS5000-E 维护指南.pdf_chunk62",   # 手动浅放电测试（锂电池）
        ],
    },
    {
        "query": "BF电池柜的CAN扩展卡拨码开关如何设置？",
        "expected_files": [
            "06_UPS5000-E-(25kVA-75kVA)-BF 模块化电池柜 快速指南.pdf_chunk3",   # DIP2-DIP4对应UPS/电池柜1-4地址
        ],
    },
    {
        "query": "UPS5000-E监控模块的LCD界面由哪几部分组成？",
        "expected_files": [
            "10_UPS5000-E 监控模块 用户手册.pdf_chunk43",   # 状态栏、告警栏、信息显示栏
        ],
    },
    {
        "query": "UPS系统的admin管理员用户默认密码是什么？",
        "expected_files": [
            "10_UPS5000-E 监控模块 用户手册.pdf_chunk46",   # LCD=000001, WEB=Changeme
            "11_UPS5000-E 维护指南.pdf_chunk64",            # 同上（维护指南版本）
            "20_UPS5000 干接点扩展卡 用户手册 (03021RKN).pdf_chunk11",  # 同上（干接点卡版本）
        ],
    },
    {
        "query": "如何安装反灌保护卡？安装时有哪些安全注意事项？",
        "expected_files": [
            "17_UPS5000 反灌保护卡 用户手册 (0302080427, 03021KQQ).pdf_chunk31",   # 支持热插拔，必须佩戴绝缘手套
        ],
    },
    {
        "query": "如何通过LCD或WEB界面设置干接点扩展卡的DO和DI端口？",
        "expected_files": [
            "20_UPS5000 干接点扩展卡 用户手册 (03021RKN).pdf_chunk12",   # LCD/WEB 设置路径和步骤
        ],
    },
    {
        "query": "UPS5000-E-(20kVA-80kVA) 208V版本如何进行无紧固安装调平？",
        "expected_files": [
            "04_UPS5000-E-(20kVA-80kVA) 快速指南 (一体化UPS, 208V).pdf_chunk1",   # 调节地脚螺栓0-8mm
            "04_UPS5000-E-(20kVA-80kVA) 快速指南 (一体化UPS, 208V).pdf_chunk2",   # 滚轮悬空、水平尺校验
        ],
    },
    {
        "query": "UPS5000-E-SM半柜高各接口的螺栓规格和扭力力矩是多少？",
        "expected_files": [
            "08_UPS5000-E-(25kVA-75kVA)-SM 快速指南 (半柜高).pdf_chunk1",   # 螺栓规格表：主路M8/20N·m，电池M10/35N·m等
            "08_UPS5000-E-(25kVA-75kVA)-SM 快速指南 (半柜高).pdf_chunk2",   # 续螺栓规格表 + 接线说明
        ],
    },
]

K_VALUES = [1, 3, 5, 10]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def login(username: str, password: str) -> str:
    resp = requests.post(
        f"{BASE_URL}/api/v1/auth/login",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    print(f"[OK] Logged in as {username}")
    return token


def ensure_eval_kb(token: str) -> str:
    """Create the evaluation KB if it does not exist; otherwise reuse it."""
    resp = requests.get(
        f"{BASE_URL}/api/v1/knowledge-bases",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    for kb in resp.json():
        if kb.get("name") == EVAL_KB_NAME:
            print(f"[OK] Reusing evaluation KB '{EVAL_KB_NAME}': {kb['id']}")
            return kb["id"]

    resp = requests.post(
        f"{BASE_URL}/api/v1/knowledge-bases",
        json={"name": EVAL_KB_NAME, "description": EVAL_KB_DESC, "config": {}},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    resp.raise_for_status()
    kb_id = resp.json()["id"]
    print(f"[OK] Created evaluation KB '{EVAL_KB_NAME}': {kb_id}")
    return kb_id


def upload_file(token: str, kb_id: str, file_path: Path) -> Dict[str, Any]:
    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{BASE_URL}/api/v1/documents",
            data={"kb_id": kb_id, "title": file_path.name},
            files={"file": (file_path.name, f, "application/octet-stream")},
            headers={"Authorization": f"Bearer {token}"},
        )
    resp.raise_for_status()
    return resp.json()


# 2026-07-03: 新增函数 - 检查文件是否已存在，避免重复上传
def upload_file_if_not_exists(
    token: str, kb_id: str, file_path: Path, existing_docs: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """如果文件不存在才上传，避免重复上传导致数据重复"""
    filename = file_path.name

    # 检查文件是否已存在
    for doc in existing_docs:
        if doc.get("filename") == filename:
            print(f"[SKIP] {filename} already exists (doc_id: {doc.get('id')})")
            return doc

    # 文件不存在，上传
    return upload_file(token, kb_id, file_path)


def list_docs(token: str, kb_id: str) -> List[Dict[str, Any]]:
    resp = requests.get(
        f"{BASE_URL}/api/v1/documents/{kb_id}?limit=100",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    return resp.json().get("items", [])


def wait_for_indexing(token: str, kb_id: str, timeout: int = 300) -> bool:
    print(f"[INFO] Waiting for documents in KB {kb_id} to be indexed (timeout {timeout}s)...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        docs = list_docs(token, kb_id)
        if not docs:
            time.sleep(2)
            continue
        pending = [d for d in docs if d.get("status") in ("pending", "processing")]
        if not pending:
            indexed = [d for d in docs if d.get("status") == "indexed"]
            print(f"[OK] All {len(docs)} documents processed ({len(indexed)} indexed)")
            return True
        statuses = [f"{d.get('filename', 'doc')}:{d.get('status')}" for d in pending[:5]]
        print(f"[INFO] Waiting for {len(pending)} docs: {', '.join(statuses)}...")
        time.sleep(5)
    print("[WARN] Timeout waiting for document processing")
    return False


def search(token: str, kb_id: str, query: str, mode: str, top_k: int, rerank_top_k: int) -> Dict[str, Any]:
    url = f"{BASE_URL}/api/v1/search"
    # 对 keyword 模式做查询改写（剥离疑问词）
    if mode == "keyword":
        rw = rewrite_query(query)
        if rw != query:
            print(f"    (改写: '{query[:40]}' → '{rw}')")
            query = rw
    if mode in ("semantic", "keyword"):
        url = f"{url}/{mode}"
    resp = requests.post(
        url,
        json={
            "query": query,
            "kb_ids": [kb_id],
            "mode": mode,
            "top_k": top_k,
            "rerank_top_k": rerank_top_k,
        },
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------


def recall_at_k(retrieved_doc_ids: Sequence[str], relevant_doc_ids: Set[str], k: int) -> float:
    if not relevant_doc_ids:
        return 0.0
    retrieved_k = retrieved_doc_ids[:k]
    relevant_retrieved = len(set(retrieved_k) & relevant_doc_ids)
    return relevant_retrieved / len(relevant_doc_ids)


def precision_at_k(retrieved_doc_ids: Sequence[str], relevant_doc_ids: Set[str], k: int) -> float:
    if k == 0:
        return 0.0
    retrieved_k = retrieved_doc_ids[:k]
    relevant_retrieved = len(set(retrieved_k) & relevant_doc_ids)
    return relevant_retrieved / k


def mrr(retrieved_doc_ids: Sequence[str], relevant_doc_ids: Set[str]) -> float:
    for rank, doc_id in enumerate(retrieved_doc_ids, start=1):
        if doc_id in relevant_doc_ids:
            return 1.0 / rank
    return 0.0


def dcg_at_k(relevances: Sequence[int], k: int) -> float:
    return sum(
        rel / math.log2(idx + 2) for idx, rel in enumerate(relevances[:k])
    )


def ndcg_at_k(retrieved_doc_ids: Sequence[str], relevant_doc_ids: Set[str], k: int) -> float:
    relevances = [1 if doc_id in relevant_doc_ids else 0 for doc_id in retrieved_doc_ids]
    ideal_relevances = sorted(relevances, reverse=True)
    dcg = dcg_at_k(relevances, k)
    idcg = dcg_at_k(ideal_relevances, k)
    return dcg / idcg if idcg > 0 else 0.0


# ---------------------------------------------------------------------------
# Evaluation orchestration
# ---------------------------------------------------------------------------


def build_filename_to_doc_id(docs: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for doc in docs:
        filename = doc.get("filename") or doc.get("title")
        doc_id = doc.get("id")
        if filename and doc_id:
            mapping[filename] = str(doc_id)
    return mapping


def evaluate_query(
    token: str,
    kb_id: str,
    query: str,
    relevant_doc_ids: Set[str],
    doc_id_to_filename: Dict[str, str] = None,
    modes: Sequence[str] = ("hybrid", "semantic", "keyword"),
    top_k: int = 10,
    rerank_top_k: int = 20,
) -> Dict[str, Any]:
    per_mode: Dict[str, Any] = {}
    # 解析期望列表，分离 chunk 级和文件级
    expected_filenames: Set[str] = set()
    expected_chunks: Set[str] = set()
    for e in relevant_doc_ids:
        if '_chunk' in e:
            expected_chunks.add(e)
            # 也提取文件名部分，用于文件名级别匹配
            fname = e.split('_chunk')[0]
            expected_filenames.add(fname)
        else:
            expected_filenames.add(e)

    for mode in modes:
        response = search(token, kb_id, query, mode, top_k, rerank_top_k)
        retrieved_doc_ids = [r.get("doc_id") for r in response.get("results", []) if r.get("doc_id")]

        # chunk 级匹配
        retrieved_chunk_ids = []
        for r in response.get("results", []):
            doc_id = r.get("doc_id", "")
            chunk_idx = (r.get("position_info") or {}).get("chunk_index", "")
            fname = doc_id_to_filename.get(doc_id, doc_id[:8]) if doc_id_to_filename else doc_id[:8]
            if chunk_idx is not None:
                retrieved_chunk_ids.append(f"{fname}_chunk{chunk_idx}")
            else:
                retrieved_chunk_ids.append(fname)

        # 对 chunk 级期望，用 retrieved_chunk_ids 计算；否则用 retrieved_doc_ids
        if expected_chunks:
            used_retrieved = retrieved_chunk_ids
            used_relevant = expected_chunks | expected_filenames
        else:
            used_retrieved = retrieved_doc_ids
            used_relevant = expected_filenames

        per_mode[mode] = {
            "total": response.get("total", 0),
            "retrieved_doc_ids": retrieved_doc_ids,
            "retrieved_chunk_ids": retrieved_chunk_ids[:10],
            "results_raw": response.get("results", []),
            "recall@k": {k: recall_at_k(used_retrieved, used_relevant, k) for k in K_VALUES},
            "precision@k": {k: precision_at_k(used_retrieved, used_relevant, k) for k in K_VALUES},
            "mrr": mrr(used_retrieved, used_relevant),
            "ndcg@k": {k: ndcg_at_k(used_retrieved, used_relevant, k) for k in K_VALUES},
        }
    return {"query": query, "relevant_doc_ids": relevant_doc_ids, "modes": per_mode}


def average(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def aggregate_metrics(
    results: Sequence[Dict[str, Any]], modes: Sequence[str]
) -> Dict[str, Dict[str, float]]:
    aggregates: Dict[str, Dict[str, Any]] = {}
    for mode in modes:
        recalls = {k: [] for k in K_VALUES}
        precisions = {k: [] for k in K_VALUES}
        mrrs: List[float] = []
        ndcgs = {k: [] for k in K_VALUES}

        for r in results:
            mode_result = r["modes"][mode]
            for k in K_VALUES:
                recalls[k].append(mode_result["recall@k"][k])
                precisions[k].append(mode_result["precision@k"][k])
                ndcgs[k].append(mode_result["ndcg@k"][k])
            mrrs.append(mode_result["mrr"])

        aggregates[mode] = {
            f"recall@{k}": average(recalls[k]) for k in K_VALUES
        }
        aggregates[mode].update({f"precision@{k}": average(precisions[k]) for k in K_VALUES})
        aggregates[mode].update({f"ndcg@{k}": average(ndcgs[k]) for k in K_VALUES})
        aggregates[mode]["mrr"] = average(mrrs)

    return aggregates


def print_results(
    results: Sequence[Dict[str, Any]],
    aggregates: Dict[str, Dict[str, float]],
    modes: Sequence[str],
    doc_id_to_filename: Dict[str, str] = None,
) -> None:
    """打印测试结果，包括每个 query 返回的具体文件"""
    print("\n" + "=" * 80)
    print("PER-QUERY RESULTS")
    print("=" * 80)
    for r in results:
        print(f"\nQuery: {r['query']}")

        # 打印期望的文件/chunks
        expected_files = []
        for doc_id in sorted(r['relevant_doc_ids']):
            if '_chunk' in doc_id:
                expected_files.append(doc_id)  # chunk 级标注直接显示全名
            elif doc_id_to_filename and doc_id in doc_id_to_filename:
                expected_files.append(f"{doc_id_to_filename[doc_id]}")
            else:
                expected_files.append(doc_id[:8])
        print(f"Expected files: {expected_files}")

        for mode in modes:
            mode_result = r["modes"][mode]
            print(f"  [{mode:8}] total={mode_result['total']}")

            # 显示返回的 chunks（按实际排名，不按文件去重）
            retrieved_chunk_ids = mode_result.get('retrieved_chunk_ids', [])
            if retrieved_chunk_ids:
                display = retrieved_chunk_ids[:5]  # 只显示前5个，不按文件去重
                print(f"    top chunks : {display}")
            elif mode == "hybrid" and doc_id_to_filename:
                retrieved_doc_ids = mode_result.get('retrieved_doc_ids', [])
                retrieved_files = []
                seen_doc_ids = set()
                for doc_id in retrieved_doc_ids:
                    if doc_id in seen_doc_ids:
                        continue
                    seen_doc_ids.add(doc_id)
                    if doc_id in doc_id_to_filename:
                        retrieved_files.append(doc_id_to_filename[doc_id])
                    else:
                        retrieved_files.append(doc_id[:8])
                    if len(retrieved_files) >= 5:
                        break
                print(f"    returned    : {retrieved_files}")

            print(f"    recall@k    : " + ", ".join(f"@{k}={mode_result['recall@k'][k]:.2f}" for k in K_VALUES))
            print(f"    precision@k : " + ", ".join(f"@{k}={mode_result['precision@k'][k]:.2f}" for k in K_VALUES))
            print(f"    ndcg@k      : " + ", ".join(f"@{k}={mode_result['ndcg@k'][k]:.2f}" for k in K_VALUES))
            print(f"    mrr         : {mode_result['mrr']:.2f}")

    print("\n" + "=" * 80)
    print("AGGREGATE METRICS")
    print("=" * 80)
    for mode in modes:
        print(f"\nMode: {mode}")
        for metric in ["mrr"] + [f"recall@{k}" for k in K_VALUES] + [f"precision@{k}" for k in K_VALUES] + [f"ndcg@{k}" for k in K_VALUES]:
            print(f"  {metric:12}: {aggregates[mode].get(metric, 0.0):.3f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate UPS document retrieval quality")
    parser.add_argument(
        "--reuse-kb",
        action="store_true",
        help="Reuse the existing evaluation KB instead of creating a new one",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Skip upload and assume the evaluation KB already contains indexed docs",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=30,
        help="Per-channel recall count passed to the search API",
    )
    parser.add_argument(
        "--rerank-top-k",
        type=int,
        default=20,
        help="Number of results returned after reranking",
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=300,
        help="Maximum seconds to wait for document indexing",
    )
    parser.add_argument(
        "--run-new-only",
        action="store_true",
        help="只跑新增的10条query（跳过原来的10条）",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    modes = ("hybrid", "semantic", "keyword")

    print("=" * 80)
    print("UPS Document Retrieval Quality Evaluation")
    print(f"API: {BASE_URL}")
    print(f"KB : {EVAL_KB_NAME}")
    print("=" * 80)

    # Validate sample files exist.
    missing = [f for f in SAMPLE_FILES if not (SAMPLES_DIR / f).exists()]
    if missing:
        print(f"[ERROR] Missing sample files: {missing}")
        return 1

    token = login(ADMIN_USER, ADMIN_PASS)

    if args.skip_upload:
        # Find the eval KB by name.
        resp = requests.get(
            f"{BASE_URL}/api/v1/knowledge-bases",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        kb_id = None
        for kb in resp.json():
            if kb.get("name") == EVAL_KB_NAME:
                kb_id = kb["id"]
                break
        if not kb_id:
            print(f"[ERROR] Reuse requested but KB '{EVAL_KB_NAME}' not found")
            return 1
        print(f"[OK] Reusing KB {kb_id}")
    else:
        kb_id = ensure_eval_kb(token)

        # 2026-07-03: 修改上传逻辑 - 检查文件是否已存在，避免重复上传
        # Upload sample files. Track filename -> doc_id as we go.
        print("\n[INFO] Uploading sample documents...")
        # 先获取已存在的文档列表
        existing_docs = list_docs(token, kb_id)
        filename_to_doc_id: Dict[str, str] = {}
        for filename in SAMPLE_FILES:
            file_path = SAMPLES_DIR / filename
            try:
                doc = upload_file_if_not_exists(token, kb_id, file_path, existing_docs)
                filename_to_doc_id[filename] = doc["id"]
                if doc.get("status") == "indexed":
                    print(f"[OK] {filename} already indexed (doc_id: {doc['id']})")
                else:
                    print(f"[OK] Uploaded {filename} -> {doc['id']}")
            except requests.HTTPError as exc:
                print(f"[ERROR] Failed to upload {filename}: {exc.response.text}")
                return 1

        # Wait for ingestion/indexing.
        if not wait_for_indexing(token, kb_id, timeout=args.wait_timeout):
            print("[ERROR] Documents did not finish indexing in time")
            return 1

    # Rebuild filename -> doc_id mapping from the backend state.
    docs = list_docs(token, kb_id)
    filename_to_doc_id = build_filename_to_doc_id(docs)
    indexed_count = sum(1 for d in docs if d.get("status") == "indexed")
    print(f"\n[INFO] KB {kb_id} has {indexed_count}/{len(docs)} indexed documents")
    if indexed_count < len(SAMPLE_FILES):
        print("[WARN] Not all sample documents are indexed")

    # 2026-07-22: 支持只跑新增的10条query
    active_queries = QUERY_ANNOTATIONS[10:] if args.run_new_only else QUERY_ANNOTATIONS
    if args.run_new_only:
        print(f"[INFO] --run-new-only: 只跑新增的 {len(active_queries)} 条 query")

    # Translate filename annotations to doc_id annotations.
    annotated_queries: List[Tuple[str, Set[str]]] = []
    for qa in active_queries:
        relevant_doc_ids: Set[str] = set()
        for filename in qa["expected_files"]:
            # 支持 chunk 级别标注：filename_chunkN，去掉 _chunkN 获取文档名
            doc_key = filename
            if '_chunk' in filename:
                doc_name = filename.split('_chunk')[0]
            else:
                doc_name = filename
            # 先精确匹配，再模糊匹配
            doc_id = filename_to_doc_id.get(doc_name)
            if not doc_id:
                # 模糊匹配：截断后匹配（处理文件名被截断的情况）
                for mapped_name, mapped_id in filename_to_doc_id.items():
                    if doc_name in mapped_name or mapped_name in doc_name:
                        doc_id = mapped_id
                        break
            if doc_id:
                relevant_doc_ids.add(doc_key)
            else:
                print(f"[WARN] Could not map expected file '{doc_name}' to a doc_id")
                continue
        if relevant_doc_ids:
            annotated_queries.append((qa["query"], relevant_doc_ids))

    # Run evaluation.
    print("\n[INFO] Running evaluation queries...")
    results: List[Dict[str, Any]] = []
    # 构建反向映射: doc_id -> filename
    doc_id_to_filename = {v: k for k, v in filename_to_doc_id.items()}

    for query, relevant_doc_ids in annotated_queries:
        result = evaluate_query(
            token=token,
            kb_id=kb_id,
            query=query,
            relevant_doc_ids=relevant_doc_ids,
            doc_id_to_filename=doc_id_to_filename,
        )
        results.append(result)

    aggregates = aggregate_metrics(results, modes)

    # 2026-07-03: 构建 doc_id -> filename 的反向映射
    doc_id_to_filename = {v: k for k, v in filename_to_doc_id.items()}
    print_results(results, aggregates, modes, doc_id_to_filename)

    print("\n" + "=" * 80)
    print("EVALUATION COMPLETE")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
