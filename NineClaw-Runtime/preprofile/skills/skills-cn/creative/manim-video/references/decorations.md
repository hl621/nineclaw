# 装饰与视觉润色

装饰是用于注释、突出显示其他 mobject 或为其添加边框的 mobject。它们能让技术上正确的动画呈现出精致的视觉效果。

## SurroundingRectangle（环绕矩形）

在任意 mobject 周围绘制矩形。它是突出显示内容的首选：

```python
highlight = SurroundingRectangle(
    equation[2],            # the term to highlight
    color=YELLOW,
    buff=0.15,              # padding between content and border
    corner_radius=0.1,      # rounded corners
    stroke_width=2
)
self.play(Create(highlight))
self.wait(1)
self.play(FadeOut(highlight))
```

### 围住等式的一部分

```python
eq = MathTex(r"E", r"=", r"m", r"c^2")
box = SurroundingRectangle(eq[2:], color=YELLOW, buff=0.1)  # highlight "mc²"
label = Text("mass-energy", font_size=18, font="Menlo", color=YELLOW)
label.next_to(box, DOWN, buff=0.2)
self.play(Create(box), FadeIn(label))
```

## BackgroundRectangle（背景矩形）

在文本后方添加半透明背景，使其在复杂场景中仍清晰易读：

```python
bg = BackgroundRectangle(equation, fill_opacity=0.7, buff=0.2, color=BLACK)
self.play(FadeIn(bg), Write(equation))

# Or using set_stroke for a "backdrop" effect on the text itself:
label.set_stroke(BLACK, width=5, background=True)
```

对于覆盖在图表或示意图上的文本标签，`set_stroke(background=True)` 方法更简洁。

## Brace 和 BraceLabel

用于注释示意图或等式中某些部分的花括号：

```python
brace = Brace(equation[2:4], DOWN, color=YELLOW)
brace_label = brace.get_text("these terms", font_size=20)
self.play(GrowFromCenter(brace), FadeIn(brace_label))

# Between two specific points
brace = BraceBetweenPoints(point_a, point_b, direction=UP)
```

### Brace 的放置位置

```python
# Below a group
Brace(group, DOWN)
# Above a group
Brace(group, UP)
# Left of a group
Brace(group, LEFT)
# Right of a group
Brace(group, RIGHT)
```

## 用于注释的箭头

### 指向 mobject 的直箭头

```python
arrow = Arrow(
    start=label.get_bottom(),
    end=target.get_top(),
    color=YELLOW,
    stroke_width=2,
    buff=0.1,                    # gap between arrow tip and target
    max_tip_length_to_length_ratio=0.15  # small arrowhead
)
self.play(GrowArrow(arrow), FadeIn(label))
```

### 曲线箭头

```python
arrow = CurvedArrow(
    start_point=source.get_right(),
    end_point=target.get_left(),
    angle=PI/4,                  # curve angle
    color=PRIMARY
)
```

### 使用箭头添加标签

```python
# LabeledArrow: arrow with built-in text label
arr = LabeledArrow(
    Text("gradient", font_size=16, font="Menlo"),
    start=point_a, end=point_b, color=RED
)
```

## DashedLine 和 DashedVMobject

```python
# Dashed line (for asymptotes, construction lines, implied connections)
asymptote = DashedLine(
    axes.c2p(2, -3), axes.c2p(2, 3),
    color=YELLOW, dash_length=0.15
)

# Make any VMobject dashed
dashed_circle = DashedVMobject(Circle(radius=2, color=BLUE), num_dashes=30)
```

## Angle 和 RightAngle 标记

```python
line1 = Line(ORIGIN, RIGHT * 2)
line2 = Line(ORIGIN, UP * 2 + RIGHT)

# Angle arc between two lines
angle = Angle(line1, line2, radius=0.5, color=YELLOW)
angle_value = angle.get_value()  # radians

# Right angle marker (the small square)
right_angle = RightAngle(line1, Line(ORIGIN, UP * 2), length=0.3, color=WHITE)
```

## Cross（删除线）

将某项标记为错误或已弃用：

```python
cross = Cross(old_equation, color=RED, stroke_width=4)
self.play(Create(cross))
# Then show the correct version
```

## Underline（下划线）

```python
underline = Underline(important_text, color=ACCENT, stroke_width=3)
self.play(Create(underline))
```

## 颜色突出显示工作流

### 方法 1：创建时使用 t2c

```python
text = Text("The gradient is negative here", t2c={"gradient": BLUE, "negative": RED})
```

### 方法 2：创建后使用 set_color_by_tex

```python
eq = MathTex(r"\nabla L = -\frac{\partial L}{\partial w}")
eq.set_color_by_tex(r"\nabla", BLUE)
eq.set_color_by_tex(r"\partial", RED)
```

### 方法 3：通过索引访问 submobject

```python
eq = MathTex(r"a", r"+", r"b", r"=", r"c")
eq[0].set_color(RED)    # "a"
eq[2].set_color(BLUE)   # "b"
eq[4].set_color(GREEN)  # "c"
```

## 组合使用注释

叠加多种注释以增强强调效果：

```python
# Highlight a term, add a brace, and an arrow — in sequence
box = SurroundingRectangle(eq[2], color=YELLOW, buff=0.1)
brace = Brace(eq[2], DOWN, color=YELLOW)
label = brace.get_text("learning rate", font_size=18)

self.play(Create(box))
self.wait(0.5)
self.play(FadeOut(box), GrowFromCenter(brace), FadeIn(label))
self.wait(1.5)
self.play(FadeOut(brace), FadeOut(label))
```

### 注释的生命周期

注释应遵循一定的节奏：
1. **出现** — 吸引注意力（Create、GrowFromCenter）
2. **停留** — 让观众阅读并理解（self.wait）
3. **消失** — 清理画面，为下一个内容腾出空间（FadeOut）

切勿让注释无限期地停留在画面上——一旦完成使命，它们就会成为视觉噪声。
