---
name: simplify-code
description: "由 4 个并行代理清理最近的代码改动。"
version: 1.1.0
author: Hermes Agent (inspired by Claude Code /simplify)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [code-review, cleanup, refactor, delegation, subagent, parallel, simplify]
    related_skills: [requesting-code-review, test-driven-development, plan]
---

# 简化代码——并行审查与清理

让四位各有侧重的审查者并行审查你最近的代码改动，汇总他们的发现，并应用值得实施的修复。

**这是一次清理，而不是排查 bug。** 你的目标是提升已经可以正常工作的代码质量——消除重复、简化不必要的复杂性、减少浪费，并将治标不治本的补丁深化为更根本的修复。不要在这里寻找正确性 bug；那是 `requesting-code-review` 的职责。

**核心原则：** 四位专注于狭窄领域的审查者，胜过一位面面俱到的审查者。每位审查者只深入搜索一类问题——复用、质量、效率、实现层次——不会因同时兼顾四个方面而分散注意力。他们并发运行，因此你只需承担一次审查的延迟，而不是四次。

## 何时使用

当用户说出以下任一表达时，触发此技能：

- "simplify" / "simplify my changes" / "simplify these changes"
- "review my code" / "review my recent changes" / "clean up my changes"
- "/simplify"（如果他们沿用了 Claude Code 的习惯）

用户可能会添加以下可选修饰语——请遵从：

- **重点：** "simplify focus on efficiency" → 只运行效率审查者（或在汇总时更侧重其发现）。可识别的重点有：`reuse`、`quality`（也接受 `simplification`）、`efficiency`、`altitude`。
- **试运行：** "simplify but don't change anything" / "just report" → 运行四位审查者、展示发现，但不应用任何改动。应用前先询问。
- **范围：** "simplify the last commit" / "simplify staged" / "simplify src/foo.py" → 相应缩小 diff 来源（参见阶段 1）。

不要在每次编辑后自动运行此技能，也不要把它附加到无关任务的末尾。它会消耗四个子代理的 token——只有用户明确要求时才调用。

## 流程

### 阶段 1——确定改动

捕获待审查的 diff。根据用户的要求选择来源；默认顺序如下：

```bash
# 1. Default: uncommitted working-tree changes (tracked files)
git diff

# 2. If that's empty, include staged changes
git diff HEAD

# 3. Scoped variants the user may request:
git diff --staged                 # "staged changes"
git diff HEAD~1                    # "the last commit"
git diff main...HEAD              # "this branch" / "my PR"
git diff -- src/foo.py            # specific file(s)
```

如果 `git diff` 和 `git diff HEAD` 都为空，并且不存在 git 仓库或没有改动，则退而检查用户明确指定的文件，或本次会话中最近创建/编辑的文件。如果确实找不到任何改动过的代码，如实说明并停止——没有可简化的内容。

捕获完整的 diff 文本，并留意其大小。如果规模很大（例如改动超过 2000 行），应警告用户：四个子代理各自携带完整 diff 会消耗大量 token；继续之前，建议按目录或提交缩小范围。

### 阶段 2——并行启动四位审查者

使用 `delegate_task` 的**批处理模式**——将四个任务放进同一个 `tasks` 数组，使其并发运行。四路并行是此模式的合适扇出数量；在任何默认安装中，它都不会超出 `delegation.max_concurrent_children` 限额。

**无法使用委派？** 如果当前上下文无法调用 `delegate_task`（例如你是叶子子代理、委派已禁用或预算已耗尽），不要跳过审查或遗漏任何视角。请在当前上下文中依次自行完成全部四个审查视角，并采用相同的搜索标准和发现格式。随后在最终摘要中明确说明：这次执行的是单轮内联审查，而不是并行扇出，以便用户了解实际执行方式。

向**每位**审查者提供**完整 diff**（不能只给片段——跨文件问题往往隐藏在间隙中）以及仓库绝对路径，以便他们搜索更广泛的代码库。每位审查者都获得 `terminal`、`file` 和 `search` 工具集（从而可以使用 `git`、`read_file` 和 `search_files`/grep）。

要求每位审查者：
- 在现有代码库中搜索证据（不要只根据 diff 推断）。
- **遵循切斯特顿栅栏原则：** 在标记任何待删除内容之前，对相应行运行 `git blame`，了解它存在的原因。如果无法确定其原始目的，将其标记为 `confidence: low`——不要猜测。
- 用结构化格式报告发现，并说明具体成本、置信度和风险：
  ```
  file:line → problem → cost (what's duplicated/wasted/harder to maintain) → suggested fix | confidence: high/medium/low | risk: SAFE/CAREFUL/RISKY
  ```
  **成本**字段迫使每条发现证明自身价值——如果无法说明问题实际造成了什么成本，那很可能只是无关紧要的挑剔。
  - **SAFE** = 已证明不会影响行为（未使用的 import、注释掉的代码、纯透传包装器）。自动应用。
  - **CAREFUL** = 在不改变语义的前提下改进代码（重命名局部变量、扁平化嵌套三元表达式、提取辅助函数）。应用后用测试验证。
  - **RISKY** = 可能改变行为或破坏公共契约（重构 N+1、重命名公共 API、改变内存生命周期）。标记供人工审查——不要自动应用。
- 跳过吹毛求疵和纯样式变动。只标记能实质性改善代码的问题。

传入以下四个目标（剔除用户指定重点之外的目标）：

**审查者 1——代码复用**
> Review this diff for code that duplicates functionality already in the
> codebase. Search utility modules, shared helpers, and adjacent files
> (use search_files / grep) for existing functions, constants, or patterns
> the new code could call instead of reimplementing. Flag: new functions
> that duplicate existing ones; hand-rolled logic that an existing utility
> already does (manual string/path manipulation, custom env checks, ad-hoc
> type guards, re-implemented parsing). For each, name the existing thing to
> use and where it lives.

**审查者 2——代码质量**
> Review this diff for quality problems. Look for: redundant state (values
> that duplicate or could be derived from existing state; caches that don't
> need to exist); parameter sprawl (new params bolted on where the function
> should have been restructured); copy-paste-with-variation (near-duplicate
> blocks that should share an abstraction); leaky abstractions (exposing
> internals, breaking an existing encapsulation boundary); stringly-typed
> code (raw strings where a constant/enum/registry already exists — check the
> canonical registries before flagging); deeply nested conditionals (ternary
> chains, 3+-level if/else pyramids — flatten with guard clauses, early
> returns, or a lookup table); AI-generated slop patterns (extra
> comments restating obvious code like `// increment counter` above `count++`;
> unnecessary defensive null-checks on already-validated inputs; `as any`
> casts that bypass the type system; patterns inconsistent with the rest of
> the file). For each, give the concrete refactor.

**审查者 3——效率**
> Review this diff for efficiency problems. Look for: unnecessary work
> (redundant computation, repeated file reads, duplicate API calls, N+1
> access patterns); missed concurrency (independent ops run sequentially);
> hot-path bloat (heavy/blocking work on startup or per-request paths);
> TOCTOU anti-patterns (existence pre-checks before an op instead of doing
> the op and handling the error); memory issues (unbounded growth, missing
> cleanup, listener/handle leaks; long-lived callbacks or objects built as
> closures that capture the whole enclosing scope — everything captured
> stays alive as long as the object does, so prefer a small class or
> explicit-fields struct that copies only what it needs); overly broad reads
> (loading whole files when a slice would do); silent failures (empty catch
> blocks, ignored error returns, `except: pass`, `.catch(() => {})` with no
> handling, error propagation gaps — these hide bugs and should at minimum
> log before swallowing). For each, give the concrete fix and why it's
> faster or safer.

**审查者 4——实现层次**
> Review this diff for changes implemented at the wrong depth — band-aids
> layered on top of shared infrastructure instead of fixes to the
> infrastructure itself. Signs of a too-shallow fix: a special case added to
> a generic code path to handle one caller (an `if (caller == X)` branch, a
> type check, a magic-value escape hatch); a symptom patched at the call
> site while sibling call sites keep the same flaw; a workaround stacked on
> an earlier workaround; a wrapper added to avoid touching the thing that
> actually needs changing; configuration or flags introduced to route around
> a broken default instead of fixing the default. For each, identify the
> underlying mechanism the change is dodging and describe the deeper fix —
> generalize the shared path, fix the root default, or fix the whole bug
> class — and honestly note when the deeper fix is large enough that it
> should be its own task rather than part of this cleanup. Read the
> surrounding code and `git blame` first: what looks like a band-aid is
> sometimes a deliberate boundary (compat shims, staged migrations,
> vendored-code isolation). Don't flag those.

### 阶段 3——汇总并应用

等待四位审查者全部返回（批处理模式会将结果一起返回）。

1. **合并**发现并去重——如果两条发现针对同一行或同一底层机制，将它们合并为一条。
2. **剔除误报**——你掌握的上下文最多；无需与审查者争论，只需静默丢弃薄弱或错误的建议。
3. **解决冲突。** 审查者可能意见不一（审查者 1："use existing util X"；审查者 3："X is slow, inline it"）。默认决策顺序为：**正确性 > 用户明确指定的重点 > 可读性/复用 > 微观性能。** 除非路径确实是热点，否则不要应用损害清晰度的性能“修复”。如果两个建议互斥且都合理，选择改动代码更少的方案，并注明备选方案。
4. **按风险等级依次应用：**
   - **先处理 SAFE**（自动应用）：未使用的 import、注释掉的代码、纯透传包装器、冗余类型断言。之后运行测试。
   - **再处理 CAREFUL**（应用并验证，每次处理一个文件）：重命名局部变量、扁平化三元表达式、提取辅助函数、合并重复代码。每处理一个文件后都运行测试；任何导致失败的改动都应还原。
   - **最后处理 RISKY**（标记供审查——不要自动应用）：N+1 重构、公共 API 变更、并发修复、错误处理变更。展示每一项的风险说明和测试覆盖状态。实现层次类发现通常属于此级别——深化修复意味着要改动共享基础设施，因此应展示更深层修复方案，由用户决定现在实施还是作为后续任务。
   如果用户选择了试运行，则展示全部三个等级，但不应用任何改动。
5. **验证**没有破坏任何内容：运行项目中针对所改文件的测试（而非完整测试套件），并重新运行仓库使用的 linter/type check。如果某项修复导致测试失败，还原该项修复并报告。
6. **总结**所做的改动：按审查者类别和风险等级简要列出已应用的修复，以及主动跳过的发现及原因。如果采用内联方式（没有委派），在此明确说明。

## 常见陷阱

- **扇出不要超过 4 路。** 更多审查者只会带来更高成本和更多待协调的冲突建议，而不是更好的覆盖面。这四个类别已经覆盖整个问题空间。
- **向每位审查者提供完整 diff。** 将 diff 拆给不同审查者会破坏此设计——只有看到全貌，才能发现跨文件重复和 N+1 问题。
- **审查者应搜索，而不是猜测。** 如果复用类发现没有指向现有工具（"there's probably a helper for this"），那就是噪声。必须提供 `file:line` 证据；缺少证据的发现应丢弃。
- **应用 ≠ 重写。** 这是清理用户最近的改动，不是重构整个模块的许可证。编辑范围应限于 diff 涉及的部分，以及修复所必需的最小周边改动。实现层次类发现是例外中的例外：当正确修复比 diff 更深入时，应将其标记出来——不要在一次清理中擅自重建共享机制。
- **不要偏离到 bug 排查。** 如果审查者发现了真正的正确性 bug，应醒目报告——但要作为单独的“发现 bug”备注，而不是混入清理修复。正确性审查是另一套流程，验证标准也不同。
- **尊重项目约定。** 如果仓库中存在 AGENTS.md / CLAUDE.md / HERMES.md 或 linter 配置，应将这些规则纳入审查提示，使建议符合项目风格，而不是与之冲突。
- **大型 diff 会撑爆上下文。** 如果 diff 很大，应在委派前缩小范围——让四个子代理各自携带 5000 行 diff 成本高昂，而且可能被截断。
- **不要过度信任死代码工具。** `knip`、`ts-prune` 和 `depcheck` 会标记实际上通过动态方式使用的 export（基于字符串的 import、反射）。删除前务必搜索符号名称——工具报告干净并不能作为证明。
- **重命名前未检查公共契约。** export 名称、API 路由路径、数据库列名和配置键都是契约——即使命名不佳，重命名也会破坏使用方。将公共契约变更标记为 RISKY；绝不要自动重命名。
- **删除“没必要”的错误处理。** 空 catch 块或被忽略的错误可能是有意为之——该错误在当前上下文中可能符合预期且无害。标记它，不要删除；交由人工决定。
- **并非每个特例都是治标补丁。** 兼容性 shim、分阶段迁移以及 vendored code 的隔离层看起来像实现层次违规，但可能是刻意设计。标记前检查 `git blame` 和周边注释；如果意图不明，标记为 `confidence: low`。

## 相关技能

如果你的安装中有可选的 `subagent-driven-development` 技能，它涵盖的是互补场景：在实现过程中按任务进行并行审查。本技能则是独立的事后清理流程。预提交安全/质量门禁请使用 `requesting-code-review`——那是排查 bug；这里是清理代码。
