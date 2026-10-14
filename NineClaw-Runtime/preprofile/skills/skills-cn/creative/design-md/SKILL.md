---
name: design-md
description: 编写、验证和导出 Google 的 DESIGN.md 令牌规范文件。
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [design, design-system, tokens, ui, accessibility, wcag, tailwind, dtcg, google]
    related_skills: [popular-web-designs, claude-design, excalidraw, architecture-diagram]
---

# DESIGN.md Skill

DESIGN.md 是 Google 的开放规范（Apache-2.0，`google-labs-code/design.md`），用于向编码智能体描述视觉标识。一个文件同时包含：

- **YAML front matter** —— 机器可读的设计令牌（规范值）
- **Markdown 正文** —— 人类可读的设计依据，按规范章节组织

令牌提供精确值，正文则向智能体说明这些值存在的*原因*及其应用方式。CLI（`npx @google/design.md`）可检查结构和 WCAG 对比度、比较版本以发现回归，并导出为 Tailwind 或 W3C DTCG JSON。

## 何时使用此 Skill

- 用户要求创建 DESIGN.md 文件、设计令牌或设计系统规范
- 用户希望在多个项目或工具之间保持一致的 UI／品牌形象
- 用户粘贴了现有 DESIGN.md，并要求检查、比较、导出或扩展它
- 用户要求将样式指南转换为智能体可使用的格式
- 用户希望对其配色方案进行对比度／WCAG 无障碍验证

如果只是需要视觉灵感或布局示例，请改用 `popular-web-designs`。如果要从零设计一次性的 HTML 成品（原型、演示文稿、落地页、组件实验室），并关注其中的*流程与审美判断*，请使用 `claude-design`。本 Skill 专门用于*正式规范文件*本身。

## 文件结构

```md
---
version: alpha
name: Heritage
description: Architectural minimalism meets journalistic gravitas.
colors:
  primary: "#1A1C1E"
  secondary: "#6C7278"
  tertiary: "#B8422E"
  neutral: "#F7F5F2"
typography:
  h1:
    fontFamily: Public Sans
    fontSize: 3rem
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  body-md:
    fontFamily: Public Sans
    fontSize: 1rem
rounded:
  sm: 4px
  md: 8px
  lg: 16px
spacing:
  sm: 8px
  md: 16px
  lg: 24px
components:
  button-primary:
    backgroundColor: "{colors.tertiary}"
    textColor: "#FFFFFF"
    rounded: "{rounded.sm}"
    padding: 12px
  button-primary-hover:
    backgroundColor: "{colors.primary}"
---

## Overview

Architectural Minimalism meets Journalistic Gravitas...

## Colors

- **Primary (#1A1C1E):** Deep ink for headlines and core text.
- **Tertiary (#B8422E):** "Boston Clay" — the sole driver for interaction.

## Typography

Public Sans for everything except small all-caps labels...

## Components

`button-primary` is the only high-emphasis action on a page...
```

## 令牌类型

| 类型 | 格式 | 示例 |
|------|------|------|
| 颜色 | 任意 CSS 颜色（十六进制、`rgb()`、`oklch()`、命名颜色） | `"#1A1C1E"`、`"oklch(62% 0.18 250)"` |
| 尺寸 | 数字 + 单位（`px`、`em`、`rem`） | `48px`、`-0.02em` |
| 令牌引用 | `{path.to.token}` | `{colors.primary}` |
| 排版 | 包含 `fontFamily`、`fontSize`、`fontWeight`、`lineHeight`、`letterSpacing`、`fontFeature`、`fontVariation` 的对象 | 见上文 |

组件属性白名单为：`backgroundColor`、`textColor`、`typography`、`rounded`、`padding`、`size`、`height`、`width`。变体（hover、active、pressed）必须使用键名相关的**独立组件条目**（`button-primary-hover`），不能嵌套。

## 规范章节顺序

章节均为可选，但存在的章节应按以下顺序排列。检查器会将顺序错误的章节标记为（`section-order`，警告），也会标记重复标题。按照规范，使用方会拒绝重复标题，因此返回文件前必须修复这两类问题。

1. Overview（别名：Brand & Style）
2. Colors
3. Typography
4. Layout（别名：Layout & Spacing）
5. Elevation & Depth（别名：Elevation）
6. Shapes
7. Components
8. Do's and Don'ts

未知章节会被保留，不会报错。只要值类型有效，未知令牌名称也可接受。未知组件属性则会产生警告。

## 工作流：编写新的 DESIGN.md

1. **询问用户**（或自行推断）品牌基调、强调色和排版方向。如果用户提供了网站、图片或氛围描述，将其转换为上文所示的令牌结构。
2. 在用户的项目根目录中**编写 `DESIGN.md`**，并使用 `write_file` 写入。始终包含 `name:` 和 `colors:`；其他章节可选，但建议添加。
3. **使用令牌引用**（如 `{colors.primary}`），并将其写入 `components:` 章节；不要重复填写十六进制值，以确保调色板只有一个权威来源。
4. **执行检查**（见下文）。返回前修复所有失效引用或 WCAG 验证失败。
5. **如果用户已有项目**，还应在该文件旁生成 Tailwind 或 DTCG 导出文件（`tailwind.theme.json`、`tokens.json`）。

## 工作流：检查／比较／导出

CLI 为 `@google/design.md`（Node）。使用 `npx`，无需全局安装。

```bash
# Validate structure + token references + WCAG contrast
npx -y @google/design.md lint DESIGN.md

# Compare two versions, fail on regression (exit 1 = regression)
npx -y @google/design.md diff DESIGN.md DESIGN-v2.md

# Export to Tailwind v3 theme JSON (`tailwind` is a back-compat alias)
npx -y @google/design.md export --format json-tailwind DESIGN.md > tailwind.theme.json

# Export to a Tailwind v4 CSS @theme block (--color-*, --text-*, --radius-*, ...)
npx -y @google/design.md export --format css-tailwind DESIGN.md > theme.css

# Export to W3C DTCG (Design Tokens Format Module) JSON
npx -y @google/design.md export --format dtcg DESIGN.md > tokens.json

# Print the spec itself — useful when injecting into an agent prompt
npx -y @google/design.md spec --rules-only --format json
```

所有命令都接受 `-` 作为标准输入。`lint` 遇到错误时返回退出码 1（仅有警告时返回 0）。无论源文件中的检查结果如何，只要导出成功，`export` 就会返回 0；若要以检查结果作为通过条件，请单独运行 `lint`。输出默认为 JSON；如需以结构化方式报告检查结果，可解析该输出。

在 Windows 上，`design.md` 可执行文件名可能与 `.md` 文件关联发生冲突（表现为静默无操作，或文件在编辑器中打开）。请使用不含点号的别名：`npx -y -p @google/design.md designmd lint DESIGN.md`。

### 检查规则参考（截至 CLI 0.3.0 共 9 条规则）

- `broken-ref`（错误）—— `{colors.missing}` 指向不存在的令牌
- `contrast-ratio`（警告）—— 组件的 `textColor` 与 `backgroundColor` 对比度低于 WCAG AA（4.5:1）
- `missing-primary`（警告）—— 已定义颜色，但没有 `primary` 令牌
- `missing-typography`（警告）—— 已定义颜色，但没有排版令牌
- `orphaned-tokens`（警告）—— 从未被组件引用的颜色令牌
- `section-order`（警告）—— 章节未按规范顺序排列
- `unknown-key`（警告）—— 顶层 YAML 键看起来像规范键的拼写错误（`colours:` → `colors:`）；自定义扩展键不会触发警告
- `token-summary`、`missing-sections`（信息）—— 令牌数量及缺少的可选章节

如果用户重视无障碍性，请在总结中明确说明相关结果——WCAG 检查结果是使用该 CLI 最关键的理由。

## 常见陷阱

- **不要嵌套组件变体。** `button-primary.hover` 是错误写法；正确做法是将 `button-primary-hover` 作为同级键。
- **十六进制颜色必须使用带引号的字符串。** 否则 YAML 会因 `#` 解析失败，或以异常方式截断 `#1A1C1E` 等值。
- **负尺寸也需要引号。** `letterSpacing: -0.02em` 会被解析为 YAML 流；应写为 `letterSpacing: "-0.02em"`。
- **即便检查器只发出警告，章节顺序仍然很重要。** 如果用户提供的正文顺序杂乱，应在保存前按规范列表重新排序，因为符合规范的使用方会依赖该顺序。
- **排版子属性的拼写错误会被静默丢弃。** 截至 CLI 0.3.0，`fontwight:` 这样的拼写错误不会产生检查结果，且其值会从导出内容中消失；务必依据 schema 复核子属性名称（`fontFamily`、`fontSize`、`fontWeight`、`lineHeight`、`letterSpacing`、`fontFeature`、`fontVariation`）。
- **`version: alpha` 是当前规范版本**（截至 2026 年 7 月，CLI 0.3.0）。该规范仍标记为 alpha，请留意破坏性变更。
- **令牌引用按点分隔路径解析。** `{colors.primary}` 有效；`{primary}` 无效。

## 规范的权威来源

- 仓库：https://github.com/google-labs-code/design.md （Apache-2.0）
- CLI：npm 上的 `@google/design.md`
- 生成的 DESIGN.md 文件采用用户项目所使用的许可证；规范本身采用 Apache-2.0。
