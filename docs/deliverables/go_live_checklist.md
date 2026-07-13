# 企业级私有化多模态 RAG 系统 — 上线 Checklist

> 版本：v1.0  
> 更新日期：2026-07-04  
> 依据：README.md、docs/design/13-部署与运维架构.md、docs/operations/docker_deployment_resource_estimate.md、docs/gap_analysis.md

---

## 使用说明

本 Checklist 用于系统正式上线前的最后验收。建议由项目经理组织，运维、安全、研发、QA 共同参与逐项确认。所有关键项必须勾选通过后方可上线。

---

## 一、环境准备

| 序号 | 检查项 | 检查方式 | 结果 |
|------|--------|----------|------|
| 1.1 | 已确认部署模式：Docker Compose 全量 / 轻量 / K8s Helm | 查看部署方案文档 | ☐ |
| 1.2 | 服务器资源满足最低要求：开发 8 核/16GB；生产 16 核/32GB+ | `docker system info` / K8s 节点资源 | ☐ |
| 1.3 | 系统盘 ≥ 50 GB，数据盘按文档量级预留（小规模 100 GB，中规模 500 GB） | `df -h` | ☐ |
| 1.4 | Docker / Docker Compose / K8s / Helm 版本符合要求 | `docker --version`、`helm version` | ☐ |
| 1.5 | 网络策略已配置：Kong Admin / Grafana / Prometheus 不直接暴露公网 | 检查安全组 / Ingress 规则 | ☐ |
| 1.6 | 域名 / 内网 IP / TLS 证书已就绪 | 浏览器访问验证 | ☐ |
| 1.7 | `.env` 和 `backend/.env` 已从 `.env.example` 复制并替换默认值 | 文件检查 | ☐ |
| 1.8 | 所有默认密码、密钥已替换为强密码 | `openssl rand -hex 32` 示例 | ☐ |
| 1.9 | 敏感文件（`.env`、`backend/.env`、`secrets.yaml`）未提交到 Git | `git status` | ☐ |
| 1.10 | 外部依赖（Embedding / Re-rank / LLM）服务地址可达 | `curl` 健康检查 | ☐ |

---

## 二、安全与合规

| 序号 | 检查项 | 检查方式 | 结果 |
|------|--------|----------|------|
| 2.1 | JWT_SECRET_KEY 已替换为强随机密钥 | 检查 `backend/.env` | ☐ |
| 2.2 | PostgreSQL / Redis / RabbitMQ / MinIO / Grafana 密码已替换 | 检查 `.env` | ☐ |
| 2.3 | API Key 生产环境已替换占位值 | 检查 `kong.yml` / 数据库 | ☐ |
| 2.4 | 文件上传接口已启用类型白名单和大小限制 | 上传非法文件测试 | ☐ |
| 2.5 | 关键词敏感词库已按业务需求配置 | 系统管理 → 关键词管理 | ☐ |
| 2.6 | 五级权限穿透已验证：文件类型/文档/字段/标签/关键词 | 设计测试用例 | ☐ |
| 2.7 | 审计日志已开启并持久化 | 检查 PostgreSQL audit_logs 表 | ☐ |
| 2.8 | Prompt 注入回归测试已通过 | `backend/tests/test_prompt_injection.py` | ☐ |
| 2.9 | CI/CD 安全扫描（Bandit/Semgrep/pip-audit/Trivy/SBOM）无高危漏洞 | GitHub Actions Artifacts | ☐ |
| 2.10 | 容器镜像扫描无 HIGH/CRITICAL 漏洞或已评审接受 | Trivy 报告 | ☐ |
| 2.11 | 生产环境 Kong Admin API 已关闭或限制白名单 | 端口扫描 / 配置检查 | ☐ |
| 2.12 | 已配置 HTTPS / TLS，禁止明文 HTTP 传输敏感数据 | 浏览器证书检查 | ☐ |

---

## 三、监控与告警

| 序号 | 检查项 | 检查方式 | 结果 |
|------|--------|----------|------|
| 3.1 | Prometheus 可访问：`http://<host>:9090` | 浏览器 / curl | ☐ |
| 3.2 | Grafana 可访问：`http://<host>:3001`，默认密码已修改 | 登录验证 | ☐ |
| 3.3 | 4 套预置 Dashboard 已加载：Overview / API / Retrieval / LLM | Grafana UI | ☐ |
| 3.4 | 应用指标中间件已启用：`rag_api_requests_total`、`rag_retrieval_duration_seconds` 等 | Prometheus 查询 | ☐ |
| 3.5 | 告警规则已配置：P99 延迟、错误率、队列长度、磁盘、服务存活 | `monitoring/prometheus/alerts.yml` | ☐ |
| 3.6 | Alertmanager 告警通道已替换为真实接收人（邮件 / 飞书 / Slack / PagerDuty） | 触发测试告警 | ☐ |
| 3.7 | 日志已按 JSON 结构化输出 | 查看后端日志 | ☐ |
| 3.8 | 健康检查接口 `/api/v1/health` 返回各组件状态 | curl 验证 | ☐ |
| 3.9 | K8s 环境下 Liveness / Readiness Probe 已配置 | 检查 Deployment YAML | ☐ |

---

## 四、备份与恢复

| 序号 | 检查项 | 检查方式 | 结果 |
|------|--------|----------|------|
| 4.1 | PostgreSQL 每日全量备份任务已配置 | CronJob / 脚本 | ☐ |
| 4.2 | PostgreSQL WAL 增量备份已启用 | 检查 Postgres 配置 | ☐ |
| 4.3 | Milvus 每周全量备份 + 每日增量备份已配置 | 备份脚本 | ☐ |
| 4.4 | MinIO 对象存储已配置多副本或跨区域复制 | MinIO 控制台 | ☐ |
| 4.5 | Redis RDB 快照和 AOF 持久化已启用 | `redis.conf` | ☐ |
| 4.6 | 备份文件已存储到独立位置（异地或独立存储桶） | 检查备份目录 / 桶 | ☐ |
| 4.7 | 已执行一次备份恢复演练 | 演练记录 | ☐ |
| 4.8 | 数据保留策略已明确（如 PostgreSQL 30 天、Milvus 4 周） | 运维文档 | ☐ |

---

## 五、回滚与灰度

| 序号 | 检查项 | 检查方式 | 结果 |
|------|--------|----------|------|
| 5.1 | 已制定回滚方案：数据库迁移回滚、镜像版本回滚、配置回滚 | 回滚文档 | ☐ |
| 5.2 | 蓝绿部署脚本 `scripts/blue-green-deploy.sh` 已验证 | 执行一次切换演练 | ☐ |
| 5.3 | 回滚脚本 `scripts/rollback.sh` 已验证 | 执行一次回滚演练 | ☐ |
| 5.4 | 数据库变更已通过 Alembic 管理，具备 down revision | `alembic history` | ☐ |
| 5.5 | 生产镜像已按版本号标记（如 `v1.0.0`），旧版本镜像保留 | 镜像仓库 | ☐ |
| 5.6 | K8s 环境下滚动更新策略已配置 `maxSurge` / `maxUnavailable` | Deployment YAML | ☐ |
| 5.7 | 灰度发布方案已明确（如按用户组、按流量百分比） | 发布计划 | ☐ |

---

## 六、功能验收

| 序号 | 检查项 | 检查方式 | 结果 |
|------|--------|----------|------|
| 6.1 | 用户可正常注册/登录，JWT 鉴权生效 | 前端 + API 测试 | ☐ |
| 6.2 | 可创建知识库并配置可见范围、默认权限 | 前端操作 | ☐ |
| 6.3 | 可上传 PDF/Word/Excel/图片/链接文档 | 前端操作 | ☐ |
| 6.4 | 文档状态从"待解析"变为"已索引"，且可检索 | 等待 + 搜索验证 | ☐ |
| 6.5 | 混合/语义/关键词三种检索模式返回正确结果 | API 测试 | ☐ |
| 6.6 | 单库问答可生成答案并展示引用来源 | 前端操作 | ☐ |
| 6.7 | 流式问答正常输出 | 前端操作 | ☐ |
| 6.8 | 多轮对话上下文保留 | 前端操作 | ☐ |
| 6.9 | 答案点赞/点踩反馈正常 | 前端操作 | ☐ |
| 6.10 | 五级权限控制生效：越权文档/字段/关键词不可见 | 权限测试用例 | ☐ |
| 6.11 | API Key 创建、scope 限制、撤销机制正常 | `scripts/agent_api_harness.py` | ☐ |
| 6.12 | 评测工作台可导入数据集并生成指标报告 | 前端操作 | ☐ |
| 6.13 | 系统管理可配置 Embedding/Re-rank/LLM 模型 | 前端操作 | ☐ |
| 6.14 | 审计日志记录登录、上传、检索、权限变更 | 数据库查询 | ☐ |

---

## 七、性能与稳定性

| 序号 | 检查项 | 检查方式 | 结果 |
|------|--------|----------|------|
| 7.1 | 检索 P99 延迟 ≤ 2s | 压测报告 | ☐ |
| 7.2 | 问答生成 P99 延迟 ≤ 6.5s | 压测报告 | ☐ |
| 7.3 | API 错误率 ≤ 1% | Prometheus / 压测报告 | ☐ |
| 7.4 | 100 并发用户下核心功能稳定 | 压测报告 | ☐ |
| 7.5 | 连续 72 小时运行无崩溃 | 稳定性测试报告 | ☐ |
| 7.6 | Celery Worker 在任务堆积后可自动恢复 | 模拟任务堆积测试 | ☐ |
| 7.7 | 磁盘使用率在告警阈值（75%）以下 | `df -h` | ☐ |

---

## 八、文档交付

| 序号 | 检查项 | 检查方式 | 结果 |
|------|--------|----------|------|
| 8.1 | PRD 产品需求文档已交付 | `docs/deliverables/PRD.md` | ☐ |
| 8.2 | 用户操作手册已交付 | `docs/deliverables/user_manual.md` | ☐ |
| 8.3 | FAQ 文档已交付 | `docs/deliverables/FAQ.md` | ☐ |
| 8.4 | Sprint 计划已交付 | `docs/deliverables/sprint_plan.md` | ☐ |
| 8.5 | 上线 Checklist 已交付 | `docs/deliverables/go_live_checklist.md` | ☐ |
| 8.6 | 用户画像已交付 | `docs/deliverables/personas.md` | ☐ |
| 8.7 | 痛点优先级矩阵已交付 | `docs/deliverables/pain_priority_matrix.md` | ☐ |
| 8.8 | 需求调研报告已交付 | `docs/deliverables/requirements_research_report.md` | ☐ |
| 8.9 | 测试报告已交付 | `docs/deliverables/test_report.md` | ☐ |
| 8.10 | 培训 PPT 大纲已交付 | `docs/deliverables/training_ppt_outline.md` | ☐ |
| 8.11 | API 使用指南已就绪 | `docs/API_USAGE.md` | ☐ |
| 8.12 | 运维部署文档已就绪 | `docs/design/13-部署与运维架构.md` | ☐ |

---

## 九、上线审批

| 角色 | 签字 | 日期 |
|------|------|------|
| 项目经理 | ____________ | |
| 运维负责人 | ____________ | |
| 安全负责人 | ____________ | |
| QA 负责人 | ____________ | |
| 产品经理 | ____________ | |

---

## 十、上线后观察项

上线后 7 天内建议重点关注：

1. API P99 延迟与错误率趋势。
2. Celery 队列长度与 Worker 处理延迟。
3. 用户登录、检索、问答核心流程成功率。
4. 敏感词拦截与权限越界事件。
5. 磁盘与内存资源增长趋势。
6. 用户反馈收集与 Bad Case 登记。

---

## 附录：关键命令速查

```bash
# Docker Compose 全量启动
docker compose up -d

# 查看服务状态
docker compose ps

# 查看后端日志
docker logs rag-system-app-backend

# 执行 Alembic 迁移
cd backend && alembic upgrade head

# 健康检查
curl http://localhost:8000/api/v1/health

# API 全量测试
python scripts/agent_api_harness.py --base-url http://localhost:8080 --area all

# K8s 部署
cd k8s/helm/rag-system && bash upgrade.sh rag-system rag-system
```
