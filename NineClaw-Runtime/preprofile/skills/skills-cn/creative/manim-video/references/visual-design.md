# 视觉设计原则

## 12 条核心原则

1. **先几何，后代数**——先展示形状，再展示方程。
2. **透明度分层**——PRIMARY=1.0，CONTEXT=0.4，GRID=0.15。通过亮度引导注意力。
3. **每个场景只引入一个新思想**——每个场景只引入一个概念。
4. **空间一致性**——同一概念始终占据屏幕上的同一区域。
5. **颜色即含义**——为概念而非 Mobject 分配颜色。如果速度是蓝色，就始终保持蓝色。
6. **渐进式披露**——先展示最简单的版本，再逐步增加复杂度。
7. **变换，而非替换**——使用 Transform/ReplacementTransform 来展示关联。
8. **留出呼吸空间**——展示新内容后至少执行 `self.wait(1.5)`。
9. **视觉重量平衡**——不要把所有内容都堆在一侧。
10. **一致的运动语汇**——选择少量动画类型并反复使用。
11. **深色背景，浅色内容**——#1C1C1C 到 #2D2B55 的背景可最大化对比度。
12. **有意留白**——至少保留画面 15% 的空白。

## 布局模板

### FULL_CENTER
一个主要元素居中，标题在上，注释在下。
最适合：单个方程、单幅图示、标题卡。

### LEFT_RIGHT
两个元素并排，分别位于 x=-3.5 和 x=3.5。
最适合：方程 + 视觉图示、前后对比、比较。

### TOP_BOTTOM
主要元素位于 y=1.5，辅助内容位于 y=-1.5。
最适合：概念 + 示例、定理 + 情形。

### GRID
通过 `arrange_in_grid()` 排列多个元素。
最适合：对比矩阵、多步骤流程。

### PROGRESSIVE
元素逐个出现，沿 DOWN 方向排列，并设置 aligned_edge=LEFT。
最适合：算法、证明、分步流程。

### ANNOTATED_DIAGRAM
中央图示配以浮动标签，并用箭头连接。
最适合：架构图、带注释的图示。

## 调色板

### 经典 3B1B
```python
BG="#1C1C1C"; PRIMARY=BLUE; SECONDARY=GREEN; ACCENT=YELLOW; HIGHLIGHT=RED
```

### 暖色学术风
```python
BG="#2D2B55"; PRIMARY="#FF6B6B"; SECONDARY="#FFD93D"; ACCENT="#6BCB77"
```

### 霓虹科技风
```python
BG="#0A0A0A"; PRIMARY="#00F5FF"; SECONDARY="#FF00FF"; ACCENT="#39FF14"
```

## 字体选择

**所有文本都使用等宽字体。** Manim 的 Pango 文本渲染器在所有字号和分辨率下使用比例字体（Helvetica、Inter、SF Pro、Arial）时都会产生错误的字距调整。字符会相互重叠，间距也不一致。这是 Pango 的根本限制，并非 Manim 的缺陷。

等宽字体的字符宽度固定——其设计本身就不会产生字距调整问题。

### 推荐字体

| 用途 | 字体 | 后备字体 |
|----------|------|----------|
| **所有文本（默认）** | `"Menlo"` | `"Courier New"`、`"DejaVu Sans Mono"` |
| 代码、标签 | `"JetBrains Mono"`、`"SF Mono"` | `"Menlo"` |
| 数学公式 | 使用 `MathTex`（通过 LaTeX 而非 Pango 渲染） | — |

```python
MONO = "Menlo"  # define once at top of file

title = Text("Fourier Series", font_size=48, color=PRIMARY, weight=BOLD, font=MONO)
label = Text("n=1: (4/pi) sin(x)", font_size=20, color=BLUE, font=MONO)
note = Text("Convergence at discontinuities", font_size=18, color=DIM, font=MONO)

# Math — always use MathTex, not Text
equation = MathTex(r"\nabla L = \frac{\partial L}{\partial w}")
```

### 可以使用比例字体的情况

字号较大（font_size >= 48）且字符串较短（1–3 个单词）的标题文本可以使用比例字体，而不会出现明显的字距问题。除此之外——标签、说明、多词文本、小字号文本——都应使用等宽字体。

### 字体可用性

- **macOS**：Menlo（预装）、SF Mono
- **Linux**：DejaVu Sans Mono（预装）、Liberation Mono
- **跨平台**：JetBrains Mono（从 jetbrains.com 安装）

`"Menlo"` 是最稳妥的默认选择——macOS 已预装，而 Linux 系统会回退到 DejaVu Sans Mono。

### 精细文本控制

`Text()` 不支持 `letter_spacing` 或字距调整参数。若需精细控制，请使用带 Pango 属性的 `MarkupText`：

```python
# Letter spacing (Pango units: 1/1024 of a point)
MarkupText('<span letter_spacing="6000">HERMES</span>', font_size=18, font="Menlo")

# Bold specific words
MarkupText('This is <b>important</b>', font_size=24, font="Menlo")

# Color specific words
MarkupText('Red <span foreground="#FF6B6B">warning</span>', font_size=24, font="Menlo")
```

### 最小字号

`font_size=18` 是在任何分辨率下保证文本可读的最小字号。小于 18 时，字符在 `-ql` 下会变得模糊，即使在 `-qh` 下也几乎难以辨认。

## 视觉层级检查清单

对每一帧检查：
1. 唯一需要关注的内容是什么？（最亮/最大）
2. 哪些是上下文？（降低至 0.3–0.4）
3. 哪些是结构性元素？（降低至 0.15）
4. 空白空间足够吗？（>15%）
5. 所有文本在手机尺寸下都清晰可读吗？
