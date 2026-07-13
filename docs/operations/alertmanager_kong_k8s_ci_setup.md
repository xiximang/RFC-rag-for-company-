# Alertmanager / Kong / K8s / CI 配置补齐说明

本文档说明如何为私有化 RAG 系统启用真实告警通道、Kong 健康检查、Kubernetes Startup Probe 以及 CI 镜像扫描门禁。

---

## 1. Alertmanager 真实告警通道

配置文件：`monitoring/alertmanager.yml`

### 1.1 Webhook URL 注入

所有 webhook receiver 的 URL 已改为通过环境变量注入，默认兜底为本地占位地址：

```yaml
webhook_configs:
  - url: '${ALERT_WEBHOOK_URL:-http://127.0.0.1:5001/_alertmanager/webhook}'
    send_resolved: false
```

启动 Alertmanager 时设置：

```bash
export ALERT_WEBHOOK_URL="https://hooks.slack.com/services/xxx"
docker compose up -d alertmanager
```

### 1.2 Email receiver 示例

Email receiver 默认保持注释，SMTP 相关全局配置也保持注释，确保没有真实 SMTP 时 Alertmanager 仍能正常启动。

如需启用邮件告警，先取消 `global` 中的 SMTP 注释并配置真实环境变量：

```bash
export SMTP_SMARTHOST="smtp.example.com:587"
export SMTP_FROM="alertmanager@example.com"
export ALERT_EMAIL_TO="ops-team@example.com"
```

然后取消 `receivers` 中 `email` receiver 的注释，并在 `route.routes` 中将需要邮件通知的告警路由到 `email`。

示例 receiver：

```yaml
receivers:
  - name: email
    email_configs:
      - to: '${ALERT_EMAIL_TO}'
        from: '${SMTP_FROM}'
        smarthost: '${SMTP_SMARTHOST}'
        send_resolved: true
```

验证配置（需 Alertmanager 二进制或容器）：

```bash
alertmanager --config.file=monitoring/alertmanager.yml --config.check
```

---

## 2. Kong 健康检查

配置文件：`kong.yml`

已为 `app-backend` 和 `app-backend-external` 两个服务开启主动健康检查：

```yaml
healthchecks:
  active:
    type: http
    http_path: /api/v1/health
    timeout: 5
    healthy:
      interval: 10
      successes: 2
    unhealthy:
      interval: 10
      http_failures: 3
```

- 探测路径：`/api/v1/health`
- 探测间隔：10 秒
- 单次探测超时：5 秒
- 健康判定：连续 2 次成功
- 不健康判定：连续 3 次失败

加载配置后，可通过 Kong Admin API 查看 upstream 健康状态：

```bash
curl -s http://localhost:8001/upstreams/app-backend/targets/health
```

或使用 decK 校验：

```bash
deck validate -s kong.yml
```

---

## 3. Kubernetes Startup Probe

文件：`k8s/helm/rag-system/templates/app-backend/deployment.yaml`

在 `livenessProbe` 和 `readinessProbe` 旁增加了 `startupProbe`：

```yaml
startupProbe:
  httpGet:
    path: /api/v1/health
    port: http
  periodSeconds: 10
  failureThreshold: 30
```

- 探测路径：`/api/v1/health`
- 探测周期：10 秒
- 最大失败次数：30（即最长允许 300 秒启动时间）

使用 Helm 部署时生效：

```bash
helm upgrade --install rag-system ./k8s/helm/rag-system \
  --namespace rag-system --create-namespace
```

验证 Pod 是否已挂载 startup probe：

```bash
kubectl describe pod -n rag-system -l app.kubernetes.io/component=app-backend
```

---

## 4. CI 镜像扫描门禁

文件：`.github/workflows/ci-cd.yml`

### 4.1 默认开启门禁

`IMAGE_SCAN_FAIL_ON_SEVERITY` 默认值已从 `"false"` 改为 `"true"`。

### 4.2 仅拦截 HIGH/CRITICAL 漏洞

为 `trivy-backend`、`trivy-frontend`、`trivy-worker` 三个扫描步骤增加了：

```yaml
severity: HIGH,CRITICAL
```

当 `IMAGE_SCAN_FAIL_ON_SEVERITY=true` 时，只要发现 HIGH 或 CRITICAL 漏洞，对应扫描步骤就会返回非零退出码并阻断构建。

### 4.3 关闭门禁时不阻断

若将 `IMAGE_SCAN_FAIL_ON_SEVERITY` 显式设为 `"false"`：

```yaml
env:
  IMAGE_SCAN_FAIL_ON_SEVERITY: "false"
```

或在工作流触发时通过 `workflow_dispatch` / 仓库变量覆盖，扫描仍会执行并生成报告，但 `exit-code: 0` 与 `continue-on-error: true` 保证不会阻断流水线。

### 4.4 查看扫描结果

扫描完成后，GitHub Actions 页面会展示：

- `image-scan-reports` artifact（JSON 格式原始报告）
- Job summary 中 `Trivy Backend/Frontend/Worker Scan` 状态
- Security report aggregation 中各镜像漏洞数量统计

---

## 5. 快速验证清单

| 组件 | 验证命令 |
|------|----------|
| Alertmanager 配置 | `alertmanager --config.file=monitoring/alertmanager.yml --config.check` |
| Kong 配置 | `deck validate -s kong.yml` 或 `deck sync -s kong.yml --dry-run` |
| K8s Deployment | `helm template rag-system ./k8s/helm/rag-system \| grep -A 6 startupProbe` |
| CI 工作流 | 在 GitHub Actions 页面手动触发一次构建，检查 trivy 步骤是否按预期通过/失败 |

---

## 6. 注意事项

1. `monitoring/alertmanager.yml` 中的环境变量默认值语法 `${VAR:-default}` 需要 Alertmanager ≥ 0.22 / Prometheus ≥ 2.30 才完全支持。低版本请去掉 `:-default` 并在运行时显式注入变量。
2. Kong 健康检查依赖后端 `/api/v1/health` 返回 HTTP 200；如果该端点暂时不可用，Kong 会标记 upstream target 为不健康，请确保应用启动后即暴露健康检查。
3. `startupProbe` 与 `livenessProbe`/`readinessProbe` 同时使用；startup probe 失败期间，liveness/readiness 不会执行，避免启动慢的应用被误杀。
4. 开启镜像扫描门禁后，建议定期 `trivy image --severity HIGH,CRITICAL <image>` 在本地预扫描，减少 CI 阻塞。
