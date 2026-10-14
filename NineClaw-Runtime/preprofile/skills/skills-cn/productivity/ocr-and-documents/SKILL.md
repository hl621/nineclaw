---
name: ocr-and-documents
description: "从 PDF/扫描件中提取文本（pymupdf、marker-pdf）。"
version: 2.3.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [PDF, Documents, Research, Arxiv, Text-Extraction, OCR]
    related_skills: [pdf, docx, powerpoint]
---

# PDF 与文档提取

对于 DOCX：请参阅 `docx` 技能（创建/编辑），或使用 `python-docx` 进行结构化读取。
对于 PPTX：请参阅 `powerpoint` 技能（完整的创建/读取/编辑支持）。
对于 PDF 操作（合并、拆分、表单、水印、创建）：请参阅 `pdf` 技能。
本技能涵盖**从 PDF 和扫描文档中提取文本**。

## 第 1 步：是否有远程 URL？

如果文档有 URL，**始终先尝试 `web_extract`**：

```
web_extract(urls=["https://arxiv.org/pdf/2402.03300"])
web_extract(urls=["https://example.com/report.pdf"])
```

它通过 Firecrawl 完成 PDF 到 Markdown 的转换，无需本地依赖。

仅在以下情况使用本地提取：文件位于本地、web_extract 失败，或需要批量处理。

## 第 2 步：选择本地提取器

| 功能 | pymupdf（约 25MB） | marker-pdf（约 3–5GB） |
|---------|-----------------|---------------------|
| **文本型 PDF** | ✅ | ✅ |
| **扫描型 PDF（OCR）** | ❌ | ✅（90 多种语言） |
| **表格** | ✅（基础） | ✅（高精度） |
| **公式 / LaTeX** | ❌ | ✅ |
| **代码块** | ❌ | ✅ |
| **表单** | ❌ | ✅ |
| **移除页眉/页脚** | ❌ | ✅ |
| **阅读顺序检测** | ❌ | ✅ |
| **图像提取** | ✅（嵌入图像） | ✅（带上下文） |
| **图像 → 文本（OCR）** | ❌ | ✅ |
| **EPUB** | ✅ | ✅ |
| **Markdown 输出** | ✅（通过 pymupdf4llm） | ✅（原生支持，质量更高） |
| **安装体积** | 约 25MB | 约 3–5GB（PyTorch + 模型） |
| **速度** | 即时 | 约 1–14 秒/页（CPU），约 0.2 秒/页（GPU） |

**决策**：除非需要 OCR、公式、表单或复杂版面分析，否则使用 pymupdf。

如果用户需要 marker 的能力，但系统没有约 5GB 可用磁盘空间：
> “此文档需要 OCR/高级提取（marker-pdf），而 PyTorch 和模型需要约 5GB 空间。您的系统有 [X]GB 可用空间。可选方案：释放空间；提供 URL，以便我使用 web_extract；或者我可以尝试 pymupdf，它适用于文本型 PDF，但不支持扫描文档或公式。”

---

## pymupdf（轻量级）

```bash
pip install pymupdf pymupdf4llm
```

**通过辅助脚本**：
```bash
python scripts/extract_pymupdf.py document.pdf              # Plain text
python scripts/extract_pymupdf.py document.pdf --markdown    # Markdown
python scripts/extract_pymupdf.py document.pdf --tables      # Tables
python scripts/extract_pymupdf.py document.pdf --images out/ # Extract images
python scripts/extract_pymupdf.py document.pdf --metadata    # Title, author, pages
python scripts/extract_pymupdf.py document.pdf --pages 0-4   # Specific pages
```

**内联方式**：
```bash
python3 -c "
import pymupdf
doc = pymupdf.open('document.pdf')
for page in doc:
    print(page.get_text())
"
```

---

## marker-pdf（高质量 OCR）

```bash
# Check disk space first
python scripts/extract_marker.py --check

pip install marker-pdf
```

**通过辅助脚本**：
```bash
python scripts/extract_marker.py document.pdf                # Markdown
python scripts/extract_marker.py document.pdf --json         # JSON with metadata
python scripts/extract_marker.py document.pdf --output_dir out/  # Save images
python scripts/extract_marker.py scanned.pdf                 # Scanned PDF (OCR)
python scripts/extract_marker.py document.pdf --use_llm      # LLM-boosted accuracy
```

**CLI**（随 marker-pdf 安装）：
```bash
marker_single document.pdf --output_dir ./output
marker /path/to/folder --workers 4    # Batch
```

---

## Arxiv 论文

```
# Abstract only (fast)
web_extract(urls=["https://arxiv.org/abs/2402.03300"])

# Full paper
web_extract(urls=["https://arxiv.org/pdf/2402.03300"])

# Search
web_search(query="arxiv GRPO reinforcement learning 2026")
```

## 拆分、合并与搜索

pymupdf 原生支持这些操作——使用 `execute_code` 或内联 Python：

```python
# Split: extract pages 1-5 to a new PDF
import pymupdf
doc = pymupdf.open("report.pdf")
new = pymupdf.open()
for i in range(5):
    new.insert_pdf(doc, from_page=i, to_page=i)
new.save("pages_1-5.pdf")
```

```python
# Merge multiple PDFs
import pymupdf
result = pymupdf.open()
for path in ["a.pdf", "b.pdf", "c.pdf"]:
    result.insert_pdf(pymupdf.open(path))
result.save("merged.pdf")
```

```python
# Search for text across all pages
import pymupdf
doc = pymupdf.open("report.pdf")
for i, page in enumerate(doc):
    results = page.search_for("revenue")
    if results:
        print(f"Page {i+1}: {len(results)} match(es)")
        print(page.get_text("text"))
```

无需额外依赖——pymupdf 这一个包即可完成拆分、合并、搜索和文本提取。

---

## 注意事项

- 对于 URL，始终首选 `web_extract`
- pymupdf 是稳妥的默认选择——即时运行、无需模型、可在各平台使用
- marker-pdf 用于 OCR、扫描文档、公式和复杂版面——仅在需要时安装
- 两个辅助脚本都支持 `--help` 查看完整用法
- marker-pdf 首次使用时会将约 2.5GB 的模型下载到 `~/.cache/huggingface/`
- 对于 Word 文档：`pip install python-docx`（优于 OCR——可解析实际结构）
- 对于 PowerPoint：请参阅 `powerpoint` 技能（使用 python-pptx）
