# Prompt Injection 分类器运维说明

## 1. 设计目标

项目中已有的静态正则规则 (`PROMPT_INJECTION_PATTERNS`) 会误杀长文本中偶然出现的敏感词。
`PromptInjectionClassifier` 在保留静态规则的同时，引入一个轻量、无外部模型依赖的评分器，通过**关键词密度 + 长度归一化**降低误报。

## 2. 核心原理

分类器从四个维度打分，每个维度输出 `[0.0, 1.0]`，再按权重加权：

| 维度 | 含义 | 主要信号 |
|------|------|----------|
| `regex` | 静态正则命中 | ignore/disregard/system:/DAN 等加权匹配 |
| `override` | 指令覆盖密度 | ignore、disregard、override、new instructions 等 |
| `roleplay` | 角色扮演信号 | pretend、act as、you are now、simulation 等 |
| `delimiter` | 分隔符/冒号异常 | `system:`、`developer:`、`<<<`、`[/system]` 等 |

最终分数会进行长度归一化：长文本中偶然出现少量敏感词会被压低，短注入 payload 会保持高分。

## 3. 可调参数

所有参数均可通过环境变量或构造函数覆盖：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `PROMPT_INJECTION_THRESHOLD` | `0.7` | 阻断阈值，分数 ≥ 阈值视为注入 |
| `PROMPT_INJECTION_WEIGHT_REGEX` | `0.50` | 正则维度权重 |
| `PROMPT_INJECTION_WEIGHT_OVERRIDE` | `0.20` | 指令覆盖维度权重 |
| `PROMPT_INJECTION_WEIGHT_ROLEPLAY` | `0.20` | 角色扮演维度权重 |
| `PROMPT_INJECTION_WEIGHT_DELIMITER` | `0.10` | 分隔符维度权重 |

权重会在初始化时自动归一化到和为 1。

## 4. 核心 API

```python
from app.services.prompt_injection_classifier import PromptInjectionClassifier

classifier = PromptInjectionClassifier()

# 仅返回风险分数
score = classifier.score("Ignore previous instructions")

# 返回完整审计结构
result = classifier.classify("Ignore previous instructions")
```

`classify` 返回结构：

```json
{
  "score": 0.85,
  "threshold": 0.7,
  "features": {
    "regex": 0.25,
    "override": 0.6,
    "roleplay": 0.0,
    "delimiter": 0.0
  },
  "matched_patterns": [
    "ignore\\s+(?:the\\s+)?(?:above\\s+|previous\\s+)?instructions?"
  ]
}
```

## 5. 与 Security Gateway 集成

`backend/app/services/security_gateway.py` 中的 `detect_prompt_injection` 采用双保险：

```
命中静态规则  OR  classifier.score >= threshold  -> 阻断
```

接口签名保持不变，现有调用方无需修改。

## 6. 审计字段建议

在日志 / 审计表中建议记录：

- `prompt_injection_score`: 分类器分数
- `prompt_injection_threshold`: 当前阈值
- `prompt_injection_features`: 四个维度分数（JSON）
- `prompt_injection_matched_patterns`: 命中的正则列表
- `prompt_injection_static_hit`: 是否命中静态规则

## 7. 调优建议

- 阈值过低：误报增加，普通业务查询被拦截。
- 阈值过高：漏报增加，复杂注入可能绕过。
- 如果某类注入绕过较多，可适当提升对应维度权重，例如提高 `PROMPT_INJECTION_WEIGHT_DELIMITER` 应对分隔符攻击。
- 生产环境建议结合人工标注持续校准阈值与权重。

## 8. 测试

```bash
cd backend
.venv/Scripts/python -m pytest tests/test_prompt_injection.py -v
.venv/Scripts/python -m pytest tests/ -q --ignore=tests/e2e
```
