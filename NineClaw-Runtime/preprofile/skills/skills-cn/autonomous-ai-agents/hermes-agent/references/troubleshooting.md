# 故障排查

### 语音无法工作
1. 检查 config.yaml 中是否设置了 `stt.enabled: true`
2. 验证提供商：运行 `pip install faster-whisper` 或设置 API key
3. 在 gateway 中：执行 `/restart`。在 CLI 中：退出后重新启动。

### 工具不可用
1. 运行 `hermes tools` — 检查是否已为你的平台启用该工具集
2. 某些工具需要环境变量（检查 `.env`）
3. 启用工具后执行 `/reset`

### 模型/提供商问题
1. 运行 `hermes doctor` — 检查配置和依赖项
2. 运行 `hermes auth` — 对 OAuth 提供商重新进行身份验证（或运行 `hermes auth add <provider>`）
3. 检查 `.env` 是否包含正确的 API key
4. **Copilot 403**：`gh auth login` 的令牌不能用于 Copilot API。你必须通过 `hermes model` → GitHub Copilot 使用 Copilot 专用的 OAuth 设备代码流程。

### 更改未生效
- **工具/技能：** `/reset` 会使用更新后的工具集启动新会话
- **配置更改：** 在 gateway 中：执行 `/restart`。在 CLI 中：退出后重新启动。
- **代码更改：** 重启 CLI 或 gateway 进程

### 技能未显示
1. 运行 `hermes skills list` — 验证是否已安装
2. 运行 `hermes skills config` — 检查是否已为平台启用
3. 显式加载：`hermes -s name`（或该技能自己的 `/<name>` 斜杠命令）

### Gateway 问题
先检查日志：
```bash
grep -i "failed to send\|error" ~/.hermes/logs/gateway.log | tail -20
```

常见 gateway 问题：
- **退出 SSH 后 gateway 停止运行**：启用 linger：`sudo loginctl enable-linger $USER`
- **关闭 WSL2 后 gateway 停止运行**：要让 systemd 服务正常工作，WSL2 要求设置 `systemd=true`，该设置位于 `/etc/wsl.conf` 中。若未设置，gateway 会回退到 `nohup`（会在会话关闭时停止运行）。
- **Gateway 陷入崩溃循环**：重置失败状态：`systemctl --user reset-failed hermes-gateway`

### 平台特定问题
- **Discord bot 没有响应**：必须在 Bot → Privileged Gateway Intents 中启用 **Message Content Intent**。
- **Slack bot 只能在私信中工作**：必须订阅 `message.channels` 事件。否则，bot 会忽略公共频道。
- **Windows 特定问题**（`Alt+Enter` 换行、WinError 10106、使用 UTF-8 BOM 的配置、行尾格式）：请参阅 `references/windows-quirks.md`。

### 辅助模型无法工作
如果 `auxiliary` 任务（视觉、压缩、session_search）静默失败，说明 `auto` 提供商找不到后端。请设置 `OPENROUTER_API_KEY` 或 `GOOGLE_API_KEY`，也可以显式配置每项辅助任务的提供商：
```bash
hermes config set auxiliary.vision.provider <your_provider>
hermes config set auxiliary.vision.model <model_name>
```

### “重置权限”/自动批准所有操作
请参阅 `references/security-privacy.md` — 清除“Always allow”存储，不要改动 yolo mode。
