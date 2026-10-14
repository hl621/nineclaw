---
name: docx
description: "创建、读取和编辑 Word .docx 文档及模板。"
version: 1.0.0
author: Anthropic (adapted by Nous Research)
license: Proprietary. LICENSE.txt has complete terms
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Word, DOCX, Documents, Office, Productivity]
    category: productivity
    related_skills: [pdf, xlsx, powerpoint, ocr-and-documents]
---

# DOCX 技能

创建、读取和编辑 Word 文档，包括报告、备忘录、信函、信头、目录、修订（红线修改）和批注。`.docx` 是由 XML 文件组成的 ZIP 归档；本技能既涵盖高层级的创建方法，也涵盖精细的 XML 编辑。

## 适用场景

当用户希望创建、读取、编辑或处理 Word 文档（.docx）或 Word 模板（.dotx）时，应使用此技能。触发条件包括：提到“Word 文档”、“.docx”或“.dotx”；要求以 Word 文件形式交付“报告”“备忘录”“信函”或类似内容；从 .docx 文件中提取或重组内容；在 Word 文件中查找和替换；插入图片；处理修订或批注。不要用于 PDF（参见 `pdf` 技能）、电子表格（`xlsx`）或演示文稿（`powerpoint`）。

## 前置条件

```bash
npm ls docx --depth=0 2>/dev/null | grep -q docx || npm install docx   # creation (docx-js)
pip show pandoc >/dev/null 2>&1 || true; which pandoc || sudo apt install -y pandoc   # reading
which soffice || sudo apt install -y libreoffice     # rendering/verification
which pdftoppm || sudo apt install -y poppler-utils  # PDF → images
pip install defusedxml lxml   # validation scripts
```

macOS：`brew install pandoc libreoffice poppler`。

## 快速参考

| 任务 | 方法 |
|---|---|
| **创建**新文档 | 编写一个使用 `docx`（npm）的脚本——参见下文的注意事项 |
| **编辑**现有文档 | `unzip` → 编辑 `word/document.xml` → `zip`（docx-js 无法打开现有文件） |
| **读取**内容 | `pandoc -t markdown file.docx`（或使用会自动提取 .docx 文本的 `read_file`） |

> 下文中的脚本路径均相对于本技能目录。

## 使用 docx-js 创建文档——注意事项

编写脚本并调用 `require('docx')`。模型了解其 API；以下是容易踩坑之处：

- **页面大小默认为 A4。** 如需 US Letter，请设置 `page: { size: { width: 12240, height: 15840 } }`（单位为 DXA；1440 = 1″）。
- **横向页面：**传入纵向页面尺寸并设置 `orientation: PageOrientation.LANDSCAPE`；docx-js 会在内部交换宽度和高度。
- **表格需要设置两套宽度：**既要在表格上设置 `columnWidths`，也要在每个单元格上设置 `width`，两者都使用 `WidthType.DXA`（PERCENTAGE 在 Google Docs 中会失效）。各列宽度之和必须等于表格宽度。
- **表格底纹：**使用 `ShadingType.CLEAR`，绝不要使用 `SOLID`（会渲染成黑色）。
- **列表：**绝不要直接插入 `•`；应使用 `numbering` 配置，并将其设置为 `LevelFormat.BULLET`。
- **`ImageRun` 必须包含 `type:`**（`"png"`、`"jpg"` 等）。
- **`PageBreak` 必须位于 `Paragraph` 内。**
- **绝不要使用 `\n`**；应使用独立的 `Paragraph` 元素。
- **目录：**标题必须使用内置的 `HeadingLevel.*`；自定义标题样式必须设置 `outlineLevel`，否则不会出现在目录中。
- **不要用表格充当水平分隔线**；应改用段落的下边框。
- **点引导符／同一行右对齐：**使用 `PositionalTab`（`alignment: PositionalTabAlignment.RIGHT`、`leader: PositionalTabLeader.DOT`），并将其置于 `TextRun` 内；不要用字面量 `.` 或空格填充。

## 验证输出

写入 `.docx` 后，将其渲染并进行目视检查：

```bash
python scripts/office/soffice.py --headless --convert-to pdf output.docx
pdftoppm -jpeg -r 100 output.pdf page
ls page-*.jpg   # then inspect each with vision_analyze
```

`pdftoppm` 会根据总页数的位数，对页码进行前导零填充（`page-01.jpg`…`page-12.jpg`）。

## 编辑现有文档

旧版 `.doc` 文件必须先转换：`python scripts/office/soffice.py --headless --convert-to docx file.doc`。

```bash
unzip -q doc.docx -d unpacked/
find unpacked -type l -delete   # strip symlink entries — docx from external parties is untrusted
python scripts/merge_runs.py unpacked/   # coalesce fragmented runs so text is findable
# edit unpacked/word/document.xml in place — do NOT reformat or pretty-print
(cd unpacked && rm -f ../out.docx && zip -Xr ../out.docx .)
python scripts/office/validate.py out.docx --original doc.docx   # XSD checks; --auto-repair fixes common issues
# redlining? add --author "<the name you redlined under>" to check every edit is tracked
```

Word 会将文本拆分到许多 `<w:r>` 文本片段（run）中（例如修订 ID、拼写检查标记），因此文档中肉眼可见的短语，在 XML 中往往并不是连续字符串。`merge_runs.py` 会合并 `word/document.xml` 中格式完全相同的相邻文本片段，且不会改变内容或渲染结果；它也可以直接接收 `.docx`（`python scripts/merge_runs.py doc.docx -o merged.docx`）。

**修订：**进行红线修改时，请使用 `--author "<the name you redlined under>"` 验证（需要 `--original`）。它会报告所有未被 `<w:ins>`/`<w:del>` 包裹的文本更改；这类遗漏很容易意外发生，而且在接受修订后的视图中不可见。使用 `<w:ins>`/`<w:del>` 包裹文本片段，并设置 `w:id`、`w:author`、`w:date` 属性。在 `<w:del>` 内，文本元素应为 `<w:delText>`，而不是 `<w:t>`。删除的段落标记（`<w:pPr><w:rPr><w:del w:id=".." w:author=".." w:date=".."/></w:rPr></w:pPr>`）表示“将此段落合并到下一段”；因此，要彻底删除一个段落，需要同时添加该标记，并用 `<w:del>` 包裹每个文本片段。`<w:del/>` 必须位于 rPr 其他子元素之前；其顺序由 XML 模式（schema）强制规定。

要生成已接受所有修订的干净副本，请运行：`python scripts/accept_changes.py in.docx out.docx`。

接受删除的段落标记时，应将该段落与下方段落合并，因此所有文本片段都被删除的段落应当消失。Word 会这样处理，但 `accept_changes.py` 和 `pandoc --track-changes=accept` 并不总能做到。两者的失败表现相同：删除文本后仍保留空段落；如果该段落原本自动编号，就会显示为一个多余的空项目符号：

- `pandoc --track-changes=accept` 从不合并段落。
- `accept_changes.py`（LibreOffice）通常能正确合并，但如果被删除段落后紧跟一个空白间隔段落，则不会合并。

无论在哪种视图中出现空项目符号，它都只是该视图的伪影，并非文档缺陷。请在 XML 中检查段落删除情况。

## 批注

批注需要六个相互关联的文件。请使用辅助脚本：如果还要编辑 `document.xml`，请使用目录模式（可省去一次解压和重新压缩）；否则使用直接处理 `.docx` 的模式：

```bash
# Against an already-unpacked directory (preferred when also placing markers)
python scripts/comment.py unpacked/ "Fees & expenses cap is too low"
python scripts/comment.py unpacked/ "Agreed" --parent 0

# Against a .docx directly
python scripts/comment.py contract.docx "This cap is too low" -o annotated.docx
```

该脚本会写入 `comments.xml`、`commentsExtended.xml`、`commentsIds.xml`、`commentsExtensible.xml`、关系文件以及内容类型覆盖项。批注 ID 会自动分配。随后，它会输出 `<w:commentRangeStart>`/`<w:commentRangeEnd>`/`<w:commentReference>` 片段；将其添加到 `word/document.xml`，即可把批注锚定到特定文本。在放置这些标记之前，批注虽然存在，但不可见。

## 常见陷阱

- 不要通过 `xml.etree.ElementTree` 往返处理 OOXML；它会重写命名空间前缀并破坏文件。脚本化转换应使用 `defusedxml.minidom`。
- 必须从解压目录的**内部**进行压缩（`cd unpacked && zip -Xr ../out.docx .`），并先用 `rm` 删除目标文件，否则已删除的部件仍会残留在归档中。

## 验证

1. `python scripts/office/validate.py out.docx --original in.docx`：检查 XML 模式（schema）、关系和内容类型；每项失败都会指出修复方法。
2. 渲染为 PDF → 图片（参见“验证输出”），再用 `vision_analyze` 检查每一页，重点查找损坏的表格、缺失的图片、间距异常和遗留的占位文本。

## 相关技能

`pdf`（PDF 工作）、`xlsx`（电子表格）、`powerpoint`（演示文稿）、`ocr-and-documents`（扫描输入提取）。
