# Shader 管线与可组合效果

在字符渲染之后、编码之前，应用于像素画布（`numpy uint8 array, shape (H,W,3)`）的后处理效果。还涵盖**像素级混合模式**、**反馈缓冲区**和 **ShaderChain** 合成器。

> **另请参阅：** composition.md（混合模式、色调映射）· effects.md · scenes.md · architecture.md · optimization.md · troubleshooting.md
>
> **混合模式：** 关于 20 种像素混合模式和 `blend_canvas()`，请参阅 `composition.md`。所有混合均使用 `blend_canvas(base, top, mode, opacity)`。

## 设计理念

Shader 管线将原始 ASCII 渲染转换为电影感输出。系统以**可组合性**为设计核心——每个 shader、混合模式和反馈变换都是独立的构建块。将它们组合起来，只需少量基础元素即可创造出无限多样的视觉效果。

选择能够强化氛围的 shader：
- **复古终端**：CRT + 扫描线 + 颗粒 + 绿色/琥珀色色调
- **简洁现代**：仅使用轻微 bloom + 柔和暗角
- **故障艺术**：强烈色差 + 故障条带 + 色彩波动 + 像素排序
- **电影感**：bloom + 暗角 + 颗粒 + 色彩分级
- **梦幻感**：强烈 bloom + 柔焦 + 色彩波动 + 低对比度
- **冷峻/工业风**：高对比度 + 颗粒 + 扫描线 + 无 bloom
- **迷幻风**：色彩波动 + 色差 + 万花筒镜像 + 高饱和度 + 带色相偏移的反馈
- **数据损坏**：像素排序 + 数据弯曲 + 块状故障 + 色调分离
- **递归/无限**：带缩放的反馈缓冲区 + 滤色混合 + 色相偏移

---

## 像素级混合模式

为保证精度，所有操作都在 float32 [0,1] 画布上进行。使用 `blend_canvas(base, top, mode, opacity)`，它会处理 uint8 <-> float 转换。

### 可用模式

```python
BLEND_MODES = {
    "normal":       lambda a, b: b,
    "add":          lambda a, b: np.clip(a + b, 0, 1),
    "subtract":     lambda a, b: np.clip(a - b, 0, 1),
    "multiply":     lambda a, b: a * b,
    "screen":       lambda a, b: 1 - (1-a)*(1-b),
    "overlay":      # 2*a*b if a<0.5, else 1-2*(1-a)*(1-b)
    "softlight":    lambda a, b: (1-2*b)*a*a + 2*b*a,
    "hardlight":    # like overlay but keyed on b
    "difference":   lambda a, b: abs(a - b),
    "exclusion":    lambda a, b: a + b - 2*a*b,
    "colordodge":   lambda a, b: a / (1-b),
    "colorburn":    lambda a, b: 1 - (1-a)/b,
    "linearlight":  lambda a, b: a + 2*b - 1,
    "vividlight":   # burn if b<0.5, dodge if b>=0.5
    "pin_light":    # min(a,2b) if b<0.5, max(a,2b-1) if b>=0.5
    "hard_mix":     lambda a, b: 1 if a+b>=1 else 0,
    "lighten":      lambda a, b: max(a, b),
    "darken":       lambda a, b: min(a, b),
    "grain_extract": lambda a, b: a - b + 0.5,
    "grain_merge":  lambda a, b: a + b - 0.5,
}
```

### 用法

```python
def blend_canvas(base, top, mode="normal", opacity=1.0):
    """Blend two uint8 canvases (H,W,3) using a named blend mode + opacity."""
    af = base.astype(np.float32) / 255.0
    bf = top.astype(np.float32) / 255.0
    result = BLEND_MODES[mode](af, bf)
    if opacity < 1.0:
        result = af * (1-opacity) + result * opacity
    return np.clip(result * 255, 0, 255).astype(np.uint8)

# Multi-layer compositing
result = blend_canvas(base, layer_a, "screen", 0.7)
result = blend_canvas(result, layer_b, "difference", 0.5)
result = blend_canvas(result, layer_c, "multiply", 0.3)
```

### 创意组合

- **反馈 + 差值** = 迷幻的色彩演化（每一帧都与前一帧执行 XOR）
- **滤色 + 滤色** = 叠加式辉光堆叠
- 对两种不同效果使用**正片叠底** = 仅显示两者都有亮度的区域（交集）
- 在两个图层之间使用**排除** = 在二者不同之处产生互补图案
- **颜色减淡/加深** = 极大增强重叠区域的对比度
- **实色混合** = 将交叠处的一切简化为纯黑/纯白/纯色

---

## 反馈缓冲区

递归时间效果：第 N-1 帧经过衰减和可选的空间变换后反馈到第 N 帧。可产生拖尾、回声、涂抹、缩放隧道、旋转反馈和彩虹轨迹。

```python
class FeedbackBuffer:
    def __init__(self):
        self.buf = None  # previous frame (float32, 0-1)
    
    def apply(self, canvas, decay=0.85, blend="screen", opacity=0.5,
              transform=None, transform_amt=0.02, hue_shift=0.0):
        """Mix current frame with decayed/transformed previous frame.
        
        Args:
            canvas: current frame (uint8 H,W,3)
            decay: how fast old frame fades (0=instant, 1=permanent)
            blend: blend mode for mixing feedback
            opacity: strength of feedback mix
            transform: None, "zoom", "shrink", "rotate_cw", "rotate_ccw",
                       "shift_up", "shift_down", "mirror_h"
            transform_amt: strength of spatial transform per frame
            hue_shift: rotate hue of feedback buffer each frame (0-1)
        """
```

### 反馈预设

```python
# Infinite zoom tunnel
fb_cfg = {"decay": 0.8, "blend": "screen", "opacity": 0.4,
          "transform": "zoom", "transform_amt": 0.015}

# Rainbow trails (psychedelic)
fb_cfg = {"decay": 0.7, "blend": "screen", "opacity": 0.3,
          "transform": "zoom", "transform_amt": 0.01, "hue_shift": 0.02}

# Ghostly echo (horror)
fb_cfg = {"decay": 0.9, "blend": "add", "opacity": 0.15,
          "transform": "shift_up", "transform_amt": 0.01}

# Kaleidoscopic recursion
fb_cfg = {"decay": 0.75, "blend": "screen", "opacity": 0.35,
          "transform": "rotate_cw", "transform_amt": 0.005, "hue_shift": 0.01}

# Color evolution (abstract)
fb_cfg = {"decay": 0.8, "blend": "difference", "opacity": 0.4, "hue_shift": 0.03}

# Multiplied depth
fb_cfg = {"decay": 0.65, "blend": "multiply", "opacity": 0.3, "transform": "mirror_h"}

# Rising heat haze
fb_cfg = {"decay": 0.5, "blend": "add", "opacity": 0.2,
          "transform": "shift_up", "transform_amt": 0.02}
```

---

## ShaderChain

可组合的 shader 管线。使用带参数的命名 shader 构建处理链。顺序很重要——shader 会依次应用到画布上。

```python
class ShaderChain:
    """Composable shader pipeline.
    
    Usage:
        chain = ShaderChain()
        chain.add("bloom", thr=120)
        chain.add("chromatic", amt=5)
        chain.add("kaleidoscope", folds=6)
        chain.add("vignette", s=0.2)
        chain.add("grain", amt=12)
        canvas = chain.apply(canvas, f=features, t=time)
    """
    def __init__(self):
        self.steps = []

    def add(self, shader_name, **kwargs):
        self.steps.append((shader_name, kwargs))
        return self  # chainable

    def apply(self, canvas, f=None, t=0):
        if f is None: f = {}
        for name, kwargs in self.steps:
            canvas = _apply_shader_step(canvas, name, kwargs, f, t)
        return canvas
```

### `_apply_shader_step()` — 完整分派函数

将 shader 名称路由到相应实现。部分 shader 支持**音频响应式缩放**——分派函数读取 `f["bdecay"]` 和 `f["rms"]`，根据节拍调制参数。

```python
def _apply_shader_step(canvas, name, kwargs, f, t):
    """Dispatch a single shader by name with kwargs.
    
    Args:
        canvas: uint8 (H,W,3) pixel array
        name: shader key string (e.g. "bloom", "chromatic")
        kwargs: dict of shader parameters
        f: audio features dict (keys: bdecay, rms, sub, etc.)
        t: current time in seconds (float)
    Returns:
        canvas: uint8 (H,W,3) — processed
    """
    bd = f.get("bdecay", 0)    # beat decay (0-1, high on beat)
    rms = f.get("rms", 0.3)   # audio energy (0-1)

    # --- Geometry ---
    if name == "crt":
        return sh_crt(canvas, kwargs.get("strength", 0.05))
    elif name == "pixelate":
        return sh_pixelate(canvas, kwargs.get("block", 4))
    elif name == "wave_distort":
        return sh_wave_distort(canvas, t,
            kwargs.get("freq", 0.02), kwargs.get("amp", 8), kwargs.get("axis", "x"))
    elif name == "kaleidoscope":
        return sh_kaleidoscope(canvas.copy(), kwargs.get("folds", 6))
    elif name == "mirror_h":
        return sh_mirror_h(canvas.copy())
    elif name == "mirror_v":
        return sh_mirror_v(canvas.copy())
    elif name == "mirror_quad":
        return sh_mirror_quad(canvas.copy())
    elif name == "mirror_diag":
        return sh_mirror_diag(canvas.copy())

    # --- Channel ---
    elif name == "chromatic":
        base = kwargs.get("amt", 3)
        return sh_chromatic(canvas, max(1, int(base * (0.4 + bd * 0.8))))
    elif name == "channel_shift":
        return sh_channel_shift(canvas,
            kwargs.get("r", (0,0)), kwargs.get("g", (0,0)), kwargs.get("b", (0,0)))
    elif name == "channel_swap":
        return sh_channel_swap(canvas, kwargs.get("order", (2,1,0)))
    elif name == "rgb_split_radial":
        return sh_rgb_split_radial(canvas, kwargs.get("strength", 5))

    # --- Color ---
    elif name == "invert":
        return sh_invert(canvas)
    elif name == "posterize":
        return sh_posterize(canvas, kwargs.get("levels", 4))
    elif name == "threshold":
        return sh_threshold(canvas, kwargs.get("thr", 128))
    elif name == "solarize":
        return sh_solarize(canvas, kwargs.get("threshold", 128))
    elif name == "hue_rotate":
        return sh_hue_rotate(canvas, kwargs.get("amount", 0.1))
    elif name == "saturation":
        return sh_saturation(canvas, kwargs.get("factor", 1.5))
    elif name == "color_grade":
        return sh_color_grade(canvas, kwargs.get("tint", (1,1,1)))
    elif name == "color_wobble":
        return sh_color_wobble(canvas, t, kwargs.get("amt", 0.3) * (0.5 + rms * 0.8))
    elif name == "color_ramp":
        return sh_color_ramp(canvas, kwargs.get("ramp", [(0,0,0),(255,255,255)]))

    # --- Glow / Blur ---
    elif name == "bloom":
        return sh_bloom(canvas, kwargs.get("thr", 130))
    elif name == "edge_glow":
        return sh_edge_glow(canvas, kwargs.get("hue", 0.5))
    elif name == "soft_focus":
        return sh_soft_focus(canvas, kwargs.get("strength", 0.3))
    elif name == "radial_blur":
        return sh_radial_blur(canvas, kwargs.get("strength", 0.03))

    # --- Noise ---
    elif name == "grain":
        return sh_grain(canvas, int(kwargs.get("amt", 10) * (0.5 + rms * 0.8)))
    elif name == "static":
        return sh_static_noise(canvas, kwargs.get("density", 0.05), kwargs.get("color", True))

    # --- Lines / Patterns ---
    elif name == "scanlines":
        return sh_scanlines(canvas, kwargs.get("intensity", 0.08), kwargs.get("spacing", 3))
    elif name == "halftone":
        return sh_halftone(canvas, kwargs.get("dot_size", 6))

    # --- Tone ---
    elif name == "vignette":
        return sh_vignette(canvas, kwargs.get("s", 0.22))
    elif name == "contrast":
        return sh_contrast(canvas, kwargs.get("factor", 1.3))
    elif name == "gamma":
        return sh_gamma(canvas, kwargs.get("gamma", 1.5))
    elif name == "levels":
        return sh_levels(canvas,
            kwargs.get("black", 0), kwargs.get("white", 255), kwargs.get("midtone", 1.0))
    elif name == "brightness":
        return sh_brightness(canvas, kwargs.get("factor", 1.5))

    # --- Glitch / Data ---
    elif name == "glitch_bands":
        return sh_glitch_bands(canvas, f)
    elif name == "block_glitch":
        return sh_block_glitch(canvas, kwargs.get("n_blocks", 8), kwargs.get("max_size", 40))
    elif name == "pixel_sort":
        return sh_pixel_sort(canvas, kwargs.get("threshold", 100), kwargs.get("direction", "h"))
    elif name == "data_bend":
        return sh_data_bend(canvas, kwargs.get("offset", 1000), kwargs.get("chunk", 500))

    else:
        return canvas  # unknown shader — passthrough
```

### 音频响应式 Shader

三个 shader 会根据音频特征缩放其参数：

| Shader | 响应对象 | 效果 |
|--------|------------|--------|
| `chromatic` | `bdecay` | `amt * (0.4 + bdecay * 0.8)` — 节拍出现时色差增强 |
| `color_wobble` | `rms` | `amt * (0.5 + rms * 0.8)` — 波动强度跟随能量变化 |
| `grain` | `rms` | `amt * (0.5 + rms * 0.8)` — 响亮片段中的颗粒更粗糙 |
| `glitch_bands` | `bdecay`, `sub` | 条带数量和位移随节拍能量缩放 |

要让任意 shader 响应节拍，可在分派函数中缩放其参数：`base_val * (low + bd * range)`。

---

## 完整 Shader 目录

### 几何 Shader

| Shader | 关键参数 | 说明 |
|--------|-----------|-------------|
| `crt` | `strength=0.05` | CRT 桶形畸变（缓存重映射） |
| `pixelate` | `block=4` | 降低有效分辨率 |
| `wave_distort` | `freq, amp, axis` | 正弦式行/列位移 |
| `kaleidoscope` | `folds=6` | 通过极坐标重映射实现径向对称 |
| `mirror_h` | — | 水平镜像 |
| `mirror_v` | — | 垂直镜像 |
| `mirror_quad` | — | 四重镜像 |
| `mirror_diag` | — | 对角镜像 |

### 通道操作

| Shader | 关键参数 | 说明 |
|--------|-----------|-------------|
| `chromatic` | `amt=3` | R/B 通道水平偏移（响应节拍） |
| `channel_shift` | `r=(sx,sy), g, b` | 各通道独立进行 x、y 偏移 |
| `channel_swap` | `order=(2,1,0)` | 重新排列 RGB 通道（BGR、GRB 等） |
| `rgb_split_radial` | `strength=5` | 从中心向外辐射的色差 |

### 色彩操作

| Shader | 关键参数 | 说明 |
|--------|-----------|-------------|
| `invert` | — | 反转所有颜色 |
| `posterize` | `levels=4` | 将色深减少为 N 级 |
| `threshold` | `thr=128` | 二值黑白 |
| `solarize` | `threshold=128` | 对高于阈值的像素进行日光化反转 |
| `hue_rotate` | `amount=0.1` | 将所有色相旋转指定量（0-1） |
| `saturation` | `factor=1.5` | 缩放饱和度（>1=更高，<1=更低） |
| `color_grade` | `tint=(r,g,b)` | 逐通道乘数 |
| `color_wobble` | `amt=0.3` | 随时间变化的逐通道正弦调制 |
| `color_ramp` | `ramp=[(R,G,B),...]` | 将亮度映射到自定义颜色渐变 |

### 辉光/模糊

| Shader | 关键参数 | 说明 |
|--------|-----------|-------------|
| `bloom` | `thr=130` | 明亮区域辉光（4 倍下采样 + 方框模糊） |
| `edge_glow` | `hue=0.5` | 检测边缘并添加彩色叠加层 |
| `soft_focus` | `strength=0.3` | 与模糊版本混合 |
| `radial_blur` | `strength=0.03` | 从中心向外的缩放模糊 |

### 噪声/颗粒

| Shader | 关键参数 | 说明 |
|--------|-----------|-------------|
| `grain` | `amt=10` | 2 倍下采样的胶片颗粒（响应节拍） |
| `static` | `density=0.05, color=True` | 随机像素噪声（电视雪花） |

### 线条/图案

| Shader | 关键参数 | 说明 |
|--------|-----------|-------------|
| `scanlines` | `intensity=0.08, spacing=3` | 将每第 N 行变暗 |
| `halftone` | `dot_size=6` | 半色调网点图案叠加层 |

### 色调

| Shader | 关键参数 | 说明 |
|--------|-----------|-------------|
| `vignette` | `s=0.22` | 边缘压暗（缓存距离场） |
| `contrast` | `factor=1.3` | 围绕中点 128 调整对比度 |
| `gamma` | `gamma=1.5` | Gamma 校正（>1=中间调更亮） |
| `levels` | `black, white, midtone` | 色阶调整（Photoshop 风格） |
| `brightness` | `factor=1.5` | 全局亮度乘数 |

### 故障/数据

| Shader | 关键参数 | 说明 |
|--------|-----------|-------------|
| `glitch_bands` |（使用 `f`） | 响应节拍的水平行位移 |
| `block_glitch` | `n_blocks=8, max_size=40` | 随机矩形块位移 |
| `pixel_sort` | `threshold=100, direction="h"` | 按亮度对行/列中的像素排序 |
| `data_bend` | `offset, chunk` | 原始字节位移（datamoshing） |

---

## Shader 实现

每个 shader 函数接收一个画布（`uint8 H,W,3`），并返回形状相同的画布。命名约定为 `sh_<name>`。构建坐标重映射表的几何 shader 应当**缓存**这些表，因为它们只取决于分辨率和参数，而与帧内容无关。

### 辅助函数

操作色相/饱和度的 shader 需要向量化 HSV 转换：

```python
def rgb2hsv(r, g, b):
    """Vectorized RGB (0-255 uint8) -> HSV (float32 0-1)."""
    rf = r.astype(np.float32) / 255.0
    gf = g.astype(np.float32) / 255.0
    bf = b.astype(np.float32) / 255.0
    cmax = np.maximum(np.maximum(rf, gf), bf)
    cmin = np.minimum(np.minimum(rf, gf), bf)
    delta = cmax - cmin + 1e-10
    h = np.zeros_like(rf)
    m = cmax == rf; h[m] = ((gf[m] - bf[m]) / delta[m]) % 6
    m = cmax == gf; h[m] = (bf[m] - rf[m]) / delta[m] + 2
    m = cmax == bf; h[m] = (rf[m] - gf[m]) / delta[m] + 4
    h = h / 6.0 % 1.0
    s = np.where(cmax > 0, delta / (cmax + 1e-10), 0)
    return h, s, cmax

def hsv2rgb(h, s, v):
    """Vectorized HSV->RGB. h,s,v are numpy float32 arrays."""
    h = h % 1.0
    c = v * s; x = c * (1 - np.abs((h * 6) % 2 - 1)); m = v - c
    r = np.zeros_like(h); g = np.zeros_like(h); b = np.zeros_like(h)
    mask = h < 1/6;            r[mask]=c[mask]; g[mask]=x[mask]
    mask = (h>=1/6)&(h<2/6);   r[mask]=x[mask]; g[mask]=c[mask]
    mask = (h>=2/6)&(h<3/6);   g[mask]=c[mask]; b[mask]=x[mask]
    mask = (h>=3/6)&(h<4/6);   g[mask]=x[mask]; b[mask]=c[mask]
    mask = (h>=4/6)&(h<5/6);   r[mask]=x[mask]; b[mask]=c[mask]
    mask = h >= 5/6;            r[mask]=c[mask]; b[mask]=x[mask]
    R = np.clip((r+m)*255, 0, 255).astype(np.uint8)
    G = np.clip((g+m)*255, 0, 255).astype(np.uint8)
    B = np.clip((b+m)*255, 0, 255).astype(np.uint8)
    return R, G, B

def mkc(R, G, B, rows, cols):
    """Stack R,G,B uint8 arrays into (rows,cols,3) canvas."""
    o = np.zeros((rows, cols, 3), dtype=np.uint8)
    o[:,:,0] = R; o[:,:,1] = G; o[:,:,2] = B
    return o
```

---

### 几何 Shader

#### CRT 桶形畸变
缓存坐标重映射——它不会随帧变化：
```python
_crt_cache = {}
def sh_crt(c, strength=0.05):
    k = (c.shape[0], c.shape[1], round(strength, 3))
    if k not in _crt_cache:
        h, w = c.shape[:2]; cy, cx = h/2, w/2
        Y = np.arange(h, dtype=np.float32)[:, None]
        X = np.arange(w, dtype=np.float32)[None, :]
        ny = (Y - cy) / cy; nx = (X - cx) / cx
        r2 = nx**2 + ny**2
        factor = 1 + strength * r2
        sx = np.clip((nx * factor * cx + cx), 0, w-1).astype(np.int32)
        sy = np.clip((ny * factor * cy + cy), 0, h-1).astype(np.int32)
        _crt_cache[k] = (sy, sx)
    sy, sx = _crt_cache[k]
    return c[sy, sx]
```

#### 像素化
```python
def sh_pixelate(c, block=4):
    """Reduce effective resolution."""
    sm = c[::block, ::block]
    return np.repeat(np.repeat(sm, block, axis=0), block, axis=1)[:c.shape[0], :c.shape[1]]
```

#### 波形畸变
```python
def sh_wave_distort(c, t, freq=0.02, amp=8, axis="x"):
    """Sinusoidal row/column displacement. Uses time t for animation."""
    h, w = c.shape[:2]
    out = c.copy()
    if axis == "x":
        for y in range(h):
            shift = int(amp * math.sin(y * freq + t * 3))
            out[y] = np.roll(c[y], shift, axis=0)
    else:
        for x in range(w):
            shift = int(amp * math.sin(x * freq + t * 3))
            out[:, x] = np.roll(c[:, x], shift, axis=0)
    return out
```

#### 位移贴图
```python
def sh_displacement_map(c, dx_map, dy_map, strength=10):
    """Displace pixels using float32 displacement maps (same HxW as c).
    dx_map/dy_map: positive = shift right/down."""
    h, w = c.shape[:2]
    Y = np.arange(h)[:, None]; X = np.arange(w)[None, :]
    ny = np.clip((Y + (dy_map * strength).astype(int)), 0, h-1)
    nx = np.clip((X + (dx_map * strength).astype(int)), 0, w-1)
    return c[ny, nx]
```

#### 万花筒
```python
def sh_kaleidoscope(c, folds=6):
    """Radial symmetry by polar coordinate remapping."""
    h, w = c.shape[:2]; cy, cx = h//2, w//2
    Y = np.arange(h, dtype=np.float32)[:, None] - cy
    X = np.arange(w, dtype=np.float32)[None, :] - cx
    angle = np.arctan2(Y, X)
    dist = np.sqrt(X**2 + Y**2)
    wedge = 2 * np.pi / folds
    folded_angle = np.abs((angle % wedge) - wedge/2)
    ny = np.clip((cy + dist * np.sin(folded_angle)).astype(int), 0, h-1)
    nx = np.clip((cx + dist * np.cos(folded_angle)).astype(int), 0, w-1)
    return c[ny, nx]
```

#### 镜像变体
```python
def sh_mirror_h(c):
    """Horizontal mirror — left half reflected to right."""
    w = c.shape[1]; c[:, w//2:] = c[:, :w//2][:, ::-1]; return c

def sh_mirror_v(c):
    """Vertical mirror — top half reflected to bottom."""
    h = c.shape[0]; c[h//2:, :] = c[:h//2, :][::-1, :]; return c

def sh_mirror_quad(c):
    """4-fold mirror — top-left quadrant reflected to all four."""
    h, w = c.shape[:2]; hh, hw = h//2, w//2
    tl = c[:hh, :hw].copy()
    c[:hh, hw:hw+tl.shape[1]] = tl[:, ::-1]
    c[hh:hh+tl.shape[0], :hw] = tl[::-1, :]
    c[hh:hh+tl.shape[0], hw:hw+tl.shape[1]] = tl[::-1, ::-1]
    return c

def sh_mirror_diag(c):
    """Diagonal mirror — top-left triangle reflected."""
    h, w = c.shape[:2]
    for y in range(h):
        x_cut = int(w * y / h)
        if x_cut > 0 and x_cut < w:
            c[y, x_cut:] = c[y, :x_cut+1][::-1][:w-x_cut]
    return c
```

> **注意：** 镜像 shader 会进行原地修改。分派函数传入 `canvas.copy()`，以免破坏原始数据。

---

### 通道操作 Shader

#### 色差
```python
def sh_chromatic(c, amt=3):
    """R/B channel horizontal shift. Beat-reactive in dispatch (amt scaled by bdecay)."""
    if amt < 1: return c
    a = int(amt)
    o = c.copy()
    o[:, a:, 0] = c[:, :-a, 0]   # red shifts right
    o[:, :-a, 2] = c[:, a:, 2]   # blue shifts left
    return o
```

#### 通道偏移
```python
def sh_channel_shift(c, r_shift=(0,0), g_shift=(0,0), b_shift=(0,0)):
    """Independent per-channel x,y shifting."""
    o = c.copy()
    for ch_i, (sx, sy) in enumerate([r_shift, g_shift, b_shift]):
        if sx != 0: o[:,:,ch_i] = np.roll(c[:,:,ch_i], sx, axis=1)
        if sy != 0: o[:,:,ch_i] = np.roll(o[:,:,ch_i], sy, axis=0)
    return o
```

#### 通道交换
```python
def sh_channel_swap(c, order=(2,1,0)):
    """Reorder RGB channels. (2,1,0)=BGR, (1,0,2)=GRB, etc."""
    return c[:, :, list(order)]
```

#### RGB 径向分离
```python
def sh_rgb_split_radial(c, strength=5):
    """Chromatic aberration radiating from center — stronger at edges."""
    h, w = c.shape[:2]; cy, cx = h//2, w//2
    Y = np.arange(h, dtype=np.float32)[:, None]
    X = np.arange(w, dtype=np.float32)[None, :]
    dist = np.sqrt((Y-cy)**2 + (X-cx)**2)
    max_dist = np.sqrt(cy**2 + cx**2)
    factor = dist / max_dist * strength
    dy = ((Y-cy) / (dist+1) * factor).astype(int)
    dx = ((X-cx) / (dist+1) * factor).astype(int)
    out = c.copy()
    ry = np.clip(Y.astype(int)+dy, 0, h-1); rx = np.clip(X.astype(int)+dx, 0, w-1)
    out[:,:,0] = c[ry, rx, 0]  # red shifts outward
    by = np.clip(Y.astype(int)-dy, 0, h-1); bx = np.clip(X.astype(int)-dx, 0, w-1)
    out[:,:,2] = c[by, bx, 2]  # blue shifts inward
    return out
```

---

### 色彩操作 Shader

#### 反相
```python
def sh_invert(c):
    return 255 - c
```

#### 色调分离
```python
def sh_posterize(c, levels=4):
    """Reduce color depth to N levels per channel."""
    step = 256.0 / levels
    return (np.floor(c.astype(np.float32) / step) * step).astype(np.uint8)
```

#### 阈值化
```python
def sh_threshold(c, thr=128):
    """Binary black/white at threshold."""
    gray = c.astype(np.float32).mean(axis=2)
    out = np.zeros_like(c); out[gray > thr] = 255
    return out
```

#### 日光化
```python
def sh_solarize(c, threshold=128):
    """Invert pixels above threshold — classic darkroom effect."""
    o = c.copy(); mask = c > threshold; o[mask] = 255 - c[mask]
    return o
```

#### 色相旋转
```python
def sh_hue_rotate(c, amount=0.1):
    """Rotate all hues by amount (0-1)."""
    h, s, v = rgb2hsv(c[:,:,0], c[:,:,1], c[:,:,2])
    h = (h + amount) % 1.0
    R, G, B = hsv2rgb(h, s, v)
    return mkc(R, G, B, c.shape[0], c.shape[1])
```

#### 饱和度
```python
def sh_saturation(c, factor=1.5):
    """Adjust saturation. >1=more saturated, <1=desaturated."""
    h, s, v = rgb2hsv(c[:,:,0], c[:,:,1], c[:,:,2])
    s = np.clip(s * factor, 0, 1)
    R, G, B = hsv2rgb(h, s, v)
    return mkc(R, G, B, c.shape[0], c.shape[1])
```

#### 色彩分级
```python
def sh_color_grade(c, tint):
    """Per-channel multiplier. tint=(r_mul, g_mul, b_mul)."""
    o = c.astype(np.float32)
    o[:,:,0] *= tint[0]; o[:,:,1] *= tint[1]; o[:,:,2] *= tint[2]
    return np.clip(o, 0, 255).astype(np.uint8)
```

#### 色彩波动
```python
def sh_color_wobble(c, t, amt=0.3):
    """Time-varying per-channel sine modulation. Audio-reactive in dispatch (amt scaled by rms)."""
    o = c.astype(np.float32)
    o[:,:,0] *= 1.0 + amt * math.sin(t * 5.0)
    o[:,:,1] *= 1.0 + amt * math.sin(t * 5.0 + 2.09)
    o[:,:,2] *= 1.0 + amt * math.sin(t * 5.0 + 4.19)
    return np.clip(o, 0, 255).astype(np.uint8)
```

#### 颜色渐变映射
```python
def sh_color_ramp(c, ramp_colors):
    """Map luminance to a custom color gradient.
    ramp_colors = list of (R,G,B) tuples, evenly spaced from dark to bright."""
    gray = c.astype(np.float32).mean(axis=2) / 255.0
    n = len(ramp_colors)
    idx = np.clip(gray * (n-1), 0, n-1.001)
    lo = np.floor(idx).astype(int); hi = np.minimum(lo+1, n-1)
    frac = idx - lo
    ramp = np.array(ramp_colors, dtype=np.float32)
    out = ramp[lo] * (1-frac[:,:,None]) + ramp[hi] * frac[:,:,None]
    return np.clip(out, 0, 255).astype(np.uint8)
```

---

### 辉光/模糊 Shader

#### Bloom
```python
def sh_bloom(c, thr=130):
    """Bright-area glow: 4x downsample, threshold, 3-pass box blur, screen blend."""
    sm = c[::4, ::4].astype(np.float32)
    br = np.where(sm > thr, sm, 0)
    for _ in range(3):
        p = np.pad(br, ((1,1),(1,1),(0,0)), mode="edge")
        br = (p[:-2,:-2]+p[:-2,1:-1]+p[:-2,2:]+p[1:-1,:-2]+p[1:-1,1:-1]+
              p[1:-1,2:]+p[2:,:-2]+p[2:,1:-1]+p[2:,2:]) / 9.0
    bl = np.repeat(np.repeat(br, 4, axis=0), 4, axis=1)[:c.shape[0], :c.shape[1]]
    return np.clip(c.astype(np.float32) + bl * 0.5, 0, 255).astype(np.uint8)
```

#### 边缘辉光
```python
def sh_edge_glow(c, hue=0.5):
    """Detect edges via gradient, add colored overlay."""
    gray = c.astype(np.float32).mean(axis=2)
    gx = np.abs(gray[:, 2:] - gray[:, :-2])
    gy = np.abs(gray[2:, :] - gray[:-2, :])
    ex = np.zeros_like(gray); ey = np.zeros_like(gray)
    ex[:, 1:-1] = gx; ey[1:-1, :] = gy
    edge = np.clip((ex + ey) / 255 * 2, 0, 1)
    R, G, B = hsv2rgb(np.full_like(edge, hue), np.full_like(edge, 0.8), edge * 0.5)
    out = c.astype(np.int16).copy()
    out[:,:,0] = np.clip(out[:,:,0] + R.astype(np.int16), 0, 255)
    out[:,:,1] = np.clip(out[:,:,1] + G.astype(np.int16), 0, 255)
    out[:,:,2] = np.clip(out[:,:,2] + B.astype(np.int16), 0, 255)
    return out.astype(np.uint8)
```

#### 柔焦
```python
def sh_soft_focus(c, strength=0.3):
    """Blend original with 2x-downsampled box blur."""
    sm = c[::2, ::2].astype(np.float32)
    p = np.pad(sm, ((1,1),(1,1),(0,0)), mode="edge")
    bl = (p[:-2,:-2]+p[:-2,1:-1]+p[:-2,2:]+p[1:-1,:-2]+p[1:-1,1:-1]+
          p[1:-1,2:]+p[2:,:-2]+p[2:,1:-1]+p[2:,2:]) / 9.0
    bl = np.repeat(np.repeat(bl, 2, axis=0), 2, axis=1)[:c.shape[0], :c.shape[1]]
    return np.clip(c * (1-strength) + bl * strength, 0, 255).astype(np.uint8)
```

#### 径向模糊
```python
def sh_radial_blur(c, strength=0.03, center=None):
    """Zoom blur from center — motion blur radiating outward."""
    h, w = c.shape[:2]
    cy, cx = center if center else (h//2, w//2)
    Y = np.arange(h, dtype=np.float32)[:, None]
    X = np.arange(w, dtype=np.float32)[None, :]
    out = c.astype(np.float32)
    for s in [strength, strength*2]:
        dy = (Y - cy) * s; dx = (X - cx) * s
        sy = np.clip((Y + dy).astype(int), 0, h-1)
        sx = np.clip((X + dx).astype(int), 0, w-1)
        out += c[sy, sx].astype(np.float32)
    return np.clip(out / 3, 0, 255).astype(np.uint8)
```

---

### 噪声/颗粒 Shader

#### 胶片颗粒
```python
def sh_grain(c, amt=10):
    """2x-downsampled film grain. Audio-reactive in dispatch (amt scaled by rms)."""
    noise = np.random.randint(-amt, amt+1, (c.shape[0]//2, c.shape[1]//2, 1), dtype=np.int16)
    noise = np.repeat(np.repeat(noise, 2, axis=0), 2, axis=1)[:c.shape[0], :c.shape[1]]
    return np.clip(c.astype(np.int16) + noise, 0, 255).astype(np.uint8)
```

#### 静态噪声
```python
def sh_static_noise(c, density=0.05, color=True):
    """Random pixel noise overlay (TV static)."""
    mask = np.random.random((c.shape[0]//2, c.shape[1]//2)) < density
    mask = np.repeat(np.repeat(mask, 2, axis=0), 2, axis=1)[:c.shape[0], :c.shape[1]]
    out = c.copy()
    if color:
        noise = np.random.randint(0, 256, (c.shape[0], c.shape[1], 3), dtype=np.uint8)
    else:
        v = np.random.randint(0, 256, (c.shape[0], c.shape[1]), dtype=np.uint8)
        noise = np.stack([v, v, v], axis=2)
    out[mask] = noise[mask]
    return out
```

---

### 线条/图案 Shader

#### 扫描线
```python
def sh_scanlines(c, intensity=0.08, spacing=3):
    """Darken every Nth row."""
    m = np.ones(c.shape[0], dtype=np.float32)
    m[::spacing] = 1.0 - intensity
    return np.clip(c * m[:, None, None], 0, 255).astype(np.uint8)
```

#### 半色调
```python
def sh_halftone(c, dot_size=6):
    """Halftone dot pattern overlay — circular dots sized by local brightness."""
    h, w = c.shape[:2]
    gray = c.astype(np.float32).mean(axis=2) / 255.0
    out = np.zeros_like(c)
    for y in range(0, h, dot_size):
        for x in range(0, w, dot_size):
            block = gray[y:y+dot_size, x:x+dot_size]
            if block.size == 0: continue
            radius = block.mean() * dot_size * 0.5
            cy_b, cx_b = dot_size//2, dot_size//2
            for dy in range(min(dot_size, h-y)):
                for dx in range(min(dot_size, w-x)):
                    if math.sqrt((dy-cy_b)**2 + (dx-cx_b)**2) < radius:
                        out[y+dy, x+dx] = c[y+dy, x+dx]
    return out
```

> **性能说明：** 由于使用 Python 循环，半色调处理速度较慢。对于低分辨率或单张测试帧尚可接受。生产环境中，建议考虑使用预计算距离掩码的向量化版本。

---

### 色调 Shader

#### 暗角
```python
_vig_cache = {}
def sh_vignette(c, s=0.22):
    """Edge darkening using cached distance field."""
    k = (c.shape[0], c.shape[1], round(s, 2))
    if k not in _vig_cache:
        h, w = c.shape[:2]
        Y = np.linspace(-1, 1, h)[:, None]; X = np.linspace(-1, 1, w)[None, :]
        _vig_cache[k] = np.clip(1.0 - np.sqrt(X**2 + Y**2) * s, 0.15, 1).astype(np.float32)
    return np.clip(c * _vig_cache[k][:,:,None], 0, 255).astype(np.uint8)
```

#### 反向暗角

反向暗角：压暗**中心**，同时保持边缘明亮。适合在繁杂背景中央放置文本时使用——无需边缘生硬的方框，就能形成自然的暗区以提高可读性。

可与 `apply_text_backdrop()`（参见 composition.md）结合使用，逐帧进行字形感知的压暗。

```python
_rvignette_cache = {}

def sh_reverse_vignette(c, strength=0.5):
    """Center darkening, edge brightening. Cached."""
    k = ('rv', c.shape[0], c.shape[1], round(strength, 2))
    if k not in _rvignette_cache:
        h, w = c.shape[:2]
        Y = np.linspace(-1, 1, h)[:, None]
        X = np.linspace(-1, 1, w)[None, :]
        d = np.sqrt(X**2 + Y**2)
        # Invert: bright at edges, dark at center
        mask = np.clip(1.0 - (1.0 - d * 0.7) * strength, 0.2, 1.0)
        _rvignette_cache[k] = mask[:, :, np.newaxis].astype(np.float32)
    return np.clip(c.astype(np.float32) * _rvignette_cache[k], 0, 255).astype(np.uint8)
```

| 参数 | 默认值 | 效果 |
|-------|---------|--------|
| `strength` | 0.5 | 0 = 无效果，1.0 = 中心近乎全黑 |

添加到 ShaderChain 分派函数：
```python
elif name == "reverse_vignette":
    return sh_reverse_vignette(canvas, kwargs.get("strength", 0.5))
```

#### 对比度
```python
def sh_contrast(c, factor=1.3):
    """Adjust contrast around midpoint 128."""
    return np.clip((c.astype(np.float32) - 128) * factor + 128, 0, 255).astype(np.uint8)
```

#### Gamma
```python
def sh_gamma(c, gamma=1.5):
    """Gamma correction. >1=brighter mids, <1=darker mids."""
    return np.clip(((c.astype(np.float32)/255.0) ** (1.0/gamma)) * 255, 0, 255).astype(np.uint8)
```

#### 色阶
```python
def sh_levels(c, black=0, white=255, midtone=1.0):
    """Levels adjustment (Photoshop-style). Remap black/white points, apply midtone gamma."""
    o = (c.astype(np.float32) - black) / max(1, white - black)
    o = np.clip(o, 0, 1) ** (1.0 / midtone)
    return (o * 255).astype(np.uint8)
```

#### 亮度
```python
def sh_brightness(c, factor=1.5):
    """Global brightness multiplier. Prefer tonemap() for scene-level brightness control."""
    return np.clip(c.astype(np.float32) * factor, 0, 255).astype(np.uint8)
```

---

### 故障/数据 Shader

#### 故障条带
```python
def sh_glitch_bands(c, f):
    """Beat-reactive horizontal row displacement. f = audio features dict.
    Uses f["bdecay"] for intensity and f["sub"] for band height."""
    n = int(3 + f.get("bdecay", 0) * 10)
    out = c.copy()
    for _ in range(n):
        y = random.randint(0, c.shape[0]-1)
        h = random.randint(1, max(2, int(4 + f.get("sub", 0.3) * 12)))
        shift = int((random.random()-0.5) * f.get("bdecay", 0) * 60)
        if shift != 0 and y+h < c.shape[0]:
            out[y:y+h] = np.roll(out[y:y+h], shift, axis=1)
    return out
```

#### 块状故障
```python
def sh_block_glitch(c, n_blocks=8, max_size=40):
    """Random rectangular block displacement — copy blocks to random positions."""
    out = c.copy(); h, w = c.shape[:2]
    for _ in range(n_blocks):
        bw = random.randint(10, max_size); bh = random.randint(5, max_size//2)
        sx = random.randint(0, w-bw-1); sy = random.randint(0, h-bh-1)
        dx = random.randint(0, w-bw-1); dy = random.randint(0, h-bh-1)
        out[dy:dy+bh, dx:dx+bw] = c[sy:sy+bh, sx:sx+bw]
    return out
```

#### 像素排序
```python
def sh_pixel_sort(c, threshold=100, direction="h"):
    """Sort pixels by brightness in contiguous bright regions."""
    gray = c.astype(np.float32).mean(axis=2)
    out = c.copy()
    if direction == "h":
        for y in range(0, c.shape[0], 3):  # every 3rd row for speed
            row_bright = gray[y]
            mask = row_bright > threshold
            regions = np.diff(np.concatenate([[0], mask.astype(int), [0]]))
            starts = np.where(regions == 1)[0]
            ends = np.where(regions == -1)[0]
            for s, e in zip(starts, ends):
                if e - s > 2:
                    indices = np.argsort(gray[y, s:e])
                    out[y, s:e] = c[y, s:e][indices]
    else:
        for x in range(0, c.shape[1], 3):
            col_bright = gray[:, x]
            mask = col_bright > threshold
            regions = np.diff(np.concatenate([[0], mask.astype(int), [0]]))
            starts = np.where(regions == 1)[0]
            ends = np.where(regions == -1)[0]
            for s, e in zip(starts, ends):
                if e - s > 2:
                    indices = np.argsort(gray[s:e, x])
                    out[s:e, x] = c[s:e, x][indices]
    return out
```

#### 数据弯曲
```python
def sh_data_bend(c, offset=1000, chunk=500):
    """Treat raw pixel bytes as data, copy a chunk to another offset — datamosh artifacts."""
    flat = c.flatten().copy()
    n = len(flat)
    src = offset % n; dst = (offset + chunk*3) % n
    length = min(chunk, n-src, n-dst)
    if length > 0:
        flat[dst:dst+length] = flat[src:src+length]
    return flat.reshape(c.shape)
```

---

## 色调预设

```python
TINT_WARM      = (1.15, 1.0, 0.85)   # golden warmth
TINT_COOL      = (0.85, 0.95, 1.15)  # blue cool
TINT_MATRIX    = (0.7, 1.2, 0.7)     # green terminal
TINT_AMBER     = (1.2, 0.9, 0.6)     # amber monitor
TINT_SEPIA     = (1.2, 1.05, 0.8)    # old film
TINT_NEON_PINK = (1.3, 0.7, 1.1)     # cyberpunk pink
TINT_ICE       = (0.8, 1.0, 1.3)     # frozen
TINT_BLOOD     = (1.4, 0.7, 0.7)     # horror red
TINT_FOREST    = (0.8, 1.15, 0.75)   # natural green
TINT_VOID      = (0.85, 0.85, 1.1)   # deep space
TINT_SUNSET    = (1.3, 0.85, 0.7)    # orange dusk
```

---

## 转场

> **注意：** 这些转场作用于字符级 `(chars, colors)` 数组（v1 接口）。在 v2 中，场景之间的转场通常通过节拍边界处的硬切来处理（参见 `scenes.md`），或者将两个场景都渲染到画布，再使用透明度随时间变化的 `blend_canvas()`。下述字符级转场对场景内效果仍然有用。

### 交叉淡化
```python
def tr_crossfade(ch_a, co_a, ch_b, co_b, blend):
    co = (co_a.astype(np.float32) * (1-blend) + co_b.astype(np.float32) * blend).astype(np.uint8)
    mask = np.random.random(ch_a.shape) < blend
    ch = ch_a.copy(); ch[mask] = ch_b[mask]
    return ch, co
```

### v2 画布级交叉淡化
```python
def tr_canvas_crossfade(canvas_a, canvas_b, blend):
    """Smooth pixel crossfade between two canvases."""
    return np.clip(canvas_a * (1-blend) + canvas_b * blend, 0, 255).astype(np.uint8)
```

### 擦除（定向）
```python
def tr_wipe(ch_a, co_a, ch_b, co_b, blend, direction="left"):
    """direction: left, right, up, down, radial, diagonal"""
    rows, cols = ch_a.shape
    if direction == "radial":
        cx, cy = cols/2, rows/2
        rr = np.arange(rows)[:, None]; cc = np.arange(cols)[None, :]
        d = np.sqrt((cc-cx)**2 + (rr-cy)**2)
        mask = d < blend * np.sqrt(cx**2 + cy**2)
        ch = ch_a.copy(); co = co_a.copy()
        ch[mask] = ch_b[mask]; co[mask] = co_b[mask]
    return ch, co
```

### 故障切换
```python
def tr_glitch_cut(ch_a, co_a, ch_b, co_b, blend):
    if blend < 0.5: ch, co = ch_a.copy(), co_a.copy()
    else: ch, co = ch_b.copy(), co_b.copy()
    if 0.3 < blend < 0.7:
        intensity = 1.0 - abs(blend - 0.5) * 4
        for _ in range(int(intensity * 20)):
            y = random.randint(0, ch.shape[0]-1)
            shift = int((random.random()-0.5) * 40 * intensity)
            if shift: ch[y] = np.roll(ch[y], shift); co[y] = np.roll(co[y], shift, axis=0)
    return ch, co
```

---

## 输出格式

### MP4（默认）
```python
cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
       "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0",
       "-c:v", "libx264", "-preset", "fast", "-crf", str(crf),
       "-pix_fmt", "yuv420p", output_path]
```

### GIF
```python
cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
       "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0",
       "-vf", f"fps={fps},scale={W}:{H}:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
       "-loop", "0", output_gif]
```

### PNG 序列

用于逐帧精确编辑、在外部工具（After Effects、Nuke）中合成，或无损归档：

```python
import os

def output_png_sequence(frames, output_dir, W, H, fps, prefix="frame"):
    """Write frames as numbered PNGs. frames = iterable of uint8 (H,W,3) arrays."""
    os.makedirs(output_dir, exist_ok=True)
    
    # Method 1: Direct PIL write (no ffmpeg dependency)
    from PIL import Image
    for i, frame in enumerate(frames):
        img = Image.fromarray(frame)
        img.save(os.path.join(output_dir, f"{prefix}_{i:06d}.png"))
    
    # Method 2: ffmpeg pipe (faster for large sequences)
    cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0",
           os.path.join(output_dir, f"{prefix}_%06d.png")]
```

将 PNG 序列重新组装为视频：
```bash
ffmpeg -framerate 24 -i frame_%06d.png -c:v libx264 -crf 18 -pix_fmt yuv420p output.mp4
```

### Alpha 通道/透明背景（RGBA）

用于将 ASCII 艺术合成到其他视频或图像之上。使用 RGBA 画布（4 个通道），而不是 RGB（3 个通道）：

```python
def create_rgba_canvas(H, W):
    """Transparent canvas — alpha channel starts at 0 (fully transparent)."""
    return np.zeros((H, W, 4), dtype=np.uint8)

def render_char_rgba(canvas, row, col, char_img, color_rgb, alpha=255):
    """Render a character with alpha. char_img = PIL glyph mask (grayscale).
    Alpha comes from the glyph mask — background stays transparent."""
    r, g, b = color_rgb
    y0, x0 = row * cell_h, col * cell_w
    mask = np.array(char_img)  # grayscale 0-255
    canvas[y0:y0+cell_h, x0:x0+cell_w, 0] = np.maximum(canvas[y0:y0+cell_h, x0:x0+cell_w, 0], (mask * r / 255).astype(np.uint8))
    canvas[y0:y0+cell_h, x0:x0+cell_w, 1] = np.maximum(canvas[y0:y0+cell_h, x0:x0+cell_w, 1], (mask * g / 255).astype(np.uint8))
    canvas[y0:y0+cell_h, x0:x0+cell_w, 2] = np.maximum(canvas[y0:y0+cell_h, x0:x0+cell_w, 2], (mask * b / 255).astype(np.uint8))
    canvas[y0:y0+cell_h, x0:x0+cell_w, 3] = np.maximum(canvas[y0:y0+cell_h, x0:x0+cell_w, 3], mask)

def blend_onto_background(rgba_canvas, bg_rgb):
    """Composite RGBA canvas over a solid or image background."""
    alpha = rgba_canvas[:, :, 3:4].astype(np.float32) / 255.0
    fg = rgba_canvas[:, :, :3].astype(np.float32)
    bg = bg_rgb.astype(np.float32)
    result = fg * alpha + bg * (1.0 - alpha)
    return result.astype(np.uint8)
```

通过 ffmpeg 输出 RGBA（用于编辑的 ProRes 4444，以及用于 Web 的 WebM VP9）：
```bash
# ProRes 4444 — preserves alpha, widely supported in NLEs
ffmpeg -y -f rawvideo -pix_fmt rgba -s {W}x{H} -r {fps} -i pipe:0 \
    -c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le output.mov

# WebM VP9 — alpha support for web/browser compositing
ffmpeg -y -f rawvideo -pix_fmt rgba -s {W}x{H} -r {fps} -i pipe:0 \
    -c:v libvpx-vp9 -pix_fmt yuva420p -crf 30 -b:v 0 output.webm

# PNG sequence with alpha (lossless)
ffmpeg -y -f rawvideo -pix_fmt rgba -s {W}x{H} -r {fps} -i pipe:0 \
    frame_%06d.png
```

**关键限制**：作用于 `(H,W,3)` 数组的 shader 需要适配 RGBA。可以只将 shader 应用于 RGB 通道并保留 alpha，也可以编写支持 RGBA 的版本：

```python
def apply_shader_rgba(canvas_rgba, shader_fn, **kwargs):
    """Apply an RGB shader to the color channels of an RGBA canvas."""
    rgb = canvas_rgba[:, :, :3]
    alpha = canvas_rgba[:, :, 3:4]
    rgb_out = shader_fn(rgb, **kwargs)
    return np.concatenate([rgb_out, alpha], axis=2)
```

---

## 实时终端渲染

使用 ANSI 转义码在终端中实时显示 ASCII。适用于开发期间预览场景、现场演出和交互式参数调节。

### ANSI 颜色转义码

```python
def rgb_to_ansi(r, g, b):
    """24-bit true color ANSI escape (supported by most modern terminals)."""
    return f"\033[38;2;{r};{g};{b}m"

ANSI_RESET = "\033[0m"
ANSI_CLEAR = "\033[2J\033[H"  # clear screen + cursor home
ANSI_HIDE_CURSOR = "\033[?25l"
ANSI_SHOW_CURSOR = "\033[?25h"
```

### 帧到 ANSI 的转换

```python
def frame_to_ansi(chars, colors):
    """Convert char+color arrays to a single ANSI string for terminal output.
    
    Args:
        chars: (rows, cols) array of single characters
        colors: (rows, cols, 3) uint8 RGB array
    Returns:
        str: ANSI-encoded frame ready for sys.stdout.write()
    """
    rows, cols = chars.shape
    lines = []
    for r in range(rows):
        parts = []
        prev_color = None
        for c in range(cols):
            rgb = tuple(colors[r, c])
            ch = chars[r, c]
            if ch == " " or rgb == (0, 0, 0):
                parts.append(" ")
            else:
                if rgb != prev_color:
                    parts.append(rgb_to_ansi(*rgb))
                    prev_color = rgb
                parts.append(ch)
        parts.append(ANSI_RESET)
        lines.append("".join(parts))
    return "\n".join(lines)
```

### 优化：增量更新

仅重绘相较上一帧发生变化的字符。这样可避免对静态区域进行多余的终端写入：

```python
def frame_to_ansi_delta(chars, colors, prev_chars, prev_colors):
    """Emit ANSI escapes only for cells that changed."""
    rows, cols = chars.shape
    parts = []
    for r in range(rows):
        for c in range(cols):
            if (chars[r, c] != prev_chars[r, c] or
                not np.array_equal(colors[r, c], prev_colors[r, c])):
                parts.append(f"\033[{r+1};{c+1}H")  # move cursor
                rgb = tuple(colors[r, c])
                parts.append(rgb_to_ansi(*rgb))
                parts.append(chars[r, c])
    return "".join(parts)
```

### 实时渲染循环

```python
import sys
import time

def render_live(scene_fn, r, fps=24, duration=None):
    """Render a scene function live in the terminal.
    
    Args:
        scene_fn: v2 scene function (r, f, t, S) -> canvas
                  OR v1-style function that populates a grid
        r: Renderer instance
        fps: target frame rate
        duration: seconds to run (None = run until Ctrl+C)
    """
    frame_time = 1.0 / fps
    S = {}
    f = {}  # synthesize features or connect to live audio
    
    sys.stdout.write(ANSI_HIDE_CURSOR + ANSI_CLEAR)
    sys.stdout.flush()
    
    t0 = time.monotonic()
    frame_count = 0
    try:
        while True:
            t = time.monotonic() - t0
            if duration and t > duration:
                break
            
            # Synthesize features from time (or connect to live audio via pyaudio)
            f = synthesize_features(t)
            
            # Render scene — for terminal, use a small grid
            g = r.get_grid("sm")
            # Option A: v2 scene → extract chars/colors from canvas (reverse render)
            # Option B: call effect functions directly for chars/colors
            canvas = scene_fn(r, f, t, S)
            
            # For terminal display, render chars+colors directly
            # (bypassing the pixel canvas — terminal uses character cells)
            chars, colors = scene_to_terminal(scene_fn, r, f, t, S, g)
            
            frame_str = ANSI_CLEAR + frame_to_ansi(chars, colors)
            sys.stdout.write(frame_str)
            sys.stdout.flush()
            
            # Frame timing
            elapsed = time.monotonic() - t0 - (frame_count * frame_time)
            sleep_time = frame_time - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
            frame_count += 1
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write(ANSI_SHOW_CURSOR + ANSI_RESET + "\n")
        sys.stdout.flush()

def scene_to_terminal(scene_fn, r, f, t, S, g):
    """Run effect functions and return (chars, colors) for terminal display.
    For terminal mode, skip the pixel canvas and work with character arrays directly."""
    # Effects that return (chars, colors) work directly
    # For vf-based effects, render the value field + hue field to chars/colors:
    val = vf_plasma(g, f, t, S)
    hue = hf_time_cycle(0.08)(g, t)
    mask = val > 0.03
    chars = val2char(val, mask, PAL_DENSE)
    R, G, B = hsv2rgb(hue, np.full_like(val, 0.8), val)
    colors = mkc(R, G, B, g.rows, g.cols)
    return chars, colors
```

### 基于 Curses 的渲染（更稳健）

用于需要妥善处理尺寸调整和输入的全功能终端 UI：

```python
import curses

def render_curses(scene_fn, r, fps=24):
    """Curses-based live renderer with resize handling and key input."""
    
    def _main(stdscr):
        curses.start_color()
        curses.use_default_colors()
        curses.curs_set(0)  # hide cursor
        stdscr.nodelay(True)  # non-blocking input
        
        # Initialize color pairs (curses supports 256 colors)
        # Map RGB to nearest curses color pair
        color_cache = {}
        next_pair = [1]
        
        def get_color_pair(r, g, b):
            key = (r >> 4, g >> 4, b >> 4)  # quantize to reduce pairs
            if key not in color_cache:
                if next_pair[0] < curses.COLOR_PAIRS - 1:
                    ci = 16 + (r // 51) * 36 + (g // 51) * 6 + (b // 51)  # 6x6x6 cube
                    curses.init_pair(next_pair[0], ci, -1)
                    color_cache[key] = next_pair[0]
                    next_pair[0] += 1
                else:
                    return 0
            return curses.color_pair(color_cache[key])
        
        S = {}
        f = {}
        frame_time = 1.0 / fps
        t0 = time.monotonic()
        
        while True:
            t = time.monotonic() - t0
            f = synthesize_features(t)
            
            # Adapt grid to terminal size
            max_y, max_x = stdscr.getmaxyx()
            g = r.get_grid_for_size(max_x, max_y)  # dynamic grid sizing
            
            chars, colors = scene_to_terminal(scene_fn, r, f, t, S, g)
            rows, cols = chars.shape
            
            for row in range(min(rows, max_y - 1)):
                for col in range(min(cols, max_x - 1)):
                    ch = chars[row, col]
                    rgb = tuple(colors[row, col])
                    try:
                        stdscr.addch(row, col, ch, get_color_pair(*rgb))
                    except curses.error:
                        pass  # ignore writes outside terminal bounds
            
            stdscr.refresh()
            
            # Handle input
            key = stdscr.getch()
            if key == ord('q'):
                break
            
            time.sleep(max(0, frame_time - (time.monotonic() - t0 - t)))
    
    curses.wrapper(_main)
```

### 终端渲染限制

| 限制 | 数值 | 说明 |
|-----------|-------|-------|
| 最大实用网格 | ~200x60 | 取决于终端尺寸 |
| 色彩支持 | 24 位（现代）、256 色（回退）、16 色（最低） | 检查 `$COLORTERM` 是否支持真彩色 |
| 帧率上限 | ~30 fps | 瓶颈在终端 I/O |
| 增量更新 | 快 2-5 倍 | 仅当每帧变化的单元格少于 30% 时才值得使用 |
| SSH 延迟 | 会严重影响性能 | 实时渲染仅适合本地终端 |

**检测色彩支持：**
```python
import os
def get_terminal_color_depth():
    ct = os.environ.get("COLORTERM", "")
    if ct in ("truecolor", "24bit"):
        return 24
    term = os.environ.get("TERM", "")
    if "256color" in term:
        return 8  # 256 colors
    return 4  # 16 colors basic ANSI
```
