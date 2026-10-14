---
name: ascii-art
description: "ASCII 艺术：pyfiglet、cowsay、boxes、图像转 ASCII。"
version: 4.0.0
author: 0xbyt4, Hermes Agent
license: MIT
dependencies: []
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [ASCII, Art, Banners, Creative, Unicode, Text-Art, pyfiglet, figlet, cowsay, boxes]
    related_skills: [excalidraw]

---

# ASCII 艺术 Skill

提供多种工具以满足不同的 ASCII 艺术需求。所有工具都是本地 CLI 程序或免费 REST API——无需 API 密钥。

## 工具 1：文本横幅（pyfiglet——本地）

将文本渲染为大型 ASCII 艺术横幅。内置 571 种字体。

### 安装

```bash
pip install pyfiglet --break-system-packages -q
```

### 用法

```bash
python3 -m pyfiglet "YOUR TEXT" -f slant
python3 -m pyfiglet "TEXT" -f doom -w 80    # Set width
python3 -m pyfiglet --list_fonts             # List all 571 fonts
```

### 推荐字体

| 风格 | 字体 | 最适合 |
|-------|------|----------|
| 简洁现代 | `slant` | 项目名称、标题 |
| 粗体块状 | `doom` | 标题、徽标 |
| 大而清晰 | `big` | 横幅 |
| 经典横幅 | `banner3` | 宽屏显示 |
| 紧凑 | `small` | 副标题 |
| 赛博朋克 | `cyberlarge` | 科技主题 |
| 3D 效果 | `3-d` | 启动画面 |
| 哥特风格 | `gothic` | 戏剧化文本 |

### 技巧

- 预览 2–3 种字体，让用户挑选最喜欢的一种
- 短文本（1–8 个字符）最适合 `doom` 或 `block` 等细节丰富的字体
- 长文本更适合 `small` 或 `mini` 等紧凑字体

## 工具 2：文本横幅（asciified API——远程、无需安装）

将文本转换为 ASCII 艺术的免费 REST API，提供 250 多种 FIGlet 字体。直接返回纯文本，无需解析。未安装 pyfiglet 时可使用此工具，也可将其作为快捷替代方案。

### 用法（通过终端 curl）

```bash
# Basic text banner (default font)
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello+World"

# With a specific font
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello&font=Slant"
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello&font=Doom"
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello&font=Star+Wars"
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello&font=3-D"
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello&font=Banner3"

# List all available fonts (returns JSON array)
curl -s "https://asciified.thelicato.io/api/v2/fonts"
```

### 技巧

- 文本参数中的空格需用 `+` 进行 URL 编码
- 响应是纯文本 ASCII 艺术，不带 JSON 包装，可直接显示
- 字体名称区分大小写；使用字体端点获取准确名称
- 任何带 curl 的终端均可使用——无需 Python 或 pip

## 工具 3：Cowsay（消息艺术）

经典工具：将文本放入由 ASCII 角色配上的对话气泡中。

### 安装

```bash
sudo apt install cowsay -y    # Debian/Ubuntu
# brew install cowsay         # macOS
```

### 用法

```bash
cowsay "Hello World"
cowsay -f tux "Linux rules"       # Tux the penguin
cowsay -f dragon "Rawr!"          # Dragon
cowsay -f stegosaurus "Roar!"     # Stegosaurus
cowthink "Hmm..."                  # Thought bubble
cowsay -l                          # List all characters
```

### 可用角色（50 多种）

`beavis.zen`, `bong`, `bunny`, `cheese`, `daemon`, `default`, `dragon`,
`dragon-and-cow`, `elephant`, `eyes`, `flaming-skull`, `ghostbusters`,
`hellokitty`, `kiss`, `kitty`, `koala`, `luke-koala`, `mech-and-cow`,
`meow`, `moofasa`, `moose`, `ren`, `sheep`, `skeleton`, `small`,
`stegosaurus`, `stimpy`, `supermilker`, `surgery`, `three-eyes`,
`turkey`, `turtle`, `tux`, `udder`, `vader`, `vader-koala`, `www`

### 眼睛/舌头修饰参数

```bash
cowsay -b "Borg"       # =_= eyes
cowsay -d "Dead"       # x_x eyes
cowsay -g "Greedy"     # $_$ eyes
cowsay -p "Paranoid"   # @_@ eyes
cowsay -s "Stoned"     # *_* eyes
cowsay -w "Wired"      # O_O eyes
cowsay -e "OO" "Msg"   # Custom eyes
cowsay -T "U " "Msg"   # Custom tongue
```

## 工具 4：Boxes（装饰边框）

在任意文本周围绘制装饰性的 ASCII 艺术边框/画框。内置 70 多种设计。

### 安装

```bash
sudo apt install boxes -y    # Debian/Ubuntu
# brew install boxes         # macOS
```

### 用法

```bash
echo "Hello World" | boxes                    # Default box
echo "Hello World" | boxes -d stone           # Stone border
echo "Hello World" | boxes -d parchment       # Parchment scroll
echo "Hello World" | boxes -d cat             # Cat border
echo "Hello World" | boxes -d dog             # Dog border
echo "Hello World" | boxes -d unicornsay      # Unicorn
echo "Hello World" | boxes -d diamonds        # Diamond pattern
echo "Hello World" | boxes -d c-cmt           # C-style comment
echo "Hello World" | boxes -d html-cmt        # HTML comment
echo "Hello World" | boxes -a c               # Center text
boxes -l                                       # List all 70+ designs
```

### 与 pyfiglet 或 asciified 组合使用

```bash
python3 -m pyfiglet "HERMES" -f slant | boxes -d stone
# Or without pyfiglet installed:
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=HERMES&font=Slant" | boxes -d stone
```

## 工具 5：TOIlet（彩色文本艺术）

类似 pyfiglet，但支持 ANSI 彩色效果和视觉滤镜，非常适合制作吸睛的终端效果。

### 安装

```bash
sudo apt install toilet toilet-fonts -y    # Debian/Ubuntu
# brew install toilet                      # macOS
```

### 用法

```bash
toilet "Hello World"                    # Basic text art
toilet -f bigmono12 "Hello"            # Specific font
toilet --gay "Rainbow!"                 # Rainbow coloring
toilet --metal "Metal!"                 # Metallic effect
toilet -F border "Bordered"             # Add border
toilet -F border --gay "Fancy!"         # Combined effects
toilet -f pagga "Block"                 # Block-style font (unique to toilet)
toilet -F list                          # List available filters
```

### 滤镜

`crop`、`gay`（彩虹）、`metal`、`flip`、`flop`、`180`、`left`、`right`、`border`

**注意**：toilet 使用 ANSI 转义码输出颜色——可在终端中正常显示，但在某些环境中可能无法渲染（例如纯文本文件、部分聊天平台）。

## 工具 6：图像转 ASCII 艺术

将图像（PNG、JPEG、GIF、WEBP）转换为 ASCII 艺术。

### 选项 A：ascii-image-converter（推荐、现代）

```bash
# Install
sudo snap install ascii-image-converter
# OR: go install github.com/TheZoraiz/ascii-image-converter@latest
```

```bash
ascii-image-converter image.png                  # Basic
ascii-image-converter image.png -C               # Color output
ascii-image-converter image.png -d 60,30         # Set dimensions
ascii-image-converter image.png -b               # Braille characters
ascii-image-converter image.png -n               # Negative/inverted
ascii-image-converter https://url/image.jpg      # Direct URL
ascii-image-converter image.png --save-txt out   # Save as text
```

### 选项 B：jp2a（轻量级，仅支持 JPEG）

```bash
sudo apt install jp2a -y
jp2a --width=80 image.jpg
jp2a --colors image.jpg              # Colorized
```

## 工具 7：搜索现成 ASCII 艺术

从 Web 搜索精选 ASCII 艺术。使用 `terminal` 配合 `curl`。

### 来源 A：ascii.co.uk（推荐用于现成艺术）

按主题整理的大型经典 ASCII 艺术集合。作品位于 HTML `<pre>` 标签内。使用 curl 获取页面，再用一小段 Python 代码提取作品。

**URL 模式：** `https://ascii.co.uk/art/{subject}`

**第 1 步——获取页面：**

```bash
curl -s 'https://ascii.co.uk/art/cat' -o /tmp/ascii_art.html
```

**第 2 步——从 pre 标签提取作品：**

```python
import re, html
with open('/tmp/ascii_art.html') as f:
    text = f.read()
arts = re.findall(r'<pre[^>]*>(.*?)</pre>', text, re.DOTALL)
for art in arts:
    clean = re.sub(r'<[^>]+>', '', art)
    clean = html.unescape(clean).strip()
    if len(clean) > 30:
        print(clean)
        print('\n---\n')
```

**可用主题**（用作 URL 路径）：
- 动物：`cat`、`dog`、`horse`、`bird`、`fish`、`dragon`、`snake`、`rabbit`、`elephant`、`dolphin`、`butterfly`、`owl`、`wolf`、`bear`、`penguin`、`turtle`
- 物品：`car`、`ship`、`airplane`、`rocket`、`guitar`、`computer`、`coffee`、`beer`、`cake`、`house`、`castle`、`sword`、`crown`、`key`
- 自然：`tree`、`flower`、`sun`、`moon`、`star`、`mountain`、`ocean`、`rainbow`
- 角色：`skull`、`robot`、`angel`、`wizard`、`pirate`、`ninja`、`alien`
- 节日：`christmas`、`halloween`、`valentine`

**技巧：**
- 保留艺术家的签名/缩写——这是重要礼仪
- 每页包含多件作品——为用户选择最好的一件
- 通过 curl 可稳定使用，无需 JavaScript

### 来源 B：GitHub Octocat API（有趣的彩蛋）

返回一只随机 GitHub Octocat 及一句睿智名言。无需身份验证。

```bash
curl -s https://api.github.com/octocat
```

## 工具 8：趣味 ASCII 实用工具（通过 curl）

这些免费服务直接返回 ASCII 艺术，非常适合增添趣味内容。

### ASCII 艺术二维码

```bash
curl -s "qrenco.de/Hello+World"
curl -s "qrenco.de/https://example.com"
```

### ASCII 艺术天气

```bash
curl -s "wttr.in/London"          # Full weather report with ASCII graphics
curl -s "wttr.in/Moon"            # Moon phase in ASCII art
curl -s "v2.wttr.in/London"       # Detailed version
```

## 工具 9：由 LLM 生成自定义艺术（后备方案）

当上述工具无法满足需求时，使用以下 Unicode 字符直接生成 ASCII 艺术：

### 字符表

**框线字符：** `╔ ╗ ╚ ╝ ║ ═ ╠ ╣ ╦ ╩ ╬ ┌ ┐ └ ┘ │ ─ ├ ┤ ┬ ┴ ┼ ╭ ╮ ╰ ╯`

**方块元素：** `░ ▒ ▓ █ ▄ ▀ ▌ ▐ ▖ ▗ ▘ ▝ ▚ ▞`

**几何图形与符号：** `◆ ◇ ◈ ● ○ ◉ ■ □ ▲ △ ▼ ▽ ★ ☆ ✦ ✧ ◀ ▶ ◁ ▷ ⬡ ⬢ ⌂`

### 规则

- 最大宽度：每行 60 个字符（终端安全）
- 最大高度：横幅 15 行，场景 25 行
- 仅使用等宽字体：输出必须能在固定宽度字体中正确渲染

## 决策流程

1. **将文本制作成横幅** → 若已安装则使用 pyfiglet，否则通过 curl 使用 asciified API
2. **将消息包装成趣味角色艺术** → cowsay
3. **添加装饰边框/画框** → boxes（可与 pyfiglet/asciified 组合）
4. **绘制特定事物**（猫、火箭、龙）→ 通过 curl 获取 ascii.co.uk 内容并解析
5. **将图像转换为 ASCII** → ascii-image-converter 或 jp2a
6. **二维码** → 通过 curl 使用 qrenco.de
7. **天气/月相艺术** → 通过 curl 使用 wttr.in
8. **自定义/创意内容** → 使用 Unicode 字符表由 LLM 生成
9. **任意工具未安装** → 安装该工具，或退回下一选项
