# 方程与 LaTeX 参考

## LaTeX 基础

```python
eq = MathTex(r"E = mc^2")
eq = MathTex(r"f(x) &= x^2 + 2x + 1 \\ &= (x + 1)^2")  # multi-line aligned
```

**始终使用原始字符串（`r""`）。**

## 分步推导

```python
step1 = MathTex(r"a^2 + b^2 = c^2")
step2 = MathTex(r"a^2 = c^2 - b^2")
self.play(Write(step1), run_time=1.5)
self.wait(1.5)
self.play(TransformMatchingTex(step1, step2), run_time=1.5)
```

## 选择性着色

```python
eq = MathTex(r"a^2", r"+", r"b^2", r"=", r"c^2")
eq[0].set_color(RED)
eq[4].set_color(GREEN)
```

## 逐步构建

```python
parts = MathTex(r"f(x)", r"=", r"\sum_{n=0}^{\infty}", r"\frac{f^{(n)}(a)}{n!}", r"(x-a)^n")
self.play(Write(parts[0:2]))
self.wait(0.5)
self.play(Write(parts[2]))
self.wait(0.5)
self.play(Write(parts[3:]))
```

## 突出显示

```python
highlight = SurroundingRectangle(eq[2], color=YELLOW, buff=0.1)
self.play(Create(highlight))
self.play(Indicate(eq[4], color=YELLOW))
```

## 标注

```python
brace = Brace(eq, DOWN, color=YELLOW)
label = brace.get_text("Fundamental Theorem", font_size=24)
self.play(GrowFromCenter(brace), Write(label))
```

## 常用 LaTeX

```python
MathTex(r"\frac{a}{b}")                  # fraction
MathTex(r"\alpha, \beta, \gamma")         # Greek
MathTex(r"\sum_{i=1}^{n} x_i")           # summation
MathTex(r"\int_{0}^{\infty} e^{-x} dx")  # integral
MathTex(r"\vec{v}")                       # vector
MathTex(r"\lim_{x \to \infty} f(x)")    # limit
```

## 矩阵

`MathTex` 通过 `amsmath`（默认加载）支持标准 LaTeX 矩阵环境：

```python
# Bracketed matrix
MathTex(r"\begin{bmatrix} 1 & 0 \\ 0 & 1 \end{bmatrix}")

# Parenthesized matrix
MathTex(r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}")

# Determinant (vertical bars)
MathTex(r"\begin{vmatrix} a & b \\ c & d \end{vmatrix}")

# Plain (no delimiters)
MathTex(r"\begin{matrix} x_1 \\ x_2 \\ x_3 \end{matrix}")
```

对于需要逐元素制作动画或为单个条目着色的矩阵，请改用 `IntegerMatrix`、`DecimalMatrix` 或 `MobjectMatrix` Mobject——参见 `mobjects.md`。

## 分段函数

```python
MathTex(r"""
    f(x) = \begin{cases}
        x^2    & \text{if } x \geq 0 \\
        -x^2   & \text{if } x < 0
    \end{cases}
""")
```

## 对齐环境

对于需要对齐的多行推导，请使用 `aligned`，并将其置于 `MathTex` 内：

```python
MathTex(r"""
    \begin{aligned}
        \nabla \cdot \mathbf{E} &= \frac{\rho}{\epsilon_0} \\
        \nabla \cdot \mathbf{B} &= 0 \\
        \nabla \times \mathbf{E} &= -\frac{\partial \mathbf{B}}{\partial t} \\
        \nabla \times \mathbf{B} &= \mu_0 \mathbf{J} + \mu_0 \epsilon_0 \frac{\partial \mathbf{E}}{\partial t}
    \end{aligned}
""")
```

注意：`MathTex` 默认会将内容包装在 `align*` 中。如有需要，可通过 `tex_environment` 覆盖：
```python
MathTex(r"...", tex_environment="gather*")
```

## 推导模式

```python
class DerivationScene(Scene):
    def construct(self):
        self.camera.background_color = BG
        s1 = MathTex(r"ax^2 + bx + c = 0")
        self.play(Write(s1))
        self.wait(1.5)
        s2 = MathTex(r"x^2 + \frac{b}{a}x + \frac{c}{a} = 0")
        s2.next_to(s1, DOWN, buff=0.8)
        self.play(s1.animate.set_opacity(0.4), TransformMatchingTex(s1.copy(), s2))
```

## 使用 substrings_to_isolate 处理复杂方程

对于难以手动拆分的密集方程，可使用 `substrings_to_isolate` 告诉 Manim 将哪些子字符串作为独立元素进行跟踪：

```python
# Without isolation — the whole expression is one blob
lagrangian = MathTex(
    r"\mathcal{L} = \bar{\psi}(i \gamma^\mu D_\mu - m)\psi - \tfrac{1}{4}F_{\mu\nu}F^{\mu\nu}"
)

# With isolation — each named substring is a separate submobject
lagrangian = MathTex(
    r"\mathcal{L} = \bar{\psi}(i \gamma^\mu D_\mu - m)\psi - \tfrac{1}{4}F_{\mu\nu}F^{\mu\nu}",
    substrings_to_isolate=[r"\psi", r"D_\mu", r"\gamma^\mu", r"F_{\mu\nu}"]
)
# Now you can color individual terms
lagrangian.set_color_by_tex(r"\psi", BLUE)
lagrangian.set_color_by_tex(r"F_{\mu\nu}", YELLOW)
```

这对于在复杂方程上使用 `TransformMatchingTex` 至关重要——若不进行隔离，密集表达式的匹配会失败。

## 多行复杂方程

对于包含多行相关内容的方程，请将每一行作为独立参数传入：

```python
maxwell = MathTex(
    r"\nabla \cdot \mathbf{E} = \frac{\rho}{\epsilon_0}",
    r"\nabla \times \mathbf{B} = \mu_0\mathbf{J} + \mu_0\epsilon_0\frac{\partial \mathbf{E}}{\partial t}"
).arrange(DOWN)

# Each line is a separate submobject — animate independently
self.play(Write(maxwell[0]))
self.wait(1)
self.play(Write(maxwell[1]))
```

## 将 TransformMatchingTex 与 key_map 配合使用

在变换过程中，将源方程与目标方程之间的特定子字符串建立映射：

```python
eq1 = MathTex(r"A^2 + B^2 = C^2")
eq2 = MathTex(r"A^2 = C^2 - B^2")

self.play(TransformMatchingTex(
    eq1, eq2,
    key_map={"+": "-"},   # map "+" in source to "-" in target
    path_arc=PI / 2,      # arc the pieces into position
))
```

## set_color_by_tex — 按子字符串着色

```python
eq = MathTex(r"E = mc^2")
eq.set_color_by_tex("E", BLUE)
eq.set_color_by_tex("m", RED)
eq.set_color_by_tex("c", GREEN)
```

## 将 TransformMatchingTex 与 matched_keys 配合使用

当子字符串的匹配存在歧义时，请明确指定要对齐的内容：

```python
kw = dict(font_size=72, t2c={"A": BLUE, "B": TEAL, "C": GREEN})
lines = [
    MathTex(r"A^2 + B^2 = C^2", **kw),
    MathTex(r"A^2 = C^2 - B^2", **kw),
    MathTex(r"A^2 = (C + B)(C - B)", **kw),
    MathTex(r"A = \sqrt{(C + B)(C - B)}", **kw),
]

self.play(TransformMatchingTex(
    lines[0].copy(), lines[1],
    matched_keys=["A^2", "B^2", "C^2"],  # explicitly match these
    key_map={"+": "-"},                    # map + to -
    path_arc=PI / 2,                       # arc pieces into position
))
```

若不使用 `matched_keys`，动画会匹配最长的公共子字符串；对于复杂方程，这可能产生意外结果（例如跨项匹配 "^2 = C^2"）。
