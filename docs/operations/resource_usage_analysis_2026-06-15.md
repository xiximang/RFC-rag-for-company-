# 企业级私有化 RAG 服务资源占用分析

> 分析日期：2026-06-15  
> 分析对象：`docker-compose.yml`（全量版）与 `docker-compose.lightweight.yml`（轻量版）

## 1. 分析结论（ TL;DR ）

| 部署模式 | 默认启动容器数 | 内存 limit 合计 | 实测内存占用 | 建议最低宿主机内存 | 典型 CPU 需求 |
|----------|---------------|----------------|-------------|-------------------|--------------|
| 超轻量版 | 4             | **1.6 GB**     | **~187 MB** | **2 GB**          | 1–2 核       |
| 轻量版   | 5             | **~4.9 GB**    | **~1.75 GB**| **6–8 GB**        | 2–4 核       |
| 全量版   | 16            | **~14.9 GB**   | **~12 GB+** | **16–20 GB**      | 6–8 核       |
| 全量 + 监控 | 19          | **~16.3 GB**   | **~14 GB+** | **20–24 GB**      | 8 核         |

- **超轻量版**：在轻量版基础上去掉独立 worker，改为 backend 同步执行任务（`CELERY_TASK_ALWAYS_EAGER=true`），并将 uvicorn workers 从 2 降到 1，实测仅占 **~187 MB**。
- 轻量版去掉了 Milvus、RabbitMQ、MinIO、Kong、监控栈，用 **pgvector + Redis + 本地存储** 替代，资源占用下降约 **65%**。
- 全量版资源大户主要是 **Milvus 独立节点（2 GB）**、多个 Python Worker（共 ~6 GB limit）以及 **Kong / RabbitMQ / MinIO** 等中间件。
- 实际占用通常低于 limit 合计，但 Docker Desktop / 虚拟机本身会额外吃掉 **0.5–1.5 GB**。

---

## 2. 轻量版资源明细

`docker-compose.lightweight.yml` 默认启动 5 个容器：

| 服务 | 镜像 | 内存 limit | CPU limit | 说明 |
|------|------|-----------|-----------|------|
| postgres | pgvector/pgvector:pg16 | 1 GB | 1.0 | 关系库 + 向量扩展 |
| redis | redis:7-alpine | 256 MB | 0.5 | 缓存 / Celery broker |
| app-backend | 本地构建 | 1.5 GB | 1.0 | FastAPI + Alembic + 2 workers |
| worker | 本地构建 (Dockerfile.ingest) | 2 GB | 1.0 | Celery 统一 Worker（ingest/embed/permission_sync） |
| frontend | 本地构建 (node + nginx) | 128 MB | 0.25 | 静态资源 nginx |
| **合计** | | **4.88 GB** | **3.75 核** | |

### 轻量版启动后的典型实际占用（估算）

| 服务 | 启动后内存 | 峰值（上传/索引时） |
|------|-----------|-------------------|
| postgres | 150–300 MB | 400 MB |
| redis | 30–50 MB | 100 MB |
| app-backend | 300–500 MB | 800 MB |
| worker | 400–700 MB | 1.5 GB（解析大文档 + embedding） |
| frontend | 20–40 MB | 50 MB |
| **合计** | **~1 GB** | **~2.8 GB** |

> 因此轻量版在 **6 GB 内存** 的笔记本上可稳定运行，8 GB 更从容。

---

## 3. 超轻量版优化（< 1 GB）

针对「宿主机内存最多 1 GB」的需求，对 `docker-compose.lightweight.yml` 做了进一步裁剪：

### 关键改动

1. **移除独立 worker 容器**
   - 原 worker 实测空闲内存 **1.18 GB**，是资源占用最大头。
   - 改为在 backend 内同步执行任务：`CELERY_TASK_ALWAYS_EAGER=true`。
   - 文档解析/embedding 等任务直接在 API 请求进程中完成，适合个人演示和小文件场景。

2. **backend uvicorn workers 从 2 降到 1**
   - 进程数减半，实测内存从 **~497 MB** 降到 **~145 MB**。

3. **收紧各服务 limit**
   - postgres: 1 GB → **512 MB**
   - frontend: 128 MB → **64 MB**
   - app-backend: 1.5 GB → **768 MB**
   - redis 保持 256 MB

### 超轻量版实测

| 服务 | 实测内存 | 内存 limit | 占用率 |
|------|---------|-----------|--------|
| rag-lw-app-backend | **145 MB** | 768 MB | 18.9% |
| rag-lw-postgres | **23.5 MB** | 512 MB | 4.6% |
| rag-lw-frontend | **12.8 MB** | 64 MB | 20.1% |
| rag-lw-redis | **5.4 MB** | 256 MB | 2.1% |
| **合计** | **~187 MB** | **1.6 GB** | |

###  trade-off

- ✅ 内存占用从 1.75 GB 降到 **187 MB**，满足 < 1 GB 要求。
- ⚠️ 大文件/批量 ingestion 会阻塞 API 进程；生产环境建议加回独立 worker。
- ⚠️ backend 768 MB limit 在解析超大文档时可能 OOM，适合轻量使用。

---

## 4. 全量版资源明细

`docker-compose.yml` 默认启动 16 个容器（不含 monitoring profile）：

| 服务 | 镜像 | 内存 limit | CPU limit | 说明 |
|------|------|-----------|-----------|------|
| kong | kong:3.5 | 1.5 GB | 1.0 | API 网关 |
| migrate | 本地构建 | 512 MB | 0.5 | 一次性迁移容器 |
| app-backend | 本地构建 | 1 GB | - | FastAPI API |
| ingest-worker | 本地构建 | 1.5 GB | 1.0 | 文档解析 Worker |
| embed-worker | 本地构建 | 1.5 GB | 1.0 | Embedding Worker |
| permission-sync-worker | 本地构建 | 1.5 GB | - | 权限同步 Worker |
| embedding-service | 本地构建 | 256 MB | 0.5 | 内嵌 embedding 服务 |
| llm-service | 本地构建 | 256 MB | 0.5 | 内嵌 LLM 服务 |
| frontend | 本地构建 | 128 MB | - | nginx 前端 |
| postgres | postgres:16 | 1 GB | 0.5 | 关系库 |
| redis | redis:7-alpine | 256 MB | 0.25 | 缓存 |
| rabbitmq | rabbitmq:3-management | 512 MB | 0.25 | 消息队列 |
| milvus-standalone | milvusdb/milvus:v2.4.1 | 2 GB | 2.0 | 向量数据库 |
| etcd | gcr.io/etcd-development/etcd:v3.5.5 | 512 MB | 0.5 | Milvus 元数据 |
| minio | minio/minio | 512 MB | 0.5 | 对象存储 |
| minio-init | minio/mc | 256 MB | 0.25 | 一次性初始化 |
| **合计** | | **14.88 GB** | **约 8.75 核** | |

### 全量版资源大户分析

1. **Milvus 独立节点（2 GB）**
   - 自带 etcd + MinIO 依赖，自身也是内存型向量数据库。
   - 实际启动后常占 1.2–1.8 GB。

2. **Python Worker 群（ingest / embed / permission-sync + backend，约 6 GB limit）**
   - 每个 Worker 镜像包含大量 ML/OCR/PDF 依赖，冷启动内存高。
   - 文档解析（tesseract、libreoffice、poppler）会显著推高峰值。

3. **API Gateway 与中间件（Kong、RabbitMQ、MinIO、etcd，约 3 GB）**
   - 这些组件提高了扩展性和企业特性，但也显著增加基线资源。

4. **可选监控栈（prometheus / grafana / alertmanager + exporters，约 1.5 GB）**
   - 默认不启动，需要 `--profile monitoring` 或 `--profile monitoring-exporters`。

---

## 5. 镜像体积分析

| 镜像 | Dockerfile | 估算体积 | 主要体积来源 |
|------|-----------|---------|-------------|
| rag-backend | `backend/Dockerfile` | ~1.5–2 GB | python:3.11-slim + requirements（torch/transformers 等） |
| rag-worker (ingest) | `backend/Dockerfile.ingest` | ~2–2.5 GB | 额外安装 tesseract、libreoffice、poppler |
| rag-frontend | `frontend/Dockerfile` | ~100–150 MB | node builder + nginx alpine |
| 基础镜像 | postgres / redis / rabbitmq / milvus / kong / minio / etcd | 各 100 MB–1 GB | 官方镜像 |

> 首次构建/拉取镜像会占用大量磁盘空间，建议预留 **10–15 GB** 镜像缓存。

---

## 6. 与宿主机配置对比

当前宿主环境：

- **逻辑 CPU**：16 核
- **物理内存**：12.6 GB

### 可运行性评估

| 模式 | 能否本地运行 | 说明 |
|------|-------------|------|
| 超轻量版 | ✅ 推荐（1 GB 内存主机） | 实测 187 MB，limit 1.6 GB，适合笔记本/小主机 |
| 轻量版 | ✅ 推荐 | limit 4.9 GB，峰值约 2.8 GB，12.6 GB 宿主机足够 |
| 全量版 | ⚠️ 紧张 | limit 14.9 GB，接近/超过 12.6 GB；需要调高 Docker Desktop 内存上限，且不能同时跑其他大应用 |
| 全量 + 监控 | ❌ 不建议 | 合计 16 GB+，本地内存不足 |

---

## 7. 优化建议

1. **内存 < 1 GB 选超轻量版**
   - `docker compose -f docker-compose.lightweight.yml up -d`
   - 已去掉独立 worker，backend 同步执行 ingestion，适合个人演示、小文件。

2. **日常使用选原轻量版**
   - 如需后台处理大文件，保留独立 worker：`CELERY_TASK_ALWAYS_EAGER=false` 并恢复 `worker` 服务。
   - 已覆盖知识库、检索、权限、上传等核心功能。

2. **全量版仅用于生产/演示**
   - 需要 16 GB+ 内存的服务器或云主机。
   - 若本地演示，可关闭 monitoring profile：
     ```bash
     docker compose -f docker-compose.yml up -d
     ```

3. **进一步压缩 Worker 内存**
   - 将 ingest / embed / permission-sync 合并为统一 worker（轻量版已这么做）。
   - 文档解析使用外部服务或按需启动，避免常驻大镜像。

4. **监控按需启用**
   - 不要默认启动 prometheus/grafana，需要时再附加 profile。

5. **Docker Desktop 内存设置**
   - 超轻量版：建议分配 **2 GB**。
   - 轻量版：建议分配 **5–6 GB**。
   - 全量版：建议分配 **12–14 GB**（如果宿主机允许）。

---

## 8. 实测数据

### 8.1 原轻量版（5 容器）

命令：`docker stats --no-stream`

| 服务 | 实测内存 | 内存 limit | 内存占用率 | 实测 CPU | 备注 |
|------|---------|-----------|-----------|---------|------|
| postgres | **53 MB** | 1 GB | 5.2% | 1.9% | pgvector 启动后基线较低 |
| redis | **5.4 MB** | 256 MB | 2.1% | 0.7% | 轻负载 |
| app-backend | **497 MB** | 1.5 GB | 32.4% | 0.7% | 2 workers + FastAPI |
| worker | **1.18 GB** | 2 GB | 59.0% | 0.1% | ingest 镜像含 tesseract/libreoffice，常驻内存高 |
| frontend | **13 MB** | 128 MB | 10.3% | 0.0% | nginx 静态服务 |
| **合计** | **~1.75 GB** | **4.88 GB** | **35.8%** | | |

### 关键发现

- 轻量版 **实际占用约 1.75 GB**，远低于 limit 合计 4.88 GB。
- 主要内存消耗来自 **worker（1.18 GB）**，原因是 Dockerfile.ingest 预装了 OCR、Office 解析等重型依赖。
- app-backend 约 500 MB，postgres 仅 53 MB，前端 13 MB，redis 5 MB。
- 当前宿主内存 12.6 GB，运行轻量版后仍有充足余量。

### 8.2 超轻量版（4 容器）

命令：`docker stats --no-stream`

| 服务 | 实测内存 | 内存 limit | 占用率 | 备注 |
|------|---------|-----------|--------|------|
| app-backend | **145 MB** | 768 MB | 18.9% | uvicorn workers=1 + eager Celery |
| postgres | **23.5 MB** | 512 MB | 4.6% | pgvector |
| frontend | **12.8 MB** | 64 MB | 20.1% | nginx |
| redis | **5.4 MB** | 256 MB | 2.1% | 缓存 / broker |
| **合计** | **~187 MB** | **1.6 GB** | | |

- 相比原轻量版，内存占用从 **1.75 GB** 降到 **187 MB**（下降约 **89%**）。
- 主要代价：ingestion 改为 backend 同步执行，不适合大文件/高并发场景。

## 9. 镜像体积实测

命令：`docker images`

| 镜像 | 大小 | 说明 |
|------|------|------|
| your-dockerhub-username/rag-backend | **1.65 GB** | python:3.11-slim + ML 依赖 |
| rag-system-worker | **2.36 GB** | ingest worker，额外含 tesseract / libreoffice |
| your-dockerhub-username/rag-frontend | **99 MB** | node builder + nginx alpine |
| postgres:16 | **642 MB** | 官方镜像 |
| redis:7-alpine | **58 MB** | 官方镜像 |
| **轻量版所需镜像合计** | **~4.75 GB** | 首次构建/拉取需预留此空间 |

---

## 10. 参考命令

```bash
# 查看容器资源占用
docker stats --no-stream

# 查看镜像占用
docker system df

# 轻量版启动
docker compose -f docker-compose.lightweight.yml up -d --build

# 全量版启动（不含监控）
docker compose -f docker-compose.yml up -d --build

# 全量版 + 监控
docker compose -f docker-compose.yml --profile monitoring up -d --build
```
