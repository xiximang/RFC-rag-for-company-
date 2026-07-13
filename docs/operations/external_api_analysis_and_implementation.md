# 账号级外部 API 体系：文件/权限架构分析与实现

## 1. 结论

项目**后端已经实现了一套相对完整的账号级外部 API 体系**：

- `api_keys` 表 + 迁移脚本
- `ApiKeyService`：生成、哈希、校验、限流
- `api_keys.py`：用户在前端/内部创建、查看、撤销自己的 API Key
- `external.py`：外部系统通过 `X-API-Key` 调用搜索、聊天、知识库、文档等接口
- 权限模型：API Key 继承创建者的安全等级（L0-L4），scopes 不能超过该等级允许范围

**当前主要缺失是前端没有「我的 API Key」管理页面**，普通用户无法自助创建 Key。此外外部 API 有一些小缺陷（如 chat 非流式返回的 sources 被硬编码为空）。

本次实现重点：

1. 前端新增 **API Key 管理页面**（创建、复制、查看、撤销）。
2. 后端补充 `/api-keys/scopes` 返回当前用户可申请的 scope 列表。
3. 修复 `external_chat` 非流式返回丢失 `sources` 的问题。

---

## 2. 文件管理架构

### 2.1 架构分层

```
API 层 (FastAPI Routers)
├── documents.py          内部文档上传/下载/删除
├── knowledge_bases.py    知识库 CRUD
└── external.py           外部 API Key 接口（复用内部服务）

业务服务层 (Services)
├── DocumentService       文档元数据 + 文件流
├── KnowledgeBaseService  知识库业务
├── RetrievalService      检索、RRF、重排序
└── PermissionService     权限过滤

存储/向量抽象层
├── storage/              Local / S3(MinIO) 可插拔
├── retrieval/            Milvus / pgvector 可插拔
└── pipelines/            文档/Excel/图片/音频/视频/链接解析

异步任务层 (Celery)
├── ingest_tasks.py       解析 → 切片 → 标注 → 排队 embedding
└── embed_tasks.py        Embedding → 向量库 + 全文索引

数据层
├── PostgreSQL            documents / chunks / permissions / api_keys
├── pgvector/Milvus       向量索引
└── Meilisearch/TSVECTOR  全文索引
```

### 2.2 数据流

```
上传文件
  → DocumentService.upload_document()
    → 生成 storage_key: {kb_id}/{uuid}_{filename}
    → 调用 storage.upload() → local / MinIO
    → documents 表 status=pending
    → Celery process_document.delay(doc_id)

摄取任务
  → 下载到临时文件
  → PipelineFactory 按 file_type 选择解析管道
  → 切片 → Chunk 记录（含 content_tsv）
  → KeywordService / SensitiveInfoService 标注敏感信息
  → Celery embed_chunks()

索引任务
  → EmbeddingClient.embed_batch()
  → 向量库 insert_chunks()
  → 全文库 index_chunks()
  → Chunk.status=active, Document.status=indexed

检索
  → PermissionService.build_vector_filter()
  → 向量召回 + BM25 + RRF + Re-rank
  → PermissionService.check_field_permission()
  → 返回带来源引用的结果
```

### 2.3 关键文件

| 用途 | 路径 |
|------|------|
| 文档上传/下载 | `backend/app/api/v1/documents.py` |
| 外部 API | `backend/app/api/v1/external.py` |
| 文档服务 | `backend/app/services/document_service.py` |
| 存储工厂 | `backend/app/storage/__init__.py` |
| 向量工厂 | `backend/app/retrieval/vector_store.py` |
| 摄取任务 | `backend/app/workers/ingest_tasks.py` |
| 解析管道 | `backend/app/pipelines/factory.py` |

### 2.4 外部 API 视角的薄弱点

1. **缺少前端自助管理**：用户看不到、创建不了 API Key。
2. **缺少异步状态通知**：外部系统上传后只能轮询 document status。
3. **大文件上传占内存**：`await file.read()` 全量读入。
4. **chat 非流式 sources 为空**：`external_chat` 硬编码 `sources=[]`。
5. **scope 粒度粗**：只有全局 scope，没有「仅允许访问某几个 KB」的细粒度 scope。

---

## 3. 权限管理架构

### 3.1 权限模型

```
用户 (User)
├── security_level: L0 / L1 / L2 / L3 / L4
├── role / is_active / status
└── 所属用户组 (UserGroup)

权限维度
├── 文件类型权限 (FileTypePermission)   按 role_id（用户或组）控制可访问文件类型
├── 文档权限 (DocumentPermission)       单文档 READ / WRITE / ADMIN / DENY
├── 字段权限 (FieldPermission)          Word/Excel 字段/列/段落级控制
├── 标签权限 (TagPermission)            按标签放行/拦截
└── 用户组权限 (GroupPermission)        组级权限

权限生效链路
登录 → JWT → get_current_user
  → 业务路由
    → PermissionService
      ├── get_user_security_level()      用户+所属组最高安全等级
      ├── get_user_allowed_file_types()  允许文件类型
      ├── get_user_denied_documents()    黑名单文档
      ├── get_user_denied_tags()         黑名单标签
      ├── build_vector_filter()          生成向量库通用过滤条件
      └── check_field_permission()       chunk 字段级校验
```

### 3.2 关键文件

| 用途 | 路径 |
|------|------|
| 权限服务 | `backend/app/services/permission_service.py` |
| 用户模型 | `backend/app/models/user.py` |
| 权限模型 | `backend/app/models/permission.py` |
| 向量过滤 | `backend/app/retrieval/filters.py` |
| API Key 鉴权 | `backend/app/api/v1/auth.py` |

### 3.3 API Key 与权限的结合

- API Key 属于某个用户（`owner_id`）。
- Key 的 `scopes` 不能超过该用户安全等级允许范围（`ALLOWED_SCOPES_BY_LEVEL`）。
- 外部接口通过 `get_current_api_key_user()` 拿到 `UserResponse`，复用内部所有权限服务。
- 因此外部调用者**自动继承**该用户的知识库所有权、文件类型限制、字段级过滤等权限。

### 3.4 当前权限 gap

1. **管理接口缺少显式授权校验**：部分系统管理接口仅靠 `is_admin` 判断，未使用统一权限服务。
2. **API Key scope 无法限制到具体 KB**：拿到 `kb:write` 就能操作所有者全部 KB。
3. **外部 API 写操作缺少审计**：`AuditLog` 表已存在，但 `external.py` 未写入审计记录。
4. **缺少 API Key 使用日志**：没有按 key 统计调用量、失败率的接口。

---

## 4. 实现内容

### 4.1 后端增强

#### 4.1.1 新增 `GET /api/v1/api-keys/scopes`

返回当前登录用户可申请的 scope 列表，供前端动态渲染复选框。

响应示例：

```json
{
  "allowed_scopes": ["kb:read", "search", "chat", "doc:write"],
  "all_scopes": ["kb:read", "search", "chat", "doc:write", "kb:write", "user:read", "apikey:admin"]
}
```

#### 4.1.2 修复 `external_chat` 非流式 sources

原代码：

```python
return ChatResponse(
    answer=result["answer"],
    intercepted=result["intercepted"],
    sources=[],   # 硬编码为空
    ...
)
```

修复为：

```python
sources=result.get("sources", [])
```

### 4.2 前端新增 API Key 管理页

- 路径：`/api-keys`
- 功能：
  - 列表：名称、前缀、scopes、限流、过期时间、最后使用、状态
  - 创建：名称、scope 复选框（按当前用户等级过滤）、每分钟请求数、可选过期时间
  - 创建成功后弹窗显示完整 Key（只显示一次），支持一键复制
  - 撤销：将 Key 置为 inactive
- 菜单：在左侧菜单「权限管理」下方或用户头像下拉增加「API Key 管理」入口

### 4.3 文件改动清单

后端：
- `backend/app/api/v1/api_keys.py`：新增 `/scopes` 路由
- `backend/app/api/v1/external.py`：修复 chat sources

前端：
- `frontend/src/pages/ApiKeys.tsx`：新增页面
- `frontend/src/router.tsx`：注册 `/api-keys`
- `frontend/src/layout/AppLayout.tsx`：增加菜单项

---

## 5. 后续可继续增强

1. **细粒度 KB scope**：`kb:read:uuid1,uuid2`、`doc:write:uuid1`。
2. **外部 API 审计**：在 `external.py` 写操作处写入 `AuditLog`。
3. **Webhook**：文档 ingestion 完成后回调外部系统。
4. **API Key 统计**：按 key 展示调用次数、最近调用时间。
5. **上传优化**：支持 presigned URL / 流式分片上传。
