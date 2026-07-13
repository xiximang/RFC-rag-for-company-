# RAG 系统 — 权限分级体系端到端测试报告

> **测试日期**: 2026-07-08
> **测试环境**: Backend `http://localhost:8080/api/v1`
> **测试范围**: 3 个 P0 历史漏洞 + 外部 API Key 作用域执行
> **测试脚本**: `.tmp/permission_eval.py`
> **测试工具**: Python 标准库（urllib）

---

## 一、测试概览

| 指标 | 数值 |
|------|------|
| 总测试项 | 9 |
| 通过 | 5 |
| 失败 | 4 |
| 通过率 | 55.6% |
| 失败严重度 | **3 个 P0 漏洞全部复现 + 1 个 JWT/API Key 鉴权问题** |

---

## 二、P0 漏洞现状表

| 漏洞 | 之前状态（2026-07-07） | 现在状态（2026-07-08） | 是否修复 |
|------|------------------------|------------------------|----------|
| **P0-1 搜索越权** | 🔴 L1 用户能返回 admin KB 内容 | 🔴 tester_l1 调用 `POST /chat`（kb_ids=admin 的 demo-kb） → **HTTP 200，返回 4 条 admin 文档 chunk**（含 UPS5000-E-400K / 500K 型号表） | ❌ **未修复** |
| **P0-2 权限授予无管理员验证** | 🔴 L1 用户能给任何人授予权限 | 🔴 tester_l1 调用 `POST /permissions/grant` → **HTTP 200，返回 `{"message":"授权成功","permission_id":"e797f049-..."}`** | ❌ **未修复** |
| **P0-3 文档重处理无所有权检查** | 🔴 L1 用户可重处理 admin 文档 | 🔴 tester_l1 调用 `POST /documents/{admin_doc_id}/reprocess` → **HTTP 200，重处理已入队** | ❌ **未修复** |

### 2.1 漏洞复现证据

#### P0-1 搜索越权（tester_l1 → admin KB）

```
请求:  POST /api/v1/chat
       Authorization: Bearer <tester_l1 JWT>
       body: {"query":"50kVA 功率模块","kb_ids":["47da8708-f0c6-40a6-8285-298809e55c90"],"top_k":5,"mode":"hybrid"}

响应:  HTTP 200
       answer: 包含 UPS5000-E-400K / 500K 型号重量尺寸表
       sources: 4 条 admin 知识库的 chunk
```

**根因**（`backend/app/api/v1/chat.py::_retrieve_and_generate`）：
```python
chunks = await retrieval_service.search(
    db=db,
    user_id=user_id,             # ← tester_l1
    query=query,
    kb_ids=kb_ids,               # ← 直接信任用户传入的 kb_ids，无所有权校验
    ...
)
```
`/api/v1/chat` 与 `/api/v1/search` 都没有调用 `_require_kb_access()`，这与 `documents.py` 中的 `upload_document` 形成了鲜明对比——后端已存在 KB 所有权检查函数但未在搜索/对话链路中复用。

#### P0-2 权限授予（tester_l1 → 给 admin 授权）

```
请求:  POST /api/v1/permissions/grant
       Authorization: Bearer <tester_l1 JWT>
       body: {"target_type":"user","target_id":"<admin user_id>","object_type":"document","object_id":"1854a453-...","permission":"READ"}

响应:  HTTP 200
       body: {"message":"授权成功","permission_id":"e797f049-4732-4484-a8b7-21e7073af8ff"}
```

**根因**（`backend/app/api/v1/permissions.py`）：
```python
@router.post("/grant")
async def grant_permission(
    request: PermissionGrantRequest,
    service: PermissionService = Depends(get_permission_service),
    current_user: UserResponse = Depends(get_current_user),   # ← 只检查登录
):
    perm = await service.grant_permission(...)
```
端点缺少 `if not is_admin(current_user): raise 403` 的守门。

#### P0-3 文档重处理（tester_l1 → 重处理 admin 文档）

```
请求:  POST /api/v1/documents/1854a453-cd80-4a46-b99c-157a72a44bab/reprocess
       Authorization: Bearer <tester_l1 JWT>

响应:  HTTP 200
       body: {"id":"1854a453-...","kb_id":"47da8708-...","filename":"UPS5000-E-(350kVA-500kVA) 快速指南 (50kVA功率模块).pdf", ...}
```

**根因**（`backend/app/api/v1/documents.py::reprocess_document`）：
```python
async def reprocess_document(...):
    service = DocumentService(db)
    doc = await service.get_document(doc_id)
    if doc.status == "processing": ...
    await service.clear_document_index(doc_id)   # ← 任意用户可清空索引
    _dispatch_ingest(str(doc_id), background)
```
没有调用 `_require_document_access(db, current_user, doc_id)`，与 `delete_document` 端点相同的漏洞（`delete_document` 已经修了，但 reprocess 没修）。

---

## 三、API Key 测试矩阵

| # | Actor | Endpoint | 期望 | 实际 | HTTP | 备注 |
|---|-------|----------|------|------|------|------|
| 1 | admin JWT | `POST /external/chat` | allowed | ❌ **blocked (401 "Invalid API key")** | 401 | **新发现**：JWT 不能直接用于 `/external/*` 端点，需用 API Key |
| 2 | search-chat Key (scopes=[search,chat,kb:read]) | `POST /external/chat` | allowed | ✅ allowed | 200 | 正常返回检索片段 |
| 3 | search-chat Key | `POST /external/knowledge-bases/{kb}/documents` | blocked | ✅ blocked | 403 | `"Missing required scope: doc:write"` |
| 4 | search-only Key (scopes=[search]) | `POST /external/knowledge-bases` | blocked | ✅ blocked | 403 | `"Missing required scope: kb:write"` |
| 5 | search-only Key | `POST /external/chat` | blocked | ✅ blocked | 403 | `"Missing required scope: chat"` |
| 6 | search-only Key | `POST /external/search` | allowed | ✅ allowed | 200 | 正常返回 5 条结果 |
| 7 | full-admin Key (scopes=[\*]) | `POST /external/chat` | allowed | ⚠️ 无法创建 | — | admin 安全等级为 L0，不允许 scopes=[\*]，需 L4 用户 |

### 3.1 关键观察

- **API Key 作用域执行严密**：`require_api_scope()` 依赖注入在 4 个 `/external/*` 端点上 100% 拦截越权请求（403 + 明确错误信息）。
- **域隔离清晰**：外部 `/api/v1/external/*` 与内部 `/api/v1/chat` / `/api/v1/permissions` 是两套独立鉴权链路——API Key 校验通过 `get_current_api_key_user`，JWT 校验通过 `get_current_user`。
- **scope 矩阵严格执行**：`scopes_for_level()` 与 `validate_scopes_for_level()` 阻止了 admin (L0) 创建 `*` 级别的 Key，符合"Key 永远不能超出 owner 等级"的设计原则。

---

## 四、新发现的问题

### 🔴 NEW-1: JWT 不能直接调用 `/api/v1/external/*`

```
测试:  admin (L0) JWT 调 POST /external/chat
响应:  HTTP 401  {"detail":"Invalid API key"}
```

**根因**（`backend/app/api/v1/auth.py::_extract_api_key`）：`get_current_api_key_user` 把 `Authorization: Bearer <JWT>` 当作 API key 处理，但 JWT 不是 `rag_live_` 前缀，bcrypt 校验必然失败。

**影响**：外部 `/external/*` 端点只接受 API Key 鉴权，与 `/chat`、`/search` 等内部端点的 JWT 鉴权完全分离。这意味着如果第三方系统拿到了 admin JWT，仍无法直接对接 `/external/*`。从安全设计上是合理的"双轨"隔离，但从 API 体验上需要文档说明。

### 🟡 NEW-2: `*` scope 仅 L4 用户可申请

```
测试:  admin (L0) 创建 scopes=["*"] 的 Key
响应:  HTTP 403  "Scopes not permitted for level L0: ['*']"
```

这是设计行为（`ALLOWED_SCOPES_BY_LEVEL["L4"]=["*"]`），但测试用例 3.5 因此跳过。建议测试报告补充说明："完整 scope Key 必须由 L4 用户创建"。

---

## 五、修复建议（按优先级）

### P0（必须修复 — 阻止生产上线）

| 优先级 | 漏洞 | 建议修复 |
|--------|------|----------|
| P0-1 | 搜索/对话 KB 越权 | 在 `chat.py::chat()`、`search.py::search()`、`external.py::external_chat()` 与 `external_search()` 起始处插入 `await _require_kb_access(db, current_user, kb_id)` 循环校验 |
| P0-2 | 权限授予无管理员验证 | `permissions.py::grant_permission` 起始处加 `if not is_admin(current_user): raise HTTPException(403, "需要管理员权限")` |
| P0-3 | 文档重处理无所有权 | `documents.py::reprocess_document` 改为 `doc = await _require_document_access(db, current_user, doc_id)` |

### P1（建议修复 — 减少攻击面）

| 优先级 | 问题 | 建议 |
|--------|------|------|
| P1-1 | `/api/v1/external/*` 与内部 API 鉴权"双轨" | 在 API 文档（`docs/API_USAGE.md`）中明确：外部端点必须用 API Key；为内部测试场景提供 `Authorization: ApiKey <jwt>` 兼容（可选） |
| P1-2 | `/permissions/grant` 同时缺少"目标用户存在性"校验 | 授予前先 `db.get(User, target_id)`，目标不存在时 404 |

### P2（长期改进）

| 优先级 | 问题 | 建议 |
|--------|------|------|
| P2-1 | 无审计日志记录上述越权尝试 | 引入中间件记录 403 事件，关联到 `audit_logs` 表 |
| P2-2 | `*` scope 仅 L4 申请 | 在管理后台提供 L4 用户的 key 列表，方便运维 |

---

## 六、测试环境与方法说明

### 6.1 测试用户

| 用户名 | 安全等级 | 来源 | 备注 |
|--------|---------|------|------|
| admin | L0 | `.tmp/token.txt` | 已有 JWT |
| tester_l1 | L0 | `POST /auth/register` 自动 L0 | 测试用例不需要 L1/L3 差异，主要验证"跨用户越权" |
| tester_l3 | L0 | 同上 | 备用 |

### 6.2 测试数据

| 资源 | UUID |
|------|------|
| demo-kb | `47da8708-f0c6-40a6-8285-298809e55c90`（admin 所有） |
| 50kVA 文档 | `1854a453-cd80-4a46-b99c-157a72a44bab` |
| 40kVA 文档 | `7e67e15f-c89b-40c6-8ae7-c8d3e9041c2d` |
| 60kVA 文档 | `613aa74e-18fc-4847-adfc-6fe99f104e1f` |

### 6.3 复现命令（最小化）

```bash
python .tmp/permission_eval.py
```

输出同时落盘到 `.tmp/permission_eval_results.json`。

---

## 七、总结

- **修复数**: 0 个 P0 漏洞被修复（3/3 全部复现）
- **新增问题**: 2 个（NEW-1 JWT 不能用于 `/external/*`、NEW-2 `*` scope 仅 L4）
- **正面发现**: API Key 作用域执行严密，外部端点 100% 拦截越权 scope 请求
- **核心建议**: 在 chat/search/permissions/grant/reprocess 四个端点补上 `_require_kb_access` / `is_admin` 守门，可在 50 行代码内完成

> **结论**: 数据库层权限模型（L0-L3 + 12 张权限表）设计完整，但 API 层 3 个 P0 漏洞 100% 复现，权限分级体系仍**不可直接用于生产环境**。API Key 路径唯一亮点。