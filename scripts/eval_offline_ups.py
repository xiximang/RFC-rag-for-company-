"""
离线 UPS eval：预生成 query 向量查 pgvector + BM25 API + Reranker
"""
from __future__ import annotations
import argparse, json, math, os, sys, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
import requests, psycopg2

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 查询改写权威实现位于 backend/app/retrieval/query_rewriter.py，
# 按文件加载以避免拖入整个 backend 依赖栈，保持 eval 脚本独立性。
import importlib.util as _ilu
_qr_spec = _ilu.spec_from_file_location(
    "_query_rewriter", PROJECT_ROOT / "backend" / "app" / "retrieval" / "query_rewriter.py"
)
_qr_mod = _ilu.module_from_spec(_qr_spec)
_qr_spec.loader.exec_module(_qr_mod)
rewrite_query = _qr_mod.rewrite_query
BASE_URL = os.environ.get("RAG_API_URL", "http://localhost:8080")
ADMIN_USER = os.environ.get("RAG_ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("RAG_ADMIN_PASS")
VECTORS_PATH = PROJECT_ROOT / "samples_2" / "test_result" / "query_vectors.json"
KB_ID = "c93132f7-3664-4b0d-9d35-4fb88a0e7375"
DB_URL = "postgresql://rag_user:rag_password@localhost:5432/rag_kb"
RRF_K = 30
RERANK_API = "https://yunwu.ai/v1/rerank"
RERANK_KEY = "sk-7z3dhC0HIC8LDJPZWF2w82UnZOLzyDvDsDHHCWrAefPkGaZz"
RERANK_MODEL = "qwen3-rerank"

K_VALUES = [1, 3, 5, 10, 20, 30, 50]

QUERY_ANNOTATIONS: List[Dict[str, Any]] = [
    {"query":"SOH显示电池异常，电池放电电压较低。","expected_files":["02_iBattery 3.0 用户手册.pdf_chunk65"]},
    {"query":"iBOX的RF_Z指示灯不亮了","expected_files":["01_iBattery 3.0 快速指南.pdf_chunk14","02_iBattery 3.0 用户手册.pdf_chunk55","02_iBattery 3.0 用户手册.pdf_chunk77"]},
    {"query":"下发电池电压低关机的命令是什么","expected_files":["03_UPS5000-E-(20kVA-40kVA) 用户手册 (一体化UPS 2.0, 武汉工行).pdf_chunk185","03_UPS5000-E-(20kVA-40kVA) 用户手册 (一体化UPS 2.0, 武汉工行).pdf_chunk186","03_UPS5000-E-(20kVA-40kVA) 用户手册 (一体化UPS 2.0, 武汉工行).pdf_chunk187","05_UPS5000-E-(20kVA-80kVA) 用户手册 (一体化UPS, 208V).pdf_chunk197","05_UPS5000-E-(20kVA-80kVA) 用户手册 (一体化UPS, 208V).pdf_chunk198"]},
    {"query":"输出开关断开，是什么问题","expected_files":["18_UPS5000 告警参考.pdf_chunk654","18_UPS5000 告警参考.pdf_chunk655"]},
    {"query":"UPS5000E工作模式_维修旁路是什么","expected_files":["09_UPS5000-E-(25kVA-75kVA) V100R003C01 培训资料.ppt_chunk1","09_UPS5000-E-(25kVA-75kVA) V100R003C01 培训资料.ppt_chunk2"]},
    {"query":"怎么连接出风边柜电源线","expected_files":["15_UPS5000 上出风边柜 用户手册.pdf_chunk13","15_UPS5000 上出风边柜 用户手册.pdf_chunk14"]},
    {"query":"MDU显示屏接口有哪些","expected_files":["07_UPS5000-E-(25kVA-75kVA)-BF 用户手册.pdf_chunk83","07_UPS5000-E-(25kVA-75kVA)-BF 用户手册.pdf_chunk84"]},
    {"query":"母线电压未升起，UPS整流器无法工作","expected_files":["07_UPS5000-E-(25kVA-75kVA)-BF 用户手册.pdf_chunk178","11_UPS5000-E 维护指南.pdf_chunk67","18_UPS5000 告警参考.pdf_chunk308"]},
    {"query":"支脚机柜2400*850（四柜）的底座是如何并联的","expected_files":["14_UPS5000&SmartLi 机柜底座接口图.xlsx_chunk2","14_UPS5000&SmartLi 机柜底座接口图.xlsx_chunk13"]},
    {"query":"电池冷启动操作步骤","expected_files":["07_UPS5000-E-(25kVA-75kVA)-BF 用户手册.pdf_chunk164"]},
    # 新增 10 条 query（2026-07-22）：覆盖更多文档与问题类型
    {"query":"UPS5000安装对环境有什么要求？","expected_files":["19_UPS5000 安全须知.pdf_chunk0"]},
    {"query":"UPS出现0060-027逆变器异常告警应如何处理？","expected_files":["13_UPS5000&SmartLi FAQ.pdf_chunk5","13_UPS5000&SmartLi FAQ.pdf_chunk6"]},
    {"query":"如何对UPS电池进行浅放电测试？","expected_files":["11_UPS5000-E 维护指南.pdf_chunk60","11_UPS5000-E 维护指南.pdf_chunk62"]},
    {"query":"BF电池柜的CAN扩展卡拨码开关如何设置？","expected_files":["06_UPS5000-E-(25kVA-75kVA)-BF 模块化电池柜 快速指南.pdf_chunk3"]},
    {"query":"UPS5000-E监控模块的LCD界面由哪几部分组成？","expected_files":["10_UPS5000-E 监控模块 用户手册.pdf_chunk43"]},
    {"query":"UPS系统的admin管理员用户默认密码是什么？","expected_files":["10_UPS5000-E 监控模块 用户手册.pdf_chunk46","11_UPS5000-E 维护指南.pdf_chunk64","20_UPS5000 干接点扩展卡 用户手册 (03021RKN).pdf_chunk11"]},
    {"query":"如何安装反灌保护卡？安装时有哪些安全注意事项？","expected_files":["17_UPS5000 反灌保护卡 用户手册 (0302080427, 03021KQQ).pdf_chunk31"]},
    {"query":"如何通过LCD或WEB界面设置干接点扩展卡的DO和DI端口？","expected_files":["20_UPS5000 干接点扩展卡 用户手册 (03021RKN).pdf_chunk12"]},
    {"query":"UPS5000-E-(20kVA-80kVA) 208V版本如何进行无紧固安装调平？","expected_files":["04_UPS5000-E-(20kVA-80kVA) 快速指南 (一体化UPS, 208V).pdf_chunk1","04_UPS5000-E-(20kVA-80kVA) 快速指南 (一体化UPS, 208V).pdf_chunk2"]},
    {"query":"UPS5000-E-SM半柜高各接口的螺栓规格和扭力力矩是多少？","expected_files":["08_UPS5000-E-(25kVA-75kVA)-SM 快速指南 (半柜高).pdf_chunk1","08_UPS5000-E-(25kVA-75kVA)-SM 快速指南 (半柜高).pdf_chunk2"]},
]

# ── Metrics ──
def recall_at_k(retrieved, relevant, k):
    if not relevant: return 0.0
    return len(set(retrieved[:k]) & relevant) / len(relevant)
def precision_at_k(retrieved, relevant, k):
    return len(set(retrieved[:k]) & relevant) / k if k > 0 else 0.0
def mrr(retrieved, relevant):
    for i, d in enumerate(retrieved, 1):
        if d in relevant: return 1.0/i
    return 0.0
def ndcg_at_k(retrieved, relevant, k):
    rels = [1 if d in relevant else 0 for d in retrieved[:k]]
    ideal = sorted(rels, reverse=True)
    dcg = sum(r/math.log2(i+2) for i,r in enumerate(rels))
    idcg = sum(r/math.log2(i+2) for i,r in enumerate(ideal))
    return dcg/idcg if idcg > 0 else 0.0

def login() -> str:
    r = requests.post(f"{BASE_URL}/api/v1/auth/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASS},
        headers={"Content-Type":"application/x-www-form-urlencoded"})
    if r.status_code != 200: print(f"[ERROR] 登录失败"); return ""
    return r.json()["access_token"]

def build_mapping(token: str) -> Tuple[Dict[str,str], Dict[str,str]]:
    r = requests.get(f"{BASE_URL}/api/v1/documents/{KB_ID}?limit=100",
        headers={"Authorization":f"Bearer {token}"})
    fn2id, id2fn = {}, {}
    for d in r.json().get("items",[]):
        fn = d.get("filename") or d.get("title")
        did = str(d["id"]) if d.get("id") else None
        if fn and did:
            fn2id[fn] = did
            id2fn[did] = fn
    return fn2id, id2fn

def search_pgvector(qvec: List[float], top_k: int, id2fn: Dict[str,str]) -> List[Dict]:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("""
        SELECT c.id::text, c.chunk_index, c.content, c.doc_id::text
        FROM text_chunk_vectors v
        JOIN chunks c ON c.id::text = v.chunk_id
        WHERE v.kb_id = %s
        ORDER BY v.embedding <=> %s::vector
        LIMIT %s
    """, (KB_ID, json.dumps(qvec), top_k))
    rows = cur.fetchall()
    cur.close(); conn.close()
    items = []
    for cid, ci, content, doc_id in rows:
        fname = id2fn.get(doc_id, doc_id[:8])
        items.append({"chunk_id": cid, "chunk_index": ci, "content": content,
                      "doc_id": doc_id, "filename": fname, "score": 0})
    return items

def search_keyword(query: str, token: str, top_k: int, id2fn: Dict[str,str]) -> List[Dict]:
    r = requests.post(f"{BASE_URL}/api/v1/search/keyword",
        json={"query":query,"kb_ids":[KB_ID],"top_k":top_k,"rerank_top_k":top_k},
        headers={"Authorization":f"Bearer {token}"}, timeout=30)
    if r.status_code != 200: return []
    items = []
    for item in r.json().get("results",[]):
        ci = (item.get("position_info") or {}).get("chunk_index","")
        doc_id = item.get("doc_id","")
        fname = id2fn.get(doc_id, doc_id[:8])
        items.append({"chunk_id": item.get("chunk_id"), "chunk_index": ci,
                      "content": item.get("content",""), "doc_id": doc_id,
                      "filename": fname, "score": item.get("score",0)})
    return items

def rrf_fuse(semantic: List[Dict], keyword: List[Dict], top_k: int) -> List[Dict]:
    scores = {}
    by_key = {}
    for rank, item in enumerate(semantic, 1):
        key = f"{item['filename']}_chunk{item['chunk_index']}"
        scores[key] = scores.get(key, 0) + 1.0/(RRF_K+rank)
        by_key[key] = item
    for rank, item in enumerate(keyword, 1):
        key = f"{item['filename']}_chunk{item['chunk_index']}"
        scores[key] = scores.get(key, 0) + 1.0/(RRF_K+rank)
        by_key[key] = item
    sorted_keys = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:top_k]
    return [by_key[k] for k in sorted_keys]

def call_reranker(query: str, items: List[Dict], top_k: int) -> List[Dict]:
    if not items: return items
    docs = [it["content"][:500] for it in items]
    try:
        r = requests.post(RERANK_API, json={"model":RERANK_MODEL,"query":query,"documents":docs,"top_n":top_k},
            headers={"Authorization":f"Bearer {RERANK_KEY}"}, timeout=60)
        if r.status_code == 200:
            results = r.json().get("results",[])
            reranked = []
            for res in results:
                idx = res.get("index")
                if idx is not None and idx < len(items):
                    it = dict(items[idx])
                    it["rerank_score"] = res.get("relevance_score", 0)
                    reranked.append(it)
            reranked.sort(key=lambda x: x.get("rerank_score",0), reverse=True)
            if reranked:
                return reranked[:top_k]
    except:
        pass
    return items[:top_k]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=30)
    parser.add_argument("--reranker", action="store_true", help="开启 reranker")
    args = parser.parse_args(argv)
    TOP_K = args.top_k

    if not VECTORS_PATH.exists():
        print(f"[ERROR] 找不到 {VECTORS_PATH}"); return 1
    vec_data = json.loads(VECTORS_PATH.read_text())
    query_vecs = {d["query"]:d["vector"] for d in vec_data}

    token = login()
    if not token: return 1
    fn2id, id2fn = build_mapping(token)

    all_results = []
    for qa in QUERY_ANNOTATIONS:
        query = qa["query"]
        expected = qa["expected_files"]
        expected_chunks = {e for e in expected if "_chunk" in e}
        expected_fnames = {e.split("_chunk")[0] for e in expected_chunks}
        relevant = expected_chunks | expected_fnames

        # 查询改写（语义和 keyword 都用改写后的 query）
        rw_query = rewrite_query(query)
        if rw_query != query:
            print(f"  (改写: '{query[:40]}' → '{rw_query}')")

        # 使用改写后的 query 向量，没有则用原版
        qvec = query_vecs.get(rw_query) or query_vecs.get(query)
        if not qvec: continue

        # 向量检索
        semantic = search_pgvector(qvec, TOP_K, id2fn)

        # BM25
        keyword = search_keyword(rw_query, token, TOP_K, id2fn)
        # RRF 融合
        hybrid = rrf_fuse(semantic, keyword, TOP_K)

        # Reranker
        if args.reranker and hybrid:
            hybrid = call_reranker(query, hybrid, TOP_K)

        # 格式化为 key 列表
        def to_keys(items):
            return [f"{it['filename']}_chunk{it['chunk_index']}" for it in items]

        for mode, items in [("semantic", semantic), ("keyword", keyword), ("hybrid", hybrid)]:
            keys = to_keys(items)
            print(f"\nQuery: {query[:40]}")
            print(f"Expected: {expected_chunks}")
            print(f"  [{mode:8}] top={len(keys)}")
            for i, k in enumerate(keys[:10]):
                flag = " ← ✅" if k in relevant else ""
                print(f"    #{i+1} {k}{flag}")
            print(f"    recall@3={recall_at_k(keys,relevant,3):.2f} recall@5={recall_at_k(keys,relevant,5):.2f} mrr={mrr(keys,relevant):.2f}")
            all_results.append({"query":query,"mode":mode,"keys":keys,"relevant":relevant})

    # 聚合
    print(f"\n{'='*60}")
    print(f"  AGGREGATE METRICS (top_k={TOP_K}{'+reranker' if args.reranker else ''})")
    print(f"{'='*60}")
    for mode in ["semantic","keyword","hybrid"]:
        rs = [r for r in all_results if r["mode"]==mode]
        if not rs: continue
        print(f"\nMode: {mode}")
        for k in K_VALUES:
            rec = sum(recall_at_k(r["keys"],r["relevant"],k) for r in rs)/len(rs)
            pre = sum(precision_at_k(r["keys"],r["relevant"],k) for r in rs)/len(rs)
            ndc = sum(ndcg_at_k(r["keys"],r["relevant"],k) for r in rs)/len(rs)
            print(f"  recall@{k:2d}={rec:.3f} precision@{k:2d}={pre:.3f} ndcg@{k:2d}={ndc:.3f}")
        mrrs = sum(mrr(r["keys"],r["relevant"]) for r in rs)/len(rs)
        print(f"  mrr={mrrs:.3f}")

if __name__=="__main__":
    sys.exit(main())
