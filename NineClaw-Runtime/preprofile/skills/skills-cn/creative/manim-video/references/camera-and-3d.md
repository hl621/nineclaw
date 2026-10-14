# 摄像机与 3D 参考

## MovingCameraScene（2D 摄像机控制）

```python
class ZoomExample(MovingCameraScene):
    def construct(self):
        circle = Circle(radius=2, color=BLUE)
        self.play(Create(circle))
        # Zoom in
        self.play(self.camera.frame.animate.set(width=4).move_to(circle.get_top()), run_time=2)
        self.wait(2)
        # Zoom back out
        self.play(self.camera.frame.animate.set(width=14.222).move_to(ORIGIN), run_time=2)
```

### 摄像机操作

```python
self.camera.frame.animate.set(width=6)     # zoom in
self.camera.frame.animate.set(width=20)    # zoom out
self.camera.frame.animate.move_to(target)  # pan
self.camera.frame.save_state()             # save
self.play(Restore(self.camera.frame))      # restore
```

## ThreeDScene

```python
class ThreeDExample(ThreeDScene):
    def construct(self):
        self.set_camera_orientation(phi=60*DEGREES, theta=-45*DEGREES)
        axes = ThreeDAxes()
        surface = Surface(
            lambda u, v: axes.c2p(u, v, np.sin(u) * np.cos(v)),
            u_range=[-PI, PI], v_range=[-PI, PI], resolution=(30, 30)
        )
        surface.set_color_by_gradient(BLUE, GREEN, YELLOW)
        self.play(Create(axes), Create(surface))
        self.begin_ambient_camera_rotation(rate=0.2)
        self.wait(5)
        self.stop_ambient_camera_rotation()
```

### 3D 中的摄像机控制

```python
self.set_camera_orientation(phi=70*DEGREES, theta=-45*DEGREES)
self.move_camera(phi=45*DEGREES, theta=30*DEGREES, run_time=2)
self.begin_ambient_camera_rotation(rate=0.2)
```

### 3D Mobject

```python
sphere = Sphere(radius=1).set_color(BLUE).set_opacity(0.7)
cube = Cube(side_length=2, fill_color=GREEN, fill_opacity=0.5)
arrow = Arrow3D(start=ORIGIN, end=[2, 1, 1], color=RED)
# 2D text facing camera:
label = Text("Label", font_size=30)
self.add_fixed_in_frame_mobjects(label)
```

### 参数曲线

```python
helix = ParametricFunction(
    lambda t: [np.cos(t), np.sin(t), t / (2*PI)],
    t_range=[0, 4*PI], color=YELLOW
)
```

## 何时使用 3D
- 曲面、向量场、空间几何、3D 变换
## 何时不应使用 3D
- 2D 概念、文本密集型场景、平面数据（条形图、时间序列）

## ZoomedScene — 嵌入式放大视图

在保持完整视图可见的同时，用嵌入式放大视图展示某处细节：

```python
class ZoomExample(ZoomedScene):
    def __init__(self, **kwargs):
        super().__init__(
            zoom_factor=0.3,           # how much of the scene the zoom box covers
            zoomed_display_height=3,   # size of the inset
            zoomed_display_width=3,
            zoomed_camera_frame_starting_position=ORIGIN,
            **kwargs
        )

    def construct(self):
        self.camera.background_color = BG
        # ... create your scene content ...

        # Activate the zoom
        self.activate_zooming()

        # Move the zoom frame to a point of interest
        self.play(self.zoomed_camera.frame.animate.move_to(detail_point))
        self.wait(2)

        # Deactivate
        self.play(self.get_zoomed_display_pop_out_animation(), rate_func=lambda t: smooth(1-t))
```

使用场景：放大公式中的特定项、展示图示中的精细细节、放大绘图中的某个区域。

## LinearTransformationScene — 线性代数

内置了基向量和网格、用于可视化矩阵变换的场景：

```python
class LinearTransformExample(LinearTransformationScene):
    def __init__(self, **kwargs):
        super().__init__(
            show_coordinates=True,
            show_basis_vectors=True,
            **kwargs
        )

    def construct(self):
        matrix = [[2, 1], [1, 1]]

        # Add a vector before applying the transform
        vector = self.get_vector([1, 2], color=YELLOW)
        self.add_vector(vector)

        # Apply the transformation — grid, basis vectors, and your vector all transform
        self.apply_matrix(matrix)
        self.wait(2)
```

这会呈现 3Blue1Brown《线性代数的本质》中标志性的视觉风格——网格线发生形变、基向量伸缩，并通过面积变化来直观展示行列式。
