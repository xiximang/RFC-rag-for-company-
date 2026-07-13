# 企业级私有化多模态 RAG 系统 — 测试报告摘要

> 版本：v1.0  
> 更新日期：2026-07-04  
> 测试时间：2026-07-04  
> 测试目标：`scripts/agent_api_harness.py` 全量 API 可用性  
> 依据：`scripts/agent_api_harness.py`、`docs/operations/api_test_report_2026-07-03.md`

---

## 1. 测试概述

### 1.1 测试目标

验证企业级私有化多模态 RAG 系统在当前部署环境下，全部核心 API 接口的可用性、权限边界与异常处理能力。

### 1.2 测试范围

覆盖以下 11 个功能区域：

1. `auth` — 认证
2. `apikeys` — API Key 生命周期
3. `permissions` — 权限边界
4. `groups` — 用户组管理
5. `keywords` — 敏感关键词
6. `eval` — 评测
7. `system` — 系统端点
8. `docs` — 文档上传与管理
9. `kb` — 知识库管理
10. `docs_lifecycle` — 文档全生命周期
11. `search_chat` — 搜索与问答

### 1.3 测试环境

| 项目 | 内容 |
|------|------|
| 部署模式 | Docker Compose 轻量版（pgvector + Redis + local storage） |
| 后端容器 | `rag-lw-app-backend` |
| 前端容器 | `rag-lw-frontend` |
| 测试基址 | `http://localhost:8080/api/v1` |
| 测试用户 | L0–L4 五个分级测试账号，每个账号对应一个 API Key |
| 凭证文件 | `.tmp/agent_credentials.json` |

### 1.4 测试工具

- `scripts/agent_api_harness.py`：基于 `requests` 的 API 可用性测试脚本。
- 命令：`python scripts/agent_api_harness.py --base-url http://localhost:8080 --area all`

---

## 2. 测试执行结果

### 2.1 总体统计

| 指标 | 数值 |
|------|------|
| 测试区域数 | 11 |
| 通过（PASS） | 73 |
| 失败（FAIL） | 0 |
| 跳过（SKIP） | 2 |
| 错误（ERROR） | 0 |
| **通过率** | **100%（按执行用例）** |

### 2.2 各区域详细结果

| 区域 | PASS | FAIL | SKIP | ERROR | 状态 |
|------|------|------|------|-------|------|
| auth | 14 | 0 | 0 | 0 | ✅ 通过 |
| apikeys | 9 | 0 | 1 | 0 | ✅ 通过 |
| permissions | 7 | 0 | 0 | 0 | ✅ 通过 |
| groups | 7 | 0 | 0 | 0 | ✅ 通过 |
| keywords | 6 | 0 | 0 | 0 | ✅ 通过 |
| eval | 5 | 0 | 0 | 0 | ✅ 通过 |
| system | 4 | 0 | 0 | 0 | ✅ 通过 |
| docs | 2 | 0 | 0 | 0 | ✅ 通过 |
| kb | 6 | 0 | 0 | 0 | ✅ 通过 |
| docs_lifecycle | 5 | 0 | 0 | 0 | ✅ 通过 |
| search_chat | 8 | 0 | 1 | 0 | ✅ 通过 |
| **合计** | **73** | **0** | **2** | **0** | ✅ 通过 |

### 2.3 SKIP 说明

| 区域 | SKIP 原因 |
|------|-----------|
| apikeys | 某条可选 scope 校验依赖外部服务状态，当前环境未启用 |
| search_chat | 流式对话的某条边界用例依赖真实 LLM 返回，当前使用 mock 服务跳过 |

> 以上 SKIP 项不影响核心功能可用性，均为环境或可选依赖导致的非阻塞跳过。

---

## 3. 关键测试项验证

### 3.1 认证与鉴权

| 测试项 | 结果 |
|--------|------|
| admin 登录返回 token | PASS |
| `/auth/me` 返回用户信息与 admin 一致 | PASS |
| 有效 API Key 通过 `X-API-Key` header 访问外部接口 | PASS |
| 同一 Key 通过 `Authorization: Bearer <key>` 访问 | PASS |
| 随机错误 Key 访问返回 401 | PASS |
| 创建后立即撤销的 Key 访问返回 401 | PASS |

### 3.2 知识库 / 文档全生命周期

| 测试项 | 结果 |
|--------|------|
| 创建知识库 | PASS |
| 列出知识库并确认 | PASS |
| 上传 txt 文档 | PASS |
| 查看文档列表 | PASS |
| 下载文件 | PASS |
| 删除文档 | PASS |
| 删除知识库 | PASS |

### 3.3 搜索与对话

| 测试项 | 结果 |
|--------|------|
| 混合搜索 | PASS |
| 语义搜索 | PASS |
| 关键词搜索 | PASS |
| 非流式对话 | PASS |
| 流式对话 | PASS |

### 3.4 API Key 权限边界

| 测试项 | 结果 |
|--------|------|
| L0 用户创建知识库返回 403 | PASS |
| L0 用户上传文档返回 403 | PASS |
| L1 用户创建知识库返回 403 | PASS |
| L2 用户创建知识库返回 201 | PASS |
| L4 用户列出知识库返回 200 | PASS |
| 各级用户 scope 列表正确 | PASS |

### 3.5 内部管理接口

| 测试项 | 结果 |
|--------|------|
| `/health` 健康检查 | PASS |
| admin 获取用户列表 | PASS |
| admin 创建新用户 | PASS |
| 非 admin 访问用户列表返回 403 | PASS |
| 权限检查接口 | PASS |
| admin 列出 API Key | PASS |

---

## 4. 发现与修复

### 4.1 本次测试未发现阻塞性问题

在当前轻量版部署下，`scripts/agent_api_harness.py` 全量 73 个用例全部通过，0 失败，0 错误。

### 4.2 历史问题回顾

在 2026-07-03 的多 Agent 测试中曾发现以下问题，已修复：

| Bug | 位置 | 影响 | 修复 |
|-----|------|------|------|
| `UUID(doc.kb_id)` 对已是 UUID 的对象重复包装 | `backend/app/api/v1/external.py` `_require_document_access` | 文档下载/删除外部 API 500 | 改为直接传 `doc.kb_id` |

修复后重新执行文档生命周期测试，全部通过。

---

## 5. 测试结论

1. **系统 API 整体可用**：73/73 执行用例通过，2 项因环境/可选依赖跳过，无失败。
2. **认证与授权机制正常**：JWT、API Key 两种传递方式、scope 权限边界、撤销机制均正确。
3. **知识库/文档 CRUD 正常**：创建、上传、下载、删除全流程可用。
4. **检索与问答正常**：三种检索模式、非流式/流式对话均返回正确结构。
5. **管理接口权限正确**：非管理员访问管理接口被正确拒绝。

---

## 6. 建议

### 6.1 上线前建议

1. 补充高并发与限流测试，验证 Kong rate-limiting 与后端承载能力。
2. 使用真实 Embedding / Re-rank / LLM 服务进行端到端效果回归测试。
3. 补充大文件（>100MB 视频/PDF）分片上传与超时测试。
4. 完成 `docs/deliverables/go_live_checklist.md` 全部安全与监控检查项。

### 6.2 上线后建议

1. 持续监控 API P99 延迟、错误率、Celery 队列长度。
2. 定期运行 `scripts/agent_api_harness.py` 作为回归测试。
3. 收集用户反馈，补充评测数据集，持续优化检索与生成效果。

---

## 7. 附录：测试命令

```bash
# 全量 API 测试
python scripts/agent_api_harness.py --base-url http://localhost:8080 --area all

# 指定区域测试（示例：认证）
python scripts/agent_api_harness.py --base-url http://localhost:8080 --area auth

# 指定区域测试（示例：搜索与对话）
python scripts/agent_api_harness.py --base-url http://localhost:8080 --area search_chat
```

---

## 8. 参考文档

- `scripts/agent_api_harness.py`
- `docs/operations/api_test_report_2026-07-03.md`
- `docs/API_USAGE.md`
- `docs/deliverables/go_live_checklist.md`
