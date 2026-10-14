---
name: hermes-agent
description: "使用、配置、定制主题、扩展和编排 Hermes Agent。"
version: 3.1.0
author: Hermes Agent + Teknium
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [hermes, setup, configuration, multi-agent, spawning, cli, gateway, themes, skins, desktop-plugins, tui-widgets, petdex, development]
    homepage: https://github.com/NousResearch/hermes-agent
    related_skills: [claude-code, codex, opencode]
---

# Hermes Agent

Hermes Agent 是 Nous Research 推出的开源 AI 智能体框架，可在终端、原生桌面应用、消息平台和 IDE 中运行。它与 Claude Code (Anthropic)、Codex (OpenAI) 和 OpenClaw 属于同一类别——这类自主编程与任务执行智能体通过调用工具与你的系统交互。Hermes 支持任意 LLM 提供商（OpenRouter、Anthropic、OpenAI、Google、DeepSeek、xAI、本地模型以及其他 20 多家提供商），可在 Linux、macOS、Windows 和 WSL 上运行。

Hermes 的独特之处：

- **通过技能持续自我改进** —— Hermes 会将可复用的操作流程保存为技能，并在未来会话中加载，从经验中不断学习。
- **跨会话持久记忆** —— 记住你的身份、偏好、环境详情和经验教训，并支持可插拔的记忆后端。
- **多平台网关** —— 同一个智能体可在 Telegram、Discord、Slack、WhatsApp、iMessage、Signal、Matrix、Teams、Email 以及十余个平台上运行，并拥有完整的工具访问能力，而不只是聊天。
- **多种交互界面** —— 同一套智能体核心驱动 CLI、Ink TUI、原生 Electron 桌面应用、Web 仪表盘，以及供 IDE（VS Code / Zed / JetBrains）使用的 ACP server。
- **不绑定提供商** —— 可在工作流进行期间切换模型和提供商；凭据池还能自动轮换多个 API key。
- **配置档案** —— 可运行多个彼此独立的 Hermes 实例，各自拥有隔离的配置、会话、技能和记忆。
- **可扩展、可定制主题** —— 支持插件、MCP servers、自定义工具、webhook 触发器、cron 调度、可统一定制所有界面的皮肤、桌面 UI 插件、TUI widgets 和宠物吉祥物。

**本技能是一个导航中心。** 正文涵盖身份定位、快速上手、实例生成/编排以及严格不变量。其他内容均位于参考文件中——**回答前请加载下方与任务匹配的参考文件**；不要仅依据正文回答细节问题。

**文档：** https://hermes-agent.nousresearch.com/docs/

## 范围与验证

本技能是一份精简的操作指南，并非所有 Hermes 功能的完整事实来源。如果某项 Hermes 功能、命令或设置未在此处或参考文件中提及，不要据此认定它不存在。给出否定回答前，请检查实时仓库和官方文档。

适合用于验证的信息来源：

- CLI 命令：`hermes --help`、`hermes <command> --help` 和 `hermes_cli/main.py`
- 用户文档：https://hermes-agent.nousresearch.com/docs/
- 源代码树：https://github.com/NousResearch/hermes-agent

## 快速上手

```bash
# Install (shell installer — sets up uv, Python, the venv, and the launcher)
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash

# Interactive chat (default surface; set display.interface: tui to launch the Ink TUI instead)
hermes

# Single query
hermes chat -q "What is the capital of France?"

# Setup wizard  /  pick model+provider  /  health check
hermes setup
hermes model
hermes doctor

# Other surfaces
hermes desktop                 # launch the native desktop app (alias: hermes gui)
hermes dashboard               # web admin panel + embedded chat
hermes proxy                   # OpenAI-compatible local proxy backed by your OAuth provider
```

## 关键路径

```
~/.hermes/config.yaml       Main configuration (settings — never secrets)
~/.hermes/.env              API keys and secrets ONLY (under $HERMES_HOME if set)
$HERMES_HOME/skills/        Installed skills
~/.hermes/skins/            Custom themes (see references/themes.md)
~/.hermes/desktop-plugins/  Desktop app UI plugins (see references/desktop-plugins.md)
~/.hermes/tui-widgets/      TUI widget apps (see references/tui-widgets.md)
~/.hermes/pets/             Installed pet mascots (see references/petdex.md)
~/.hermes/state.db          Canonical session store (SQLite + FTS5)
~/.hermes/sessions/         Gateway routing index, request dumps, *.jsonl transcripts
~/.hermes/logs/             Gateway and error logs
~/.hermes/auth.json         OAuth tokens and credential pools
~/.hermes/hermes-agent/     Source code (if git-installed)
```

配置档案使用相同目录结构，位于 `~/.hermes/profiles/<name>/`。启用配置档案后，应通过 `$HERMES_HOME` 解析真实主目录——切勿硬编码 `~/.hermes`。

## 路由表——根据任务加载对应参考文件

| 用户想要…… | 加载 |
|---|---|
| CLI 命令、子命令、flags、“如何运行 X” | `references/cli-reference.md` |
| 会话内 slash commands | `references/slash-commands.md` |
| 提供商设置、API keys、OAuth | `references/providers-and-models.md` |
| config.yaml 各部分、toolsets、voice/STT/TTS | `references/configuration.md` |
| AGENTS.md / .hermes.md / CLAUDE.md 项目规则 | `references/project-context-files.md` |
| 密钥脱敏、PII、审批模式、“重置权限” | `references/security-privacy.md` |
| Delegation、cron、curator、kanban | `references/background-systems.md` |
| MCP servers（添加、目录、`hermes mcp`） | `references/native-mcp.md` |
| Webhook 路由与事件驱动运行 | `references/webhooks.md` |
| 自定义主题/皮肤（“synthwave theme”“更改金色 ●”） | `references/themes.md` + `templates/skin.yaml` |
| 桌面应用 UI 元素（pane、widget、⌘K command、page） | `references/desktop-plugins.md` + `templates/plugin.js` |
| 实时 TUI panel 或 modal widget（ticker、clock、dashboard） | `references/tui-widgets.md` + `templates/clock.mjs` |
| 宠物吉祥物——安装、选择、缩放、诊断 | `references/petdex.md` |
| Windows 特有问题（keybinds、WinError 10106、BOM） | `references/windows-quirks.md` |
| 调试：语音、工具缺失、网关、辅助模型 | `references/troubleshooting.md` |
| 贡献代码：添加工具、slash commands、测试 | `references/contributor-guide.md` |
| delegate_task“上限为 N”的报告 | `references/delegate-task-concurrency-diagnosis.md` |
| “应用 X 能否使用我的 Nous Portal 订阅/OAuth？” | `references/portal-auth-for-third-party-apps.md` |

即使没有加载参考文件，也必须遵守两条主题规则：**皮肤要由你亲自应用**（`hermes config set display.skin <name>`——所有界面会在约一秒内实时重新绘制；不要让用户自行运行 `/skin`）；而且**如需微调某一种颜色，应编辑当前启用的皮肤**（`hermes skin set <key> <hex>`）——绝不要派生 `default`，否则会丢失调色板并重置背景。

## 生成额外的 Hermes 实例

将额外的 Hermes 进程作为完全独立的子进程运行——它们各自拥有独立的会话、工具和环境。

### 何时使用此方式，何时使用 delegate_task

| | `delegate_task` | 生成 `hermes` 进程 |
|-|-----------------|--------------------------|
| 隔离性 | 对话独立，进程共享 | 进程完全独立 |
| 持续时间 | 数分钟（受父循环限制） | 数小时/数天 |
| 工具访问 | 父智能体工具的子集 | 完整工具访问 |
| 交互式 | 否 | 是（PTY mode） |
| 使用场景 | 快速并行子任务 | 长时间自主任务 |

### 单次运行模式

```
terminal(command="hermes chat -q 'Research GRPO papers and write summary to ~/research/grpo.md'", timeout=300)

# Background for long tasks:
terminal(command="hermes chat -q 'Set up CI/CD for ~/myapp'", background=true)
```

### 交互式 PTY 模式（通过 tmux）

Hermes 使用 prompt_toolkit，因此需要真正的终端。若要以交互方式生成实例，请使用 tmux：

```
# Start
terminal(command="tmux new-session -d -s agent1 -x 120 -y 40 'hermes'", timeout=10)

# Wait for startup, then send a message
terminal(command="sleep 8 && tmux send-keys -t agent1 'Build a FastAPI auth service' Enter", timeout=15)

# Read output
terminal(command="sleep 20 && tmux capture-pane -t agent1 -p", timeout=5)

# Send follow-up
terminal(command="tmux send-keys -t agent1 'Add rate limiting middleware' Enter", timeout=5)

# Exit
terminal(command="tmux send-keys -t agent1 '/exit' Enter && sleep 2 && tmux kill-session -t agent1", timeout=10)
```

### 多智能体协作

```
# Agent A: backend
terminal(command="tmux new-session -d -s backend -x 120 -y 40 'hermes -w'", timeout=10)
terminal(command="sleep 8 && tmux send-keys -t backend 'Build REST API for user management' Enter", timeout=15)

# Agent B: frontend
terminal(command="tmux new-session -d -s frontend -x 120 -y 40 'hermes -w'", timeout=10)
terminal(command="sleep 8 && tmux send-keys -t frontend 'Build React dashboard for user management' Enter", timeout=15)

# Check progress, relay context between them
terminal(command="tmux capture-pane -t backend -p | tail -30", timeout=5)
terminal(command="tmux send-keys -t frontend 'Here is the API schema from the backend agent: ...' Enter", timeout=5)
```

### 恢复会话

```
# Resume most recent session
terminal(command="tmux new-session -d -s resumed 'hermes --continue'", timeout=10)

# Resume specific session
terminal(command="tmux new-session -d -s resumed 'hermes --resume 20260225_143052_a1b2c3'", timeout=10)
```

### 提示

- **快速子任务优先使用 `delegate_task`** —— 相比生成完整进程，开销更小
- **生成会编辑代码的智能体时使用 `-w` (worktree mode)** —— 可避免 git 冲突
- **为单次运行模式设置超时** —— 复杂任务可能需要 5–10 分钟
- **使用 `hermes chat -q` 执行无需跟进的任务** —— 不需要 PTY
- **交互式会话使用 tmux** —— 原始 PTY 模式下 prompt_toolkit 会遇到 `\r` 与 `\n` 的问题
- **对于计划任务**，应使用 `cronjob` 工具而不是生成进程——该工具会处理投递和重试
- **关于“delegate_task 上限为 N”的报告** —— 请参阅 `references/delegate-task-concurrency-diagnosis.md`。Hermes 中确实存在三种触发上限的路径；如果都未触发，则是模型在自我限制，并将其合理化为“运行时限制”。
- **“$external_app 能否使用我的 Nous Portal 订阅/OAuth？”** —— 请参阅 `references/portal-auth-for-third-party-apps.md`。引导用户逐层理解三个方面（plugin-vs-app、Portal 实际暴露的内容、local-broker-proxy 方案）。

## 交互界面（快速了解）

- **桌面应用**（`hermes desktop` / `hermes gui`）——适用于 macOS/Linux/Windows 的原生 Electron 应用：支持流式聊天、会话列表、Cmd+K palette、拖放文件、原生通知，以及每个配置档案独立的远程网关登录。可通过 UI 插件扩展——参阅 `references/desktop-plugins.md`。
- **Web 仪表盘**（`hermes dashboard`）——完整的管理面板：包括消息渠道、MCP 目录、webhooks、记忆、配置档案构建器，以及内嵌的 `hermes --tui` 聊天。通过 OAuth/token 门禁保护。
- **Ink TUI**（`hermes --tui` 或 `display.interface: tui`）——带有停靠式 widget apps 的终端 UI——参阅 `references/tui-widgets.md`。
- **OpenAI-compatible proxy**（`hermes proxy`）——由你当前登录的 OAuth provider 支持的本地 OpenAI API。可将 Codex CLI、Aider、Cline 或任意脚本连接到它——无需 API key。

## 严格不变量（无论加载了什么内容，都绝不能违反）

- **绝不能破坏 prompt caching** —— 不要在对话进行期间更改既有上下文、toolsets 或 system prompt。唯一例外是上下文压缩。
- **消息角色必须交替** —— 绝不能连续出现两条 assistant 消息或两条 user 消息；只有 `tool` 结果可以连续出现。
- **密钥放在 `.env`，设置放在 `config.yaml`** —— 绝不能让用户把非凭据设置放进 `.env`。
- **路径必须兼容配置档案** —— 代码中使用 `get_hermes_home()`，在会话中解析路径时使用 `$HERMES_HOME`。
- **绝不能替用户手动编辑 `config.yaml`** —— 应使用 `hermes config set KEY VAL`；一个错误缩进就可能损坏文件并导致实时网关中断。
