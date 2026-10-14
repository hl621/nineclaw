---
name: codebase-inspection
description: "使用 pygount 检查代码库：代码行数、语言及占比。"
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [LOC, Code Analysis, pygount, Codebase, Metrics, Repository]
    related_skills: [github-repo-management]
prerequisites:
  commands: [pygount]
---

# 使用 pygount 检查代码库

使用 `pygount` 分析代码仓库的代码行数、语言构成、文件数量，以及代码与注释的比例。

## 适用场景

- 用户要求统计 LOC（代码行数）
- 用户希望了解代码仓库的语言构成
- 用户询问代码库的规模或组成
- 用户希望了解代码与注释的比例
- 泛泛询问“这个代码仓库有多大”之类的问题

## 前置条件

```bash
pip install --break-system-packages pygount 2>/dev/null || pip install pygount
```

## 1. 基本摘要（最常用）

获取完整的语言构成明细，包括文件数量、代码行数和注释行数：

```bash
cd /path/to/repo
pygount --format=summary \
  --folders-to-skip=".git,node_modules,venv,.venv,__pycache__,.cache,dist,build,.next,.tox,.eggs,*.egg-info" \
  .
```

**重要：** 始终使用 `--folders-to-skip` 排除依赖目录和构建目录，否则 pygount 会遍历这些目录，耗时很长甚至卡住。

## 2. 常见的排除目录

请根据项目类型进行调整：

```bash
# Python projects
--folders-to-skip=".git,venv,.venv,__pycache__,.cache,dist,build,.tox,.eggs,.mypy_cache"

# JavaScript/TypeScript projects
--folders-to-skip=".git,node_modules,dist,build,.next,.cache,.turbo,coverage"

# General catch-all
--folders-to-skip=".git,node_modules,venv,.venv,__pycache__,.cache,dist,build,.next,.tox,vendor,third_party"
```

## 3. 按特定语言筛选

```bash
# Only count Python files
pygount --suffix=py --format=summary .

# Only count Python and YAML
pygount --suffix=py,yaml,yml --format=summary .
```

## 4. 逐文件详细输出

```bash
# Default format shows per-file breakdown
pygount --folders-to-skip=".git,node_modules,venv" .

# Sort by code lines (pipe through sort)
pygount --folders-to-skip=".git,node_modules,venv" . | sort -t$'\t' -k1 -nr | head -20
```

## 5. 输出格式

```bash
# Summary table (default recommendation)
pygount --format=summary .

# JSON output for programmatic use
pygount --format=json .

# Pipe-friendly: Language, file count, code, docs, empty, string
pygount --format=summary . 2>/dev/null
```

## 6. 解读结果

摘要表中的各列：
- **语言** — 检测到的编程语言
- **文件数** — 该语言的文件数量
- **代码** — 实际代码（可执行或声明性代码）的行数
- **注释** — 注释或文档的行数
- **%** — 占总量的百分比

特殊的伪语言：
- `__empty__` — 空文件
- `__binary__` — 二进制文件（图像、编译产物等）
- `__generated__` — 自动生成的文件（通过启发式规则检测）
- `__duplicate__` — 内容完全相同的文件
- `__unknown__` — 无法识别的文件类型

## 注意事项

1. **始终排除 .git、node_modules 和 venv** — 如果不使用 `--folders-to-skip`，pygount 会遍历所有内容；面对大型依赖目录树时，可能耗时数分钟甚至卡住。
2. **Markdown 显示 0 行代码** — pygount 会将所有 Markdown 内容归类为注释而非代码。这是预期行为。
3. **JSON 文件显示的代码行数偏少** — pygount 可能会较为保守地统计 JSON 行数。如需准确统计 JSON 行数，请直接使用 `wc -l`。
4. **大型单体代码仓库** — 对于非常大的代码仓库，建议使用 `--suffix` 指定特定语言，而不是扫描全部内容。
