# UPS5000-E RAG 知识库 — BadCase 详细分析报告

**生成时间**：2026-07-07 11:09  
**模型**：gemini-embedding-2-preview (3072→768截断) + qwen3-rerank  
**知识库**：UPS5000-E PDF测试 (ID: `5dee1bb7-1cb1-44b5-9907-55be0ed92524`)  
**评测文档**：3 份 PDF（D40/D50/D60）  

---

## 一、BadCase 概览

在 14 条查询 × 2 模式 = 28 次检索中，共有 **5 次 Hit@5 = 0** 的失败记录，全部集中在 keyword 模式和 hybrid 模式的中文查询场景。

| BadCase ID | 查询 | 模式 | 期望文档 | 实际返回 | 失败类型 |
| --- | --- | --- | --- | --- | --- |
| BC-1 | 50kVA 功率模块 | `keyword` | D50 | 0 结果 | 全文检索零命中 |
| BC-2 | 50kVA 功率模块 | `hybrid` | D50 | D40, D40, D60 | 语义偏移+D40淹没 |
| BC-3 | 60kVA 功率模块 | `keyword` | D60 | 0 结果 | 全文检索零命中 |
| BC-4 | 安装设备前请详细阅读用户手册 | `keyword` | D50, D60 | 0 结果 | 全文检索零命中 |
| BC-5 | 安装设备前请详细阅读用户手册 | `hybrid` | D50, D60 | D40, D40, D40 | 语义偏移+D40垄断 |

> **备注**：Q12「60kVA 功率模块」hybrid 模式返回 D40, D60, D40，D60 在第 2 位命中，Hit@5 = 1，不算 BadCase，但 Hit@1 = 0 仍需关注。

---

## 二、根因分析

### 2.1 根因 #1：PostgreSQL 'simple' 分词器无法正确切分中英混合文本

这是 **BC-1/BC-3/BC-4（keyword 模式全部 0 结果）** 的根本原因。

系统 keyword 检索使用 PostgreSQL 的 `plainto_tsquery('simple', query)` 匹配 `to_tsvector('simple', content)`。**'simple' 分词器仅按空格和标点切词，不理解中文词边界**。当中英文连续出现时（如"50kVA功率模块"），整个字符串被视为一个 token，无法被拆分匹配。

**查询端分词（用户输入 "50kVA 功率模块"）：**

```
plainto_tsquery('simple', '50kVA 功率模块')
→ '50kva' & '功率模块'
↑ 空格分隔 → 2 个独立 token
```

**文档端分词（PDF文本 "50kVA功率模块"）：**

```
to_tsvector('simple', '快速指南 (50kVA功率模块)')
→ '50kva功率模块':2 '快速指南':1
↑ 无空格 → 整体作为 1 个 token
```

**匹配结果**：查询 token `'50kva'` 无法匹配文档 token `'50kva功率模块'`，`'功率模块'` 也无法匹配 → **全文检索返回 0 行**。

同理，Q13 的查询 "安装设备前请详细阅读用户手册" 被分词为 `'安装设备前请详细阅读用户手册'`（单个 token），而文档中的文本是 "安装设备前请详细阅读用户手册**了解产品信息及安全注意事项**"，被分词为另一个更长的 token，两者不等 → 无法匹配。

> **根因确认**：数据库直接验证 — `SELECT ... WHERE to_tsvector('simple', content) @@ plainto_tsquery('simple', '50kVA 功率模块')` 返回 **0 行**。'simple' 配置不具备 CJK 分词能力。

---

### 2.2 根因 #2：D40 文档 chunk 数量过大导致 D50/D60 被淹没

这是 **BC-2/BC-5（hybrid 模式语义偏移）** 的主要原因。

| 文档 | 简称 | Chunk 数 | 含"功率模块"的 chunk | 含"安装设备前"的 chunk | 占比 |
| --- | --- | --- | --- | --- | --- |
| D40 | 40kVA用户手册 | **386** | 242 | 0 | **62.7%** |
| D50 | 50kVA快速指南 | 11 | 2 | 1 | 18.2% |
| D60 | 60kVA快速指南 | 10 | 2 | 2 | 20.0% |

D40（386 chunks）占总 chunk 数的 **94.8%**。在 hybrid 向量检索中，D40 的大量"功率模块"相关 chunk（242个）在语义空间中形成密集区域，将 D50 和 D60 的少数 chunk（各仅2个）挤出 Top-K。Rerank 阶段虽然对 Top-K 重新排序，但无法召回已经在向量检索阶段被淘汰的 chunk。

> **量化分析**：对于 Q11 "50kVA 功率模块" hybrid 检索：
> - D40 Top-1 chunk score = 0.843，内容是"40kVA功率模块"的操作指导
> - D50 目标 chunk（含"50kVA功率模块"标题）score 未进 Top-5
> - Score 差距约 0.08+，被 D40 的 242 个相关 chunk 淹没

---

### 2.3 根因 #3：Rerank 未改变排序（score = rerank_score）

在所有 BadCase 的 hybrid 返回结果中，`score` 与 `rerank_score` 完全一致：

| BadCase | 位置 | 返回文档 | score | rerank_score | 是否改变 |
| --- | --- | --- | --- | --- | --- |
| BC-2 (Q11) | Top-1 | D40 | 0.843 | 0.843 | ❌ 否 |
| BC-2 (Q11) | Top-2 | D40 | 0.778 | 0.778 | ❌ 否 |
| BC-2 (Q11) | Top-3 | D60 | 0.766 | 0.766 | ❌ 否 |
| BC-5 (Q13) | Top-1 | D40 | 0.731 | 0.731 | ❌ 否 |
| BC-5 (Q13) | Top-2 | D40 | 0.595 | 0.595 | ❌ 否 |
| BC-5 (Q13) | Top-3 | D40 | 0.589 | 0.589 | ❌ 否 |

这表明 qwen3-rerank 的返回值可能被当作 pass-through 处理，或 rerank API 返回的 relevance_score 与原始 score 数值一致，未能起到重排序作用。需要检查 `retrieval_service.py` 中 rerank 的结果合并逻辑。

---

## 三、逐案详细分析

### BC-1：Q11「50kVA 功率模块」keyword 模式 — 零结果

| 项目 | 详情 |
| --- | --- |
| 查询 | `50kVA 功率模块` |
| 期望文档 | D50（50kVA快速指南） |
| 实际返回 | **0 条结果** |
| 失败类型 | 全文检索零命中（token 不匹配） |

**数据库验证：**

```sql
-- 查询分词
plainto_tsquery('simple', '50kVA 功率模块')
→ '50kva' & '功率模块'    -- 2 个 token

-- D50 目标 chunk 分词
to_tsvector('simple', '快速指南 (50kVA功率模块)')
→ '50kva功率模块':2 '快速指南':1    -- "50kVA功率模块" 作为 1 个 token

-- 全文匹配
WHERE to_tsvector('simple', content) @@ plainto_tsquery('simple', '50kVA 功率模块')
→ 0 行  -- '50kva' ≠ '50kva功率模块'，匹配失败
```

**D50 目标 chunk 内容（应被检索到）：**

```
[TABLE]
UPS型号 | 重量 | 尺寸（高×宽×深）
UPS5000-E-400K-SM | 670kg | 2000mm×1200mm×850mm
UPS5000-E-500K-FM | 830kg | ...
[/TABLE]
UPS5000-E-(350kVA-500kVA)
快速指南 (50kVA功率模块)
文档版本：12 部件编码：31507657 发布日期：2026-05-13
1 产品简介 ...
```

> **根因**：PDF 提取的文本中 "50kVA" 与 "功率模块" 之间无空格（"50kVA功率模块"），'simple' 分词器将其作为单个 token。查询中 "50kVA" 与 "功率模块" 之间有空格，被分为 2 个 token。token 不等 → 零命中。

---

### BC-2：Q11「50kVA 功率模块」hybrid 模式 — D50 未进 Top-5

| 项目 | 详情 |
| --- | --- |
| 查询 | `50kVA 功率模块` |
| 期望文档 | D50（50kVA快速指南） |
| 实际返回 | D40, D40, D60（仅 3 条，D50 未出现） |
| 失败类型 | 语义偏移 + D40 chunk 数量淹没 |

**返回结果详情：**

| 排名 | 文档 | score | rerank_score | 内容摘要 |
| --- | --- | --- | --- | --- |
| 1 | D40 | 0.843 | 0.843 | 360kVA-480kVA) 用户手册 (40kVA功率模块) 5 操作指导... 电池供电状态... 油机启动... |
| 2 | D40 | 0.778 | 0.778 | 模块容量 \| 机架内基本模块数... 工作模式... BSC模式... |
| 3 | D60 | 0.766 | 0.766 | [TABLE] 型号 \| UPS5000-E-400K-FMS... 快速指南(60kVA功率模块)... |

**分析：**

- **Top-1 是 D40 的操作指导章节**，内容关于"电池供电""油机启动"，与"50kVA 功率模块"的查询意图（寻找 50kVA 功率模块文档）完全无关，但 embedding 相似度高达 0.843
- **D40 有 242 个包含"功率模块"的 chunk**，在向量空间中形成密集区域，主导了 Top-K 排序
- **D50 仅 2 个含"功率模块"的 chunk**，其 embedding 与查询的相似度低于 D40 的 chunk，被挤出 Top-5
- **Rerank 未改变顺序**（score = rerank_score），未能纠正向量检索的偏差
- **3072→768 维截断损失**：gemini 原生 3072 维截断为 768 维后，语义区分能力下降，可能导致不同文档的 chunk 向量趋同

---

### BC-3：Q12「60kVA 功率模块」keyword 模式 — 零结果

| 项目 | 详情 |
| --- | --- |
| 查询 | `60kVA 功率模块` |
| 期望文档 | D60（60kVA快速指南） |
| 实际返回 | **0 条结果** |
| 失败类型 | 全文检索零命中（与 BC-1 同理） |

**数据库验证：**

```sql
to_tsvector('simple', '快速指南(60kVA功率模块)')
→ '60kva功率模块':N    -- 整体作为 1 个 token

plainto_tsquery('simple', '60kVA 功率模块')
→ '60kva' & '功率模块'  -- 2 个 token

匹配结果：0 行  -- token 不等
```

根因与 BC-1 完全一致：PDF 文本中 "60kVA功率模块" 无空格分隔，'simple' 分词器无法拆分。

---

### BC-4：Q13「安装设备前请详细阅读用户手册」keyword 模式 — 零结果

| 项目 | 详情 |
| --- | --- |
| 查询 | `安装设备前请详细阅读用户手册` |
| 期望文档 | D50, D60 |
| 实际返回 | **0 条结果** |
| 失败类型 | 全文检索零命中（长中文句 token 不等） |

**数据库验证：**

```sql
-- 查询分词
to_tsvector('simple', '安装设备前请详细阅读用户手册')
→ '安装设备前请详细阅读用户手册':1    -- 整句作为 1 个 token

-- D60 目标 chunk 分词（实际文本）
to_tsvector('simple', '1. 安装设备前请详细阅读用户手册了解产品信息及安全注意事项。')
→ '1':1 '安装设备前请详细阅读用户手册了解产品信息及安全注意事项':2
                                                  ↑ 比 query 多了"了解产品信息及安全注意事项"

-- 匹配结果
'安装设备前请详细阅读用户手册' ≠ '安装设备前请详细阅读用户手册了解产品信息及安全注意事项'
→ 0 行  -- token 不等
```

**D60 目标 chunk 内容（应被检索到）：**

```
×850mm
尺寸（高×宽×深）2000mm×1200mm×850mm
0mm
1. 安装设备前请详细阅读用户手册了解产品信息及安全注意事项。
2. 安装操作设备时，必须使用绝缘的工具。
3. UPS必须由本公司或本公司代理商认证的工程师进行安装、调试和维护...
UPS5000-E-400K-FMS UPS5000-E-500K-FMS
（1）功率模块 （2）监控模块 （3）配电模块盖板...
```

> **根因**：'simple' 分词器将连续中文字符串作为单个 token。查询中的"安装设备前请详细阅读用户手册"是完整 token，但文档中的文本在"用户手册"后面继续接了"了解产品信息及安全注意事项"，形成了一个更长的 token。两个 token 字符串不等，无法匹配。

---

### BC-5：Q13「安装设备前请详细阅读用户手册」hybrid 模式 — D50/D60 均未出现

| 项目 | 详情 |
| --- | --- |
| 查询 | `安装设备前请详细阅读用户手册` |
| 期望文档 | D50, D60 |
| 实际返回 | D40, D40, D40（全部来自 D40 用户手册） |
| 失败类型 | 语义偏移 + D40 垄断 Top-K |

**返回结果详情：**

| 排名 | 文档 | score | rerank_score | 内容摘要 |
| --- | --- | --- | --- | --- |
| 1 | D40 | 0.731 | 0.731 | ...在运输、存储、安装、操作、使用或/和维护设备前，请先阅读本手册，严格按照手册内容操作... |
| 2 | D40 | 0.595 | 0.595 | ...不符合资格的人员进行设备安装和使用；未按产品及文档中的操作说明... |
| 3 | D40 | 0.589 | 0.589 | ...安装、操作和维护必须按照手册的步骤顺序来进行... |

**分析：**

- **D40 全部 3 条结果都与"安装"和"手册"相关**，但语义上更偏向"安全注意事项声明"而非 D60 中的具体安装步骤（"1. 安装设备前请详细阅读用户手册"）
- **D40 的安全声明 chunk（386 chunks 中的安全章节）在语义空间中覆盖面广**，与查询的 embedding 相似度高于 D60 的安装步骤 chunk
- **D60 的目标 chunk score 低于 0.589**，未进入 Top-3（hybrid 模式仅返回 3 条结果）
- **D50 的目标 chunk（含"安装设备前"）也未进入 Top-3**，被 D40 的安全章节淹没
- **Rerank 再次未改变顺序**（score = rerank_score），未能提升 D50/D60 的排名

> **关键洞察**：D40 的"安全注意事项"章节在语义上与"安装设备前请详细阅读用户手册"高度相关（都提到"安装""手册""操作"），形成了一个"语义陷阱"——embedding 模型认为安全声明比实际安装步骤更相关。这是 **文档内容分布不均导致的语义偏移**。

---

## 四、影响评估

| 影响维度 | 影响程度 | 说明 |
| --- | --- | --- |
| keyword 模式可用性 | 🔴 严重 | 所有含中英混合文本的查询（如 "50kVA 功率模块"）在 keyword 模式下返回 0 结果，功能完全失效 |
| hybrid 模式准确性 | 🟡 中等 | hybrid 模式能返回结果但存在语义偏移，D40（386 chunks）系统性淹没 D50/D60（各 10-11 chunks） |
| Rerank 有效性 | 🟡 待确认 | 所有 BadCase 中 rerank_score = score，rerank 未起到重排序作用 |
| embedding 截断损失 | 🟡 中等 | 3072→768 维截断可能降低不同文档 chunk 的语义区分度 |
| 用户体验 | 🔴 严重 | 中文用户在 keyword 模式搜索中文关键词时 0 结果，hybrid 模式返回错误文档 |

---

## 五、修复建议

### 5.1 P0 — 修复 keyword 中文分词（解决 BC-1/BC-3/BC-4）

**方案 A（推荐）：安装 zhparser 或 jieba PostgreSQL 扩展**

- 将 `ts_config` 从 `'simple'` 改为 `'zhparser'` 或使用 jieba 分词
- 修改 `bm25_client.py` 中的 `self.ts_config = "zhparser"`
- 重建 `content_tsv` 列：`UPDATE chunks SET content_tsv = to_tsvector('zhparser', content);`
- **预期效果**："50kVA功率模块" → `'50kva'` + `'功率'` + `'模块'`，可被查询匹配

**方案 B（快速兜底）：在 BM25 检索中增加 ILIKE 模糊匹配**

- 在 `bm25_client.py` 的 `search()` 方法中，当 tsvector 匹配为 0 时，fallback 到 `content ILIKE '%query%'`
- **优点**：无需安装扩展，即时生效
- **缺点**：性能差（全表扫描），无法排序

---

### 5.2 P1 — 修复 D40 chunk 淹没问题（解决 BC-2/BC-5）

**方案 A：文档级 MMR 去重**

- 在 hybrid 检索的 Top-K 结果中，限制每篇文档最多返回 N 条（如 2 条），保证文档多样性
- 修改 `retrieval_service.py` 中的 hybrid 合并逻辑

**方案 B：文档权重均衡**

- 根据文档 chunk 数量反比加权：D40（386 chunks）降低权重，D50/D60（10-11 chunks）提升权重
- 公式：`adjusted_score = original_score * log(total_chunks / doc_chunk_count + 1)`

---

### 5.3 P1 — 修复 Rerank 未生效问题

- 检查 `retrieval_service.py` 中 rerank 结果合并逻辑：确认 `rerank_score` 是否实际替换了原始 `score`
- 检查 qwen3-rerank API 返回格式：`relevance_score` 是否被正确解析
- 添加日志：记录 rerank 前后的 score 变化，验证 rerank 是否生效
- 可能需要修改 rerank score 的归一化逻辑（qwen3-rerank 返回的 score 范围可能与向量 score 不同）

---

### 5.4 P2 — Embedding 维度升级

- 当前 3072→768 截断损失约 75% 的维度信息
- 将 pgvector 列从 `vector(768)` 升级为 `vector(3072)`（需重建向量表 + HNSW 索引）
- 预期效果：提升语义区分度，减少 D40 chunk 的"语义陷阱"效应
- 代价：存储空间增加 4 倍，检索延迟增加

---

## 六、修复后验证计划

| 步骤 | 操作 | 验证标准 |
| --- | --- | --- |
| 1 | 安装 zhparser + 重建 content_tsv | BC-1/BC-3/BC-4 keyword 模式 Hit@5 > 0 |
| 2 | 添加文档级 MMR（每文档最多 2 条） | BC-2/BC-5 hybrid 模式 D50 或 D60 进入 Top-3 |
| 3 | 修复 rerank score 合并逻辑 | rerank_score ≠ score（至少 1 条结果排序变化） |
| 4 | （可选）升级 pgvector 至 3072 维 | hybrid Hit@5 ≥ 92.9%（13/14） |
| 5 | 重新运行 14 条评测 | keyword Hit@5 ≥ 85%，hybrid Hit@5 ≥ 92% |

---

## 附录：数据库验证证据汇总

### A1. Chunk 分布统计

```sql
SELECT c.doc_id, COUNT(*) as total_chunks,
       COUNT(CASE WHEN c.content ILIKE '%50kVA%' THEN 1 END) as has_50kva,
       COUNT(CASE WHEN c.content ILIKE '%60kVA%' THEN 1 END) as has_60kva,
       COUNT(CASE WHEN c.content ILIKE '%功率模块%' THEN 1 END) as has_power_module,
       COUNT(CASE WHEN c.content ILIKE '%安装设备前%' THEN 1 END) as has_install_notice
FROM chunks c
WHERE c.doc_id IN ('a93e8e88-f462-4b1c-9e66-45d315f9dadf',  -- D50
                   '08fd4d44-097b-4583-95dd-271a630f1f37',  -- D60
                   '034cbc59-6290-48ff-aa29-1ee64c3f4f9d') -- D40
GROUP BY c.doc_id ORDER BY c.doc_id;
```

| doc_id | total_chunks | has_50kva | has_60kva | has_power_module | has_install_notice |
| --- | --- | --- | --- | --- | --- |
| a93e8e88... (D50) | 11 | 2 | 0 | 2 | 1 |
| 08fd4d44... (D60) | 10 | 0 | 2 | 2 | 2 |
| 034cbc59... (D40) | 386 | 0 | 0 | 242 | 0 |

### A2. tsvector 分词验证

```sql
-- 查询文本分词
to_tsvector('simple', '快速指南 (50kVA功率模块)')
→ '50kva功率模块':2 '快速指南':1

-- 查询词分词
plainto_tsquery('simple', '50kVA 功率模块')
→ '50kva' & '功率模块'

-- 全文匹配
SELECT count(*) FROM chunks WHERE to_tsvector('simple', content) @@ plainto_tsquery('simple', '50kVA 功率模块');
→ 0
```

### A3. Rerank 验证

所有 hybrid 返回结果中 `rerank_score` 字段值与 `score` 字段值完全一致，表明 rerank 未改变排序。

---

*UPS5000-E RAG BadCase 详细分析报告 — 生成于 2026-07-07 11:09*
