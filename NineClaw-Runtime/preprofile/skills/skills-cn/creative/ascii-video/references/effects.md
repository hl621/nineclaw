# Effect 目录

用于生成视觉图案的 Effect 构件。在 v2 中，这些构件用在**场景函数内部**，场景函数会直接返回像素画布。下列构件作用于网格坐标数组，并生成 `(chars, colors)` 或明度/色相场，再由场景函数通过 `_render_vf()` 将其渲染到画布。

> **另请参阅：** architecture.md · composition.md · scenes.md · shaders.md · troubleshooting.md

## 设计理念

Effects 是创意核心。不要在每个项目中原样照搬这些内容——应把它们用作**构件**，并**组合、修改和创造**新的效果。每个项目都应呈现独特的观感。

核心原则：
- **叠加多个 effects**，而不是使用单个大而全的函数
- **一切皆参数化**——色相、速度、密度和振幅都应作为参数
- **响应特征**——音频/视频特征应为每种 effect 调制至少 2–3 个参数
- **逐段变化**——切勿让整段视频始终使用同一套 effect 配置
- **创造项目专属 effects**——下方目录只是一套起始词汇，而非固定集合

---

## 背景填充

每种 effect 都应从背景开始。绝不要留下单调的纯黑画面。

### 动态正弦场（通用）
```python
def bg_sinefield(g, f, t, hue=0.6, bri=0.5, pal=PAL_DEFAULT,
                 freq=(0.13, 0.17, 0.07, 0.09), speed=(0.5, -0.4, -0.3, 0.2)):
    """Layered sine field. Adjust freq/speed tuples for different textures."""
    v1 = np.sin(g.cc*freq[0] + t*speed[0]) * np.sin(g.rr*freq[1] - t*speed[1]) * 0.5 + 0.5
    v2 = np.sin(g.cc*freq[2] - t*speed[2] + g.rr*freq[3]) * 0.4 + 0.5
    v3 = np.sin(g.dist_n*5 + t*0.2) * 0.3 + 0.4
    v4 = np.cos(g.angle*3 - t*0.6) * 0.15 + 0.5
    val = np.clip((v1*0.3 + v2*0.25 + v3*0.25 + v4*0.2) * bri * (0.6 + f["rms"]*0.6), 0.06, 1)
    mask = val > 0.03
    ch = val2char(val, mask, pal)
    h = np.full_like(val, hue) + f.get("cent", 0.5)*0.1 + val*0.08
    R, G, B = hsv2rgb(h, np.clip(0.35+f.get("flat",0.4)*0.4, 0, 1) * np.ones_like(val), val)
    return ch, mkc(R, G, B, g.rows, g.cols)
```

### 视频源背景
```python
def bg_video(g, frame_rgb, pal=PAL_DEFAULT, brightness=0.5):
    small = np.array(Image.fromarray(frame_rgb).resize((g.cols, g.rows)))
    lum = np.mean(small, axis=2) / 255.0 * brightness
    mask = lum > 0.02
    ch = val2char(lum, mask, pal)
    co = np.clip(small * np.clip(lum[:,:,None]*1.5+0.3, 0.3, 1), 0, 255).astype(np.uint8)
    return ch, co
```

### 噪声 / 静态干扰场
```python
def bg_noise(g, f, t, pal=PAL_BLOCKS, density=0.3, hue_drift=0.02):
    val = np.random.random((g.rows, g.cols)).astype(np.float32) * density * (0.5 + f["rms"]*0.5)
    val = np.clip(val, 0, 1); mask = val > 0.02
    ch = val2char(val, mask, pal)
    R, G, B = hsv2rgb(np.full_like(val, t*hue_drift % 1), np.full_like(val, 0.3), val)
    return ch, mkc(R, G, B, g.rows, g.cols)
```

### 类 Perlin 平滑噪声
```python
def bg_smooth_noise(g, f, t, hue=0.5, bri=0.5, pal=PAL_DOTS, octaves=3):
    """Layered sine approximation of Perlin noise. Cheap, smooth, organic."""
    val = np.zeros((g.rows, g.cols), dtype=np.float32)
    for i in range(octaves):
        freq = 0.05 * (2 ** i)
        amp = 0.5 / (i + 1)
        phase = t * (0.3 + i * 0.2)
        val += np.sin(g.cc * freq + phase) * np.cos(g.rr * freq * 0.7 - phase * 0.5) * amp
    val = np.clip(val * 0.5 + 0.5, 0, 1) * bri
    mask = val > 0.03
    ch = val2char(val, mask, pal)
    h = np.full_like(val, hue) + val * 0.1
    R, G, B = hsv2rgb(h, np.full_like(val, 0.5), val)
    return ch, mkc(R, G, B, g.rows, g.cols)
```

### 元胞 / Voronoi 近似
```python
def bg_cellular(g, f, t, n_centers=12, hue=0.5, bri=0.6, pal=PAL_BLOCKS):
    """Voronoi-like cells using distance to nearest of N moving centers."""
    rng = np.random.RandomState(42)  # deterministic centers
    cx = (rng.rand(n_centers) * g.cols).astype(np.float32)
    cy = (rng.rand(n_centers) * g.rows).astype(np.float32)
    # Animate centers
    cx_t = cx + np.sin(t * 0.5 + np.arange(n_centers) * 0.7) * 5
    cy_t = cy + np.cos(t * 0.4 + np.arange(n_centers) * 0.9) * 3
    # Min distance to any center
    min_d = np.full((g.rows, g.cols), 999.0, dtype=np.float32)
    for i in range(n_centers):
        d = np.sqrt((g.cc - cx_t[i])**2 + (g.rr - cy_t[i])**2)
        min_d = np.minimum(min_d, d)
    val = np.clip(1.0 - min_d / (g.cols * 0.3), 0, 1) * bri
    # Cell edges (where distance is near-equal between two centers)
    # ... second-nearest trick for edge highlighting
    mask = val > 0.03
    ch = val2char(val, mask, pal)
    R, G, B = hsv2rgb(np.full_like(val, hue) + min_d * 0.005, np.full_like(val, 0.5), val)
    return ch, mkc(R, G, B, g.rows, g.cols)
```

---

> **注意：** v1 的 `eff_rings`、`eff_rays`、`eff_spiral`、`eff_glow`、`eff_tunnel`、`eff_vortex`、`eff_freq_waves`、`eff_interference`、`eff_aurora` 和 `eff_ripple` 函数，已由下方的 `vf_*` 值场生成器取代（通过 `_render_vf()` 使用）。`vf_*` 版本可与多网格 compositing 流水线集成，是所有新场景的首选。

---

## 粒子系统

### 通用模式
所有粒子系统都通过 `S` 字典参数使用持久状态：
```python
# S is the persistent state dict (same as r.S, passed explicitly)
if "px" not in S:
    S["px"]=[]; S["py"]=[]; S["vx"]=[]; S["vy"]=[]; S["life"]=[]; S["char"]=[]

# Emit new particles (on beat, continuously, or on trigger)
# Update: position += velocity, apply forces, decay life
# Draw: map to grid, set char/color based on life
# Cull: remove dead, cap total count
```

### 粒子字符集

不要硬编码粒子字符。应根据项目/氛围进行选择：

```python
# Energy / explosive
PART_ENERGY  = list("*+#@\u26a1\u2726\u2605\u2588\u2593")
PART_SPARK   = list("\u00b7\u2022\u25cf\u2605\u2736*+")
# Organic / natural
PART_LEAF    = list("\u2740\u2741\u2742\u2743\u273f\u2618\u2022")
PART_SNOW    = list("\u2744\u2745\u2746\u00b7\u2022*\u25cb")
PART_RAIN    = list("|\u2502\u2503\u2551/\\")
PART_BUBBLE  = list("\u25cb\u25ce\u25c9\u25cf\u2218\u2219\u00b0")
# Data / tech
PART_DATA    = list("01{}[]<>|/\\")
PART_HEX     = list("0123456789ABCDEF")
PART_BINARY  = list("01")
# Mystical
PART_RUNE    = list("\u16a0\u16a2\u16a6\u16b1\u16b7\u16c1\u16c7\u16d2\u16d6\u16da\u16de\u16df\u2726\u2605")
PART_ZODIAC  = list("\u2648\u2649\u264a\u264b\u264c\u264d\u264e\u264f\u2650\u2651\u2652\u2653")
# Minimal
PART_DOT     = list("\u00b7\u2022\u25cf")
PART_DASH    = list("-=~\u2500\u2550")
```

### 爆炸（节拍触发）
```python
def emit_explosion(S, f, center_r, center_c, char_set=PART_ENERGY, count_base=80):
    if f.get("beat", 0) > 0:
        for _ in range(int(count_base + f["rms"]*150)):
            ang = random.uniform(0, 2*math.pi)
            sp = random.uniform(1, 9) * (0.5 + f.get("sub_r", 0.3)*2)
            S["px"].append(float(center_c))
            S["py"].append(float(center_r))
            S["vx"].append(math.cos(ang)*sp*2.5)
            S["vy"].append(math.sin(ang)*sp)
            S["life"].append(1.0)
            S["char"].append(random.choice(char_set))
# Update: gravity on vy += 0.03, life -= 0.015
# Color: life * 255 for brightness, hue fade controlled by caller
```

### 上升余烬
```python
# Emit: sy = rows-1, vy = -random.uniform(1,5), vx = random.uniform(-1.5,1.5)
# Update: vx += random jitter * 0.3, life -= 0.01
# Cap at ~1500 particles
```

### 消散云团
```python
# Init: N=600 particles spread across screen
# Update: slow upward drift, fade life progressively
# life -= 0.002 * (1 + elapsed * 0.05)  # accelerating fade
```

### 星空（3D 投影）
```python
# N stars with (sx, sy, sz) in normalized coords
# Move: sz -= speed (stars approach camera)
# Project: px = cx + sx/sz * cx, py = cy + sy/sz * cy
# Reset stars that pass camera (sz <= 0.01)
# Brightness = (1 - sz), draw streaks behind bright stars
```

### 轨道（圆周/椭圆运动）
```python
def emit_orbit(S, n=20, radius=15, speed=1.0, char_set=PART_DOT):
    """Particles orbiting a center point."""
    for i in range(n):
        angle = i * 2 * math.pi / n
        S["px"].append(0.0); S["py"].append(0.0)  # will be computed from angle
        S["vx"].append(angle)  # store angle as "vx" for orbit
        S["vy"].append(radius + random.uniform(-2, 2))  # store radius
        S["life"].append(1.0)
        S["char"].append(random.choice(char_set))
# Update: angle += speed * dt, px = cx + radius * cos(angle), py = cy + radius * sin(angle)
```

### 引力阱
```python
# Particles attracted toward one or more gravity points
# Update: compute force vector toward each well, apply as acceleration
# Particles that reach well center respawn at edges
```

### 集群 / Boids

由三条简单规则涌现出的群集行为：分离、对齐、聚合。

```python
def update_boids(S, g, f, n_boids=200, perception=8.0, max_speed=2.0,
                 sep_weight=1.5, ali_weight=1.0, coh_weight=1.0,
                 char_set=None):
    """Boids flocking simulation. Particles self-organize into organic groups.

    perception: how far each boid can see (grid cells)
    sep_weight: separation (avoid crowding) strength
    ali_weight: alignment (match neighbor velocity) strength
    coh_weight: cohesion (steer toward group center) strength
    """
    if char_set is None:
        char_set = list("·•●◦∘⬤")
    if "boid_x" not in S:
        rng = np.random.RandomState(42)
        S["boid_x"] = rng.uniform(0, g.cols, n_boids).astype(np.float32)
        S["boid_y"] = rng.uniform(0, g.rows, n_boids).astype(np.float32)
        S["boid_vx"] = (rng.random(n_boids).astype(np.float32) - 0.5) * max_speed
        S["boid_vy"] = (rng.random(n_boids).astype(np.float32) - 0.5) * max_speed
        S["boid_ch"] = [random.choice(char_set) for _ in range(n_boids)]

    bx = S["boid_x"]; by = S["boid_y"]
    bvx = S["boid_vx"]; bvy = S["boid_vy"]
    n = len(bx)

    # For each boid, compute steering forces
    ax = np.zeros(n, dtype=np.float32)
    ay = np.zeros(n, dtype=np.float32)

    # Spatial hash for efficient neighbor lookup
    cell_size = perception
    cells = {}
    for i in range(n):
        cx_i = int(bx[i] / cell_size)
        cy_i = int(by[i] / cell_size)
        key = (cx_i, cy_i)
        if key not in cells:
            cells[key] = []
        cells[key].append(i)

    for i in range(n):
        cx_i = int(bx[i] / cell_size)
        cy_i = int(by[i] / cell_size)
        sep_x, sep_y = 0.0, 0.0
        ali_x, ali_y = 0.0, 0.0
        coh_x, coh_y = 0.0, 0.0
        count = 0

        # Check neighboring cells
        for dcx in range(-1, 2):
            for dcy in range(-1, 2):
                for j in cells.get((cx_i + dcx, cy_i + dcy), []):
                    if j == i:
                        continue
                    dx = bx[j] - bx[i]
                    dy = by[j] - by[i]
                    dist = np.sqrt(dx * dx + dy * dy)
                    if dist < perception and dist > 0.01:
                        count += 1
                        # Separation: steer away from close neighbors
                        if dist < perception * 0.4:
                            sep_x -= dx / (dist * dist)
                            sep_y -= dy / (dist * dist)
                        # Alignment: match velocity
                        ali_x += bvx[j]
                        ali_y += bvy[j]
                        # Cohesion: steer toward center of group
                        coh_x += bx[j]
                        coh_y += by[j]

        if count > 0:
            # Normalize and weight
            ax[i] += sep_x * sep_weight
            ay[i] += sep_y * sep_weight
            ax[i] += (ali_x / count - bvx[i]) * ali_weight * 0.1
            ay[i] += (ali_y / count - bvy[i]) * ali_weight * 0.1
            ax[i] += (coh_x / count - bx[i]) * coh_weight * 0.01
            ay[i] += (coh_y / count - by[i]) * coh_weight * 0.01

    # Audio reactivity: bass pushes boids outward from center
    if f.get("bass", 0) > 0.5:
        cx_g, cy_g = g.cols / 2, g.rows / 2
        dx = bx - cx_g; dy = by - cy_g
        dist = np.sqrt(dx**2 + dy**2) + 1
        ax += (dx / dist) * f["bass"] * 2
        ay += (dy / dist) * f["bass"] * 2

    # Update velocity and position
    bvx += ax; bvy += ay
    # Clamp speed
    speed = np.sqrt(bvx**2 + bvy**2) + 1e-10
    over = speed > max_speed
    bvx[over] *= max_speed / speed[over]
    bvy[over] *= max_speed / speed[over]
    bx += bvx; by += bvy

    # Wrap at edges
    bx %= g.cols; by %= g.rows

    S["boid_x"] = bx; S["boid_y"] = by
    S["boid_vx"] = bvx; S["boid_vy"] = bvy

    # Draw
    ch = np.full((g.rows, g.cols), " ", dtype="U1")
    co = np.zeros((g.rows, g.cols, 3), dtype=np.uint8)
    for i in range(n):
        r, c = int(by[i]) % g.rows, int(bx[i]) % g.cols
        ch[r, c] = S["boid_ch"][i]
        spd = min(1.0, speed[i] / max_speed)
        R, G, B = hsv2rgb_scalar(spd * 0.3, 0.8, 0.5 + spd * 0.5)
        co[r, c] = (R, G, B)
    return ch, co
```

### 流场粒子

沿值场梯度运动的粒子。任何 `vf_*` 函数都能化作承载粒子的“河流”：

```python
def update_flow_particles(S, g, f, flow_field, n=500, speed=1.0,
                          life_drain=0.005, emit_rate=10,
                          char_set=None):
    """Particles steered by a value field gradient.

    flow_field: float32 (rows, cols) — the field particles follow.
                Particles flow from low to high values (uphill) or along
                the gradient direction.
    """
    if char_set is None:
        char_set = list("·•∘◦°⋅")
    if "fp_x" not in S:
        S["fp_x"] = []; S["fp_y"] = []; S["fp_vx"] = []; S["fp_vy"] = []
        S["fp_life"] = []; S["fp_ch"] = []

    # Emit new particles at random positions
    for _ in range(emit_rate):
        if len(S["fp_x"]) < n:
            S["fp_x"].append(random.uniform(0, g.cols - 1))
            S["fp_y"].append(random.uniform(0, g.rows - 1))
            S["fp_vx"].append(0.0); S["fp_vy"].append(0.0)
            S["fp_life"].append(1.0)
            S["fp_ch"].append(random.choice(char_set))

    # Compute gradient of flow field (central differences)
    pad = np.pad(flow_field, 1, mode="wrap")
    grad_x = (pad[1:-1, 2:] - pad[1:-1, :-2]) * 0.5
    grad_y = (pad[2:, 1:-1] - pad[:-2, 1:-1]) * 0.5

    # Update particles
    i = 0
    while i < len(S["fp_x"]):
        px, py = S["fp_x"][i], S["fp_y"][i]
        # Sample gradient at particle position
        gc = int(px) % g.cols; gr = int(py) % g.rows
        gx = grad_x[gr, gc]; gy = grad_y[gr, gc]
        # Steer velocity toward gradient direction
        S["fp_vx"][i] = S["fp_vx"][i] * 0.9 + gx * speed * 10
        S["fp_vy"][i] = S["fp_vy"][i] * 0.9 + gy * speed * 10
        S["fp_x"][i] += S["fp_vx"][i]
        S["fp_y"][i] += S["fp_vy"][i]
        S["fp_life"][i] -= life_drain

        if S["fp_life"][i] <= 0:
            for k in ("fp_x", "fp_y", "fp_vx", "fp_vy", "fp_life", "fp_ch"):
                S[k].pop(i)
        else:
            i += 1

    # Draw
    ch = np.full((g.rows, g.cols), " ", dtype="U1")
    co = np.zeros((g.rows, g.cols, 3), dtype=np.uint8)
    for i in range(len(S["fp_x"])):
        r = int(S["fp_y"][i]) % g.rows
        c = int(S["fp_x"][i]) % g.cols
        ch[r, c] = S["fp_ch"][i]
        v = S["fp_life"][i]
        co[r, c] = (int(v * 200), int(v * 180), int(v * 255))
    return ch, co
```

### 粒子拖尾

在当前位置与先前位置之间绘制渐隐线条：

```python
def draw_particle_trails(S, g, trail_key="trails", max_trail=8, fade=0.7):
    """Add trails to any particle system. Call after updating positions.
    Stores previous positions in S[trail_key] and draws fading lines.

    Expects S to have 'px', 'py' lists (standard particle keys).
    max_trail: number of previous positions to remember
    fade: brightness multiplier per trail step (0.7 = 70% each step back)
    """
    if trail_key not in S:
        S[trail_key] = []

    # Store current positions
    current = list(zip(
        [int(y) for y in S.get("py", [])],
        [int(x) for x in S.get("px", [])]
    ))
    S[trail_key].append(current)
    if len(S[trail_key]) > max_trail:
        S[trail_key] = S[trail_key][-max_trail:]

    # Draw trails onto char/color arrays
    ch = np.full((g.rows, g.cols), " ", dtype="U1")
    co = np.zeros((g.rows, g.cols, 3), dtype=np.uint8)
    trail_chars = list("·∘◦°⋅.,'`")

    for age, positions in enumerate(reversed(S[trail_key])):
        bri = fade ** age
        if bri < 0.05:
            break
        ci = min(age, len(trail_chars) - 1)
        for r, c in positions:
            if 0 <= r < g.rows and 0 <= c < g.cols and ch[r, c] == " ":
                ch[r, c] = trail_chars[ci]
                v = int(bri * 180)
                co[r, c] = (v, v, int(v * 0.8))
    return ch, co
```

---

## 雨幕 / Matrix Effects

### 列式雨幕（向量化）
```python
def eff_matrix_rain(g, f, t, S, hue=0.33, bri=0.6, pal=PAL_KATA,
                    speed_base=0.5, speed_beat=3.0):
    """Vectorized matrix rain. S dict persists column positions."""
    if "ry" not in S or len(S["ry"]) != g.cols:
        S["ry"] = np.random.uniform(-g.rows, g.rows, g.cols).astype(np.float32)
        S["rsp"] = np.random.uniform(0.3, 2.0, g.cols).astype(np.float32)
        S["rln"] = np.random.randint(8, 40, g.cols)
        S["rch"] = np.random.randint(0, len(pal), (g.rows, g.cols))  # pre-assign chars

    speed_mult = speed_base + f.get("bass", 0.3)*speed_beat + f.get("sub_r", 0.3)*3
    if f.get("beat", 0) > 0: speed_mult *= 2.5
    S["ry"] += S["rsp"] * speed_mult

    # Reset columns that fall past bottom
    rst = (S["ry"] - S["rln"]) > g.rows
    S["ry"][rst] = np.random.uniform(-25, -2, rst.sum())

    # Vectorized draw using fancy indexing
    ch = np.full((g.rows, g.cols), " ", dtype="U1")
    co = np.zeros((g.rows, g.cols, 3), dtype=np.uint8)
    heads = S["ry"].astype(int)
    for c in range(g.cols):
        head = heads[c]
        trail_len = S["rln"][c]
        for i in range(trail_len):
            row = head - i
            if 0 <= row < g.rows:
                fade = 1.0 - i / trail_len
                ci = S["rch"][row, c] % len(pal)
                ch[row, c] = pal[ci]
                v = fade * bri * 255
                if i == 0:  # head is bright white-ish
                    co[row, c] = (int(v*0.9), int(min(255, v*1.1)), int(v*0.9))
                else:
                    R, G, B = hsv2rgb_single(hue, 0.7, fade * bri)
                    co[row, c] = (R, G, B)
    return ch, co, S
```

---

## Glitch / 数据 Effects

### 水平条带位移
```python
def eff_glitch_displace(ch, co, f, intensity=1.0):
    n_bands = int(8 + f.get("flux", 0.3)*25 + f.get("bdecay", 0)*15) * intensity
    for _ in range(int(n_bands)):
        y = random.randint(0, ch.shape[0]-1)
        h = random.randint(1, int(3 + f.get("sub", 0.3)*8))
        shift = int((random.random()-0.5) * f.get("rms", 0.3)*40 + f.get("bdecay", 0)*20*(random.random()-0.5))
        if shift != 0:
            for row in range(h):
                rr = y + row
                if 0 <= rr < ch.shape[0]:
                    ch[rr] = np.roll(ch[rr], shift)
                    co[rr] = np.roll(co[rr], shift, axis=0)
    return ch, co
```

### 块状损坏
```python
def eff_block_corrupt(ch, co, f, char_pool=None, count_base=20):
    if char_pool is None:
        char_pool = list(PAL_BLOCKS[4:] + PAL_KATA[2:8])
    for _ in range(int(count_base + f.get("flux", 0.3)*60 + f.get("bdecay", 0)*40)):
        bx = random.randint(0, max(1, ch.shape[1]-6))
        by = random.randint(0, max(1, ch.shape[0]-4))
        bw, bh = random.randint(2,6), random.randint(1,4)
        block_char = random.choice(char_pool)
        # Fill rectangle with single char and random color
        for r in range(bh):
            for c in range(bw):
                rr, cc = by+r, bx+c
                if 0 <= rr < ch.shape[0] and 0 <= cc < ch.shape[1]:
                    ch[rr, cc] = block_char
                    co[rr, cc] = (random.randint(100,255), random.randint(0,100), random.randint(0,80))
    return ch, co
```

### 扫描条（垂直）
```python
def eff_scanbars(ch, co, f, t, n_base=4, chars="|\u2551|!1l"):
    for bi in range(int(n_base + f.get("himid_r", 0.3)*12)):
        sx = int((t*50*(1+bi*0.3) + bi*37) % ch.shape[1])
        for rr in range(ch.shape[0]):
            if random.random() < 0.7:
                ch[rr, sx] = random.choice(chars)
    return ch, co
```

### 错误消息
```python
# Parameterize the error vocabulary per project:
ERRORS_TECH = ["SEGFAULT","0xDEADBEEF","BUFFER_OVERRUN","PANIC!","NULL_PTR",
               "CORRUPT","SIGSEGV","ERR_OVERFLOW","STACK_SMASH","BAD_ALLOC"]
ERRORS_COSMIC = ["VOID_BREACH","ENTROPY_MAX","SINGULARITY","DIMENSION_FAULT",
                 "REALITY_ERR","TIME_PARADOX","DARK_MATTER_LEAK","QUANTUM_DECOHERE"]
ERRORS_ORGANIC = ["CELL_DIVISION_ERR","DNA_MISMATCH","MUTATION_OVERFLOW",
                  "NEURAL_DEADLOCK","SYNAPSE_TIMEOUT","MEMBRANE_BREACH"]
```

### 十六进制数据流
```python
hex_str = "".join(random.choice("0123456789ABCDEF") for _ in range(random.randint(8,20)))
stamp(ch, co, hex_str, rand_row, rand_col, (0, 160, 80))
```

---

## 频谱 / 可视化

### 镜像频谱条
```python
def eff_spectrum(g, f, t, n_bars=64, pal=PAL_BLOCKS, mirror=True):
    bar_w = max(1, g.cols // n_bars); mid = g.rows // 2
    band_vals = np.array([f.get("sub",0.3), f.get("bass",0.3), f.get("lomid",0.3),
                          f.get("mid",0.3), f.get("himid",0.3), f.get("hi",0.3)])
    ch = np.full((g.rows, g.cols), " ", dtype="U1")
    co = np.zeros((g.rows, g.cols, 3), dtype=np.uint8)
    for b in range(n_bars):
        frac = b / n_bars
        fi = frac * 5; lo_i = int(fi); hi_i = min(lo_i+1, 5)
        bval = min(1, (band_vals[lo_i]*(1-fi%1) + band_vals[hi_i]*(fi%1)) * 1.8)
        height = int(bval * (g.rows//2 - 2))
        for dy in range(height):
            hue = (f.get("cent",0.5)*0.3 + frac*0.3 + dy/max(height,1)*0.15) % 1.0
            ci = pal[min(int(dy/max(height,1)*len(pal)*0.7+len(pal)*0.2), len(pal)-1)]
            for dc in range(bar_w - (1 if bar_w > 2 else 0)):
                cc = b*bar_w + dc
                if 0 <= cc < g.cols:
                    rows_to_draw = [mid - dy, mid + dy] if mirror else [g.rows - 1 - dy]
                    for row in rows_to_draw:
                        if 0 <= row < g.rows:
                            ch[row, cc] = ci
                            co[row, cc] = hsv_to_rgb_single(hue, 0.85, 0.5+dy/max(height,1)*0.5)
    return ch, co
```

### 波形
```python
def eff_waveform(g, f, t, row_offset=-5, hue=0.1):
    ch = np.full((g.rows, g.cols), " ", dtype="U1")
    co = np.zeros((g.rows, g.cols, 3), dtype=np.uint8)
    for c in range(g.cols):
        wv = (math.sin(c*0.15+t*5)*f.get("bass",0.3)*0.5
            + math.sin(c*0.3+t*8)*f.get("mid",0.3)*0.3
            + math.sin(c*0.6+t*12)*f.get("hi",0.3)*0.15)
        wr = g.rows + row_offset + int(wv * 4)
        if 0 <= wr < g.rows:
            ch[wr, c] = "~"
            v = int(120 + f.get("rms",0.3)*135)
            co[wr, c] = [v, int(v*0.7), int(v*0.4)]
    return ch, co
```

---

## 火焰 / 熔岩

### 火焰柱
```python
def eff_fire(g, f, t, n_base=20, hue_base=0.02, hue_range=0.12, pal=PAL_BLOCKS):
    n_cols = int(n_base + f.get("bass",0.3)*30 + f.get("sub_r",0.3)*20)
    ch = np.full((g.rows, g.cols), " ", dtype="U1")
    co = np.zeros((g.rows, g.cols, 3), dtype=np.uint8)
    for fi in range(n_cols):
        fx_c = int((fi*g.cols/n_cols + np.sin(t*2+fi*0.7)*3) % g.cols)
        height = int((f.get("bass",0.3)*0.4 + f.get("sub_r",0.3)*0.3 + f.get("rms",0.3)*0.3) * g.rows * 0.7)
        for dy in range(min(height, g.rows)):
            fr = g.rows - 1 - dy
            frac = dy / max(height, 1)
            bri = max(0.1, (1 - frac*0.6) * (0.5 + f.get("rms",0.3)*0.5))
            hue = hue_base + frac * hue_range
            ci = "\u2588" if frac<0.2 else ("\u2593" if frac<0.4 else ("\u2592" if frac<0.6 else "\u2591"))
            ch[fr, fx_c] = ci
            R, G, B = hsv2rgb_single(hue, 0.9, bri)
            co[fr, fx_c] = (R, G, B)
    return ch, co
```

### 冰焰 / 冷焰（结构相同，色相范围不同）
```python
# hue_base=0.55, hue_range=0.15 -- blue to cyan
# Lower intensity, slower movement
```

---

## 文本叠加层

### 滚动字幕
```python
def eff_ticker(ch, co, t, text, row, speed=15, color=(80, 100, 140)):
    off = int(t * speed) % max(len(text), 1)
    doubled = text + "   " + text
    stamp(ch, co, doubled[off:off+ch.shape[1]], row, 0, color)
```

### 节拍触发词语
```python
def eff_beat_words(ch, co, f, words, row_center=None, color=(255,240,220)):
    if f.get("beat", 0) > 0:
        w = random.choice(words)
        r = (row_center or ch.shape[0]//2) + random.randint(-5,5)
        stamp(ch, co, w, r, (ch.shape[1]-len(w))//2, color)
```

### 渐隐消息序列
```python
def eff_fading_messages(ch, co, t, elapsed, messages, period=4.0, color_base=(220,220,220)):
    msg_idx = int(elapsed / period) % len(messages)
    phase = elapsed % period
    fade = max(0, min(1.0, phase) * min(1.0, period - phase))
    if fade > 0.05:
        v = fade
        msg = messages[msg_idx]
        cr, cg, cb = [int(c * v) for c in color_base]
        stamp(ch, co, msg, ch.shape[0]//2, (ch.shape[1]-len(msg))//2, (cr, cg, cb))
```

---

## 画面震动
随节拍整体平移字符/颜色数组：
```python
def eff_shake(ch, co, f, x_amp=6, y_amp=3):
    shake_x = int(f.get("sub",0.3)*x_amp*(random.random()-0.5)*2 + f.get("bdecay",0)*4*(random.random()-0.5)*2)
    shake_y = int(f.get("bass",0.3)*y_amp*(random.random()-0.5)*2)
    if abs(shake_x) > 0:
        ch = np.roll(ch, shake_x, axis=1)
        co = np.roll(co, shake_x, axis=1)
    if abs(shake_y) > 0:
        ch = np.roll(ch, shake_y, axis=0)
        co = np.roll(co, shake_y, axis=0)
    return ch, co
```

---

## 可组合 Effect 系统

真正的创作能力来自**组合**。组合分为三个层级：

### 第 1 级：字符级分层

将多个 effects 堆叠为 `(chars, colors)` 图层：

```python
class LayerStack(EffectNode):
    """Render effects bottom-to-top with character-level compositing."""
    def add(self, effect, alpha=1.0):
        """alpha < 1.0 = probabilistic override (sparse overlay)."""
        self.layers.append((effect, alpha))

# Usage:
stack = LayerStack()
stack.add(bg_effect)           # base — fills screen
stack.add(main_effect)         # overlay on top (space chars = transparent)
stack.add(particle_effect)     # sparse overlay on top of that
ch, co = stack.render(g, f, t, S)
```

### 第 2 级：像素级混合

渲染到画布后，使用 Photoshop 风格的模式进行混合：

```python
class PixelBlendStack:
    """Stack canvases with blend modes for complex compositing."""
    def add(self, canvas, mode="normal", opacity=1.0)
    def composite(self) -> canvas

# Usage:
pbs = PixelBlendStack()
pbs.add(canvas_a)                        # base
pbs.add(canvas_b, "screen", 0.7)        # additive glow
pbs.add(canvas_c, "difference", 0.5)    # psychedelic interference
result = pbs.composite()
```

### 第 3 级：时间反馈

将上一帧反馈至当前帧，以形成递归 effects：

```python
fb = FeedbackBuffer()
for each frame:
    canvas = render_current()
    canvas = fb.apply(canvas, decay=0.8, blend="screen",
                      transform="zoom", transform_amt=0.015, hue_shift=0.02)
```

### Effect 节点——统一接口

在 v2 协议中，effect 节点用在场景函数**内部**，场景函数本身返回画布。Effect 节点生成中间结果 `(chars, colors)`，再通过网格的 `.render()` 方法或 `_render_vf()` 渲染到画布。

```python
class EffectNode:
    def render(self, g, f, t, S) -> (chars, colors)

# Concrete implementations:
class ValueFieldEffect(EffectNode):
    """Wraps a value field function + hue field function + palette."""
    def __init__(self, val_fn, hue_fn, pal=PAL_DEFAULT, sat=0.7)

class LambdaEffect(EffectNode):
    """Wrap any (g,f,t,S) -> (ch,co) function."""
    def __init__(self, fn)

class ConditionalEffect(EffectNode):
    """Switch effects based on audio features."""
    def __init__(self, condition, if_true, if_false=None)
```

### 值场生成器（原子构件）

这些生成取值范围为 [0,1] 的 float32 数组 `(rows, cols)`，即原始视觉图案。它们的签名均为 `(g, f, t, S, **params) -> float32 array`。

#### 三角函数场（基于正弦/余弦）

```python
def vf_sinefield(g, f, t, S, bri=0.5,
                 freq=(0.13, 0.17, 0.07, 0.09), speed=(0.5, -0.4, -0.3, 0.2)):
    """Layered sine field. General purpose background/texture."""
    v1 = np.sin(g.cc*freq[0] + t*speed[0]) * np.sin(g.rr*freq[1] - t*speed[1]) * 0.5 + 0.5
    v2 = np.sin(g.cc*freq[2] - t*speed[2] + g.rr*freq[3]) * 0.4 + 0.5
    v3 = np.sin(g.dist_n*5 + t*0.2) * 0.3 + 0.4
    return np.clip((v1*0.35 + v2*0.35 + v3*0.3) * bri * (0.6 + f.get("rms",0.3)*0.6), 0, 1)

def vf_smooth_noise(g, f, t, S, octaves=3, bri=0.5):
    """Multi-octave sine approximation of Perlin noise."""
    val = np.zeros((g.rows, g.cols), dtype=np.float32)
    for i in range(octaves):
        freq = 0.05 * (2 ** i); amp = 0.5 / (i + 1)
        phase = t * (0.3 + i * 0.2)
        val = val + np.sin(g.cc*freq + phase) * np.cos(g.rr*freq*0.7 - phase*0.5) * amp
    return np.clip(val * 0.5 + 0.5, 0, 1) * bri

def vf_rings(g, f, t, S, n_base=6, spacing_base=4):
    """Concentric rings, bass-driven count and wobble."""
    n = int(n_base + f.get("sub_r",0.3)*25 + f.get("bass",0.3)*10)
    sp = spacing_base + f.get("bass_r",0.3)*7 + f.get("rms",0.3)*3
    val = np.zeros((g.rows, g.cols), dtype=np.float32)
    for ri in range(n):
        rad = (ri+1)*sp + f.get("bdecay",0)*15
        wobble = f.get("mid_r",0.3)*5*np.sin(g.angle*3+t*4)
        rd = np.abs(g.dist - rad - wobble)
        th = 1 + f.get("sub",0.3)*3
        val = np.maximum(val, np.clip((1 - rd/th) * (0.4 + f.get("bass",0.3)*0.8), 0, 1))
    return val

def vf_spiral(g, f, t, S, n_arms=3, tightness=2.5):
    """Logarithmic spiral arms."""
    val = np.zeros((g.rows, g.cols), dtype=np.float32)
    for ai in range(n_arms):
        offset = ai * 2*np.pi / n_arms
        log_r = np.log(g.dist + 1) * tightness
        arm_phase = g.angle + offset - log_r + t * 0.8
        arm_val = np.clip(np.cos(arm_phase * n_arms) * 0.6 + 0.2, 0, 1)
        arm_val *= (0.4 + f.get("rms",0.3)*0.6) * np.clip(1 - g.dist_n*0.5, 0.2, 1)
        val = np.maximum(val, arm_val)
    return val

def vf_tunnel(g, f, t, S, speed=3.0, complexity=6):
    """Tunnel depth effect — infinite zoom feeling."""
    tunnel_d = 1.0 / (g.dist_n + 0.1)
    v1 = np.sin(tunnel_d*2 - t*speed) * 0.45 + 0.55
    v2 = np.sin(g.angle*complexity + tunnel_d*1.5 - t*2) * 0.35 + 0.55
    return np.clip(v1*0.5 + v2*0.5, 0, 1)

def vf_vortex(g, f, t, S, twist=3.0):
    """Twisting radial pattern — distance modulates angle."""
    twisted = g.angle + g.dist_n * twist * np.sin(t * 0.5)
    val = np.sin(twisted * 4 - t * 2) * 0.5 + 0.5
    return np.clip(val * (0.5 + f.get("bass",0.3)*0.8), 0, 1)

def vf_interference(g, f, t, S, n_waves=6):
    """Overlapping sine waves creating moire patterns."""
    drivers = ["mid_r", "himid_r", "bass_r", "lomid_r", "hi_r", "sub_r"]
    vals = np.zeros((g.rows, g.cols), dtype=np.float32)
    for i in range(min(n_waves, len(drivers))):
        angle = i * np.pi / n_waves
        freq = 0.06 + i * 0.03; sp = 0.5 + i * 0.3
        proj = g.cc * np.cos(angle) + g.rr * np.sin(angle)
        vals = vals + np.sin(proj*freq + t*sp) * f.get(drivers[i], 0.3) * 2.5
    return np.clip(vals * 0.12 + 0.45, 0.1, 1)

def vf_aurora(g, f, t, S, n_bands=3):
    """Horizontal aurora bands."""
    val = np.zeros((g.rows, g.cols), dtype=np.float32)
    for i in range(n_bands):
        fr = 0.08 + i*0.04; fc = 0.012 + i*0.008
        sr = 0.7 + i*0.3; sc = 0.18 + i*0.12
        val = val + np.sin(g.rr*fr + t*sr) * np.sin(g.cc*fc + t*sc) * (0.6/n_bands)
    return np.clip(val * (f.get("lomid_r",0.3)*3 + 0.2), 0, 0.7)

def vf_ripple(g, f, t, S, sources=None, freq=0.3, damping=0.02):
    """Concentric ripples from point sources."""
    if sources is None: sources = [(0.5, 0.5)]
    val = np.zeros((g.rows, g.cols), dtype=np.float32)
    for ry, rx in sources:
        dy = g.rr - g.rows*ry; dx = g.cc - g.cols*rx
        d = np.sqrt(dy**2 + dx**2)
        val = val + np.sin(d*freq - t*4) * np.exp(-d*damping) * 0.5
    return np.clip(val + 0.5, 0, 1)

def vf_plasma(g, f, t, S):
    """Classic plasma: sum of sines at different orientations and speeds."""
    v = np.sin(g.cc * 0.03 + t * 0.7) * 0.5
    v = v + np.sin(g.rr * 0.04 - t * 0.5) * 0.4
    v = v + np.sin((g.cc * 0.02 + g.rr * 0.03) + t * 0.3) * 0.3
    v = v + np.sin(g.dist_n * 4 - t * 0.8) * 0.3
    return np.clip(v * 0.5 + 0.5, 0, 1)

def vf_diamond(g, f, t, S, freq=0.15):
    """Diamond/checkerboard pattern."""
    val = np.abs(np.sin(g.cc * freq + t * 0.5)) * np.abs(np.sin(g.rr * freq * 1.2 - t * 0.3))
    return np.clip(val * (0.6 + f.get("rms",0.3)*0.8), 0, 1)

def vf_noise_static(g, f, t, S, density=0.4):
    """Random noise — different each frame. Non-deterministic."""
    return np.random.random((g.rows, g.cols)).astype(np.float32) * density * (0.5 + f.get("rms",0.3)*0.5)
```

#### 基于噪声的场（有机、非周期）

与基于正弦的场相比，它们会产生本质不同的纹理——有机、不重复，且不存在明显的轴向对齐。它们是高端生成艺术的基础。

```python
def _hash2d(ix, iy):
    """Integer-coordinate hash for gradient noise. Returns float32 in [0,1]."""
    # Good-quality hash via large prime mixing
    n = ix * 374761393 + iy * 668265263
    n = (n ^ (n >> 13)) * 1274126177
    return ((n ^ (n >> 16)) & 0x7fffffff).astype(np.float32) / 0x7fffffff

def _smoothstep(t):
    """Hermite smoothstep: 3t^2 - 2t^3. Smooth interpolation in [0,1]."""
    t = np.clip(t, 0, 1)
    return t * t * (3 - 2 * t)

def _smootherstep(t):
    """Perlin's improved smoothstep: 6t^5 - 15t^4 + 10t^3. C2-continuous."""
    t = np.clip(t, 0, 1)
    return t * t * t * (t * (t * 6 - 15) + 10)

def _value_noise_2d(x, y):
    """2D value noise at arbitrary float coordinates. Returns float32 in [0,1].
    x, y: float32 arrays of same shape."""
    ix = np.floor(x).astype(np.int64)
    iy = np.floor(y).astype(np.int64)
    fx = _smootherstep(x - ix)
    fy = _smootherstep(y - iy)
    # 4-corner hashes
    n00 = _hash2d(ix, iy)
    n10 = _hash2d(ix + 1, iy)
    n01 = _hash2d(ix, iy + 1)
    n11 = _hash2d(ix + 1, iy + 1)
    # Bilinear interpolation
    nx0 = n00 * (1 - fx) + n10 * fx
    nx1 = n01 * (1 - fx) + n11 * fx
    return nx0 * (1 - fy) + nx1 * fy

def vf_noise(g, f, t, S, freq=0.08, speed=0.3, bri=0.7):
    """Value noise. Smooth, organic, no axis alignment artifacts.
    freq: spatial frequency (higher = finer detail).
    speed: temporal scroll rate."""
    x = g.cc * freq + t * speed
    y = g.rr * freq * 0.8 - t * speed * 0.4
    return np.clip(_value_noise_2d(x, y) * bri, 0, 1)

def vf_fbm(g, f, t, S, octaves=5, freq=0.06, lacunarity=2.0, gain=0.5,
           speed=0.2, bri=0.8):
    """Fractal Brownian Motion — octaved noise with lacunarity/gain control.
    The standard building block for clouds, terrain, smoke, organic textures.

    octaves: number of noise layers (more = finer detail, more cost)
    freq: base spatial frequency
    lacunarity: frequency multiplier per octave (2.0 = standard)
    gain: amplitude multiplier per octave (0.5 = standard, <0.5 = smoother)
    speed: temporal evolution rate
    """
    val = np.zeros((g.rows, g.cols), dtype=np.float32)
    amplitude = 1.0
    f_x = freq
    f_y = freq * 0.85  # slight anisotropy avoids grid artifacts
    for i in range(octaves):
        phase = t * speed * (1 + i * 0.3)
        x = g.cc * f_x + phase + i * 17.3  # offset per octave
        y = g.rr * f_y - phase * 0.6 + i * 31.7
        val = val + _value_noise_2d(x, y) * amplitude
        amplitude *= gain
        f_x *= lacunarity
        f_y *= lacunarity
    # Normalize to [0,1]
    max_amp = (1 - gain ** octaves) / (1 - gain) if gain != 1 else octaves
    return np.clip(val / max_amp * bri * (0.6 + f.get("rms", 0.3) * 0.6), 0, 1)

def vf_domain_warp(g, f, t, S, base_fn=None, warp_fn=None,
                   warp_strength=15.0, freq=0.06, speed=0.2):
    """Domain warping — feed one noise field's output as coordinate offsets
    into another noise field. Produces flowing, melting organic distortion.
    Signature technique of high-end generative art (Inigo Quilez).

    base_fn: value field to distort (default: fbm)
    warp_fn: value field for displacement (default: noise at different freq)
    warp_strength: how many grid cells to displace (higher = more warped)
    """
    # Warp field: displacement in x and y
    wx = _value_noise_2d(g.cc * freq * 1.3 + t * speed, g.rr * freq + 7.1)
    wy = _value_noise_2d(g.cc * freq + t * speed * 0.7 + 3.2, g.rr * freq * 1.1 - 11.8)
    # Center warp around 0 (noise returns [0,1], shift to [-0.5, 0.5])
    wx = (wx - 0.5) * warp_strength * (0.5 + f.get("rms", 0.3) * 1.0)
    wy = (wy - 0.5) * warp_strength * (0.5 + f.get("bass", 0.3) * 0.8)
    # Sample base field at warped coordinates
    warped_cc = g.cc + wx
    warped_rr = g.rr + wy
    if base_fn is not None:
        # Create a temporary grid-like object with warped coords
        # Simplification: evaluate base_fn with modified coordinates
        val = _value_noise_2d(warped_cc * freq * 0.8 + t * speed * 0.5,
                              warped_rr * freq * 0.7 - t * speed * 0.3)
    else:
        # Default: fbm at warped coordinates
        val = np.zeros((g.rows, g.cols), dtype=np.float32)
        amp = 1.0
        fx, fy = freq * 0.8, freq * 0.7
        for i in range(4):
            val = val + _value_noise_2d(warped_cc * fx + t * speed * 0.5 + i * 13.7,
                                        warped_rr * fy - t * speed * 0.3 + i * 27.3) * amp
            amp *= 0.5; fx *= 2.0; fy *= 2.0
        val = val / 1.875  # normalize 4-octave sum
    return np.clip(val * 0.8, 0, 1)

def vf_voronoi(g, f, t, S, n_cells=20, speed=0.3, edge_width=1.5,
               mode="distance", seed=42):
    """Voronoi diagram as value field. Proper implementation with
    nearest/second-nearest distance for cell interiors and edges.

    mode: "distance" (bright at center, dark at edges),
          "edge" (bright at cell boundaries),
          "cell_id" (flat color per cell — use with discrete palette)
    edge_width: thickness of edge highlight (for "edge" mode)
    """
    rng = np.random.RandomState(seed)
    # Animated cell centers
    cx = rng.rand(n_cells).astype(np.float32) * g.cols
    cy = rng.rand(n_cells).astype(np.float32) * g.rows
    vx = (rng.rand(n_cells).astype(np.float32) - 0.5) * speed * 10
    vy = (rng.rand(n_cells).astype(np.float32) - 0.5) * speed * 10
    cx_t = (cx + vx * np.sin(t * 0.5 + np.arange(n_cells) * 0.8)) % g.cols
    cy_t = (cy + vy * np.cos(t * 0.4 + np.arange(n_cells) * 1.1)) % g.rows

    # Compute nearest and second-nearest distance
    d1 = np.full((g.rows, g.cols), 1e9, dtype=np.float32)
    d2 = np.full((g.rows, g.cols), 1e9, dtype=np.float32)
    id1 = np.zeros((g.rows, g.cols), dtype=np.int32)
    for i in range(n_cells):
        d = np.sqrt((g.cc - cx_t[i]) ** 2 + (g.rr - cy_t[i]) ** 2)
        mask = d < d1
        d2 = np.where(mask, d1, np.minimum(d2, d))
        id1 = np.where(mask, i, id1)
        d1 = np.minimum(d1, d)

    if mode == "edge":
        # Edges: where d2 - d1 is small
        edge_val = np.clip(1.0 - (d2 - d1) / edge_width, 0, 1)
        return edge_val * (0.5 + f.get("rms", 0.3) * 0.8)
    elif mode == "cell_id":
        # Flat per-cell value
        return (id1.astype(np.float32) / n_cells) % 1.0
    else:
        # Distance: bright near center, dark at edges
        max_d = g.cols * 0.15
        return np.clip(1.0 - d1 / max_d, 0, 1) * (0.5 + f.get("rms", 0.3) * 0.7)
```

#### 基于模拟的场（涌现、演化）

它们利用持久状态 `S` 逐帧演化图案，能够产生无状态数学方法无法实现的复杂性。

```python
def vf_reaction_diffusion(g, f, t, S, feed=0.055, kill=0.062,
                          da=1.0, db=0.5, dt=1.0, steps_per_frame=8,
                          init_mode="spots"):
    """Gray-Scott reaction-diffusion model. Produces coral, leopard spots,
    mitosis, worm-like, and labyrinthine patterns depending on feed/kill.

    The two chemicals A and B interact:
        A + 2B → 3B  (autocatalytic)
        B → P        (decay)
        feed: rate A is replenished, kill: rate B decays
    Different feed/kill ratios produce radically different patterns.

    Presets (feed, kill):
        Spots/dots:       (0.055, 0.062)
        Worms/stripes:    (0.046, 0.063)
        Coral/branching:  (0.037, 0.060)
        Mitosis/splitting: (0.028, 0.062)
        Labyrinth/maze:   (0.029, 0.057)
        Holes/negative:   (0.039, 0.058)
        Chaos/unstable:   (0.026, 0.051)

    steps_per_frame: simulation steps per video frame (more = faster evolution)
    """
    key = "rd_" + str(id(g))  # unique per grid
    if key + "_a" not in S:
        # Initialize chemical fields
        A = np.ones((g.rows, g.cols), dtype=np.float32)
        B = np.zeros((g.rows, g.cols), dtype=np.float32)
        if init_mode == "spots":
            # Random seed spots
            rng = np.random.RandomState(42)
            for _ in range(max(3, g.rows * g.cols // 200)):
                r, c = rng.randint(2, g.rows - 2), rng.randint(2, g.cols - 2)
                B[r - 1:r + 2, c - 1:c + 2] = 1.0
        elif init_mode == "center":
            cr, cc = g.rows // 2, g.cols // 2
            B[cr - 3:cr + 3, cc - 3:cc + 3] = 1.0
        elif init_mode == "ring":
            mask = (g.dist_n > 0.2) & (g.dist_n < 0.3)
            B[mask] = 1.0
        S[key + "_a"] = A
        S[key + "_b"] = B

    A = S[key + "_a"]
    B = S[key + "_b"]

    # Audio modulation: feed/kill shift subtly with audio
    f_mod = feed + f.get("bass", 0.3) * 0.003
    k_mod = kill + f.get("hi_r", 0.3) * 0.002

    for _ in range(steps_per_frame):
        # Laplacian via 3x3 convolution kernel
        # [0.05, 0.2, 0.05]
        # [0.2, -1.0, 0.2]
        # [0.05, 0.2, 0.05]
        pA = np.pad(A, 1, mode="wrap")
        pB = np.pad(B, 1, mode="wrap")
        lapA = (pA[:-2, 1:-1] + pA[2:, 1:-1] + pA[1:-1, :-2] + pA[1:-1, 2:]) * 0.2 \
             + (pA[:-2, :-2] + pA[:-2, 2:] + pA[2:, :-2] + pA[2:, 2:]) * 0.05 \
             - A * 1.0
        lapB = (pB[:-2, 1:-1] + pB[2:, 1:-1] + pB[1:-1, :-2] + pB[1:-1, 2:]) * 0.2 \
             + (pB[:-2, :-2] + pB[:-2, 2:] + pB[2:, :-2] + pB[2:, 2:]) * 0.05 \
             - B * 1.0
        ABB = A * B * B
        A = A + (da * lapA - ABB + f_mod * (1 - A)) * dt
        B = B + (db * lapB + ABB - (f_mod + k_mod) * B) * dt
        A = np.clip(A, 0, 1)
        B = np.clip(B, 0, 1)

    S[key + "_a"] = A
    S[key + "_b"] = B
    # Output B chemical as value (the visible pattern)
    return np.clip(B * 2.0, 0, 1)

def vf_game_of_life(g, f, t, S, rule="life", birth=None, survive=None,
                    steps_per_frame=1, density=0.3, fade=0.92, seed=42):
    """Cellular automaton as value field with analog fade trails.
    Grid cells are born/die by neighbor count rules. Dead cells fade
    gradually instead of snapping to black, producing ghost trails.

    rule presets:
        "life":     B3/S23 (Conway's Game of Life)
        "coral":    B3/S45678 (slow crystalline growth)
        "maze":     B3/S12345 (fills to labyrinth)
        "anneal":   B4678/S35678 (smooth blobs)
        "day_night": B3678/S34678 (balanced growth/decay)
    Or specify birth/survive directly as sets: birth={3}, survive={2,3}

    fade: how fast dead cells dim (0.9 = slow trails, 0.5 = fast)
    """
    presets = {
        "life":      ({3}, {2, 3}),
        "coral":     ({3}, {4, 5, 6, 7, 8}),
        "maze":      ({3}, {1, 2, 3, 4, 5}),
        "anneal":    ({4, 6, 7, 8}, {3, 5, 6, 7, 8}),
        "day_night": ({3, 6, 7, 8}, {3, 4, 6, 7, 8}),
    }
    if birth is None or survive is None:
        birth, survive = presets.get(rule, presets["life"])

    key = "gol_" + str(id(g))
    if key + "_grid" not in S:
        rng = np.random.RandomState(seed)
        S[key + "_grid"] = (rng.random((g.rows, g.cols)) < density).astype(np.float32)
        S[key + "_display"] = S[key + "_grid"].copy()

    grid = S[key + "_grid"]
    display = S[key + "_display"]

    # Beat can inject random noise
    if f.get("beat", 0) > 0.5:
        inject = np.random.random((g.rows, g.cols)) < 0.02
        grid = np.clip(grid + inject.astype(np.float32), 0, 1)

    for _ in range(steps_per_frame):
        # Count neighbors (toroidal wrap)
        padded = np.pad(grid > 0.5, 1, mode="wrap").astype(np.int8)
        neighbors = (padded[:-2, :-2] + padded[:-2, 1:-1] + padded[:-2, 2:] +
                     padded[1:-1, :-2] +                     padded[1:-1, 2:] +
                     padded[2:, :-2]  + padded[2:, 1:-1]  + padded[2:, 2:])
        alive = grid > 0.5
        new_alive = np.zeros_like(grid, dtype=bool)
        for b in birth:
            new_alive |= (~alive) & (neighbors == b)
        for s in survive:
            new_alive |= alive & (neighbors == s)
        grid = new_alive.astype(np.float32)

    # Analog display: alive cells = 1.0, dead cells fade
    display = np.where(grid > 0.5, 1.0, display * fade)
    S[key + "_grid"] = grid
    S[key + "_display"] = display
    return np.clip(display, 0, 1)

def vf_strange_attractor(g, f, t, S, attractor="clifford",
                         n_points=50000, warmup=500, bri=0.8, seed=42,
                         params=None):
    """Strange attractor projected to 2D density field.
    Iterates N points through attractor equations, bins to grid,
    produces a density map. Elegant, non-repeating curves.

    attractor presets:
        "clifford":  sin(a*y) + c*cos(a*x), sin(b*x) + d*cos(b*y)
        "de_jong":   sin(a*y) - cos(b*x), sin(c*x) - cos(d*y)
        "bedhead":   sin(x*y/b) + cos(a*x - y), x*sin(a*y) + cos(b*x - y)

    params: (a, b, c, d) floats — each attractor has different sweet spots.
            If None, uses time-varying defaults for animation.
    """
    key = "attr_" + attractor
    if params is None:
        # Time-varying parameters for slow morphing
        a = -1.4 + np.sin(t * 0.05) * 0.3
        b = 1.6 + np.cos(t * 0.07) * 0.2
        c = 1.0 + np.sin(t * 0.03 + 1) * 0.3
        d = 0.7 + np.cos(t * 0.04 + 2) * 0.2
    else:
        a, b, c, d = params

    # Iterate attractor
    rng = np.random.RandomState(seed)
    x = rng.uniform(-0.1, 0.1, n_points).astype(np.float64)
    y = rng.uniform(-0.1, 0.1, n_points).astype(np.float64)

    # Warmup iterations (reach the attractor)
    for _ in range(warmup):
        if attractor == "clifford":
            xn = np.sin(a * y) + c * np.cos(a * x)
            yn = np.sin(b * x) + d * np.cos(b * y)
        elif attractor == "de_jong":
            xn = np.sin(a * y) - np.cos(b * x)
            yn = np.sin(c * x) - np.cos(d * y)
        elif attractor == "bedhead":
            xn = np.sin(x * y / b) + np.cos(a * x - y)
            yn = x * np.sin(a * y) + np.cos(b * x - y)
        else:
            xn = np.sin(a * y) + c * np.cos(a * x)
            yn = np.sin(b * x) + d * np.cos(b * y)
        x, y = xn, yn

    # Bin to grid
    # Find bounds
    margin = 0.1
    x_min, x_max = x.min() - margin, x.max() + margin
    y_min, y_max = y.min() - margin, y.max() + margin

    # Map to grid coordinates
    gx = ((x - x_min) / (x_max - x_min) * (g.cols - 1)).astype(np.int32)
    gy = ((y - y_min) / (y_max - y_min) * (g.rows - 1)).astype(np.int32)
    valid = (gx >= 0) & (gx < g.cols) & (gy >= 0) & (gy < g.rows)
    gx, gy = gx[valid], gy[valid]

    # Accumulate density
    density = np.zeros((g.rows, g.cols), dtype=np.float32)
    np.add.at(density, (gy, gx), 1.0)

    # Log-scale density for visibility (most bins have few hits)
    density = np.log1p(density)
    mx = density.max()
    if mx > 0:
        density = density / mx
    return np.clip(density * bri * (0.5 + f.get("rms", 0.3) * 0.8), 0, 1)
```

#### 基于 SDF 的场（几何精度）

有符号距离场（Signed Distance Fields）可生成数学上精确的形状。与有机、模糊的正弦场不同，SDF 能提供边缘柔和度可控的硬质几何边界。与 domain warping 结合后，可创造“熔化几何”效果。

所有 SDF 图元都会返回**有符号距离**（内部为负，外部为正）。使用 `sdf_render()` 将其转换为值场。

```python
def sdf_render(dist, edge_width=1.5, invert=False):
    """Convert signed distance to value field [0,1].
    edge_width: controls anti-aliasing / softness of the boundary.
    invert: True = bright inside shape, False = bright outside."""
    val = 1.0 - np.clip(dist / edge_width, 0, 1) if not invert else np.clip(dist / edge_width, 0, 1)
    return np.clip(val, 0, 1)

def sdf_glow(dist, falloff=0.05):
    """Render SDF as glowing outline — bright at boundary, fading both directions."""
    return np.clip(np.exp(-np.abs(dist) * falloff), 0, 1)

# --- Primitives ---

def sdf_circle(g, cx_frac=0.5, cy_frac=0.5, radius=0.3):
    """Circle SDF. cx/cy/radius in normalized [0,1] coordinates."""
    dx = (g.cc / g.cols - cx_frac) * (g.cols / g.rows)  # aspect correction
    dy = g.rr / g.rows - cy_frac
    return np.sqrt(dx**2 + dy**2) - radius

def sdf_box(g, cx_frac=0.5, cy_frac=0.5, w=0.3, h=0.2, round_r=0.0):
    """Rounded rectangle SDF."""
    dx = np.abs(g.cc / g.cols - cx_frac) * (g.cols / g.rows) - w + round_r
    dy = np.abs(g.rr / g.rows - cy_frac) - h + round_r
    outside = np.sqrt(np.maximum(dx, 0)**2 + np.maximum(dy, 0)**2)
    inside = np.minimum(np.maximum(dx, dy), 0)
    return outside + inside - round_r

def sdf_ring(g, cx_frac=0.5, cy_frac=0.5, radius=0.3, thickness=0.03):
    """Ring (annulus) SDF."""
    d = sdf_circle(g, cx_frac, cy_frac, radius)
    return np.abs(d) - thickness

def sdf_line(g, x0=0.2, y0=0.5, x1=0.8, y1=0.5, thickness=0.01):
    """Line segment SDF between two points (normalized coords)."""
    ax = g.cc / g.cols * (g.cols / g.rows) - x0 * (g.cols / g.rows)
    ay = g.rr / g.rows - y0
    bx = (x1 - x0) * (g.cols / g.rows)
    by = y1 - y0
    h = np.clip((ax * bx + ay * by) / (bx * bx + by * by + 1e-10), 0, 1)
    dx = ax - bx * h
    dy = ay - by * h
    return np.sqrt(dx**2 + dy**2) - thickness

def sdf_triangle(g, cx=0.5, cy=0.5, size=0.25):
    """Equilateral triangle SDF centered at (cx, cy)."""
    px = (g.cc / g.cols - cx) * (g.cols / g.rows) / size
    py = (g.rr / g.rows - cy) / size
    # Equilateral triangle math
    k = np.sqrt(3.0)
    px = np.abs(px) - 1.0
    py = py + 1.0 / k
    cond = px + k * py > 0
    px2 = np.where(cond, (px - k * py) / 2.0, px)
    py2 = np.where(cond, (-k * px - py) / 2.0, py)
    px2 = np.clip(px2, -2.0, 0.0)
    return -np.sqrt(px2**2 + py2**2) * np.sign(py2) * size

def sdf_star(g, cx=0.5, cy=0.5, n_points=5, outer_r=0.25, inner_r=0.12):
    """Star polygon SDF — n-pointed star."""
    px = (g.cc / g.cols - cx) * (g.cols / g.rows)
    py = g.rr / g.rows - cy
    angle = np.arctan2(py, px)
    dist = np.sqrt(px**2 + py**2)
    # Modular angle for star symmetry
    wedge = 2 * np.pi / n_points
    a = np.abs((angle % wedge) - wedge / 2)
    # Interpolate radius between inner and outer
    r_at_angle = inner_r + (outer_r - inner_r) * np.clip(np.cos(a * n_points) * 0.5 + 0.5, 0, 1)
    return dist - r_at_angle

def sdf_heart(g, cx=0.5, cy=0.45, size=0.25):
    """Heart shape SDF."""
    px = (g.cc / g.cols - cx) * (g.cols / g.rows) / size
    py = -(g.rr / g.rows - cy) / size + 0.3  # flip y, offset
    px = np.abs(px)
    cond = (px + py) > 1.0
    d1 = np.sqrt((px - 0.25)**2 + (py - 0.75)**2) - np.sqrt(2.0) / 4.0
    d2 = np.sqrt((px + py - 1.0)**2) / np.sqrt(2.0)
    return np.where(cond, d1, d2) * size

# --- Combinators ---

def sdf_union(d1, d2):
    """Boolean union — shape is wherever either SDF is inside."""
    return np.minimum(d1, d2)

def sdf_intersect(d1, d2):
    """Boolean intersection — shape is where both SDFs overlap."""
    return np.maximum(d1, d2)

def sdf_subtract(d1, d2):
    """Boolean subtraction — d1 minus d2."""
    return np.maximum(d1, -d2)

def sdf_smooth_union(d1, d2, k=0.1):
    """Smooth minimum (polynomial) — blends shapes with rounded join.
    k: smoothing radius. Higher = more rounding."""
    h = np.clip(0.5 + 0.5 * (d2 - d1) / k, 0, 1)
    return d2 * (1 - h) + d1 * h - k * h * (1 - h)

def sdf_smooth_subtract(d1, d2, k=0.1):
    """Smooth subtraction — d1 minus d2 with rounded edge."""
    return sdf_smooth_union(d1, -d2, k)

def sdf_repeat(g, sdf_fn, spacing_x=0.25, spacing_y=0.25, **sdf_kwargs):
    """Tile an SDF primitive infinitely. spacing in normalized coords."""
    # Modular coordinates
    mod_cc = (g.cc / g.cols) % spacing_x - spacing_x / 2
    mod_rr = (g.rr / g.rows) % spacing_y - spacing_y / 2
    # Create modified grid-like arrays for the SDF
    # This is a simplified approach — build a temporary namespace
    class ModGrid:
        pass
    mg = ModGrid()
    mg.cc = mod_cc * g.cols; mg.rr = mod_rr * g.rows
    mg.cols = g.cols; mg.rows = g.rows
    return sdf_fn(mg, **sdf_kwargs)

# --- SDF as Value Field ---

def vf_sdf(g, f, t, S, sdf_fn=sdf_circle, edge_width=1.5, glow=False,
           glow_falloff=0.03, animate=True, **sdf_kwargs):
    """Wrap any SDF primitive as a standard vf_* value field.
    If animate=True, applies slow rotation and breathing to the shape."""
    if animate:
        sdf_kwargs.setdefault("cx_frac", 0.5)
        sdf_kwargs.setdefault("cy_frac", 0.5)
    d = sdf_fn(g, **sdf_kwargs)
    if glow:
        return sdf_glow(d, glow_falloff) * (0.5 + f.get("rms", 0.3) * 0.8)
    return sdf_render(d, edge_width) * (0.5 + f.get("rms", 0.3) * 0.8)
```

### 色相场生成器（颜色映射）

这些生成取值范围为 [0,1] 的 float32 色相数组，可独立地与任意值场组合。每个生成器都是工厂函数，会返回签名为 `(g, f, t, S) -> float32 array` 的闭包。固定色相也可以直接使用普通 float。

```python
def hf_fixed(hue):
    """Single hue everywhere."""
    def fn(g, f, t, S):
        return np.full((g.rows, g.cols), hue, dtype=np.float32)
    return fn

def hf_angle(offset=0.0):
    """Hue mapped to angle from center — rainbow wheel."""
    def fn(g, f, t, S):
        return (g.angle / (2 * np.pi) + offset + t * 0.05) % 1.0
    return fn

def hf_distance(base=0.5, scale=0.02):
    """Hue mapped to distance from center."""
    def fn(g, f, t, S):
        return (base + g.dist * scale + t * 0.03) % 1.0
    return fn

def hf_time_cycle(speed=0.1):
    """Hue cycles uniformly over time."""
    def fn(g, f, t, S):
        return np.full((g.rows, g.cols), (t * speed) % 1.0, dtype=np.float32)
    return fn

def hf_audio_cent():
    """Hue follows spectral centroid — timbral color shifting."""
    def fn(g, f, t, S):
        return np.full((g.rows, g.cols), f.get("cent", 0.5) * 0.3, dtype=np.float32)
    return fn

def hf_gradient_h(start=0.0, end=1.0):
    """Left-to-right hue gradient."""
    def fn(g, f, t, S):
        h = np.broadcast_to(
            start + (g.cc / g.cols) * (end - start),
            (g.rows, g.cols)
        ).copy()  # .copy() is CRITICAL — see troubleshooting.md
        return h % 1.0
    return fn

def hf_gradient_v(start=0.0, end=1.0):
    """Top-to-bottom hue gradient."""
    def fn(g, f, t, S):
        h = np.broadcast_to(
            start + (g.rr / g.rows) * (end - start),
            (g.rows, g.cols)
        ).copy()
        return h % 1.0
    return fn

def hf_plasma(speed=0.3):
    """Plasma-style hue field — organic color variation."""
    def fn(g, f, t, S):
        return (np.sin(g.cc*0.02 + t*speed)*0.5 + np.sin(g.rr*0.015 + t*speed*0.7)*0.5) % 1.0
    return fn
```

---

## 坐标变换

在 effect 求值**之前**应用 UV 空间变换。通过变换 `vf_*` 函数所见的网格坐标，可对任意此类函数进行旋转、缩放、平铺或扭曲。

### 变换辅助函数

```python
def uv_rotate(g, angle):
    """Rotate UV coordinates around grid center.
    Returns (rotated_cc, rotated_rr) arrays — use in place of g.cc, g.rr."""
    cx, cy = g.cols / 2.0, g.rows / 2.0
    cos_a, sin_a = np.cos(angle), np.sin(angle)
    dx = g.cc - cx
    dy = g.rr - cy
    return cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a

def uv_scale(g, sx=1.0, sy=1.0, cx_frac=0.5, cy_frac=0.5):
    """Scale UV coordinates around a center point.
    sx, sy > 1 = zoom in (fewer repeats), < 1 = zoom out (more repeats)."""
    cx = g.cols * cx_frac; cy = g.rows * cy_frac
    return cx + (g.cc - cx) / sx, cy + (g.rr - cy) / sy

def uv_skew(g, kx=0.0, ky=0.0):
    """Skew UV coordinates. kx shears horizontally, ky vertically."""
    return g.cc + g.rr * kx, g.rr + g.cc * ky

def uv_tile(g, nx=3.0, ny=3.0, mirror=False):
    """Tile UV coordinates. nx, ny = number of repeats.
    mirror=True: alternating tiles are flipped (seamless)."""
    u = (g.cc / g.cols * nx) % 1.0
    v = (g.rr / g.rows * ny) % 1.0
    if mirror:
        flip_u = ((g.cc / g.cols * nx).astype(int) % 2) == 1
        flip_v = ((g.rr / g.rows * ny).astype(int) % 2) == 1
        u = np.where(flip_u, 1.0 - u, u)
        v = np.where(flip_v, 1.0 - v, v)
    return u * g.cols, v * g.rows

def uv_polar(g):
    """Convert Cartesian to polar UV. Returns (angle_as_cc, dist_as_rr).
    Use to make any linear effect radial."""
    # Angle wraps [0, cols), distance wraps [0, rows)
    return g.angle / (2 * np.pi) * g.cols, g.dist_n * g.rows

def uv_cartesian_from_polar(g):
    """Convert polar-addressed effects back to Cartesian.
    Treats g.cc as angle and g.rr as radius."""
    angle = g.cc / g.cols * 2 * np.pi
    radius = g.rr / g.rows
    cx, cy = g.cols / 2.0, g.rows / 2.0
    return cx + radius * np.cos(angle) * cx, cy + radius * np.sin(angle) * cy

def uv_twist(g, amount=2.0):
    """Twist: rotation increases with distance from center. Creates spiral distortion."""
    twist_angle = g.dist_n * amount
    return uv_rotate_raw(g.cc, g.rr, g.cols / 2, g.rows / 2, twist_angle)

def uv_rotate_raw(cc, rr, cx, cy, angle):
    """Raw rotation on arbitrary coordinate arrays."""
    cos_a, sin_a = np.cos(angle), np.sin(angle)
    dx = cc - cx; dy = rr - cy
    return cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a

def uv_fisheye(g, strength=1.5):
    """Fisheye / barrel distortion on UV coordinates."""
    cx, cy = g.cols / 2.0, g.rows / 2.0
    dx = (g.cc - cx) / cx
    dy = (g.rr - cy) / cy
    r = np.sqrt(dx**2 + dy**2)
    r_distort = np.power(r, strength)
    scale = np.where(r > 0, r_distort / (r + 1e-10), 1.0)
    return cx + dx * scale * cx, cy + dy * scale * cy

def uv_wave(g, t, freq=0.1, amp=3.0, axis="x"):
    """Sinusoidal coordinate displacement. Wobbles the UV space."""
    if axis == "x":
        return g.cc + np.sin(g.rr * freq + t * 3) * amp, g.rr
    else:
        return g.cc, g.rr + np.sin(g.cc * freq + t * 3) * amp

def uv_mobius(g, a=1.0, b=0.0, c=0.0, d=1.0):
    """Möbius transformation (conformal map): f(z) = (az + b) / (cz + d).
    Operates on complex plane. Produces mathematically precise, visually
    striking inversions and circular transforms."""
    cx, cy = g.cols / 2.0, g.rows / 2.0
    # Map grid to complex plane [-1, 1]
    zr = (g.cc - cx) / cx
    zi = (g.rr - cy) / cy
    # Complex division: (a*z + b) / (c*z + d)
    num_r = a * zr - 0 * zi + b  # imaginary parts of a,b,c,d = 0 for real params
    num_i = a * zi + 0 * zr + 0
    den_r = c * zr - 0 * zi + d
    den_i = c * zi + 0 * zr + 0
    denom = den_r**2 + den_i**2 + 1e-10
    wr = (num_r * den_r + num_i * den_i) / denom
    wi = (num_i * den_r - num_r * den_i) / denom
    return cx + wr * cx, cy + wi * cy
```

### 将变换用于值场

变换会改变值场所见的坐标。将变换包装在 `vf_*` 调用外部：

```python
# Rotate a plasma field 45 degrees
def vf_rotated_plasma(g, f, t, S):
    rc, rr = uv_rotate(g, np.pi / 4 + t * 0.1)
    class TG:  # transformed grid
        pass
    tg = TG(); tg.cc = rc; tg.rr = rr
    tg.rows = g.rows; tg.cols = g.cols
    tg.dist_n = g.dist_n; tg.angle = g.angle; tg.dist = g.dist
    return vf_plasma(tg, f, t, S)

# Tile a vortex 3x3 with mirror
def vf_tiled_vortex(g, f, t, S):
    tc, tr = uv_tile(g, 3, 3, mirror=True)
    class TG:
        pass
    tg = TG(); tg.cc = tc; tg.rr = tr
    tg.rows = g.rows; tg.cols = g.cols
    tg.dist = np.sqrt((tc - g.cols/2)**2 + (tr - g.rows/2)**2)
    tg.dist_n = tg.dist / (tg.dist.max() + 1e-10)
    tg.angle = np.arctan2(tr - g.rows/2, tc - g.cols/2)
    return vf_vortex(tg, f, t, S)

# Helper: create transformed grid from coordinate arrays
def make_tgrid(g, new_cc, new_rr):
    """Build a grid-like object with transformed coordinates.
    Preserves rows/cols for sizing, recomputes polar coords."""
    class TG:
        pass
    tg = TG()
    tg.cc = new_cc; tg.rr = new_rr
    tg.rows = g.rows; tg.cols = g.cols
    cx, cy = g.cols / 2.0, g.rows / 2.0
    dx = new_cc - cx; dy = new_rr - cy
    tg.dist = np.sqrt(dx**2 + dy**2)
    tg.dist_n = tg.dist / (max(cx, cy) + 1e-10)
    tg.angle = np.arctan2(dy, dx)
    tg.dx = dx; tg.dy = dy
    tg.dx_n = dx / max(g.cols, 1)
    tg.dy_n = dy / max(g.rows, 1)
    return tg
```

---

## 时间连贯性

用于让参数随时间平滑且有意图地演化的工具。它取代了静态参数或直接音频响应这两种默认模式。

### 缓动函数

标准动画缓动曲线。它们均接收 [0,1] 范围内的 `t`，并返回 [0,1] 范围内的值：

```python
def ease_linear(t): return t
def ease_in_quad(t): return t * t
def ease_out_quad(t): return t * (2 - t)
def ease_in_out_quad(t): return np.where(t < 0.5, 2*t*t, -1 + (4-2*t)*t)
def ease_in_cubic(t): return t**3
def ease_out_cubic(t): return (t - 1)**3 + 1
def ease_in_out_cubic(t):
    return np.where(t < 0.5, 4*t**3, 1 - (-2*t + 2)**3 / 2)
def ease_in_expo(t): return np.where(t == 0, 0, 2**(10*(t-1)))
def ease_out_expo(t): return np.where(t == 1, 1, 1 - 2**(-10*t))
def ease_elastic(t):
    """Elastic ease-out — overshoots then settles."""
    return np.where(t == 0, 0, np.where(t == 1, 1,
        2**(-10*t) * np.sin((t*10 - 0.75) * (2*np.pi) / 3) + 1))
def ease_bounce(t):
    """Bounce ease-out — bounces at the end."""
    t = np.asarray(t, dtype=np.float64)
    result = np.empty_like(t)
    m1 = t < 1/2.75
    m2 = (~m1) & (t < 2/2.75)
    m3 = (~m1) & (~m2) & (t < 2.5/2.75)
    m4 = ~(m1 | m2 | m3)
    result[m1] = 7.5625 * t[m1]**2
    t2 = t[m2] - 1.5/2.75;   result[m2] = 7.5625 * t2**2 + 0.75
    t3 = t[m3] - 2.25/2.75;  result[m3] = 7.5625 * t3**2 + 0.9375
    t4 = t[m4] - 2.625/2.75; result[m4] = 7.5625 * t4**2 + 0.984375
    return result
```

### 关键帧插值

在特定时间点定义参数值，并使用缓动在它们之间插值：

```python
def keyframe(t, points, ease_fn=ease_in_out_cubic, loop=False):
    """Interpolate between keyframed values.

    Args:
        t: current time (float, seconds)
        points: list of (time, value) tuples, sorted by time
        ease_fn: easing function for interpolation
        loop: if True, wraps around after last keyframe

    Returns:
        interpolated value at time t

    Example:
        twist = keyframe(t, [(0, 1.0), (5, 6.0), (10, 2.0)], ease_out_cubic)
    """
    if not points:
        return 0.0
    if loop:
        period = points[-1][0] - points[0][0]
        if period > 0:
            t = points[0][0] + (t - points[0][0]) % period

    # Clamp to range
    if t <= points[0][0]:
        return points[0][1]
    if t >= points[-1][0]:
        return points[-1][1]

    # Find surrounding keyframes
    for i in range(len(points) - 1):
        t0, v0 = points[i]
        t1, v1 = points[i + 1]
        if t0 <= t <= t1:
            progress = (t - t0) / (t1 - t0)
            eased = ease_fn(progress)
            return v0 + (v1 - v0) * eased

    return points[-1][1]

def keyframe_array(t, points, ease_fn=ease_in_out_cubic):
    """Keyframe interpolation that works with numpy arrays as values.
    points: list of (time, np.array) tuples."""
    if t <= points[0][0]: return points[0][1].copy()
    if t >= points[-1][0]: return points[-1][1].copy()
    for i in range(len(points) - 1):
        t0, v0 = points[i]
        t1, v1 = points[i + 1]
        if t0 <= t <= t1:
            progress = ease_fn((t - t0) / (t1 - t0))
            return v0 * (1 - progress) + v1 * progress
    return points[-1][1].copy()
```

### 值场变形

在两个不同值场之间平滑过渡：

```python
def vf_morph(g, f, t, S, vf_a, vf_b, t_start, t_end,
             ease_fn=ease_in_out_cubic):
    """Morph between two value fields over a time range.

    Usage:
        val = vf_morph(g, f, t, S,
            lambda g,f,t,S: vf_plasma(g,f,t,S),
            lambda g,f,t,S: vf_vortex(g,f,t,S, twist=5),
            t_start=10.0, t_end=15.0)
    """
    if t <= t_start:
        return vf_a(g, f, t, S)
    if t >= t_end:
        return vf_b(g, f, t, S)
    progress = ease_fn((t - t_start) / (t_end - t_start))
    a = vf_a(g, f, t, S)
    b = vf_b(g, f, t, S)
    return a * (1 - progress) + b * progress

def vf_sequence(g, f, t, S, fields, durations, crossfade=1.0,
                ease_fn=ease_in_out_cubic):
    """Cycle through a sequence of value fields with crossfades.

    fields: list of vf_* callables
    durations: list of float seconds per field
    crossfade: seconds of overlap between adjacent fields
    """
    total = sum(durations)
    t_local = t % total  # loop
    elapsed = 0
    for i, dur in enumerate(durations):
        if t_local < elapsed + dur:
            # Current field
            base = fields[i](g, f, t, S)
            # Check if we're in a crossfade zone
            time_in = t_local - elapsed
            time_left = dur - time_in
            if time_in < crossfade and i > 0:
                # Fading in from previous
                prev = fields[(i - 1) % len(fields)](g, f, t, S)
                blend = ease_fn(time_in / crossfade)
                return prev * (1 - blend) + base * blend
            if time_left < crossfade and i < len(fields) - 1:
                # Fading out to next
                nxt = fields[(i + 1) % len(fields)](g, f, t, S)
                blend = ease_fn(1 - time_left / crossfade)
                return base * (1 - blend) + nxt * blend
            return base
        elapsed += dur
    return fields[-1](g, f, t, S)
```

### 时间噪声

在 `(x, y, t)` 处采样的 3D 噪声——图案会随时间平滑演化，不会出现逐帧跳变：

```python
def vf_temporal_noise(g, f, t, S, freq=0.06, t_freq=0.3, octaves=4,
                      bri=0.8):
    """Noise field that evolves smoothly in time. Uses 3D noise via
    two 2D noise lookups combined with temporal interpolation.

    Unlike vf_fbm which scrolls noise (creating directional motion),
    this morphs the pattern in-place — cells brighten and dim without
    the field moving in any direction."""
    # Two noise samples at floor/ceil of temporal coordinate
    t_scaled = t * t_freq
    t_lo = np.floor(t_scaled)
    t_frac = _smootherstep(np.full((g.rows, g.cols), t_scaled - t_lo, dtype=np.float32))

    val_lo = np.zeros((g.rows, g.cols), dtype=np.float32)
    val_hi = np.zeros((g.rows, g.cols), dtype=np.float32)
    amp = 1.0; fx = freq
    for i in range(octaves):
        val_lo = val_lo + _value_noise_2d(
            g.cc * fx + t_lo * 7.3 + i * 13, g.rr * fx + t_lo * 3.1 + i * 29) * amp
        val_hi = val_hi + _value_noise_2d(
            g.cc * fx + (t_lo + 1) * 7.3 + i * 13, g.rr * fx + (t_lo + 1) * 3.1 + i * 29) * amp
        amp *= 0.5; fx *= 2.0
    max_amp = (1 - 0.5 ** octaves) / 0.5
    val = (val_lo * (1 - t_frac) + val_hi * t_frac) / max_amp
    return np.clip(val * bri * (0.6 + f.get("rms", 0.3) * 0.6), 0, 1)
```

---

### 组合值场

通过数学运算混合值场，可带来组合数量的爆炸式增长：

```python
# Multiplication = intersection (only shows where both have brightness)
combined = vf_plasma(g,f,t,S) * vf_vortex(g,f,t,S)

# Addition = union (shows both, clips at 1.0)
combined = np.clip(vf_rings(g,f,t,S) + vf_spiral(g,f,t,S), 0, 1)

# Interference = beat pattern (shows XOR-like patterns)
combined = np.abs(vf_plasma(g,f,t,S) - vf_tunnel(g,f,t,S))

# Modulation = one effect shapes the other
combined = vf_rings(g,f,t,S) * (0.3 + 0.7 * vf_plasma(g,f,t,S))

# Maximum = shows the brightest of two effects
combined = np.maximum(vf_spiral(g,f,t,S), vf_aurora(g,f,t,S))
```

### 完整场景示例（v2——返回画布）

v2 场景函数会在内部组合 effects，并返回像素画布：

```python
def scene_complex(r, f, t, S):
    """v2 scene function: returns canvas (uint8 H,W,3).
    r = Renderer, f = audio features, t = time, S = persistent state dict."""
    g = r.grids["md"]
    rows, cols = g.rows, g.cols
    
    # 1. Value field composition
    plasma = vf_plasma(g, f, t, S)
    vortex = vf_vortex(g, f, t, S, twist=4.0)
    combined = np.clip(plasma * 0.6 + vortex * 0.5 + plasma * vortex * 0.4, 0, 1)
    
    # 2. Color from hue field
    h = (hf_angle(0.3)(g,f,t,S) * 0.5 + hf_time_cycle(0.08)(g,f,t,S) * 0.5) % 1.0
    
    # 3. Render to canvas via _render_vf helper
    canvas = _render_vf(g, combined, h, sat=0.75, pal=PAL_DENSE)
    
    # 4. Optional: blend a second layer
    overlay = _render_vf(r.grids["sm"], vf_rings(r.grids["sm"],f,t,S),
                         hf_fixed(0.6)(r.grids["sm"],f,t,S), pal=PAL_BLOCK)
    canvas = blend_canvas(canvas, overlay, "screen", 0.4)
    
    return canvas
    
# In the render_clip() loop (handled by the framework):
# canvas = scene_fn(r, f, t, S)
# canvas = tonemap(canvas, gamma=scene_gamma)
# canvas = feedback.apply(canvas, ...)
# canvas = shader_chain.apply(canvas, f=f, t=t)
# pipe.stdin.write(canvas.tobytes())
```

逐段改变**值场组合**、**色相场**、**调色板**、**混合模式**、**反馈配置**和 **shader 链**，以获得最大的视觉多样性。12 种值场 × 8 种色相场 × 14 种调色板 × 20 种混合模式 × 7 种反馈变换 × 38 种 shaders，实际上可以产生无限组合。

---

## 组合 Effects——创意指南

上方目录是一套词汇。下面介绍如何将其组合成看起来经过精心设计的作品。

### 通过分层营造纵深
每个场景都应至少包含两个网格密度不同的图层：
- **背景**（sm 或 xs）：浓密、昏暗的纹理，避免画面变成单调的纯黑。使用低亮度（bri=0.15-0.25）的 fBM、平滑噪声或 domain warp。
- **内容**（md）：主视觉——圆环、Voronoi、螺旋、隧道。使用完整亮度。
- **强调**（lg 或 xl）：稀疏高光——粒子、文本模板、辉光脉冲。以 screen 模式混合到最上层。

### 有趣的 Effect 搭配
| 搭配 | 混合 | 奏效原因 |
|------|-------|-------------|
| fBM + Voronoi 边缘 | `screen` | 有机纹理填充元胞，边缘则增添结构感 |
| Domain warp + plasma | `difference` | 迷幻的有机干涉效果 |
| 隧道 + 涡旋 | `screen` | 纵深透视 + 旋转动能 |
| 螺旋 + 干涉 | `exclusion` | 不同空间频率形成的 Moiré 图案 |
| 反应扩散 + 火焰 | `add` | 鲜活的有机基底 + 动态前景 |
| SDF 几何 + domain warp | `screen` | 简洁形状漂浮于有机纹理中 |

### 将 Effects 用作蒙版
任何值场都可通过 `mask_from_vf()` 用作另一种 effect 的蒙版：
- 使用 Voronoi 元胞遮罩火焰（仅在元胞内部显示火焰）
- 使用 fBM 遮罩纯色图层（形成有机色彩云团）
- 使用 SDF 形状遮罩反应扩散场
- 通过动态光圈/划像，让一种 effect 在另一种之上显现

### 创造新 Effects
每个项目都应至少创造一种目录中没有的 effect：
- 通过数学运算**组合两个 vf_* 函数**：`np.clip(vf_fbm(...) * vf_rings(...), 0, 1)`
- 在求值前**应用坐标变换**：`vf_plasma(twisted_grid, ...)`
- **使用一个场调制另一个场的参数**：`vf_spiral(..., tightness=2 + vf_fbm(...) * 5)`
- **叠加时间偏移**：分别在 `t` 和 `t - 0.5` 渲染同一个场，再以 difference 模式混合，形成运动拖尾
- **通过 SDF 边界镜像值场**，形成万花筒般的几何图案
