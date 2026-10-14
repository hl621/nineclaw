# 更新器与数值追踪器

## 更新器解决的问题

普通动画是离散的：`self.play()` 会从状态 A 过渡到状态 B。但如果你需要持续维持对象间的关系，该怎么办？例如，让标签始终悬停在移动圆点上方，或让一条线始终连接两个点。

如果不使用更新器，你就得在每次调用 `self.play()` 前手动重新定位所有依赖对象。让一个圆点移动五次，就意味着要为标签手动调用五次重新定位。漏掉一次，标签就会停在错误的位置。

更新器让你只需声明一次关系。Manim 会在每一帧（取决于质量设置，帧率为 15-60 fps）调用更新器函数来维持该关系，无论同时还发生了什么。

## ValueTracker：隐形的方向盘

ValueTracker 是一个不可见的 Mobject，用于保存单个浮点数。它从不会出现在画面中。它存在的意义是：你可以为它设置动画，同时让其他对象根据它的值作出响应。

可以把它想象成一个滑块：将滑块从 0 拖到 5，所有与它关联的对象都会实时响应。

```python
tracker = ValueTracker(0)        # invisible, stores 0.0
tracker.get_value()              # read: 0.0
tracker.set_value(5)             # write: jump to 5.0 instantly
tracker.animate.set_value(5)     # animate: smoothly interpolate to 5.0
```

### 三步模式

每次使用 ValueTracker 都遵循以下模式：

1. **创建追踪器**（隐形滑块）
2. **通过更新器创建读取追踪器值的可见对象**
3. **为追踪器设置动画**——所有依赖对象都会自动更新

```python
# Step 1: Create tracker
x_tracker = ValueTracker(1)

# Step 2: Create dependent objects
dot = always_redraw(lambda: Dot(axes.c2p(x_tracker.get_value(), 0), color=YELLOW))
v_line = always_redraw(lambda: axes.get_vertical_line(
    axes.c2p(x_tracker.get_value(), func(x_tracker.get_value())), color=BLUE
))
label = always_redraw(lambda: DecimalNumber(x_tracker.get_value(), font_size=24)
    .next_to(dot, UP))

self.add(dot, v_line, label)

# Step 3: Animate the tracker — everything follows
self.play(x_tracker.animate.set_value(5), run_time=3)
```

## 更新器的类型

### Lambda 更新器（最常用）

每一帧都会运行一个函数，并将 mobject 本身传入该函数：

```python
# Label always stays above the dot
label.add_updater(lambda m: m.next_to(dot, UP, buff=0.2))

# Line always connects two points
line.add_updater(lambda m: m.put_start_and_end_on(
    point_a.get_center(), point_b.get_center()
))
```

### 基于时间的更新器（使用 dt）

第二个参数 `dt` 表示自上一帧以来经过的时间（在 60fps 下约为 0.017 秒）：

```python
# Continuous rotation
square.add_updater(lambda m, dt: m.rotate(0.5 * dt))

# Continuous rightward drift
dot.add_updater(lambda m, dt: m.shift(RIGHT * 0.3 * dt))

# Oscillation
dot.add_updater(lambda m, dt: m.move_to(
    axes.c2p(m.get_center()[0], np.sin(self.time))
))
```

使用 `dt` 的更新器适合处理物理模拟、连续运动和随时间变化的效果。

### always_redraw：每一帧完全重建

每一帧都从头创建一个新的 mobject。它的开销比 `add_updater` 更大，但能够处理 mobject 结构发生变化（而不只是位置或颜色变化）的情况：

```python
# Brace that follows a resizing square
brace = always_redraw(Brace, square, UP)

# Area under curve that updates as function changes
area = always_redraw(lambda: axes.get_area(
    graph, x_range=[0, x_tracker.get_value()], color=BLUE, opacity=0.3
))

# Label that reconstructs its text
counter = always_redraw(lambda: Text(
    f"n = {int(x_tracker.get_value())}", font_size=24, font="Menlo"
).to_corner(UR))
```

**如何选择：**
- `add_updater`——位置、颜色、不透明度的变化（开销小，优先使用）
- `always_redraw`——形状或结构本身发生变化时（开销大，谨慎使用）

## DecimalNumber：显示实时数值

```python
# Counter that tracks a ValueTracker
tracker = ValueTracker(0)
number = DecimalNumber(0, font_size=48, num_decimal_places=1, color=PRIMARY)
number.add_updater(lambda m: m.set_value(tracker.get_value()))
number.add_updater(lambda m: m.next_to(dot, RIGHT, buff=0.3))

self.add(number)
self.play(tracker.animate.set_value(100), run_time=3)
```

### Variable：带标签的版本

```python
var = Variable(0, Text("x", font_size=24, font="Menlo"), num_decimal_places=2)
self.add(var)
self.play(var.tracker.animate.set_value(PI), run_time=2)
# Displays: x = 3.14
```

## 移除更新器

```python
# Remove all updaters
mobject.clear_updaters()

# Suspend temporarily (during an animation that would fight the updater)
mobject.suspend_updating()
self.play(mobject.animate.shift(RIGHT))
mobject.resume_updating()

# Remove specific updater (if you stored a reference)
def my_updater(m):
    m.next_to(dot, UP)
label.add_updater(my_updater)
# ... later ...
label.remove_updater(my_updater)
```

## 基于动画的更新器

### UpdateFromFunc / UpdateFromAlphaFunc

它们是动画（传给 `self.play`），而不是持续生效的更新器：

```python
# Call a function on each frame of the animation
self.play(UpdateFromFunc(mobject, lambda m: m.next_to(moving_target, UP)), run_time=3)

# With alpha (0 to 1) — useful for custom interpolation
self.play(UpdateFromAlphaFunc(circle, lambda m, a: m.set_fill(opacity=a)), run_time=2)
```

### turn_animation_into_updater

将一次性动画转换为连续更新器：

```python
from manim import turn_animation_into_updater

# This would normally play once — now it loops forever
turn_animation_into_updater(Rotating(gear, rate=PI/4))
self.add(gear)
self.wait(5)  # gear rotates for 5 seconds
```

## 实用模式

### 模式 1：沿函数轨迹移动的圆点

```python
tracker = ValueTracker(0)
graph = axes.plot(np.sin, x_range=[0, 2*PI], color=PRIMARY)
dot = always_redraw(lambda: Dot(
    axes.c2p(tracker.get_value(), np.sin(tracker.get_value())),
    color=YELLOW
))
tangent = always_redraw(lambda: axes.get_secant_slope_group(
    x=tracker.get_value(), graph=graph, dx=0.01,
    secant_line_color=HIGHLIGHT, secant_line_length=3
))

self.add(graph, dot, tangent)
self.play(tracker.animate.set_value(2*PI), run_time=6, rate_func=linear)
```

### 模式 2：曲线下方的实时面积

```python
tracker = ValueTracker(0.5)
area = always_redraw(lambda: axes.get_area(
    graph, x_range=[0, tracker.get_value()],
    color=PRIMARY, opacity=0.3
))
area_label = always_redraw(lambda: DecimalNumber(
    # Numerical integration
    sum(func(x) * 0.01 for x in np.arange(0, tracker.get_value(), 0.01)),
    font_size=24
).next_to(axes, RIGHT))

self.add(area, area_label)
self.play(tracker.animate.set_value(4), run_time=5)
```

### 模式 3：连线图

```python
# Nodes that can be moved, with edges that auto-follow
node_a = Dot(LEFT * 2, color=PRIMARY)
node_b = Dot(RIGHT * 2, color=SECONDARY)
edge = Line().add_updater(lambda m: m.put_start_and_end_on(
    node_a.get_center(), node_b.get_center()
))
label = Text("edge", font_size=18, font="Menlo").add_updater(
    lambda m: m.move_to(edge.get_center() + UP * 0.3)
)

self.add(node_a, node_b, edge, label)
self.play(node_a.animate.shift(UP * 2), run_time=2)
self.play(node_b.animate.shift(DOWN + RIGHT), run_time=2)
# Edge and label follow automatically
```

### 模式 4：参数探索

```python
# Explore how a parameter changes a curve
a_tracker = ValueTracker(1)
curve = always_redraw(lambda: axes.plot(
    lambda x: a_tracker.get_value() * np.sin(x),
    x_range=[0, 2*PI], color=PRIMARY
))
param_label = always_redraw(lambda: Text(
    f"a = {a_tracker.get_value():.1f}", font_size=24, font="Menlo"
).to_corner(UR))

self.add(curve, param_label)
self.play(a_tracker.animate.set_value(3), run_time=3)
self.play(a_tracker.animate.set_value(0.5), run_time=2)
self.play(a_tracker.animate.set_value(1), run_time=1)
```

## 常见错误

1. **更新器与动画冲突：** 如果某个 mobject 的更新器会设置其位置，而你又尝试用动画将它移到别处，那么更新器会在每一帧覆盖动画效果。请先暂停更新。

2. **对简单移动使用 always_redraw：** 如果只需重新定位，请使用 `add_updater`。`always_redraw` 会在每一帧重建整个 mobject——开销高昂，而且对于位置追踪而言没有必要。

3. **忘记添加到场景：** 更新器只会在已加入场景的 mobject 上运行。`always_redraw` 会创建 mobject，但你仍然需要调用 `self.add()`。

4. **更新器创建新 mobject 却不清理：** 如果更新器每一帧都创建 Text 对象，这些对象会不断累积。请使用 `always_redraw`（它会处理清理），或就地更新属性。
