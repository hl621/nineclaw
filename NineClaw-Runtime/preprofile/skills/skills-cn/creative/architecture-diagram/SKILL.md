---
name: architecture-diagram
description: "以 HTML 形式生成深色主题的 SVG 架构、云与基础设施图。"
version: 1.0.0
author: Cocoon AI (hello@cocoon-ai.com), ported by Hermes Agent
license: MIT
dependencies: []
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [architecture, diagrams, SVG, HTML, visualization, infrastructure, cloud]
    related_skills: [concept-diagrams, excalidraw]
---

# 架构图 Skill

生成专业的深色主题技术架构图，以包含内联 SVG 图形的独立 HTML 文件形式交付。无需外部工具、API 密钥或渲染库——只需写入 HTML 文件并在浏览器中打开即可。

## 适用范围

**最适合：**
- 软件系统架构（前端 / 后端 / 数据库分层）
- 云基础设施（VPC、区域、子网、托管服务）
- 微服务 / 服务网格拓扑
- 数据库与 API 关系图、部署图
- 任何适合深色网格背景美学的技术基础设施主题

**以下情况应优先寻找其他方案：**
- 物理、化学、数学、生物或其他科学主题
- 实体对象（车辆、硬件、人体结构、剖面图）
- 平面图、叙事旅程、教育 / 教科书风格的视觉图
- 手绘白板草图（可考虑 `excalidraw`）
- 动画讲解（可考虑动画类 Skill）

如果该主题有更专业的 Skill，应优先使用。如果没有合适选项，本 Skill 也可作为通用 SVG 图表的后备方案——输出将采用下述深色科技美学。

基于 [Cocoon AI 的 architecture-diagram-generator](https://github.com/Cocoon-AI/architecture-diagram-generator)（MIT）。

## 工作流程

1. 用户描述其系统架构（组件、连接关系、技术）
2. 按照下方设计系统生成 HTML 文件
3. 使用 `write_file` 保存为 `.html` 文件（例如 `~/architecture-diagram.html`）
4. 用户在任意浏览器中打开——可离线运行，无依赖

### 输出位置

将图表保存到用户指定路径；若未指定，则默认保存到当前工作目录：
```
./[project-name]-architecture.html
```

### 预览

保存后，建议用户将其打开：
```bash
# macOS
open ./my-architecture.html
# Linux
xdg-open ./my-architecture.html
```

## 设计系统与视觉语言

### 调色板（语义映射）

使用特定的 `rgba` 填充色和十六进制描边色对组件分类：

| 组件类型 | 填充色 (rgba) | 描边色（十六进制） |
| :--- | :--- | :--- |
| **前端** | `rgba(8, 51, 68, 0.4)` | `#22d3ee` (cyan-400) |
| **后端** | `rgba(6, 78, 59, 0.4)` | `#34d399` (emerald-400) |
| **数据库** | `rgba(76, 29, 149, 0.4)` | `#a78bfa` (violet-400) |
| **AWS/云** | `rgba(120, 53, 15, 0.3)` | `#fbbf24` (amber-400) |
| **安全** | `rgba(136, 19, 55, 0.4)` | `#fb7185` (rose-400) |
| **消息总线** | `rgba(251, 146, 60, 0.3)` | `#fb923c` (orange-400) |
| **外部系统** | `rgba(30, 41, 59, 0.5)` | `#94a3b8` (slate-400) |

### 字体与背景
- **字体：** JetBrains Mono（等宽），从 Google Fonts 加载
- **字号：** 12px（名称）、9px（副标签）、8px（注释）、7px（微型标签）
- **背景：** Slate-950（`#020617`），带有细微的 40px 网格图案

```svg
<!-- Background Grid Pattern -->
<pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
  <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1e293b" stroke-width="0.5"/>
</pattern>
```

## 技术实现细节

### 组件渲染
组件使用圆角矩形（`rx="6"`）和 1.5px 描边。为防止箭头透过半透明填充显示，采用**双矩形遮罩技术**：
1. 绘制不透明背景矩形（`#0f172a`）
2. 在其上绘制带半透明样式的矩形

### 连接规则
- **Z 轴顺序：** 在 SVG 中尽早绘制箭头（网格之后），使其呈现在组件框后方
- **箭头端点：** 通过 SVG marker 定义
- **安全流：** 使用玫红色（`#fb7185`）虚线
- **边界：**
  - *安全组：* 虚线（`4,4`），玫红色
  - *区域：* 大虚线（`8,4`），琥珀色，`rx="12"`

### 间距与布局逻辑
- **标准高度：** 60px（服务）；80–120px（大型组件）
- **垂直间距：** 组件之间至少 40px
- **消息总线：** 必须放在服务之间的间隙中，不得与服务重叠
- **图例位置：** **至关重要。** 必须置于所有边界框之外。计算所有边界中最低的 Y 坐标，并将图例放在其下方至少 20px 处。

## 文档结构

生成的 HTML 文件采用四部分布局：
1. **页眉：** 标题、脉冲圆点指示器和副标题
2. **主 SVG：** 图表位于带圆角边框的卡片内
3. **摘要卡片：** 图表下方由三张卡片组成的网格，用于展示高层信息
4. **页脚：** 精简的元数据

### 信息卡片模式
```html
<div class="card">
  <div class="card-header">
    <div class="card-dot cyan"></div>
    <h3>Title</h3>
  </div>
  <ul>
    <li>• Item one</li>
    <li>• Item two</li>
  </ul>
</div>
```

## 输出要求
- **单文件：** 一个自包含的 `.html` 文件
- **无外部依赖：** 所有 CSS 和 SVG 均须内联（Google Fonts 除外）
- **无 JavaScript：** 所有动画（例如脉冲圆点）均使用纯 CSS
- **兼容性：** 必须能在任意现代 Web 浏览器中正确渲染

## 模板参考

加载完整 HTML 模板，以获取精确结构、CSS 和 SVG 组件示例：

```
skill_view(name="architecture-diagram", file_path="templates/template.html")
```

模板包含每种组件类型（前端、后端、数据库、云、安全）、箭头样式（标准、虚线、曲线）、安全组、区域边界和图例的可运行示例——生成图表时应以其为结构参考。
