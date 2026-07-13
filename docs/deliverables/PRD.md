# 企业级私有化多模态 RAG 系统 — 产品需求文档（PRD）

> 版本：v1.0  
> 更新日期：2026-07-04  
> 文档状态：ToB 交付版  
> 依据：docs/design/01-14、PROJECT_PLAN.md、gap_analysis.md

---

## 1. 文档说明

### 1.1 目的

本文档面向企业客户、交付团队与研发管理方，定义「企业级私有化多模态 RAG 系统」的产品定位、目标用户、核心功能与非功能需求，并明确 MVP 范围，作为需求评审、开发排期与验收的依据。

### 1.2 范围

- 覆盖知识库、检索、问答、权限、评测、安全、部署运维等核心模块。
- 不包含 P2 远期能力（知识图谱、IM 集成、Agentic RAG、多语言 UI、移动端适配）。

### 1.3 术语

| 术语 | 说明 |
|------|------|
| RAG | Retrieval-Augmented Generation，检索增强生成 |
| Chunk | 文档分块，用于向量化和检索的最小单元 |
| RBAC | 基于角色的访问控制 |
| ABAC | 基于属性的访问控制 |
| L0-L4 | 系统五级安全级别，L0 最低，L4 最高 |

---

## 2. 项目背景

企业在知识管理上面临以下痛点：

1. **知识分散**：制度、规范、产品资料、财务数据、培训视频等散落在邮件、网盘、IM、本地电脑中，检索困难。
2. **检索效率低**：传统关键词搜索无法理解语义，用户需要多次尝试才能定位信息。
3. **权限风险高**：通用 SaaS RAG 难以满足金融、政务、制造等行业对数据主权和细粒度权限的要求。
4. **多模态支持弱**：图片、视频、Excel 表格等非文本知识难以被统一检索和利用。
5. **答案不可信**：大模型生成内容可能出现"幻觉"，缺乏来源引用和合规拦截。

本项目基于 `docs/design/` 中的 15 份方案文档构建，目标是将设计转化为可运行的私有化 RAG 平台，优先完成 MVP 核心版（Phase 1），实现"数据不出域、权限可穿透、来源可追溯"。

---

## 3. 目标用户

| 用户角色 | 典型画像 | 核心诉求 |
|----------|----------|----------|
| 企业知识管理员（KB Admin） | 部门文档负责人、知识库运营者 | 方便地创建/维护知识库、管理文档生命周期、配置权限、监控使用效果 |
| 普通员工 / 业务用户 | 研发、销售、财务、人力等一线人员 | 通过自然语言快速找到准确答案，操作门槛低 |
| 系统管理员（Super Admin） | IT/运维/安全负责人 | 私有化部署、用户管理、模型配置、审计合规、稳定可观测 |
| 算法/评测工程师 | 负责效果优化的技术人员 | 可量化检索与生成效果，支持 A/B 对比和 Bad Case 分析 |

详细用户画像见 `personas.md`。

---

## 4. 核心功能需求

### 4.1 知识库管理

| 需求编号 | 需求描述 | 优先级 | 对应实现 |
|----------|----------|--------|----------|
| KB-001 | 支持创建、编辑、删除、列出知识库 | P0 | `backend/app/api/v1/knowledge_bases.py` |
| KB-002 | 支持为知识库配置分块策略、默认模态、Embedding 模型 | P0 | `backend/app/api/v1/knowledge_bases.py` |
| KB-003 | 支持查看知识库统计（文档数、分块数、状态分布） | P0 | `GET /knowledge-bases/{id}/stats` |
| KB-004 | 支持知识库公开/私有/部门可见范围配置 | P0 | 设计文档 04、权限服务 |
| KB-005 | 支持文档重新处理（reprocess） | P0 | `POST /documents/{doc_id}/reprocess` |

### 4.2 文档上传与摄取

| 需求编号 | 需求描述 | 优先级 | 对应实现 |
|----------|----------|--------|----------|
| DOC-001 | 支持 PDF、Word（DOC/DOCX）、TXT、Markdown 解析 | P0 | `backend/app/pipelines/document_pipeline.py` |
| DOC-002 | 支持 Excel（XLS/XLSX）、CSV 解析，保留表头/列/行结构 | P0 | `backend/app/pipelines/excel_pipeline.py` |
| DOC-003 | 支持图片（PNG/JPG/WebP）OCR 与 Vision 描述 | P0 | `backend/app/pipelines/image_pipeline.py` |
| DOC-004 | 支持视频（MP4/MOV/AVI）关键帧提取与时序索引 | P1 | `backend/app/pipelines/video_pipeline.py` |
| DOC-005 | 支持网页链接自动抓取与增量更新 | P1 | `backend/app/pipelines/link_pipeline.py` |
| DOC-006 | 支持音频（MP3/WAV/M4A）解析 | P2 | `backend/app/pipelines/audio_pipeline.py` |
| DOC-007 | 异步 Celery 任务队列处理，支持进度追踪 | P0 | RabbitMQ/Redis + 3 类 Worker |

### 4.3 统一检索

| 需求编号 | 需求描述 | 优先级 | 对应实现 |
|----------|----------|--------|----------|
| SEA-001 | 支持语义检索（Dense，Milvus/pgvector） | P0 | `backend/app/services/retrieval_service.py` |
| SEA-002 | 支持关键词检索（BM25/Sparse） | P0 | `backend/app/retrieval/bm25_client.py` |
| SEA-003 | 支持混合检索（hybrid）与 RRF 融合 | P0 | `backend/app/retrieval/fusion.py` |
| SEA-004 | 支持三种检索模式切换：`hybrid` / `semantic` / `keyword` | P0 | `backend/app/api/v1/search.py` |
| SEA-005 | 支持跨知识库、跨模态检索 | P0 | 多 Collection 联合检索 |
| SEA-006 | 支持搜索历史保存与查看 | P0 | `GET /search/history` |

### 4.4 问答生成

| 需求编号 | 需求描述 | 优先级 | 对应实现 |
|----------|----------|--------|----------|
| CHAT-001 | 基于检索上下文生成答案并引用来源 Chunk | P0 | `backend/app/api/v1/chat.py` |
| CHAT-002 | 支持多轮对话与会话历史管理 | P0 | `conversation_service.py` |
| CHAT-003 | 支持流式（SSE）与非流式问答 | P0 | `/chat`、`/chat/stream` |
| CHAT-004 | 支持答案点赞/点踩反馈 | P0 | `POST /chat/messages/{id}/feedback` |
| CHAT-005 | 答案引用支持页码、sheet、行范围、视频时间戳 | P1 | SourceItem 元数据 |

### 4.5 权限控制

| 需求编号 | 需求描述 | 优先级 | 对应实现 |
|----------|----------|--------|----------|
| PERM-001 | 五级权限穿透：文件类型 → 文档 → 字段/段落 → 标签 → 关键词 | P0 | 设计文档 04、权限服务 |
| PERM-002 | 支持 RBAC + ABAC 混合授权 | P0 | `permission_service.py` |
| PERM-003 | 支持用户组层级继承 | P0 | `backend/app/api/v1/groups.py` |
| PERM-004 | 支持字段级权限（Excel 列、Word 段落） | P0 | Chunk 元数据 + 字段过滤 |
| PERM-005 | 支持标签级权限控制 | P0 | 标签权限过滤器 |
| PERM-006 | 支持关键词级别敏感内容拦截 | P0 | `backend/app/api/v1/keywords.py` |
| PERM-007 | 权限计算结果 Redis 缓存，TTL 5 分钟 | P0 | `backend/app/core/cache.py` |

### 4.6 安全与敏感词

| 需求编号 | 需求描述 | 优先级 | 对应实现 |
|----------|----------|--------|----------|
| SEC-001 | 全局关键词配置与分级（L0-L4） | P0 | 设计文档 05 |
| SEC-002 | Chunk 入库时自动标注 max_keyword_level | P0 | `keyword_annotator.py` |
| SEC-003 | 检索与生成阶段越级内容拦截 | P0 | `security_gateway.py` |
| SEC-004 | 敏感信息检测（身份证、手机、邮箱、银行卡）与脱敏 | P0 | `sensitive_info_service.py` |
| SEC-005 | Prompt 注入检测与防护 | P1 | `security_gateway.py` + 回归测试 |
| SEC-006 | API 安全网关：L4 本地处理 / L3 脱敏 / L2 直接调用 | P0 | `backend/app/services/security_gateway.py` |

### 4.7 评测与反馈

| 需求编号 | 需求描述 | 优先级 | 对应实现 |
|----------|----------|--------|----------|
| EVAL-001 | 支持评测数据集创建、导入（JSON/Excel） | P0 | `backend/app/api/v1/eval.py` |
| EVAL-002 | 支持检索指标：Recall@K / Precision@K / MRR / NDCG@K / Hit Rate | P0 | `evaluation_service.py` |
| EVAL-003 | 支持生成指标：Relevance / Faithfulness / Completeness | P0 | LLM-as-Judge |
| EVAL-004 | 支持 A/B 对比测试 | P1 | 设计文档 12 |
| EVAL-005 | 支持 Bad Case 自动分类与趋势报告 | P1 | `BadCaseAnalyzer` |

### 4.8 模型配置

| 需求编号 | 需求描述 | 优先级 | 对应实现 |
|----------|----------|--------|----------|
| CFG-001 | 支持 Embedding / Re-rank / LLM 模型配置 | P0 | `backend/app/api/v1/config.py` |
| CFG-002 | 配置保存后即时生效，无需重启服务 | P0 | `runtime_config.py` |
| CFG-003 | 兼容 OpenAI 协议的外部模型服务接入 | P0 | 设计文档 14 |

### 4.9 用户与系统管理

| 需求编号 | 需求描述 | 优先级 | 对应实现 |
|----------|----------|--------|----------|
| USER-001 | 用户 CRUD、用户组 CRUD 与成员管理 | P0 | `users.py`、`groups.py` |
| USER-002 | JWT + OAuth2 Password 登录 | P0 | `auth.py` |
| USER-003 | API Key 生命周期管理与 scope 权限边界 | P0 | `external.py` + API Key 服务 |
| USER-004 | 审计日志：登录、上传、检索、权限变更 | P0 | `audit_logs` 模型 |
| USER-005 | 组件健康检查 `/health` | P0 | `backend/app/api/v1/health.py` |

---

## 5. 非功能需求

### 5.1 性能

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 检索 P99 延迟 | ≤ 2s | 混合检索含重排序 |
| 检索平均延迟 | ≤ 800ms | 向量检索 + 权限过滤 |
| 问答生成 P99 延迟 | ≤ 6.5s | 依赖外部 LLM |
| 并发用户 | ≥ 100 | 中小规模生产 |
| 文档处理 | < 10MB 文档 2 分钟内可检索 | Celery Worker 异步 |

### 5.2 可用性与可靠性

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 服务可用性 | ≥ 99.9%（生产 K8s） | 蓝绿部署 + HPA |
| 数据持久化 | PostgreSQL 主从 + Milvus/MinIO 多副本 | 设计文档 13 |
| 备份策略 | PostgreSQL 每日全量 + WAL 实时；Milvus 每周全量 | 设计文档 13 |
| 故障恢复 RTO | PostgreSQL < 1min；Milvus < 30s；Redis < 2min | 设计文档 13 |

### 5.3 安全性

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 权限零泄露 | 100% | 五级权限穿透逐级校验 |
| 敏感词拦截 | 按 L0-L4 级别生效 | 关键词服务 |
| DevSecOps | CI 集成 Bandit/Semgrep/pip-audit/Trivy/SBOM | `.github/workflows/ci-cd.yml` |
| Secret 管理 | 不在 Git 中提交 `.env`、密码、API Key | `.gitignore` 已配置 |

### 5.4 可观测性

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 监控覆盖 | Prometheus + Grafana 4 套 Dashboard | API / 检索 / 模型 / 总览 |
| 告警规则 | 7 类核心告警 | P99 延迟、错误率、队列长度、磁盘、服务存活等 |
| 日志规范 | JSON 结构化日志 | 含 request_id、user_id、action |

### 5.5 部署与扩展

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 部署形态 | Docker Compose（开发/POC）+ Kubernetes Helm（生产） | `docker-compose.yml`、`k8s/helm` |
| 轻量模式 | 5 容器即可运行 | `docker-compose.lightweight.yml` |
| 资源要求 | 开发 8 核/16GB；生产 16 核/32GB 起步 | 资源估算文档 |

### 5.6 兼容性

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 浏览器 | Chrome/Edge/Firefox 最新两个大版本 | Safari 拖拽上传已知兼容问题 |
| 模型接口 | 兼容 OpenAI Embedding / Cohere Rerank 协议 | 设计文档 14 |
| 文件格式 | 见 4.2 文档摄取需求 | |

---

## 6. MVP 范围

### 6.1 MVP 包含

| 模块 | MVP 能力 |
|------|----------|
| 知识库 | 创建、编辑、删除、统计、公开/私有范围 |
| 文档摄取 | PDF/Word/TXT/Markdown/Excel/图片/视频/链接 |
| 检索 | 语义 + 关键词 + 混合检索，三种模式 |
| 问答 | 单轮/多轮对话、流式/非流式、引用溯源、反馈 |
| 权限 | 五级穿透、RBAC+ABAC、用户组、字段级/标签级/关键词级权限 |
| 安全 | 关键词拦截、敏感信息检测、Prompt 注入防护、API 安全网关 |
| 模型配置 | Embedding/Re-rank/LLM 热配置 |
| 用户管理 | 用户/用户组 CRUD、JWT 登录、API Key scope |
| 评测 | 数据集管理、检索/生成指标、A/B 对比 |
| 部署 | Docker Compose 全量/轻量、Kong 网关、监控告警 |

### 6.2 MVP 不包含（P2 远期）

- 知识图谱模块（实体/关系抽取、图谱检索）
- 企微 / 飞书 / 钉钉 IM 集成
- Agentic RAG（多跳检索、自我修正、规划）
- 多语言 UI（i18n）
- 移动端响应式适配
- 音频 RAG 完整 Pipeline（已部分实现，依赖 ASR 私有化环境）

### 6.3 MVP 验收标准

1. `docker-compose up -d` 可一键启动全栈。
2. `http://localhost:8000/docs` 可访问 API 文档。
3. `http://localhost:3002` 可访问前端。
4. 可完成：上传文档 → 解析分块 → 向量化 → 检索 → 问答 完整流程。
5. 权限控制和关键词拦截功能可演示。
6. `scripts/agent_api_harness.py` 全量 API 测试通过（73 PASS / 2 SKIP / 0 FAIL）。

---

## 7. 需求优先级汇总

| 优先级 | 含义 | 对应范围 |
|--------|------|----------|
| P0 | 影响 MVP 可用性，必须完成 | 4.1-4.9 全部 P0 项 |
| P1 | 影响产品竞争力和效果，建议 1 个月内补齐 | 完整混合检索、多轮对话增强、Prompt 注入分类器、评测工作台深度 |
| P2 | 长期差异化能力 | 知识图谱、IM 集成、Agentic RAG、多语言、移动端 |

---

## 8. 参考文档

- `docs/design/01-系统总体架构.md`
- `docs/design/04-用户群与多层级权限控制.md`
- `docs/design/05-关键词分级敏感控制系统.md`
- `docs/design/06-多模态RAG-Pipeline设计.md`
- `docs/design/07-统一检索与重排序引擎.md`
- `docs/design/12-评测与反馈体系.md`
- `docs/design/13-部署与运维架构.md`
- `docs/design/14-技术选型与实施路线图.md`
- `PROJECT_PLAN.md`
- `docs/gap_analysis.md`
