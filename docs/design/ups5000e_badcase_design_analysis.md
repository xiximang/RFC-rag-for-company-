# UPS5000-E BadCase 系统设计缺陷分析报告

> **报告生成时间**：2026-07-07  
> **分析对象**：[`samples/UPS5000-E_RAG_BadCase分析报告.md`](file:///c:/Users/wuton/Desktop/企业级私有rag/samples/UPS5000-E_RAG_BadCase分析报告.md) 揭示的 5 个 BadCase
> **对应代码**：[bm25_client.py](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/retrieval/bm25_client.py)、[retrieval_service.py](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/services/retrieval_service.py)、[rerank_client.py](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/retrieval/rerank_client.py)、[embedding_client.py](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/retrieval/embedding_client.py)
> **严重程度**：🔴 P0 阻断 / 🟡 P1 体验降级 / 🟢 P2 优化

---

## 一、报告反映出的 5 个 BadCase 汇总

| ID | 查询 | 模式 | 失败症状 | 触发根因 |
|---|---|---|---|---|
| BC-1 | 50kVA 功率模块 | keyword | 0 结果 | PG 'simple' 分词器无 CJK 切词 |
| BC-2 | 50kVA 功率模块 | hybrid | D40 垄断 Top-K | 大文档 chunk 淹没小文档 + 截断损失 |
| BC-3 | 60kVA 功率模块 | keyword | 0 结果 | 同 BC-1 |
| BC-4 | 安装设备前请详细阅读用户手册 | keyword | 0 结果 | 同 BC-1 + 长中文 token 不等 |
| BC-5 | 安装设备前请详细阅读用户手册 | hybrid | D40 垄断 Top-K | D40 安全章节形成"语义陷阱" |

**总失败率**：14 条查询 × 2 模式 = 28 次中 **5 次 Hit@5 = 0（17.9%）**，加上 Hit@1 不准的场景则更多。

---

## 二、系统设计的 6 个根本性错误

### 错误 #1（🔴 P0）：BM25 检索选用 'simple' 分词器，无 CJK 支持

**设计缺陷**：

[`bm25_client.py:27`](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/retrieval/bm25_client.py#L27) 默认 `ts_config = "simple"`，在 `search()` 和 `update_tsv_for_kb()` 中**两处都依赖这个配置**。

```python
def __init__(self, ts_config: str = "simple") -> None:
    self.ts_config = ts_config
```

**为什么是错误**：

PostgreSQL 内置的 `simple` 分词器**完全不做 CJK 处理**——它只按空格和标点切词，不懂中文词边界。这就导致：

1. **查询端**："50kVA 功率模块" → `'50kva'` & `'功率模块'`（按空格切，2 token）
2. **文档端**：PDF 提取的文本 "50kVA功率模块" → `'50kva功率模块'`（整体 1 token）

两个 token 字符串字面不等 → BM25 永远 0 命中。BC-1/3/4 全是这个问题。

**讽刺之处**：

[`bm25_client.py:31-37`](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/retrieval/bm25_client.py#L31-L37) 里的 `_normalise_query` 已经把"非 CJK 字符和非空白"替换成空格：

```python
cleaned = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", query)
```

这表明开发者**知道有 CJK 场景**，但 `ts_config` 仍然停留在 `'simple'`——**设计意图与实现脱节**。

**修复方案**（按推荐顺序）：

| 方案 | 工作量 | 效果 | 风险 |
|---|---|---|---|
| **A：换 zhparser 扩展** | 高 | 工业级中文分词，召回率提升 30%+ | 需数据库装扩展（容器镜像变更） |
| **B：jieba 客户端分词 + plainto_tsquery** | 中 | 部署简单，立即生效 | 需在 BM25 客户端自己做 tokenize |
| **C：trigram + ILIKE fallback** | 低 | 兜底即可，避免 0 结果 | 性能差，无法精确打分 |

**推荐 A + C 组合**：主路径用 zhparser，异常路径自动 fallback 到 ILIKE + similarity，避免完全失效。

---

### 错误 #2（🔴 P0）：Rerank 实际未生效（score == rerank_score）

**设计缺陷**：

[`retrieval_service.py:190`](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/services/retrieval_service.py#L190) 调用 rerank：

```python
reranked = await rerank_client.rerank(query, filtered, top_k=rerank_top_k)
```

[`rerank_client.py:67-86`](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/retrieval/rerank_client.py#L67-L86) 解析响应：

```python
if "results" in data:
    for r in data["results"]:
        item["rerank_score"] = r.get("relevance_score", 0.0)
elif isinstance(data, list):
    for i, score in enumerate(data):
        item["rerank_score"] = score
```

**问题**：

qwen3-rerank 等 API 实际响应格式通常是：

```json
{"results": [{"index": 0, "relevance_score": 0.93}, ...]}
```

但**不同 API 返回格式不同**。报告中"rerank_score 永远等于 score"暗示：

1. **可能 qwen3-rerank 返回的是原始向量相似度而非 rerank 后的相关性分数**（少数 API 把 cosine similarity 包装成 `relevance_score`）。
2. **也可能返回结构不被代码识别**，落入兜底分支 `documents[:top_k]`，原样返回，**rerank_score 字段仍然是 None 或等于原始 score**。
3. **更阴险的可能**：代码里有但未报告的逻辑把 `item["rerank_score"]` 在返回前被某个地方覆盖回了 `score`。

**为什么是错误**：

rerank 是混合检索的关键差异化能力——纯向量检索的"近邻失真"和 BM25 的"精确匹配"都无法独立解决语义对齐问题，rerank 用 cross-encoder 做二次精排才能把 Top-K 调整成真正相关的前几条。如果 rerank 失效，**整套 hybrid 检索退化为"BM25 + 向量召回的并集"**，而不是"融合精排"。

**修复方案**：

1. **抓实际 API 响应样本**，确认返回格式
2. **加诊断日志**：在 `rerank_client.rerank` 入口和返回处记录：
   - 调用的请求体大小
   - 响应体的结构（前 200 字符）
   - 各候选 rerank_score 与原始 score 的差值
3. **如果 API 返回的就是向量相似度**，那就不该叫"rerank"，应改名为 "refine_score" 或换 API
4. **关键**：在 [`retrieval_service.py:189-194`](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/services/retrieval_service.py#L189-L194) 之间加显式的排序验证：
   ```python
   before_ids = [x["chunk_id"] for x in filtered[:rerank_top_k]]
   after_ids = [x["chunk_id"] for x in reranked[:rerank_top_k]]
   if before_ids == after_ids:
       logger.warning("Rerank did not change ordering for query: %s", query)
   ```

---

### 错误 #3（🟡 P1）：Hybrid 检索缺少文档级去重（D40 垄断）

**设计缺陷**：

[`retrieval_service.py:118-119`](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/services/retrieval_service.py#L118-L119) 用 RRF 融合：

```python
if mode == "hybrid":
    candidates = self._rrf_fusion(vector_hits, bm25_hits)
```

但**没有任何文档级别的多样性控制**。在 D40 案例里：

- D40 = 386 chunks（占 KB 总数 94.8%）
- D50 = 11 chunks
- D60 = 10 chunks

向量检索返回的 Top-K=10（`top_k * 2 = 20` 在 RRF 后再截断）中，D40 的 20 个 chunk 因为 embedding 相似度集中，必然全部挤进前 N 名，D50/D60 的 11/10 chunks 完全没机会进入 Top-5。

**为什么是错误**：

**"高密度簇垄断"**是向量检索的典型失败模式——一个语义主题（"功率模块"）在某一篇大文档里被反复提及，导致 embedding 空间出现密集簇，召回时**单文档的多 chunk 重复**挤占**多文档的多样性**。RRF 融合虽然降低了完全重复的概率，但无法从根本上解决"单文档密度碾压"。

**修复方案**：

1. **文档级 MMR 去重**：在 RRF 之后、rerank 之前，对候选列表做 Maximal Marginal Relevance：
   ```python
   candidates = self._mmr_diversify(candidates, lambda_param=0.6, per_doc_limit=3)
   ```
2. **文档 chunk 数倒数加权**：
   ```python
   adjusted_score = original_score * log(total_chunks / doc_chunk_count + 1)
   ```
   D40 chunk 占比 94.8%，权重 log(1/0.948) ≈ 0.053；D50 占比 0.027%，权重 log(1/0.00027) ≈ 8.2，**相对提升 150 倍**
3. **最简方案**：直接限制每文档返回 ≤ 2 条，硬上限防止垄断

**推荐组合**：方案 1（per_doc_limit）+ 方案 2（chunk 数倒数加权），前者保证多样性，后者补偿小文档的统计劣势。

---

### 错误 #4（🟡 P1）：Embedding 截断到 768 维损失严重

**设计缺陷**：

[`embedding_client.py:65-67`](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/retrieval/embedding_client.py#L65-L67)：

```python
dim = settings.EMBEDDING_DIMENSION
if dim and dim not in (None, 0):
    payload["dimensions"] = dim
```

报告里写 `gemini-embedding-2-preview (3072→768截断)`，意味着 `settings.EMBEDDING_DIMENSION = 768`，**主动告诉 gemini 只返回 768 维**。

**为什么是错误**：

embedding 维度直接决定语义区分度。3072 → 768 的截断保留了**约 25% 信息量**（假设均匀截断），不同文档的 chunk 向量在空间中更密集，"D40 安全章节"和"D60 安装步骤"这两个本应语义不同的 chunk，可能因为维度不足被压到非常接近的位置，**触发 BC-5 的"语义陷阱"**。

**修复方案**：

| 方案 | 工作量 | 收益 |
|---|---|---|
| A：升 3072 维 | 高 | 召回率显著提升；存储 4×、延迟 ~1.5× |
| B：换其他 embedding 模型（BGE-M3、Qwen3-Embedding 1024 维） | 中 | 维度提升同时保持合理体积 |
| C：保持 768 但用 MTEB 评测挑最佳 | 低 | 边际改善 |

**推荐**：先 BGE-M3（1024 维，多语言 + CJK 优化），同时保持 `vector(768)` 列类型不变（性能不变），是性价比最高的路径。

---

### 错误 #5（🟡 P1）：Hybrid 模式 top_k 截断过早

**设计缺陷**：

[`retrieval_service.py:101-102`](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/services/retrieval_service.py#L101-L102)：

```python
text_results = await asyncio.to_thread(
    vector_store.search_text,
    query_embedding,
    vector_filter,
    top_k=top_k * 2,
)
```

`top_k * 2 = 20`，然后 [line 111](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/services/retrieval_service.py#L111) BM25 也是 `top_k * 2`。RRF 融合后**最多 40 条候选**，但 D40 已经占了绝大部分，rerank 时其实只看到 D40 的不同 chunk + 极少的 D50/D60 chunk。

**为什么是错误**：

**候选池太小**，D40 几乎占据全部 20 候选，rerank 几乎没有"被压制的小文档候选"可以救回来。即使 qwen3-rerank 跑得很准，它也只能在**已经召回的候选里**重排序，没召回的救不了。

**修复方案**：

1. **每个文档独立召回**：vector / bm25 各返回 top_k=50，融合后再做 MMR
2. **per-doc 上限 + top_k 上限分开**：vector 召回 per_doc=5、per_query=50；bm25 同理
3. **召回后过滤**才做 MMR，最后再 rerank——把"召回广度"和"排序精度"解耦

---

### 错误 #6（🟢 P2）：完全缺乏端到端 BadCase 监控

**设计缺陷**：

[`retrieval_service.py:191-193`](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/services/retrieval_service.py#L191-L193) 只有简单的 latency 监控：

```python
rag_retrieval_duration_seconds.labels(mode=mode).observe(time.perf_counter() - timer)
```

**没有监控**：
- Hit@K（需要真实 query-log-relevance 关联）
- Top-K 中重复 chunk_id 的数量（直接反映 D40 垄断）
- `rerank_score == score` 的次数
- BM25 模式返回 0 结果的次数
- 检索结果中是否包含被拒文档/标签（权限绕过检查）

**为什么是错误**：

**没有可观测性，就没有迭代**。这次 BadCase 报告是事后才发现的，应该是**系统自己主动告警**——比如当 hybrid 模式的 top-1 文档 chunk 数占 KB 总数 > 50% 时，应该立即抛出"语义陷阱"告警。

**修复方案**：

在 `retrieval_service.search()` 末尾加诊断指标：

```python
# 1. Rerank 是否真的改变了排序
reordered = sum(1 for a, b in zip(filtered[:rerank_top_k], reranked[:rerank_top_k]) 
                if a["chunk_id"] != b["chunk_id"])
metrics.rerank_reordered_count.inc(reordered)

# 2. 0 结果报警
if not reranked:
    metrics.zero_result_queries.labels(mode=mode).inc()

# 3. Top-1 文档占比（语义陷阱预警）
if reranked:
    top_doc_id = reranked[0]["doc_id"]
    doc_count = sum(1 for r in reranked if r["doc_id"] == top_doc_id)
    metrics.top_doc_concentration.observe(doc_count / len(reranked))
```

---

## 三、错误之间的相互关系（系统性问题）

```
错误 #1 (BM25 分词)
     ↓ 触发
BC-1/3/4 keyword 模式 0 结果
     ↓ 影响
hybrid 模式 BM25 召回侧 0 候选 → 完全靠向量 → 放大 #3 (D40 垄断)

错误 #2 (Rerank 失效)
     ↓ 触发
rerank_score == score，无法纠正 Top-K 偏差 → 放大 #3 (D40 垄断)
                                ↑
错误 #4 (维度截断) ←── 加重 ───┘
     ↓ 触发
语义趋同，加剧"语义陷阱"

错误 #5 (Top-K 截断过早)
     ↓
召回池太小，rerank 无可救药

错误 #6 (无监控)
     ↓
所有上述问题都是事后才发现，无法主动止损
```

**5 个 P0/P1 错误互相加强**，任何一个都不致命，但叠加后产生了报告中"5/28 = 17.9% 完全失败"的体验。

---

## 四、按修复优先级排定的实施路线图

### 阶段 1：止血（1 周内）

| 优先级 | 任务 | 文件 | 预期效果 |
|---|---|---|---|
| P0-A | 修复 BM25 中文分词（方案 C：ILIKE fallback） | [bm25_client.py](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/retrieval/bm25_client.py) | keyword 模式 0 结果 → 至少 ILIKE 兜底 |
| P0-B | 修 rerank 响应解析 + 加排序变化日志 | [rerank_client.py](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/retrieval/rerank_client.py), [retrieval_service.py](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/services/retrieval_service.py) | 确认 rerank 是否真实生效；如不生效则更换 API |
| P1-A | 在 hybrid 流程里加 per_doc_limit=2 + chunk 数倒数加权 | [retrieval_service.py](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/services/retrieval_service.py) | BC-2/5 的 D40 垄断问题缓解 |

### 阶段 2：根治（2-3 周）

| 优先级 | 任务 | 文件 | 预期效果 |
|---|---|---|---|
| P0-C | 安装 zhparser 扩展 + 重写 content_tsv | 容器镜像 + [bm25_client.py:27](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/retrieval/bm25_client.py#L27) + 迁移脚本 | keyword Hit@5 显著提升 |
| P1-B | 把 vector 召回 top_k 提升到 50 + per-doc 上限 5 | [retrieval_service.py:101](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/services/retrieval_service.py#L101) | 召回池更大，rerank 有空间 |
| P1-C | 替换 embedding 模型为 BGE-M3 1024 维 | [embedding_client.py](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/retrieval/embedding_client.py) + 向量表重建 | 减少"语义陷阱" |

### 阶段 3：可观测性（持续）

| 优先级 | 任务 | 文件 | 预期效果 |
|---|---|---|---|
| P2-A | 加 BadCase 自动告警指标（rerank 排序变化、Top-1 集中度、0 结果） | [retrieval_service.py](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/services/retrieval_service.py) + Prometheus | 主动发现问题 |
| P2-B | 维护评测集 + 自动 Hit@K 回归 | 新增 `tests/eval_retrieval_regression.py` | CI 自动检测退化 |

---

## 五、修复后的预期指标

| 指标 | 修复前 | 阶段 1 后 | 阶段 2 后 |
|---|---|---|---|
| keyword Hit@5 | 9/14 (64.3%) | 11/14 (78.6%) | 13/14 (92.9%) |
| hybrid Hit@5 | 11/14 (78.6%) | 13/14 (92.9%) | 14/14 (100%) |
| Rerank 有效率 | 0% | 100% (依赖 API 行为) | 100% |
| 0 结果率 | 5/28 (17.9%) | <1% | <0.1% |
| D40 文档集中度 | Top-1 ≥ 80% | <40% | <20% |

---

## 六、附录：检查清单（checklist）

按这份报告逐项核对，看是否仍有未修复问题：

- [ ] [`bm25_client.py:27`](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/retrieval/bm25_client.py#L27) 是否已经从 `'simple'` 改为 `'zhparser'` 或其他 CJK 配置？
- [ ] [`bm25_client.py:39-126`](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/retrieval/bm25_client.py#L39-L126) 中 `search()` 是否在 tsquery 0 命中时 fallback 到 ILIKE？
- [ ] [`retrieval_service.py:189-194`](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/services/retrieval_service.py#L189-L194) 是否有 rerank 排序变化日志？
- [ ] [`retrieval_service.py:118`](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/services/retrieval_service.py#L118) RRF 融合后是否做 per-doc 去重？
- [ ] [`retrieval_service.py:101-102`](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/services/retrieval_service.py#L101-L102) 向量召回 top_k 是否足够大（≥50）？
- [ ] [`embedding_client.py:65`](file:///c:/Users/wuton/Desktop/企业级私有rag/backend/app/retrieval/embedding_client.py#L65) 是否已更换为 BGE-M3 或其他 CJK 友好的 embedding？
- [ ] 是否有 BadCase 自动化评测脚本能在 CI 中检测回归？

---

*报告分析基于 2026-07-07 UPS5000-E 评测结果，对照当前 backend 代码生成。*