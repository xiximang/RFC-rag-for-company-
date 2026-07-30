请根据以下描述生成一张完整的企业级私有化多模态混合RAG检索系统的架构图。要求：清晰分层、标注组件名称和关键技术选型、画出数据/请求流向箭头。

## 整体架构层次（从上到下）

### 1. 应用层
- **Web 前端**（React 18 + TypeScript + Ant Design + Zustand）
  - 检索控制台（Search Console）：用户输入 query，流式展示 LLM 回答
  - 知识库管理（Knowledge Base）：上传文档、管理知识库
  - 评测工作台（Eval Workbench）：创建评测数据集、运行评测任务、查看指标
  - 权限管理（Permission Manager）：配置 L1-L5 权限、管理敏感关键词
  - 管理后台（System Admin / Operations Dashboard）

### 2. 网关层
- **Kong API Gateway**（DB-less 声明式配置）
  - 路由分发：`/api/*` → FastAPI 后端，`/*` → 前端静态资源
  - 限流：100 req/min（普通 API），1000 req/min（External API Key）
  - Prometheus 指标暴露

### 3. 服务层（FastAPI + SQLAlchemy 异步）
- **API 路由层**（20+ 模块）：search / chat / documents / auth / eval / permissions / knowledge_bases / feedback 等，每个模块独立文件
- **核心业务服务层**（关键服务用粗体标注）：
  - **RetrievalService**（混合检索引擎核心）
  - **GenerationService**（LLM 调用 + 流式关键词拦截）
  - **SecurityGateway**（三级 API 策略：L4→本地 / L3→脱敏 / L2→直接）
  - PermissionService（五级权限的存算）
  - EvaluationService（离线评测流水线）
  - KeywordService（AC 自动机关键词标注/拦截）
  - CompressionService（上下文按权限级别压缩）
- **文档摄入 Pipeline 层**（Factory 模式）：
  - DocumentIngestPipeline（PDF/DOCX/PPTX/TXT/HTML）
  - ExcelIngestPipeline（XLSX，含表格抽取）
  - ImageIngestPipeline（图片 OCR）
  - AudioIngestPipeline（Whisper 语音转文字）
  - VideoIngestPipeline（stub，仅标记存储）

### 4. 异步任务层（Celery + RabbitMQ）
- **Ingest Worker**（ingest 队列）：PDF 解析（pdfplumber）、OCR 回退（Tesseract）、Excel 解析（openpyxl）、文档分块、关键词标注
- **Embed Worker**（embed 队列）：调用 embedding API 向量化、写入 Milvus
- **Eval Worker**（eval 队列）：离线检索质量评测

### 5. 混合检索核心链路（在服务层 RetrievalService 内部）—— 这是架构核心，用放大/高亮区域或虚线框标出
- **双路并行召回**：
  - 向量检索：query → embedding API（text-embedding-3-small）→ **Milvus**（HNSW 索引，COSINE 距离）→ 带权限过滤表达式的 ANN 搜索
  - 关键词检索：query → **PostgreSQL tsvector**（zhparser 中文分词 + GIN 索引）→ BM25 风格全文搜索 + 三层降级（tsvector → jieba ILIKE → 原始 ILIKE）
- **RRF 融合**（Reciprocal Rank Fusion，k=60）：合并两路结果，按 RRF 公式重排
- **文档级去重**（per_doc_limit=2）：防止同一文档垄断结果
- **三层查询缓存**（CacheManager）：
  - 第1层：精确哈希（SHA256 query → query_cache 表，直接命中）
  - 第2层：语义向量（pgvector `<=>` 余弦相似度，阈值 0.92）
  - 第3层：关键词 Jaccard（query token 交集/并集，阈值 0.60）
- **在应用层加载 Chunk 完整信息后**：
  - **L3 字段级权限过滤**：check_field_permission() 逐行校验
  - **L5 关键词级别降级**：chunk_level > user_level → content 替换为占位符
- **Cross-Encoder Rerank**（qwen3-rerank）：对过滤后的候选结果做深度语义精排
- **SecurityGateway 策略决策** → **LLM 生成**（deepseek-v4-flash 或 MiniMax-M3）→ **AC 自动机流式拦截** → 返回前端
- **工程师反馈闭环**：工程师调整排序 → 写入 engineer_feedback 表 → 更新 query_cache

### 6. 权限体系（贯穿全链路）
- **L1 文件类型**：file_type_permissions 表 → 在检索前翻译成 Milvus `modality in [...]` / PG `WHERE modality IN` 条件
- **L2 文档级别**：document_permissions 表 → 检索前 `doc_id not in [...]` 过滤 + 检索后兜底检查
- **L3 字段/列级**：field_permissions 表 → 检索后应用层逐 chunk 检查 Excel 列 / Word 段落权限
- **L4 标签级别**：tag_permissions 表 → 检索前 `array_not_contains(tags, ...)` 过滤
- **L5 关键词敏感级别**：sensitive_keywords 表 → AC 自动机标注 chunk 敏感级别 → 检索时比较 user_level vs chunk_level，越级内容替换为占位符

### 7. 数据层
- **PostgreSQL 16**（主关系数据库）：
  - 业务表：users, knowledge_bases, documents, chunks, conversations, messages, engineer_feedback, query_cache
  - 权限表：file_type_permissions, document_permissions, field_permissions, tag_permissions
  - 评测表：evaluation_datasets, evaluation_tasks, evaluation_question_runs
  - 辅助表：tags, user_groups, audit_logs, search_history, sensitive_keywords, api_keys, comments, bookmarks, system_config
  - 扩展：pgvector（向量类型 + HNSW 索引，用于 query_cache 语义检索）

- **Milvus 2.4**（主向量数据库）：
  - rag_text_chunks 集合：chunk_id, doc_id, kb_id, modality, tags, max_keyword_level, embedding(1024d)，HNSW 索引
  - rag_image_frames 集合：chunk_id, image_url, embedding(512d)

- **MinIO**（S3 兼容对象存储）：
  - bucket: rag-documents
  - 存储所有上传的原始文件（PDF/DOCX/XLSX/PPTX/图片等）
  - 文件生命周期：上传 → MinIO → ingest worker 下载到临时目录解析 → 解析后原始文件保留

- **Redis**（缓存）：
  - 权限缓存（300s TTL）：user_doc_permission, user_tag_permission, user_security_level, user_file_types
  - 文档 ACL 版本号（86400s TTL）：doc_acl_version
  - 容错降级：Redis 不可用时自动降级到查询 PostgreSQL

- **RabbitMQ**（Celery 消息队列）：
  - ingest 队列：文档解析任务
  - embed 队列：向量化任务

### 8. 基础设施层
- Docker 容器化（docker-compose.yml）
- Prometheus + Grafana（监控，profile: monitoring）
- 自定义 Prometheus 指标：rag_api_request_duration_seconds（API 延迟分布）、rag_retrieval_duration_seconds（检索耗时 per mode）、rag_generation_duration_seconds（LLM 生成耗时 per model）、rag_rerank_total / rag_zero_result_total / rag_top_doc_concentration（BadCase 监测）

## 数据流向（请用箭头标注）

### 写入流（文档上传 → 检索就绪）：
用户上传文件 → API 格式校验 → 创建 Document 记录（PG, status=pending）→ 上传到 MinIO → Celery 入队 → Ingest Worker：从 MinIO 下载 → Pipeline 解析（根据文件类型选择）→ 文本清洗 → 智能分块 → AC 自动机关键词标注（max_keyword_level/tags）→ Chunk 写入 PostgreSQL（含 content_tsv 全文索引）→ 入队 Embed Worker → Embed Worker：调 embedding API → 向量写入 Milvus → Document status=indexed

### 查询流（用户提问 → 看到回答）：
用户在浏览器输入 query → React 发 POST /api/v1/chat/stream → Kong 路由 → FastAPI → 三层缓存命中检查（哈希 → 语义 → Jaccard，命中直接返回缓存 answer 跳过全部检索和 LLM）→ 未命中 → 权限画像（user_level / denied_docs / denied_tags / allowed_types）→ 双路并行检索（Milvus ANN + expr 权限过滤 → chunk_id 候选 || PostgreSQL BM25 tsquery + WHERE 权限过滤 → chunk_id 候选）→ RRF 融合 → 文档级去重 → 从 PG 加载 Chunk 完整信息（content）→ L3 字段级过滤 → L5 关键词级别降级（越级 content 替换为占位符）→ Cross-Encoder Rerank → SecurityGateway 三级策略（L4→本地 / L3→脱敏 / L2→直接）→ LLM 流式生成 → AC 自动机实时拦截敏感内容 → SSE 流式返回前端 → 前端逐 token 渲染

## 布局要求
- 从上到下的分层布局
- 混合检索核心链路区域用虚线框或不同底色高亮，标注"CORE: Hybrid Retrieval Engine"
- 权限体系用侧边条或贯穿线标注，表示贯穿检索全流程
- 数据流向箭头用不同颜色区分：写入流（蓝色）、查询流（红色/橙色）
- 在检索核心区域标注关键指标：Top-5召回率92.3%、Top-1准确率89.5%
