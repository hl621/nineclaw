# 优化参考

> **另请参阅：** architecture.md · composition.md · scenes.md · shaders.md · inputs.md · troubleshooting.md

## 硬件检测

在脚本启动时检测用户的硬件，并自动调整渲染参数。切勿硬编码 worker 数量或分辨率。

### CPU 与内存检测

```python
import multiprocessing
import platform
import shutil
import os

def detect_hardware():
    """Detect hardware capabilities and return render config."""
    cpu_count = multiprocessing.cpu_count()
    
    # Leave 1-2 cores free for OS + ffmpeg encoding
    if cpu_count >= 16:
        workers = cpu_count - 2
    elif cpu_count >= 8:
        workers = cpu_count - 1
    elif cpu_count >= 4:
        workers = cpu_count - 1
    else:
        workers = max(1, cpu_count)
    
    # Memory detection (platform-specific)
    try:
        if platform.system() == "Darwin":
            import subprocess
            mem_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
        elif platform.system() == "Linux":
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        mem_bytes = int(line.split()[1]) * 1024
                        break
        else:
            mem_bytes = 8 * 1024**3  # assume 8GB on unknown
    except Exception:
        mem_bytes = 8 * 1024**3

    mem_gb = mem_bytes / (1024**3)
    
    # Each worker uses ~50-150MB depending on grid sizes
    # Cap workers if memory is tight
    mem_per_worker_mb = 150
    max_workers_by_mem = int(mem_gb * 1024 * 0.6 / mem_per_worker_mb)  # use 60% of RAM
    workers = min(workers, max_workers_by_mem)
    
    # ffmpeg availability and codec support
    has_ffmpeg = shutil.which("ffmpeg") is not None
    
    return {
        "cpu_count": cpu_count,
        "workers": workers,
        "mem_gb": mem_gb,
        "platform": platform.system(),
        "arch": platform.machine(),
        "has_ffmpeg": has_ffmpeg,
    }
```

### 自适应质量配置

根据硬件调整分辨率、FPS、CRF 和网格密度：

```python
def quality_profile(hw, target_duration_s, user_preference="auto"):
    """
    Returns render settings adapted to hardware.
    user_preference: "auto", "draft", "preview", "production", "max"
    """
    if user_preference == "draft":
        return {"vw": 960, "vh": 540, "fps": 12, "crf": 28, "workers": min(4, hw["workers"]),
                "grid_scale": 0.5, "shaders": "minimal", "particles_max": 200}
    
    if user_preference == "preview":
        return {"vw": 1280, "vh": 720, "fps": 15, "crf": 25, "workers": hw["workers"],
                "grid_scale": 0.75, "shaders": "standard", "particles_max": 500}
    
    if user_preference == "max":
        return {"vw": 3840, "vh": 2160, "fps": 30, "crf": 15, "workers": hw["workers"],
                "grid_scale": 2.0, "shaders": "full", "particles_max": 3000}
    
    # "production" or "auto"
    # Auto-detect: estimate render time, downgrade if it would take too long
    n_frames = int(target_duration_s * 24)
    est_seconds_per_frame = 0.18  # ~180ms at 1080p
    est_total_s = n_frames * est_seconds_per_frame / max(1, hw["workers"])
    
    if hw["mem_gb"] < 4 or hw["cpu_count"] <= 2:
        # Low-end: 720p, 15fps
        return {"vw": 1280, "vh": 720, "fps": 15, "crf": 23, "workers": hw["workers"],
                "grid_scale": 0.75, "shaders": "standard", "particles_max": 500}
    
    if est_total_s > 3600:  # would take over an hour
        # Downgrade to 720p to speed up
        return {"vw": 1280, "vh": 720, "fps": 24, "crf": 20, "workers": hw["workers"],
                "grid_scale": 0.75, "shaders": "standard", "particles_max": 800}
    
    # Standard production: 1080p 24fps
    return {"vw": 1920, "vh": 1080, "fps": 24, "crf": 20, "workers": hw["workers"],
            "grid_scale": 1.0, "shaders": "full", "particles_max": 1200}


def apply_quality_profile(profile):
    """Set globals from quality profile."""
    global VW, VH, FPS, N_WORKERS
    VW = profile["vw"]
    VH = profile["vh"]
    FPS = profile["fps"]
    N_WORKERS = profile["workers"]
    # Grid sizes scale with resolution
    # CRF passed to ffmpeg encoder
    # Shader set determines which post-processing is active
```

### CLI 集成

```python
parser = argparse.ArgumentParser()
parser.add_argument("--quality", choices=["draft", "preview", "production", "max", "auto"],
                    default="auto", help="Render quality preset")
parser.add_argument("--aspect", choices=["landscape", "portrait", "square"],
                    default="landscape", help="Aspect ratio preset")
parser.add_argument("--workers", type=int, default=0, help="Override worker count (0=auto)")
parser.add_argument("--resolution", type=str, default="", help="Override resolution e.g. 1280x720")
args = parser.parse_args()

hw = detect_hardware()
if args.workers > 0:
    hw["workers"] = args.workers
profile = quality_profile(hw, target_duration, args.quality)

# Apply aspect ratio preset (before manual resolution override)
ASPECT_PRESETS = {
    "landscape": (1920, 1080),
    "portrait":  (1080, 1920),
    "square":    (1080, 1080),
}
if args.aspect != "landscape" and not args.resolution:
    profile["vw"], profile["vh"] = ASPECT_PRESETS[args.aspect]

if args.resolution:
    w, h = args.resolution.split("x")
    profile["vw"], profile["vh"] = int(w), int(h)
apply_quality_profile(profile)

log(f"Hardware: {hw['cpu_count']} cores, {hw['mem_gb']:.1f}GB RAM, {hw['platform']}")
log(f"Render:   {profile['vw']}x{profile['vh']} @{profile['fps']}fps, "
    f"CRF {profile['crf']}, {profile['workers']} workers")
```

### 竖屏模式注意事项

竖屏（1080x1920）与横屏 1080p 的像素数相同，因此性能相当。但二者的 composition 模式有所不同：

| 关注项 | 横屏 | 竖屏 |
|---------|-----------|----------|
| `lg` 下的网格列数 | 160 | 90 |
| `lg` 下的网格行数 | 45 | 80 |
| 文本行最大字符数 | 居中时约 50 | 居中时约 25-30 |
| 垂直雨幕 | 移动距离短 | 移动距离长且更具戏剧性 |
| 水平频谱 | 占满宽度 | 需要旋转或压缩 |
| 径向 effects | 自然的圆形 | 高椭圆（宽高比校正会处理此问题） |
| 粒子爆炸 | 横向扩散广 | 纵向扩散高 |
| 文本堆叠 | 3-4 行较舒适 | 8-10 行较舒适 |
| 引用布局 | 2-3 行宽文本 | 5-6 行短文本 |

**针对竖屏优化的模式：**
- 垂直雨幕/矩阵 effects 会自然增强——列的移动距离更长
- 火焰列能上升并穿过更多屏幕空间
- 上升的余烬/粒子拥有更长的垂直移动空间
- 文本可以用更多行进行更紧凑的堆叠
- 应用宽高比校正后，径向 effects 可正常工作（GridLayer 会自动处理）
- 频谱条可旋转 90 度（从底部升起的垂直条）

**竖屏文本布局：**
```python
def layout_text_portrait(text, max_chars_per_line=25, grid=None):
    """Break text into short lines for portrait display."""
    words = text.split()
    lines = []; current = ""
    for w in words:
        if len(current) + len(w) + 1 > max_chars_per_line:
            lines.append(current.strip())
            current = w + " "
        else:
            current += w + " "
    if current.strip():
        lines.append(current.strip())
    return lines
```

## 性能预算

目标：每帧 100-200ms（单线程 5-10 fps，8 个 worker 合计 40-80 fps）。

| 组件 | 耗时 | 说明 |
|-----------|------|-------|
| 特征提取 | 1-5ms | 渲染前为所有帧预计算 |
| Effect 函数 | 2-15ms | 使用向量化 NumPy，避免 Python 循环 |
| 字符渲染 | 80-150ms | **瓶颈**——逐单元格 Python 循环 |
| Shader pipeline | 5-25ms | 取决于启用的 shaders |
| ffmpeg 编码 | ~5ms | 通过管道缓冲摊销 |

## 位图预栅格化

在初始化时栅格化每个字符，而不是逐帧栅格化：

```python
# At init time -- done once
for c in all_characters:
    img = Image.new("L", (cell_w, cell_h), 0)
    ImageDraw.Draw(img).text((0, 0), c, fill=255, font=font)
    bitmaps[c] = np.array(img, dtype=np.float32) / 255.0  # float32 for fast multiply

# At render time -- fast lookup
bitmap = bitmaps[char]
canvas[y:y+ch, x:x+cw] = np.maximum(canvas[y:y+ch, x:x+cw],
                                      (bitmap[:,:,None] * color).astype(np.uint8))
```

从所有 palettes 和叠加文本中收集全部字符，放入初始化集合。对任何遗漏的字符进行延迟初始化。

## 预渲染背景纹理

对于字符不需要逐帧变化的背景，这是 `_render_vf()` 的替代方案。初始化时一次性预烘焙静态 ASCII 纹理，然后每帧乘以逐单元格颜色场。只需一次矩阵乘法，而不是数千次位图 blit。

适用场景：背景层使用固定字符 palette，每帧仅改变颜色/亮度。不适用于字符选择依赖动态 value field 的图层。

### 初始化：烘焙纹理

```python
# In GridLayer.__init__:
self._bg_row_idx = np.clip(
    (np.arange(VH) - self.oy) // self.ch, 0, self.rows - 1
)
self._bg_col_idx = np.clip(
    (np.arange(VW) - self.ox) // self.cw, 0, self.cols - 1
)
self._bg_textures = {}

def make_bg_texture(self, palette):
    """Pre-render a static ASCII texture (grayscale float32) once."""
    if palette not in self._bg_textures:
        texture = np.zeros((VH, VW), dtype=np.float32)
        rng = random.Random(12345)
        ch_list = [c for c in palette if c != " " and c in self.bm]
        if not ch_list:
            ch_list = list(self.bm.keys())[:5]
        for row in range(self.rows):
            y = self.oy + row * self.ch
            if y + self.ch > VH:
                break
            for col in range(self.cols):
                x = self.ox + col * self.cw
                if x + self.cw > VW:
                    break
                bm = self.bm[rng.choice(ch_list)]
                texture[y:y+self.ch, x:x+self.cw] = bm
        self._bg_textures[palette] = texture
    return self._bg_textures[palette]
```

### 渲染：颜色场 x 缓存纹理

```python
def render_bg(self, color_field, palette=PAL_CIRCUIT):
    """Fast background: pre-rendered ASCII texture * per-cell color field.
    color_field: (rows, cols, 3) uint8. Returns (VH, VW, 3) uint8."""
    texture = self.make_bg_texture(palette)
    # Expand cell colors to pixel coords via pre-computed index maps
    color_px = color_field[
        self._bg_row_idx[:, None], self._bg_col_idx[None, :]
    ].astype(np.float32)
    return (texture[:, :, None] * color_px).astype(np.uint8)
```

### 在 Scene 中使用

```python
# Build per-cell color from effect fields (cheap — rows*cols, not VH*VW)
hue = ((t * 0.05 + val * 0.2) % 1.0).astype(np.float32)
R, G, B = hsv2rgb(hue, np.full_like(val, 0.5), val)
color_field = mkc(R, G, B, g.rows, g.cols)  # (rows, cols, 3) uint8

# Render background — single matrix multiply, no per-cell loop
canvas_bg = g.render_bg(color_field, PAL_DENSE)
```

纹理初始化循环只运行一次，并按 palette 缓存。每帧成本仅为一次花式索引查找加一次广播乘法——比密集背景中 `render()` 的逐单元格位图 blit 循环快几个数量级。

## 坐标数组缓存

在初始化时预计算所有网格相对坐标数组，而不是逐帧计算：

```python
# These are O(rows*cols) and used in every effect
self.rr = np.arange(rows)[:, None]    # row indices
self.cc = np.arange(cols)[None, :]    # col indices
self.dist = np.sqrt(dx**2 + dy**2)   # distance from center
self.angle = np.arctan2(dy, dx)       # angle from center
self.dist_n = ...                      # normalized distance
```

## 向量化 Effect 模式

### 避免在 Effects 中使用逐单元格 Python 循环

渲染循环（compositing 位图）不可避免地需要逐单元格进行。但 effect 函数必须完全采用向量化 NumPy——切勿在 Python 中遍历行/列。

错误示例（O(rows*cols) Python 循环）：
```python
for r in range(rows):
    for c in range(cols):
        val[r, c] = math.sin(c * 0.1 + t) * math.cos(r * 0.1 - t)
```

正确示例（向量化）：
```python
val = np.sin(g.cc * 0.1 + t) * np.cos(g.rr * 0.1 - t)
```

### 向量化矩阵雨

朴素的逐列、逐拖尾像素循环是仅次于渲染循环的第二大瓶颈。请使用 NumPy 花式索引：

```python
# Instead of nested Python loops over columns and trail pixels:
# Build row index arrays for all active trail pixels at once
all_rows = []
all_cols = []
all_fades = []
for c in range(cols):
    head = int(S["ry"][c])
    trail_len = S["rln"][c]
    for i in range(trail_len):
        row = head - i
        if 0 <= row < rows:
            all_rows.append(row)
            all_cols.append(c)
            all_fades.append(1.0 - i / trail_len)

# Vectorized assignment
ar = np.array(all_rows)
ac = np.array(all_cols)
af = np.array(all_fades, dtype=np.float32)
# Assign chars and colors in bulk using fancy indexing
ch[ar, ac] = ...  # vectorized char assignment
co[ar, ac, 1] = (af * bri * 255).astype(np.uint8)  # green channel
```

### 向量化火焰列

采用相同模式——累积索引数组，再批量赋值：

```python
fire_val = np.zeros((rows, cols), dtype=np.float32)
for fi in range(n_cols):
    fx_c = int((fi * cols / n_cols + np.sin(t * 2 + fi * 0.7) * 3) % cols)
    height = int(energy * rows * 0.7)
    dy = np.arange(min(height, rows))
    fr = rows - 1 - dy
    frac = dy / max(height, 1)
    # Width spread: base columns wider at bottom
    for dx in range(-1, 2):  # 3-wide columns
        c = fx_c + dx
        if 0 <= c < cols:
            fire_val[fr, c] = np.maximum(fire_val[fr, c],
                                          (1 - frac * 0.6) * (0.5 + rms * 0.5))
# Now map fire_val to chars and colors in one vectorized pass
```

## 面向文本密集 Scene 的 PIL 字符串渲染

渲染大量长文本字符串（滚动 ticker、打字机序列、创意洪流）时，可替代逐单元格位图 blit。它使用 PIL 原生的 `ImageDraw.text()`，在一次 C 调用中渲染整个字符串，而不是每个字符执行一次 Python 循环位图 blit。

典型收益：包含 56 行 ticker 的 scene 只需 56 次 PIL `text()` 调用，而不是约 10K 次单独的位图 blit。

适用场景：scene 渲染多行可读文本字符串。不适用于稀疏或空间上分散的单个字符（此类情况使用常规 `render()`）。

```python
from PIL import Image, ImageDraw

def render_text_layer(grid, rows_data, font):
    """Render dense text rows via PIL instead of per-cell bitmap blitting.

    Args:
        grid: GridLayer instance (for oy, ch, ox, font metrics)
        rows_data: list of (row_index, text_string, rgb_tuple) — one per row
        font: PIL ImageFont instance (grid.font)

    Returns:
        uint8 array (VH, VW, 3) — canvas with rendered text
    """
    img = Image.new("RGB", (VW, VH), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    for row_idx, text, color in rows_data:
        y = grid.oy + row_idx * grid.ch
        if y + grid.ch > VH:
            break
        draw.text((grid.ox, y), text, fill=color, font=font)
    return np.array(img)
```

### 在 Ticker Scene 中使用

```python
# Build ticker data (text + color per row)
rows_data = []
for row in range(n_tickers):
    text = build_ticker_text(row, t)       # scrolling substring
    color = hsv2rgb_scalar(hue, 0.85, bri) # (R, G, B) tuple
    rows_data.append((row, text, color))

# One PIL pass instead of thousands of bitmap blits
canvas_tickers = render_text_layer(g_md, rows_data, g_md.font)

# Blend with other layers normally
result = blend_canvas(canvas_bg, canvas_tickers, "screen", 0.9)
```

这纯粹是一项渲染优化——视觉输出相同，但 draw call 更少。对于根据 value fields 单独放置字符的稀疏字符场，仍需使用网格的 `render()` 方法。

## Bloom 优化

**请勿使用 `scipy.ndimage.uniform_filter`**——实测耗时为 424ms/帧。

请改用 4x 下采样加手动 box blur——84ms/帧（快 5 倍）：

```python
sm = canvas[::4, ::4].astype(np.float32)  # 4x downsample
br = np.where(sm > threshold, sm, 0)
for _ in range(3):                          # 3-pass manual box blur
    p = np.pad(br, ((1,1),(1,1),(0,0)), mode='edge')
    br = (p[:-2,:-2] + p[:-2,1:-1] + p[:-2,2:] +
          p[1:-1,:-2] + p[1:-1,1:-1] + p[1:-1,2:] +
          p[2:,:-2] + p[2:,1:-1] + p[2:,2:]) / 9.0
bl = np.repeat(np.repeat(br, 4, axis=0), 4, axis=1)[:H, :W]
```

## Vignette 缓存

距离场依赖分辨率和强度，且不会逐帧变化：

```python
_vig_cache = {}
def sh_vignette(canvas, strength):
    key = (canvas.shape[0], canvas.shape[1], round(strength, 2))
    if key not in _vig_cache:
        Y = np.linspace(-1, 1, H)[:, None]
        X = np.linspace(-1, 1, W)[None, :]
        _vig_cache[key] = np.clip(1.0 - np.sqrt(X**2+Y**2) * strength, 0.15, 1).astype(np.float32)
    return np.clip(canvas * _vig_cache[key][:,:,None], 0, 255).astype(np.uint8)
```

CRT 桶形畸变也采用相同模式（缓存 remap 坐标）。

## 胶片颗粒优化

以一半分辨率生成噪声，再平铺放大：

```python
noise = np.random.randint(-amt, amt+1, (H//2, W//2, 1), dtype=np.int16)
noise = np.repeat(np.repeat(noise, 2, axis=0), 2, axis=1)[:H, :W]
```

2x 块状颗粒看起来与胶片颗粒相似，随机数生成成本仅为四分之一。

## 并行渲染

### Worker 架构

```python
hw = detect_hardware()
N_WORKERS = hw["workers"]

# Batch splitting (for non-clip architectures)
batch_size = (n_frames + N_WORKERS - 1) // N_WORKERS
batches = [(i, i*batch_size, min((i+1)*batch_size, n_frames), features, seg_path) ...]

with multiprocessing.Pool(N_WORKERS) as pool:
    segments = pool.starmap(render_batch, batches)
```

### 逐 Clip 并行（分段视频的首选方案）

```python
from concurrent.futures import ProcessPoolExecutor, as_completed

with ProcessPoolExecutor(max_workers=N_WORKERS) as pool:
    futures = {pool.submit(render_clip, seg, features, path): seg["id"]
               for seg, path in clip_args}
    for fut in as_completed(futures):
        clip_id = futures[fut]
        try:
            fut.result()
            log(f"  {clip_id} done")
        except Exception as e:
            log(f"  {clip_id} FAILED: {e}")
```

### Worker 隔离

每个 worker：
- 创建自己的 `Renderer` 实例（包含完整网格与位图初始化）
- 打开自己的 ffmpeg 子进程
- 拥有独立的随机种子（`random.seed(batch_id * 10000)`）
- 写入自己的 segment 文件和 stderr 日志

### ffmpeg 管道安全

**至关重要**：对于长时间运行的 ffmpeg，切勿使用 `stderr=subprocess.PIPE`。stderr 缓冲区在约 64KB 时填满并导致死锁：

```python
# WRONG -- will deadlock
pipe = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

# RIGHT -- stderr to file
stderr_fh = open(err_path, "w")
pipe = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=stderr_fh)
# ... write all frames ...
pipe.stdin.close()
pipe.wait()
stderr_fh.close()
```

### 拼接

```python
with open(concat_file, "w") as cf:
    for seg in segments:
        cf.write(f"file '{seg}'\n")

cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file]
if audio_path:
    cmd += ["-i", audio_path, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest"]
else:
    cmd += ["-c:v", "copy"]
cmd.append(output_path)
subprocess.run(cmd, capture_output=True, check=True)
```

## 粒子系统性能

根据质量配置限制粒子数量：

| 系统 | 低 | 标准 | 高 |
|--------|-----|----------|------|
| 爆炸 | 300 | 1000 | 2500 |
| 余烬 | 500 | 1500 | 3000 |
| 星空 | 300 | 800 | 1500 |
| 溶解 | 200 | 600 | 1200 |

通过截断列表来剔除粒子：
```python
MAX_PARTICLES = profile.get("particles_max", 1200)
if len(S["px"]) > MAX_PARTICLES:
    for k in ("px", "py", "vx", "vy", "life", "char"):
        S[k] = S[k][-MAX_PARTICLES:]  # keep newest
```

## 内存管理

- 特征数组：为所有帧预计算，通过 fork 语义（COW）在 workers 间共享
- Canvas：每个 worker 仅分配一次并复用（`np.zeros(...)`）
- 字符数组：每帧分配（成本较低——rows*cols 个 U1 字符串）
- 位图缓存：每种网格大小约 500KB，每个 worker 初始化一次

每个 worker 的总内存：约 50-150MB。8 个 workers 合计：约 400-800MB。

对于低内存系统（< 4GB），请减少 worker 数量并使用更小的网格。

## 亮度验证

渲染完成后，在样本时间戳抽查亮度：

```python
for t in [2, 30, 60, 120, 180]:
    cmd = ["ffmpeg", "-ss", str(t), "-i", output_path,
           "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    r = subprocess.run(cmd, capture_output=True)
    arr = np.frombuffer(r.stdout, dtype=np.uint8)
    print(f"t={t}s  mean={arr.mean():.1f}  max={arr.max()}")
```

目标：安静片段的均值 > 5，活跃片段的均值 > 15。如果始终低于目标，请提高 effects 中的亮度下限和/或全局 boost 乘数。

## 渲染时间估算

耗时随硬件而变化。基准：1080p、24fps、约 180ms/帧/worker。

| 时长 | 帧数 | 4 个 workers | 8 个 workers | 16 个 workers |
|----------|--------|-----------|-----------|------------|
| 30s | 720 | ~3 分钟 | ~2 分钟 | ~1 分钟 |
| 2 分钟 | 2,880 | ~13 分钟 | ~7 分钟 | ~4 分钟 |
| 3.5 分钟 | 5,040 | ~23 分钟 | ~12 分钟 | ~6 分钟 |
| 5 分钟 | 7,200 | ~33 分钟 | ~17 分钟 | ~9 分钟 |
| 10 分钟 | 14,400 | ~65 分钟 | ~33 分钟 | ~17 分钟 |

在 720p 下：耗时乘以约 0.5。在 4K 下：耗时乘以约 4。

更重的 effects（大量粒子、密集网格、额外 shader passes）会增加约 20-50% 的耗时。

---

## 临时文件清理

渲染会生成中间文件，这些文件会在多次运行中不断累积。请在最终 concat/mux 步骤后清理。

### 需要清理的文件

| 文件类型 | 来源 | 位置 |
|-----------|--------|----------|
| WAV 提取文件 | `ffmpeg -i input.mp3 ... tmp.wav` | `tempfile.mktemp()` 或项目目录 |
| Segment clips | `render_clip()` 输出 | `segments/seg_00.mp4` 等 |
| Concat 列表 | ffmpeg concat demuxer 输入 | `segments/concat.txt` |
| ffmpeg stderr 日志 | 为调试而通过管道写入文件 | 项目目录中的 `*.log` |
| 特征缓存 | pickle 化的 NumPy 数组 | `*.pkl` 或 `*.npz` |

### 清理函数

```python
import glob
import tempfile
import shutil

def cleanup_render_artifacts(segments_dir="segments", keep_final=True):
    """Remove intermediate files after successful render.
    
    Call this AFTER verifying the final output exists and plays correctly.
    
    Args:
        segments_dir: directory containing segment clips and concat list
        keep_final: if True, only delete intermediates (not the final output)
    """
    removed = []
    
    # 1. Segment clips
    if os.path.isdir(segments_dir):
        shutil.rmtree(segments_dir)
        removed.append(f"directory: {segments_dir}")
    
    # 2. Temporary WAV files
    for wav in glob.glob("*.wav"):
        if wav.startswith("tmp") or wav.startswith("extracted_"):
            os.remove(wav)
            removed.append(wav)
    
    # 3. ffmpeg stderr logs
    for log in glob.glob("ffmpeg_*.log"):
        os.remove(log)
        removed.append(log)
    
    # 4. Feature cache (optional — useful to keep for re-renders)
    # for cache in glob.glob("features_*.npz"):
    #     os.remove(cache)
    #     removed.append(cache)
    
    print(f"Cleaned {len(removed)} artifacts: {removed}")
    return removed
```

### 与渲染 Pipeline 集成

在最终输出通过验证后，于主渲染脚本末尾调用清理函数：

```python
# At end of main()
if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
    cleanup_render_artifacts(segments_dir="segments")
    print(f"Done. Output: {output_path}")
else:
    print("WARNING: final output missing or empty — skipping cleanup")
```

### 临时文件最佳实践

- 使用 `tempfile.mkdtemp()` 创建 segment 目录——避免污染项目目录
- 使用 `tempfile.mktemp(suffix=".wav")` 命名 WAV 提取文件，使其位于 OS 临时目录中
- 调试时设置 `KEEP_INTERMEDIATES=1` 环境变量以跳过清理
- 特征缓存（`.npz`）存储成本低、重新计算成本高——默认保留
