---
name: spike
description: "在正式构建前，通过一次性实验验证想法。"
version: 1.0.0
author: Hermes Agent (adapted from gsd-build/get-shit-done)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [spike, prototype, experiment, feasibility, throwaway, exploration, research, planning, mvp, proof-of-concept]
    related_skills: [sketch, subagent-driven-development, plan]
---

# Spike 探索实验

当用户希望在投入正式构建前先**切身验证一个想法**时，使用此技能——例如验证可行性、比较不同方案，或揭示单靠研究无法回答的未知问题。Spike 从设计之初就是一次性的；获得所需结论后就应将其丢弃。

当用户说出 "let me try this"、"I want to see if X works"、"spike this out"、"before I commit to Y"、"quick prototype of Z"、"is this even possible?" 或 "compare A vs B" 等表达时，加载此技能。

## 不应使用此技能的情况

- 通过查阅文档或阅读代码就能得到答案——只做研究，不要构建
- 这项工作将用于生产环境或正式交付——改用 `plan` 技能
- 想法已经得到验证——直接进入实现

## 如果用户安装了完整 GSD 系统

如果同级技能中出现 `gsd-spike`（通过 `npx get-shit-done-cc --hermes` 安装），并且用户希望使用完整 GSD 工作流，则优先选择 **`gsd-spike`**：它提供持久化 `.planning/spikes/` 状态、跨会话 MANIFEST 跟踪、Given/When/Then 结论格式，以及与 GSD 其余部分集成的提交模式。本技能是轻量级独立版本，适合没有安装（或不想使用）完整系统的用户。

## 核心方法

无论规模大小，每个 spike 都遵循以下循环：

```
decompose  →  research  →  build  →  verdict
   ↑__________________________________________↓
                  iterate on findings
```

### 1. 分解

将用户的想法拆成 **2–5 个相互独立的可行性问题**。每个问题对应一个 spike。用 Given/When/Then 框架整理成表格：

| # | Spike | 验证内容（Given/When/Then） | 风险 |
|---|-------|----------------------------|------|
| 001 | websocket-streaming | Given 已建立 WS 连接，when LLM 流式输出 token，then 客户端在 100ms 内收到数据块 | 高 |
| 002a | pdf-parse-pdfjs | Given 一份多页 PDF，when 使用 pdfjs 解析，then 能够提取结构化文本 | 中 |
| 002b | pdf-parse-camelot | Given 一份多页 PDF，when 使用 camelot 解析，then 能够提取结构化文本 | 中 |

**Spike 类型：**
- **标准型**——用一种方案回答一个问题
- **比较型**——针对同一问题尝试不同方案（共享编号，并添加字母后缀 `a`/`b`/`c`）

**好的 spike 问题：** 针对具体可行性，并有可观察的输出。
**差的 spike 问题：** 范围过宽、没有可观察输出，或者只是“阅读关于 X 的文档”。

**按风险排序。** 最可能让整个想法无法成立的 spike 应先运行。如果困难部分行不通，就没有必要先为简单部分制作原型。

只有当用户已经明确知道要探索什么并清楚表达时，才**跳过分解**。此时将用户的想法作为单个 spike。

### 2. 对齐（适用于多个 spike 的想法）

展示 spike 表格。询问："Build all in this order, or adjust?" 在编写任何代码之前，让用户删除、重新排序或重新表述。

### 3. 研究（每个 spike，构建之前）

Spike 并非无需研究——先研究到足以选出正确方案，再开始构建。对每个 spike：

1. **简要说明。** 用 2–3 句话说明这个 spike 是什么、为何重要以及关键风险。
2. 如果确实存在选择，**列出相互竞争的方案**：

   | 方案 | 工具/库 | 优点 | 缺点 | 状态 |
   |------|---------|------|------|------|
   | ... | ... | ... | ... | 维护中 / 已放弃 / beta |

3. **选择一个。** 说明理由。如果有两个或更多可信方案，则在同一 spike 中快速构建多个变体。
4. 对没有外部依赖的纯逻辑问题，**跳过研究**。

在研究步骤中使用 Hermes 工具：

- `web_search("python websocket streaming libraries 2025")`——寻找候选方案
- `web_extract(urls=["https://websockets.readthedocs.io/..."])`——阅读实际文档（返回 markdown）
- `terminal("pip show websockets | grep Version")`——检查项目 venv 中已安装的版本

对于没有文档页面的库，clone 后阅读其 `README.md` / `examples/`，并使用 `read_file` 获取内容。如果用户配置了 Context7 MCP，它也是很好的信息来源——先使用 `mcp_*_resolve-library-id`，再使用 `mcp_*_query-docs`。

### 4. 构建

每个 spike 使用一个独立目录，并保持可独立运行。

```
spikes/
├── 001-websocket-streaming/
│   ├── README.md
│   └── main.py
├── 002a-pdf-parse-pdfjs/
│   ├── README.md
│   └── parse.js
└── 002b-pdf-parse-camelot/
    ├── README.md
    └── parse.py
```

**优先构建用户可以交互的东西。** 如果唯一输出只是一行表示 "it works." 的日志，spike 就失去了意义。用户希望能*切身感受* spike 确实有效。默认选项按优先级排序如下：

1. 可运行的 CLI：接收输入并打印可观察的输出
2. 用于演示行为的最小 HTML 页面
3. 只有一个 endpoint 的小型 Web 服务器
4. 一个单元测试：用易于理解的断言检验问题

**宁可深入验证，也不要追求速度。** 不要只跑通一次正常路径就宣布 "it works"。要测试边界情况，并追查出人意料的发现。只有经过诚实调查得出的结论才值得信任。

除非 spike 明确需要，否则应**避免**：复杂的包管理、构建工具/bundler、Docker、env 文件和配置系统。所有内容都直接硬编码——这只是 spike。

**构建单个 spike**——典型工具调用顺序：

```
terminal("mkdir -p spikes/001-websocket-streaming")
write_file("spikes/001-websocket-streaming/README.md", "# 001: websocket-streaming\n\n...")
write_file("spikes/001-websocket-streaming/main.py", "...")
terminal("cd spikes/001-websocket-streaming && python3 main.py")
# Observe output, iterate.
```

**并行比较型 spike（002a / 002b）——进行委派。** 当两种方案可以并行执行，且都需要真正的工程工作（而非 10 行原型）时，使用 `delegate_task` 扇出：

```
delegate_task(tasks=[
    {"goal": "Build 002a-pdf-parse-pdfjs: ...", "toolsets": ["terminal", "file", "web"]},
    {"goal": "Build 002b-pdf-parse-camelot: ...", "toolsets": ["terminal", "file", "web"]},
])
```

每个子代理返回各自的结论；由你撰写正面对比。

### 5. 结论

每个 spike 的 `README.md` 以以下内容收尾：

```markdown
## Verdict: VALIDATED | PARTIAL | INVALIDATED

### What worked
- ...

### What didn't
- ...

### Surprises
- ...

### Recommendation for the real build
- ...
```

**VALIDATED** = 核心问题以证据得到肯定回答。
**PARTIAL** = 仅在约束 X、Y、Z 下可行——应记录这些约束。
**INVALIDATED** = 因特定原因不可行。这仍然是一次成功的 spike。

## 比较型 spike

当两种方案回答同一个问题（002a / 002b）时，应**连续**构建它们，然后在最后进行正面对比：

```markdown
## Head-to-head: pdfjs vs camelot

| Dimension | pdfjs (002a) | camelot (002b) |
|-----------|--------------|----------------|
| Extraction quality | 9/10 structured | 7/10 table-only |
| Setup complexity | npm install, 1 line | pip + ghostscript |
| Perf on 100-page PDF | 3s | 18s |
| Handles rotated text | no | yes |

**Winner:** pdfjs for our use case. Camelot if we need table-first extraction later.
```

## 前沿模式（选择下一个要探索的内容）

如果已有 spike，并且用户询问 "what should I spike next?"，遍历现有目录并寻找：

- **集成风险**——两个已验证的 spike 接触同一资源，但此前是独立测试的
- **数据交接**——假设 spike A 的输出与 spike B 的输入兼容，但从未证明
- **愿景缺口**——被默认具备但尚未验证的能力
- **替代方案**——针对 PARTIAL 或 INVALIDATED spike 的不同思路

以 Given/When/Then 格式提出 2–4 个候选项，让用户选择。

## 输出

- 在仓库根目录创建 `spikes/`（如果用户遵循 GSD 约定，则创建 `.planning/spikes/`）
- 每个 spike 一个目录：`NNN-descriptive-name/`
- 每个 spike 使用一个 `README.md`，记录问题、方案、结果和结论
- 代码应保持一次性——如果一个 spike 需要花两天“清理为生产代码”，那就是一次糟糕的 spike

## 归属说明

改编自 GSD（Get Shit Done）项目的 `/gsd-spike` 工作流——MIT © 2025 Lex Christopherson（[gsd-build/get-shit-done](https://github.com/gsd-build/get-shit-done)）。完整 GSD 系统提供持久化 spike 状态、MANIFEST 跟踪，并可与更广泛的规范驱动开发流水线集成；使用 `npx get-shit-done-cc --hermes --global` 安装。
