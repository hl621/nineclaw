# 故障排查

## LaTeX 错误

**缺少原始字符串**（最常见的错误）：
```python
# WRONG: MathTex("\\frac{1}{2}")  -- \\f is form-feed
# RIGHT: MathTex(r"\frac{1}{2}")
```

**花括号不匹配**：`MathTex(r"\frac{1}{2")` -- 缺少右花括号。

**未安装 LaTeX**：`which pdflatex` -- 安装 texlive-full 或 mactex。

**缺少软件包**：将其添加到导言区：
```python
tex_template = TexTemplate()
tex_template.add_to_preamble(r"\usepackage{mathrsfs}")
MathTex(r"\mathscr{L}", tex_template=tex_template)
```

## VGroup TypeError

**错误：** `TypeError: Only values of type VMobject can be added as submobjects of VGroup`

**原因：** `Text()` 对象是 `Mobject`，而不是 `VMobject`。在 Manim CE v0.20+ 中，将 `Text` 与形状混合放入 `VGroup` 会失败。

```python
# WRONG: Text is not a VMobject
group = VGroup(circle, Text("Label"))

# RIGHT: use Group for mixed types
group = Group(circle, Text("Label"))

# RIGHT: VGroup is fine for shapes-only
shapes = VGroup(circle, square, arrow)

# RIGHT: MathTex IS a VMobject — VGroup works
equations = VGroup(MathTex(r"a"), MathTex(r"b"))
```

**规则：** 如果组中包含任何 `Text()`，请使用 `Group`。如果其中全是形状或全是 `MathTex`，则可以使用 `VGroup`。

**淡出所有对象：** 始终使用 `Group(*self.mobjects)`，不要使用 `VGroup(*self.mobjects)`：
```python
self.play(FadeOut(Group(*self.mobjects)))  # safe for mixed types
```

## Group 不支持 save_state() / restore()

**错误：** `NotImplementedError: Please override in a child class.`

**原因：** Manim CE v0.20+ 中未实现 `Group.save_state()` 和 `Group.restore()`。只有 `VGroup` 和各个 `Mobject` 子类支持保存/恢复。

```python
# WRONG: Group doesn't support save_state
group = Group(circle, Text("label"))
group.save_state()  # NotImplementedError!

# RIGHT: use FadeIn with shift/scale instead of save_state/restore
self.play(FadeIn(group, shift=UP * 0.3, scale=0.8))

# RIGHT: or save/restore on individual VMobjects
circle.save_state()
self.play(circle.animate.shift(RIGHT))
self.play(Restore(circle))
```

## letter_spacing 不是有效参数

**错误：** `TypeError: Mobject.__init__() got an unexpected keyword argument 'letter_spacing'`

**原因：** `Text()` 不接受 `letter_spacing`。Manim 使用 Pango 渲染文本，并且未在 `Text()` 上提供字距调整控制。

```python
# WRONG
Text("HERMES", letter_spacing=6)

# RIGHT: use MarkupText with Pango attributes for spacing control
MarkupText('<span letter_spacing="6000">HERMES</span>', font_size=18)
# Note: Pango letter_spacing is in 1/1024 of a point
```

## 动画错误

**动画不可见** -- 从未添加 mobject：
```python
# WRONG: circle = Circle(); self.play(circle.animate.set_color(RED))
# RIGHT: self.play(Create(circle)); self.play(circle.animate.set_color(RED))
```

**变换混淆** -- 执行 Transform(A, B) 后，屏幕上显示的是 A，而不是 B。如果希望得到 B，请使用 ReplacementTransform。

**动画重复** -- 在一次 play() 中对同一个 mobject 应用两次动画：
```python
# WRONG: self.play(c.animate.shift(RIGHT), c.animate.set_color(RED))
# RIGHT: self.play(c.animate.shift(RIGHT).set_color(RED))
```

**更新器与动画冲突**：
```python
mob.suspend_updating()
self.play(mob.animate.shift(RIGHT))
mob.resume_updating()
```

## 渲染问题

**输出模糊**：使用了 -ql (480p)。最终渲染请改用 -qm/-qh。

**渲染缓慢**：开发期间使用 -ql。降低 Surface 分辨率。缩短 self.wait()。

**输出陈旧**：`manim -ql --disable_caching script.py Scene`

**ffmpeg 拼接失败**：所有片段的分辨率/FPS/编解码器必须一致。

## 常见错误

**文本在边缘被裁切**：使用 `buff >= 0.5` 作为 `.to_edge()` 的参数

**文本重叠**：使用 `ReplacementTransform(old, new)`，不要在原文本上叠加 `Write(new)`。

**画面过于拥挤**：可见元素最多保持在 5-6 个。拆分为多个场景，或使用不透明度分层。

**没有留出停顿**：内容揭示后至少使用 `self.wait(1.5)`，关键时刻使用 `self.wait(2.0)`。

**缺少背景颜色**：在每个场景中设置 `self.camera.background_color = BG`。

## 调试策略

1. 渲染静帧：`manim -ql -s script.py Scene` -- 立即检查布局
2. 隔离出错场景 -- 只渲染该场景
3. 将 `self.play()` 替换为 `self.add()`，立即查看最终状态
4. 打印位置：`print(mob.get_center())`
5. 清除缓存：删除 `media/` 目录
