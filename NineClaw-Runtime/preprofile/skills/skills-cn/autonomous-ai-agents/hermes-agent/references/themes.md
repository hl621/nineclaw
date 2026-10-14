# Themes / Skins——创作 Hermes 配色主题

创作一个 Hermes **skin**——用一个 YAML 文件同时为 CLI、TUI 和
桌面 GUI 设置主题。Skin engine（`hermes_cli/skin_engine.py`）会解析
当前 skin，gateway 再将其推送到所有界面，因此放入
`~/.hermes/skins/` 的文件就是主题版的 plugin：无需代码，覆盖所有界面。本
skill 介绍如何编写优秀的 skin 并将其激活；不涉及构建 GUI theme
editor，也不提供内置 preset。

## 适用场景

- 用户希望为 Hermes 本身定制外观（“给我做个 synthwave theme”“深色森林
  氛围”“匹配我的品牌色”）。
- 用户希望 CLI/TUI/desktop 共用一套协调一致的 palette。
- 用户希望实时迭代（“这个 coral 太抢眼了，换成 teal”）——编辑
  当前 skin 的 YAML，你的工具操作一结束，所有界面都会重新绘制。

## 前提条件

- 对 Hermes home dir 拥有写权限——默认为 `~/.hermes`，也可能是 `$HERMES_HOME`
  / 当前 profile 的目录。Skin 位于 `<hermes-home>/skins/`。
- 原生工具：`write_file`（创建 YAML）、`read_file` / `search_files`
  （查看现有 skin）、`terminal`（通过 `hermes config set` 激活）。

## 运行方法

1. 选择仅含小写字母、可安全用于 hyphen 的 `name`（例如 `synthwave`）。
2. 复制 `templates/skin.yaml` 并填入 palette（保留每一个 key——缺失的
   key 会继承 `default` skin）。
3. 使用 `write_file` 将其写入 `<hermes-home>/skins/<name>.yaml`。
4. 将其激活（参见操作流程）。确认变更已经生效。

## 快速参考——element → key

使用 Hex（`#rrggbb`）。主题采用**语义化**方式：一个 key 会为扮演同一角色的所有 element 着色，
所以请让 element 与其 key 对应。若要只改变某个特定 element 的颜色，请设置其所在行的
key（未设置时，element-specific key 会回退到共享 key）。

| 可见 element | 要设置的 Key | 回退到 |
|---|---|---|
| 应用背景（整个 TUI + GUI） | `background` | terminal 默认值 |
| **工具调用 marker**（`●`、tool spinner） | `ui_tool` | `ui_accent` |
| **思考 / reasoning 文本** | `ui_thinking` | `banner_dim` |
| Accent——heading、link、chevron、`Σ` | `ui_accent` / `banner_accent` | — |
| Heading / primary text | `banner_title` / `ui_primary` | — |
| Body / label text、user message | `ui_text` / `banner_text`, `ui_label` | — |
| Muted / secondary、tree connector | `banner_dim` | — |
| Border、rule、gutter | `ui_border` / `banner_border` | — |
| Prompt symbol 颜色 | `prompt` | `banner_text` |
| Success / warn / error | `ui_ok` / `ui_warn` / `ui_error` | — |
| Status bar 文本 + usage | `status_bar_text`, `status_bar_good/warn/bad/critical` | — |
| Diff add/remove（line + word） | `diff_added` / `diff_removed` / `diff_added_word` / `diff_removed_word` | 内置值 |
| Code syntax（string/number/keyword/comment） | `syntax_string` / `syntax_number` / `syntax_keyword` / `syntax_comment` | accent/text/border/muted |
| Completion menu | `completion_menu_bg` / `completion_menu_current_bg` / `…_meta_bg` | — |

请注意共享关系：`ui_accent` 会同时为 tool marker **以及** heading/link/chevron 着色，
因此，若只想为工具调用重新着色（经典需求“改变金色 `●`”），请设置 `ui_tool`。
`branding`（`agent_name`、`prompt_symbol`、`welcome`、`goodbye`、`help_header`）、
`spinner` 和 `tool_prefix` 是可选的个性化配置；完整 schema 位于
`hermes_cli/skin_engine.py`。

## 操作流程

1. **设计 palette。**先选择 `background`，然后选择一个相对它满足
   WCAG AA（约 4.5:1）的 `ui_accent`，确保 label 清晰可读——GUI 会强制要求
   contrast，但低 contrast 的 accent 看起来仍会发灰。让
   `ui_ok`/`ui_warn`/`ui_error` 保持为一眼可辨的绿色/琥珀色/红色。
2. **写入文件**到 `<hermes-home>/skins/<name>.yaml`。Template 中的每个顶层
   `colors` key 都应存在。
3. **由你亲自应用——绝不要手动编辑 `config.yaml`。**通过
   `terminal` 运行安全 writer：
   ```
   hermes config set display.skin <name>
   ```
   Gateway 的 skin watcher 会发现变更，并在**约一秒内实时重新绘制所有界面**
   ——CLI、TUI 和 desktop——该 skin 也会出现在
   Appearance / `Cmd-K` / `/skin` 中。应由你应用它；不要让用户去运行
   `/skin`（他们当然仍可这样做，但应用 skin 是你的工作）。Writer 会生成有效 YAML——
   手动编辑可能破坏文件并导致实时 gateway（包括 `/`）失效。
4. **确认新外观已生效**，并告诉用户如何还原：运行
   `hermes config set display.skin default`（也可以使用 `/skin default`）。

## 微调当前外观（只改变一项）

当用户希望调整当前外观时（“把工具 `●` 变成 cyan”“背景再暖一点”），请使用唯一且确定的命令——
它会原位编辑当前 skin 的单个 key，其他一切（包括 background）都不受影响：

```
hermes skin set <key> <hex>      # e.g. hermes skin set ui_tool "#00FFFF"
```

该命令会编辑当前 skin 的文件（内置 skin 会被 fork 为保留完整 palette 的可编辑副本），
watcher 会实时重绘，其他任何内容都不会变化。进行微调时，
绝不要基于 `default` 手写新 skin——那会丢弃当前 palette 并重置 background。
`hermes skin set background "#08201f"` 只改变 background；
`hermes skin use <name>` / `hermes skin list` 分别用于切换和列举。

## 易踩坑点

- 当前 profile 激活时，**不要硬编码 `~/.hermes`**——先从 `$HERMES_HOME` 解析真实 home，
  未设置时再回退到 `~/.hermes`。
- **坚持使用 `#rrggbb` hex。**不保证所有界面都能解析简写 `#rgb`、`rgb()` 和命名颜色。
- **设置 `background`。**如果不设置，GUI 只能根据文本
  luminance 猜测基础 surface——虽然可用，但你会失去对应用背景的控制。
- **名称冲突**：与 desktop 内置项同名的 skin（`mono`、`slate`、
  `cyberpunk`、`nous`、`midnight`、`ember`）无法在 GUI 中覆盖该内置项。
  请选择一个新名称。
- **绝不要手动编辑 `config.yaml` 来激活。**使用 `hermes config set
  display.skin <name>`——手动编辑时一个多余的 indent 就会损坏文件，
  并可能让实时 gateway（包括 `/`）失效。始终只需一条命令，并保证有效。
- **由你应用，不要让用户代劳。**`hermes config set display.skin <name>`
  已经足够——gateway watcher 会在约一秒内重绘所有界面。不要推给用户“自己输入 /skin”；
  那是旧的行为方式。
- **要改变一种颜色，就编辑当前 skin——绝不要 fork `default`。**为微调而 fork
  `default` 会丢弃当前 palette：没有 `background` 的 skin 会把 terminal 重置为其自身默认值
  （通常是黑色）。原位 patch 当前 skin 文件，才能保留 `background` 和其他所有设置。

## 验证

- 使用 `read_file` 读取已写入的 `<hermes-home>/skins/<name>.yaml`，确认其为有效
  YAML，并包含预期的 `name` 和 `colors`。
- 运行 `hermes config get display.skin`，确认报告结果为 `<name>`。
- 本轮结束时重绘便会完成——请用户确认新外观。
