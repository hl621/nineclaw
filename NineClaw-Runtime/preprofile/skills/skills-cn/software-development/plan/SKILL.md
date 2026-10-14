---
name: plan
description: 将 Markdown 计划写入 .hermes/plans/；不执行计划。
version: 2.0.0
author: Hermes Agent (writing-craft adapted from obra/superpowers)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [planning, plan-mode, implementation, workflow, design, documentation]
    related_skills: [subagent-driven-development, test-driven-development, requesting-code-review]
---

# 计划模式

当用户需要计划而非执行时，请使用本技能。

## 核心行为

本轮只制定计划。

- 不要实现代码。
- 除计划 Markdown 文件外，不要编辑项目文件。
- 不要运行会产生修改的终端命令，不要 commit、push，也不要执行外部操作。
- 必要时，可以使用只读命令／工具检查仓库或其他上下文。
- 你的交付物是一份保存在活跃工作区 `.hermes/plans/` 下的 Markdown 计划。

## 输出要求

编写一份具体且可执行的 Markdown 计划。

酌情包含：
- 目标
- 当前上下文／假设
- 建议方案
- 分步计划
- 可能需要修改的文件
- 测试／验证
- 风险、权衡与开放问题

如果任务与代码有关，请包含精确的文件路径、可能的测试目标和验证步骤。

## 保存位置

使用 `write_file` 将计划保存到：
- `.hermes/plans/YYYY-MM-DD_HHMMSS-<slug>.md`

将其视为相对于活跃工作目录／后端工作区的路径。Hermes 文件工具能够感知后端，因此使用此相对路径可确保在 local、docker、ssh、modal 和 daytona 后端中，计划都与工作区保存在一起。

如果运行时提供了特定目标路径，请使用该精确路径。
如果没有，请自行在 `.hermes/plans/` 下创建一个合理的、带时间戳的文件名。

## 交互风格

- 如果请求足够明确，直接编写计划。
- 如果 `/plan` 没有附带明确指令，则根据当前对话上下文推断任务。
- 如果信息确实不足，应提出一个简短的澄清问题，而不是猜测。
- 保存计划后，用简短回复说明计划内容和保存路径。

---

# 写好计划

本技能接下来的内容说明如何编写一份*出色的*实施计划——也就是应写入上述 Markdown 文件的内容。

## 概述

编写全面的实施计划时，应假设实施者对代码库一无所知，而且品味存疑。记录他们需要的一切：应修改哪些文件、完整代码、测试命令、应查阅的文档，以及如何验证。把任务拆成小块。DRY。YAGNI。TDD。频繁提交。

假设实施者是一名熟练的开发者，但对工具集或问题领域几乎一无所知。并假设他们不太懂如何做好测试设计。

**核心原则：**好的计划让实施变得显而易见。如果有人还需要猜测，这份计划就不完整。

## 何时需要完整的实施计划

**在以下工作之前始终使用：**
- 实现多步骤功能
- 拆解复杂需求
- 通过 subagent-driven-development 委派给子智能体

**以下情况也不要跳过：**
- 功能看似简单（假设会导致 bug）
- 你打算亲自实现（未来的你也需要指导）
- 独自工作（文档依然重要）

## 小粒度任务

**每项任务 = 2–5 分钟的专注工作。**

每个步骤只执行一个动作：
- “编写失败的测试”——一个步骤
- “运行测试，确认它失败”——一个步骤
- “实现使测试通过所需的最少代码”——一个步骤
- “运行测试，确认它们通过”——一个步骤
- “提交”——一个步骤

**过大：**
```markdown
### Task 1: Build authentication system
[50 lines of code across 5 files]
```

**大小合适：**
```markdown
### Task 1: Create User model with email field
[10 lines, 1 file]

### Task 2: Add password hash field to User
[8 lines, 1 file]

### Task 3: Create password hashing utility
[15 lines, 1 file]
```

## 计划文档结构

### 标头（必需）

每份计划**必须**以以下内容开头：

```markdown
# [Feature Name] Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

---
```

### 任务结构

每项任务遵循以下格式：

````markdown
### Task N: [Descriptive Name]

**Objective:** What this task accomplishes (one sentence)

**Files:**
- Create: `exact/path/to/new_file.py`
- Modify: `exact/path/to/existing.py:45-67` (line numbers if known)
- Test: `tests/path/to/test_file.py`

**Step 1: Write failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

**Step 2: Run test to verify failure**

Run: `pytest tests/path/test.py::test_specific_behavior -v`
Expected: FAIL — "function not defined"

**Step 3: Write minimal implementation**

```python
def function(input):
    return expected
```

**Step 4: Run test to verify pass**

Run: `pytest tests/path/test.py::test_specific_behavior -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
````

## 编写流程

### 第 1 步：理解需求

阅读并理解：
- 功能需求
- 设计文档或用户描述
- 验收标准
- 约束条件

### 第 2 步：探索代码库

使用 Hermes 工具了解项目：

```python
# Understand project structure
search_files("*.py", target="files", path="src/")

# Look at similar features
search_files("similar_pattern", path="src/", file_glob="*.py")

# Check existing tests
search_files("*.py", target="files", path="tests/")

# Read key files
read_file("src/app.py")
```

### 第 3 步：设计方案

确定：
- 架构模式
- 文件组织方式
- 所需依赖
- 测试策略

### 第 4 步：编写任务

按以下顺序创建任务：
1. 设置／基础设施
2. 核心功能（每项都采用 TDD）
3. 边界情况
4. 集成
5. 清理／文档

### 第 5 步：补充完整细节

每项任务都应包含：
- **精确的文件路径**（不要写“配置文件”，而要写 `src/config/settings.py`）
- **完整的代码示例**（不要只写“添加验证”，而要给出实际代码）
- **精确命令**及其预期输出
- 能够证明任务有效的**验证步骤**

### 第 6 步：审查计划

检查：
- [ ] 任务前后衔接、顺序合理
- [ ] 每项任务粒度足够小（2–5 分钟）
- [ ] 文件路径精确
- [ ] 代码示例完整（可复制粘贴）
- [ ] 命令精确，并包含预期输出
- [ ] 没有缺失的上下文
- [ ] 已应用 DRY、YAGNI、TDD 原则

## 原则

### DRY（不要重复自己）

**错误：**在 3 个地方复制粘贴验证逻辑
**正确：**提取验证函数，并在各处复用

### YAGNI（你不会需要它）

**错误：**为未来需求添加“灵活性”
**正确：**只实现当前需要的内容

```python
# Bad — YAGNI violation
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
        self.preferences = {}  # Not needed yet!
        self.metadata = {}     # Not needed yet!

# Good — YAGNI
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
```

### TDD（测试驱动开发）

每项产出代码的任务都应包含完整的 TDD 循环：
1. 编写失败的测试
2. 运行测试以确认失败
3. 编写最少的代码
4. 运行测试以确认通过

详情参见 `test-driven-development` 技能。

### 频繁提交

每项任务完成后都要提交：
```bash
git add [files]
git commit -m "type: description"
```

## 常见错误

### 任务含糊

**错误：**“添加身份验证”
**正确：**“创建包含 email 和 password_hash 字段的 User 模型”

### 代码不完整

**错误：**“第 1 步：添加验证函数”
**正确：**“第 1 步：添加验证函数”，后面紧跟完整的函数代码

### 缺少验证

**错误：**“第 3 步：测试它是否有效”
**正确：**“第 3 步：运行 `pytest tests/test_auth.py -v`，预期：3 passed”

### 缺少文件路径

**错误：**“创建模型文件”
**正确：**“创建：`src/models/user.py`”

## 执行交接

保存计划后，提出执行方案：

**"Plan complete and saved. Ready to execute using subagent-driven-development — I'll dispatch a fresh subagent per task with two-stage review (spec compliance then code quality). Shall I proceed?"**

执行时，使用 `subagent-driven-development` 技能：
- 每项任务都使用新的 `delegate_task`，并提供完整上下文
- 每项任务完成后进行规范符合性审查
- 规范通过后进行代码质量审查
- 只有两项审查都批准后才能继续

## 记住

```
Bite-sized tasks (2-5 min each)
Exact file paths
Complete code (copy-pasteable)
Exact commands with expected output
Verification steps
DRY, YAGNI, TDD
Frequent commits
```

**好的计划让实施变得显而易见。**
