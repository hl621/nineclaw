---
name: pdf
description: "创建、合并、拆分、填写和保护 PDF 文件。"
version: 1.0.0
author: Anthropic (adapted by Nous Research)
license: Proprietary. LICENSE.txt has complete terms
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [PDF, Documents, Forms, Office, Productivity]
    category: productivity
    related_skills: [ocr-and-documents, nano-pdf, docx, xlsx]
---

# PDF 技能

创建、合并、拆分、转换和保护 PDF 文件——包括合并、页面操作、表单填写、水印、加密以及文本和表格提取。若要从扫描文档中大量提取文本，优先使用 `ocr-and-documents` 技能；若要用自然语言编辑现有 PDF 文本，优先使用 `nano-pdf`。

## 何时使用

每当用户希望对 PDF 文件执行任何操作时，都应使用此技能：读取或提取文本和表格、组合或合并多个 PDF、拆分 PDF、旋转页面、添加水印、创建新 PDF、填写 PDF 表单、加密/解密、提取图像，或对扫描 PDF 执行 OCR。如果用户提到 .pdf 文件或要求生成 PDF，请使用此技能。

## 前置条件

```bash
pip install pypdf pdfplumber reportlab
which pdftotext || sudo apt install -y poppler-utils   # pdftotext, pdftoppm, pdfimages
which qpdf || sudo apt install -y qpdf                 # CLI merge/split/decrypt
```

macOS：`brew install poppler qpdf`。OCR 附加依赖：`pip install pytesseract pdf2image` + `sudo apt install -y tesseract-ocr`。

> 下文脚本路径均相对于此技能目录。表单填写有独立的工作流——请阅读 [forms.md](forms.md) 并遵循其中说明。高级库用法（pypdfium2、pdf-lib）与故障排除请参阅 [reference.md](reference.md)。

## 快速参考

| 任务 | 最佳工具 | 命令/代码 |
|------|-----------|--------------|
| 合并 PDF | pypdf | 每页调用 `writer.add_page(page)` |
| 拆分 PDF | pypdf | 每个文件一页 |
| 提取文本 | pdfplumber | `page.extract_text()` |
| 提取表格 | pdfplumber | `page.extract_tables()` |
| 创建 PDF | reportlab | Canvas 或 Platypus |
| 命令行合并/拆分 | qpdf | `qpdf --empty --pages ...` |
| 对扫描 PDF 执行 OCR | pytesseract | 先转换为图像（或使用 `ocr-and-documents`） |
| 填写 PDF 表单 | 参阅 [forms.md](forms.md) | `scripts/fill_fillable_fields.py` 等 |
| 编辑现有文本 | `nano-pdf` 技能 | `nano-pdf edit file.pdf <page> "<instruction>"` |

## 常用操作

### 合并 / 拆分 / 旋转（pypdf）

```python
from pypdf import PdfReader, PdfWriter

# Merge
writer = PdfWriter()
for pdf_file in ["doc1.pdf", "doc2.pdf"]:
    for page in PdfReader(pdf_file).pages:
        writer.add_page(page)
with open("merged.pdf", "wb") as f:
    writer.write(f)

# Split: one file per page
reader = PdfReader("input.pdf")
for i, page in enumerate(reader.pages):
    w = PdfWriter(); w.add_page(page)
    with open(f"page_{i+1}.pdf", "wb") as f:
        w.write(f)

# Rotate
page = reader.pages[0]
page.rotate(90)  # clockwise
```

### 提取文本和表格（pdfplumber）

```python
import pdfplumber, pandas as pd

with pdfplumber.open("document.pdf") as pdf:
    text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    tables = [pd.DataFrame(t[1:], columns=t[0])
              for page in pdf.pages
              for t in page.extract_tables() if t]
```

### 创建 PDF（reportlab）

```python
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet

doc = SimpleDocTemplate("report.pdf", pagesize=letter)
styles = getSampleStyleSheet()
story = [Paragraph("Report Title", styles["Title"]), Spacer(1, 12),
         Paragraph("Body text...", styles["Normal"]), PageBreak(),
         Paragraph("Page 2", styles["Heading1"])]
doc.build(story)
```

**下标/上标：** 切勿使用 Unicode 下标/上标字符（₀₁₂、⁰¹²）——内置字体缺少这些字形，会渲染成纯黑方块。请使用 `<sub>`/`<super>` 标记，并将其置于 `Paragraph` 对象中：`Paragraph("H<sub>2</sub>O", styles['Normal'])`。对于通过画布绘制的文本，请手动调整字号和位置。

### 命令行工具

```bash
pdftotext -layout input.pdf output.txt                     # text, layout preserved
pdftotext -f 1 -l 5 input.pdf output.txt                   # pages 1-5
qpdf --empty --pages file1.pdf file2.pdf -- merged.pdf     # merge
qpdf input.pdf --pages . 1-5 -- pages1-5.pdf               # split range
qpdf input.pdf output.pdf --rotate=+90:1                   # rotate page 1
qpdf --password=pw --decrypt encrypted.pdf decrypted.pdf   # remove password
pdfimages -j input.pdf img                                 # extract images
```

### 水印

```python
from pypdf import PdfReader, PdfWriter

watermark = PdfReader("watermark.pdf").pages[0]
reader, writer = PdfReader("document.pdf"), PdfWriter()
for page in reader.pages:
    page.merge_page(watermark)
    writer.add_page(page)
with open("watermarked.pdf", "wb") as f:
    writer.write(f)
```

### 密码保护

```python
writer.encrypt("userpassword", "ownerpassword")
```

### 对扫描 PDF 执行 OCR

```python
import pytesseract
from pdf2image import convert_from_path

pages = convert_from_path("scanned.pdf")
text = "\n\n".join(pytesseract.image_to_string(img) for img in pages)
```

若要从扫描件中批量/结构化提取内容，`ocr-and-documents` 技能（pymupdf、marker-pdf）是更合适的方案。

## 表单填写

请先阅读 [forms.md](forms.md)——其中区分了可填写（AcroForm）PDF 与扁平扫描表单，并逐步介绍这些辅助脚本：

- `scripts/check_fillable_fields.py`——PDF 是否包含 AcroForm 字段？
- `scripts/extract_form_field_info.py` / `scripts/extract_form_structure.py`——枚举字段
- `scripts/fill_fillable_fields.py`——填写 AcroForm 字段
- `scripts/fill_pdf_form_with_annotations.py`——在扁平表单上叠加文本
- `scripts/check_bounding_boxes.py`、`scripts/create_validation_image.py`——以可视方式验证位置

## 常见陷阱

- `page.extract_text()` 在纯图像页面上返回 `None`——请用 `or ""` 防护，并回退到 OCR。
- pypdf 会保留加密标志：读取加密 PDF 时，必须先使用 `PdfReader(path, password=...)`，之后才能访问页面。
- reportlab 坐标以左下角为原点，单位为点（1/72″）——而不是以左上角为原点。
- 通过批注叠加填写扁平表单时，交付前务必渲染验证图像并检查放置位置。

## 验证

1. 使用 `PdfReader` 打开输出，并断言页数符合预期。
2. 从输出中重新提取文本（使用 `pdftotext` 或 pdfplumber），确认新增内容确实存在。
3. 对任何视觉内容（水印、已填写的表单、创建的报告）：运行 `pdftoppm -jpeg -r 100 output.pdf page`，并使用 `vision_analyze` 检查图像。

## 相关技能

`ocr-and-documents`（扫描文档文本提取）、`nano-pdf`（原位自然语言文本编辑）、`docx`（Word）、`xlsx`（电子表格）、`powerpoint`（演示文稿）。
