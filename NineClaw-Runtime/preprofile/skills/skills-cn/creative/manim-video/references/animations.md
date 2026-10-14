# 动画参考

## 核心概念

动画是一个 Python 对象，用于计算 Mobject 随时间变化的中间视觉状态。动画是传递给 `self.play()` 的对象，而不是函数。

`run_time` 控制动画时长（单位为秒，默认值为 1）。对于重要动画，务必显式指定它。

## 创建动画

```python
self.play(Create(circle))          # traces outline
self.play(Write(equation))         # simulates handwriting (for Text/MathTex)
self.play(FadeIn(group))           # opacity 0 -> 1
self.play(GrowFromCenter(dot))     # scale 0 -> 1 from center
self.play(DrawBorderThenFill(sq))  # outline first, then fill
```

## 移除动画

```python
self.play(FadeOut(mobject))         # opacity 1 -> 0
self.play(Uncreate(circle))        # reverse of Create
self.play(ShrinkToCenter(group))   # scale 1 -> 0
```

## 变换动画

```python
# Transform -- modifies the original in place
self.play(Transform(circle, square))
# After: circle IS the square (same object, new appearance)

# ReplacementTransform -- replaces old with new
self.play(ReplacementTransform(circle, square))
# After: circle removed, square on screen

# TransformMatchingTex -- smart equation morphing
eq1 = MathTex(r"a^2 + b^2")
eq2 = MathTex(r"a^2 + b^2 = c^2")
self.play(TransformMatchingTex(eq1, eq2))
```

**关键事项**：执行 `Transform(A, B)` 后，变量 `A` 引用屏幕上的 Mobject。变量 `B` 并未显示在屏幕上。请使用 `ReplacementTransform`，以便之后操作 `B`。

## .animate 语法

```python
self.play(circle.animate.set_color(RED))
self.play(circle.animate.shift(RIGHT * 2).scale(0.5))  # chain multiple
```

## 其他创建动画

```python
self.play(GrowFromPoint(circle, LEFT * 3))     # scale 0 -> 1 from a specific point
self.play(GrowFromEdge(rect, DOWN))             # grow from one edge
self.play(SpinInFromNothing(square))            # scale up while rotating (default PI/2)
self.play(GrowArrow(arrow))                     # grows arrow from start to tip
```

## 移动动画

```python
# Move a mobject along an arbitrary path
path = Arc(radius=2, angle=PI)
self.play(MoveAlongPath(dot, path), run_time=2)

# Rotate (as a Transform, not .animate — supports about_point)
self.play(Rotate(square, angle=PI / 2, about_point=ORIGIN), run_time=1.5)

# Rotating (continuous rotation, updater-style — good for spinning objects)
self.play(Rotating(gear, angle=TAU, run_time=4, rate_func=linear))
```

`MoveAlongPath` 接受任意 `VMobject` 作为路径——可使用 `Arc`、`CubicBezier`、`Line` 或自定义 `VMobject`。位置通过 `path.point_from_proportion()` 计算。

## 强调动画

```python
self.play(Indicate(mobject))             # brief yellow flash + scale
self.play(Circumscribe(mobject))         # draw rectangle around it
self.play(Flash(point))                  # radial flash
self.play(Wiggle(mobject))               # shake side to side
```

## 速率函数

```python
self.play(FadeIn(mob), rate_func=smooth)          # default: ease in/out
self.play(FadeIn(mob), rate_func=linear)           # constant speed
self.play(FadeIn(mob), rate_func=rush_into)        # start slow, end fast
self.play(FadeIn(mob), rate_func=rush_from)        # start fast, end slow
self.play(FadeIn(mob), rate_func=there_and_back)   # animate then reverse
```

## 动画组合

```python
# Simultaneous
self.play(FadeIn(title), Create(circle), run_time=2)

# AnimationGroup with lag
self.play(AnimationGroup(*[FadeIn(i) for i in items], lag_ratio=0.2))

# LaggedStart
self.play(LaggedStart(*[Write(l) for l in lines], lag_ratio=0.3, run_time=3))

# Succession (sequential in one play call)
self.play(Succession(FadeIn(title), Wait(0.5), Write(subtitle)))
```

## 更新器

```python
tracker = ValueTracker(0)
dot = Dot().add_updater(lambda m: m.move_to(axes.c2p(tracker.get_value(), 0)))
self.play(tracker.animate.set_value(5), run_time=3)
```

## 字幕

```python
# Method 1: standalone
self.add_subcaption("Key insight", duration=2)
self.play(Write(equation), run_time=2.0)

# Method 2: inline
self.play(Write(equation), subcaption="Key insight", subcaption_duration=2)
```

Manim 会自动生成 `.srt` 字幕文件。务必添加辅助字幕，以提升内容的无障碍性。

## 时间编排模式

```python
# Pause-after-reveal
self.play(Write(key_equation), run_time=2.0)
self.wait(2.0)

# Dim-and-focus
self.play(old_content.animate.set_opacity(0.3), FadeIn(new_content))

# Clean exit
self.play(FadeOut(Group(*self.mobjects)), run_time=0.5)
self.wait(0.3)
```

## 响应式 Mobject：always_redraw()

每一帧都从头重新构建一个 Mobject——当其几何形状依赖其他动态变化的对象时，这是不可或缺的：

```python
# Brace that follows a resizing square
brace = always_redraw(Brace, square, UP)
self.add(brace)
self.play(square.animate.scale(2))  # brace auto-adjusts

# Horizontal line that tracks a moving dot
h_line = always_redraw(lambda: axes.get_h_line(dot.get_left()))

# Label that always stays next to another mobject
label = always_redraw(lambda: Text("here", font_size=20).next_to(dot, UP, buff=0.2))
```

注意：`always_redraw` 会在每一帧重新创建 Mobject。对于简单的属性跟踪，请改用 `add_updater`（开销更低）：
```python
label.add_updater(lambda m: m.next_to(dot, UP))
```

## TracedPath——轨迹追踪

绘制一个点行进过的路径：

```python
dot = Dot(color=YELLOW)
path = TracedPath(dot.get_center, stroke_color=YELLOW, stroke_width=2)
self.add(dot, path)
self.play(dot.animate.shift(RIGHT * 3 + UP * 2), run_time=2)
# path shows the trail the dot left behind

# Fading trail (dissipates over time):
path = TracedPath(dot.get_center, dissipating_time=0.5, stroke_opacity=[0, 1])
```

使用场景：梯度下降路径、行星轨道、函数轨迹描绘、粒子轨迹。

## FadeTransform——更平滑的交叉淡化

`Transform` 会让形状通过难看的中间扭曲完成变形。`FadeTransform` 会结合位置匹配进行交叉淡化——当源对象与目标对象外观不同时，请使用它：

```python
# UGLY: Transform warps circle into square through a blob
self.play(Transform(circle, square))

# SMOOTH: FadeTransform cross-fades cleanly
self.play(FadeTransform(circle, square))

# FadeTransformPieces: per-submobject FadeTransform
self.play(FadeTransformPieces(group1, group2))

# TransformFromCopy: animate a COPY while keeping the original visible
self.play(TransformFromCopy(source, target))
# source stays on screen, a copy morphs into target
```

**建议：** 对于外观差异较大的形状，默认使用 `FadeTransform`。仅对相似形状（圆→椭圆、公式→公式）使用 `Transform`/`ReplacementTransform`。

## ApplyMatrix——线性变换可视化

在 Mobject 上以动画形式呈现矩阵变换：

```python
# Apply a 2x2 matrix to a grid
matrix = [[2, 1], [1, 1]]
self.play(ApplyMatrix(matrix, number_plane), run_time=2)

# Also works on individual mobjects
self.play(ApplyMatrix([[0, -1], [1, 0]], square))  # 90-degree rotation
```

可与 `LinearTransformationScene` 搭配使用——参见 `camera-and-3d.md`。

## squish_rate_func——时间窗口交错

将任意速率函数压缩到动画中的指定时间窗口，从而无需 `LaggedStart` 即可实现相互重叠的交错动画：

```python
self.play(
    FadeIn(a, rate_func=squish_rate_func(smooth, 0, 0.5)),    # 0% to 50%
    FadeIn(b, rate_func=squish_rate_func(smooth, 0.25, 0.75)), # 25% to 75%
    FadeIn(c, rate_func=squish_rate_func(smooth, 0.5, 1.0)),  # 50% to 100%
    run_time=2
)
```

需要精确控制动画的重叠区间时，它比 `LaggedStart` 更合适。

## 其他速率函数

```python
from manim import (
    smooth, linear, rush_into, rush_from,
    there_and_back, there_and_back_with_pause,
    running_start, double_smooth, wiggle,
    lingering, exponential_decay, not_quite_there,
    squish_rate_func
)

# running_start: pulls back before going forward (anticipation)
self.play(FadeIn(mob, rate_func=running_start))

# there_and_back_with_pause: goes there, holds, comes back
self.play(mob.animate.shift(UP), rate_func=there_and_back_with_pause)

# not_quite_there: stops at a fraction of the full animation
self.play(FadeIn(mob, rate_func=not_quite_there(0.7)))
```

## ShowIncreasingSubsets / ShowSubmobjectsOneByOne

逐步显示组内成员——非常适合用于算法可视化：

```python
# Reveal array elements one at a time
array = Group(*[Square() for _ in range(8)]).arrange(RIGHT)
self.play(ShowIncreasingSubsets(array), run_time=3)

# Show submobjects with staggered appearance
self.play(ShowSubmobjectsOneByOne(code_lines), run_time=4)
```

## ShowPassingFlash

一道闪光沿路径移动：

```python
# Flash traveling along a curve
self.play(ShowPassingFlash(curve.copy().set_color(YELLOW), time_width=0.3))

# Great for: data flow, electrical signals, network traffic
```
