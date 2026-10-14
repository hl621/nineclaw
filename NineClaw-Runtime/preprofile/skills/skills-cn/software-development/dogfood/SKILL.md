---
name: dogfood
description: "对 Web 应用进行探索式 QA：发现缺陷、收集证据并生成报告。"
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [qa, testing, browser, web, dogfood]
    related_skills: []
---

# Dogfood：系统化 Web 应用 QA 测试

## 概述

本技能指导你使用浏览器工具集，对 Web 应用进行系统化探索式 QA 测试。你将浏览应用、与元素交互、捕获问题证据，并生成结构化的缺陷报告。

## 前置条件

- 必须提供浏览器工具集（`browser_navigate`、`browser_snapshot`、`browser_click`、`browser_type`、`browser_vision`、`browser_console`、`browser_scroll`、`browser_back`、`browser_press`）
- 用户提供的目标 URL 和测试范围

## 输入

用户提供：
1. **目标 URL** — 测试的入口点
2. **范围** — 需要重点测试的区域或功能（或使用 "full site" 进行全面测试）
3. **输出目录**（可选）— 保存截图和报告的位置（默认：`./dogfood-output`）

## 工作流程

遵循以下由 5 个阶段组成的系统化工作流程：

### 阶段 1：规划

1. 创建输出目录结构：
   ```
   {output_dir}/
   ├── screenshots/       # Evidence screenshots
   └── report.md          # Final report (generated in Phase 5)
   ```
2. 根据用户输入确定测试范围。
3. 规划要测试的页面和功能，构建一个粗略的站点地图：
   - 落地页/首页
   - 导航链接（页眉、页脚、侧边栏）
   - 关键用户流程（注册、登录、搜索、结账等）
   - 表单和交互式元素
   - 边界情况（空状态、错误页面、404 页面）

### 阶段 2：探索

针对计划中的每个页面或功能：

1. **导航**到该页面：
   ```
   browser_navigate(url="https://example.com/page")
   ```

2. **获取快照**以了解 DOM 结构：
   ```
   browser_snapshot()
   ```

3. **检查控制台**中的 JavaScript 错误：
   ```
   browser_console(clear=true)
   ```
   每次导航后以及每次重要交互后都要执行此操作。无明显外在表现的 JS 错误是很有价值的发现。

4. **获取带标注的截图**，以直观评估页面并识别交互式元素：
   ```
   browser_vision(question="Describe the page layout, identify any visual issues, broken elements, or accessibility concerns", annotate=true)
   ```
   `annotate=true` 标志会在交互式元素上叠加编号为 `[N]` 的标签。每个 `[N]` 都映射到 ref `@eN`，供后续浏览器命令使用。

5. **系统化测试交互式元素**：
   - 点击按钮和链接：`browser_click(ref="@eN")`
   - 填写表单：`browser_type(ref="@eN", text="test input")`
   - 测试键盘导航：`browser_press(key="Tab")`、`browser_press(key="Enter")`
   - 滚动浏览内容：`browser_scroll(direction="down")`
   - 使用无效输入测试表单验证
   - 测试空表单提交

6. **每次交互后**，检查以下内容：
   - 控制台错误：`browser_console()`
   - 视觉变化：`browser_vision(question="What changed after the interaction?")`
   - 预期行为与实际行为的差异

### 阶段 3：收集证据

对发现的每个问题：

1. **获取展示该问题的截图**：
   ```
   browser_vision(question="Capture and describe the issue visible on this page", annotate=false)
   ```
   保存响应中的 `screenshot_path`，报告中会引用该路径。

2. **记录详细信息**：
   - 问题出现位置的 URL
   - 复现步骤
   - 预期行为
   - 实际行为
   - 控制台错误（如有）
   - 截图路径

3. **使用问题分类法对问题进行分类**（参见 `references/issue-taxonomy.md`）：
   - 严重程度：Critical / High / Medium / Low
   - 类别：Functional / Visual / Accessibility / Console / UX / Content

### 阶段 4：分类整理

1. 审查所有已收集的问题。
2. 去重 — 合并在不同位置表现出来的同一个缺陷。
3. 为每个问题确定最终的严重程度和类别。
4. 按严重程度排序（Critical 最先，然后依次为 High、Medium、Low）。
5. 按严重程度和类别统计问题数量，供执行摘要使用。

### 阶段 5：报告

使用 `templates/dogfood-report-template.md` 中的模板生成最终报告。

报告必须包括：
1. **执行摘要**，其中包含问题总数、按严重程度划分的明细，以及测试范围
2. **每个问题的独立章节**，其中包含：
   - 问题编号和标题
   - 严重程度和类别徽章
   - 观察到问题的 URL
   - 问题描述
   - 复现步骤
   - 预期行为与实际行为
   - 截图引用（使用 `MEDIA:<screenshot_path>` 嵌入图像）
   - 相关的控制台错误（如有）
3. 所有问题的**汇总表**
4. **测试说明** — 已测试的内容、未测试的内容以及任何阻碍因素

将报告保存至 `{output_dir}/report.md`。

## 工具参考

| 工具 | 用途 |
|------|---------|
| `browser_navigate` | 前往某个 URL |
| `browser_snapshot` | 获取 DOM 文本快照（无障碍树） |
| `browser_click` | 通过 ref（`@eN`）或文本点击元素 |
| `browser_type` | 在输入字段中输入文本 |
| `browser_scroll` | 在页面中向上/向下滚动 |
| `browser_back` | 返回浏览器历史记录中的上一页 |
| `browser_press` | 按下键盘按键 |
| `browser_vision` | 截图并进行 AI 分析；使用 `annotate=true` 获取元素标签 |
| `browser_console` | 获取 JS 控制台输出和错误 |

## 提示

- **每次导航后以及每次重要交互后，始终检查 `browser_console()`。** 无明显外在表现的 JS 错误是最有价值的发现之一。
- 当需要判断交互式元素的位置，或快照中的 ref 不明确时，**请将 `annotate=true` 与 `browser_vision` 搭配使用**。
- **同时使用有效和无效输入进行测试** — 表单验证缺陷很常见。
- **滚动浏览长页面** — 首屏以下的内容可能存在渲染问题。
- **测试导航流程** — 端到端走完多步骤流程。
- **检查响应式行为**，留意截图中可见的任何布局问题。
- **不要忘记边界情况**：空状态、超长文本、特殊字符、快速点击。
- 向用户报告截图时，请加入 `MEDIA:<screenshot_path>`，以便用户直接查看内嵌证据。
