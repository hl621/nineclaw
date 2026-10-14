# 故障排查参考

> **另请参阅：** composition.md · architecture.md · shaders.md · scenes.md · optimization.md

## 快速诊断

| 症状 | 可能原因 | 修复方法 |
|---------|-------------|-----|
| 输出全黑 | 色调映射 gamma 过高或没有效果在渲染 | 将 gamma 降至 0.5，并检查 scene_fn 是否返回非零画布 |
| 画面泛白/过亮 | 使用了线性亮度乘数而非色调映射 | 将 `canvas * N` 替换为 `tonemap(canvas, gamma=0.75)` |
| ffmpeg 在渲染途中卡住 | stderr=subprocess.PIPE 导致死锁 | 将 stderr 重定向到文件 |
| “read-only” 数组错误 | broadcast_to 视图后未调用 .copy() | 在 broadcast_to 后添加 `.copy()` |
| PicklingError | SCENES 表中存在 Lambda 或闭包 | 在模块级别定义所有 fx_* 函数 |
| 输出中随机出现暗洞 | 字体缺少 Unicode 字形 | 初始化时验证字符面板 |
| 音画不同步 | 帧计时误差累积 | 使用整数帧计数器，每帧重新计算 t |
| 单色、扁平的输出 | 色相场的形状不匹配 | 在 hsv2rgb 前确保 h、s、v 数组均为 (rows,cols) |
| 繁杂背景上的文本难以辨认 | 文本与背景之间缺乏对比 | 使用 `apply_text_backdrop()`（composition.md）+ `reverse_vignette` shader（shaders.md） |
| 文本乱码/镜像 | 对文本场景应用了万花筒或镜像 shader | **切勿对含有可读文本的场景应用 kaleidoscope、mirror_h/v/quad/diag**——径向折叠会破坏可读性。仅将它们应用于背景图层或无文本场景 |

ASCII 视频开发中常见的 bug、易踩坑点及平台特有问题。

## NumPy 广播

### `broadcast_to().copy()` 陷阱

色相场生成器经常返回广播视图形式的数组——其形状为 `(1, cols)` 或 `(rows, 1)`，numpy 会将其广播为 `(rows, cols)`。这些视图是**只读的**。如果任何下游代码尝试原地修改它们（例如 `h %= 1.0`），numpy 会抛出：

```
ValueError: output array is read-only
```

**修复方法**：始终调用 `.copy()`，并将其置于 `broadcast_to()` 之后：

```python
h = np.broadcast_to(h, (g.rows, g.cols)).copy()
```

这一点在 `_render_vf()` 中尤为重要，因为色相数组会传入 `hsv2rgb()`。

### `+=` 与 `+` 陷阱

当操作数形状并非完全一致时，广播也会因原地运算符而失败：

```python
# FAILS if result is (rows,1) and operand is (rows, cols)
val += np.sin(g.cc * 0.02 + t * 0.3) * 0.5

# WORKS — creates a new array
val = val + np.sin(g.cc * 0.02 + t * 0.3) * 0.5
```

`vf_plasma()` 函数曾存在此 bug。混合不同形状的数组时，请使用 `+` 而非 `+=`。

### `hsv2rgb()` 中的形状不匹配

`hsv2rgb(h, s, v)` 要求三个数组的形状完全相同。如果 `h` 为 `(1, cols)`，而 `s` 为 `(rows, cols)`，函数会崩溃或产生错误输出。

**修复方法**：调用前，确保所有输入均已广播并复制为 `(rows, cols)`。

---

## 混合模式陷阱

### Overlay 会压暗暗部输入

`overlay(a, b) = 2*a*b`（当 `a < 0.5` 时）。两个 0.12 的值会得到 `2 * 0.12 * 0.12 = 0.03`，结果比任一输入都暗。

**影响**：如果两个图层都很暗（ASCII 艺术通常如此），overlay 会产生近乎全黑的输出。

**修复方法**：对于较暗的源素材，请使用 `screen`。Screen 始终会提亮：`1 - (1-a)*(1-b)`。

### Colordodge 除以零

`colordodge(a, b) = a / (1 - b)`。当 `b = 1.0`（纯白像素）时，会发生除零。

**修复方法**：添加 epsilon：`a / (1 - b + 1e-6)`。`BLEND_MODES` 中的实现应包含此项。

### Colorburn 除以零

`colorburn(a, b) = 1 - (1-a) / b`。当 `b = 0`（纯黑像素）时，会发生除零。

**修复方法**：添加 epsilon：`1 - (1-a) / (b + 1e-6)`。

### Multiply 始终会压暗

`multiply(a, b) = a * b`。由于两个操作数都在 [0,1] 范围内，结果始终 <= min(a,b)。切勿将 multiply 用作反馈混合模式，否则画面会在几帧内变黑。

**修复方法**：反馈请使用 `screen`，或使用低不透明度的 `add`。

---

## 多进程

### Pickle 序列化限制

`ProcessPoolExecutor` 通过 pickle 序列化函数参数。这会限制能够传递给 worker 的内容：

| 可以 Pickle | 无法 Pickle |
|-----------|---------------|
| 模块级函数（`def fx_foo():`） | Lambda（`lambda x: x + 1`） |
| 字典、列表、numpy 数组 | 闭包（在函数内部定义的函数） |
| 类实例（带 `__reduce__`） | 实例方法 |
| 字符串、数字 | 文件句柄、socket |

**影响**：SCENES 表中引用的所有场景函数都必须使用 `def` 在模块级别定义。如果使用 lambda 或闭包，会收到：

```
_pickle.PicklingError: Can't pickle <function <lambda> at 0x...>
```

**修复方法**：在模块顶层定义所有场景函数。在 `_render_vf()` 内部作为 val_fn/hue_fn 使用的 Lambda 不受影响，因为它们在 worker 进程内执行，不会跨进程边界进行 pickle 序列化。

### macOS spawn 与 Linux fork

在 macOS 上，`multiprocessing` 默认使用 `spawn`（完整序列化）。在 Linux 上，默认使用 `fork`（写时复制）。这意味着：

- **macOS**：每个 worker 都会收到序列化的特征数组（30 秒视频约为 57KB，但会随时长增长）。每个 worker 都会重新导入整个模块。
- **Linux**：特征数组通过 COW 共享。Worker 会继承父进程的内存。

**影响**：在 macOS 上，模块级代码（如 `detect_hardware()`）会在每个 worker 进程中运行。如果它有副作用（例如调用子进程），这些操作会发生 N+1 次。

### 每个 Worker 的状态隔离

每个 worker 都会创建自己的：
- `Renderer` 实例（带全新的网格缓存）
- `FeedbackBuffer`（反馈不会跨越场景边界）
- 随机种子（`random.seed(hash(seg_id) + 42)`）

这意味着：
- 粒子状态不会在场景之间延续（符合预期）
- 反馈拖影会在场景切换时重置（符合预期）
- `np.random` 状态**不会**由 `random.seed()` 设定种子——它们使用独立的 RNG

**确定性噪声的修复方法**：显式使用 `np.random.RandomState(seed)`：

```python
rng = np.random.RandomState(hash(seg_id) + 42)
noise = rng.random((rows, cols))
```

---

## 亮度问题

### 色调映射后场景仍然过暗

如果场景经过色调映射后仍然过暗，请检查：

1. **Gamma 过高**：对于含破坏性后处理的场景，将 gamma 降至 0.5–0.6
2. **Shader 破坏亮度**：shader 链中的 Solarize、posterize 或对比度调整可能会抵消色调映射的效果。将破坏性 shader 移到链中更靠前的位置，或提高 gamma 以作补偿。
3. **使用 multiply 的反馈**：Multiply 反馈会逐帧压暗。请切换为 screen 或 add。
4. **场景中的 Overlay 混合**：如果场景函数对暗色图层使用 `blend_canvas(..., "overlay", ...)`，请切换为 screen。

### 诊断：测试帧亮度

```bash
python reel.py --test-frame 10.0
# Output: Mean brightness: 44.3, max: 255
```

如果均值 < 20，则场景需要调整。常见修复方法：
- 降低 SCENES 条目中的 gamma
- 将内部混合模式从 overlay/multiply 改为 screen/add
- 增大值场乘数（例如 `vf_plasma(...) * 1.5`）
- 检查 shader 链中是否存在过强的 solarize 或 threshold

### v1 亮度模式（已弃用）

旧模式使用线性乘数：

```python
# OLD — don't use
canvas = np.clip(canvas.astype(np.float32) * 2.0, 0, 255).astype(np.uint8)
```

这种方法存在以下问题：
- 暗场景（均值 8）：`8 * 2.0 = 16`——仍然很暗
- 亮场景（均值 130）：`130 * 2.0 = 255`——被裁剪，细节丢失

请改用 `tonemap()`。参见 `composition.md` § 自适应色调映射。

---

## ffmpeg 问题

### 管道死锁

这是头号生产环境 bug。如果使用 `stderr=subprocess.PIPE`：

```python
# DEADLOCK — stderr buffer fills at 64KB, blocks ffmpeg, blocks your writes
pipe = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
```

**修复方法**：始终将 stderr 重定向到文件：

```python
stderr_fh = open(err_path, "w")
pipe = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL, stderr=stderr_fh)
```

### 帧数不匹配

如果写入管道的帧数与 ffmpeg 的预期（由 `-r` 和时长决定）不符，输出可能会出现：
- 末尾缺帧
- 时长不正确
- 音画不同步

**修复方法**：显式计算帧数：`n_frames = int(duration * FPS)`。不要在未验证总数是否匹配的情况下使用 `range(int(start*FPS), int(end*FPS))`。

### Concat 因 “unsafe file name” 而失败

```
[concat @ ...] Unsafe file name
```

**修复方法**：始终使用 `-safe 0`：
```python
["ffmpeg", "-f", "concat", "-safe", "0", "-i", concat_path, ...]
```

---

## 字体问题

### 单元格高度（macOS Pillow）

在某些 macOS Pillow 版本中，`textbbox()` 和 `getbbox()` 返回的高度不正确。请使用 `getmetrics()`：

```python
ascent, descent = font.getmetrics()
cell_height = ascent + descent  # correct
# NOT: font.getbbox("M")[3]  # wrong on some versions
```

### 缺少 Unicode 字形

并非所有字体都能渲染全部 Unicode 字符。如果字符面板中的某个字符不在字体内，该字形会渲染为空白或豆腐块，在输出中表现为暗洞。

**修复方法**：初始化时验证：

```python
all_chars = set()
for pal in [PAL_DEFAULT, PAL_DENSE, PAL_RUNE, ...]:
    all_chars.update(pal)

valid_chars = set()
for c in all_chars:
    if c == " ":
        valid_chars.add(c)
        continue
    img = Image.new("L", (20, 20), 0)
    ImageDraw.Draw(img).text((0, 0), c, fill=255, font=font)
    if np.array(img).max() > 0:
        valid_chars.add(c)
    else:
        log(f"WARNING: '{c}' (U+{ord(c):04X}) missing from font")
```

### 各平台的字体路径

| 平台 | 常见路径 |
|----------|-------------|
| macOS | `/System/Library/Fonts/Menlo.ttc`, `/System/Library/Fonts/Monaco.ttf` |
| Linux | `/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf` |
| Windows | `C:\Windows\Fonts\consola.ttf`（Consolas） |

始终探测多个路径，并妥善回退。参见 `architecture.md` § 字体选择。

---

## 性能

### 较慢的 Shader

一些 shader 使用 Python 循环，在 1080p 下速度非常慢：

| Shader | 问题 | 修复方法 |
|--------|-------|-----|
| `wave_distort` | 逐行 Python 循环 | 使用向量化的高级索引 |
| `halftone` | 三重嵌套循环 | 使用分块归约进行向量化 |
| `matrix rain` | 逐列、逐拖影循环 | 累积索引数组，批量赋值 |

### 渲染时间的扩展规律

如果渲染耗时远超预期：
1. 检查网格数量——每增加一个网格，初始化阶段每帧会增加约 100–150ms
2. 检查粒子数量——将其限制在与质量级别相适应的范围内
3. 检查 shader 数量——每个 shader 会增加 2–25ms
4. 检查效果中是否意外使用了 Python 循环（应仅使用 numpy）

---

## 常见错误

### 使用 `r.S` 与 `S` 参数

v2 场景协议将 `S`（状态字典）作为显式参数传递。但 `S` **就是** `r.S`——它们是同一个对象。两种写法都可行：

```python
def fx_scene(r, f, t, S):
    S["counter"] = S.get("counter", 0) + 1   # via parameter (preferred)
    r.S["counter"] = r.S.get("counter", 0) + 1  # via renderer (also works)
```

为清晰起见，请使用 `S` 参数。显式参数能清楚表明该函数具有持久状态。

### 忘记处理空的特征值

如果音频静默，音频特征默认为 0.0。请通过 `.get()` 使用合理的默认值：

```python
energy = f.get("bass", 0.3)  # default to 0.3, not 0
```

如果默认值设为 0，静默期间效果会变为空白。

### 每帧新建数据，而非更新现有状态

粒子系统中的一个常见 bug：每帧都创建新数组，而不是更新持久状态。

```python
# WRONG — particles reset every frame
S["px"] = []
for _ in range(100):
    S["px"].append(random.random())

# RIGHT — only initialize once, update each frame
if "px" not in S:
    S["px"] = []
# ... emit new particles based on beats
# ... update existing particles
```

### 未裁剪值场

值场应位于 [0, 1] 范围内。如果超出此范围，`val2char()` 会产生索引错误：

```python
# WRONG — vf_plasma() * 1.5 can exceed 1.0
val = vf_plasma(g, f, t, S) * 1.5

# RIGHT — clip after scaling
val = np.clip(vf_plasma(g, f, t, S) * 1.5, 0, 1)
```

`_render_vf()` 辅助函数会自动裁剪，但如果要构建自定义场景，请显式进行裁剪。

## 亮度最佳实践

- 使用密集的动态背景——绝不使用纯黑，应始终填满网格
- Vignette 最小值限制为 0.15（而非 0.12）
- Bloom threshold 设为 130（而非 170），让更多像素参与辉光
- 对暗色 ASCII 图层使用 `screen` 混合模式（而非 `overlay`）——overlay 会对暗值取平方：`2 * 0.12 * 0.12 = 0.03`
- FeedbackBuffer 的 decay 最小值为 0.5——低于此值时，反馈消失得太快，难以看到
- 值场下限：`vf * 0.8 + 0.05` 可确保没有单元格真正为零
- 各场景的 gamma 覆盖值：默认 0.75、solarize 0.55、posterize 0.50、亮场景 0.85
- 尽早测试帧：在提交完整渲染前，先渲染关键时间戳的单帧

**完整渲染前的快速检查清单：**
1. 渲染 3 个测试帧（开始、中间、结束）
2. 检查色调映射后是否满足 `canvas.mean() > 8`
3. 检查是否没有场景在视觉上呈现纯黑
4. 验证各部分存在变化（每个场景使用不同的 bg/palette/color）
5. 确认 shader 链包含 bloom（threshold 130）
6. 确认 vignette strength ≤ 0.25
