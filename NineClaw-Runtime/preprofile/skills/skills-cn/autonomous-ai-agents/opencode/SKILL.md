---
name: opencode
description: "将编码任务委派给 OpenCode CLI（功能开发、PR 审查）。"
version: 1.2.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Coding-Agent, OpenCode, Autonomous, Refactoring, Code-Review]
    related_skills: [claude-code, codex, hermes-agent]
---

# OpenCode CLI

将 [OpenCode](https://opencode.ai) 作为由 Hermes terminal/process 工具编排的自主编码工作进程使用。OpenCode 是一个不依赖特定提供商的开源 AI 编码智能体，提供 TUI 和 CLI。

## 何时使用

- 用户明确要求使用 OpenCode
- 你希望让外部编码智能体实现、重构或审查代码
- 你需要可检查进度的长时间编码会话
- 你希望在相互隔离的工作目录或 worktree 中并行执行任务

## 前置条件

- 已安装 OpenCode：`npm i -g opencode-ai@latest` 或 `brew install anomalyco/tap/opencode`
- 已配置身份验证：`opencode auth login`，或设置提供商环境变量（OPENROUTER_API_KEY 等）
- 验证：`opencode auth list` 应显示至少一个提供商
- 用于编码任务的 Git 仓库（推荐）
- 交互式 TUI 会话需要 `pty=true`

## 可执行文件定位（重要）

不同的 shell 环境可能会解析到不同的 OpenCode 二进制文件。如果你的终端与 Hermes 中的行为不一致，请检查：

```
terminal(command="which -a opencode")
terminal(command="opencode --version")
```

如有需要，请固定使用明确的二进制文件路径：

```
terminal(command="$HOME/.opencode/bin/opencode run '...'", workdir="~/project", pty=true)
```

## 一次性任务

对于范围明确、非交互式的任务，使用 `opencode run`：

```
terminal(command="opencode run 'Add retry logic to API calls and update tests'", workdir="~/project")
```

使用 `-f` 附加上下文文件：

```
terminal(command="opencode run 'Review this config for security issues' -f config.yaml -f .env.example", workdir="~/project")
```

使用 `--thinking` 显示模型的思考过程：

```
terminal(command="opencode run 'Debug why tests fail in CI' --thinking", workdir="~/project")
```

强制使用指定模型：

```
terminal(command="opencode run 'Refactor auth module' --model openrouter/anthropic/claude-sonnet-4", workdir="~/project")
```

## 交互式会话（后台）

对于需要多轮交互的迭代工作，请在后台启动 TUI：

```
terminal(command="opencode", workdir="~/project", background=true, pty=true)
# Returns session_id

# Send a prompt
process(action="submit", session_id="<id>", data="Implement OAuth refresh flow and add tests")

# Monitor progress
process(action="poll", session_id="<id>")
process(action="log", session_id="<id>")

# Send follow-up input
process(action="submit", session_id="<id>", data="Now add error handling for token expiry")

# Exit cleanly — Ctrl+C
process(action="write", session_id="<id>", data="\x03")
# Or just kill the process
process(action="kill", session_id="<id>")
```

**重要：** 不要使用 `/exit`——它不是有效的 OpenCode 命令，反而会打开智能体选择器对话框。请使用 Ctrl+C（`\x03`）或 `process(action="kill")` 退出。

### TUI 快捷键

| 按键 | 操作 |
|-----|--------|
| `Enter` | 提交消息（如有需要，请按两次） |
| `Tab` | 在智能体（build/plan）之间切换 |
| `Ctrl+P` | 打开命令面板 |
| `Ctrl+X L` | 切换会话 |
| `Ctrl+X M` | 切换模型 |
| `Ctrl+X N` | 新建会话 |
| `Ctrl+X E` | 打开编辑器 |
| `Ctrl+C` | 退出 OpenCode |

### 恢复会话

退出后，OpenCode 会输出会话 ID。可使用以下命令恢复：

```
terminal(command="opencode -c", workdir="~/project", background=true, pty=true)  # Continue last session
terminal(command="opencode -s ses_abc123", workdir="~/project", background=true, pty=true)  # Specific session
```

## 常用选项

| 选项 | 用途 |
|------|-----|
| `run 'prompt'` | 执行一次后退出 |
| `--continue` / `-c` | 继续上一次 OpenCode 会话 |
| `--session <id>` / `-s` | 继续指定会话 |
| `--agent <name>` | 选择 OpenCode 智能体（build 或 plan） |
| `--model provider/model` | 强制使用指定模型 |
| `--format json` | 输出机器可读的结果或事件 |
| `--file <path>` / `-f` | 将文件附加到消息中 |
| `--thinking` | 显示模型思考块 |
| `--variant <level>` | 推理强度（high、max、minimal） |
| `--title <name>` | 为会话命名 |
| `--attach <url>` | 连接到正在运行的 opencode 服务器 |

## 操作流程

1. 验证工具是否就绪：
   - `terminal(command="opencode --version")`
   - `terminal(command="opencode auth list")`
2. 对于范围明确的任务，使用 `opencode run '...'`（无需 pty）。
3. 对于迭代式任务，启动 `opencode` 并设置 `background=true, pty=true`。
4. 使用 `process(action="poll"|"log")` 监控耗时较长的任务。
5. 如果 OpenCode 请求输入，请通过 `process(action="submit", ...)` 响应。
6. 使用 `process(action="write", data="\x03")` 或 `process(action="kill")` 退出。
7. 向用户总结文件变更、测试结果和后续步骤。

## PR 审查工作流

OpenCode 内置了 PR 命令：

```
terminal(command="opencode pr 42", workdir="~/project", pty=true)
```

也可以在临时克隆中进行审查，以实现隔离：

```
terminal(command="REVIEW=$(mktemp -d) && git clone https://github.com/user/repo.git $REVIEW && cd $REVIEW && opencode run 'Review this PR vs main. Report bugs, security risks, test gaps, and style issues.' -f $(git diff origin/main --name-only | head -20 | tr '\n' ' ')", pty=true)
```

## 并行工作模式

使用独立的工作目录或 worktree 来避免冲突：

```
terminal(command="opencode run 'Fix issue #101 and commit'", workdir="/tmp/issue-101", background=true, pty=true)
terminal(command="opencode run 'Add parser regression tests and commit'", workdir="/tmp/issue-102", background=true, pty=true)
process(action="list")
```

## 会话与成本管理

列出以往会话：

```
terminal(command="opencode session list")
```

检查 token 用量和成本：

```
terminal(command="opencode stats")
terminal(command="opencode stats --days 7 --models anthropic/claude-sonnet-4")
```

## 常见陷阱

- 交互式 `opencode`（TUI）会话需要 `pty=true`。`opencode run` 命令不需要 pty。
- `/exit` 不是有效命令——它会打开智能体选择器。请使用 Ctrl+C 退出 TUI。
- PATH 不一致可能会选中错误的 OpenCode 二进制文件或模型配置。
- 如果 OpenCode 看起来卡住了，请先检查日志，再终止进程：
  - `process(action="log", session_id="<id>")`
- 避免让多个并行 OpenCode 会话共用同一个工作目录。
- 在 TUI 中，可能需要按两次 Enter 才能提交（第一次完成文本输入，第二次发送）。

## 验证

冒烟测试：

```
terminal(command="opencode run 'Respond with exactly: OPENCODE_SMOKE_OK'")
```

成功标准：
- 输出中包含 `OPENCODE_SMOKE_OK`
- 命令退出，且未出现提供商或模型错误
- 对于编码任务：预期文件已更改且测试通过

## 规则

1. 对于一次性自动化任务，优先使用 `opencode run`——它更简单，也不需要 pty。
2. 仅在需要迭代时使用交互式后台模式。
3. 始终将 OpenCode 会话限定在单个仓库或工作目录中。
4. 对于耗时较长的任务，根据 `process` 日志提供进度更新。
5. 报告具体结果（已更改的文件、测试情况、剩余风险）。
6. 使用 Ctrl+C 或 kill 退出交互式会话，绝不要使用 `/exit`。
