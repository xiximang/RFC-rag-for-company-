# 企业级私有化多模态 RAG 系统 — Sprint 计划

> 版本：v1.0  
> 更新日期：2026-07-04  
> 依据：PROJECT_PLAN.md、docs/design/14-技术选型与实施路线图.md、docs/gap_analysis.md

---

## 说明

本计划将项目搭建实施分为 6 个 Sprint，每个 Sprint 约 1~2 周，与 `PROJECT_PLAN.md` 中的六个批次一一对应：

- Sprint 1：基础环境搭建
- Sprint 2：数据层与存储
- Sprint 3：核心服务
- Sprint 4：检索与生成
- Sprint 5：前端集成
- Sprint 6：测试验证与交付

---

## Sprint 1：基础环境搭建

### 目标

搭建项目运行的基础设施与前后端基座，确保团队可在统一环境中开发联调。

### 任务拆分

| 任务 | 负责人 | 输出 |
|------|--------|------|
| Docker Compose 全栈编排 | 基础设施工程师 | `docker-compose.yml`、`docker-compose.lightweight.yml` |
| Kong API 网关配置 | 后端工程师 | `kong.yml` |
| Prometheus + Grafana + Alertmanager 监控栈 | 运维工程师 | `monitoring/prometheus.yml`、`monitoring/grafana/*`、`monitoring/alertmanager.yml` |
| FastAPI 后端基础框架 | 后端工程师 | `backend/main.py`、`config.py`、`database.py`、`core/exceptions.py`、`requirements.txt`、`Dockerfile`、`Dockerfile.worker` |
| React 前端基础框架 | 前端工程师 | `frontend/package.json`、`vite.config.ts`、`tsconfig.json`、`src/App.tsx`、`src/main.tsx`、`src/router.tsx`、`src/layout/*`、`src/services/api.ts` |

### 验收标准

1. `docker compose up -d` 可启动全部基础服务。
2. Kong 代理可达：`curl http://localhost:8000/health` 返回 200。
3. 前端可访问：`http://localhost:3002` 显示登录页。
4. 后端 Swagger：`http://localhost:8000/docs` 可访问。

### 周期

约 1.5 周。

---

## Sprint 2：数据层与存储

### 目标

完成业务数据模型、向量存储与缓存封装，建立统一的数据访问层。

### 任务拆分

| 任务 | 负责人 | 输出 |
|------|--------|------|
| PostgreSQL 数据模型 + Alembic 迁移 | 后端工程师 | `backend/app/models/*.py`、`backend/alembic/*`、初始迁移脚本 |
| Milvus 向量存储封装 | 后端工程师 | `backend/app/retrieval/vector_store.py`、`backend/app/retrieval/milvus_client.py` |
| Redis 缓存封装 | 后端工程师 | `backend/app/core/cache.py`、`backend/app/core/redis_client.py` |
| 轻量模式 pgvector 适配 | 后端工程师 | `backend/app/retrieval/pgvector_client.py`（按需） |
| MinIO / 本地文件存储封装 | 后端工程师 | `backend/app/core/storage.py` |

### 验收标准

1. Alembic 迁移可正常执行，所有表创建成功。
2. Milvus Collection 可创建并写入测试向量。
3. Redis 缓存可读写，TTL 生效。
4. 轻量模式下 pgvector 可替代 Milvus 完成基础向量检索。

### 周期

约 1.5 周。

---

## Sprint 3：核心服务

### 目标

实现权限、关键词、文档摄取三大核心服务，支撑 RAG 主流程的数据准备与安全控制。

### 任务拆分

| 任务 | 负责人 | 输出 |
|------|--------|------|
| 用户群与权限服务 | 后端工程师 | `backend/app/services/permission_service.py`、`backend/app/api/v1/permissions.py`、`backend/app/api/v1/groups.py` |
| 关键词敏感控制服务 | 后端工程师 | `backend/app/services/keyword_service.py`、`backend/app/pipelines/keyword_annotator.py`、`backend/app/api/v1/keywords.py` |
| 文档摄取 Pipeline | 后端工程师 | `backend/app/pipelines/*.py`、`backend/app/services/document_service.py`、`backend/app/workers/ingest_tasks.py`、`backend/app/api/v1/documents.py` |
| 用户认证服务 | 后端工程师 | `backend/app/api/v1/auth.py`、`backend/app/services/auth_service.py` |
| 用户管理接口 | 后端工程师 | `backend/app/api/v1/users.py` |

### 验收标准

1. 用户注册/登录返回 JWT Token。
2. 用户/用户组 CRUD 正常。
3. 文档上传后进入 Celery 队列异步解析。
4. 关键词全局配置可保存，Chunk 入库时自动标注级别。
5. 五级权限计算正确，可通过 `/permissions/check/{doc_id}` 验证。

### 周期

约 2 周。

---

## Sprint 4：检索与生成

### 目标

实现统一检索引擎、重排序、生成服务与 API 安全网关，打通"问题 → 检索 → 答案"闭环。

### 任务拆分

| 任务 | 负责人 | 输出 |
|------|--------|------|
| 检索与重排序引擎 | 后端/算法工程师 | `backend/app/retrieval/retriever.py`、`backend/app/retrieval/fusion.py`、`backend/app/retrieval/reranker.py`、`backend/app/api/v1/search.py` |
| API 安全网关 + 上下文压缩 | 后端工程师 | `backend/app/services/security_gateway.py`、`backend/app/services/compression_service.py`、`backend/app/security/validator.py` |
| 生成服务 + 问答 API | 后端工程师 | `backend/app/services/chat_service.py`、`backend/app/api/v1/chat.py`、`backend/app/services/conversation_service.py` |
| 评测服务 | 后端/算法工程师 | `backend/app/services/eval_service.py`、`backend/app/api/v1/eval.py` |
| 模型配置服务 | 后端工程师 | `backend/app/core/runtime_config.py`、`backend/app/api/v1/config.py` |

### 验收标准

1. `/search` 三种模式（hybrid/semantic/keyword）返回正确结构。
2. `/chat` 非流式和 `/chat/stream` 流式均正常返回。
3. 答案包含引用来源（chunk_id、doc_id、score、position_info）。
4. 权限过滤与关键词拦截生效，越权内容不可见。
5. 评测接口可创建数据集、发起任务、查看指标。

### 周期

约 2 周。

---

## Sprint 5：前端集成

### 目标

完成管理后台与业务前端页面，实现用户可操作的完整产品界面。

### 任务拆分

| 任务 | 负责人 | 输出 |
|------|--------|------|
| 登录页 + 布局框架 | 前端工程师 | `frontend/src/pages/Login.tsx`、`src/layout/*` |
| 知识库管理 + 上传中心 + 文档查看 | 前端工程师 | `frontend/src/pages/KnowledgeBase.tsx`、`frontend/src/components/UploadPanel/*.tsx`、`frontend/src/components/DocViewer/*.tsx` |
| 搜索控制台 + 问答页面 | 前端工程师 | `frontend/src/pages/SearchConsole.tsx`、`frontend/src/pages/Chat.tsx` |
| 权限管理 + 标签管理 | 前端工程师 | `frontend/src/pages/PermissionMgr.tsx`、`frontend/src/components/PermissionEditor/*.tsx`、`frontend/src/components/TagManager/*.tsx` |
| 评测工作台 + 系统管理 | 前端工程师 | `frontend/src/pages/EvalWorkbench.tsx`、`frontend/src/pages/SystemAdmin.tsx` |

### 验收标准

1. 用户可完成：登录 → 创建知识库 → 上传文档 → 等待索引 → 检索 → 问答 的完整流程。
2. KB 管理员可配置知识库权限、标签、用户组成员。
3. Super Admin 可配置模型、查看审计日志、管理 API Key。
4. 评测工作台可导入数据集并展示指标。

### 周期

约 2 周。

---

## Sprint 6：测试验证与交付

### 目标

修复模块间接口不一致问题，完成集成测试、安全扫描与部署验证，达到上线条件。

### 任务拆分

| 任务 | 负责人 | 输出 |
|------|--------|------|
| 模块接口联调 | 全栈工程师 | 修复接口不一致、字段映射问题 |
| 集成测试 | QA 工程师 | 测试用例、测试报告 |
| API 可用性测试 | QA/自动化 | `scripts/agent_api_harness.py` 执行报告 |
| Docker Compose 一键启动验证 | 运维工程师 | 部署验证记录 |
| CI/CD 安全扫描 | DevOps 工程师 | GitHub Actions 报告、漏洞修复记录 |
| 文档整理 | 技术文档工程师 | PRD、用户手册、FAQ、上线 Checklist、培训 PPT 大纲 |

### 验收标准

1. `docker-compose up -d` 可一键启动所有服务。
2. `http://localhost:8000/docs` 可访问 FastAPI 自动生成的 API 文档。
3. `http://localhost:3002` 可访问前端页面。
4. 可完成：上传文档 → 解析分块 → 向量化 → 检索 → 问答 的完整流程。
5. 权限控制和关键词拦截功能可演示。
6. `scripts/agent_api_harness.py --area all` 全量通过，目标：73 PASS / 2 SKIP / 0 FAIL。
7. 完成 PRD、用户手册、FAQ、Sprint 计划、上线 Checklist、Persona、痛点矩阵、需求调研报告、测试报告、培训 PPT 大纲等 ToB 交付物。

### 周期

约 1.5 周。

---

## 总体里程碑

| 里程碑 | 时间 | 关键交付 |
|--------|------|----------|
| M1 基础设施就绪 | Sprint 1 结束 | Docker Compose 全栈可启动 |
| M2 数据层就绪 | Sprint 2 结束 | 模型、向量库、缓存可用 |
| M3 核心服务就绪 | Sprint 3 结束 | 权限、关键词、文档摄取可用 |
| M4 检索生成闭环 | Sprint 4 结束 | 搜索/问答/API 安全网关可用 |
| M5 前端集成完成 | Sprint 5 结束 | 核心页面流程可闭环操作 |
| M6 MVP 验收通过 | Sprint 6 结束 | 全量测试通过、交付文档齐全 |

---

## 风险与缓冲

| 风险 | 影响 | 应对 |
|------|------|------|
| Embedding/LLM 外部服务接入延迟 | 高 | 提前提供 mock 服务，接口契约先行 |
| 视频/音频解析环境依赖复杂 | 中 | Sprint 3 先支持文档/Excel/图片，音视频作为 P1 跟进 |
| 字段级权限性能问题 | 中 | 使用 Redis 缓存权限矩阵，Milvus expr 长度监控 |
| 前端联调接口不一致 | 中 | Sprint 6 预留 0.5 周集中联调 |
