# 架构参考

> **另请参阅：** composition.md · effects.md · scenes.md · shaders.md · inputs.md · optimization.md · troubleshooting.md

## 网格系统

### 分辨率预设

```python
RESOLUTION_PRESETS = {
    "landscape":  (1920, 1080),  # 16:9 — YouTube, default
    "portrait":   (1080, 1920),  # 9:16 — TikTok, Reels, Stories
    "square":     (1080, 1080),  # 1:1  — Instagram feed
    "ultrawide":  (2560, 1080),  # 21:9 — cinematic
    "landscape4k":(3840, 2160),  # 16:9 — 4K
    "portrait4k": (2160, 3840),  # 9:16 — 4K portrait
}

def get_resolution(preset="landscape", custom=None):
    """Returns (VW, VH) tuple."""
    if custom:
        return custom
    return RESOLUTION_PRESETS.get(preset, RESOLUTION_PRESETS["landscape"])
```

### 多密度网格

预先初始化多种网格尺寸。逐区段切换以丰富视觉变化。网格尺寸根据分辨率自动计算：

**横屏（1920x1080）：**

| 键 | 字号 | 网格（列 x 行） | 用途 |
|-----|-----------|-------------------|-----|
| xs | 8 | 400x108 | 超密集数据场 |
| sm | 10 | 320x83 | 密集细节、雨、星空 |
| md | 16 | 192x56 | 默认均衡、转场 |
| lg | 20 | 160x45 | 引语/歌词文本（在 1080p 下清晰可读） |
| xl | 24 | 137x37 | 短引语、大标题 |
| xxl | 40 | 80x22 | 巨型文本、极简画面 |

**竖屏（1080x1920）：**

| 键 | 字号 | 网格（列 x 行） | 用途 |
|-----|-----------|-------------------|-----|
| xs | 8 | 225x192 | 超密集、高耸的数据列 |
| sm | 10 | 180x148 | 密集细节、垂直雨幕 |
| md | 16 | 112x100 | 默认均衡 |
| lg | 20 | 90x80 | 可读文本（每行约 30 个字符，居中） |
| xl | 24 | 75x66 | 短引语、堆叠排布 |
| xxl | 40 | 45x39 | 巨型文本、极简画面 |

**方形（1080x1080）：**

| 键 | 字号 | 网格（列 x 行） | 用途 |
|-----|-----------|-------------------|-----|
| sm | 10 | 180x83 | 密集细节 |
| md | 16 | 112x56 | 默认均衡 |
| lg | 20 | 90x45 | 可读文本 |

**竖屏模式的主要差异：**
- 列数更少（`lg` 下为 90，而非 160）——每行必须更短或进行换行
- 行数多得多（`lg` 下为 80，而非 45）——垂直堆叠非常自然
- 宽高比校正发生翻转：`asp = cw / ch` 仍然有效，但视觉重点转为垂直方向
- 径向效果若不校正，会呈现为高而窄的椭圆
- 垂直效果（雨、余烬、火柱）会自然得到增强
- 水平效果（频谱条、波形）需要旋转或压缩

**竖屏文本的网格尺寸**：2-3 个单词一行时使用 `lg`（20px）。舒适的最大行长约为 25-30 个字符。对于较长引语，应果断拆分成许多垂直堆叠的短行——竖屏有充足的垂直空间。`xl`（24px）适合单个单词或极短短语。

网格尺寸：`cols = VW // cell_width`、`rows = VH // cell_height`。

### 字体选择

不要硬编码单一字体。应选择符合项目氛围的字体。网格对齐要求使用等宽字体，但不同字体的个性差异很大：

| 字体 | 风格特征 | 平台 |
|------|-------------|----------|
| Menlo | 简洁、中性、Apple 原生 | macOS |
| Monaco | 复古终端风、紧凑 | macOS |
| Courier New | 经典打字机风、宽字形 | 跨平台 |
| SF Mono | 现代、字距紧凑 | macOS |
| Consolas | Windows 原生、简洁 | Windows |
| JetBrains Mono | 开发者风格、支持连字 | 需安装 |
| Fira Code | 几何感、现代 | 需安装 |
| IBM Plex Mono | 商务、权威 | 需安装 |
| Source Code Pro | Adobe 出品、均衡 | 需安装 |

**初始化时检测字体**：探测可用字体，并妥善回退：

```python
import platform

def find_font(preferences):
    """Try fonts in order, return first that exists."""
    for name, path in preferences:
        if os.path.exists(path):
            return path
    raise FileNotFoundError(f"No monospace font found. Tried: {[p for _,p in preferences]}")

FONT_PREFS_MACOS = [
    ("Menlo", "/System/Library/Fonts/Menlo.ttc"),
    ("Monaco", "/System/Library/Fonts/Monaco.ttf"),
    ("SF Mono", "/System/Library/Fonts/SFNSMono.ttf"),
    ("Courier", "/System/Library/Fonts/Courier.ttc"),
]
FONT_PREFS_LINUX = [
    ("DejaVu Sans Mono", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
    ("Liberation Mono", "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"),
    ("Noto Sans Mono", "/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf"),
    ("Ubuntu Mono", "/usr/share/fonts/truetype/ubuntu/UbuntuMono-R.ttf"),
]
FONT_PREFS_WINDOWS = [
    ("Consolas", r"C:\Windows\Fonts\consola.ttf"),
    ("Courier New", r"C:\Windows\Fonts\cour.ttf"),
    ("Lucida Console", r"C:\Windows\Fonts\lucon.ttf"),
    ("Cascadia Code", os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts\CascadiaCode.ttf")),
    ("Cascadia Mono", os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts\CascadiaMono.ttf")),
]

def _get_font_prefs():
    s = platform.system()
    if s == "Darwin":
        return FONT_PREFS_MACOS
    elif s == "Windows":
        return FONT_PREFS_WINDOWS
    return FONT_PREFS_LINUX

FONT_PREFS = _get_font_prefs()
```

**多字体渲染**：为不同图层使用不同字体（例如背景使用等宽字体，叠加文本使用更粗的变体）。每个 GridLayer 都拥有自己的字体：

```python
grid_bg = GridLayer(find_font(FONT_PREFS), 16)       # background
grid_text = GridLayer(find_font(BOLD_PREFS), 20)      # readable text
```

### 收集所有字符

初始化网格前，收集所有需要预先栅格化为位图的字符：

```python
all_chars = set()
for pal in [PAL_DEFAULT, PAL_DENSE, PAL_BLOCKS, PAL_RUNE, PAL_KATA,
            PAL_GREEK, PAL_MATH, PAL_DOTS, PAL_BRAILLE, PAL_STARS,
            PAL_HALFFILL, PAL_HATCH, PAL_BINARY, PAL_MUSIC, PAL_BOX,
            PAL_CIRCUIT, PAL_ARROWS, PAL_HERMES]:  # ... all palettes used in project
    all_chars.update(pal)
# Add any overlay text characters
all_chars.update("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .,-:;!?/|")
all_chars.discard(" ")  # space is never rendered
```

### GridLayer 初始化

每个网格都会预先计算坐标数组，以便对效果进行向量化计算。网格会自动适配任何分辨率（横屏、竖屏、方形）：

```python
class GridLayer:
    def __init__(self, font_path, font_size, vw=None, vh=None):
        """Initialize grid for any resolution.
        vw, vh: video width/height in pixels. Defaults to global VW, VH."""
        vw = vw or VW; vh = vh or VH
        self.vw = vw; self.vh = vh

        self.font = ImageFont.truetype(font_path, font_size)
        asc, desc = self.font.getmetrics()
        bbox = self.font.getbbox("M")
        self.cw = bbox[2] - bbox[0]  # character cell width
        self.ch = asc + desc  # CRITICAL: not textbbox height

        self.cols = vw // self.cw
        self.rows = vh // self.ch
        self.ox = (vw - self.cols * self.cw) // 2  # centering
        self.oy = (vh - self.rows * self.ch) // 2

        # Aspect ratio metadata
        self.aspect = vw / vh  # >1 = landscape, <1 = portrait, 1 = square
        self.is_portrait = vw < vh
        self.is_landscape = vw > vh

        # Index arrays
        self.rr = np.arange(self.rows, dtype=np.float32)[:, None]
        self.cc = np.arange(self.cols, dtype=np.float32)[None, :]

        # Polar coordinates (aspect-corrected)
        cx, cy = self.cols / 2.0, self.rows / 2.0
        asp = self.cw / self.ch
        self.dx = self.cc - cx
        self.dy = (self.rr - cy) * asp
        self.dist = np.sqrt(self.dx**2 + self.dy**2)
        self.angle = np.arctan2(self.dy, self.dx)

        # Normalized (0-1 range) -- for distance falloff
        self.dx_n = (self.cc - cx) / max(self.cols, 1)
        self.dy_n = (self.rr - cy) / max(self.rows, 1) * asp
        self.dist_n = np.sqrt(self.dx_n**2 + self.dy_n**2)

        # Pre-rasterize all characters to float32 bitmaps
        self.bm = {}
        for c in all_chars:
            img = Image.new("L", (self.cw, self.ch), 0)
            ImageDraw.Draw(img).text((0, 0), c, fill=255, font=self.font)
            self.bm[c] = np.array(img, dtype=np.float32) / 255.0
```

### 字符渲染循环

这是性能瓶颈。它把预先栅格化的位图合成到像素画布上：

```python
def render(self, chars, colors, canvas=None):
    if canvas is None:
        canvas = np.zeros((VH, VW, 3), dtype=np.uint8)
    for row in range(self.rows):
        y = self.oy + row * self.ch
        if y + self.ch > VH: break
        for col in range(self.cols):
            c = chars[row, col]
            if c == " ": continue
            x = self.ox + col * self.cw
            if x + self.cw > VW: break
            a = self.bm[c]  # float32 bitmap
            canvas[y:y+self.ch, x:x+self.cw] = np.maximum(
                canvas[y:y+self.ch, x:x+self.cw],
                (a[:, :, None] * colors[row, col]).astype(np.uint8))
    return canvas
```

使用 `np.maximum` 进行加法混合（较亮字符会覆盖较暗字符，绝不会使画面变暗）。

### 多图层渲染

将多个网格渲染到同一画布上，以营造纵深：

```python
canvas = np.zeros((VH, VW, 3), dtype=np.uint8)
canvas = grid_lg.render(bg_chars, bg_colors, canvas)   # background layer
canvas = grid_md.render(main_chars, main_colors, canvas)  # main layer
canvas = grid_sm.render(detail_chars, detail_colors, canvas)  # detail overlay
```

---

## 字符调色板

### 设计原则

字符调色板是 ASCII 视频的主要视觉纹理。它不仅控制亮度映射，还决定整体视觉感受。应有意识地设计调色板：

- **视觉权重**：按字符填充的墨迹/像素量排序。空格始终位于索引 0。
- **一致性**：同一调色板中的字符应属于同一个视觉家族。
- **密度曲线**：亮度到字符的映射是非线性的。密集调色板（字符多）可产生更平滑的渐变；稀疏调色板（5-8 个字符）可产生色调分离式/图形化外观。
- **渲染兼容性**：调色板中的每个字符都必须存在于字体中。初始化时进行测试，并移除缺失的字形。

### 调色板库

按视觉家族组织。根据项目自由组合——不要所有内容都默认使用 PAL_DEFAULT。

#### 密度/亮度调色板
```python
PAL_DEFAULT  = " .`'-:;!><=+*^~?/|(){}[]#&$@%"       # classic ASCII art
PAL_DENSE    = " .:;+=xX$#@\u2588"                          # simple 11-level ramp
PAL_MINIMAL  = " .:-=+#@"                               # 8-level, graphic
PAL_BINARY   = " \u2588"                                      # 2-level, extreme contrast
PAL_GRADIENT = " \u2591\u2592\u2593\u2588"                              # 4-level block gradient
```

#### Unicode 块元素
```python
PAL_BLOCKS   = " \u2591\u2592\u2593\u2588\u2584\u2580\u2590\u258c"                 # standard blocks
PAL_BLOCKS_EXT = " \u2596\u2597\u2598\u2599\u259a\u259b\u259c\u259d\u259e\u259f\u2591\u2592\u2593\u2588"  # quadrant blocks (more detail)
PAL_SHADE    = " \u2591\u2592\u2593\u2588\u2587\u2586\u2585\u2584\u2583\u2582\u2581"          # vertical fill progression
```

#### 符号/主题类
```python
PAL_MATH     = " \u00b7\u2218\u2219\u2022\u00b0\u00b1\u2213\u00d7\u00f7\u2248\u2260\u2261\u2264\u2265\u221e\u222b\u2211\u220f\u221a\u2207\u2202\u2206\u03a9"    # math symbols
PAL_BOX      = " \u2500\u2502\u250c\u2510\u2514\u2518\u251c\u2524\u252c\u2534\u253c\u2550\u2551\u2554\u2557\u255a\u255d\u2560\u2563\u2566\u2569\u256c"          # box drawing
PAL_CIRCUIT  = " .\u00b7\u2500\u2502\u250c\u2510\u2514\u2518\u253c\u25cb\u25cf\u25a1\u25a0\u2206\u2207\u2261"                 # circuit board
PAL_RUNE     = " .\u16a0\u16a2\u16a6\u16b1\u16b7\u16c1\u16c7\u16d2\u16d6\u16da\u16de\u16df"                   # elder futhark runes
PAL_ALCHEMIC = " \u2609\u263d\u2640\u2642\u2643\u2644\u2645\u2646\u2647\u2648\u2649\u264a\u264b"            # planetary/alchemical symbols
PAL_ZODIAC   = " \u2648\u2649\u264a\u264b\u264c\u264d\u264e\u264f\u2650\u2651\u2652\u2653"            # zodiac
PAL_ARROWS   = " \u2190\u2191\u2192\u2193\u2194\u2195\u2196\u2197\u2198\u2199\u21a9\u21aa\u21bb\u27a1"             # directional arrows
PAL_MUSIC    = " \u266a\u266b\u266c\u2669\u266d\u266e\u266f\u25cb\u25cf"                       # musical notation
```

#### 文字/书写系统
```python
PAL_KATA     = " \u00b7\uff66\uff67\uff68\uff69\uff6a\uff6b\uff6c\uff6d\uff6e\uff6f\uff70\uff71\uff72\uff73\uff74\uff75\uff76\uff77"          # katakana halfwidth (matrix rain)
PAL_GREEK    = " \u03b1\u03b2\u03b3\u03b4\u03b5\u03b6\u03b7\u03b8\u03b9\u03ba\u03bb\u03bc\u03bd\u03be\u03c0\u03c1\u03c3\u03c4\u03c6\u03c8\u03c9"    # Greek lowercase
PAL_CYRILLIC = " \u0430\u0431\u0432\u0433\u0434\u0435\u0436\u0437\u0438\u043a\u043b\u043c\u043d\u043e\u043f\u0440\u0441\u0442\u0443\u0444\u0445\u0446\u0447\u0448"  # Cyrillic lowercase
PAL_ARABIC   = " \u0627\u0628\u062a\u062b\u062c\u062d\u062e\u062f\u0630\u0631\u0632\u0633\u0634\u0635\u0636\u0637"       # Arabic letters (isolated forms)
```

#### 点/点状渐进
```python
PAL_DOTS     = " ⋅∘∙●◉◎◆✦★"                   # dot size progression
PAL_BRAILLE  = " ⠁⠂⠃⠄⠅⠆⠇⠈⠉⠊⠋⠌⠍⠎⠏⠐⠑⠒⠓⠔⠕⠖⠗⠘⠙⠚⠛⠜⠝⠞⠟⠿"  # braille patterns
PAL_STARS    = " ·✧✦✩✨★✶✳✸"               # star progression
PAL_HALFFILL = " ◔◑◕◐◒◓◖◗◙"               # directional half-fill progression
PAL_HATCH    = " ▣▤▥▦▧▨▩"                     # crosshatch density ramp
```

#### 项目专用（示例——为每个项目创造新的调色板）
```python
PAL_HERMES   = " .\u00b7~=\u2248\u221e\u26a1\u263f\u2726\u2605\u2295\u25ca\u25c6\u25b2\u25bc\u25cf\u25a0"   # mythology/tech blend
PAL_OCEAN    = " ~\u2248\u2248\u2248\u223c\u2307\u2248\u224b\u224c\u2248"                       # water/wave characters
PAL_ORGANIC  = " .\u00b0\u2218\u2022\u25e6\u25c9\u2742\u273f\u2741\u2743"                 # growing/botanical
PAL_MACHINE  = " _\u2500\u2502\u250c\u2510\u253c\u2261\u25a0\u2588\u2593\u2592\u2591"             # mechanical/industrial
```

### 创建自定义调色板

为项目进行设计时，应围绕内容主题构建调色板：

1. **选择视觉家族**（点、块、符号、文字）
2. **按视觉权重排序**——以目标字号渲染每个字符，统计发光像素数量，然后按升序排列
3. **在目标网格尺寸下测试**——某些字符在较小尺寸下会糊成一团
4. **在字体中验证**——移除字体无法渲染的字符：

```python
def validate_palette(pal, font):
    """Remove characters the font can't render."""
    valid = []
    for c in pal:
        if c == " ":
            valid.append(c)
            continue
        img = Image.new("L", (20, 20), 0)
        ImageDraw.Draw(img).text((0, 0), c, fill=255, font=font)
        if np.array(img).max() > 0:  # char actually rendered something
            valid.append(c)
    return "".join(valid)
```

### 将数值映射到字符

```python
def val2char(v, mask, pal=PAL_DEFAULT):
    """Map float array (0-1) to character array using palette."""
    n = len(pal)
    idx = np.clip((v * n).astype(int), 0, n - 1)
    out = np.full(v.shape, " ", dtype="U1")
    for i, ch in enumerate(pal):
        out[mask & (idx == i)] = ch
    return out
```

适用于不同视觉曲线的**非线性映射**：

```python
def val2char_gamma(v, mask, pal, gamma=1.0):
    """Gamma-corrected palette mapping. gamma<1 = brighter, gamma>1 = darker."""
    v_adj = np.power(np.clip(v, 0, 1), gamma)
    return val2char(v_adj, mask, pal)

def val2char_step(v, mask, pal, thresholds):
    """Custom threshold mapping. thresholds = list of float breakpoints."""
    out = np.full(v.shape, pal[0], dtype="U1")
    for i, thr in enumerate(thresholds):
        out[mask & (v > thr)] = pal[min(i + 1, len(pal) - 1)]
    return out
```

---

## 色彩系统

### HSV->RGB（向量化）

所有色彩计算都在 HSV 中完成，以便直观控制，并在渲染时转换：

```python
def hsv2rgb(h, s, v):
    """Vectorized HSV->RGB. h,s,v are numpy arrays. Returns (R,G,B) uint8 arrays."""
    h = h % 1.0
    c = v * s; x = c * (1 - np.abs((h*6) % 2 - 1)); m = v - c
    # ... 6 sector assignment ...
    return (np.clip((r+m)*255, 0, 255).astype(np.uint8),
            np.clip((g+m)*255, 0, 255).astype(np.uint8),
            np.clip((b+m)*255, 0, 255).astype(np.uint8))
```

### 色彩映射策略

不要默认只使用一种策略。应根据视觉意图进行选择：

| 策略 | 色相来源 | 效果 | 适用场景 |
|----------|------------|--------|----------|
| 角度映射 | `g.angle / (2*pi)` | 围绕中心的彩虹 | 径向效果、万花筒 |
| 距离映射 | `g.dist_n * 0.3` | 从中心向外渐变 | 隧道、纵深效果 |
| 频率映射 | `f["cent"] * 0.2` | 随音色改变色彩 | 音频响应效果 |
| 数值映射 | `val * 0.15` | 依赖亮度的色相 | 火焰、热力图 |
| 时间循环 | `t * rate` | 缓慢旋转色彩 | 氛围、轻松场景 |
| 源采样 | 视频帧像素颜色 | 保留原始色彩 | 视频转 ASCII |
| 调色板索引 | 离散色彩查找 | 扁平图形风格 | 复古、像素艺术 |
| 色温 | 在暖色与冷色之间混合 | 情绪基调 | 氛围驱动的场景 |
| 互补色 | `hue` 和 `hue + 0.5` | 高对比度 | 醒目、戏剧化 |
| 三角色 | `hue`、`hue + 0.33`、`hue + 0.66` | 鲜艳、均衡 | 迷幻效果 |
| 类似色 | `hue +/- 0.08` | 和谐、细腻 | 优雅、统一 |
| 单色 | 固定色相，改变 S 和 V | 克制、聚焦 | 黑色电影、极简风格 |

### 调色板（离散 RGB）

对于非 HSV 工作流——直接使用 RGB 色彩集合，营造图形化/复古外观：

```python
# Named color palettes -- use for flat/graphic styles or per-character coloring
COLORS_NEON = [(255,0,102), (0,255,153), (102,0,255), (255,255,0), (0,204,255)]
COLORS_PASTEL = [(255,179,186), (255,223,186), (255,255,186), (186,255,201), (186,225,255)]
COLORS_MONO_GREEN = [(0,40,0), (0,80,0), (0,140,0), (0,200,0), (0,255,0)]
COLORS_MONO_AMBER = [(40,20,0), (80,50,0), (140,90,0), (200,140,0), (255,191,0)]
COLORS_CYBERPUNK = [(255,0,60), (0,255,200), (180,0,255), (255,200,0)]
COLORS_VAPORWAVE = [(255,113,206), (1,205,254), (185,103,255), (5,255,161)]
COLORS_EARTH = [(86,58,26), (139,90,43), (189,154,91), (222,193,136), (245,230,193)]
COLORS_ICE = [(200,230,255), (150,200,240), (100,170,230), (60,130,210), (30,80,180)]
COLORS_BLOOD = [(80,0,0), (140,10,10), (200,20,20), (255,50,30), (255,100,80)]
COLORS_FOREST = [(10,30,10), (20,60,15), (30,100,20), (50,150,30), (80,200,50)]

def rgb_palette_map(val, mask, palette):
    """Map float array (0-1) to RGB colors from a discrete palette."""
    n = len(palette)
    idx = np.clip((val * n).astype(int), 0, n - 1)
    R = np.zeros(val.shape, dtype=np.uint8)
    G = np.zeros(val.shape, dtype=np.uint8)
    B = np.zeros(val.shape, dtype=np.uint8)
    for i, (r, g, b) in enumerate(palette):
        m = mask & (idx == i)
        R[m] = r; G[m] = g; B[m] = b
    return R, G, B
```

### OKLAB 色彩空间（感知均匀）

HSV 色相在感知上并不均匀：绿色占据的视觉范围远大于蓝色。OKLAB / OKLCH 能提供感知均匀的色彩步进——无论起始色相如何，0.1 的色相增量看起来都同样不同。OKLAB 适用于：
- 渐变插值（不会出现不需要的中间色相）
- 生成色彩和谐方案（感知上均衡的调色板）
- 随时间平滑过渡色彩

```python
# --- sRGB <-> Linear sRGB ---

def srgb_to_linear(c):
    """Convert sRGB [0,1] to linear light. c: float32 array."""
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)

def linear_to_srgb(c):
    """Convert linear light to sRGB [0,1]."""
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(np.maximum(c, 0), 1/2.4) - 0.055)

# --- Linear sRGB <-> OKLAB ---

def linear_rgb_to_oklab(r, g, b):
    """Linear sRGB to OKLAB. r,g,b: float32 arrays [0,1].
    Returns (L, a, b) where L=[0,1], a,b=[-0.4, 0.4] approx."""
    l_ = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m_ = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s_ = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_c = np.cbrt(l_); m_c = np.cbrt(m_); s_c = np.cbrt(s_)
    L = 0.2104542553 * l_c + 0.7936177850 * m_c - 0.0040720468 * s_c
    a = 1.9779984951 * l_c - 2.4285922050 * m_c + 0.4505937099 * s_c
    b_ = 0.0259040371 * l_c + 0.7827717662 * m_c - 0.8086757660 * s_c
    return L, a, b_

def oklab_to_linear_rgb(L, a, b):
    """OKLAB to linear sRGB. Returns (r, g, b) float32 arrays [0,1]."""
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l_c = l_ ** 3; m_c = m_ ** 3; s_c = s_ ** 3
    r = +4.0767416621 * l_c - 3.3077115913 * m_c + 0.2309699292 * s_c
    g = -1.2684380046 * l_c + 2.6097574011 * m_c - 0.3413193965 * s_c
    b_ = -0.0041960863 * l_c - 0.7034186147 * m_c + 1.7076147010 * s_c
    return np.clip(r, 0, 1), np.clip(g, 0, 1), np.clip(b_, 0, 1)

# --- Convenience: sRGB uint8 <-> OKLAB ---

def rgb_to_oklab(R, G, B):
    """sRGB uint8 arrays to OKLAB."""
    r = srgb_to_linear(R.astype(np.float32) / 255.0)
    g = srgb_to_linear(G.astype(np.float32) / 255.0)
    b = srgb_to_linear(B.astype(np.float32) / 255.0)
    return linear_rgb_to_oklab(r, g, b)

def oklab_to_rgb(L, a, b):
    """OKLAB to sRGB uint8 arrays."""
    r, g, b_ = oklab_to_linear_rgb(L, a, b)
    R = np.clip(linear_to_srgb(r) * 255, 0, 255).astype(np.uint8)
    G = np.clip(linear_to_srgb(g) * 255, 0, 255).astype(np.uint8)
    B = np.clip(linear_to_srgb(b_) * 255, 0, 255).astype(np.uint8)
    return R, G, B

# --- OKLCH (cylindrical form of OKLAB) ---

def oklab_to_oklch(L, a, b):
    """OKLAB to OKLCH. Returns (L, C, H) where H is in [0, 1] (normalized)."""
    C = np.sqrt(a**2 + b**2)
    H = (np.arctan2(b, a) / (2 * np.pi)) % 1.0
    return L, C, H

def oklch_to_oklab(L, C, H):
    """OKLCH to OKLAB. H in [0, 1]."""
    angle = H * 2 * np.pi
    a = C * np.cos(angle)
    b = C * np.sin(angle)
    return L, a, b
```

### 渐变插值（OKLAB 与 HSV 对比）

通过 OKLAB 插值色彩，可避免 HSV 产生的色相绕行：

```python
def lerp_oklab(color_a, color_b, t_array):
    """Interpolate between two sRGB colors through OKLAB.
    color_a, color_b: (R, G, B) tuples 0-255
    t_array: float32 array [0,1] — interpolation parameter per pixel.
    Returns (R, G, B) uint8 arrays."""
    La, aa, ba = rgb_to_oklab(
        np.full_like(t_array, color_a[0], dtype=np.uint8),
        np.full_like(t_array, color_a[1], dtype=np.uint8),
        np.full_like(t_array, color_a[2], dtype=np.uint8))
    Lb, ab, bb = rgb_to_oklab(
        np.full_like(t_array, color_b[0], dtype=np.uint8),
        np.full_like(t_array, color_b[1], dtype=np.uint8),
        np.full_like(t_array, color_b[2], dtype=np.uint8))
    L = La + (Lb - La) * t_array
    a = aa + (ab - aa) * t_array
    b = ba + (bb - ba) * t_array
    return oklab_to_rgb(L, a, b)

def lerp_oklch(color_a, color_b, t_array, short_path=True):
    """Interpolate through OKLCH (preserves chroma, smooth hue path).
    short_path: take the shorter arc around the hue wheel."""
    La, aa, ba = rgb_to_oklab(
        np.full_like(t_array, color_a[0], dtype=np.uint8),
        np.full_like(t_array, color_a[1], dtype=np.uint8),
        np.full_like(t_array, color_a[2], dtype=np.uint8))
    Lb, ab, bb = rgb_to_oklab(
        np.full_like(t_array, color_b[0], dtype=np.uint8),
        np.full_like(t_array, color_b[1], dtype=np.uint8),
        np.full_like(t_array, color_b[2], dtype=np.uint8))
    L1, C1, H1 = oklab_to_oklch(La, aa, ba)
    L2, C2, H2 = oklab_to_oklch(Lb, ab, bb)
    # Shortest hue path
    if short_path:
        dh = H2 - H1
        dh = np.where(dh > 0.5, dh - 1.0, np.where(dh < -0.5, dh + 1.0, dh))
        H = (H1 + dh * t_array) % 1.0
    else:
        H = H1 + (H2 - H1) * t_array
    L = L1 + (L2 - L1) * t_array
    C = C1 + (C2 - C1) * t_array
    Lout, aout, bout = oklch_to_oklab(L, C, H)
    return oklab_to_rgb(Lout, aout, bout)
```

### 生成色彩和谐方案

根据种子颜色自动生成和谐的调色板：

```python
def harmony_complementary(seed_rgb):
    """Two colors: seed + opposite hue."""
    L, a, b = rgb_to_oklab(np.array([seed_rgb[0]]), np.array([seed_rgb[1]]), np.array([seed_rgb[2]]))
    _, C, H = oklab_to_oklch(L, a, b)
    return [seed_rgb, _oklch_to_srgb_tuple(L[0], C[0], (H[0] + 0.5) % 1.0)]

def harmony_triadic(seed_rgb):
    """Three colors: seed + two at 120-degree offsets."""
    L, a, b = rgb_to_oklab(np.array([seed_rgb[0]]), np.array([seed_rgb[1]]), np.array([seed_rgb[2]]))
    _, C, H = oklab_to_oklch(L, a, b)
    return [seed_rgb,
            _oklch_to_srgb_tuple(L[0], C[0], (H[0] + 0.333) % 1.0),
            _oklch_to_srgb_tuple(L[0], C[0], (H[0] + 0.667) % 1.0)]

def harmony_analogous(seed_rgb, spread=0.08, n=5):
    """N colors spread evenly around seed hue."""
    L, a, b = rgb_to_oklab(np.array([seed_rgb[0]]), np.array([seed_rgb[1]]), np.array([seed_rgb[2]]))
    _, C, H = oklab_to_oklch(L, a, b)
    offsets = np.linspace(-spread * (n-1)/2, spread * (n-1)/2, n)
    return [_oklch_to_srgb_tuple(L[0], C[0], (H[0] + off) % 1.0) for off in offsets]

def harmony_split_complementary(seed_rgb, split=0.08):
    """Three colors: seed + two flanking the complement."""
    L, a, b = rgb_to_oklab(np.array([seed_rgb[0]]), np.array([seed_rgb[1]]), np.array([seed_rgb[2]]))
    _, C, H = oklab_to_oklch(L, a, b)
    comp = (H[0] + 0.5) % 1.0
    return [seed_rgb,
            _oklch_to_srgb_tuple(L[0], C[0], (comp - split) % 1.0),
            _oklch_to_srgb_tuple(L[0], C[0], (comp + split) % 1.0)]

def harmony_tetradic(seed_rgb):
    """Four colors: two complementary pairs at 90-degree offset."""
    L, a, b = rgb_to_oklab(np.array([seed_rgb[0]]), np.array([seed_rgb[1]]), np.array([seed_rgb[2]]))
    _, C, H = oklab_to_oklch(L, a, b)
    return [seed_rgb,
            _oklch_to_srgb_tuple(L[0], C[0], (H[0] + 0.25) % 1.0),
            _oklch_to_srgb_tuple(L[0], C[0], (H[0] + 0.5) % 1.0),
            _oklch_to_srgb_tuple(L[0], C[0], (H[0] + 0.75) % 1.0)]

def _oklch_to_srgb_tuple(L, C, H):
    """Helper: single OKLCH -> sRGB (R,G,B) int tuple."""
    La = np.array([L]); Ca = np.array([C]); Ha = np.array([H])
    Lo, ao, bo = oklch_to_oklab(La, Ca, Ha)
    R, G, B = oklab_to_rgb(Lo, ao, bo)
    return (int(R[0]), int(G[0]), int(B[0]))
```

### OKLAB 色相场

可直接替换 `hf_*` 生成器，以产生感知均匀的色相变化：

```python
def hf_oklch_angle(offset=0.0, chroma=0.12, lightness=0.7):
    """OKLCH hue mapped to angle from center. Perceptually uniform rainbow.
    Returns (R, G, B) uint8 color array instead of a float hue.
    NOTE: Use with _render_vf_rgb() variant, not standard _render_vf()."""
    def fn(g, f, t, S):
        H = (g.angle / (2 * np.pi) + offset + t * 0.05) % 1.0
        L = np.full_like(H, lightness)
        C = np.full_like(H, chroma)
        Lo, ao, bo = oklch_to_oklab(L, C, H)
        R, G, B = oklab_to_rgb(Lo, ao, bo)
        return mkc(R, G, B, g.rows, g.cols)
    return fn
```

### 合成辅助函数

```python
def mkc(R, G, B, rows, cols):
    """Pack 3 uint8 arrays into (rows, cols, 3) color array."""
    o = np.zeros((rows, cols, 3), dtype=np.uint8)
    o[:,:,0] = R; o[:,:,1] = G; o[:,:,2] = B
    return o

def layer_over(base_ch, base_co, top_ch, top_co):
    """Composite top layer onto base. Non-space chars overwrite."""
    m = top_ch != " "
    base_ch[m] = top_ch[m]; base_co[m] = top_co[m]
    return base_ch, base_co

def layer_blend(base_co, top_co, alpha):
    """Alpha-blend top color layer onto base. alpha is float array (0-1) or scalar."""
    if isinstance(alpha, (int, float)):
        alpha = np.full(base_co.shape[:2], alpha, dtype=np.float32)
    a = alpha[:,:,None]
    return np.clip(base_co * (1 - a) + top_co * a, 0, 255).astype(np.uint8)

def stamp(ch, co, text, row, col, color=(255,255,255)):
    """Write text string at position."""
    for i, c in enumerate(text):
        cc = col + i
        if 0 <= row < ch.shape[0] and 0 <= cc < ch.shape[1]:
            ch[row, cc] = c; co[row, cc] = color
```

---

## 区段系统

将时间范围映射到效果函数、着色器配置和网格尺寸：

```python
SECTIONS = [
    (0.0, "void"), (3.94, "starfield"), (21.0, "matrix"),
    (46.0, "drop"), (130.0, "glitch"), (187.0, "outro"),
]

FX_DISPATCH = {"void": fx_void, "starfield": fx_starfield, ...}
SECTION_FX = {"void": {"vignette": 0.3, "bloom": 170}, ...}
SECTION_GRID = {"void": "md", "starfield": "sm", "drop": "lg", ...}
SECTION_MIRROR = {"drop": "h", "bass_rings": "quad"}

def get_section(t):
    sec = SECTIONS[0][1]
    for ts, name in SECTIONS:
        if t >= ts: sec = name
    return sec
```

---

## 并行编码

将帧分配给 N 个工作进程。每个进程都通过管道把原始 RGB 数据传给自己的 ffmpeg 子进程：

```python
def render_batch(batch_id, frame_start, frame_end, features, seg_path):
    r = Renderer()
    cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{VW}x{VH}", "-r", str(FPS), "-i", "pipe:0",
           "-c:v", "libx264", "-preset", "fast", "-crf", "18",
           "-pix_fmt", "yuv420p", seg_path]

    # CRITICAL: stderr to file, not pipe
    stderr_fh = open(os.path.join(workdir, f"err_{batch_id:02d}.log"), "w")
    pipe = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=stderr_fh)

    for fi in range(frame_start, frame_end):
        t = fi / FPS
        sec = get_section(t)
        f = {k: float(features[k][fi]) for k in features}
        ch, co = FX_DISPATCH[sec](r, f, t)
        canvas = r.render(ch, co)
        canvas = apply_mirror(canvas, sec, f)
        canvas = apply_shaders(canvas, sec, f, t)
        pipe.stdin.write(canvas.tobytes())

    pipe.stdin.close()
    pipe.wait()
    stderr_fh.close()
```

拼接分段并混流音频：

```python
# Write concat file
with open(concat_path, "w") as cf:
    for seg in segments:
        cf.write(f"file '{seg}'\n")

subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_path,
                "-i", audio_path, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", output_path])
```

## 效果函数约定

### v2 协议（当前）

每个场景函数：`(r, f, t, S) -> canvas_uint8`——其中 `r` = Renderer，`f` = 特征字典，`t` = 时间浮点数，`S` = 持久状态字典

```python
def fx_example(r, f, t, S):
    """Scene function returns a full pixel canvas (uint8 H,W,3).
    Scenes have full control over multi-grid rendering and pixel-level composition.
    """
    # Render multiple layers at different grid densities
    canvas_a = _render_vf(r, "md", vf_plasma, hf_angle(0.0), PAL_DENSE, f, t, S)
    canvas_b = _render_vf(r, "sm", vf_vortex, hf_time_cycle(0.1), PAL_RUNE, f, t, S)

    # Pixel-level blend
    result = blend_canvas(canvas_a, canvas_b, "screen", 0.8)
    return result
```

请参阅 `references/scenes.md`，了解完整的场景协议、Renderer 类、`_render_vf()` 辅助函数和完整场景示例。

混合模式、色调映射、反馈缓冲区和多网格合成，请参阅 `references/composition.md`。

### v1 协议（旧版）

使用单一网格的简单场景仍可返回 `(chars, colors)`，并由调用方负责渲染；但所有新代码均推荐使用 v2 画布协议。

```python
def fx_simple(r, f, t, S):
    g = r.get_grid("md")
    val = np.sin(g.dist * 0.1 - t * 3) * f.get("bass", 0.3) * 2
    val = np.clip(val, 0, 1); mask = val > 0.03
    ch = val2char(val, mask, PAL_DEFAULT)
    R, G, B = hsv2rgb(np.full_like(val, 0.6), np.full_like(val, 0.7), val)
    co = mkc(R, G, B, g.rows, g.cols)
    return g.render(ch, co)  # returns canvas directly
```

### 持久状态

需要跨帧保持状态的效果（粒子、雨柱）使用 `S` 字典参数（它就是 `r.S`——两者是同一对象，但为清晰起见显式传入）：

```python
def fx_with_state(r, f, t, S):
    if "particles" not in S:
        S["particles"] = initialize_particles()
    update_particles(S["particles"])
    # ...
```

状态会在单个场景/剪辑的各帧之间持续存在。每个工作进程（以及每个场景）都有各自独立的状态。

### 辅助函数

```python
def hsv2rgb_scalar(h, s, v):
    """Single-value HSV to RGB. Returns (R, G, B) tuple of ints 0-255."""
    h = h % 1.0
    c = v * s; x = c * (1 - abs((h * 6) % 2 - 1)); m = v - c
    if h * 6 < 1:   r, g, b = c, x, 0
    elif h * 6 < 2:  r, g, b = x, c, 0
    elif h * 6 < 3:  r, g, b = 0, c, x
    elif h * 6 < 4:  r, g, b = 0, x, c
    elif h * 6 < 5:  r, g, b = x, 0, c
    else:             r, g, b = c, 0, x
    return (int((r+m)*255), int((g+m)*255), int((b+m)*255))

def log(msg):
    """Print timestamped log message."""
    print(msg, flush=True)
```
