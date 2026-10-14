# Mobject 参考手册

屏幕上所有可见内容都是 Mobject。它们具有位置、颜色和不透明度等属性，并且可以制作动画。

## 文本

```python
title = Text("Hello World", font_size=48, color=BLUE)
eq = MathTex(r"E = mc^2", font_size=40)

# Multi-part (for selective coloring)
eq = MathTex(r"a^2", r"+", r"b^2", r"=", r"c^2")
eq[0].set_color(RED)
eq[4].set_color(BLUE)

# Mixed text and math
t = Tex(r"The area is $\pi r^2$", font_size=36)

# Styled markup
t = MarkupText('<span foreground="#58C4DD">Blue</span> text', font_size=30)
```

**对于任何包含反斜杠的字符串，始终使用原始字符串（`r""`）。**

## 形状

```python
circle = Circle(radius=1, color=BLUE, fill_opacity=0.5)
square = Square(side_length=2, color=RED)
rect = Rectangle(width=4, height=2, color=GREEN)
dot = Dot(point=ORIGIN, radius=0.08, color=YELLOW)
line = Line(LEFT * 2, RIGHT * 2, color=WHITE)
arrow = Arrow(LEFT, RIGHT, color=ORANGE)
rrect = RoundedRectangle(corner_radius=0.3, width=4, height=2)
brace = Brace(rect, DOWN, color=YELLOW)
```

## 多边形与圆弧

```python
# Arbitrary polygon from vertices
poly = Polygon(LEFT, UP * 2, RIGHT, color=GREEN, fill_opacity=0.3)

# Regular n-sided polygon
hexagon = RegularPolygon(n=6, color=TEAL, fill_opacity=0.4)

# Triangle (shorthand for RegularPolygon(n=3))
tri = Triangle(color=YELLOW, fill_opacity=0.5)

# Arc (portion of a circle)
arc = Arc(radius=2, start_angle=0, angle=PI / 2, color=BLUE)

# Arc between two points
arc_between = ArcBetweenPoints(LEFT * 2, RIGHT * 2, angle=TAU / 4, color=RED)

# Curved arrow (arc with tip)
curved_arrow = CurvedArrow(LEFT * 2, RIGHT * 2, color=ORANGE)
```

## 扇形与圆环

```python
# Sector (pie slice)
sector = Sector(outer_radius=2, start_angle=0, angle=PI / 3, fill_opacity=0.7, color=BLUE)

# Annulus (ring)
ring = Annulus(inner_radius=1, outer_radius=2, fill_opacity=0.5, color=GREEN)

# Annular sector (partial ring)
partial_ring = AnnularSector(
    inner_radius=1, outer_radius=2,
    angle=PI / 2, start_angle=0,
    fill_opacity=0.7, color=TEAL
)

# Cutout (punch holes in a shape)
background = Square(side_length=4, fill_opacity=1, color=BLUE)
hole = Circle(radius=0.5)
cutout = Cutout(background, hole, fill_opacity=1, color=BLUE)
```

适用场景：饼图、环形进度指示器、带圆弧的维恩图、几何证明。

## 定位

```python
mob.move_to(ORIGIN)                        # center
mob.move_to(UP * 2 + RIGHT)               # relative
label.next_to(circle, DOWN, buff=0.3)     # next to another
title.to_edge(UP, buff=0.5)               # screen edge (buff >= 0.5!)
mob.to_corner(UL, buff=0.5)               # corner
```

## VGroup 与 Group

**VGroup** 用于形状集合（仅限 VMobject——Circle、Square、Arrow、Line、MathTex）：
```python
shapes = VGroup(circle, square, arrow)
shapes.arrange(DOWN, buff=0.5)
shapes.set_color(BLUE)
```

**Group** 用于混合类型的集合（Text + 形状，或任意 Mobject 类型）：
```python
# Text objects are Mobjects, not VMobjects — use Group when mixing
labeled_shape = Group(circle, Text("Label").next_to(circle, DOWN))
labeled_shape.move_to(ORIGIN)

# FadeOut everything on screen (may contain mixed types)
self.play(FadeOut(Group(*self.mobjects)))
```

**规则：如果组中包含任何 `Text()` 对象，请使用 `Group`，而非 `VGroup`。** 在 Manim CE v0.20+ 中，VGroup 会引发 TypeError。MathTex 和 Tex 都是 VMobject，可以与 VGroup 一起使用。

两者都支持 `arrange()`、`arrange_in_grid()`、`set_opacity()`、`shift()`、`scale()`、`move_to()`。

## 样式

```python
mob.set_color(BLUE)
mob.set_fill(RED, opacity=0.5)
mob.set_stroke(WHITE, width=2)
mob.set_opacity(0.4)
mob.set_z_index(1)                         # layering
```

## 专用 Mobject

```python
nl = NumberLine(x_range=[-3, 3, 1], length=8, include_numbers=True)
table = Table([["A", "B"], ["C", "D"]], row_labels=[Text("R1"), Text("R2")])
code = Code("example.py", tab_width=4, font_size=20, language="python")
highlight = SurroundingRectangle(target, color=YELLOW, buff=0.2)
bg = BackgroundRectangle(equation, fill_opacity=0.7, buff=0.2)
```

## 自定义 Mobject

```python
class NetworkNode(Group):
    def __init__(self, label_text, color=BLUE, **kwargs):
        super().__init__(**kwargs)
        self.circle = Circle(radius=0.4, color=color, fill_opacity=0.3)
        self.label = Text(label_text, font_size=20).move_to(self.circle)
        self.add(self.circle, self.label)
```

## 矩阵 Mobject

将矩阵显示为由数字或 Mobject 组成的网格：

```python
# Integer matrix
m = IntegerMatrix([[1, 2], [3, 4]])

# Decimal matrix (control decimal places)
m = DecimalMatrix([[1.5, 2.7], [3.1, 4.9]], element_to_mobject_config={"num_decimal_places": 2})

# Mobject matrix (any mobject in each cell)
m = MobjectMatrix([
    [MathTex(r"\pi"), MathTex(r"e")],
    [MathTex(r"\phi"), MathTex(r"\tau")]
])

# Bracket types: "(" "[" "|" or "\\{"
m = IntegerMatrix([[1, 0], [0, 1]], left_bracket="[", right_bracket="]")
```

适用场景：线性代数、变换矩阵、方程组系数展示。

## 常量

方向：`UP, DOWN, LEFT, RIGHT, ORIGIN, UL, UR, DL, DR`
颜色：`RED, BLUE, GREEN, YELLOW, WHITE, GRAY, ORANGE, PINK, PURPLE, TEAL, GOLD`
画幅：`config.frame_width = 14.222, config.frame_height = 8.0`

## SVGMobject——导入 SVG 文件

```python
logo = SVGMobject("path/to/logo.svg")
logo.set_color(WHITE).scale(0.5).to_corner(UR)
self.play(FadeIn(logo))

# SVG submobjects are individually animatable
for part in logo.submobjects:
    self.play(part.animate.set_color(random_color()))
```

## ImageMobject——显示图像

```python
img = ImageMobject("screenshot.png")
img.set_height(3).to_edge(RIGHT)
self.play(FadeIn(img))
```

注意：图像无法使用 `.animate` 添加动画（它们是光栅图像，而非矢量图形）。只能使用 `FadeIn`/`FadeOut` 以及 `shift`/`scale`。

## Variable——自动更新的显示内容

```python
var = Variable(0, Text("x"), num_decimal_places=2)
var.move_to(ORIGIN)
self.add(var)

# Animate the value
self.play(var.tracker.animate.set_value(5), run_time=2)
# Display auto-updates: "x = 5.00"
```

对于简单的带标签数值显示，这比手动组合 `DecimalNumber` + `add_updater` 更简洁。

## BulletedList

```python
bullets = BulletedList(
    "First key point",
    "Second important fact",
    "Third conclusion",
    font_size=28
)
bullets.to_edge(LEFT, buff=1.0)
self.play(Write(bullets))

# Highlight individual items
self.play(bullets[1].animate.set_color(YELLOW))
```

## DashedLine 与角度标记

```python
# Dashed line (asymptotes, construction lines)
dashed = DashedLine(LEFT * 3, RIGHT * 3, color=SUBTLE, dash_length=0.15)

# Angle marker between two lines
line1 = Line(ORIGIN, RIGHT * 2)
line2 = Line(ORIGIN, UP * 2 + RIGHT)
angle = Angle(line1, line2, radius=0.5, color=YELLOW)
angle_label = angle.get_value()  # returns the angle in radians

# Right angle marker
right_angle = RightAngle(line1, Line(ORIGIN, UP * 2), length=0.3, color=WHITE)
```

## 布尔运算（CSG）

对二维形状进行合并、相减或求交：

```python
circle = Circle(radius=1.5, color=BLUE, fill_opacity=0.5).shift(LEFT * 0.5)
square = Square(side_length=2, color=RED, fill_opacity=0.5).shift(RIGHT * 0.5)

# Union, Intersection, Difference, Exclusion
union = Union(circle, square, color=GREEN, fill_opacity=0.5)
intersect = Intersection(circle, square, color=YELLOW, fill_opacity=0.5)
diff = Difference(circle, square, color=PURPLE, fill_opacity=0.5)
exclude = Exclusion(circle, square, color=ORANGE, fill_opacity=0.5)
```

适用场景：维恩图、集合论、几何证明、面积计算。

## LabeledArrow / LabeledLine

```python
# Arrow with built-in label (auto-positioned)
arr = LabeledArrow(Text("force", font_size=18), start=LEFT, end=RIGHT, color=RED)

# Line with label
line = LabeledLine(Text("d = 5m", font_size=18), start=LEFT * 2, end=RIGHT * 2)
```

自动处理标签定位——比手动组合 `Arrow` + `Text().next_to()` 更简洁。

## 按子字符串设置文本颜色/字体/样式（t2c、t2f、t2s、t2w）

```python
# Color specific words (t2c = text-to-color)
text = Text(
    "Gradient descent minimizes the loss function",
    t2c={"Gradient descent": BLUE, "loss function": RED}
)

# Different fonts per word (t2f = text-to-font)
text = Text(
    "Use Menlo for code and Inter for prose",
    t2f={"Menlo": "Menlo", "Inter": "Inter"}
)

# Italic/slant per word (t2s = text-to-slant)
text = Text("Normal and italic text", t2s={"italic": ITALIC})

# Bold per word (t2w = text-to-weight)
text = Text("Normal and bold text", t2w={"bold": BOLD})
```

这比创建多个独立 Text 对象再将其编组简洁得多。

## 使用背景描边提高复杂背景上的可读性

当文本与其他内容（函数图像、示意图、图片等）重叠时，在其后方添加深色描边：

```python
# CE syntax:
label.set_stroke(BLACK, width=5, background=True)

# Apply to a group
for mob in labels:
    mob.set_stroke(BLACK, width=4, background=True)
```

这正是 3Blue1Brown 无需使用 BackgroundRectangle，便能让文本在复杂背景上保持清晰可读的方式。

## 复函数变换

将复函数应用到整个 Mobject——对平面进行变换：

```python
c_grid = ComplexPlane()
moving_grid = c_grid.copy()
moving_grid.prepare_for_nonlinear_transform()  # adds more sample points for smooth deformation

self.play(
    moving_grid.animate.apply_complex_function(lambda z: z**2),
    run_time=5,
)

# Also works with R3->R3 functions:
self.play(grid.animate.apply_function(
    lambda p: [p[0] + 0.5 * math.sin(p[1]), p[1] + 0.5 * math.sin(p[0]), p[2]]
), run_time=5)
```

**关键：** 应用非线性函数之前，务必先调用 `prepare_for_nonlinear_transform()`——否则网格采样点过少，变形会显得生硬并产生明显折角。
