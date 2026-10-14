# Webhook 订阅

创建动态 webhook 订阅，让外部服务（GitHub、GitLab、Stripe、CI/CD、IoT sensors、monitoring tools）通过向 URL POST 事件来触发 Hermes 智能体运行。

## 设置（必须先完成）

必须先启用 webhook 平台，才能创建订阅。使用以下命令检查：
```bash
hermes webhook list
```

如果显示“Webhook platform is not enabled”，请进行设置：

### 选项 1：设置向导
```bash
hermes gateway setup
```
按照提示启用 webhooks、设置端口，并设置全局 HMAC secret。

### 选项 2：手动配置
添加到 `~/.hermes/config.yaml`：
```yaml
platforms:
  webhook:
    enabled: true
    extra:
      port: 8644
      secret: "generate-a-strong-secret-here"
```

省略 `host` 时，将使用 dual-stack 默认设置，同时侦听 IPv4 和 IPv6。
仅当你确实想限制绑定时，才应设置具体地址。

### 选项 3：环境变量
添加到 `${HERMES_HOME:-~/.hermes}/.env`：
```bash
WEBHOOK_ENABLED=true
WEBHOOK_PORT=8644
WEBHOOK_SECRET=generate-a-strong-secret-here
```

配置完成后，启动（或重启）网关：
```bash
hermes gateway run
# Or if using systemd:
systemctl --user restart hermes-gateway
```

验证其是否正在运行：
```bash
curl http://localhost:8644/health
```

## 命令

所有管理操作都通过 `hermes webhook` CLI command 完成：

### 创建订阅
```bash
hermes webhook subscribe <name> \
  --prompt "Prompt template with {payload.fields}" \
  --events "event1,event2" \
  --description "What this does" \
  --skills "skill1,skill2" \
  --deliver telegram \
  --deliver-chat-id "12345" \
  --secret "optional-custom-secret"
```

命令会返回 webhook URL 和 HMAC secret。用户应将其服务配置为向该 URL 发送 POST 请求。

### 在智能体运行前筛选或转换 payloads

有两种机制可用于收窄宽泛的事件流（例如 Todoist/GitHub 会在每次更新时触发），从而只让相关 payloads 唤醒智能体：

- **声明式 `filters`**（仅适用于 config.yaml routes）：由一系列针对 payload fields、event type 或 headers 的条件组成——支持 operators `equals`、`not_equals`、`contains`、`exists`、`missing`、`in`、`in_file`、`regex`，并支持 `all`/`any`/`not` 分组。不匹配的事件会被忽略，并返回 HTTP 200。
- **路由脚本**（订阅时使用 `--script`，或在 config route 上使用 `script:`）：位于 `~/.hermes/scripts/` 下的脚本会通过 stdin 接收 JSON 格式的 payload。JSON stdout 会在 prompt templating 前替换 payload；stdout 为空、值为 `[SILENT]` 或脚本以非零状态退出时，webhook 会被忽略。`.sh`/`.bash` 使用 bash 运行，其他脚本均使用 Python。脚本不能位于 `~/.hermes/scripts/` 之外（系统会阻止 path traversal）。

```bash
hermes webhook subscribe todoist-hermes \
  --prompt "Task changed: {payload.content}" \
  --script "todoist-hermes-label.py" \
  --deliver telegram --deliver-chat-id "12345"
```

完整 filter 语法：https://hermes-agent.nousresearch.com/docs/user-guide/messaging/webhooks#payload-filters

### 列出订阅
```bash
hermes webhook list
```

### 删除订阅
```bash
hermes webhook remove <name>
```

### 测试订阅
```bash
hermes webhook test <name>
hermes webhook test <name> --payload '{"key": "value"}'
```

## Prompt Templates

Prompts 支持使用 `{dot.notation}` 访问嵌套的 payload fields：

- `{issue.title}` —— GitHub issue title
- `{pull_request.user.login}` —— PR author
- `{data.object.amount}` —— Stripe payment amount
- `{sensor.temperature}` —— IoT sensor reading

如果未指定 prompt，系统会将完整 JSON payload 写入智能体 prompt。

## 常见模式

### GitHub：新 issues
```bash
hermes webhook subscribe github-issues \
  --events "issues" \
  --prompt "New GitHub issue #{issue.number}: {issue.title}\n\nAction: {action}\nAuthor: {issue.user.login}\nBody:\n{issue.body}\n\nPlease triage this issue." \
  --deliver telegram \
  --deliver-chat-id "-100123456789"
```

然后在 GitHub repo 的 Settings → Webhooks → Add webhook 中设置：
- Payload URL：返回的 webhook_url
- Content type：application/json
- Secret：返回的 secret
- Events：“Issues”

### GitHub：PR reviews
```bash
hermes webhook subscribe github-prs \
  --events "pull_request" \
  --prompt "PR #{pull_request.number} {action}: {pull_request.title}\nBy: {pull_request.user.login}\nBranch: {pull_request.head.ref}\n\n{pull_request.body}" \
  --skills "github-code-review" \
  --deliver github_comment
```

### Stripe：payment events
```bash
hermes webhook subscribe stripe-payments \
  --events "payment_intent.succeeded,payment_intent.payment_failed" \
  --prompt "Payment {data.object.status}: {data.object.amount} cents from {data.object.receipt_email}" \
  --deliver telegram \
  --deliver-chat-id "-100123456789"
```

### CI/CD：build notifications
```bash
hermes webhook subscribe ci-builds \
  --events "pipeline" \
  --prompt "Build {object_attributes.status} on {project.name} branch {object_attributes.ref}\nCommit: {commit.message}" \
  --deliver discord \
  --deliver-chat-id "1234567890"
```

### 通用 monitoring alert
```bash
hermes webhook subscribe alerts \
  --prompt "Alert: {alert.name}\nSeverity: {alert.severity}\nMessage: {alert.message}\n\nPlease investigate and suggest remediation." \
  --deliver origin
```

### 直接投递（不使用智能体，LLM 成本为零）

如果只想将通知推送到用户聊天中，而不需要推理或 agent loop，请添加 `--deliver-only`。渲染后的 `--prompt` template 将成为原样消息正文，直接发送到目标 adapter。

适用场景：
- 外部服务推送通知（Supabase/Firebase webhooks → Telegram）
- 应逐字转发的监控警报
- 一个智能体要向另一个智能体的用户传递消息时的智能体间通知
- 任何调用一轮 LLM 都只是徒增开销的 webhook

```bash
hermes webhook subscribe antenna-matches \
  --deliver telegram \
  --deliver-chat-id "123456789" \
  --deliver-only \
  --prompt "🎉 New match: {match.user_name} matched with you!" \
  --description "Antenna match notifications"
```

投递成功时，POST 返回 `200 OK`；目标投递失败时返回 `502`——这样上游服务就能智能重试。HMAC auth、rate limits 和 idempotency 仍然适用。

要求 `--deliver` 必须是真实目标（telegram、discord、slack、github_comment 等）——系统会拒绝 `--deliver log`，因为仅记录日志的直接投递没有意义。

## 安全性

- 每项订阅都会获得自动生成的 HMAC-SHA256 secret（也可以使用 `--secret` 自行提供）
- webhook adapter 会验证每个传入 POST 的 signatures
- config.yaml 中的静态 routes 不能被动态订阅覆盖
- 订阅持久保存到 `~/.hermes/webhook_subscriptions.json`

## 工作原理

1. `hermes webhook subscribe` 写入 `~/.hermes/webhook_subscriptions.json`
2. webhook adapter 会在每次传入请求时热重载此文件（受 mtime 控制，开销可忽略不计）
3. 当 POST 与某条 route 匹配时，adapter 会格式化 prompt 并触发智能体运行
4. 智能体的响应会投递到配置的目标（Telegram、Discord、GitHub comment 等）

## 故障排除

如果 webhooks 无法正常工作：

1. **网关是否正在运行？** 使用 `systemctl --user status hermes-gateway` 或 `ps aux | grep gateway` 检查
2. **webhook server 是否正在侦听？** `curl http://localhost:8644/health` 应返回 `{"status": "ok"}`
3. **检查网关日志：** `grep webhook ~/.hermes/logs/gateway.log | tail -20`
4. **Signature 不匹配？** 确认服务中使用的 secret 与 `hermes webhook list` 返回的 secret 一致。GitHub 发送 `X-Hub-Signature-256`，GitLab 发送 `X-Gitlab-Token`。
5. **Firewall/NAT 问题？** webhook URL 必须能从该服务访问。本地开发时，请使用隧道（ngrok、cloudflared）。
6. **Event type 错误？** 检查 `--events` filter 是否与服务发送的内容匹配。使用 `hermes webhook test <name>` 验证 route 是否正常工作。
