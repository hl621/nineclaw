---
name: hermes-agent-skill-authoring
description: "编写仓库内的 SKILL.md 文件：frontmatter 与结构。"
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [skills, authoring, hermes-agent, conventions, skill-md]
    related_skills: [plan, requesting-code-review]
---

# 编写 Hermes-Agent 技能（仓库内）

## 概述

SKILL.md 可以存放在两个位置：

1. **用户本地：** `~/.hermes/skills/<maybe-category>/<name>/SKILL.md` — 个人使用，不共享。通过 `skill_manage(action='create')` 创建。
2. **仓库内（本技能讨论的情形）：** `/home/bb/hermes-agent/skills/<category>/<name>/SKILL.md` — 提交到仓库，随软件包一同发布。使用 `write_file` + `git add`。`skill_manage(action='create')` **不会**以这棵目录树为目标。

## 何时使用

- 用户要求你“在此分支／仓库／提交中”添加技能
- 你要提交一个应随 hermes-agent 一同发布的可复用工作流
- 你正在编辑 `/home/bb/hermes-agent/skills/` 下的现有技能（小幅修改使用 `patch`，重写使用 `write_file`；`skill_manage` 仍可用于修补仓库内技能，但不能用于 `create`）

## 必需的 Frontmatter

权威依据：`tools/skill_manager_tool.py::_validate_frontmatter`。硬性要求：

- 文件最开始的字节必须是 `---`（前面不能有空行）。
- 正文之前以 `\n---\n` 闭合。
- 能够解析为 YAML 映射。
- 存在 `name` 字段。
- 存在 `description` 字段，且不超过 **1024 个字符**（`MAX_DESCRIPTION_LENGTH`）。
  **较长的描述在系统提示词技能索引中会被截断为前 57 个字符 + "..."**
  （`extract_skill_description`，位于 `agent/skill_utils.py`）；
  完整文本可通过 `skills_list()` 和 `skill_view()` 查看。
  把触发短语放在最前面。
- 闭合的 `---` 之后必须有非空正文。

`skills/software-development/` 下每个技能都采用的同类结构：

```yaml
---
name: my-skill-name               # lowercase, hyphens, ≤64 chars (MAX_NAME_LENGTH)
description: Use when <trigger>. <one-line behavior>.   # first 57 chars shown in system prompt
version: 1.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [short, descriptive, tags]
    related_skills: [other-skill, another-skill]
---
```

验证器**不会**强制要求 `version` / `author` / `license` / `metadata`，但同类技能无一例外都包含这些字段——省略它们会让你的技能显得格格不入。

## 大小限制

- 描述：不超过 1024 个字符（强制执行）。**较长的描述在系统提示词技能索引中仅显示前 57 个字符
  加 "..."；**其余内容可通过 `skills_list()`
  和 `skill_view()` 查看。
- 完整 SKILL.md：不超过 100,000 个字符（通过 `MAX_SKILL_CONTENT_CHARS` 强制执行，约 36k token）。
- `software-development/` 中的同类技能通常为 **8–14k 个字符**。应以此范围为目标。如果快要超过 20k，请拆分到 `references/*.md`，并在 SKILL.md 中引用。

## 写作质量原则

技能的存在是为了让智能体的流程更加可预测。可预测**并不**意味着每次运行都产生相同输出；而是意味着智能体能可靠地遵循同一套有用的规范。

编写或编辑任何技能时，请采用以下质量检查：

1. **针对流程可预测性进行优化。** 问自己：加载此技能后，哪些行为应该改变？如果某一行不会改变行为，就删掉它。
2. **选择恰当的上下文负载。** 由模型调用的 Hermes 技能每一轮都要为其描述付出上下文成本。描述应聚焦触发条件类别与技能的独特行为。细节放在正文或链接的参考资料中。
3. **采用信息层级。** 始终需要的步骤放在 `SKILL.md`；特定分支才需要或体量庞大的参考资料放在 `references/`、`templates/` 或 `scripts/`，并仅在需要时指向它们。
4. **以完成标准结束步骤。** 每个有序步骤都应说明智能体如何知道该步骤已经完成。好的标准应当可检查，并在必要时穷尽所有情形：“每个修改过的文件都有交代”优于“总结变更”。
5. **将规则与其约束的概念放在一起。** 避免把同一个想法分散到文件各处。让定义、注意事项、示例和验证彼此相邻。
6. **使用有力的引导词。** 相较于冗长、重复的解释，优先使用模型已经理解的紧凑概念，例如“紧密循环”“曳光弹”“根本原因”“回归测试”。好的引导词既节省 token，又能锚定行为。
7. **清理重复内容与无效指令。** 每一层含义只保留一个权威来源。逐句审视：与默认行为相比，这句话是否改变了智能体的行为？如果没有，就删除，而不是润色。
8. **警惕过早完成。** 如果智能体往往匆忙跳过某一步，先收紧该步骤的完成标准。只有在后续步骤会干扰当前步骤的高质量执行时，才拆分流程。

常见质量问题：

- **过早完成** — 技能允许智能体在工作真正完成前就继续下一步。
- **重复** — 同一规则出现在多处，并逐渐产生偏差。
- **陈旧内容堆积** — 因为觉得新增比删除更安全，已经失效的内容一直残留。
- **内容膨胀** — 始终加载的材料过多；应将仅特定分支需要的参考资料移入按需引用的文件。
- **无效文字** — 即使没有此技能，智能体也会遵循的泛泛建议。

## 与同类技能一致的结构

每个仓库内技能大致遵循：

```
# <Title>

## Overview
One or two paragraphs: what and why.

## When to Use
- Bulleted triggers
- "Don't use for:" counter-triggers

## <Topic sections specific to the skill>
- Quick-reference tables are common
- Code blocks with exact commands
- Hermes-specific recipes (tests via scripts/run_tests.sh, ui-tui paths, etc.)

## Common Pitfalls
Numbered list of mistakes and their fixes.

## Verification Checklist
- [ ] Checkbox list of post-action verifications

## One-Shot Recipes (optional)
Named scenarios → concrete command sequences.
```

并非每个章节都是强制的，但要让技能看起来与同类一致，至少需要 `Overview` + `When to Use` + 可执行的正文 + 常见陷阱。

## 目录位置

```
skills/<category>/<skill-name>/SKILL.md
```

仓库当前的类别（使用 `ls skills/` 确认）：`autonomous-ai-agents`、`creative`、`data-science`、`devops`、`email`、`gaming`、`github`、`leisure`、`mcp`、`media`、`mlops/*`、`note-taking`、`productivity`、`red-teaming`、`research`、`smart-home`、`social-media`、`software-development`。

选择最接近的现有类别。不要随意创造新的顶层类别。

## 工作流

1. **考察目标类别中的同类技能：**
   ```
   ls skills/<category>/
   ```
   阅读 2–3 个同类 SKILL.md 文件，以匹配其语气和结构。
2. 如有疑问，**检查验证器约束**：`tools/skill_manager_tool.py`。
3. 使用 `write_file` **起草**到 `skills/<category>/<name>/SKILL.md`。
4. **在本地验证**：
   ```python
   import yaml, re, pathlib
   content = pathlib.Path("skills/<category>/<name>/SKILL.md").read_text()
   assert content.startswith("---")
   m = re.search(r'\n---\s*\n', content[3:])
   fm = yaml.safe_load(content[3:m.start()+3])
   assert "name" in fm and "description" in fm
   assert len(fm["description"]) <= 1024
   assert len(content) <= 100_000
   ```
5. 在当前分支执行 **Git add + commit**。
6. **注意：**当前会话的技能加载器有缓存——`skill_view` / `skills_list` 在新会话开始前看不到新技能。这是预期行为，不是 bug。

## 交叉引用其他技能

加载时，`metadata.hermes.related_skills` 会合并两棵目录树（仓库内的 `skills/` 与 `~/.hermes/skills/`）。你**可以**从仓库内技能引用用户本地技能，但其他用户全新克隆仓库后无法解析该引用。仓库内技能最好只引用其他仓库内技能。如果某个经常被引用的技能仅存在于 `~/.hermes/skills/`，可以考虑将其提升到仓库中。

## 编辑现有的仓库内技能

- **小幅修正（错别字、补充陷阱、收紧触发条件）：** `skill_manage(action='patch', name=..., old_string=..., new_string=...)` 可正常用于仓库内技能。
- **重大重写：** 使用 `write_file` 写入整个 SKILL.md。`skill_manage(action='edit')` 也可用，但要求提供完整的新内容。
- **添加支持文件：** 使用 `write_file` 写入 `skills/<category>/<name>/references/<file>.md`、`templates/<file>` 或 `scripts/<file>`。`skill_manage(action='write_file')` 也可用，并会强制执行 references/templates/scripts/assets 子目录允许列表。
- **始终提交**修改——仓库内技能属于源代码，而不是运行时状态。

## 常见陷阱

1. **对仓库内技能使用 `skill_manage(action='create')`。** 它写入的是 `~/.hermes/skills/`，而非仓库目录树。创建仓库内技能应使用 `write_file`。

2. **`---` 前有空白。** 验证器检查 `content.startswith("---")`；开头存在任何空行或 BOM 都会验证失败。

3. **描述过于宽泛，或触发条件埋在第 57 个字符之后。** 系统提示词
   技能索引会在 57 个字符处截断长描述。同类技能的描述都以
   “Use when ...”开头，并在该窗口内完整表达触发条件类别。
   - 正确：`Use when debugging Hermes skill discovery failures.`
   - 错误：`This skill contains detailed guidance for agents working on Hermes skill discovery failures.`

4. **忘记 author/license/metadata 块。** 验证器不会强制要求，但同类技能全都具备；省略会让技能显得尚未完成。

5. **编写与同类技能重复的技能。** 创建前，先执行 `ls skills/<category>/` 并打开 2–3 个同类技能。相较于创建范围狭窄的同级技能，优先扩展现有技能。

6. **期待当前会话看到新技能。** 它看不到。技能加载器在会话开始时初始化。请在新会话中验证，或通过 `skill_view` 使用精确路径验证。

7. **任由技能堆积陈旧内容。** 技能应随时间推移变得更短或更精准。添加新规则时，应删除被其取代的旧表述；不要无休止地叠加建议。

8. **编写无效文字。** “要小心”“要全面”和“遵循最佳实践”很少能改变模型行为。请用可检查的完成标准或更有力的引导词替代。

9. **链接仓库内不存在的技能。** `related_skills: [some-user-local-skill]` 对你有效，但其他克隆会失效。最好只链接仓库内技能。

## 验证清单

- [ ] 文件位于 `skills/<category>/<name>/SKILL.md`（而不是 `~/.hermes/skills/`）
- [ ] Frontmatter 从字节 0 的 `---` 开始，以 `\n---\n` 闭合
- [ ] `name`、`description`、`version`、`author`、`license`、`metadata.hermes.{tags, related_skills}` 均存在
- [ ] 名称不超过 64 个字符，仅含小写字母与连字符
- [ ] 描述不超过 1024 个字符，触发短语在前 57 个字符内即可独立表达完整含义，
      并以“Use when ...”开头
- [ ] 文件总计不超过 100,000 个字符（目标为 8–15k）
- [ ] 结构：`# Title` → `## Overview` → `## When to Use` → 正文 → `## Common Pitfalls` → `## Verification Checklist`
- [ ] 每个有序步骤都有可检查的完成标准
- [ ] 描述聚焦触发条件，且不重复正文内容
- [ ] 庞大或特定分支才需要的参考资料通过链接文件渐进披露
- [ ] 已删除无效文字和重复规则
- [ ] `related_skills` 引用可在仓库内解析（或已明确允许其仅存在于用户本地）
- [ ] 已在预期分支完成 `git add skills/<category>/<name>/ && git commit`
