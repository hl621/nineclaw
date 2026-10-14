# 合成与亮度参考

可组合系统是实现视觉复杂度的核心。它在三个层级上运作：像素级混合模式、多网格合成，以及自适应亮度管理。本文档将介绍这三者，以及用于空间控制的遮罩/模板系统。

> **另请参阅：** architecture.md · effects.md · scenes.md · shaders.md · troubleshooting.md

## 像素级混合模式

### `blend_canvas()` 函数

所有混合操作都在完整的像素画布（`uint8 H,W,3`）上进行。内部会将其转换为 float32 [0,1] 以确保精度，完成混合后按不透明度进行 lerp，再转换回来。

```python
def blend_canvas(base, top, mode="normal", opacity=1.0):
    af = base.astype(np.float32) / 255.0
    bf = top.astype(np.float32) / 255.0
    fn = BLEND_MODES.get(mode, BLEND_MODES["normal"])
    result = fn(af, bf)
    if opacity < 1.0:
        result = af * (1 - opacity) + result * opacity
    return np.clip(result * 255, 0, 255).astype(np.uint8)
```

### 20 种混合模式

```python
BLEND_MODES = {
    # Basic arithmetic
    "normal":       lambda a, b: b,
    "add":          lambda a, b: np.clip(a + b, 0, 1),
    "subtract":     lambda a, b: np.clip(a - b, 0, 1),
    "multiply":     lambda a, b: a * b,
    "screen":       lambda a, b: 1 - (1 - a) * (1 - b),

    # Contrast
    "overlay":      lambda a, b: np.where(a < 0.5, 2*a*b, 1 - 2*(1-a)*(1-b)),
    "softlight":    lambda a, b: (1 - 2*b)*a*a + 2*b*a,
    "hardlight":    lambda a, b: np.where(b < 0.5, 2*a*b, 1 - 2*(1-a)*(1-b)),

    # Difference
    "difference":   lambda a, b: np.abs(a - b),
    "exclusion":    lambda a, b: a + b - 2*a*b,

    # Dodge / burn
    "colordodge":   lambda a, b: np.clip(a / (1 - b + 1e-6), 0, 1),
    "colorburn":    lambda a, b: np.clip(1 - (1 - a) / (b + 1e-6), 0, 1),

    # Light
    "linearlight":  lambda a, b: np.clip(a + 2*b - 1, 0, 1),
    "vividlight":   lambda a, b: np.where(b < 0.5,
                        np.clip(1 - (1-a)/(2*b + 1e-6), 0, 1),
                        np.clip(a / (2*(1-b) + 1e-6), 0, 1)),
    "pin_light":    lambda a, b: np.where(b < 0.5,
                        np.minimum(a, 2*b), np.maximum(a, 2*b - 1)),
    "hard_mix":     lambda a, b: np.where(a + b >= 1.0, 1.0, 0.0),

    # Compare
    "lighten":      lambda a, b: np.maximum(a, b),
    "darken":       lambda a, b: np.minimum(a, b),

    # Grain
    "grain_extract": lambda a, b: np.clip(a - b + 0.5, 0, 1),
    "grain_merge":  lambda a, b: np.clip(a + b - 0.5, 0, 1),
}
```

### 混合模式选择指南

**提亮类模式**（适合深色输入）：
- `screen` — 始终提亮。两个 50% 灰度图层经 screen 混合后会达到 75%。这是首选的安全混合模式。
- `add` — 简单相加，超出部分截断为白色。适合闪光、辉光和粒子叠加层。
- `colordodge` — 在重叠区域产生极强的提亮效果，可能导致过曝。请使用较低的不透明度（0.3-0.5）。
- `linearlight` — 激进提亮。与 add 类似，但带有偏移。

**压暗类模式**（应避免用于深色输入）：
- `multiply` — 压暗一切。仅当两个图层都已经很亮时使用。
- `overlay` — 基底 < 0.5 时压暗，基底 > 0.5 时提亮。会严重压缩深色输入：`2 * 0.12 * 0.12 = 0.03`。对于深色素材，请改用 `screen`。
- `colorburn` — 在重叠区域产生极强的压暗效果。

**增强对比度的模式**：
- `softlight` — 温和增强对比度。适合叠加细微纹理。
- `hardlight` — 强烈增强对比度。类似 overlay，但以顶层为基准。
- `vividlight` — 非常激进的对比度效果。请谨慎使用。

**产生色彩效果的模式**：
- `difference` — 产生类似 XOR 的图案。两个相同图层进行 difference 混合会得到黑色；错位图层则会产生狂野色彩。非常适合迷幻风格。
- `exclusion` — difference 的柔和版本。会生成互补色图案。
- `hard_mix` — 将交叠区域色调分离为纯黑、纯白或高饱和色。

**用于纹理混合的模式**：
- `grain_extract` / `grain_merge` — 从一个图层提取纹理，再将其应用到另一个图层。

### 多图层链式混合

```python
# Pattern: render layers -> blend sequentially
canvas_a = _render_vf(r, "md", vf_plasma, hf_angle(0.0), PAL_DENSE, f, t, S)
canvas_b = _render_vf(r, "sm", vf_vortex, hf_time_cycle(0.1), PAL_RUNE, f, t, S)
canvas_c = _render_vf(r, "lg", vf_rings, hf_distance(), PAL_BLOCKS, f, t, S)

result = blend_canvas(canvas_a, canvas_b, "screen", 0.8)
result = blend_canvas(result, canvas_c, "difference", 0.6)
```

顺序很重要：`screen(A, B)` 满足交换律，但 `difference(screen(A,B), C)` 与 `difference(A, screen(B,C))` 的结果不同。

### 线性光混合模式

标准 `blend_canvas()` 在 sRGB 空间（即原始字节值）中运行。这足以满足大多数用途，但 sRGB 在感知上是非线性的：在 sRGB 中混合会使中间调变暗，并令色相轻微偏移。若要进行物理准确的混合（与光线实际叠加的方式一致），应先转换到线性光空间。

使用 `srgb_to_linear()` / `linear_to_srgb()`，它们来自 `architecture.md` § OKLAB Color System。

```python
def blend_canvas_linear(base, top, mode="normal", opacity=1.0):
    """Blend in linear light space for physically accurate results.
    
    Identical API to blend_canvas(), but converts sRGB → linear before
    blending and linear → sRGB after. More expensive (~2x) due to the
    gamma conversions, but produces correct results for additive blending,
    screen, and any mode where brightness matters.
    """
    af = srgb_to_linear(base.astype(np.float32) / 255.0)
    bf = srgb_to_linear(top.astype(np.float32) / 255.0)
    fn = BLEND_MODES.get(mode, BLEND_MODES["normal"])
    result = fn(af, bf)
    if opacity < 1.0:
        result = af * (1 - opacity) + result * opacity
    result = linear_to_srgb(np.clip(result, 0, 1))
    return np.clip(result * 255, 0, 255).astype(np.uint8)
```

**何时使用 `blend_canvas_linear()`，何时使用 `blend_canvas()`：**

| 场景 | 使用 | 原因 |
|----------|-----|-----|
| 对两个明亮图层进行 Screen 混合 | `linear` | sRGB screen 会使高光过亮 |
| 对辉光/bloom effects 使用 Add 模式 | `linear` | 加法光照遵循线性物理规律 |
| 以低不透明度混合文本叠加层 | `srgb` | 对文本而言，感知混合看起来更自然 |
| 用 Multiply 制造阴影/压暗 | `srgb` | 对于压暗操作，差异很小 |
| 对色彩要求严格的工作（匹配参考图） | `linear` | 避免 sRGB 导致中间调色相偏移 |
| 性能关键的内部循环 | `srgb` | 速度约快 2 倍，对大多数 ASCII art 已经足够 |

用于合成多个图层的**批处理版本**（只转换一次，执行多次混合后再转回）：

```python
def blend_many_linear(layers, modes, opacities):
    """Blend a stack of layers in linear light space.
    
    Args:
        layers: list of uint8 (H,W,3) canvases
        modes: list of blend mode strings (len = len(layers) - 1)
        opacities: list of floats (len = len(layers) - 1)
    Returns:
        uint8 (H,W,3) canvas
    """
    # Convert all to linear at once
    linear = [srgb_to_linear(l.astype(np.float32) / 255.0) for l in layers]
    result = linear[0]
    for i in range(1, len(linear)):
        fn = BLEND_MODES.get(modes[i-1], BLEND_MODES["normal"])
        blended = fn(result, linear[i])
        op = opacities[i-1]
        if op < 1.0:
            blended = result * (1 - op) + blended * op
        result = np.clip(blended, 0, 1)
    result = linear_to_srgb(result)
    return np.clip(result * 255, 0, 255).astype(np.uint8)
```

---

## 多网格合成

这是核心视觉技术。在不同网格密度（字符尺寸）下渲染同一个概念场景，会产生自然的纹理干涉，因为不同尺度的字符会以不同空间频率相互重叠。

### 生效原理

- `sm` 网格（10pt 字体）：320x83 个字符。细节精细、纹理密集。
- `md` 网格（16pt）：192x56 个字符。中等密度。
- `lg` 网格（20pt）：160x45 个字符。字符粗犷、块状感强。

当你在 `sm` 上渲染 plasma 场、在 `lg` 上渲染 vortex，再以 screen 模式混合二者时，精细的 plasma 纹理会从粗大 vortex 字符的间隙中显露出来。最终效果比任一单独图层都更具视觉复杂度。

### `_render_vf()` 辅助函数

这是承担主要工作的函数。它接收值场 + 色相场 + 字符调色板 + 网格，并渲染成完整的像素画布：

```python
def _render_vf(r, grid_key, val_fn, hue_fn, pal, f, t, S, sat=0.8, threshold=0.03):
    """Render a value field + hue field to a pixel canvas via a named grid.

    Args:
        r: Renderer instance (has .get_grid())
        grid_key: "xs", "sm", "md", "lg", "xl", "xxl"
        val_fn: (g, f, t, S) -> float32 [0,1] array (rows, cols)
        hue_fn: callable (g, f, t, S) -> float32 hue array, OR float scalar
        pal: character palette string
        f: feature dict
        t: time in seconds
        S: persistent state dict
        sat: HSV saturation (0-1)
        threshold: minimum value to render (below = space)

    Returns:
        uint8 array (VH, VW, 3) — full pixel canvas
    """
    g = r.get_grid(grid_key)
    val = np.clip(val_fn(g, f, t, S), 0, 1)
    mask = val > threshold
    ch = val2char(val, mask, pal)

    # Hue: either a callable or a fixed float
    if callable(hue_fn):
        h = hue_fn(g, f, t, S) % 1.0
    else:
        h = np.full((g.rows, g.cols), float(hue_fn), dtype=np.float32)

    # CRITICAL: broadcast to full shape and copy (see Troubleshooting)
    h = np.broadcast_to(h, (g.rows, g.cols)).copy()

    R, G, B = hsv2rgb(h, np.full_like(val, sat), val)
    co = mkc(R, G, B, g.rows, g.cols)
    return g.render(ch, co)
```

### 网格组合策略

| 组合 | 效果 | 适用场景 |
|-------------|--------|----------|
| `sm` + `lg` | 精细细节与粗大块面之间形成最大反差 | 大胆、图形化的风格 |
| `sm` + `md` | 尺度相近的细腻纹理分层 | 有机、流动的风格 |
| `md` + `lg` + `xs` | 三种尺度相互干涉，复杂度最高 | 迷幻、密集的风格 |
| `sm` + `sm`（不同 effects） | 尺度相同，仅产生图案干涉 | 摩尔纹、干涉效果 |

### 完整的多网格场景示例

```python
def fx_psychedelic(r, f, t, S):
    """Three-layer multi-grid scene with beat-reactive kaleidoscope."""
    # Layer A: plasma on medium grid with rainbow hue
    canvas_a = _render_vf(r, "md",
        lambda g, f, t, S: vf_plasma(g, f, t, S) * 1.3,
        hf_angle(0.0), PAL_DENSE, f, t, S, sat=0.8)

    # Layer B: vortex on small grid with cycling hue
    canvas_b = _render_vf(r, "sm",
        lambda g, f, t, S: vf_vortex(g, f, t, S, twist=5.0) * 1.2,
        hf_time_cycle(0.1), PAL_RUNE, f, t, S, sat=0.7)

    # Layer C: rings on large grid with distance hue
    canvas_c = _render_vf(r, "lg",
        lambda g, f, t, S: vf_rings(g, f, t, S, n_base=8, spacing_base=3) * 1.4,
        hf_distance(0.3, 0.02), PAL_BLOCKS, f, t, S, sat=0.9)

    # Blend: A screened with B, then difference with C
    result = blend_canvas(canvas_a, canvas_b, "screen", 0.8)
    result = blend_canvas(result, canvas_c, "difference", 0.6)

    # Beat-triggered kaleidoscope
    if f.get("bdecay", 0) > 0.3:
        result = sh_kaleidoscope(result.copy(), folds=6)

    return result
```

---

## 自适应色调映射

### 亮度问题

ASCII 字符是黑色背景上的微小亮点。任何一帧中的大多数像素都是背景（黑色）。这意味着：
- 帧平均亮度本来就很低（通常在 255 中仅为 5-30）
- 不同 effects 组合会产生差异巨大的亮度水平
- spiral 场景的平均值可能为 50，而 fire 场景仅为 9
- 线性乘数（例如 `canvas * 2.0`）要么让深色场景仍然很暗，要么使明亮场景过曝

### `tonemap()` 函数

以自适应逐帧归一化 + gamma 校正取代线性亮度乘数：

```python
def tonemap(canvas, target_mean=90, gamma=0.75, black_point=2, white_point=253):
    """Adaptive tone-mapping: normalizes + gamma-corrects so no frame is
    fully dark or washed out.

    1. Compute 1st and 99.5th percentile on 4x subsample (16x fewer values,
       negligible accuracy loss, major speedup at 1080p+)
    2. Stretch that range to [0, 1]
    3. Apply gamma curve (< 1 lifts shadows, > 1 darkens)
    4. Rescale to [black_point, white_point]
    """
    f = canvas.astype(np.float32)
    sub = f[::4, ::4]  # 4x subsample: ~390K values vs ~6.2M at 1080p
    lo = np.percentile(sub, 1)
    hi = np.percentile(sub, 99.5)
    if hi - lo < 10:
        hi = max(hi, lo + 10)  # near-uniform frame fallback
    f = np.clip((f - lo) / (hi - lo), 0.0, 1.0)
    np.power(f, gamma, out=f)          # in-place: avoids allocation
    np.multiply(f, (white_point - black_point), out=f)
    np.add(f, black_point, out=f)
    return np.clip(f, 0, 255).astype(np.uint8)
```

### 为什么使用 Gamma，而不是线性处理

线性乘数 `* 2.0`：
```
input 10  -> output 20   (still dark)
input 100 -> output 200  (ok)
input 200 -> output 255  (clipped, lost detail)
```

归一化后使用 Gamma 0.75：
```
input 0.04 -> output 0.08 (lifted from invisible to visible)
input 0.39 -> output 0.50 (moderate lift)
input 0.78 -> output 0.84 (gentle lift, no clipping)
```

Gamma < 1 会压缩高光并扩展阴影。这正是我们所需要的：在不令明亮部分过曝的前提下，将深色 ASCII 内容提升到可见范围。

### 流水线顺序

`render_clip()` 中的流水线如下：

```
scene_fn(r, f, t, S)  ->  canvas
         |
    tonemap(canvas, gamma=scene_gamma)
         |
    FeedbackBuffer.apply(canvas, ...)
         |
    ShaderChain.apply(canvas, f=f, t=t)
         |
    ffmpeg pipe
```

Tonemap 在 feedback 和 shaders 之前运行。这意味着：
- Feedback 在归一化数据上运行（无论场景亮度如何，行为都保持一致）
- solarize、posterize、contrast 等 shaders 会在范围正确的数据上运行
- 链中的 brightness shader 不再需要（tonemap 已经处理亮度）

### 逐场景 Gamma 调优

默认 gamma 为 0.75。应用破坏性后处理的场景需要更激进地提亮，因为破坏操作发生在 tonemap 之后：

| 场景类型 | 推荐 Gamma | 原因 |
|------------|-------------------|-----|
| 标准 effects | 0.75 | 默认值，适用于大多数场景 |
| Solarize 后处理 | 0.50-0.60 | Solarize 会反转明亮像素，降低整体亮度 |
| Posterize 后处理 | 0.50-0.55 | Posterize 会进行量化，常将中间值压为黑色 |
| 大量 difference 混合 | 0.60-0.70 | Difference 模式会产生许多接近零的像素 |
| 已经很亮的场景 | 0.85-1.0 | 不要过度增强本就明亮的场景 |

通过场景表进行配置：

```python
SCENES = [
    {"start": 9.17, "end": 11.25, "name": "fire", "gamma": 0.55,
     "fx": fx_fire, "shaders": [("solarize", {"threshold": 200}), ...]},
    {"start": 25.96, "end": 27.29, "name": "diamond", "gamma": 0.5,
     "fx": fx_diamond, "shaders": [("bloom", {"thr": 90}), ...]},
]
```

### 亮度验证

渲染后，抽查帧亮度：

```python
# In test-frame mode
canvas = scene["fx"](r, feat, t, r.S)
canvas = tonemap(canvas, gamma=scene.get("gamma", 0.75))
chain = ShaderChain()
for sn, kw in scene.get("shaders", []):
    chain.add(sn, **kw)
canvas = chain.apply(canvas, f=feat, t=t)
print(f"Mean brightness: {canvas.astype(float).mean():.1f}, max: {canvas.max()}")
```

tonemap + shaders 处理后的目标范围：
- 安静/氛围型场景：平均值 30-60
- 活跃场景：平均值 40-100
- 高潮/峰值场景：平均值 60-150
- 若平均值 < 20：gamma 过高，或某个 shader 正在破坏亮度
- 若平均值 > 180：gamma 过低，或 add 叠加过多

---

## FeedbackBuffer 空间变换

feedback buffer 会存储上一帧，并通过衰减将其混合到当前帧。若在混合前对 buffer 应用空间变换，就会令 feedback 轨迹产生运动错觉。

### 实现

```python
class FeedbackBuffer:
    def __init__(self):
        self.buf = None

    def apply(self, canvas, decay=0.85, blend="screen", opacity=0.5,
              transform=None, transform_amt=0.02, hue_shift=0.0):
        if self.buf is None:
            self.buf = canvas.astype(np.float32) / 255.0
            return canvas

        # Decay old buffer
        self.buf *= decay

        # Spatial transform
        if transform:
            self.buf = self._transform(self.buf, transform, transform_amt)

        # Hue shift the feedback for rainbow trails
        if hue_shift > 0:
            self.buf = self._hue_shift(self.buf, hue_shift)

        # Blend feedback into current frame
        result = blend_canvas(canvas,
                              np.clip(self.buf * 255, 0, 255).astype(np.uint8),
                              blend, opacity)

        # Update buffer with current frame
        self.buf = result.astype(np.float32) / 255.0
        return result

    def _transform(self, buf, transform, amt):
        h, w = buf.shape[:2]
        if transform == "zoom":
            # Zoom in: sample from slightly inside (creates expanding tunnel)
            m = int(h * amt); n = int(w * amt)
            if m > 0 and n > 0:
                cropped = buf[m:-m or None, n:-n or None]
                # Resize back to full (nearest-neighbor for speed)
                buf = np.array(Image.fromarray(
                    np.clip(cropped * 255, 0, 255).astype(np.uint8)
                ).resize((w, h), Image.NEAREST)).astype(np.float32) / 255.0
        elif transform == "shrink":
            # Zoom out: pad edges, shrink center
            m = int(h * amt); n = int(w * amt)
            small = np.array(Image.fromarray(
                np.clip(buf * 255, 0, 255).astype(np.uint8)
            ).resize((w - 2*n, h - 2*m), Image.NEAREST))
            new = np.zeros((h, w, 3), dtype=np.uint8)
            new[m:m+small.shape[0], n:n+small.shape[1]] = small
            buf = new.astype(np.float32) / 255.0
        elif transform == "rotate_cw":
            # Small clockwise rotation via affine
            angle = amt * 10  # amt=0.005 -> 0.05 degrees per frame
            cy, cx = h / 2, w / 2
            Y = np.arange(h, dtype=np.float32)[:, None]
            X = np.arange(w, dtype=np.float32)[None, :]
            cos_a, sin_a = np.cos(angle), np.sin(angle)
            sx = (X - cx) * cos_a + (Y - cy) * sin_a + cx
            sy = -(X - cx) * sin_a + (Y - cy) * cos_a + cy
            sx = np.clip(sx.astype(int), 0, w - 1)
            sy = np.clip(sy.astype(int), 0, h - 1)
            buf = buf[sy, sx]
        elif transform == "rotate_ccw":
            angle = -amt * 10
            cy, cx = h / 2, w / 2
            Y = np.arange(h, dtype=np.float32)[:, None]
            X = np.arange(w, dtype=np.float32)[None, :]
            cos_a, sin_a = np.cos(angle), np.sin(angle)
            sx = (X - cx) * cos_a + (Y - cy) * sin_a + cx
            sy = -(X - cx) * sin_a + (Y - cy) * cos_a + cy
            sx = np.clip(sx.astype(int), 0, w - 1)
            sy = np.clip(sy.astype(int), 0, h - 1)
            buf = buf[sy, sx]
        elif transform == "shift_up":
            pixels = max(1, int(h * amt))
            buf = np.roll(buf, -pixels, axis=0)
            buf[-pixels:] = 0  # black fill at bottom
        elif transform == "shift_down":
            pixels = max(1, int(h * amt))
            buf = np.roll(buf, pixels, axis=0)
            buf[:pixels] = 0
        elif transform == "mirror_h":
            buf = buf[:, ::-1]
        return buf

    def _hue_shift(self, buf, amount):
        """Rotate hues of the feedback buffer. Operates on float32 [0,1]."""
        rgb = np.clip(buf * 255, 0, 255).astype(np.uint8)
        hsv = np.zeros_like(buf)
        # Simple approximate RGB->HSV->shift->RGB
        r, g, b = buf[:,:,0], buf[:,:,1], buf[:,:,2]
        mx = np.maximum(np.maximum(r, g), b)
        mn = np.minimum(np.minimum(r, g), b)
        delta = mx - mn + 1e-10
        # Hue
        h = np.where(mx == r, ((g - b) / delta) % 6,
            np.where(mx == g, (b - r) / delta + 2, (r - g) / delta + 4))
        h = (h / 6 + amount) % 1.0
        # Reconstruct with shifted hue (simplified)
        s = delta / (mx + 1e-10)
        v = mx
        c = v * s; x = c * (1 - np.abs((h * 6) % 2 - 1)); m = v - c
        ro = np.zeros_like(h); go = np.zeros_like(h); bo = np.zeros_like(h)
        for lo, hi, rv, gv, bv in [(0,1,c,x,0),(1,2,x,c,0),(2,3,0,c,x),
                                     (3,4,0,x,c),(4,5,x,0,c),(5,6,c,0,x)]:
            mask = ((h*6) >= lo) & ((h*6) < hi)
            ro[mask] = rv[mask] if not isinstance(rv, (int,float)) else rv
            go[mask] = gv[mask] if not isinstance(gv, (int,float)) else gv
            bo[mask] = bv[mask] if not isinstance(bv, (int,float)) else bv
        return np.stack([ro+m, go+m, bo+m], axis=2)
```

### Feedback 预设

| 预设 | 配置 | 视觉效果 |
|--------|--------|---------------|
| 无限缩放隧道 | `decay=0.8, blend="screen", transform="zoom", transform_amt=0.015` | 向外扩张的环形图案 |
| 彩虹轨迹 | `decay=0.7, blend="screen", transform="zoom", transform_amt=0.01, hue_shift=0.02` | 迷幻的彩色轨迹 |
| 幽灵回声 | `decay=0.9, blend="add", opacity=0.15, transform="shift_up", transform_amt=0.01` | 淡淡向上拖影 |
| 万花筒递归 | `decay=0.75, blend="screen", transform="rotate_cw", transform_amt=0.005, hue_shift=0.01` | 旋转的曼陀罗 feedback |
| 色彩演化 | `decay=0.8, blend="difference", opacity=0.4, hue_shift=0.03` | 逐帧色彩 XOR |
| 上升的热浪 | `decay=0.5, blend="add", opacity=0.2, transform="shift_up", transform_amt=0.02` | 热空气闪烁 |

---

## 遮罩/模板系统

遮罩是范围在 [0, 1] 内的 float32 数组 `(rows, cols)` 或 `(VH, VW)`。它们控制 effects 在何处可见：1.0 = 完全可见，0.0 = 完全隐藏。可使用遮罩创建图形/背景关系、视觉焦点和特定形状的显现效果。

### 形状遮罩

```python
def mask_circle(g, cx_frac=0.5, cy_frac=0.5, radius=0.3, feather=0.05):
    """Circular mask centered at (cx_frac, cy_frac) in normalized coords.
    feather: width of soft edge (0 = hard cutoff)."""
    asp = g.cw / g.ch if hasattr(g, 'cw') else 1.0
    dx = (g.cc / g.cols - cx_frac)
    dy = (g.rr / g.rows - cy_frac) * asp
    d = np.sqrt(dx**2 + dy**2)
    if feather > 0:
        return np.clip(1.0 - (d - radius) / feather, 0, 1)
    return (d <= radius).astype(np.float32)

def mask_rect(g, x0=0.2, y0=0.2, x1=0.8, y1=0.8, feather=0.03):
    """Rectangular mask. Coordinates in [0,1] normalized."""
    dx = np.maximum(x0 - g.cc / g.cols, g.cc / g.cols - x1)
    dy = np.maximum(y0 - g.rr / g.rows, g.rr / g.rows - y1)
    d = np.maximum(dx, dy)
    if feather > 0:
        return np.clip(1.0 - d / feather, 0, 1)
    return (d <= 0).astype(np.float32)

def mask_ring(g, cx_frac=0.5, cy_frac=0.5, inner_r=0.15, outer_r=0.35,
              feather=0.03):
    """Ring / annulus mask."""
    inner = mask_circle(g, cx_frac, cy_frac, inner_r, feather)
    outer = mask_circle(g, cx_frac, cy_frac, outer_r, feather)
    return outer - inner

def mask_gradient_h(g, start=0.0, end=1.0):
    """Left-to-right gradient mask."""
    return np.clip((g.cc / g.cols - start) / (end - start + 1e-10), 0, 1).astype(np.float32)

def mask_gradient_v(g, start=0.0, end=1.0):
    """Top-to-bottom gradient mask."""
    return np.clip((g.rr / g.rows - start) / (end - start + 1e-10), 0, 1).astype(np.float32)

def mask_gradient_radial(g, cx_frac=0.5, cy_frac=0.5, inner=0.0, outer=0.5):
    """Radial gradient mask — bright at center, dark at edges."""
    d = np.sqrt((g.cc / g.cols - cx_frac)**2 + (g.rr / g.rows - cy_frac)**2)
    return np.clip(1.0 - (d - inner) / (outer - inner + 1e-10), 0, 1)
```

### 将值场用作遮罩

可将任意 `vf_*` 函数的输出用作空间遮罩：

```python
def mask_from_vf(vf_result, threshold=0.5, feather=0.1):
    """Convert a value field to a mask by thresholding.
    feather: smooth edge width around threshold."""
    if feather > 0:
        return np.clip((vf_result - threshold + feather) / (2 * feather), 0, 1)
    return (vf_result > threshold).astype(np.float32)

def mask_select(mask, vf_a, vf_b):
    """Spatial conditional: show vf_a where mask is 1, vf_b where mask is 0.
    mask: float32 [0,1] array. Intermediate values blend."""
    return vf_a * mask + vf_b * (1 - mask)
```

### 文本模板

将文本渲染成遮罩。effects 仅透过字形可见：

```python
def mask_text(grid, text, row_frac=0.5, font=None, font_size=None):
    """Render text string as a float32 mask [0,1] at grid resolution.
    Characters = 1.0, background = 0.0.

    row_frac: vertical position as fraction of grid height.
    font: PIL ImageFont (defaults to grid's font if None).
    font_size: override font size for the mask text (for larger stencil text).
    """
    from PIL import Image, ImageDraw, ImageFont

    f = font or grid.font
    if font_size and font != grid.font:
        f = ImageFont.truetype(font.path, font_size)

    # Render text to image at pixel resolution, then downsample to grid
    img = Image.new("L", (grid.cols * grid.cw, grid.ch), 0)
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), text, font=f)
    tw = bbox[2] - bbox[0]
    x = (grid.cols * grid.cw - tw) // 2
    draw.text((x, 0), text, fill=255, font=f)
    row_mask = np.array(img, dtype=np.float32) / 255.0

    # Place in full grid mask
    mask = np.zeros((grid.rows, grid.cols), dtype=np.float32)
    target_row = int(grid.rows * row_frac)
    # Downsample rendered text to grid cells
    for c in range(grid.cols):
        px = c * grid.cw
        if px + grid.cw <= row_mask.shape[1]:
            cell = row_mask[:, px:px + grid.cw]
            if cell.mean() > 0.1:
                mask[target_row, c] = cell.mean()
    return mask

def mask_text_block(grid, lines, start_row_frac=0.3, font=None):
    """Multi-line text stencil. Returns full grid mask."""
    mask = np.zeros((grid.rows, grid.cols), dtype=np.float32)
    for i, line in enumerate(lines):
        row_frac = start_row_frac + i / grid.rows
        line_mask = mask_text(grid, line, row_frac, font)
        mask = np.maximum(mask, line_mask)
    return mask
```

### 动画遮罩

随时间变化的遮罩，可用于显现、擦除和变形：

```python
def mask_iris(g, t, t_start, t_end, cx_frac=0.5, cy_frac=0.5,
              max_radius=0.7, ease_fn=None):
    """Iris open/close: circle that grows from 0 to max_radius.
    ease_fn: easing function (default: ease_in_out_cubic from effects.md)."""
    if ease_fn is None:
        ease_fn = lambda x: x * x * (3 - 2 * x)  # smoothstep fallback
    progress = np.clip((t - t_start) / (t_end - t_start), 0, 1)
    radius = ease_fn(progress) * max_radius
    return mask_circle(g, cx_frac, cy_frac, radius, feather=0.03)

def mask_wipe_h(g, t, t_start, t_end, direction="right"):
    """Horizontal wipe reveal."""
    progress = np.clip((t - t_start) / (t_end - t_start), 0, 1)
    if direction == "left":
        progress = 1 - progress
    return mask_gradient_h(g, start=progress - 0.05, end=progress + 0.05)

def mask_wipe_v(g, t, t_start, t_end, direction="down"):
    """Vertical wipe reveal."""
    progress = np.clip((t - t_start) / (t_end - t_start), 0, 1)
    if direction == "up":
        progress = 1 - progress
    return mask_gradient_v(g, start=progress - 0.05, end=progress + 0.05)

def mask_dissolve(g, t, t_start, t_end, seed=42):
    """Random pixel dissolve — noise threshold sweeps from 0 to 1."""
    progress = np.clip((t - t_start) / (t_end - t_start), 0, 1)
    rng = np.random.RandomState(seed)
    noise = rng.random((g.rows, g.cols)).astype(np.float32)
    return (noise < progress).astype(np.float32)
```

### 遮罩布尔运算

```python
def mask_union(a, b):
    """OR — visible where either mask is active."""
    return np.maximum(a, b)

def mask_intersect(a, b):
    """AND — visible only where both masks are active."""
    return np.minimum(a, b)

def mask_subtract(a, b):
    """A minus B — visible where A is active but B is not."""
    return np.clip(a - b, 0, 1)

def mask_invert(m):
    """NOT — flip mask."""
    return 1.0 - m
```

### 将遮罩应用到画布

```python
def apply_mask_canvas(canvas, mask, bg_canvas=None):
    """Apply a grid-resolution mask to a pixel canvas.
    Expands mask from (rows, cols) to (VH, VW) via nearest-neighbor.

    canvas: uint8 (VH, VW, 3)
    mask: float32 (rows, cols) [0,1]
    bg_canvas: what shows through where mask=0. None = black.
    """
    # Expand mask to pixel resolution
    mask_px = np.repeat(np.repeat(mask, canvas.shape[0] // mask.shape[0] + 1, axis=0),
                        canvas.shape[1] // mask.shape[1] + 1, axis=1)
    mask_px = mask_px[:canvas.shape[0], :canvas.shape[1]]

    if bg_canvas is not None:
        return np.clip(canvas * mask_px[:, :, None] +
                       bg_canvas * (1 - mask_px[:, :, None]), 0, 255).astype(np.uint8)
    return np.clip(canvas * mask_px[:, :, None], 0, 255).astype(np.uint8)

def apply_mask_vf(vf_a, vf_b, mask):
    """Apply mask at value-field level — blend two value fields spatially.
    All arrays are (rows, cols) float32."""
    return vf_a * mask + vf_b * (1 - mask)
```

---

## PixelBlendStack

用于多图层 compositing 的高层封装：

```python
class PixelBlendStack:
    def __init__(self):
        self.layers = []

    def add(self, canvas, mode="normal", opacity=1.0):
        self.layers.append((canvas, mode, opacity))
        return self

    def composite(self):
        if not self.layers:
            return np.zeros((VH, VW, 3), dtype=np.uint8)
        result = self.layers[0][0]
        for canvas, mode, opacity in self.layers[1:]:
            result = blend_canvas(result, canvas, mode, opacity)
        return result
```

## 文本衬底（可读性遮罩）

在繁复的多网格 ASCII 背景上放置可读文本时，文本会融入背景而变得难以辨认。**务必在文本区域背后应用深色衬底。**

方法是：计算所有文本字形的边界框，创建一个带留白、覆盖该区域并经过高斯模糊的深色遮罩，然后先将背景乘以 `(1 - mask * darkness)`，再在其上渲染文本。

```python
from scipy.ndimage import gaussian_filter

def apply_text_backdrop(canvas, glyphs, padding=80, darkness=0.75):
    """Darken the background behind text for readability.
    
    Call AFTER rendering background, BEFORE rendering text.
    
    Args:
        canvas: (VH, VW, 3) uint8 background
        glyphs: list of {"x": float, "y": float, ...} glyph positions
        padding: pixel padding around text bounding box
        darkness: 0.0 = no darkening, 1.0 = fully black
    Returns:
        darkened canvas (uint8)
    """
    if not glyphs:
        return canvas
    xs = [g['x'] for g in glyphs]
    ys = [g['y'] for g in glyphs]
    x0 = max(0, int(min(xs)) - padding)
    y0 = max(0, int(min(ys)) - padding)
    x1 = min(VW, int(max(xs)) + padding + 50)   # extra for char width
    y1 = min(VH, int(max(ys)) + padding + 60)   # extra for char height
    
    # Soft dark mask with gaussian blur for feathered edges
    mask = np.zeros((VH, VW), dtype=np.float32)
    mask[y0:y1, x0:x1] = 1.0
    mask = gaussian_filter(mask, sigma=padding * 0.6)
    
    factor = 1.0 - mask * darkness
    return (canvas.astype(np.float32) * factor[:, :, np.newaxis]).astype(np.uint8)
```

### 在渲染流水线中使用

插入到背景渲染和文本渲染之间：

```python
# 1. Render background (multi-grid ASCII effects)
bg = render_background(cfg, t)

# 2. Darken behind text region
bg = apply_text_backdrop(bg, frame_glyphs, padding=80, darkness=0.75)

# 3. Render text on top (now readable against dark backdrop)
bg = text_renderer.render(bg, frame_glyphs, color=(255, 255, 255))
```

对于文本始终居中的场景，可将其与**反向晕影**（参见 shaders.md）结合使用——反向晕影可持续提供中央暗区，而衬底则负责适配逐帧字形位置。

## 外部布局预言机模式

对于文本繁多、需要绕开障碍物（形状、图标、其他文本）动态重排的影片，可以使用外部布局引擎预先计算字形位置，并通过 JSON 将其送入 Python renderer。

### 架构

```
Layout Engine (browser/Node.js)  →  layouts.json  →  Python ASCII Renderer
         ↑                                                    ↑
   Computes per-frame                               Reads glyph positions,
   glyph (x,y) positions                            renders as ASCII chars
   with obstacle-aware reflow                        with full effect pipeline
```

### JSON 交换格式

```json
{
  "meta": {
    "canvas_width": 1080, "canvas_height": 1080,
    "fps": 24, "total_frames": 1248,
    "fonts": {
      "body": {"charW": 12.04, "charH": 24, "fontSize": 20},
      "hero": {"charW": 24.08, "charH": 48, "fontSize": 40}
    }
  },
  "scenes": [
    {
      "id": "scene_name",
      "start_frame": 0, "end_frame": 96,
      "frames": {
        "0": {
          "glyphs": [
            {"char": "H", "x": 287.1, "y": 400.0, "alpha": 1.0},
            {"char": "e", "x": 311.2, "y": 400.0, "alpha": 1.0}
          ],
          "obstacles": [
            {"type": "circle", "cx": 540, "cy": 540, "r": 80},
            {"type": "rect", "x": 300, "y": 500, "w": 120, "h": 80}
          ]
        }
      }
    }
  ]
}
```

### 适用场景

- 绕移动物体动态重排的文本
- 逐字形动画（显现、散开、物理运动）
- 需要精确测量的可变排版
- Python 的 Pillow 文本布局不足以满足需求的任何情况

### 不适用场景

- 静态居中文本（直接使用 PIL `draw.text()` 即可）
- 仅淡入/淡出而没有空间动画的文本
- 简单的打字机效果（在 Python 中使用字符计数器处理）

### 运行预言机

使用 Playwright 在无头浏览器中运行布局引擎：

```javascript
// extract.mjs
import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
await page.goto(`file://${oraclePath}`);
await page.waitForFunction(() => window.__ORACLE_DONE__ === true, null, { timeout: 60000 });
const result = await page.evaluate(() => window.__ORACLE_RESULT__);
writeFileSync('layouts.json', JSON.stringify(result));
await browser.close();
```

### 在 Python 中使用

```python
# In the renderer, map pixel positions to the canvas:
for glyph in frame_data['glyphs']:
    char, px, py = glyph['char'], glyph['x'], glyph['y']
    alpha = glyph.get('alpha', 1.0)
    # Render using PIL draw.text() at exact pixel position
    draw.text((px, py), char, fill=(int(255*alpha),)*3, font=font)
```

JSON 中的障碍物也可以渲染为发光的 ASCII 形状（圆形、矩形），以便可视化重排区域。
