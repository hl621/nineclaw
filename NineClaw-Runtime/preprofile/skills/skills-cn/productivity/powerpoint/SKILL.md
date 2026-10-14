---
name: powerpoint
description: "创建、读取和编辑 .pptx 演示文稿、幻灯片、备注与模板。"
version: 2.0.0
author: Anthropic (adapted by Nous Research)
license: Proprietary. LICENSE.txt has complete terms
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [PowerPoint, PPTX, Presentations, Office, Productivity]
    category: productivity
    related_skills: [docx, xlsx, pdf]
---

# PowerPoint 技能

创建、读取和编辑 PowerPoint 演示文稿，包括使用 pptxgenjs 从零生成、通过直接操作 XML 基于模板编辑、演讲者备注、图表以及设计质量检查。`.pptx` 是由 XML 文件组成的 ZIP 压缩包。

## 何时使用

只要任务以任何方式涉及 .pptx 或 .potx 文件（作为输入、输出或两者兼有），都应使用此技能：创建幻灯片、推介材料或演示文稿；读取任何 .pptx 或从中提取文本；编辑现有演示文稿；合并或拆分幻灯片文件；处理模板（.potx）、版式、演讲者备注或批注。当用户提到“deck”“slides”“presentation”（或对应的中文“演示文稿”“幻灯片”），或引用 .pptx/.potx 文件名时，请触发此技能。

## 前置条件

```bash
npm ls pptxgenjs --depth=0 2>/dev/null | grep -q pptxgenjs || npm install pptxgenjs
pip install "markitdown[pptx]" Pillow defusedxml lxml
which soffice || sudo apt install -y libreoffice     # rendering/QA
which pdftoppm || sudo apt install -y poppler-utils  # PDF → images
```

macOS：`brew install libreoffice poppler`。生成的演示文稿若使用图标，还需安装 `react-icons react react-dom sharp`（npm）。

## 快速参考

| 任务 | 方法 |
|---|---|
| **创建**新演示文稿 | 编写 `pptxgenjs` 脚本——参阅下文注意事项 |
| **编辑**现有演示文稿，或基于模板构建 | 解压 → 编辑 `ppt/slides/slideN.xml` → 压缩 |
| **读取**内容 | `markitdown deck.pptx`（在 `<!-- Slide number: N -->` 标记下，每张幻灯片对应一个区块）；可视化网格：`python scripts/thumbnail.py deck.pptx` |

## 脚本

路径均相对于此技能目录。其余内容均为普通 Python、`node` 或 shell。

| 脚本 | 功能 |
|---|---|
| `scripts/thumbnail.py deck.pptx [prefix]` | 生成每张幻灯片带标签的网格，用于选择模板版式。仅支持 `.pptx`。请传入 `prefix`——其默认值为 `thumbnails`，会覆盖同一目录中其他演示文稿的网格 |
| `scripts/add_slide.py unpacked/ slide2.xml [--after slideN.xml]` | 复制幻灯片（或 `slideLayoutN.xml`），并完成所有包登记工作。也可直接接受 `.pptx`，并通过 `-o out.pptx` 输出结果 |
| `scripts/clean.py unpacked/` | 删除不再被引用的幻灯片、媒体和关系文件。请在 `<p:sldIdLst>` 最终确定**之后**运行 |
| `scripts/office/validate.py deck.pptx [--original src.pptx]` | 检查 XML 模式（schema）、关系、内容类型、图表和幻灯片；每项失败都会指出修复方法。对任何基于模板的演示文稿传入 `--original`——它会以模板为基线执行 XML 模式检查，避免将模板自身的 XSD 错误误认为你的错误 |
| `scripts/office/soffice.py --headless --convert-to pdf deck.pptx` | LibreOffice 包装器——直接使用 `soffice` 会在沙箱环境中挂起 |

## 使用 pptxgenjs 创建演示文稿——注意事项

编写脚本并调用 `require('pptxgenjs')`。模型了解该 API；以下是容易踩坑之处：

- **添加幻灯片前设置 `pres.layout`。** 默认画布为 `LAYOUT_16x9` = **10" × 5.625"**，而不是 13.3" 宽。超出边缘的坐标仍会写入而不会被限制，结果是形状根本不在幻灯片上。（`LAYOUT_WIDE` 为 13.3" × 7.5"。）
- **十六进制颜色：切勿包含 `#`，也不要使用 8 位值。** `color: "FF0000"`。`"#FF0000"` 和将 alpha 编入十六进制值的写法（`"00000020"`）都会**损坏文件**。半透明设置：填充和图像使用 `transparency: 0-100`，阴影使用 `opacity: 0.0-1.0`——用错对象时会被静默忽略。
- **pptxgenjs 会就地修改选项对象**（首次使用时将值转换为 EMU）。切勿共享同一个 `shadow`/选项对象来执行两次 `add*` 调用——每次都应新建对象。
- **阴影 `offset` 必须 ≥ 0**——负偏移会损坏文件。要让阴影向上投射，请使用 `angle: 270` 和正偏移。
- **`letterSpacing` 会被静默忽略**——正确选项是 `charSpacing`。
- **列表：** 每一项都设置 `bullet: true`，切勿使用字面量 `•`（会渲染双重项目符号）。除最后一项外，每个数组项都设置 `breakLine: true`。项目符号段落间距使用 `paraSpaceAfter`，不要使用 `lineSpacing`（会产生巨大间隙）。
- **每个输出文件使用一个 `new pptxgen()`**——切勿复用实例。
- **`rectRadius` 仅适用于 `ROUNDED_RECTANGLE`**，不适用于 `RECTANGLE`。
- **不支持渐变填充**——请改用渐变图像作为背景。
- **文本框内置内边距**——当文本必须与同一 x 坐标上的形状、线条或图标对齐时，请设置 `margin: 0`。
- **演讲者备注应放入 `slide.addNotes("...")`**（纯文本，每张幻灯片调用一次），切勿放在幻灯片文本框中。
- **保持图表为原生格式。** 对 PowerPoint 能绘制的所有图表使用 `addChart()`（组合图传入 `{type, data, options}` 数组）。对于库未暴露的 PowerPoint 原生功能（趋势线、误差线），请自行计算附加系列或对生成的 OOXML 进行后处理——不要回退为渲染图像。只有 PowerPoint 没有原生形式的图表类型（桑基图、网络图、弦图）才应以图像插入。
- **默认图表渲染非常简陋**——没有标题、数据标签，配色也过时。请设置 `showTitle` + `title`、`showValue: true` + `dataLabelPosition`、来自配色方案的 `chartColors: [...]`，并弱化图框（`catAxisLabelColor`/`valAxisLabelColor`、`valGridLine: { color, size }`、`catGridLine: { style: "none" }`；单系列设置 `showLegend: false`）。
- **在堆积条形图或柱形图中，`dataLabelPosition` 必须是 `ctr`、`inEnd` 或 `inBase`。** `outEnd` 会**损坏文件**。
- **使用 `secondaryValAxis`/`secondaryCatAxis` 的组合系列，需要在图表选项中同时提供 `valAxes` 和 `catAxes`，且各包含两个条目。** 否则 pptxgenjs 会写入从未声明的坐标轴 *id*，PowerPoint 将**丢弃该图表**并报告文件损坏。仅提供 `valAxes` 不够。
- **执行 `writeFile()` 后，运行 `python scripts/office/validate.py deck.pptx`。** 它会报告上述两种图表错误，以及 PowerPoint 无法接受的幻灯片 XML 缺陷，并指出每项修复方法。请在生成器中修复，不要手动编辑打包后的 XML。
- **切勿重排 `<p:presentation>` 的子元素。** pptxgenjs 会将 `<p:notesMasterIdLst>` 写在 `<p:sldIdLst>` 之后，并让两个母版指向同一主题部件。PowerPoint 能正常读取这种结构；一旦移动该元素，同一演示文稿就会无法打开。
- **图标：** 将 `react-icons` 渲染为 SVG（`ReactDOMServer.renderToStaticMarkup`），使用 `sharp` 以 ≥256px 栅格化，再通过 `addImage({ data: "image/png;base64," + buf.toString("base64") })` 插入——必须包含 `image/png;base64,` 前缀。

## 编辑现有演示文稿和模板

首先选择版式：`python scripts/thumbnail.py template.pptx template-thumbs` 会为每张幻灯片生成带标签的网格，并打印所创建的文件——`template-thumbs.jpg`；超过 12 张幻灯片后拆分为 `template-thumbs-N.jpg`。**始终传入以演示文稿命名的第二个参数。** 默认值为 `thumbnails`，因此在同一目录为两个演示文稿生成缩略图时，会静默覆盖彼此的网格（这只用于模板分析——视觉质量检查需要[转换为图像](#converting-to-images)中的全分辨率渲染；该脚本仅接受 `.pptx`，因此应先将 `.potx` 复制为 `.pptx` 文件名）。结合 `markitdown`，将每个内容部分映射到合适的模板幻灯片，并交替采用不同版式——不要把每个部分都放在同一种“标题 + 项目符号”幻灯片上。

```bash
python3 -c "import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall('unpacked')" deck.pptx
python scripts/add_slide.py unpacked/ slide2.xml --after slide2.xml   # duplicate a slide (or slideLayoutN.xml); prints the new slide's path
# reorder / delete slides = edit <p:sldIdLst> in ppt/presentation.xml
python scripts/clean.py unpacked/                                     # after deletions: removes orphaned slides, media, rels
# edit slide content in ppt/slides/slideN.xml
(cd unpacked && rm -f ../out.pptx && zip -Xr ../out.pptx .)           # zip from INSIDE the dir; rm first or deleted parts survive
python scripts/office/validate.py out.pptx --original deck.pptx
```

- **在编辑任何幻灯片内容之前，完成所有结构工作——添加、删除、重排。** `add_slide.py` 会逐字复制幻灯片文件，因此在编辑后再复制会克隆已编辑内容；`clean.py` 会删除 `<p:sldIdLst>` 中缺失的任何幻灯片，包括你刚写入的幻灯片。
- **切勿手动复制幻灯片文件**——`add_slide.py` 会完成新幻灯片所需的全部登记，并报告创建内容。它也可直接操作文件：`add_slide.py deck.pptx slide2.xml -o out.pptx`——**务必传入 `-o`，否则会就地重写输入演示文稿。** 复制的幻灯片仍会*引用*源幻灯片的图表/SmartArt/嵌入对象部件，而不是克隆它们，因此编辑一张幻灯片的图表会改变另一张。
- **如果使用 `python-pptx`**，请注意它无法完成三件事：复制幻灯片（唯一入口是 `add_slide(layout)`）；通过 `text_frame.text = "..."` 保留格式（该操作会将段落压缩成一个无样式文本片段——应改为赋值 `run.text`）；读取大多数模板美术素材使用的 SVG/EMF（`add_picture` 会引发 `UnidentifiedImageError`）。
- 旧式 `.ppt` 必须先转换：`python scripts/office/soffice.py --headless --convert-to pptx file.ppt`。`.potx` 模板的解包和打包方式相同——输出仍保留 `.potx` 扩展名。
- 要复用模板图标或图像，请复制已包含它的幻灯片或版式。

填写模板时：

- 如果编写 XML 转换脚本，请使用 `defusedxml.minidom` 解析——通过 `xml.etree.ElementTree` 往返处理 OOXML 会重写命名空间前缀并损坏演示文稿。
- **模板槽位 ≠ 源项目。** 如果模板显示 4 名团队成员，而你只有 3 名，请删除第 4 名成员的整个组（图像 + 文本框），而不只是文字；然后在质量检查中检查是否有孤立视觉元素。
- 每个列表项使用一个 `<a:p>`——切勿将多个项目拼接为一个段落。复制同级 `<a:pPr>` 以保留间距，并将 `b="1"` 写在 `<a:rPr>` 上，用于标题、章节标题和行内标签（`Status:`、`Owner:`）。
- 让项目符号从版式继承；只有需要覆盖时才添加 `<a:buChar>`、`<a:buAutoNum>`（编号）或 `<a:buNone>`——切勿在文本中使用字面量 `•`。
- 带有前导或尾随空格的文本，需要设置 `xml:space="preserve"`，并将其写在 `<a:t>` 上。

## 设计思路

**不要制作乏味的幻灯片。** 白底上的普通项目符号无法给人留下深刻印象。请为每张幻灯片考虑以下创意。

### 开始之前

- **选择大胆且由内容驱动的配色方案**：配色应让人感觉是专为当前主题设计的。如果将这些颜色换到完全不同的演示文稿中仍然“适用”，说明选择还不够具体。
- **突出主次，而非平均分配**：一种颜色应占主导（60-70% 的视觉权重），搭配 1-2 种辅助色和一种鲜明强调色。切勿让所有颜色权重相同。
- **深浅对比**：标题页和结论页使用深色背景，内容页使用浅色背景（“三明治”结构）；也可全程使用深色，营造高级感。
- **坚持一种视觉母题**：选择一个鲜明元素并反复使用，例如圆角图像框、彩色圆圈中的图标。让它贯穿每张幻灯片。**不要使用色条或强调色条纹作为视觉母题**（参阅“避免事项”列表）。

### 配色方案

选择与主题匹配的颜色——不要默认使用普通蓝色。可参考以下配色：

| 主题 | 主色 | 辅色 | 强调色 |
|-------|---------|-----------|--------|
| **午夜商务** | `1E2761`（海军蓝） | `CADCFC`（冰蓝） | `FFFFFF`（白色） |
| **森林与苔藓** | `2C5F2D`（森林绿） | `97BC62`（苔藓绿） | `F5F5F5`（乳白） |
| **珊瑚活力** | `F96167`（珊瑚色） | `F9E795`（金色） | `2F3C7E`（海军蓝） |
| **暖陶土** | `B85042`（陶土色） | `E7E8D1`（沙色） | `A7BEAE`（鼠尾草绿） |
| **海洋渐变** | `065A82`（深蓝） | `1C7293`（蓝绿色） | `21295C`（午夜蓝） |
| **炭灰极简** | `36454F`（炭灰） | `F2F2F2`（灰白） | `212121`（黑色） |
| **蓝绿信赖** | `028090`（蓝绿色） | `00A896`（海沫绿） | `02C39A`（薄荷绿） |
| **浆果与奶油** | `6D2E46`（浆果色） | `A26769`（灰玫瑰色） | `ECE2D0`（乳白） |
| **鼠尾草宁静** | `84B59F`（鼠尾草绿） | `69A297`（桉叶绿） | `50808E`（石板色） |
| **醒目樱桃红** | `990011`（樱桃红） | `FCF6F5`（灰白） | `2F3C7E`（海军蓝） |

### 每张幻灯片

**每张幻灯片都需要视觉元素**——图像、图表、图标或形状。纯文本幻灯片很难给人留下印象。

**版式选项：**
- 双栏（左侧文本、右侧插图）
- 图标 + 文本行（彩色圆圈内的图标、粗体标题、下方说明）
- 2x2 或 2x3 网格（一侧为图像，另一侧为内容块网格）
- 半出血图像（占满左侧或右侧），上叠内容

**数据展示：**
- 大号统计数字强调（60-72pt 大数字，下方配小标签）
- 对比栏（前后对比、优缺点、并列选项）
- 时间线或流程图（编号步骤、箭头）

**视觉润色：**
- 在章节标题旁使用彩色小圆圈中的图标
- 对关键统计数据或标语使用斜体强调文本

### 字体排印

**写入 .pptx 的字体名称由用户的 PowerPoint 渲染，而不是由当前环境渲染。** 视觉质量检查通过 LibreOffice 渲染；它会替换缺失字体，而某些替代字体宽度不同，因此质量检查预览可能显示真实演示文稿中不存在的文本溢出（或错误地显示适配）。为确保质量检查可信：

- **安全字体**（在质量检查中按真实宽度渲染，且随 Office 提供）：**Arial、Calibri、Cambria、Times New Roman、Courier New、Bookman Old Style、Century Schoolbook**。正文及任何对适配要求较高的内容均使用这些字体。
- **个性鲜明且质量检查零风险的标题**：将安全列表中的衬线标题字体（Cambria、Bookman Old Style、Century Schoolbook）与安全列表中的无衬线正文字体（Calibri 或 Arial）搭配。
- **如果用户要求使用安全列表以外的字体**（例如 Georgia 或 Trebuchet MS）：在用户要求的位置使用，但为相应容器额外预留约 10% 空间，不要相信这些元素在质量检查中的文本适配结果。
- **质量检查不可靠的字体**（替代字体宽度不同，溢出检查可能有误）：Georgia、Trebuchet MS、Impact、Arial Black、Garamond、Consolas、Palatino Linotype。Calibri Light 的替代结果因环境而异，也应视为不可靠。
- **切勿默认使用 Aptos**——Office 2023 年后的默认字体在此处没有度量兼容的替代字体，旧版 Office 安装中也缺少它，因此两端都不可靠。

| 元素 | 大小 |
|---------|------|
| 幻灯片标题 | 36-44pt 粗体 |
| 章节标题 | 20-24pt 粗体 |
| 正文 | 14-16pt |
| 图注 | 10-12pt 弱化色 |

### 间距

- 页边距至少 0.5"
- 内容块之间留 0.3-0.5"
- 保留呼吸空间——不要填满每一寸

### 避免事项（常见错误）

- **不要重复使用同一种版式**——在不同幻灯片中灵活搭配分栏、卡片和重点标注
- **不要将正文居中**——段落和列表左对齐；仅标题居中
- **不要忽视字号对比**——标题需达到 36pt 以上，才能从 14-16pt 正文中脱颖而出
- **不要默认使用蓝色**——选择能体现具体主题的颜色
- **不要随意混用间距**——选择 0.3" 或 0.5" 间隙并保持一致
- **不要只设计一张幻灯片，而让其余页面保持朴素**——要么贯彻完整风格，要么全程保持简洁
- **不要创建纯文本幻灯片**——添加图像、图标、图表或其他视觉元素；避免只有标题 + 项目符号
- **不要忘记文本框内边距**——将线条或形状与文本边缘对齐时，在文本框上设置 `margin: 0`，或偏移形状以补偿内边距
- **不要使用低对比度元素**——图标和文本都必须与背景形成强对比
- **绝不要在标题下方使用强调线**——这是 AI 生成幻灯片的典型特征；请改用留白或背景色
- **绝不要添加装饰性色条或强调条纹**——包括：横跨幻灯片宽度的页眉/页脚条、一侧边缘的竖向侧栏条纹、卡片或内容块一侧的细强调条，以及矩形的“单边框”。这些看起来像 AI 生成的填充物。若要突出卡片，请使用细微的背景色调、投影或图标，而不是边缘条纹。
- **不要默认使用乳白/米色背景**——未指定背景时，使用白色（`FFFFFF`）或用户的品牌配色；避免 `F5F5DC`、`FAF0E6`、`FAEBD7`、`FFF8E1` 等暖中性色默认值
- **不要交付溢出形状的文本**——如果文本放不下，请减小字号、拆分到多张幻灯片或扩大容器；绝不能让内容被截断或越界

## 质量检查（必需）

首次渲染通常会有一些真实问题，例如重叠、溢出、未对齐。找出并修复这些问题，只重新渲染修改过的幻灯片，然后停止。

### 内容质量检查

```bash
markitdown output.pptx
```

检查内容缺失、拼写错误和顺序错误。

**使用模板时，检查是否残留占位文本：**

```bash
markitdown output.pptx | grep -iE "\bx{3,}\b|lorem|ipsum|\bTODO|\[insert|this.*(page|slide).*layout"
```

如果 grep 返回结果，请先修复，再宣布成功。

### 文件质量检查（必需）

```bash
python scripts/office/validate.py output.pptx                      # built from scratch
python scripts/office/validate.py output.pptx --original src.pptx  # built from a template
```

**如果演示文稿源自模板，始终传入 `--original`。** 模板本身可能包含 XSD 拒绝的部件，因此不带参数运行时，可能报告并非由你造成的失败，而真正的回归也可能混在其中。`--original` 会以模板为基线执行 XML 模式和幻灯片检查。结构检查——关系、内容类型、图表——会忽略 `--original`，无论如何都会报告从模板继承的问题，因此请根据问题本身判断。

pptxgenjs 可能生成 PowerPoint 拒绝打开、而其他所有工具都接受的图表 XML：python-pptx 能打开这些演示文稿，LibreOffice 能渲染，XSD 也能通过。每项失败都会指出修复方法。请在生成器中修复并重新构建。

### 视觉质量检查

将幻灯片转换为图像（参阅[转换为图像](#converting-to-images)），并使用 `vision_analyze` 逐一检查。长时间盯着生成代码后，往往会看到自己预期的结果，而非实际渲染结果，因此请用全新视角检查图像（`delegate_task` 子代理很适合此任务）。需要查找的用户可见缺陷包括：

- **文本溢出，或在文本框/幻灯片边界处被截断——首先检查此项。** 这是最常见、且用户始终可见的缺陷。（对于“字体排印”部分所述预览器无法可靠渲染的字体，预览仅为近似值：请相信预留的约 10% 空间，而不是表面上的适配结果。）
- 元素重叠（文本穿过形状、线条穿过文字、元素相互堆叠）
- 来源引用或页脚与上方内容冲突
- 元素间距过小（< 0.3"），或卡片/章节几乎相碰
- 间隙不均（某处大片空白，另一处过于拥挤）
- 距幻灯片边缘的页边距不足（< 0.5"）
- 分栏或相似元素未一致对齐
- 低对比度文本（例如乳白背景上的浅灰文本）
- 替换文本后模板装饰位置错误——例如标题下划线原本适配单行，但替换后的标题换成了两行
- 低对比度图标（例如深色背景上的深色图标，且没有对比色圆圈）
- 文本框过窄，导致过度换行
- 残留占位内容

<a id="converting-to-images"></a>
## 转换为图像

将演示文稿转换为单张幻灯片图像，以便进行视觉检查：

```bash
python scripts/office/soffice.py --headless --convert-to pdf output.pptx
rm -f slide-*.jpg
pdftoppm -jpeg -r 150 output.pdf slide
ls -1 "$PWD"/slide-*.jpg
```

**将上方打印的绝对路径直接传给 `vision_analyze`。** `rm` 会清除之前运行遗留的过期图像。`pdftoppm` 会根据页数补零：少于 10 页的演示文稿使用 `slide-1.jpg`，10-99 页使用 `slide-01.jpg`，100 页以上使用 `slide-001.jpg`。

**修复后，重新运行上方全部四条命令**——必须从编辑后的 `.pptx` 重新生成 PDF，`pdftoppm` 才能反映改动。

## 相关技能

`docx`（Word 文档）、`xlsx`（电子表格）、`pdf`（PDF 处理），以及可选的 `pptx-author`（由模型驱动，可制作达到金融行业专业水准的演示文稿）。
