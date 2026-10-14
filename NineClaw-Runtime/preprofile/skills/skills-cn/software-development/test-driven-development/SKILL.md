---
name: test-driven-development
description: "TDD：强制执行 RED-GREEN-REFACTOR，先写测试，再写代码。"
version: 1.1.0
author: Hermes Agent (adapted from obra/superpowers)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [testing, tdd, development, quality, red-green-refactor]
    related_skills: [systematic-debugging, plan, subagent-driven-development]
---

# 测试驱动开发（TDD）

## 概述

先写测试。亲眼看它失败。再写恰好能让测试通过的最少代码。

**核心原则：** 如果没有亲眼看到测试失败，就无法知道它是否测试了正确的内容。

**违背这些规则的具体条文，就是违背这些规则的根本精神。**

## 何时使用

**始终使用：**
- 新功能
- bug 修复
- 重构
- 行为变更

**例外情况（必须先询问用户）：**
- 一次性原型
- 生成的代码
- 配置文件

正在想“这一次跳过 TDD”？停下来。这是在自我合理化。

## 铁律

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

先于测试编写了代码？删除它，重新开始。

**没有例外：**
- 不要把它留作“参考”
- 不要在写测试时“调整”它
- 不要查看它
- 删除就是彻底删除

根据测试重新实现。没有商量余地。

## RED-GREEN-REFACTOR 循环

### RED——编写失败测试

编写一个最小测试，展示预期应发生的行为。

**好的测试：**
```python
def test_retries_failed_operations_3_times():
    attempts = 0
    def operation():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise Exception('fail')
        return 'success'

    result = retry_operation(operation)

    assert result == 'success'
    assert attempts == 3
```
名称清晰，测试真实行为，并且只测试一件事。

**不好的测试：**
```python
def test_retry_works():
    mock = MagicMock()
    mock.side_effect = [Exception(), Exception(), 'success']
    result = retry_operation(mock)
    assert result == 'success'  # What about retry count? Timing?
```
名称含糊，测试的是 mock，而不是真实代码。

**要求：**
- 每个测试只覆盖一种行为
- 名称清晰且具有描述性（名称中有“and”？拆成多个测试）
- 测试真实代码，而不是 mock（除非确实无法避免）
- 名称描述行为，而不是实现

### 验证 RED——亲眼看它失败

**强制要求，绝不能跳过。**

```bash
# Use terminal tool to run the specific test
pytest tests/test_feature.py::test_specific_behavior -v
```

确认：
- 测试失败（不是因为拼写错误而报错）
- 失败消息符合预期
- 失败原因是功能尚未实现

**测试立即通过？** 说明测试的是现有行为。修正测试。

**测试报错？** 修正错误并重新运行，直到它以正确方式失败。

### GREEN——最少代码

编写能让测试通过的最简单代码，不要多写任何内容。

**好：**
```python
def add(a, b):
    return a + b  # Nothing extra
```

**不好：**
```python
def add(a, b):
    result = a + b
    logging.info(f"Adding {a} + {b} = {result}")  # Extra!
    return result
```

不要添加功能、重构其他代码，或做超出测试要求的“改进”。

**GREEN 阶段允许取巧：**
- 硬编码返回值
- 复制粘贴
- 重复代码
- 暂时跳过边界情况

这些问题将在 REFACTOR 阶段解决。

### 验证 GREEN——亲眼看它通过

**强制要求。**

```bash
# Run the specific test
pytest tests/test_feature.py::test_specific_behavior -v

# Then run ALL tests to check for regressions
pytest tests/ -q
```

确认：
- 该测试通过
- 其他测试仍然通过
- 输出干净（没有错误和警告）

**测试失败？** 修复代码，不要修改测试。

**其他测试失败？** 立即修复回归问题。

### REFACTOR——清理代码

只能在变绿后进行：
- 消除重复
- 改进命名
- 提取 helper
- 简化表达式

整个过程始终保持测试为绿色。不要添加新行为。

**如果测试在重构期间失败：** 立即撤销。改用更小的步骤。

### 重复循环

针对下一个行为编写下一个失败测试。每次只完成一个循环。

## 避免横向切片

**不要**先写完所有测试，再写完所有实现。这就是横向切片：RED 变成“写出一堆凭空设想的测试”，GREEN 变成“让这一堆测试通过”。这样会产生脆弱的测试，因为在实现尚未帮助你理解哪些行为和接口真正重要之前，测试就已经设计好了。

改用纵向 tracer bullet：

```text
WRONG:
  RED:   test1, test2, test3, test4
  GREEN: impl1, impl2, impl3, impl4

RIGHT:
  RED→GREEN: test1→impl1
  RED→GREEN: test2→impl2
  RED→GREEN: test3→impl3
```

tracer bullet 是一个端到端的行为切片。它证明整条路径有效，帮助你了解接口，并让后续每个测试都建立在刚刚获得的认知之上。

## 为什么顺序至关重要

**“我会在实现后写测试，验证它能正常工作”**

代码完成后再写的测试会立即通过。立即通过不能证明任何事情：
- 可能测试了错误的内容
- 可能测试的是实现，而不是行为
- 可能漏掉你忘记的边界情况
- 你从未亲眼看到它捕获 bug

测试先行会迫使你亲眼看到测试失败，从而证明它确实测试了某些内容。

**“我已经手动测试过所有边界情况”**

手动测试是临时、随意的。你以为自己测试了所有内容，但实际上：
- 没有测试记录
- 代码变更后无法重新运行
- 面临压力时很容易忘记某些情况
- “我试的时候能用” ≠ 覆盖全面

自动化测试是系统化的。每次都以相同方式运行。

**“删掉 X 小时的工作太浪费了”**

这是沉没成本谬误。时间已经花掉。现在有两种选择：
- 删除并用 TDD 重写（高置信度）
- 保留代码并事后补测试（低置信度，很可能存在 bug）

真正的“浪费”是保留无法信任的代码。

**“TDD 太教条，务实意味着灵活调整”**

TDD 本身就是务实的：
- 在 commit 前发现 bug（比事后调试更快）
- 防止回归（测试会立即捕获破坏性变更）
- 记录行为（测试展示代码的使用方式）
- 支持重构（可以自由修改，由测试捕获破坏）

“务实”的捷径 = 在生产环境调试 = 更慢。

**“事后补测试也能实现相同目标——重要的是精神，而不是仪式”**

不对。事后测试回答的是“这段代码做什么？”，测试先行回答的是“这段代码应该做什么？”

事后测试会受现有实现影响而产生偏差。你测试的是自己已经构建的东西，而不是实际需求。测试先行会迫使你在实现之前发现边界情况。

## 常见的自我合理化

| 借口 | 事实 |
|--------|---------|
| “太简单，不值得测试” | 简单代码也会出错。测试只需 30 秒。 |
| “之后再测试” | 测试立即通过不能证明任何事情。 |
| “事后测试也能实现相同目标” | 事后测试 = “这会做什么？”；测试先行 = “这应该做什么？” |
| “已经手动测试过了” | 临时随意 ≠ 系统化。没有记录，也无法重新运行。 |
| “删掉 X 小时的工作太浪费了” | 沉没成本谬误。保留未经验证的代码就是技术债。 |
| “保留作参考，但仍然先写测试” | 你会调整它。这就是事后测试。删除就是彻底删除。 |
| “需要先探索一下” | 可以。丢弃探索代码，然后从 TDD 开始。 |
| “测试很难写 = 设计不清晰” | 听取测试给出的反馈。难以测试 = 难以使用。 |
| “TDD 会拖慢我” | TDD 比调试更快。务实 = 测试先行。 |
| “手动测试更快” | 手动测试无法证明边界情况。每次变更后都得重新测试。 |
| “现有代码没有测试” | 你正在改进它。为自己接触的代码添加测试。 |

## 危险信号——停止并重新开始

如果发现自己正在做以下任何一件事，请删除代码并用 TDD 重新开始：

- 先写代码，后写测试
- 实现完成后再写测试
- 测试第一次运行就立即通过
- 无法解释测试为什么失败
- “稍后”再添加测试
- 用“就这一次”来自我合理化
- “我已经手动测试过了”
- “事后测试也能达到相同目的”
- “保留作参考”或“调整现有代码”
- “已经花了 X 小时，删除太浪费了”
- “TDD 太教条，我这是务实”
- “这次情况不同，因为……”

**以上任何一项都意味着：删除代码，用 TDD 重新开始。**

## 验证检查清单

将工作标记为完成之前：

- [ ] 每个新函数/方法都有测试
- [ ] 实现前亲眼看到每个测试失败
- [ ] 每个测试都因预期原因失败（功能缺失，而非拼写错误）
- [ ] 只编写了让每个测试通过所需的最少代码
- [ ] 所有测试均通过
- [ ] 输出干净（无错误、无警告）
- [ ] 测试使用真实代码（仅在无法避免时使用 mock）
- [ ] 已覆盖边界情况和错误情况

无法勾选所有项目？说明跳过了 TDD。重新开始。

## 遇到困难时

| 问题 | 解决方案 |
|---------|----------|
| 不知道如何测试 | 写出理想中的 API。先写断言。询问用户。 |
| 测试太复杂 | 设计太复杂。简化接口。 |
| 所有内容都必须 mock | 代码耦合过重。使用 dependency injection。 |
| 测试 setup 太庞大 | 提取 helper。仍然复杂？简化设计。 |

## Hermes Agent 集成

### 运行测试

在每个步骤使用 `terminal` 工具运行测试：

```python
# RED — verify failure
terminal("pytest tests/test_feature.py::test_name -v")

# GREEN — verify pass
terminal("pytest tests/test_feature.py::test_name -v")

# Full suite — verify no regressions
terminal("pytest tests/ -q")
```

### 与 delegate_task 配合使用

派发 subagent 执行实现任务时，在目标中强制要求 TDD：

```python
delegate_task(
    goal="Implement [feature] using strict TDD",
    context="""
    Follow test-driven-development skill:
    1. Write failing test FIRST
    2. Run test to verify it fails
    3. Write minimal code to pass
    4. Run test to verify it passes
    5. Refactor if needed
    6. Commit

    Project test command: pytest tests/ -q
    Project structure: [describe relevant files]
    """,
    toolsets=['terminal', 'file']
)
```

### 与 systematic-debugging 配合使用

发现 bug？编写能够复现它的失败测试。遵循 TDD 循环。该测试会证明修复有效并防止回归。

绝不要在没有测试的情况下修复 bug。

## 测试反模式

- **测试 mock 行为而不是真实行为**——mock 应用于验证交互，而不是取代被测系统
- **测试实现细节**——测试行为/结果，而不是内部方法调用
- **只测试正常路径**——还应始终测试边缘情况、错误情况和边界值
- **脆弱测试**——测试应验证行为，而不是结构；重构不应该让测试失败

## 最终规则

```
Production code → test exists and failed first
Otherwise → not TDD
```

未经用户明确许可，没有例外。
