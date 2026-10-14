# Petdex——动态 Pet Mascot

从公开的 [petdex](https://github.com/crafter-station/petdex) gallery 浏览、安装和选择动态“pet” mascot。已安装的 pet
会在 Hermes CLI、TUI 和桌面应用中响应 agent 的活动状态（idle、运行工具、reviewing、error、done）。
本 skill 操作 `hermes pets` CLI 和 `display.pet` config——不负责生成 sprite。

## 适用场景

- 用户想要 desktop/terminal mascot，或询问“pets”/ petdex。
- 用户希望更改、预览或禁用当前 pet。
- 诊断 pet 不显示的原因（terminal graphics 支持、config）。

## 前提条件

- 能够通过网络访问 `petdex.dev` 以获取 gallery/manifest（只读，无需 auth）。
- 使用 Pillow（Hermes 的 core dependency）解码 sprite——已经安装。
- 若要获得完整保真度的 terminal rendering，需要支持 graphics 的 terminal（kitty、
  Ghostty、WezTerm、iTerm2 或 sixel）。否则会自动使用 truecolor Unicode
  half-block fallback。

## 运行方法

使用 `terminal` 工具运行 `hermes pets <subcommand>`。

## 快速参考

| 目标 | Command |
| --- | --- |
| 浏览 gallery | `hermes pets list`（添加 substring 进行筛选：`hermes pets list cat`） |
| 列出已安装的 pet | `hermes pets list --installed` |
| 安装 pet | `hermes pets install <slug>`（添加 `--select` 可将其设为当前 pet） |
| 设置当前 pet | `hermes pets select <slug>`（省略 slug 会打开 picker） |
| 在所有界面调整 pet 大小 | `hermes pets scale <factor>`（例如 `0.5`，限制在 0.1–3.0） |
| 在 terminal 中预览/播放动画 | `hermes pets show [slug] [--cycle] [--state run]` |
| 禁用 pet | `hermes pets off` |
| 移除 pet | `hermes pets remove <slug>` |
| 诊断设置 | `hermes pets doctor` |

## 操作流程

1. 查找 pet：运行 `hermes pets list <query>` 并记下它的 `slug`。
2. 安装并激活：`hermes pets install <slug> --select`。
3. 预览：`hermes pets show`（按 Ctrl+C 停止）。
4. 确认设置：`hermes pets doctor`——会显示解析后的 pet、已配置的
   render mode、检测到的 terminal graphics protocol 和实际生效的 mode。

Pet 会安装到 `<HERMES_HOME>/pets/<slug>/`（支持 profile）。选择 pet
会把 `display.pet.slug` + `display.pet.enabled` 写入 `config.yaml`。

## 配置

在 `display.pet` 下进行配置，该项位于 `config.yaml` 中：

- `enabled` (bool)——总开关。
- `slug` (str)——当前 pet；留空 = 第一个已安装的 pet。
- `render_mode`——`auto`（检测）| `kitty` | `iterm` | `sixel` | `unicode` | `off`。
- `scale` (float)——原生 192×208 frame 的屏幕显示大小（默认 0.33，
  限制在 0.1–3.0）。一个 knob 即可调整所有界面的大小；可通过
  `hermes pets scale <factor>`、`/pet scale` slash command 或 desktop
  Appearance slider 设置。
- `unicode_cols` (int)——Unicode fallback 的 column 宽度。

## 易踩坑点

- 只有安装并选择 pet（`enabled: true`）后，它才会显示。
- 在 pipe/redirect 内（无 TTY）时，terminal rendering 会按设计禁用。
- petdex npm CLI 会安装到 `~/.codex/pets`；Hermes 使用自己按 profile 隔离的
  `<HERMES_HOME>/pets/`——请通过 `hermes pets` 安装。

## 验证

- 安装并选择 pet、启用 pet 且能够 import Pillow 后，`hermes pets doctor` 会报告 `✓ ready`。
