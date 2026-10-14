# 场景系统与创意构图

> **另请参阅：** architecture.md · composition.md · effects.md · shaders.md

## 场景设计理念

场景是叙事单元，而不是效果演示。每个场景都需要：
- 一个**概念**——视觉上正在发生什么？不是“等离子 + 圆环”，而是“从虚空中涌现”或“结晶”
- 一条**弧线**——场景在持续期间如何变化？积蓄、衰减、变形，还是揭示？
- 一个**角色**——它如何服务于整段视频的叙事？营造开场张力、抵达能量巅峰，还是完成收束？

下文的设计模式提供构图技巧。场景示例按复杂度递增，展示这些技巧的实际运用。协议部分则介绍技术契约。

优秀的场景设计始于概念，再选择为其服务的效果与参数。设计模式部分展示*如何*有意识地组合图层。示例部分提供各复杂度层级的完整可运行场景。协议部分则说明所有场景都必须遵循的技术契约。

---

## 场景设计模式

用于构建具有明确意图、而非随机拼凑感的场景的高阶模式。这些模式使用现有构件（值场、混合模式、着色器、反馈），但以构图意图将它们组织起来。

## 图层层级

每个场景都应具有角色分明的清晰视觉图层：

| 图层 | 网格 | 亮度 | 用途 |
|------|------|------|------|
| **背景** | xs 或 sm（密集） | 0.1–0.25 | 营造氛围与纹理，绝不与主体争夺注意力。 |
| **主体** | md（均衡） | 0.4–0.8 | 核心视觉创意，承载场景概念。 |
| **强调** | lg 或 sm（稀疏） | 0.5–1.0（稀疏覆盖） | 高光、视觉标点和稀疏的亮点。 |

背景奠定情绪。主体图层表达场景*究竟在讲什么*。强调图层则增添视觉趣味，又不喧宾夺主。

```python
def fx_example(r, f, t, S):
    local = t
    progress = min(local / 5.0, 1.0)

    g_bg = r.get_grid("sm")
    g_main = r.get_grid("md")
    g_accent = r.get_grid("lg")

    # --- Background: dim atmosphere ---
    bg_val = vf_smooth_noise(g_bg, f, t * 0.3, S, octaves=2, bri=0.15)
    # ... render bg to canvas

    # --- Content: the main visual idea ---
    content_val = vf_spiral(g_main, f, t, S, n_arms=n_arms, tightness=tightness)
    # ... render content on top of canvas

    # --- Accent: sparse highlights ---
    accent_val = vf_noise_static(g_accent, f, t, S, density=0.05)
    # ... render accent on top

    return canvas
```

## 定向参数弧线

参数应在场景持续期间*朝某个方向发展*，而不是用 `sin(t * N)` 漫无目的地振荡。

**反例：** `twist = 3.0 + 2.0 * math.sin(t * 0.6)`——来回摆动，显得毫无方向。

**正例：** `twist = 2.0 + progress * 5.0`——起初柔和，最终强烈。场景在不断*积蓄*。

使用 `progress = min(local / duration, 1.0)`（在整个场景中从 0→1）驱动定向变化：

| 模式 | 公式 | 感受 |
|------|------|------|
| 线性爬升 | `progress * range` | 稳定积蓄 |
| 缓出 | `1 - (1 - progress) ** 2` | 起步迅速，收尾柔和 |
| 缓入 | `progress ** 2` | 起步缓慢，逐渐加速 |
| 阶跃揭示 | `np.clip((progress - 0.5) / 0.25, 0, 1)` | 前 50% 不出现，随后淡入 |
| 积蓄 + 平台 | `min(1.0, progress * 1.5)` | 67% 时达到全强度并保持 |

振荡很适合*次要*参数（饱和度闪烁、色相漂移），但定义场景的*核心*参数应具有明确方向。

### 定向弧线示例

| 场景概念 | 参数 | 弧线 |
|---------|------|------|
| 涌现 | 圆环半径 | 0 → 最大值（缓出） |
| 破碎 | Voronoi 单元数量 | 8 → 38（线性） |
| 下坠 | 隧道速度 | 2.0 → 10.0（线性） |
| 曼陀罗 | 形状复杂度 | 圆环 → +多边形 → +星形 → +玫瑰线（阶跃揭示） |
| 渐强 | 图层数量 | 1 → 7（错峰进入） |
| 熵增 | 几何图形可见度 | 1.0 → 0.0（被吞噬） |

## 场景概念

每个场景都应围绕一个*视觉创意*构建，而不是围绕某个效果名称。

**反例：** “fx_plasma_cascade”——以效果命名，没有概念。
**正例：** “fx_emergence”——一个光点扩展成一片场。名称直接说明了*会发生什么*。

优秀的场景概念具备：
1. 一个**视觉隐喻**（涌现、下坠、碰撞、熵增）
2. 一条**定向弧线**（事物从 A 变为 B，而不是反复振荡）
3. **有动机的图层选择**（每个图层都服务于概念）
4. **有动机的反馈**（变换方向与隐喻相匹配）

| 概念 | 隐喻 | 反馈变换 | 原因 |
|------|------|----------|------|
| 涌现 | 诞生、扩张 | 缩小 | 过去的帧向外扩张 |
| 下坠 | 坠落、加速 | 放大 | 过去的帧疾速冲向中心 |
| 炼狱 | 上升的火焰 | 上移 | 过去的帧随火焰一同上升 |
| 熵增 | 衰败、消解 | 无 | 干净且无残留——事物直接消失 |
| 渐强 | 累积 | 缩放 + hue_shift | 一切不断叠加并偏移 |

## 构图技巧

### 反向旋转的双系统

同一效果的两个实例沿相反方向旋转，会产生视觉干涉：

```python
# Primary spiral (clockwise)
s1_val = vf_spiral(g_main, f, t * 1.5, S, n_arms=n_arms_1, tightness=tightness_1)

# Counter-rotating spiral (counter-clockwise via negative time)
s2_val = vf_spiral(g_accent, f, -t * 1.2, S, n_arms=n_arms_2, tightness=tightness_2)

# Screen blend creates bright interference at crossing points
canvas = blend_canvas(canvas_with_s1, c2, "screen", 0.7)
```

适用于螺旋、涡流和圆环。反向旋转会产生持续变动的干涉图案。

### 波浪碰撞

两道波前从相反两侧汇聚，在碰撞点相遇：

```python
collision_phase = abs(progress - 0.5) * 2  # 1→0→1 (0 at collision)

# Wave A approaches from left
offset_a = (1 - progress) * g.cols * 0.4
wave_a = np.sin((g.cc + offset_a) * 0.08 + t * 2) * 0.5 + 0.5

# Wave B approaches from right
offset_b = -(1 - progress) * g.cols * 0.4
wave_b = np.sin((g.cc + offset_b) * 0.08 - t * 2) * 0.5 + 0.5

# Interference peaks at collision
combined = wave_a * 0.5 + wave_b * 0.5 + np.abs(wave_a - wave_b) * (1 - collision_phase) * 0.5
```

### 渐进式碎裂

Voronoi 的单元数量随时间增加，形成视觉上的碎裂效果：

```python
n_pts = int(8 + progress * 30)  # 8 cells → 38 cells
# Pre-generate enough points, slice to n_pts
px = base_x[:n_pts] + np.sin(t * 0.3 + np.arange(n_pts) * 0.7) * (3 + progress * 3)
```

边缘辉光的宽度也可随进度增加，以突出裂缝。

### 熵增／吞噬

整洁的几何图案逐渐被有机过程侵占：

```python
# Geometry fades out
geo_val = clean_pattern * max(0.05, 1.0 - progress * 0.9)

# Organic process grows in
rd_val = vf_reaction_diffusion(g, f, t, S) * min(1.0, progress * 1.5)

# Render geometry first, organic on top — organic consumes geometry
```

### 图层错峰进入（渐强）

图层逐一进入，不断积累，最终达到压倒性的密度：

```python
def layer_strength(enter_t, ramp=1.5):
    """0.0 until enter_t, ramps to 1.0 over ramp seconds."""
    return max(0.0, min(1.0, (local - enter_t) / ramp))

# Layer 1: always present
s1 = layer_strength(0.0)
# Layer 2: enters at 2s
s2 = layer_strength(2.0)
# Layer 3: enters at 4s
s3 = layer_strength(4.0)
# ... etc

# Each layer uses a different effect, grid, palette, and blend mode
# Screen blend between layers so they accumulate light
```

对于 15 秒的渐强段落，让 7 个图层每隔 2 秒进入一次，效果很好。使用不同的混合模式（大多数图层用 screen，增强能量用 add，最终的强光铺陈用 colordodge）。

## 场景编排

对于多场景作品集或视频：
- **相邻场景之间要变换情绪**——不要将两个平静场景紧挨着放置
- **随机化顺序**，而不是按类型分组——避免产生“效果演示”感
- **以最强的场景收尾**——使用渐强，或其他具有明确回报的场景
- **以高能量开场**——在前 2 秒抓住注意力

---

## 场景协议

场景是顶层创意单元。每个场景都是一段有时间边界的片段，拥有自己的效果函数、着色器链、反馈配置和色调映射 gamma。

### 场景协议（v2）

### 函数签名

```python
def fx_scene_name(r, f, t, S) -> canvas:
    """
    Args:
        r: Renderer instance — access multiple grids via r.get_grid("sm")
        f: dict of audio/video features, all values normalized to [0, 1]
        t: time in seconds — local to scene (0.0 at scene start)
        S: dict for persistent state (particles, rain columns, etc.)

    Returns:
        canvas: numpy uint8 array, shape (VH, VW, 3) — full pixel frame
    """
```

**局部时间约定：** 无论场景出现在时间轴的哪个位置，场景函数收到的 `t` 都从该场景第一帧的 0.0 开始。渲染循环会先减去场景开始时间，再调用函数：

```python
# In render_clip:
t_local = fi / FPS - scene_start
canvas = fx_fn(r, feat, t_local, S)
```

这样无需修改代码即可重新编排场景顺序。场景进度按如下方式计算：

```python
progress = min(t / scene_duration, 1.0)  # 0→1 over the scene
```

这取代了 v1 协议中场景返回 `(chars, colors)` 元组的方式。v2 协议让场景能够在内部完全控制多网格渲染和像素级合成。

### Renderer 类

```python
class Renderer:
    def __init__(self):
        self.grids = {}   # lazy-initialized grid cache
        self.g = None      # "active" grid (for backward compat)
        self.S = {}        # persistent state dict

    def get_grid(self, key):
        """Get or create a GridLayer by size key."""
        if key not in self.grids:
            sizes = {"xs": 8, "sm": 10, "md": 16, "lg": 20, "xl": 24, "xxl": 40}
            self.grids[key] = GridLayer(FONT_PATH, sizes[key])
        return self.grids[key]

    def set_grid(self, key):
        """Set active grid (legacy). Prefer get_grid() for multi-grid scenes."""
        self.g = self.get_grid(key)
        return self.g
```

**与 v1 的关键区别**：场景通过调用 `r.get_grid("sm")`、`r.get_grid("lg")` 等访问多个网格。每个网格都会延迟初始化并缓存。`set_grid()` 方法仍适用于单网格场景。

### 最小场景（单网格）

```python
def fx_simple_rings(r, f, t, S):
    """Single-grid scene: rings with distance-mapped hue."""
    canvas = _render_vf(r, "md",
        lambda g, f, t, S: vf_rings(g, f, t, S, n_base=8, spacing_base=3),
        hf_distance(0.3, 0.02), PAL_STARS, f, t, S, sat=0.85)
    return canvas
```

### 标准场景（双网格 + 混合）

```python
def fx_tunnel_ripple(r, f, t, S):
    """Two-grid scene: tunnel depth exclusion-blended with ripple."""
    canvas_a = _render_vf(r, "md",
        lambda g, f, t, S: vf_tunnel(g, f, t, S, speed=5.0, complexity=10) * 1.3,
        hf_distance(0.55, 0.02), PAL_GREEK, f, t, S, sat=0.7)

    canvas_b = _render_vf(r, "sm",
        lambda g, f, t, S: vf_ripple(g, f, t, S,
            sources=[(0.3,0.3), (0.7,0.7), (0.5,0.2)], freq=0.5, damping=0.012) * 1.4,
        hf_angle(0.1), PAL_STARS, f, t, S, sat=0.8)

    return blend_canvas(canvas_a, canvas_b, "exclusion", 0.8)
```

### 复杂场景（三网格 + 条件效果 + 自定义渲染）

```python
def fx_rings_explosion(r, f, t, S):
    """Three-grid scene with particles and conditional kaleidoscope."""
    # Layer 1: rings
    canvas_a = _render_vf(r, "sm",
        lambda g, f, t, S: vf_rings(g, f, t, S, n_base=10, spacing_base=2) * 1.4,
        lambda g, f, t, S: (g.angle / (2*np.pi) + t * 0.15) % 1.0,
        PAL_STARS, f, t, S, sat=0.9)

    # Layer 2: vortex on different grid
    canvas_b = _render_vf(r, "md",
        lambda g, f, t, S: vf_vortex(g, f, t, S, twist=6.0) * 1.2,
        hf_time_cycle(0.15), PAL_BLOCKS, f, t, S, sat=0.8)

    result = blend_canvas(canvas_b, canvas_a, "screen", 0.7)

    # Layer 3: particles (custom rendering, not _render_vf)
    g = r.get_grid("sm")
    if "px" not in S:
        S["px"], S["py"], S["vx"], S["vy"], S["life"], S["pch"] = (
            [], [], [], [], [], [])
    if f.get("beat", 0) > 0.5:
        chars = list("\u2605\u2736\u2733\u2738\u2726\u2728*+")
        for _ in range(int(80 + f.get("rms", 0.3) * 120)):
            ang = random.uniform(0, 2 * math.pi)
            sp = random.uniform(1, 10) * (0.5 + f.get("sub_r", 0.3) * 2)
            S["px"].append(float(g.cols // 2))
            S["py"].append(float(g.rows // 2))
            S["vx"].append(math.cos(ang) * sp * 2.5)
            S["vy"].append(math.sin(ang) * sp)
            S["life"].append(1.0)
            S["pch"].append(random.choice(chars))

    # Update + draw particles
    ch_p = np.full((g.rows, g.cols), " ", dtype="U1")
    co_p = np.zeros((g.rows, g.cols, 3), dtype=np.uint8)
    i = 0
    while i < len(S["px"]):
        S["px"][i] += S["vx"][i]; S["py"][i] += S["vy"][i]
        S["vy"][i] += 0.03; S["life"][i] -= 0.02
        if S["life"][i] <= 0:
            for k in ("px","py","vx","vy","life","pch"): S[k].pop(i)
        else:
            pr, pc = int(S["py"][i]), int(S["px"][i])
            if 0 <= pr < g.rows and 0 <= pc < g.cols:
                ch_p[pr, pc] = S["pch"][i]
                co_p[pr, pc] = hsv2rgb_scalar(
                    0.08 + (1-S["life"][i])*0.15, 0.95, S["life"][i])
            i += 1

    canvas_p = g.render(ch_p, co_p)
    result = blend_canvas(result, canvas_p, "add", 0.8)

    # Conditional kaleidoscope on strong beats
    if f.get("bdecay", 0) > 0.4:
        result = sh_kaleidoscope(result.copy(), folds=6)

    return result
```

### 使用自定义字符渲染的场景（Matrix 雨）

当你需要 `_render_vf()` 无法提供的逐单元格控制时：

```python
def fx_matrix_layered(r, f, t, S):
    """Matrix rain blended with tunnel — two grids, screen blend."""
    # Layer 1: Matrix rain (custom per-column rendering)
    g = r.get_grid("md")
    rows, cols = g.rows, g.cols
    pal = PAL_KATA

    if "ry" not in S or len(S["ry"]) != cols:
        S["ry"] = np.random.uniform(-rows, rows, cols).astype(np.float32)
        S["rsp"] = np.random.uniform(0.3, 2.0, cols).astype(np.float32)
        S["rln"] = np.random.randint(8, 35, cols)
        S["rch"] = np.random.randint(1, len(pal), (rows, cols))

    speed = 0.6 + f.get("bass", 0.3) * 3
    if f.get("beat", 0) > 0.5: speed *= 2.5
    S["ry"] += S["rsp"] * speed

    ch = np.full((rows, cols), " ", dtype="U1")
    co = np.zeros((rows, cols, 3), dtype=np.uint8)
    heads = S["ry"].astype(int)
    for c in range(cols):
        head = heads[c]
        for i in range(S["rln"][c]):
            row = head - i
            if 0 <= row < rows:
                fade = 1.0 - i / S["rln"][c]
                ch[row, c] = pal[S["rch"][row, c] % len(pal)]
                if i == 0:
                    v = int(min(255, fade * 300))
                    co[row, c] = (int(v*0.9), v, int(v*0.9))
                else:
                    v = int(fade * 240)
                    co[row, c] = (int(v*0.1), v, int(v*0.4))
    canvas_a = g.render(ch, co)

    # Layer 2: Tunnel on sm grid for depth texture
    canvas_b = _render_vf(r, "sm",
        lambda g, f, t, S: vf_tunnel(g, f, t, S, speed=5.0, complexity=10),
        hf_distance(0.3, 0.02), PAL_BLOCKS, f, t, S, sat=0.6)

    return blend_canvas(canvas_a, canvas_b, "screen", 0.5)
```

---

## 场景表

场景表定义时间轴：哪个场景在何时播放，以及使用什么配置。

### 结构

```python
SCENES = [
    {
        "start": 0.0,           # start time in seconds
        "end": 3.96,            # end time in seconds
        "name": "starfield",    # identifier (used for clip filenames)
        "grid": "sm",           # default grid (for render_clip setup)
        "fx": fx_starfield,     # scene function reference (must be module-level)
        "gamma": 0.75,          # tonemap gamma override (default 0.75)
        "shaders": [            # shader chain (applied after tonemap + feedback)
            ("bloom", {"thr": 120}),
            ("vignette", {"s": 0.2}),
            ("grain", {"amt": 8}),
        ],
        "feedback": None,       # feedback buffer config (None = disabled)
        # "feedback": {"decay": 0.8, "blend": "screen", "opacity": 0.3,
        #              "transform": "zoom", "transform_amt": 0.02, "hue_shift": 0.02},
    },
    {
        "start": 3.96,
        "end": 6.58,
        "name": "matrix_layered",
        "grid": "md",
        "fx": fx_matrix_layered,
        "shaders": [
            ("crt", {"strength": 0.05}),
            ("scanlines", {"intensity": 0.12}),
            ("color_grade", {"tint": (0.7, 1.2, 0.7)}),
            ("bloom", {"thr": 100}),
        ],
        "feedback": {"decay": 0.5, "blend": "add", "opacity": 0.2},
    },
    # ... more scenes ...
]
```

### 节拍同步的场景切换

从音频分析结果中推导切点：

```python
# Get beat timestamps
beats = [fi / FPS for fi in range(N_FRAMES) if features["beat"][fi] > 0.5]

# Group beats into phrase boundaries (every 4-8 beats)
cuts = [0.0]
for i in range(0, len(beats), 4):  # cut every 4 beats
    cuts.append(beats[i])
cuts.append(DURATION)

# Or use the music's structure: silence gaps, energy changes
energy = features["rms"]
# Find timestamps where energy drops significantly -> natural break points
```

### `render_clip()`——渲染循环

此函数将一个场景渲染为片段文件：

```python
def render_clip(seg, features, clip_path):
    r = Renderer()
    r.set_grid(seg["grid"])
    S = r.S
    random.seed(hash(seg["id"]) + 42)  # deterministic per scene

    # Build shader chain from config
    chain = ShaderChain()
    for shader_name, kwargs in seg.get("shaders", []):
        chain.add(shader_name, **kwargs)

    # Setup feedback buffer
    fb = None
    fb_cfg = seg.get("feedback", None)
    if fb_cfg:
        fb = FeedbackBuffer()

    fx_fn = seg["fx"]

    # Open ffmpeg pipe
    cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{VW}x{VH}", "-r", str(FPS), "-i", "pipe:0",
           "-c:v", "libx264", "-preset", "fast", "-crf", "20",
           "-pix_fmt", "yuv420p", clip_path]
    stderr_fh = open(clip_path.replace(".mp4", ".log"), "w")
    pipe = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=stderr_fh)

    for fi in range(seg["frame_start"], seg["frame_end"]):
        t = fi / FPS
        feat = {k: float(features[k][fi]) for k in features}

        # 1. Scene renders canvas
        canvas = fx_fn(r, feat, t, S)

        # 2. Tonemap normalizes brightness
        canvas = tonemap(canvas, gamma=seg.get("gamma", 0.75))

        # 3. Feedback adds temporal recursion
        if fb and fb_cfg:
            canvas = fb.apply(canvas, **{k: fb_cfg[k] for k in fb_cfg})

        # 4. Shader chain adds post-processing
        canvas = chain.apply(canvas, f=feat, t=t)

        pipe.stdin.write(canvas.tobytes())

    pipe.stdin.close(); pipe.wait(); stderr_fh.close()
```

### 从场景表构建片段

```python
segments = []
for i, scene in enumerate(SCENES):
    segments.append({
        "id": f"s{i:02d}_{scene['name']}",
        "name": scene["name"],
        "grid": scene["grid"],
        "fx": scene["fx"],
        "shaders": scene.get("shaders", []),
        "feedback": scene.get("feedback", None),
        "gamma": scene.get("gamma", 0.75),
        "frame_start": int(scene["start"] * FPS),
        "frame_end": int(scene["end"] * FPS),
    })
```

### 并行渲染

场景是彼此独立的单元，会被分派到进程池：

```python
from concurrent.futures import ProcessPoolExecutor, as_completed

with ProcessPoolExecutor(max_workers=N_WORKERS) as pool:
    futures = {
        pool.submit(render_clip, seg, features, clip_path): seg["id"]
        for seg, clip_path in zip(segments, clip_paths)
    }
    for fut in as_completed(futures):
        try:
            fut.result()
        except Exception as e:
            log(f"ERROR {futures[fut]}: {e}")
```

**Pickle 约束**：`ProcessPoolExecutor` 通过 pickle 序列化参数。模块级函数可以被 pickle；lambda 和闭包则不行。所有 `fx_*` 场景函数都必须在模块级定义，不能定义为闭包或类方法。

### 测试帧模式

在指定时间戳渲染单帧，无需完整渲染即可检查视觉效果：

```python
if args.test_frame >= 0:
    fi = min(int(args.test_frame * FPS), N_FRAMES - 1)
    t = fi / FPS
    feat = {k: float(features[k][fi]) for k in features}
    scene = next(sc for sc in reversed(SCENES) if t >= sc["start"])
    r = Renderer()
    r.set_grid(scene["grid"])
    canvas = scene["fx"](r, feat, t, r.S)
    canvas = tonemap(canvas, gamma=scene.get("gamma", 0.75))
    chain = ShaderChain()
    for sn, kw in scene.get("shaders", []):
        chain.add(sn, **kw)
    canvas = chain.apply(canvas, f=feat, t=t)
    Image.fromarray(canvas).save(f"test_{args.test_frame:.1f}s.png")
    print(f"Mean brightness: {canvas.astype(float).mean():.1f}")
```

CLI：`python reel.py --test-frame 10.0`

---

## 场景设计检查清单

对于每个场景：

1. **选择 2–3 种网格尺寸**——不同尺度会产生干涉
2. **为每个图层选择不同的值场**——不要在每个网格上使用同一效果
3. **为每个图层选择不同的色相场**——或者至少使用不同的色相偏移
4. **为每个图层选择不同的调色板**——PAL_RUNE 与 PAL_BLOCKS 的组合，和 PAL_RUNE 与 PAL_DENSE 的组合观感不同
5. **选择符合能量感的混合模式**——明亮效果用 screen，迷幻效果用 difference，细腻效果用 exclusion
6. **在节拍上加入条件效果**——万花筒、镜像、故障
7. **配置反馈以获得拖尾／递归观感**——若要干净切换则设为 None
8. **使用破坏性着色器（solarize、posterize）时设置 gamma**
9. **完整渲染前，在场景中点使用 --test-frame 进行测试**

---

## 场景示例

可直接复制粘贴的场景函数，复杂度逐级递增。每个函数都是完整、可运行的 v2 场景函数，并返回像素画布。场景协议参见上文“场景协议”部分，混合模式与色调映射参见 `composition.md`。

---

### 最小——单网格、单效果

### 呼吸式等离子

一个网格、一个值场、一个色相场。这是最简单的场景。

```python
def fx_breathing_plasma(r, f, t, S):
    """Plasma field with time-cycling hue. Audio modulates brightness."""
    canvas = _render_vf(r, "md",
        lambda g, f, t, S: vf_plasma(g, f, t, S) * 1.3,
        hf_time_cycle(0.08), PAL_DENSE, f, t, S, sat=0.8)
    return canvas
```

### 反应扩散珊瑚

单网格、基于模拟的场。随时间有机演化。

```python
def fx_coral(r, f, t, S):
    """Gray-Scott reaction-diffusion — coral branching pattern.
    Slow-evolving, organic. Best for ambient/chill sections."""
    canvas = _render_vf(r, "sm",
        lambda g, f, t, S: vf_reaction_diffusion(g, f, t, S,
            feed=0.037, kill=0.060, steps_per_frame=6, init_mode="center"),
        hf_distance(0.55, 0.015), PAL_DOTS, f, t, S, sat=0.7)
    return canvas
```

### SDF 几何图形

由 SDF 构成的几何形状，整洁、精确，具有鲜明的图形感。

```python
def fx_sdf_rings(r, f, t, S):
    """Concentric SDF rings with smooth pulsing."""
    def val_fn(g, f, t, S):
        d1 = sdf_ring(g, radius=0.15 + f.get("bass", 0.3) * 0.05, thickness=0.015)
        d2 = sdf_ring(g, radius=0.25 + f.get("mid", 0.3) * 0.05, thickness=0.012)
        d3 = sdf_ring(g, radius=0.35 + f.get("hi", 0.3) * 0.04, thickness=0.010)
        combined = sdf_smooth_union(sdf_smooth_union(d1, d2, 0.05), d3, 0.05)
        return sdf_glow(combined, falloff=0.08) * (0.5 + f.get("rms", 0.3) * 0.8)
    canvas = _render_vf(r, "md", val_fn, hf_angle(0.0), PAL_STARS, f, t, S, sat=0.85)
    return canvas
```

---

### 标准——双网格 + 混合

### 穿越噪声的隧道

两个密度不同的网格，通过 screen 混合。细腻的噪声纹理会从较粗的隧道字符间透出。

```python
def fx_tunnel_noise(r, f, t, S):
    """Tunnel depth on md grid + fBM noise on sm grid, screen blended."""
    canvas_a = _render_vf(r, "md",
        lambda g, f, t, S: vf_tunnel(g, f, t, S, speed=4.0, complexity=8) * 1.2,
        hf_distance(0.5, 0.02), PAL_BLOCKS, f, t, S, sat=0.7)

    canvas_b = _render_vf(r, "sm",
        lambda g, f, t, S: vf_fbm(g, f, t, S, octaves=4, freq=0.05, speed=0.15) * 1.3,
        hf_time_cycle(0.06), PAL_RUNE, f, t, S, sat=0.6)

    return blend_canvas(canvas_a, canvas_b, "screen", 0.7)
```

### Voronoi 单元 + 螺旋叠加层

Voronoi 单元边缘上叠加螺旋臂图案。

```python
def fx_voronoi_spiral(r, f, t, S):
    """Voronoi edge detection on md + logarithmic spiral on lg."""
    canvas_a = _render_vf(r, "md",
        lambda g, f, t, S: vf_voronoi(g, f, t, S,
            n_cells=15, mode="edge", edge_width=2.0, speed=0.4),
        hf_angle(0.2), PAL_CIRCUIT, f, t, S, sat=0.75)

    canvas_b = _render_vf(r, "lg",
        lambda g, f, t, S: vf_spiral(g, f, t, S, n_arms=4, tightness=3.0) * 1.2,
        hf_distance(0.1, 0.03), PAL_BLOCKS, f, t, S, sat=0.9)

    return blend_canvas(canvas_a, canvas_b, "exclusion", 0.6)
```

### 域扭曲 fBM

同一 fBM 的两个图层，其中一个经过域扭曲，再以 difference 混合，生成迷幻的有机纹理。

```python
def fx_organic_warp(r, f, t, S):
    """Clean fBM vs domain-warped fBM, difference blended."""
    canvas_a = _render_vf(r, "sm",
        lambda g, f, t, S: vf_fbm(g, f, t, S, octaves=5, freq=0.04, speed=0.1),
        hf_plasma(0.2), PAL_DENSE, f, t, S, sat=0.6)

    canvas_b = _render_vf(r, "md",
        lambda g, f, t, S: vf_domain_warp(g, f, t, S,
            warp_strength=20.0, freq=0.05, speed=0.15),
        hf_time_cycle(0.05), PAL_BRAILLE, f, t, S, sat=0.7)

    return blend_canvas(canvas_a, canvas_b, "difference", 0.7)
```

---

### 复杂——三网格 + 条件效果 + 反馈

### 迷幻大教堂

三网格构图，配合节拍触发的万花筒效果和反馈缩放隧道。这是视觉上最复杂的模式。

```python
def fx_cathedral(r, f, t, S):
    """Three-layer cathedral: interference + rings + noise, kaleidoscope on beat,
    feedback zoom tunnel."""
    # Layer 1: interference pattern on sm grid
    canvas_a = _render_vf(r, "sm",
        lambda g, f, t, S: vf_interference(g, f, t, S, n_waves=7) * 1.3,
        hf_angle(0.0), PAL_MATH, f, t, S, sat=0.8)

    # Layer 2: pulsing rings on md grid
    canvas_b = _render_vf(r, "md",
        lambda g, f, t, S: vf_rings(g, f, t, S, n_base=10, spacing_base=3) * 1.4,
        hf_distance(0.3, 0.02), PAL_STARS, f, t, S, sat=0.9)

    # Layer 3: temporal noise on lg grid (slow morph)
    canvas_c = _render_vf(r, "lg",
        lambda g, f, t, S: vf_temporal_noise(g, f, t, S,
            freq=0.04, t_freq=0.2, octaves=3),
        hf_time_cycle(0.12), PAL_BLOCKS, f, t, S, sat=0.7)

    # Blend: A screen B, then difference with C
    result = blend_canvas(canvas_a, canvas_b, "screen", 0.8)
    result = blend_canvas(result, canvas_c, "difference", 0.5)

    # Beat-triggered kaleidoscope
    if f.get("bdecay", 0) > 0.3:
        folds = 6 if f.get("sub_r", 0.3) > 0.4 else 8
        result = sh_kaleidoscope(result.copy(), folds=folds)

    return result

# Scene table entry with feedback:
# {"start": 30.0, "end": 50.0, "name": "cathedral", "fx": fx_cathedral,
#  "gamma": 0.65, "shaders": [("bloom", {"thr": 110}), ("chromatic", {"amt": 4}),
#                              ("vignette", {"s": 0.2}), ("grain", {"amt": 8})],
#  "feedback": {"decay": 0.75, "blend": "screen", "opacity": 0.35,
#               "transform": "zoom", "transform_amt": 0.012, "hue_shift": 0.015}}
```

### 带吸引子叠加层的蒙版反应扩散

反应扩散仅透过动态虹膜蒙版可见，其下方铺有奇异吸引子密度场。

```python
def fx_masked_life(r, f, t, S):
    """Attractor base + reaction-diffusion visible through iris mask + particles."""
    g_sm = r.get_grid("sm")
    g_md = r.get_grid("md")

    # Layer 1: strange attractor density field (background)
    canvas_bg = _render_vf(r, "sm",
        lambda g, f, t, S: vf_strange_attractor(g, f, t, S,
            attractor="clifford", n_points=30000),
        hf_time_cycle(0.04), PAL_DOTS, f, t, S, sat=0.5)

    # Layer 2: reaction-diffusion (foreground, will be masked)
    canvas_rd = _render_vf(r, "md",
        lambda g, f, t, S: vf_reaction_diffusion(g, f, t, S,
            feed=0.046, kill=0.063, steps_per_frame=4, init_mode="ring"),
        hf_angle(0.15), PAL_HALFFILL, f, t, S, sat=0.85)

    # Animated iris mask — opens over first 5 seconds of scene
    scene_start = S.get("_scene_start", t)
    if "_scene_start" not in S:
        S["_scene_start"] = t
    mask = mask_iris(g_md, t, scene_start, scene_start + 5.0,
                     max_radius=0.6)
    canvas_rd = apply_mask_canvas(canvas_rd, mask, bg_canvas=canvas_bg)

    # Layer 3: flow-field particles following the R-D gradient
    rd_field = vf_reaction_diffusion(g_sm, f, t, S,
        feed=0.046, kill=0.063, steps_per_frame=0)  # read without stepping
    ch_p, co_p = update_flow_particles(S, g_sm, f, rd_field,
        n=300, speed=0.8, char_set=list("·•◦∘°"))
    canvas_p = g_sm.render(ch_p, co_p)

    result = blend_canvas(canvas_rd, canvas_p, "add", 0.7)
    return result
```

### 使用缓动关键帧的场变形序列

演示时间连贯性：通过关键帧参数在多种效果之间平滑变形。

```python
def fx_morphing_journey(r, f, t, S):
    """Morphs through 4 value fields over 20 seconds with eased transitions.
    Parameters (twist, arm count) also keyframed."""
    # Keyframed twist parameter
    twist = keyframe(t, [(0, 1.0), (5, 5.0), (10, 2.0), (15, 8.0), (20, 1.0)],
                     ease_fn=ease_in_out_cubic, loop=True)

    # Sequence of value fields with 2s crossfade
    fields = [
        lambda g, f, t, S: vf_plasma(g, f, t, S),
        lambda g, f, t, S: vf_vortex(g, f, t, S, twist=twist),
        lambda g, f, t, S: vf_fbm(g, f, t, S, octaves=5, freq=0.04),
        lambda g, f, t, S: vf_domain_warp(g, f, t, S, warp_strength=15),
    ]
    durations = [5.0, 5.0, 5.0, 5.0]

    val_fn = lambda g, f, t, S: vf_sequence(g, f, t, S, fields, durations,
                                             crossfade=2.0)

    # Render with slowly rotating hue
    canvas = _render_vf(r, "md", val_fn, hf_time_cycle(0.06),
                        PAL_DENSE, f, t, S, sat=0.8)

    # Second layer: tiled version of same sequence at smaller grid
    tiled_fn = lambda g, f, t, S: vf_sequence(
        make_tgrid(g, *uv_tile(g, 3, 3, mirror=True)),
        f, t, S, fields, durations, crossfade=2.0)
    canvas_b = _render_vf(r, "sm", tiled_fn, hf_angle(0.1),
                          PAL_RUNE, f, t, S, sat=0.6)

    return blend_canvas(canvas, canvas_b, "screen", 0.5)
```

---

### 特殊——独特的状态模式

### 带幽灵拖尾的生命游戏

带有模拟渐隐拖尾的元胞自动机。节拍会注入随机单元格。

```python
def fx_life(r, f, t, S):
    """Conway's Game of Life with fading ghost trails.
    Beat events inject random live cells for disruption."""
    canvas = _render_vf(r, "sm",
        lambda g, f, t, S: vf_game_of_life(g, f, t, S,
            rule="life", steps_per_frame=1, fade=0.92, density=0.25),
        hf_fixed(0.33), PAL_BLOCKS, f, t, S, sat=0.8)

    # Overlay: coral automaton on lg grid for chunky texture
    canvas_b = _render_vf(r, "lg",
        lambda g, f, t, S: vf_game_of_life(g, f, t, S,
            rule="coral", steps_per_frame=1, fade=0.85, density=0.15, seed=99),
        hf_time_cycle(0.1), PAL_HATCH, f, t, S, sat=0.6)

    return blend_canvas(canvas, canvas_b, "screen", 0.5)
```

### Voronoi 上的 Boids 鸟群

在元胞背景上涌现的集群运动。

```python
def fx_boid_swarm(r, f, t, S):
    """Flocking boids over animated voronoi cells."""
    # Background: voronoi cells
    canvas_bg = _render_vf(r, "md",
        lambda g, f, t, S: vf_voronoi(g, f, t, S,
            n_cells=20, mode="distance", speed=0.2),
        hf_distance(0.4, 0.02), PAL_CIRCUIT, f, t, S, sat=0.5)

    # Foreground: boids
    g = r.get_grid("md")
    ch_b, co_b = update_boids(S, g, f, n_boids=150, perception=6.0,
                              max_speed=1.5, char_set=list("▸▹►▻→⟶"))
    canvas_boids = g.render(ch_b, co_b)

    # Trails for the boids
    # (boid positions are stored in S["boid_x"], S["boid_y"])
    S["px"] = list(S.get("boid_x", []))
    S["py"] = list(S.get("boid_y", []))
    ch_t, co_t = draw_particle_trails(S, g, max_trail=6, fade=0.6)
    canvas_trails = g.render(ch_t, co_t)

    result = blend_canvas(canvas_bg, canvas_trails, "add", 0.3)
    result = blend_canvas(result, canvas_boids, "add", 0.9)
    return result
```

### 穿过 SDF 文字模板上升的火焰

仅透过文字字形可见的火焰效果。

```python
def fx_fire_text(r, f, t, S):
    """Fire columns visible through text stencil. Text acts as window."""
    g = r.get_grid("lg")

    # Full-screen fire (will be masked)
    canvas_fire = _render_vf(r, "sm",
        lambda g, f, t, S: np.clip(
            vf_fbm(g, f, t, S, octaves=4, freq=0.08, speed=0.8) *
            (1.0 - g.rr / g.rows) *  # fade toward top
            (0.6 + f.get("bass", 0.3) * 0.8), 0, 1),
        hf_fixed(0.05), PAL_BLOCKS, f, t, S, sat=0.9)  # fire hue

    # Background: dark domain warp
    canvas_bg = _render_vf(r, "md",
        lambda g, f, t, S: vf_domain_warp(g, f, t, S,
            warp_strength=8, freq=0.03, speed=0.05) * 0.3,
        hf_fixed(0.6), PAL_DENSE, f, t, S, sat=0.4)

    # Text stencil mask
    mask = mask_text(g, "FIRE", row_frac=0.45)
    # Expand vertically for multi-row coverage
    for offset in range(-2, 3):
        shifted = mask_text(g, "FIRE", row_frac=0.45 + offset / g.rows)
        mask = mask_union(mask, shifted)

    canvas_masked = apply_mask_canvas(canvas_fire, mask, bg_canvas=canvas_bg)
    return canvas_masked
```

### 竖屏模式：垂直雨幕 + 引语

针对 9:16 优化。利用垂直空间呈现长雨迹和堆叠文字。

```python
def fx_portrait_rain_quote(r, f, t, S):
    """Portrait-optimized: matrix rain (long vertical trails) with stacked quote.
    Designed for 1080x1920 (9:16)."""
    g = r.get_grid("md")  # ~112x100 in portrait

    # Matrix rain — long trails benefit from portrait's extra rows
    ch, co, S = eff_matrix_rain(g, f, t, S,
        hue=0.33, bri=0.6, pal=PAL_KATA, speed_base=0.4, speed_beat=2.5)
    canvas_rain = g.render(ch, co)

    # Tunnel depth underneath for texture
    canvas_tunnel = _render_vf(r, "sm",
        lambda g, f, t, S: vf_tunnel(g, f, t, S, speed=3.0, complexity=6) * 0.8,
        hf_fixed(0.33), PAL_BLOCKS, f, t, S, sat=0.5)

    result = blend_canvas(canvas_tunnel, canvas_rain, "screen", 0.8)

    # Quote text — portrait layout: short lines, many of them
    g_text = r.get_grid("lg")  # ~90x80 in portrait
    quote_lines = layout_text_portrait(
        "The code is the art and the art is the code",
        max_chars_per_line=20)
    # Center vertically
    block_start = (g_text.rows - len(quote_lines)) // 2
    ch_t = np.full((g_text.rows, g_text.cols), " ", dtype="U1")
    co_t = np.zeros((g_text.rows, g_text.cols, 3), dtype=np.uint8)
    total_chars = sum(len(l) for l in quote_lines)
    progress = min(1.0, (t - S.get("_scene_start", t)) / 3.0)
    if "_scene_start" not in S: S["_scene_start"] = t
    render_typewriter(ch_t, co_t, quote_lines, block_start, g_text.cols,
                      progress, total_chars, (200, 255, 220), t)
    canvas_text = g_text.render(ch_t, co_t)

    result = blend_canvas(result, canvas_text, "add", 0.9)
    return result
```

---

### 场景表模板

将场景串接成完整视频：

```python
SCENES = [
    {"start": 0.0,  "end": 5.0,  "name": "coral",
     "fx": fx_coral, "grid": "sm", "gamma": 0.70,
     "shaders": [("bloom", {"thr": 110}), ("vignette", {"s": 0.2})],
     "feedback": {"decay": 0.8, "blend": "screen", "opacity": 0.3,
                  "transform": "zoom", "transform_amt": 0.01}},

    {"start": 5.0,  "end": 15.0, "name": "tunnel_noise",
     "fx": fx_tunnel_noise, "grid": "md", "gamma": 0.75,
     "shaders": [("chromatic", {"amt": 3}), ("bloom", {"thr": 120}),
                 ("scanlines", {"intensity": 0.06}), ("grain", {"amt": 8})],
     "feedback": None},

    {"start": 15.0, "end": 35.0, "name": "cathedral",
     "fx": fx_cathedral, "grid": "sm", "gamma": 0.65,
     "shaders": [("bloom", {"thr": 100}), ("chromatic", {"amt": 5}),
                 ("color_wobble", {"amt": 0.2}), ("vignette", {"s": 0.18})],
     "feedback": {"decay": 0.75, "blend": "screen", "opacity": 0.35,
                  "transform": "zoom", "transform_amt": 0.012, "hue_shift": 0.015}},

    {"start": 35.0, "end": 50.0, "name": "morphing",
     "fx": fx_morphing_journey, "grid": "md", "gamma": 0.70,
     "shaders": [("bloom", {"thr": 110}), ("grain", {"amt": 6})],
     "feedback": {"decay": 0.7, "blend": "screen", "opacity": 0.25,
                  "transform": "rotate_cw", "transform_amt": 0.003}},
]
```
