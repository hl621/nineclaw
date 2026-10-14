# 安全与隐私开关

以下是一些常见的“为什么 Hermes 会对我的输出 / 工具调用 / 命令执行 X 操作？”相关开关，以及更改它们的准确命令。由于这些设置只在启动时读取一次，大多数变更都需要新会话（在 chat 中执行 `/reset`，或启动新的 `hermes` invocation）才能生效。

### 工具输出中的 secret 脱敏

Secret 脱敏**默认开启**——工具输出（terminal stdout、`read_file`、web content、subagent summary 等）在进入对话 context 和 log 之前，会被扫描是否含有类似 API keys、token 和 secret 的字符串。正常使用时请保持启用：

```bash
hermes config set security.redact_secrets true       # keep enabled globally
```

**需要重启。**`security.redact_secrets` 会在 import 时生成 snapshot——在会话进行中切换它（例如通过工具调用运行 `export HERMES_REDACT_SECRETS=false`）不会对当前进程生效。请让用户从 terminal 更改 config，然后启动新会话。这是有意为之——可防止 LLM 在任务进行中自行切换该开关。

仅当你确实需要原始的凭据类字符串来进行 debugging 或 redactor 开发时才禁用：
```bash
hermes config set security.redact_secrets false
```

### Gateway 消息中的 PII 脱敏

这与 secret 脱敏相互独立。启用后，gateway 会对 user ID 进行 hash，并从 session context 中移除 phone number，然后才将其传给 model：

```bash
hermes config set privacy.redact_pii true    # enable
hermes config set privacy.redact_pii false   # disable (default)
```

### 命令审批提示

默认情况下（`approvals.mode: smart`），Hermes 会让辅助 LLM 评估被标记为 destructive 的 shell command（`rm -rf`、`git reset --hard` 等）。可用 mode 如下：

- `smart`——自动批准一次低风险命令，拒绝高风险命令，并在不确定时提示用户（默认）
- `manual`——始终提示
- `off`——跳过所有审批提示（等同于 `--yolo`）

```bash
hermes config set approvals.mode smart       # recommended middle ground
hermes config set approvals.mode off         # bypass everything (not recommended)
```

不更改 config、仅对单次 invocation 绕过审批：
- `hermes --yolo …`
- `export HERMES_YOLO_MODE=1`

注意：YOLO / `approvals.mode: off` 不会关闭 secret 脱敏。两者相互独立。

### “重置权限”/“让 Hermes 再次询问”

用户通常指的是：清除累积的“Always allow”状态——不是 yolo
mode，也不是每次编辑时的 diff prompt（不存在这种提示；file write 从不经过
approval prompt，只有 shell command 会）。该状态保存在两个位置：

1. Shell-command allowlist：`hermes config set command_allowlist '[]'`
2. Shell-hook consent（仅在存在时）：`rm -f ~/.hermes/shell-hooks-allowlist.json`

然后做一次基本检查：运行 `hermes config get approvals.mode`（结果不应是 `off`），
并确认用户的 launch alias 或 systemd unit 中没有固化 `--yolo`。

### Shell hook allowlist

部分 shell-hook integration 必须先得到明确的 allowlist 授权才能触发。它由 `~/.hermes/shell-hooks-allowlist.json` 管理——某个 hook 首次尝试运行时会以交互方式提示用户。

### 禁用 web/browser/image-gen 工具

如果要完全禁止 model 使用 network 或 media 工具，请打开 `hermes tools`，按平台进行切换。下一会话（`/reset`）生效。Toolset 列表请参阅 `references/configuration.md`。

