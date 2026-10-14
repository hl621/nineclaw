---
name: excalidraw
description: "手绘风格的 Excalidraw JSON 图表（架构图、流程图、时序图）。"
version: 1.0.1
author: Hermes Agent
license: MIT
dependencies: []
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Excalidraw, Diagrams, Flowcharts, Architecture, Visualization, JSON]
    related_skills: []

---

# Excalidraw 图表技能

通过编写标准的 Excalidraw 元素 JSON 并将其保存为 `.excalidraw` 文件来创建图表。这些文件可以拖放到 [excalidraw.com](https://excalidraw.com) 中查看和编辑。无需账户、API 密钥或渲染库——只需 JSON。

## 何时使用

为架构图、流程图、时序图、概念图等生成 `.excalidraw` 文件。文件可以在 excalidraw.com 打开，也可以上传并生成可分享的链接。

## 工作流程

1. **加载此技能**（你已经完成）
2. **编写元素 JSON**——一个由 Excalidraw 元素对象组成的数组
3. **保存文件**——使用 `write_file` 创建 `.excalidraw` 文件
4. **可选：上传文件**——运行 `scripts/upload.py`，并通过 `terminal` 生成可分享的链接

### 保存图表

将元素数组包装在标准的 `.excalidraw` 外层结构中，并使用 `write_file` 保存：

```json
{
  "type": "excalidraw",
  "version": 2,
  "source": "hermes-agent",
  "elements": [ ...your elements array here... ],
  "appState": {
    "viewBackgroundColor": "#ffffff"
  }
}
```

可以保存到任意路径，例如 `~/diagrams/my_diagram.excalidraw`。

### 上传并生成可分享链接

通过终端运行上传脚本（位于此技能的 `scripts/` 目录中）：

```bash
python skills/creative/excalidraw/scripts/upload.py ~/diagrams/my_diagram.excalidraw
```

此脚本会将文件上传到 excalidraw.com（无需账户），并输出一个可分享的 URL。需要安装 `cryptography` pip 包（`pip install cryptography`）。

---

## 元素格式参考

### 必填字段（所有元素）
`type`、`id`（唯一字符串）、`x`、`y`、`width`、`height`

### 默认值（可省略——系统会自动应用）
- `strokeColor`：`"#1e1e1e"`
- `backgroundColor`：`"transparent"`
- `fillStyle`：`"solid"`
- `strokeWidth`：`2`
- `roughness`：`1`（手绘效果）
- `opacity`：`100`

画布背景为白色。

### 元素类型

**矩形**：
```json
{ "type": "rectangle", "id": "r1", "x": 100, "y": 100, "width": 200, "height": 100 }
```
- 使用 `roundness: { "type": 3 }` 创建圆角
- 使用 `backgroundColor: "#a5d8ff"`、`fillStyle: "solid"` 进行填充

**椭圆**：
```json
{ "type": "ellipse", "id": "e1", "x": 100, "y": 100, "width": 150, "height": 150 }
```

**菱形**：
```json
{ "type": "diamond", "id": "d1", "x": 100, "y": 100, "width": 150, "height": 150 }
```

**带标签的形状（容器绑定）**——创建一个绑定到该形状的文本元素：

> **警告：** 不要在形状上使用 `"label": { "text": "..." }`。这不是有效的
> Excalidraw 属性，会被静默忽略，从而生成空白形状。你必须
> 使用下面的容器绑定方法。

形状需要通过 `boundElements` 列出文本，而文本需要通过 `containerId` 反向指向形状：
```json
{ "type": "rectangle", "id": "r1", "x": 100, "y": 100, "width": 200, "height": 80,
  "roundness": { "type": 3 }, "backgroundColor": "#a5d8ff", "fillStyle": "solid",
  "boundElements": [{ "id": "t_r1", "type": "text" }] },
{ "type": "text", "id": "t_r1", "x": 105, "y": 110, "width": 190, "height": 25,
  "text": "Hello", "fontSize": 20, "fontFamily": 1, "strokeColor": "#1e1e1e",
  "textAlign": "center", "verticalAlign": "middle",
  "containerId": "r1", "originalText": "Hello", "autoResize": true }
```
- 适用于矩形、椭圆和菱形
- 设置 `containerId` 后，Excalidraw 会自动将文本居中
- 文本的 `x`/`y`/`width`/`height` 只是近似值——Excalidraw 会在加载时重新计算这些值
- `originalText` 应与 `text` 一致
- 始终包含 `fontFamily: 1`（Virgil/手绘字体）

**带标签的箭头**——使用相同的容器绑定方法：
```json
{ "type": "arrow", "id": "a1", "x": 300, "y": 150, "width": 200, "height": 0,
  "points": [[0,0],[200,0]], "endArrowhead": "arrow",
  "boundElements": [{ "id": "t_a1", "type": "text" }] },
{ "type": "text", "id": "t_a1", "x": 370, "y": 130, "width": 60, "height": 20,
  "text": "connects", "fontSize": 16, "fontFamily": 1, "strokeColor": "#1e1e1e",
  "textAlign": "center", "verticalAlign": "middle",
  "containerId": "a1", "originalText": "connects", "autoResize": true }
```

**独立文本**（仅用于标题和注释——不使用容器）：
```json
{ "type": "text", "id": "t1", "x": 150, "y": 138, "text": "Hello", "fontSize": 20,
  "fontFamily": 1, "strokeColor": "#1e1e1e", "originalText": "Hello", "autoResize": true }
```
- `x` 表示左边缘。若要以位置 `cx` 为中心：`x = cx - (text.length * fontSize * 0.5) / 2`
- 定位时不要依赖 `textAlign` 或 `width`

**箭头**：
```json
{ "type": "arrow", "id": "a1", "x": 300, "y": 150, "width": 200, "height": 0,
  "points": [[0,0],[200,0]], "endArrowhead": "arrow" }
```
- `points`：`[dx, dy]` 偏移量，以元素 `x`、`y` 为参照
- `endArrowhead`：`null` | `"arrow"` | `"bar"` | `"dot"` | `"triangle"`
- `strokeStyle`：`"solid"`（默认）| `"dashed"` | `"dotted"`

### 箭头绑定（将箭头连接到形状）

```json
{
  "type": "arrow", "id": "a1", "x": 300, "y": 150, "width": 150, "height": 0,
  "points": [[0,0],[150,0]], "endArrowhead": "arrow",
  "startBinding": { "elementId": "r1", "fixedPoint": [1, 0.5] },
  "endBinding": { "elementId": "r2", "fixedPoint": [0, 0.5] }
}
```

`fixedPoint` 坐标：`top=[0.5,0]`、`bottom=[0.5,1]`、`left=[0,0.5]`、`right=[1,0.5]`

### 绘制顺序（z-order）
- 数组顺序 = z-order（第一个在最底层，最后一个在最上层）
- 按顺序逐步输出：背景区域 → 形状 → 其绑定文本 → 其箭头 → 下一个形状
- 错误：先输出所有矩形，再输出所有文本，最后输出所有箭头
- 正确：bg_zone → shape1 → text_for_shape1 → arrow1 → arrow_label_text → shape2 → text_for_shape2 → ...
- 始终将绑定文本元素紧跟在其容器形状之后

### 尺寸指南

**字体大小：**
- 正文、标签和描述的最小 `fontSize`：**16**
- 标题和小标题的最小 `fontSize`：**20**
- 仅次要注释可使用的最小 `fontSize`：**14**（谨慎使用）
- 绝不要使用低于 14 的 `fontSize`

**元素尺寸：**
- 带标签矩形/椭圆的最小形状尺寸：120x60
- 元素之间至少留出 20-30px 的间距
- 与其使用许多微小元素，不如使用数量更少、尺寸更大的元素

### 调色板

完整颜色表请参阅 `references/colors.md`。快速参考：

| 用途 | 填充颜色 | 十六进制值 |
|-----|-----------|-----|
| 主要 / 输入 | 浅蓝色 | `#a5d8ff` |
| 成功 / 输出 | 浅绿色 | `#b2f2bb` |
| 警告 / 外部 | 浅橙色 | `#ffd8a8` |
| 处理 / 特殊 | 浅紫色 | `#d0bfff` |
| 错误 / 关键 | 浅红色 | `#ffc9c9` |
| 注释 / 决策 | 浅黄色 | `#fff3bf` |
| 存储 / 数据 | 浅青色 | `#c3fae8` |

### 提示
- 在整个图表中一致地使用调色板
- **文本对比度至关重要**——绝不要在白色背景上使用浅灰色。白色背景上的最浅文本颜色为：`#757575`
- 不要在文本中使用表情符号——它们无法用 Excalidraw 的字体渲染
- 深色模式图表请参阅 `references/dark-mode.md`
- 更大型的示例请参阅 `references/examples.md`

