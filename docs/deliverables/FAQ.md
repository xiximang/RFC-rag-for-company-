# 企业级私有化多模态 RAG 系统 — 常见问题解答（FAQ）

> 版本：v1.0  
> 更新日期：2026-07-04  
> 适用对象：最终用户、KB 管理员、Super Admin、技术支持  
> 依据：docs/operations/faq.md、README.md、docs/operations/lightweight_vs_full_deployment_plan.md、docs/API_USAGE.md

---

## 一、部署与资源

### Q1：系统有哪些部署方式？分别适合什么场景？

**A**：当前支持四种部署方式：

| 方式 | 容器数 | 建议资源 | 适用场景 |
|------|--------|----------|----------|
| Docker Compose 全量 | 约 14（+ 监控 17） | 16 核 / 16–32 GB | 功能验证、POC、中小型生产 |
| Docker Compose 轻量 | 5 | 8 核 / 8–16 GB | 本地开发、低配机器、<10 万文档 |
| Docker Compose 蓝绿 | 双应用副本 + 共享基础设施 | 按全量×1.5 规划 | 需要零停机发布的生产环境 |
| Kubernetes Helm | 按需 | 16 核 / 32 GB+ | 大型生产、HPA、Ingress、外部依赖 |

> 详细资源估算见 `docs/operations/docker_deployment_resource_estimate.md`。

### Q2：轻量模式与全量模式有什么区别？

**A**：

| 组件 | 全量模式 | 轻量模式 |
|------|----------|----------|
| 向量库 | Milvus 2.4 | PostgreSQL + pgvector |
| 对象存储 | MinIO | 本地文件系统 |
| 消息队列 | RabbitMQ | Redis |
| Worker | ingest / embed / permission-sync 独立容器 | 合并为一个 worker |
| 网关 | Kong | 可选，默认直连后端 |
| 监控 | Prometheus + Grafana + Alertmanager | 不启动 |

轻量模式保留全部"权限 RAG"核心功能，但裁剪了高可用基础设施，适合开发与中小规模部署。

### Q3：部署后前端或后端无法访问，如何排查？

**A**：按以下顺序排查：

1. 执行 `docker compose ps` 确认所有容器状态为 `Up`。
2. 查看后端日志：`docker logs rag-lw-app-backend`（或对应容器名）。
3. 检查 `.env` 中数据库、Redis、Milvus 地址是否正确。
4. 首次启动需确认 Alembic 迁移已执行。
5. 查看 Kong 配置是否加载：`docker logs <kong-container>`。

---

## 二、权限与账号

### Q4：系统的权限模型是怎样的？

**A**：系统采用 RBAC + ABAC 混合模型，并支持五级权限穿透：

```
文件类型 → 文档 → 字段/段落 → 标签 → 关键词
```

- 文件类型：控制用户可访问的模态（文档/Excel/图片/视频/链接）。
- 文档级：白名单/黑名单控制具体文档。
- 字段级：Word 段落、Excel 列/行/工作表级可见性。
- 标签级：按标签（如"公开/内部/机密"）过滤。
- 关键词级：按敏感词级别（L0-L4）拦截 Chunk。

### Q5：用户权限如何计算？

**A**：规则如下：

1. DENY 永远优先于 ALLOW。
2. 用户显式权限 > 用户组权限 > 角色默认权限。
3. 多个用户组权限取并集（OR），但 DENY 覆盖 ALLOW。
4. 用户有效安全级别 = max(个人级别, 所属所有组的最高级别)。

### Q6：普通用户如何申请访问某个知识库？

**A**：

1. 在知识库列表找到目标知识库。
2. 点击 **申请权限**。
3. 填写申请理由并提交。
4. KB 管理员或 Super Admin 在消息中心审批。
5. 审批通过后刷新页面即可访问。

### Q7：字段级权限支持哪些文档类型？

**A**：目前支持 Word 和 Excel：

- Word：可按段落或章节设置可见性。
- Excel：可按单元格、列、工作表设置可见性。

字段级权限通常用于财务、人事、合同等敏感内容场景。

### Q8：用户组权限如何继承？

**A**：权限继承遵循"用户组权限 ∪ 个人权限"的并集规则：

- 用户加入用户组后，自动获得该组的所有权限。
- 管理员也可单独给用户授权。
- 最终有效权限 = 用户组权限 + 个人直接权限。

### Q9：离职员工账号如何处理？

**A**：Super Admin 可在 **系统管理** → **用户管理** 中：

1. 禁用账号（保留历史审计日志）。
2. 或删除账号（谨慎操作，删除后无法恢复）。

建议优先使用"禁用"，以满足合规审计要求。

---

## 三、模型配置

### Q10：如何配置 Embedding / Re-rank / 生成模型？

**A**：Super Admin 进入 **系统管理** → **模型配置**：

- **Embedding 模型**：配置服务地址、向量维度、是否默认。
- **Re-rank 模型**：配置服务地址、Top-K 重排数量。
- **生成模型**：配置 Provider、API Key、Base URL、温度、最大 Token。

> 配置保存后即时生效，无需重启服务。

### Q11：支持哪些大模型 Provider？

**A**：当前已验证 minimax，接口设计上兼容 OpenAI 协议。后续可扩展至：

- 私有部署模型（如 vLLM、Ollama、Xinference）
- 商业 API（OpenAI、Azure OpenAI、智谱、通义千问等）

Embedding / Re-rank 服务须兼容 OpenAI Embedding / Cohere Rerank 接口契约。

### Q12：模型配置后为什么答案质量仍不理想？

**A**：可按以下方向优化：

1. 调整知识库分块大小（chunk_size / overlap）。
2. 更换或微调 Embedding 模型。
3. 启用/调整 Re-rank 模型 Top-K。
4. 在评测工作台跑 A/B 测试，定位 Bad Case。
5. 补充同义词映射和领域关键词。

---

## 四、敏感词与安全

### Q13：系统如何防止敏感信息泄露？

**A**：系统通过多层机制实现敏感信息控制：

1. **关键词分级拦截**：全局配置敏感词及级别（L0-L4），Chunk 入库时标注 `max_keyword_level`，检索和生成阶段按用户级别拦截。
2. **敏感信息检测**：识别身份证、手机号、邮箱、银行卡等 PII，支持脱敏。
3. **字段级/标签级权限**：限制用户可见内容范围。
4. **API 安全网关**：L4 本地处理、L3 脱敏、L2 直接调用的分级策略。
5. **Prompt 注入检测**：输入清洗、指令隔离、输出过滤。

### Q14：如何新增或修改敏感关键词？

**A**：Super Admin 进入 **系统管理** → **关键词管理**：

1. 点击 **新增关键词**。
2. 填写关键词、级别、分类、动作（block / warn）。
3. 保存后系统会自动触发异步任务重新标注相关 Chunk。

也支持通过 `POST /keywords/batch-import` 批量导入。

### Q15：为什么某些文档中的敏感词没有被拦截？

**A**：可能原因包括：

1. 关键词尚未同步到全局词库。
2. Chunk 的关键词标注异步任务尚未完成。
3. 用户安全级别高于该关键词级别。
4. 文档解析阶段未正确提取到该段文本（如扫描件 OCR 失败）。

---

## 五、API 使用

### Q16：如何获取 API 访问凭证？

**A**：

1. 登录系统。
2. 进入 **API Key 管理**。
3. 点击 **新建 API Key**，选择所需 scope。
4. 复制生成的 Key（仅展示一次）。

### Q17：API Key 的 scope 有哪些？如何选择？

**A**：常见 scope 包括：

| Scope | 说明 |
|-------|------|
| `kb:read` | 列出、查看知识库 |
| `kb:write` | 创建、修改、删除知识库 |
| `doc:read` | 查看文档列表和详情 |
| `doc:write` | 上传、删除文档 |
| `search` | 执行检索 |
| `chat` | 执行问答 |

用户可申请的范围受其安全级别限制：L0-L1 通常仅只读 scope，L2 及以上可申请写入 scope。

### Q18：API 调用返回 401 怎么办？

**A**：

1. 确认 API Key 未被撤销。
2. 确认请求头中正确传递了 `X-API-Key` 或 `Authorization: Bearer <key>`。
3. 确认 Key 拥有该接口所需的 scope。
4. 确认 Key 未过期（如系统配置了有效期）。

### Q19：外部系统如何集成知识库能力？

**A**：系统提供统一外部 API，基址为：

```
http://localhost:8000/api/v1/external
```

主要接口：

- `POST /external/knowledge-bases`：创建知识库
- `POST /external/knowledge-bases/{kb_id}/documents`：上传文档
- `POST /external/search`：混合检索
- `POST /external/chat`：非流式问答
- `POST /external/chat/stream`：流式问答

详细示例见 `docs/API_USAGE.md`。

---

## 六、文档摄取与检索

### Q20：上传文档后多久可以被搜索到？

**A**：取决于文件大小和系统负载：

- 普通文档（< 10 MB）：通常 30 秒~2 分钟。
- 大视频/大 PDF（> 100 MB）：可能需要 5~15 分钟。
- 可在 **任务中心** 查看解析进度，状态变为"已索引"后即可检索。

### Q21：为什么上传的文档搜不到？

**A**：请按以下顺序排查：

1. 检查文档状态是否为"已索引"。
2. 检查文档密级与当前用户权限是否匹配。
3. 检查搜索时是否选择了正确的知识库或模态过滤。
4. 检查问题是否与文档内容语义相关（尝试用更通用的关键词）。
5. 如果文档刚上传，可能 Worker 队列拥堵，请稍等或联系管理员。

### Q22：搜索响应很慢怎么办？

**A**：

1. 检查是否开启了重排序模型（会增加 100~500 ms 延迟）。
2. 检查知识库文档量级，超过千万级需联系管理员扩容 Milvus。
3. 检查网络延迟，尤其是私有化部署中的跨机房访问。
4. 查看 Grafana 监控，确认后端服务负载。

---

## 七、故障排查

### Q23：文档解析失败怎么办？

**A**：

1. 在文档列表查看失败原因。
2. 常见原因：文件损坏、加密 PDF、格式不符合预期、Worker 资源不足。
3. 可尝试点击 **重新处理**。
4. 多次失败后，联系管理员查看后端日志。

### Q24：生成的答案出现错误信息怎么办？

**A**：

1. 点击 **点踩** 并填写原因。
2. 检查引用来源是否准确。
3. 尝试调整问题表述，使其更具体。
4. 管理员可通过评测工作台分析 bad case，优化分块策略或重排序模型。

### Q25：忘记密码无法登录怎么办？

**A**：

1. 如果配置了 SSO/LDAP，可通过企业身份 Provider 登录。
2. 否则联系 Super Admin 重置密码。
3. 系统当前不开放用户自助找回密码（出于企业安全管控要求）。

---

## 八、快速索引表

| 问题类别 | 相关文档 | 负责人 |
|----------|----------|--------|
| 部署资源 | `docs/operations/docker_deployment_resource_estimate.md` | 运维工程师 |
| 部署模式对比 | `docs/operations/lightweight_vs_full_deployment_plan.md` | 运维工程师 |
| 基础使用 | `docs/deliverables/user_manual.md` | 最终用户、KB 管理员 |
| 权限配置 | `docs/deliverables/user_manual.md` 第 7 章 | KB 管理员、Super Admin |
| 模型配置 | `docs/deliverables/user_manual.md` 第 8 章 | Super Admin |
| API 使用 | `docs/API_USAGE.md` | 集成开发者 |
| 上线检查 | `docs/deliverables/go_live_checklist.md` | 项目经理、运维工程师 |
