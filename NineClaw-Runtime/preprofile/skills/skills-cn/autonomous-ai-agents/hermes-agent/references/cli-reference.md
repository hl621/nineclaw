# Hermes CLI 参考

当任何内容可能已过时时，请查看实时来源：`hermes --help`、`hermes <command> --help`、
https://hermes-agent.nousresearch.com/docs/reference/cli-commands

### 全局 Flags

```
hermes [flags] [command]        (no subcommand = interactive chat)

  --version, -V             Show version
  -z, --oneshot PROMPT      One-shot: print ONLY the final response (for scripts/pipes)
  -m MODEL  --provider P    Model/provider override for this invocation
  -t, --toolsets LIST       Comma-separated toolsets for this invocation
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --skills, -s SKILL        Preload skills (comma-separate or repeat)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --tui / --cli             Force the Ink TUI / classic REPL
  --ignore-rules            Skip AGENTS.md/SOUL.md/memory/skill injection
  --safe-mode               Disable ALL customizations (troubleshooting)
  --pass-session-id         Include session ID in system prompt
```

### Chat

```
hermes chat [flags]
  -q, --query TEXT          Single query, non-interactive
  --image PATH              Attach a local image to a single query
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --max-turns N             Cap tool-calling iterations
  --source TAG              Session source tag (default: cli)
```
（以及上面的全局 flags）

### 配置

```
hermes setup [section]      Wizard (model|tts|terminal|gateway|tools|agent)
hermes model                Interactive model/provider picker
hermes fallback [add|remove|list]  Fallback provider chain
hermes config [show|edit|get|set|unset|path|env-path|check|migrate]
hermes login / logout       OAuth sign-in / clear stored auth
hermes doctor [--fix]       Check dependencies and config
hermes status [--all]       Component status
```

### 工具与技能

```
hermes tools [list|enable NAME|disable NAME]   Per-platform toolsets (curses UI with no args)

hermes skills list|browse|search QUERY|inspect ID
hermes skills install ID    Hub identifier OR a direct https://…/SKILL.md URL
hermes skills config        Enable/disable skills per platform
hermes skills check|update|uninstall|publish PATH
hermes skills tap add REPO  Add a GitHub repo as a skill source
hermes bundles              Skill bundles (one /<name> alias loads several skills)
```

### MCP Servers

```
hermes mcp add NAME (--url or --command) | remove | list | test NAME
hermes mcp catalog | install NAME     Curated catalog install
hermes mcp configure NAME             Toggle tool selection
hermes mcp serve                      Run Hermes as an MCP server
```
详情（传输方式、工具发现、catalog）：`references/native-mcp.md`。

### Gateway（消息平台）

```
hermes gateway run|install|start|stop|restart|status|setup
```

20 多个平台：Telegram、Discord、Slack、WhatsApp（Baileys + Business Cloud API）、iMessage（Photon — `hermes photon setup`）、Signal、Email、SMS、Matrix、Mattermost、Teams、LINE、SimpleX、ntfy、Google Chat、Home Assistant、DingTalk、Feishu、WeCom、Weixin、API Server、Webhooks。Open WebUI 通过 API Server adapter 连接。大多数 adapter 位于 `plugins/platforms/` 下。
文档：https://hermes-agent.nousresearch.com/docs/user-guide/messaging/

### 会话

```
hermes sessions list|browse|rename ID TITLE|delete ID|export OUT|prune|stats
```

### Cron / Webhooks

```
hermes cron list|create SCHED|edit ID|pause|resume|run ID|remove|status
    Schedules: '30m', 'every 2h', '0 9 * * *', ISO timestamp
hermes webhook subscribe NAME|list|remove NAME|test NAME
```
Webhook payload/routes：`references/webhooks.md`。

### Profiles

```
hermes profile list|create NAME (--clone|--clone-all|--clone-from)|use|show|delete
hermes profile rename A B | alias NAME | export NAME | import FILE
```

### 凭据与凭据池

```
hermes auth                 Interactive credential manager
hermes auth add [PROVIDER]  Add OAuth or API-key credential (nous, openai-codex, qwen-oauth, …)
hermes auth list|remove P IDX|reset PROVIDER|status
```
同一 provider 的多份凭据会组成一个凭据池，自动轮换并跳过已耗尽的 key。

### 其他

```
hermes desktop / gui        Native desktop app
hermes dashboard            Web admin panel + embedded chat (--stop / --status)
hermes proxy                OpenAI-compatible local proxy backed by an OAuth provider
hermes portal               Quick setup / sign in via Nous Portal
hermes kanban <verb>        Multi-agent work-queue board
hermes project              Named multi-folder workspaces
hermes skin list|use|set    Switch/tweak skins (see references/themes.md)
hermes pets <verb>          Pet mascots (see references/petdex.md)
hermes memory setup|status|off|reset   Memory provider
hermes secrets bitwarden|onepassword   External secret stores
hermes moa                  Mixture-of-Agents slots
hermes hooks / security / backup / import / checkpoints / console
hermes logs [-f] [errors]   View agent/error logs
hermes send                 One-off message through a gateway platform
hermes pairing / plugins / insights / journey / computer-use
hermes acp                  ACP server (IDE integration)
hermes completion bash|zsh|fish
hermes update / uninstall / claw migrate
```

由 plugin 和 provider 提供的子命令（例如 `hermes photon setup`）只会在对应 plugin 已安装并处于活动状态后出现。

### 在哪里查找相关内容

| 要查找的内容…… | 位置 |
|---|---|
| 配置选项 | `hermes config edit` · [配置文档](https://hermes-agent.nousresearch.com/docs/user-guide/configuration) |
| 工具 / toolsets | `hermes tools list` · [工具参考](https://hermes-agent.nousresearch.com/docs/reference/tools-reference) |
| 技能目录 | `hermes skills browse` · [技能目录](https://hermes-agent.nousresearch.com/docs/reference/skills-catalog) |
| Provider 设置 | `hermes model` · [Providers 指南](https://hermes-agent.nousresearch.com/docs/integrations/providers) |
| 环境变量 | `hermes config env-path` · [环境变量参考](https://hermes-agent.nousresearch.com/docs/reference/environment-variables) |
| Gateway 日志 | `~/.hermes/logs/gateway.log`（或 `hermes logs`） |
| 会话 | `hermes sessions browse`（读取 state.db） |
