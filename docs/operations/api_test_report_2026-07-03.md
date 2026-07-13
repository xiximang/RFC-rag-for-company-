# 项目 API 可用性多 Agent 测试报告

> 测试时间：2026-07-03  
> 测试目标：`http://localhost:8080/api/v1` 全量 API 可用性  
> 测试方式：5 个并发 QA Agent，分别负责认证、知识库/文档、搜索/对话、权限边界、内部管理接口

## 1. 测试环境

- 部署模式：Docker Compose 轻量版（pgvector + Redis + local storage，独立 worker 已移除）
- 后端容器：`rag-lw-app-backend`
- 前端容器：`rag-lw-frontend`
- 测试用户：通过 admin 账号预先创建 L0–L4 五个测试账号，每个账号生成对应 API Key
- 凭证文件：`C:/Users/wuton/Desktop/企业级私有rag/.tmp/agent_credentials.json`

## 2. 测试 Agent 分工

| Agent | 负责模块 | 测试数量 | 初始通过 | 修复后通过 |
|-------|---------|---------|---------|-----------|
| Agent 1 | 认证与 API Key 生命周期 | 6 | 6 | 6 |
| Agent 2 | 外部 API 知识库/文档全生命周期 | 7 | 5 | 7 |
| Agent 3 | 外部 API 搜索/对话 | 5 | 5 | 5 |
| Agent 4 | API Key scope 权限边界 | 8 | 8 | 8 |
| Agent 5 | 内部端点与管理接口 | 6 | 6 | 6 |
| **合计** | | **32** | **30** | **32** |

## 3. 各 Agent 详细结果

### Agent 1：认证与 API Key 生命周期 ✅ 6/6

| # | 测试项 | 状态码 | 结果 |
|---|--------|--------|------|
| 1 | admin 登录 `/auth/login` 返回 token | 200 | PASS |
| 2 | `/auth/me` 返回用户与 admin 一致 | 200 | PASS |
| 3 | 有效 API Key 通过 `X-API-Key` header 访问外部接口 | 200 | PASS |
| 4 | 同一 Key 通过 `Authorization: Bearer <key>` 访问 | 200 | PASS |
| 5 | 随机错误 Key 访问返回 401 | 401 | PASS |
| 6 | 创建后立即撤销的 Key 访问返回 401 | 401 | PASS |

**结论**：认证、JWT、API Key 两种传递方式、撤销机制均正常。

---

### Agent 2：知识库/文档全生命周期 ✅ 7/7（修复后）

| # | 测试项 | 状态码 | 结果 |
|---|--------|--------|------|
| 1 | POST `/external/knowledge-bases` 创建 KB | 201 | PASS |
| 2 | GET `/external/knowledge-bases` 列出并确认 | 200 | PASS |
| 3 | POST `/external/knowledge-bases/{kb_id}/documents` 上传 txt | 201 | PASS |
| 4 | GET `/external/knowledge-bases/{kb_id}/documents` 查看列表 | 200 | PASS |
| 5 | GET `/external/documents/{doc_id}/download` 下载文件 | 200 | PASS |
| 6 | DELETE `/external/documents/{doc_id}` 删除文档 | 204 | PASS |
| 7 | DELETE `/external/knowledge-bases/{kb_id}` 删除知识库 | 204 | PASS |

**初始失败项**：
- 第 5、6 步返回 500，错误信息：
  ```
  AttributeError: 'asyncpg.pgproto.pgproto.UUID' object has no attribute 'replace'
  ```
- 根因：`external.py` 的 `_require_document_access` 中 `UUID(doc.kb_id)` 重复包装，因为 `doc.kb_id` 从 ORM 取出时已是 UUID 对象。
- **修复**：`backend/app/api/v1/external.py` 第 522 行改为直接传递 `doc.kb_id`。

---

### Agent 3：搜索与对话 ✅ 5/5

| # | 测试项 | 状态码 | 结果 |
|---|--------|--------|------|
| 1 | POST `/external/search` 混合搜索 | 200 | PASS |
| 2 | POST `/external/search/semantic` 语义搜索 | 200 | PASS |
| 3 | POST `/external/search/keyword` 关键词搜索 | 200 | PASS |
| 4 | POST `/external/chat` 非流式对话 | 200 | PASS |
| 5 | POST `/external/chat/stream` 流式对话 | 200 | PASS |

**结论**：搜索三种模式均返回正确结构；对话接口（含 SSE 流式）正常返回，未因 LLM 配置缺失触发 5xx。

---

### Agent 4：API Key 权限边界 ✅ 8/8

| # | 测试项 | 账号等级 | 状态码 | 结果 |
|---|--------|---------|--------|------|
| 1 | POST `/external/knowledge-bases`（需 kb:write） | L0 | 403 | PASS |
| 2 | POST `/external/knowledge-bases/{kb_id}/documents`（需 doc:write） | L0 | 403 | PASS |
| 3 | POST `/external/knowledge-bases`（需 kb:write） | L1 | 403 | PASS |
| 4 | POST `/external/knowledge-bases`（需 kb:write） | L2 | 201 | PASS |
| 5 | GET `/external/knowledge-bases` | L4 | 200 | PASS |
| 6 | GET `/api-keys/scopes` 返回 L0 可选项 | L0 | 200 | PASS |
| 7 | GET `/api-keys/scopes` 返回 L2 可选项 | L2 | 200 | PASS |
| 8 | GET `/api-keys/scopes` 返回 L4 可选项 | L4 | 200 | PASS |

**结论**：scope 越权正确返回 403，符合 `ALLOWED_SCOPES_BY_LEVEL` 矩阵；各等级可申请的 scope 列表正确。

---

### Agent 5：内部端点与管理接口 ✅ 6/6

| # | 测试项 | 状态码 | 结果 |
|---|--------|--------|------|
| 1 | GET `/health` | 200 | PASS |
| 2 | GET `/users`（admin） | 200 | PASS |
| 3 | POST `/users` 创建新用户（admin） | 201 | PASS |
| 4 | GET `/users`（L0 token） | 403 | PASS |
| 5 | GET `/permissions/check/document/{uuid}` | 200 | PASS |
| 6 | GET `/api-keys` 列出 admin 自己的 Key | 200 | PASS |

**结论**：健康检查、管理员用户管理、权限检查接口均正常；非管理员访问管理接口被正确拒绝。

## 4. 发现的 Bug 与修复

| Bug | 位置 | 影响 | 修复 |
|-----|------|------|------|
| `UUID(doc.kb_id)` 对已是 UUID 的对象重复包装 | `backend/app/api/v1/external.py` `_require_document_access` | 文档下载/删除外部 API 500 | 改为直接传 `doc.kb_id` |

修复后重新执行 Agent 2 的完整脚本，7/7 全部通过。

## 5. 总体结论

- **32/32 测试通过**，项目 API 在当前轻量版部署下整体可用。
- 认证、API Key、scope 权限控制、知识库/文档 CRUD、搜索、对话、管理接口均正常工作。
- 仅发现一个后端类型转换 Bug，已修复并复测通过。
- 建议后续补充：上传大文件流式测试、高并发限流测试、LLM 真实调用回归测试。
