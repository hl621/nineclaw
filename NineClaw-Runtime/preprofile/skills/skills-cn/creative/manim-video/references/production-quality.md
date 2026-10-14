# 制作质量检查清单

用于确保动画输出达到可发布标准的规范与检查项。

## 编码前检查清单

在编写任何 Manim 代码之前：

- [ ] 已编写旁白脚本，并标出视觉节拍
- [ ] 已列出场景，并注明每个场景的目的、时长和布局
- [ ] 已定义配色方案并指定各颜色的含义（`PRIMARY` = 核心概念，等等）
- [ ] 已将 `MONO = "Menlo"` 设为字体常量
- [ ] 已确定目标分辨率和宽高比

## 文本质量

### 防止重叠

```python
# RULE: buff >= 0.5 for edge text
label.to_edge(DOWN, buff=0.5)     # GOOD
label.to_edge(DOWN, buff=0.3)     # BAD — may clip

# RULE: FadeOut previous before adding new at same position
self.play(ReplacementTransform(note1, note2))  # GOOD
self.play(Write(note2))                          # BAD — overlaps note1

# RULE: Reduce font size for dense scenes
# When > 4 text elements visible, use font_size=20 not 28
```

### 宽度限制

过长的文本字符串会超出画面：

```python
# RULE: Set max width for any text that might be long
text = Text("This is a potentially long description", font_size=22, font=MONO)
if text.width > config.frame_width - 1.0:
    text.set_width(config.frame_width - 1.0)
```

### 字体一致性

```python
# RULE: Define MONO once, use everywhere
MONO = "Menlo"

# WRONG: mixing fonts
Text("Title", font="Helvetica")
Text("Label", font="Arial")
Text("Code", font="Courier")

# RIGHT: one font
Text("Title", font=MONO, weight=BOLD, font_size=48)
Text("Label", font=MONO, font_size=20)
Text("Code", font=MONO, font_size=18)
```

## 空间布局

### 坐标预算

可见画面约为 14.2 宽 × 8.0 高（默认 16:9）。计入必要的边距后：

```
Usable area: x ∈ [-6.5, 6.5], y ∈ [-3.5, 3.5]
Top title zone: y ∈ [2.5, 3.5]
Bottom note zone: y ∈ [-3.5, -2.5]
Main content: y ∈ [-2.5, 2.5], x ∈ [-6.0, 6.0]
```

### 充分利用画面

空荡的场景看起来像是尚未完成。如果主体内容较小，请添加上下文元素：
- 在内容后方添加调暗的网格/坐标轴
- 在顶部添加标题/副标题
- 在底部添加来源引用
- 添加低不透明度的装饰性几何图形

### 同时显示的元素数量上限

**硬性上限：6 个处于活跃可见状态的元素。** 超过这一数量，观众便无法兼顾所有内容。如果需要更多元素：
- 将旧元素的不透明度降至 0.3
- 移除已经完成其作用的元素
- 拆分为两个场景

## 动画质量

### 多样性检查

检查任意两个连续场景是否使用了完全相同的以下要素：
- 动画类型（如果场景 3 的所有内容都使用 Write，场景 4 应使用 FadeIn 或 Create）
- 颜色强调方式（轮换使用配色方案中的颜色）
- 布局（居中、左右、网格——交替使用）
- 节奏（如果场景 2 缓慢而从容，场景 3 可以更快一些）

### 节奏曲线

优秀的视频会遵循一条节奏曲线：

```
Slow ──→ Medium ──→ FAST (climax) ──→ Slow (conclusion)

Scene 1: Slow (introduction, setup)
Scene 2: Medium (building understanding)
Scene 3: Medium-Fast (core content, lots of animation)
Scene 4: FAST (montage of applications/results)
Scene 5: Slow (conclusion, key takeaway)
```

### 转场质量

场景之间：
- **干净退出**：`self.play(FadeOut(Group(*self.mobjects)), run_time=0.5)`
- **短暂停顿**：淡出后、下一场景的首段动画前执行 `self.wait(0.3)`
- **切勿硬切**：转场始终应使用动画

## 色彩质量

### 深色背景上的调暗处理

在白色背景上看起来鲜艳的颜色，在深色背景（#0D1117、#1C1C1C）上可能显得浑浊。请测试你的配色方案：

```python
# Colors that work well on dark backgrounds:
# Bright and saturated: #58C4DD, #83C167, #FFFF00, #FF6B6B
# Colors that DON'T work: #666666 (invisible), #2244AA (too dark)

# RULE: Structural elements (axes, grids) at opacity 0.15
# Context elements at 0.3-0.4
# Primary elements at 1.0
```

### 颜色含义的一致性

一旦为某种颜色指定了含义，该颜色在整段视频中都应保持这一含义：

```python
# If PRIMARY (#58C4DD) means "the model" in Scene 1,
# it means "the model" in every scene.
# Never reuse PRIMARY for a different concept later.
```

## 数据可视化质量

### 图表的最低要求

- 每条坐标轴都有标签
- Y 轴范围从 0 开始（否则须有清晰的断轴标记）
- 柱形/折线颜色与图例一致
- 在关键数据点上标注数值（至少标注最大值和对比点）

### 动画计数器

展示数字变化时：
```python
# GOOD: DecimalNumber with smooth animation
counter = DecimalNumber(0, font_size=48, num_decimal_places=0, font="Menlo")
self.play(counter.animate.set_value(1000), run_time=3, rate_func=rush_from)

# BAD: Text that jumps between values
```

## 渲染前检查清单

运行 `manim -qh` 之前：

- [ ] 所有场景均能在 `-ql` 下无错误渲染
- [ ] 对文本密集型场景使用 `-qm` 预览静帧（检查字距调整）
- [ ] 每个场景都已设置背景颜色（`self.camera.background_color = BG`）
- [ ] 每段重要动画都使用了 `add_subcaption()` 或 `subcaption=`
- [ ] 没有小于 font_size=18 的文本
- [ ] 没有使用比例字体的文本（使用等宽字体）
- [ ] 所有 `.to_edge()` 调用中的 buff >= 0.5
- [ ] 每个场景结束时均干净退出（FadeOut 所有元素）
- [ ] 每次揭示后都有 `self.wait()`
- [ ] 使用颜色常量（场景代码中没有硬编码的十六进制字符串）
- [ ] 所有场景都使用相同的质量标志（不要混用 `-ql` 和 `-qh`）

## 渲染后检查清单

最终视频拼接完成后：

- [ ] 以 1 倍速完整观看视频——是否有任何地方显得过于仓促？
- [ ] 是否存在两个内容同时运动、从而令人困惑的时刻？
- [ ] 每个文本标签是否都有足够的阅读时间？
- [ ] 场景之间的转场是否流畅（没有黑帧，也没有突兀的切换）？
- [ ] 音频是否与画面同步（如果使用了旁白）？
- [ ] 类似 Gibbs 所说的“第一印象”是否良好？开头 5 秒决定了观众是否会继续观看
