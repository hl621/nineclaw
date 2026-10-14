# 项目 Context 文件

Hermes 会读取 working directory 中的 context 文件，将项目级指令注入 system prompt。发现顺序采用**第一个匹配项优先**——每个会话只加载一个项目 context 来源。

| 文件（按优先级排序） | 发现方式 | 适用场景 |
|---|---|---|
| `.hermes.md` / `HERMES.md` | 向上遍历 parent，直至 git root，并在 git root 停止 | 需要分层项目规则（root + 每个 package 的 override） |
| `AGENTS.md` / `agents.md` | **仅 Cwd**——忽略 subdirectory 和 parent 中的副本 | 需要能以相同方式用于 Hermes、Claude Code、Codex 等工具的便携 agent 指令 |
| `CLAUDE.md` / `claude.md` | 仅 Cwd | 与 AGENTS.md 相同，但带有 Claude 风格 |
| `.cursorrules` / `.cursor/rules/*.mdc` | 仅 Cwd | 从 Cursor 迁移 |

`SOUL.md`（位于 `$HERMES_HOME`）是相互独立的，只要存在就始终加载——它设置 agent identity，而不是项目规则。

### 选择合适的文件

- 当你需要位于 cwd 上层（root + subtree）的 Hermes 特有行为，或希望规则从 parent directory 继承时，**使用 `.hermes.md`**。向上遍历会在 git root 停止，因此 home 级 `.hermes.md` 不会泄漏到每个项目中（git repo 的 root 就是边界）。
- 当同一项目也会由其他 agent（Codex、Claude Code、OpenCode）处理时，**使用 `AGENTS.md`**。这些工具对 `AGENTS.md` 各有约定，而“仅 cwd”的 contract 可让该文件保持便携。
- **不要把项目规则放入 `~/.hermes/AGENTS.md`**（或任何其他 home 级位置）。当 Hermes 以该目录作为 cwd 运行时，这个文件确实会加载——但只对那一个目录生效。若要提供跨项目 context，请使用 `SOUL.md`（位于 `$HERMES_HOME`，仅限 identity），或通过 `hermes skills install` 安装 skill。

### 大小与截断

每个 context 文件上限为 20,000 个字符。超过该长度的文件会按 **head + tail** 方式截断（丢弃中间部分，并插入 `[...truncated...]` marker）。对于大型项目规则，优先拆成多个 skill，不要全塞进一个文件。

### 安全

所有 context 文件在进入 system prompt 前都会经过 threat-pattern scanner。匹配 prompt injection 或 promptware 的 pattern 会替换为 `[BLOCKED: ...]` placeholder。这意味着，包含明显 injection attempt 的 `AGENTS.md` 不会把这些内容传给 model——scanner 阻止的是相关内容，而不是整个文件，因此文件其余部分仍会加载。

### 对单个会话禁用

`hermes --ignore-rules` 会跳过所有项目 context 文件（`.hermes.md`、`AGENTS.md`、`CLAUDE.md`、`.cursorrules`）**以及** `SOUL.md` identity 的自动注入，同时也会跳过 user config、plugin 和 MCP server。可用它来隔离问题究竟来自你的设置还是 Hermes 本身。

### 示例：一个简短的 `.hermes.md`

```markdown
# My Project

Hermes: when working in this repo, follow these rules.

## Build
- Always run `make test` before declaring a change done.
- Use `uv run` for Python, not `pip install`.

## Style
- Prefer `pathlib.Path` over `os.path`.
- No `print()` in production code — use the `logger`.
```

位于 `/home/me/projects/myrepo/.hermes.md` 的该文件，会在 Hermes 于 `/home/me/projects/myrepo` 的任意 subdirectory 中运行时自动加载；在 `/home/me/other-project` 中运行时则不会加载。
