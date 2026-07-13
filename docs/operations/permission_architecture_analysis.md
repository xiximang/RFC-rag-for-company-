# 企业级私有化 RAG 系统权限架构分析

> 分析范围：`backend/app/models/permission.py`、`backend/app/services/permission_service.py`、
> `backend/app/services/security_gateway.py`、`backend/app/api/v1/permissions.py`、
> `backend/app/api/v1/auth.py`、`backend/app/services/api_key_service.py`、
> `backend/app/api/v1/external.py` 及相关检索/聊天/文档模块。

---

## 1. 总体设计思想

系统采用 **RBAC（角色/组）+ ABAC（属性）+ 安全等级（L0-L4）** 的混合权限模型，
目标是在多模态企业知识库场景中实现**五级权限穿透**：

```
L1 文件类型权限 → L2 文档权限 → L3 字段/内容权限 → L4 标签权限 → L5 关键词安全等级
```

权限控制贯穿三条核心链路：

1. **检索链路**：向量检索 / BM25 检索前生成权限过滤条件，过滤无权限文档/片段。
2. **生成链路**：安全网关根据用户等级、查询等级、上下文等级决定 API 调用策略。
3. **管理链路**：知识库/文档/标签/用户组的增删改查通过 ownership 或显式授权控制。

---

## 2. 身份主体（Subjects）

### 2.1 用户 `User`

| 字段 | 作用 |
|------|------|
| `id` | 全局唯一用户 ID |
| `username` | 登录名，同时也是 `ADMIN_USERNAMES` 判断依据 |
| `role_id` | 可选 RBAC 角色 ID |
| `security_level` | 用户自身安全等级 `L0-L4`，默认 `L0` |
| `status` / `is_active` | 账户激活状态 |

关键规则：
- 公开注册的用户强制为 `L0`，高等级必须由管理员修改。
- 用户有效安全等级 = `max(用户自身等级, 所属所有用户群的 max_security_level)`。

### 2.2 用户群 `UserGroup`

| 字段 | 作用 |
|------|------|
| `id` | 组 ID |
| `member_ids` | 成员用户 ID 列表（JSONB） |
| `admin_ids` | 组管理员 ID 列表 |
| `parent_group_id` | 父级组，支持层级继承 |
| `max_security_level` | 该组内最高安全等级 |

权限解析时会：
1. 找到用户直接所在的组。
2. 递归向上收集所有父组。
3. 用所有组的 `max_security_level` 参与最终安全等级计算。

### 2.3 角色 `role_id`

目前仅在 `FileTypePermission` 中作为 `role_id` 使用，代码注释说明它可以是用户 ID 或组 ID，
尚未看到独立的 `Role` 模型，因此**角色能力较弱**，主要靠用户群实现授权。

---

## 3. 权限对象（Objects）与模型

### 3.1 权限对象层级

| 层级 | 模型 | 资源粒度 | 授权对象 | 权限语义 |
|------|------|----------|----------|----------|
| L1 | `FileTypePermission` | 文件类型（pdf/docx/excel/video/audio/image） | `role_id`（用户/组/角色 ID） | `READ` / `UPLOAD` / `DELETE` / `ADMIN` / `DENY` / `NONE` |
| L2 | `DocumentPermission` | 单篇文档 | `user` / `group` / `role` / `all` | `NONE` / `READ` / `WRITE` / `ADMIN` / `DENY` |
| L3 | `FieldPermission` | Word 段落 / Excel 工作表/列/行 | `allowed_*` / `denied_*`（用户/组/角色） | 默认拒绝，需显式授权；支持细粒度配置 |
| L4 | `TagPermission` | 单个标签 | `user` / `group` / `role` / `all` | `allow` / `deny` |
| — | `GroupPermission` | 用户组资源 | 组 | JSONB 权限详情（目前未在业务中明显使用） |

### 3.2 关键模型语义说明

#### `DocumentPermission`

- `grantee_type`: `user` / `group` / `role` / `all`
- `grantee_id`: 对应对象 ID，`all` 时可为空
- `permission`: `NONE` / `READ` / `WRITE` / `ADMIN` / `DENY`
- `inherit_from_kb`: 是否继承知识库默认权限（目前未看到知识库默认权限逻辑，字段保留）

解析优先级（代码中实现）：
```
ADMIN > WRITE > READ > NONE
DENY 一旦命中立即中断并返回 DENY
```

#### `FieldPermission`

- **默认拒绝**：只要某文档存在任何字段权限记录，未明确允许的片段都不可见。
- 支持两类细粒度配置：
  - **Excel**: `access_level`（FULL / PARTIAL / NONE）、允许/拒绝列、行过滤。
  - **Word**: 拒绝某些标题路径下的段落。

注意：字段权限的检查入口在 `PermissionService.check_field_permission`，由 `RetrievalService` 在召回后调用，
属于**后置过滤**，会消耗一次数据库查询。

#### `TagPermission`

- 只有 `allow` / `deny` 两种结果。
- `deny` 的标签会在检索时生成向量过滤条件（`tags not contains denied_tag`），
  同时在 BM25 检索和后置过滤中再次兜底。

---

## 4. 权限解析服务 `PermissionService`

### 4.1 核心方法

| 方法 | 作用 |
|------|------|
| `get_user_security_level` | 计算用户最终安全等级（自身 + 所在组） |
| `get_user_allowed_file_types` | 计算允许访问的文件类型集合（DENY 优先） |
| `check_document_permission` | 检查对单篇文档的最终权限 |
| `get_user_denied_documents` | 获取被明确拒绝的文档 ID 集合 |
| `get_user_denied_tags` | 获取被明确拒绝的标签 ID 集合 |
| `check_field_permission` | 检查片段字段级权限 |
| `build_vector_filter` | 构建后端无关的权限过滤器 `VectorFilter` |
| `build_milvus_filter_expr` | 兼容旧接口，生成 Milvus 过滤表达式 |

### 4.2 缓存策略

所有权限计算结果都通过 `CacheManager`（基于 Redis）缓存：

- `user_security_level:{user_id}`
- `user_file_types:{user_id}`
- `user_doc_permission:{user_id}:{doc_id}`
- `user_tag_permission:{user_id}`

缓存失效点：
- `grant_permission` / `revoke_permission` 时调用 `invalidate_target_cache`。
- 文档级变更时调用 `cache.invalidate_document_cache`。

**风险点**：缓存失效目前只针对目标对象，若用户被移出群组、组层级变更、标签重命名等，
可能需要更广泛的缓存清除策略。

---

## 5. 权限在核心链路的落点

### 5.1 检索链路 `RetrievalService.search`

```text
1. 计算用户安全等级、拒绝文档集合、拒绝标签集合、允许文件类型集合
2. 调用 PermissionService.build_vector_filter(...) 生成 VectorFilter
3. 向量检索：将 VectorFilter 传入 vector_store.search_text/search_image
   - Milvus: 转换为布尔表达式
   - pgvector: 转换为 SQLAlchemy WHERE 子句
4. BM25 检索：使用 denied_doc_ids / denied_tags / modalities 过滤
5. 加载 Chunk 后再次兜底：
   - denied_docs 二次校验
   - check_field_permission 字段级权限
   - 关键词等级过滤（高于用户等级的片段内容会被替换为"[内容涉及更高敏感级别，已过滤]"）
```

### 5.2 生成链路 `chat.py` / `SecurityGateway`

- **前置快检** `_fast_level_check`：
  - 若用户等级或查询关键词等级 ≥ L4，直接返回本地拦截，不走检索/LLM。
- **策略决策** `decide_api_strategy`：
  - `local_only`（L4）：禁止调用外部 API。
  - `masked_api`（L3）：调用外部 API 前对手机号、身份证、邮箱、金额做脱敏。
  - `direct_api`（L2 及以下）：直接调用。

### 5.3 管理链路

#### 知识库 `knowledge_bases.py`

- 目前使用**简单所有权模型**：`kb.owner_id == current_user.id`。
- 注释说明未来可叠加权限服务实现共享/成员访问。
- 外部 API 复用了同一 `_require_kb_access` 函数。

#### 文档 `documents.py` / `external.py`

- 通过 `DocumentService.get_document` + 知识库 ownership 校验访问。
- 删除文档时会级联删除向量、全文索引、存储文件。

#### 权限管理 `permissions.py`

提供统一 REST 接口：
- `POST /permissions/file-type`
- `POST /permissions/document`
- `POST /permissions/field`
- `POST /permissions/tag`
- `POST /permissions/grant` / `POST /permissions/revoke`
- `GET /permissions/check/{doc_id}`
- `GET /permissions/check/{object_type}/{object_id}`

所有接口都需要 JWT 登录，但没有额外的管理员权限校验（普通用户理论上可互相授权）。

---

## 6. 外部 API Key 权限模型

### 6.1 认证方式

- 请求头 `X-API-Key: rag_live_...` 或 `Authorization: Bearer rag_live_...`
- 服务端使用 bcrypt 校验 key 哈希。
- 支持过期时间、每分钟请求速率限制（Redis 计数器）、软删除。

### 6.2 Scope 矩阵（按用户安全等级限制）

| 用户等级 | 可申请的 scope |
|----------|----------------|
| L0 | `kb:read`, `search`, `chat` |
| L1 | + `doc:write` |
| L2 | + `kb:write` |
| L3 | + `user:read`, `apikey:admin` |
| L4 | `*`（全部） |

### 6.3 授权链

```
外部请求 → API Key 认证 → 还原为 owner UserResponse → 复用内部 PermissionService
```

也就是说，API Key 的**数据权限继承自 key 所有者**，scope 只控制能调用哪些外部端点，
不替代内部的文档/字段/标签级权限过滤。

---

## 7. 架构优势

1. **五级穿透设计完整**：从文件类型到关键词等级形成纵深防御。
2. **检索权限下推**：向量和 BM25 都在数据库层过滤，避免无权限数据进入内存。
3. **向量存储后端无关**：`VectorFilter` 同时支持 Milvus 表达式和 pgvector SQL，便于双模式部署。
4. **缓存提升性能**：权限计算结果 Redis 缓存，减少重复查询。
5. **外部 API Key 与内部权限解耦**：Key 只做端点 scope 控制，数据权限仍走统一服务。
6. **安全网关三层策略**：L4 拦截、L3 脱敏、L2 直通，符合企业合规需求。

---

## 8. 现存问题与风险

### 8.1 管理接口缺乏授权校验

`permissions.py` 中所有授权/撤销接口只要求登录，未校验当前用户是否为管理员或被授权对象的管理员，
存在普通用户越权修改他人权限的风险。

### 8.2 知识库访问模型过于简单

仅按 `owner_id` 判断，缺少：
- 知识库成员/共享机制
- 知识库级默认权限向文档继承（`inherit_from_kb` 字段未使用）
- 组级知识库访问

### 8.3 `GroupPermission` 表未启用

模型存在但业务代码中未见使用，用户群权限只通过 `DocumentPermission` / `TagPermission` 等表实现，
缺少统一的组-资源授权视图。

### 8.4 字段权限是后置过滤

`check_field_permission` 在召回后才执行，存在性能问题：
- 高过滤比例场景下可能召回大量无效结果。
- 无法利用向量/BM25 索引提前过滤。

### 8.5 缓存失效策略不够全面

以下场景可能导致权限缓存不一致：
- 用户被添加/移出用户群
- 用户群层级调整
- 用户安全等级被管理员修改
- 标签从文档上移除（TagPermission 仍缓存）

### 8.6 `FileTypePermission` 语义混合

`role_id` 字段既当作角色 ID 又当作用户/组 ID，缺少清晰的 RBAC 角色表，
长期维护容易混乱。

### 8.7 审计与日志不足

权限变更、拒绝访问、L4 拦截等关键事件未看到集中审计日志模型，
仅通过 Prometheus 指标 `rag_permission_intercepts_total` 统计拦截次数。

---

## 9. 改进建议

### 短期（不影响现有功能）

1. **给权限管理接口加管理员校验**：
   - 仅管理员可授予/撤销权限。
   - 普通用户只能查看自己的权限。
2. **完善缓存失效**：
   - 用户更新、组更新、组成员变更时清除相关用户权限缓存。
3. **字段权限前置化**：
   - 将允许的字段路径/列信息写入 chunk metadata，检索时先过滤再加载 Chunk。

### 中期

4. **引入知识库成员/共享模型**：
   - `KnowledgeBaseMember` 表记录用户/组对 KB 的 `READ` / `WRITE` / `ADMIN` 权限。
   - 文档默认继承 KB 权限，可单独覆盖。
5. **建立独立 `Role` 模型**：
   - 明确区分角色、用户、用户群三类授权对象。
   - 避免 `role_id` 混用。
6. **统一审计日志**：
   - 记录权限变更、访问拒绝、L4 拦截、API Key 使用等事件。

### 长期

7. **支持策略即代码（Policy as Code）**：
   - 考虑引入 OPA / Casbin 处理复杂 ABAC 策略。
8. **细粒度到单元格**：
   - Excel 字段权限从列/行扩展到单元格级，需要更丰富的 position_info 和过滤逻辑。

---

## 10. 关键文件索引

| 文件 | 说明 |
|------|------|
| `backend/app/models/permission.py` | 权限模型定义 |
| `backend/app/models/user.py` | 用户与安全等级 |
| `backend/app/models/group.py` | 用户群与层级 |
| `backend/app/services/permission_service.py` | 权限解析核心 |
| `backend/app/services/security_gateway.py` | 安全网关与 API 策略 |
| `backend/app/services/api_key_service.py` | 外部 API Key 与 scope |
| `backend/app/api/v1/permissions.py` | 权限管理 REST 接口 |
| `backend/app/api/v1/auth.py` | JWT / API Key 认证依赖 |
| `backend/app/api/v1/external.py` | 外部 API 端点（scope 校验） |
| `backend/app/api/v1/knowledge_bases.py` | 知识库 ownership 校验 |
| `backend/app/services/retrieval_service.py` | 检索链路权限过滤 |
| `backend/app/retrieval/filters.py` | 后端无关权限过滤器 |
| `backend/app/core/cache.py` | 权限缓存 |

---

## 11. 结论

该项目的权限架构设计思路清晰，覆盖了企业 RAG 场景的主要需求：
**文件类型 → 文档 → 字段 → 标签 → 关键词等级** 五级穿透，
并在检索、生成、管理三条链路都有落点。

当前最突出的 gaps 是：
1. 权限管理接口自身缺少授权校验；
2. 知识库访问模型过于简单；
3. 字段权限后置过滤的性能与一致性；
4. 缓存失效策略不够全面。

建议优先补齐管理接口授权和知识库共享机制，再逐步细化字段权限与审计。
