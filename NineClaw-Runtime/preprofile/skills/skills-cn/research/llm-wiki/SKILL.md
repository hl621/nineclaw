---
name: llm-wiki
description: "Karpathy 的 LLM Wiki：构建/查询相互链接的 Markdown 知识库。"
version: 2.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [wiki, knowledge-base, research, notes, markdown, rag-alternative]
    category: research
    related_skills: [obsidian, arxiv]
---

# Karpathy 的 LLM Wiki

以相互链接的 Markdown 文件形式，构建并维护一个持久、持续积累的知识库。
基于 [Andrej Karpathy 的 LLM Wiki 模式](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)。

传统 RAG 会针对每次查询从头重新发现知识，而 Wiki 只需编译一次知识并持续更新。
交叉引用已经建立，矛盾已经标出，综合结果会涵盖所有已摄取的内容。

**分工：** 人类负责筛选来源并指导分析；智能体负责总结、交叉引用、归档并保持一致性。

## 此 Skill 的启用场景

当用户有以下需求时，使用此 Skill：
- 要求创建、构建或启动 Wiki 或知识库
- 要求将某个来源摄取、添加或处理到其 Wiki 中
- 提出问题，且配置路径下已有 Wiki
- 要求对 Wiki 进行检查、审计或健康检查
- 在研究语境中提及其 Wiki、知识库或“笔记”

## Wiki 位置

**位置：** 通过 `WIKI_PATH` 环境变量设置（例如在 `${HERMES_HOME:-~/.hermes}/.env` 中）。

若未设置，则默认为 `~/wiki`。

```bash
WIKI="${WIKI_PATH:-$HOME/wiki}"
```

Wiki 只是一个 Markdown 文件目录——可使用 Obsidian、VS Code 或任意编辑器打开。
不需要数据库，也不需要特殊工具。

## 架构：三层结构

```
wiki/
├── SCHEMA.md           # Conventions, structure rules, domain config
├── index.md            # Sectioned content catalog with one-line summaries
├── log.md              # Chronological action log (append-only, rotated yearly)
├── raw/                # Layer 1: Immutable source material
│   ├── articles/       # Web articles, clippings
│   ├── papers/         # PDFs, arxiv papers
│   ├── transcripts/    # Meeting notes, interviews
│   └── assets/         # Images, diagrams referenced by sources
├── entities/           # Layer 2: Entity pages (people, orgs, products, models)
├── concepts/           # Layer 2: Concept/topic pages
├── comparisons/        # Layer 2: Side-by-side analyses
└── queries/            # Layer 2: Filed query results worth keeping
```

**第 1 层——原始来源：** 不可变。智能体可以读取，但绝不修改。
**第 2 层——Wiki：** 由智能体管理的 Markdown 文件，由智能体创建、更新并建立交叉引用。
**第 3 层——模式：** `SCHEMA.md` 定义结构、约定和标签分类法。

## 恢复现有 Wiki（关键——每个会话都必须执行）

当用户已有 Wiki 时，**在执行任何操作前，务必先了解其现状**：

① **读取 `SCHEMA.md`**——了解领域、约定和标签分类法。
② **读取 `index.md`**——了解现有页面及其摘要。
③ **浏览最近的 `log.md`**——读取最后 20–30 条记录，了解近期活动。

```bash
WIKI="${WIKI_PATH:-$HOME/wiki}"
# Orientation reads at session start
read_file "$WIKI/SCHEMA.md"
read_file "$WIKI/index.md"
read_file "$WIKI/log.md" offset=<last 30 lines>
```

完成上述定向了解后，才能进行摄取、查询或检查。这样可避免：
- 为已有实体创建重复页面
- 遗漏对现有内容的交叉引用
- 违反模式中定义的约定
- 重复已记录的工作

对于大型 Wiki（100 个以上页面），在创建任何新内容前，还应针对当前主题快速运行一次 `search_files`。

## 初始化新 Wiki

当用户要求创建或启动 Wiki 时：

1. 确定 Wiki 路径（从 `$WIKI_PATH` 环境变量获取，或询问用户；默认值为 `~/wiki`）
2. 创建上述目录结构
3. 询问用户该 Wiki 覆盖哪个领域——要具体明确
4. 编写针对该领域定制的 `SCHEMA.md`（参见下方模板）
5. 编写带分区标题的初始 `index.md`
6. 编写包含创建记录的初始 `log.md`
7. 确认 Wiki 已就绪，并建议首批可摄取的来源

### SCHEMA.md 模板

根据用户的领域进行调整。该模式约束智能体行为并确保一致性：

```markdown
# Wiki Schema

## Domain
[What this wiki covers — e.g., "AI/ML research", "personal health", "startup intelligence"]

## Conventions
- File names: lowercase, hyphens, no spaces (e.g., `transformer-architecture.md`)
- Every wiki page starts with YAML frontmatter (see below)
- Use `[[wikilinks]]` to link between pages (minimum 2 outbound links per page)
- When updating a page, always bump the `updated` date
- Every new page must be added to `index.md` under the correct section
- Every action must be appended to `log.md`
- **Provenance markers:** On pages that synthesize 3+ sources, append `^[raw/articles/source-file.md]`
  at the end of paragraphs whose claims come from a specific source. This lets a reader trace each
  claim back without re-reading the whole raw file. Optional on single-source pages where the
  `sources:` frontmatter is enough.

## Frontmatter
  ```yaml
  ---
  title: Page Title
  created: YYYY-MM-DD
  updated: YYYY-MM-DD
  type: entity | concept | comparison | query | summary
  tags: [from taxonomy below]
  sources: [raw/articles/source-name.md]
  # Optional quality signals:
  confidence: high | medium | low        # how well-supported the claims are
  contested: true                        # set when the page has unresolved contradictions
  contradictions: [other-page-slug]      # pages this one conflicts with
  ---
  ```

`confidence` and `contested` are optional but recommended for opinion-heavy or fast-moving
topics. Lint surfaces `contested: true` and `confidence: low` pages for review so weak claims
don't silently harden into accepted wiki fact.

### raw/ Frontmatter

Raw sources ALSO get a small frontmatter block so re-ingests can detect drift:

```yaml
---
source_url: https://example.com/article   # original URL, if applicable
ingested: YYYY-MM-DD
sha256: <hex digest of the raw content below the frontmatter>
---
```

The `sha256:` lets a future re-ingest of the same URL skip processing when content is unchanged,
and flag drift when it has changed. Compute over the body only (everything after the closing
`---`), not the frontmatter itself.

## Tag Taxonomy
[Define 10-20 top-level tags for the domain. Add new tags here BEFORE using them.]

Example for AI/ML:
- Models: model, architecture, benchmark, training
- People/Orgs: person, company, lab, open-source
- Techniques: optimization, fine-tuning, inference, alignment, data
- Meta: comparison, timeline, controversy, prediction

Rule: every tag on a page must appear in this taxonomy. If a new tag is needed,
add it here first, then use it. This prevents tag sprawl.

## Page Thresholds
- **Create a page** when an entity/concept appears in 2+ sources OR is central to one source
- **Add to existing page** when a source mentions something already covered
- **DON'T create a page** for passing mentions, minor details, or things outside the domain
- **Split a page** when it exceeds ~200 lines — break into sub-topics with cross-links
- **Archive a page** when its content is fully superseded — move to `_archive/`, remove from index

## Entity Pages
One page per notable entity. Include:
- Overview / what it is
- Key facts and dates
- Relationships to other entities ([[wikilinks]])
- Source references

## Concept Pages
One page per concept or topic. Include:
- Definition / explanation
- Current state of knowledge
- Open questions or debates
- Related concepts ([[wikilinks]])

## Comparison Pages
Side-by-side analyses. Include:
- What is being compared and why
- Dimensions of comparison (table format preferred)
- Verdict or synthesis
- Sources

## Update Policy
When new information conflicts with existing content:
1. Check the dates — newer sources generally supersede older ones
2. If genuinely contradictory, note both positions with dates and sources
3. Mark the contradiction in frontmatter: `contradictions: [page-name]`
4. Flag for user review in the lint report
```

### index.md Template

The index is sectioned by type. Each entry is one line: wikilink + summary.

```markdown
# Wiki Index

> Content catalog. Every wiki page listed under its type with a one-line summary.
> Read this first to find relevant pages for any query.
> Last updated: YYYY-MM-DD | Total pages: N

## Entities
<!-- Alphabetical within section -->

## Concepts

## Comparisons

## Queries
```

**扩展规则：** 当任一分区超过 50 个条目时，按首字母或子领域拆分为多个子分区。
当索引总计超过 200 个条目时，创建 `_meta/topic-map.md`，按主题对页面进行分组，以便更快导航。

### log.md 模板

```markdown
# Wiki Log

> Chronological record of all wiki actions. Append-only.
> Format: `## [YYYY-MM-DD] action | subject`
> Actions: ingest, update, query, lint, create, archive, delete
> When this file exceeds 500 entries, rotate: rename to log-YYYY.md, start fresh.

## [YYYY-MM-DD] create | Wiki initialized
- Domain: [domain]
- Structure created with SCHEMA.md, index.md, log.md
```

## 核心操作

### 1. 摄取

当用户提供来源（URL、文件或粘贴文本）时，将其整合到 Wiki 中：

① **捕获原始来源：**
   - URL → 使用 `web_extract` 获取 Markdown，并保存至 `raw/articles/`
   - PDF → 使用 `web_extract`（支持 PDF），并保存至 `raw/papers/`
   - 粘贴文本 → 保存至合适的 `raw/` 子目录
   - 为文件取一个描述性名称：`raw/articles/karpathy-llm-wiki-2026.md`
   - **添加原始来源的 frontmatter**（`source_url`、`ingested`、正文的 `sha256`）。
     重新摄取同一 URL 时：重新计算 sha256 并与存储值比较——若相同则跳过；若不同，则标记漂移并更新。
     这项检查成本很低，适合每次重新摄取时执行，并能捕捉来源的静默变更。

② **与用户讨论要点**——哪些内容有趣、哪些内容对该领域重要。（在自动化或 cron 场景中跳过此步骤，直接继续。）

③ **检查已有内容**——搜索 index.md，并使用 `search_files` 查找被提及实体或概念的现有页面。
   这正是持续增长的 Wiki 与一堆重复内容之间的区别。

④ **编写或更新 Wiki 页面：**
   - **新实体/概念：** 仅当其达到 SCHEMA.md 中的页面创建阈值时才创建页面（在 2 个以上来源中出现，或是某一来源的核心）
   - **现有页面：** 添加新信息、更新事实，并更新 `updated` 日期。
     当新信息与现有内容冲突时，遵循更新策略。
   - **交叉引用：** 每个新建或更新的页面必须通过 `[[wikilinks]]` 链接到至少 2 个其他页面，并检查现有页面是否反向链接。
   - **标签：** 只能使用 SCHEMA.md 分类法中已有的标签
   - **溯源：** 对综合了 3 个以上来源的页面，在其主张可追溯至特定来源的段落末尾附加 `^[raw/articles/source.md]` 标记。
   - **置信度：** 对观点性强、变化快或仅有单一来源支持的主张，在 frontmatter 中设置 `confidence: medium` 或 `low`。
     除非该主张得到多个来源的充分支持，否则不要标记为 `high`。

⑤ **更新导航：**
   - 按字母顺序将新页面添加到 `index.md` 的正确分区
   - 更新索引标题中的“Total pages”计数和“Last updated”日期
   - 向 `log.md` 追加：`## [YYYY-MM-DD] ingest | Source Title`
   - 在日志条目中列出每个已创建或更新的文件

⑥ **报告变更**——向用户列出每个已创建或更新的文件。

单个来源可能触发 5–15 个 Wiki 页面的更新。这是正常且理想的结果——正体现了知识的复利积累效应。

### 2. 查询

当用户提出与 Wiki 领域有关的问题时：

① **读取 `index.md`**，确定相关页面。
② **对于拥有 100 个以上页面的 Wiki**，还应使用 `search_files` 在所有 `.md` 文件中搜索关键词——仅靠索引可能会遗漏相关内容。
③ 使用 `read_file` **读取相关页面**。
④ 基于已编译的知识**综合回答**。引用所依据的 Wiki 页面：“基于 [[page-a]] 和 [[page-b]]……”
⑤ **将有价值的答案归档回 Wiki**——如果答案是重要的比较、深度分析或新颖综合，则在 `queries/` 或 `comparisons/` 中创建页面。
   不要归档简单查询结果——只保留那些重新推导起来代价高昂的答案。
⑥ 使用查询内容及其是否已归档的信息**更新 log.md**。

### 3. 检查

当用户要求检查、健康检查或审计 Wiki 时：

① **孤立页面：** 查找没有从其他页面接收入站 `[[wikilinks]]` 的页面。
```python
# Use execute_code for this — programmatic scan across all wiki pages
import os, re
from collections import defaultdict
wiki = "<WIKI_PATH>"
# Scan all .md files in entities/, concepts/, comparisons/, queries/
# Extract all [[wikilinks]] — build inbound link map
# Pages with zero inbound links are orphans
```

② **损坏的 Wiki 链接：** 查找指向不存在页面的 `[[links]]`。

③ **索引完整性：** 每个 Wiki 页面都应出现在 `index.md` 中。将文件系统与索引条目进行比较。

④ **Frontmatter 验证：** 每个 Wiki 页面都必须包含全部必填字段
   （title、created、updated、type、tags、sources）。所有标签都必须存在于分类法中。

⑤ **过时内容：** 页面 `updated` 日期比提及相同实体的最新来源早 90 天以上。

⑥ **矛盾：** 查找同一主题下包含冲突主张的页面。重点检查共享标签或实体但陈述不同事实的页面。
   展示所有 frontmatter 中含 `contested: true` 或 `contradictions:` 的页面，供用户审阅。

⑦ **质量信号：** 列出所有含 `confidence: low` 的页面，以及仅引用单一来源但未设置置信度字段的页面——
   这些页面需要寻找佐证，或将其降为 `confidence: medium`。

⑧ **来源漂移：** 对 `raw/` 中每个 frontmatter 含 `sha256:` 的文件重新计算哈希并标记不匹配项。
   不匹配表示原始文件曾被编辑（不应发生——raw/ 不可变），或所摄取 URL 的内容后来发生了变化。
   这不是严重错误，但值得报告。

⑨ **页面大小：** 标记超过 200 行的页面——它们是拆分候选项。

⑩ **标签审计：** 列出所有正在使用的标签，并标记 SCHEMA.md 分类法中不存在的标签。

⑪ **日志轮换：** 如果 log.md 超过 500 个条目，则对其进行轮换。

⑫ **报告发现**，提供具体文件路径和建议操作，并按严重程度分组
   （损坏链接 > 孤立页面 > 来源漂移 > 有争议页面 > 过时内容 > 样式问题）。

⑬ **追加到 log.md：** `## [YYYY-MM-DD] lint | N issues found`

## 使用 Wiki

### 搜索

```bash
# Find pages by content
search_files "transformer" path="$WIKI" file_glob="*.md"

# Find pages by filename
search_files "*.md" target="files" path="$WIKI"

# Find pages by tag
search_files "tags:.*alignment" path="$WIKI" file_glob="*.md"

# Recent activity
read_file "$WIKI/log.md" offset=<last 20 lines>
```

### 批量摄取

一次摄取多个来源时，批量执行更新：
1. 先读取所有来源
2. 识别所有来源中出现的全部实体和概念
3. 一次性检查它们的现有页面（只执行一次搜索，而不是 N 次）
4. 一次性创建/更新页面（避免重复更新）
5. 最后只更新一次 index.md
6. 编写一条覆盖整个批次的日志记录

### 归档

当内容已完全被取代或领域范围发生变化时：
1. 如果 `_archive/` 目录不存在，则创建它
2. 将页面移动到 `_archive/`，并保留其原始路径（例如 `_archive/entities/old-page.md`）
3. 从 `index.md` 中移除
4. 更新所有链接到该页面的页面——用纯文本 + “（已归档）”替换 Wiki 链接
5. 记录归档操作

### Obsidian 集成

Wiki 目录开箱即用，可直接作为 Obsidian 仓库：
- `[[wikilinks]]` 会呈现为可点击链接
- 图谱视图可视化知识网络
- YAML frontmatter 为 Dataview 查询提供数据
- `raw/assets/` 文件夹存放通过 `![[image.png]]` 引用的图像

为获得最佳效果：
- 将 Obsidian 的附件文件夹设置为 `raw/assets/`
- 在 Obsidian 设置中启用“Wikilinks”（通常默认开启）
- 安装 Dataview 插件，以支持 `TABLE tags FROM "entities" WHERE contains(tags, "company")` 之类的查询

如果同时使用 Obsidian Skill，请将 `OBSIDIAN_VAULT_PATH` 设置为与 Wiki 路径相同的目录。

### 无头 Obsidian（服务器和无头计算机）

在没有显示器的计算机上，使用 `obsidian-headless` 代替桌面应用。
它无需 GUI 即可通过 Obsidian Sync 同步仓库，非常适合在服务器上运行、写入 Wiki 的智能体，
同时由另一台设备上的 Obsidian 桌面端读取。

**设置：**
```bash
# Requires Node.js 22+
npm install -g obsidian-headless

# Login (requires Obsidian account with Sync subscription)
ob login --email <email> --password '<password>'

# Create a remote vault for the wiki
ob sync-create-remote --name "LLM Wiki"

# Connect the wiki directory to the vault
cd ~/wiki
ob sync-setup --vault "<vault-id>"

# Initial sync
ob sync

# Continuous sync (foreground — use systemd for background)
ob sync --continuous
```

**通过 systemd 在后台持续同步：**
```ini
# ~/.config/systemd/user/obsidian-wiki-sync.service
[Unit]
Description=Obsidian LLM Wiki Sync
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/path/to/ob sync --continuous
WorkingDirectory=/home/user/wiki
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now obsidian-wiki-sync
# Enable linger so sync survives logout:
sudo loginctl enable-linger $USER
```

这样，智能体便可在服务器上写入 `~/wiki`，而你可以在笔记本电脑或手机的 Obsidian 中浏览同一仓库——变更会在数秒内出现。

## 常见陷阱

- **绝不要修改 `raw/` 中的文件**——来源不可变。更正应写入 Wiki 页面。
- **务必先了解现状**——新会话中执行任何操作前，都应读取 SCHEMA、索引和近期日志。
  跳过此步骤会导致重复内容和交叉引用遗漏。
- **务必更新 index.md 和 log.md**——跳过此步骤会使 Wiki 逐渐退化；二者是导航骨架。
- **不要为顺带提及的内容创建页面**——遵循 SCHEMA.md 中的页面创建阈值。仅在脚注中出现一次的名称，不足以创建实体页面。
- **不要创建没有交叉引用的页面**——孤立页面不可见。每个页面必须链接到至少 2 个其他页面。
- **Frontmatter 必不可少**——它支持搜索、筛选和过时检测。
- **标签必须来自分类法**——随意添加标签最终会演变成噪声。先将新标签添加到 SCHEMA.md，再使用它们。
- **保持页面易于浏览**——一个 Wiki 页面应便于在 30 秒内快速浏览。拆分超过 200 行的页面，并将详细分析移至专门的深度分析页面。
- **批量更新前先询问**——如果一次摄取会修改 10 个以上现有页面，应先与用户确认范围。
- **轮换日志**——当 log.md 超过 500 个条目时，将其重命名为 `log-YYYY.md` 并创建新日志。
  智能体应在检查过程中核查日志大小。
- **明确处理矛盾**——不要静默覆盖。记录双方主张及其日期和来源，在 frontmatter 中标记，并提示用户审阅。

## 相关工具

[llm-wiki-compiler](https://github.com/atomicmemory/llm-wiki-compiler) 是一个 Node.js CLI，
它以相同的 Karpathy 理念为基础，将来源编译成概念 Wiki。它与 Obsidian 兼容，因此希望采用定时或 CLI 驱动编译流水线的用户，
可以让它指向本 Skill 所维护的同一仓库。权衡之处在于：它会接管页面生成（以自身逻辑取代智能体对是否创建页面的判断），
并且针对小型语料库进行了优化。如果你希望由智能体参与内容筛选和整理，请使用此 Skill；
如果希望批量编译一个来源目录，请使用 llmwiki。
