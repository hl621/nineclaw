# 面向 ML/AI 会议的 LaTeX 模板

本目录收录了主要机器学习与人工智能会议的官方 LaTeX 模板。

---

## 将 LaTeX 编译为 PDF

### 方式 1：VS Code + LaTeX Workshop（推荐）

**环境配置：**
1. 安装 [TeX Live](https://www.tug.org/texlive/)（建议安装完整发行版）
   - macOS：`brew install --cask mactex`
   - Ubuntu：`sudo apt install texlive-full`
   - Windows：从 [tug.org/texlive](https://www.tug.org/texlive/) 下载

2. 安装 VS Code 扩展：由 James Yu 开发的 **LaTeX Workshop**
   - 打开 VS Code → Extensions（Cmd/Ctrl+Shift+X）→ 搜索 "LaTeX Workshop" → 安装

**使用方法：**
- 在 VS Code 中打开任意 `.tex` 文件
- 保存文件（Cmd/Ctrl+S）后，会自动编译为 PDF
- 单击绿色播放按钮，或按 `Cmd/Ctrl+Alt+B` 构建
- 查看 PDF：单击 "View LaTeX PDF" 图标，或按 `Cmd/Ctrl+Alt+V`
- 并排查看：按 `Cmd/Ctrl+Alt+V`，再拖动标签页

**设置**（添加到 VS Code 的 `settings.json`）：
```json
{
  "latex-workshop.latex.autoBuild.run": "onSave",
  "latex-workshop.view.pdf.viewer": "tab",
  "latex-workshop.latex.recipes": [
    {
      "name": "pdflatex → bibtex → pdflatex × 2",
      "tools": ["pdflatex", "bibtex", "pdflatex", "pdflatex"]
    }
  ]
}
```

### 方式 2：命令行

```bash
# Basic compilation
pdflatex main.tex

# With bibliography (full workflow)
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex

# Using latexmk (handles dependencies automatically)
latexmk -pdf main.tex

# Continuous compilation (watches for changes)
latexmk -pdf -pvc main.tex
```

### 方式 3：Overleaf（在线）

1. 访问 [overleaf.com](https://www.overleaf.com)
2. 选择 New Project → Upload Project，将模板文件夹以 ZIP 格式上传
3. 在线编辑并实时预览 PDF
4. 无需在本地安装软件

### 方式 4：其他 IDE

| IDE | 扩展/插件 | 说明 |
|-----|------------------|-------|
| **Cursor** | LaTeX Workshop | 与 VS Code 相同 |
| **Sublime Text** | LaTeXTools | 流行且维护良好 |
| **Vim/Neovim** | VimTeX | 功能强大，以键盘操作为主 |
| **Emacs** | AUCTeX | 功能全面的 LaTeX 环境 |
| **TeXstudio** | 内置 | 专用 LaTeX IDE |
| **Texmaker** | 内置 | 跨平台 LaTeX 编辑器 |

### 编译故障排查

**"File not found" 错误：**
```bash
# Ensure you're in the template directory
cd templates/icml2026
pdflatex example_paper.tex
```

**参考文献未显示：**
```bash
# Run bibtex after first pdflatex
pdflatex main.tex
bibtex main        # Uses main.aux to find citations
pdflatex main.tex  # Incorporates bibliography
pdflatex main.tex  # Resolves references
```

**缺少宏包：**
```bash
# TeX Live package manager
tlmgr install <package-name>

# Or install full distribution to avoid this
```

---

## 可用模板

| 会议 | 目录 | 年份 | 来源 |
|------------|-----------|------|--------|
| ICML | `icml2026/` | 2026 | [ICML 官方说明](https://icml.cc/Conferences/2026/AuthorInstructions) |
| ICLR | `iclr2026/` | 2026 | [官方 GitHub 仓库](https://github.com/ICLR/Master-Template) |
| NeurIPS | `neurips2025/` | 2025 | 社区模板 |
| ACL | `acl/` | 2025+ | [ACL 官方仓库](https://github.com/acl-org/acl-style-files) |
| AAAI | `aaai2026/` | 2026 | [AAAI Author Kit](https://aaai.org/authorkit26/) |
| COLM | `colm2025/` | 2025 | [COLM 官方仓库](https://github.com/COLM-org/Template) |

## 使用方法

### ICML 2026

```latex
\documentclass{article}
\usepackage{icml2026}  % For submission
% \usepackage[accepted]{icml2026}  % For camera-ready

\begin{document}
% Your paper content
\end{document}
```

关键文件：
- `icml2026.sty` - 样式文件
- `icml2026.bst` - 参考文献样式
- `example_paper.tex` - 示例文档

### ICLR 2026

```latex
\documentclass{article}
\usepackage[submission]{iclr2026_conference}  % For submission
% \usepackage[final]{iclr2026_conference}  % For camera-ready

\begin{document}
% Your paper content
\end{document}
```

关键文件：
- `iclr2026_conference.sty` - 样式文件
- `iclr2026_conference.bst` - 参考文献样式
- `iclr2026_conference.tex` - 示例文档

### ACL 系列会议（ACL、EMNLP、NAACL）

```latex
\documentclass[11pt]{article}
\usepackage[review]{acl}  % For review
% \usepackage{acl}  % For camera-ready

\begin{document}
% Your paper content
\end{document}
```

关键文件：
- `acl.sty` - 样式文件
- `acl_natbib.bst` - 参考文献样式
- `acl_latex.tex` - 示例文档

### AAAI 2026

```latex
\documentclass[letterpaper]{article}
\usepackage[submission]{aaai2026}  % For submission
% \usepackage{aaai2026}  % For camera-ready

\begin{document}
% Your paper content
\end{document}
```

关键文件：
- `aaai2026.sty` - 样式文件
- `aaai2026.bst` - 参考文献样式

### COLM 2025

```latex
\documentclass{article}
\usepackage[submission]{colm2025_conference}  % For submission
% \usepackage[final]{colm2025_conference}  % For camera-ready

\begin{document}
% Your paper content
\end{document}
```

关键文件：
- `colm2025_conference.sty` - 样式文件
- `colm2025_conference.bst` - 参考文献样式

## 页数限制汇总

| 会议 | 投稿版 | Camera-Ready | 说明 |
|------------|-----------|--------------|-------|
| ICML 2026 | 8 页 | 9 页 | 参考文献/附录不限页数 |
| ICLR 2026 | 9 页 | 10 页 | 参考文献/附录不限页数 |
| NeurIPS 2025 | 9 页 | 9 页 | checklist 不计入页数限制 |
| ACL 2025 | 8 页（长文） | 视情况而定 | 参考文献/附录不限页数 |
| AAAI 2026 | 7 页 | 8 页 | 参考文献/附录不限页数 |
| COLM 2025 | 9 页 | 10 页 | 参考文献/附录不限页数 |

## 常见问题

### 编译错误

1. **缺少宏包**：安装完整 TeX 发行版（TeX Live Full 或 MikTeX）
2. **参考文献错误**：使用随模板提供的 `.bst` 文件，并在 `\bibliographystyle{}` 中指定该样式
3. **字体警告**：安装 `cm-super`，或使用 `\usepackage{lmodern}`

### 匿名化

投稿时请确保：
- `\author{}` 中不含作者姓名
- 不设置致谢章节
- 不出现资助编号
- 使用匿名仓库
- 以第三人称引用本人工作

### 常用 LaTeX 宏包

```latex
% Recommended packages (check compatibility with venue style)
\usepackage{amsmath,amsthm,amssymb}  % Math
\usepackage{graphicx}                 % Figures
\usepackage{booktabs}                 % Tables
\usepackage{hyperref}                 % Links
\usepackage{algorithm,algorithmic}    % Algorithms
\usepackage{natbib}                   % Citations
```

## 更新模板

模板每年都会更新。每次投稿前，请查阅官方来源：

- ICML: https://icml.cc/
- ICLR: https://iclr.cc/
- NeurIPS: https://neurips.cc/
- ACL: https://github.com/acl-org/acl-style-files
- AAAI: https://aaai.org/
- COLM: https://colmweb.org/
