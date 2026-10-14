# AAAI 2026 统一 LaTeX 模板使用说明 / AAAI 2026 Unified LaTeX Template Guide

> **📝 重要说明 / Important Notice**：本仓库基于 AAAI 2026 官方模板，并借助 Cursor 进行了改进。如遇任何使用问题或内容冲突，欢迎提交 issue。
>
> **📝 Important Notice**: This repository is based on the official AAAI 2026 template and was improved with the assistance of Cursor. If you encounter any issues or conflicts, please submit an issue.

[中文](#中文版本) | [English](#english-version)

---

## 🌐 在线查看 / Online Access

**📖 在线阅读和测试模板**：[https://cn.overleaf.com/read/wyhcnvcrtpyt#cd4a07](https://cn.overleaf.com/read/wyhcnvcrtpyt#cd4a07)

**📖 View and Test the Template Online**: [https://cn.overleaf.com/read/wyhcnvcrtpyt#cd4a07](https://cn.overleaf.com/read/wyhcnvcrtpyt#cd4a07)

💡 **提示 / Tips**：
- 中文：您可以通过上述链接直接在 Overleaf 中查看、编辑和编译模板，无需在本地安装 LaTeX 环境。
- English: You can view, edit, and compile the template directly in Overleaf using the link above, without installing LaTeX locally.

---

## 中文版本

### 概述 ✅

我已将 AAAI 2026 的两个版本（匿名投稿版和 camera-ready 版）**完整合并**为一个统一的模板文件 `aaai2026-unified-template.tex`。

该模板完整保留了两个原始模板的**全部内容**（共 886 行，比原始文件更全面），包括：
- 所有格式说明和要求
- 完整的示例代码和表格
- 图片处理指南
- 参考文献格式要求
- 所有章节及附录内容
- 各版本特有的 Acknowledgments 部分

### 主要差异分析

对比两个原始模板后，主要差异如下：

#### 1. 宏包加载方式
- **匿名版本**：`\usepackage[submission]{aaai2026}`
- **Camera-ready 版本**：`\usepackage{aaai2026}`

#### 2. 标题差异
- **匿名版本**："AAAI Press Anonymous Submission Instructions for Authors Using LaTeX"
- **Camera-ready 版本**："AAAI Press Formatting Instructions for Authors Using LaTeX --- A Guide"

#### 3. Links 环境的处理
- **匿名版本**：注释掉 Links 环境，以免泄露作者身份
- **Camera-ready 版本**：正常显示 Links 环境

#### 4. 内容差异
- **匿名版本**：包含 "Preparing an Anonymous Submission" 部分的特殊说明
- **Camera-ready 版本**：包含完整的格式说明和版权信息

### 依赖文件检查结果

✅ **已验证并复制到主目录的文件**：

- `aaai2026.sty` - AAAI 2026 样式文件（两个版本完全相同）
- `aaai2026.bst` - 参考文献样式文件（两个版本完全相同）
- `aaai2026.bib` - 示例参考文献文件
- `figure1.pdf` 和 `figure2.pdf` - 示例图片文件

这些文件在两个版本中完全相同，因此统一模板可以正常工作。

### 如何使用统一模板

#### 切换到匿名投稿版本
在模板文件第 11 行，**取消注释**以下内容：
```latex
\def\aaaianonymous{true}
```

#### 切换到 Camera-ready 版本
在模板文件第 11 行，**注释掉**或**删除**以下内容：
```latex
% \def\aaaianonymous{true}
```

### 一键切换的核心机制

统一模板使用 LaTeX 的条件编译功能：

```latex
% 条件包加载
\ifdefined\aaaianonymous
    \usepackage[submission]{aaai2026}  % 匿名版本
\else
    \usepackage{aaai2026}              % Camera-ready版本
\fi

% 条件标题设置
\ifdefined\aaaianonymous
    \title{AAAI Press Anonymous Submission\\Instructions for Authors Using \LaTeX{}}
\else
    \title{AAAI Press Formatting Instructions \\for Authors Using \LaTeX{} --- A Guide}
\fi

% 条件内容显示
\ifdefined\aaaianonymous
    % 匿名版本特有内容
\else
    % Camera-ready版本特有内容
\fi
```

### 文件清单

主目录包含以下文件：

- `aaai2026-unified-template.tex` - 统一主论文模板文件
- `aaai2026-unified-supp.tex` - 统一补充材料模板文件
- `aaai2026.sty` - AAAI 2026 LaTeX 样式文件
- `aaai2026.bst` - 参考文献样式文件
- `aaai2026.bib` - 示例参考文献文件
- `figure1.pdf` - 示例图片 1
- `figure2.pdf` - 示例图片 2
- `README.md` - 本说明文档

### 补充材料模板 (Supplementary Material Template)

#### 概述
`aaai2026-unified-supp.tex` 是专门为 AAAI 2026 补充材料设计的统一模板，采用与主论文模板相同的版本切换机制。

#### 主要功能
- **版本切换**：修改一行代码即可在匿名投稿版和 camera-ready 版之间切换
- **补充内容支持**：支持额外的实验、推导、数据、图表、算法等
- **格式一致性**：与主论文模板保持完全一致的格式要求
- **代码示例**：包含算法、代码列表等补充材料的示例

#### 使用方法
与主论文模板相同，只需修改第 11 行：
```latex
% 匿名投稿版本
\def\aaaianonymous{true}

% Camera-ready版本  
% \def\aaaianonymous{true}
```

#### 补充材料内容建议
- 额外的实验结果和消融研究
- 详细的数学推导和证明
- 更多的图表和可视化
- 算法伪代码和实现细节
- 数据集说明和预处理步骤
- 超参数设置和实验配置
- 失败案例分析
- 计算复杂度分析

### 使用检查清单 (Usage Checklist)

#### 📋 投稿前检查清单 (Pre-Submission Checklist)

**版本设置**：
- [ ] 已设置 `\def\aaaianonymous{true}`（匿名投稿）
- [ ] 已注释掉所有可能暴露身份的信息
- [ ] 已对可能泄露身份的自引表述进行匿名化处理

**内容完整性**：
- [ ] 已填写标题、摘要和关键词
- [ ] 所有章节内容完整
- [ ] 图表编号连续且正确
- [ ] 参考文献格式正确
- [ ] 补充材料（如有）已准备完毕

**格式检查**：
- [ ] 页面边距符合要求
- [ ] 字体和字号正确
- [ ] 行距符合标准
- [ ] 图表的位置和大小合适
- [ ] 数学公式格式正确

**技术检查**：
- [ ] LaTeX 编译无错误
- [ ] 参考文献正确生成
- [ ] PDF 输出正常
- [ ] 文件大小在限制范围内

#### 📋 录用后检查清单 (Post-Acceptance Checklist)

**版本切换**：
- [ ] 已注释掉 `\def\aaaianonymous{true}`（camera-ready）
- [ ] 已添加完整的作者信息
- [ ] 已添加所有作者的单位信息
- [ ] 已恢复所有需要恢复的注释内容

**内容更新**：
- [ ] 已根据审稿意见修改内容
- [ ] 已更新所有图表和实验
- [ ] 已完善补充材料
- [ ] 已检查所有链接和引用

**最终检查**：
- [ ] 已检查最终 PDF 的质量
- [ ] 已备份所有文件
- [ ] 符合会议最终提交要求
- [ ] 补充材料已单独提交（如需要）

#### 📋 补充材料检查清单 (Supplementary Material Checklist)

**内容组织**：
- [ ] 补充材料与主论文内容对应
- [ ] 章节结构清晰合理
- [ ] 图表编号与主论文不冲突
- [ ] 参考文献格式一致

**技术细节**：
- [ ] 算法伪代码清晰完整
- [ ] 实验设置说明详细
- [ ] 数据预处理步骤明确
- [ ] 超参数配置完整

**格式要求**：
- [ ] 使用统一的 supp 模板
- [ ] 页面设置与主论文一致
- [ ] 字体和格式符合要求
- [ ] 文件大小在限制范围内

### 实际使用建议

1. **投稿阶段**：
   - 取消注释 `\def\aaaianonymous{true}`
   - 确保不包含任何可能暴露身份的信息
   - 检查可能泄露身份的自引表述是否已匿名化

2. **录用后准备最终版本**：
   - 注释掉或删除 `\def\aaaianonymous{true}` 这一行
   - 添加完整的作者信息和单位信息
   - 取消注释 Links 环境（如需要）

3. **编译测试**：
   - 分别在两种模式下编译，确保均可正常工作
   - 检查输出的 PDF 是否符合要求
   - 验证参考文献格式是否正确

4. **依赖文件确认**：
   - 确保所有依赖文件均位于同一目录
   - 移动模板文件时，记得一并移动依赖文件

### 重要注意事项

⚠️ **关于 Bibliography Style**：
- `aaai2026.sty` 文件已自动设置 `\bibliographystyle{aaai2026}`
- **不要**在文档中再次添加 `\bibliographystyle{aaai2026}` 命令
- 否则会出现 "`Illegal, another \bibstyle command`" 错误
- 只需使用 `\bibliography{aaai2026}` 命令

### 编译命令示例

```bash
# 编译LaTeX文档
pdflatex aaai2026-unified-template.tex
bibtex aaai2026-unified-template
pdflatex aaai2026-unified-template.tex
pdflatex aaai2026-unified-template.tex
```

### 常见问题及解决方案

#### 1. "Illegal, another \bibstyle command" 错误
**原因**：重复设置了 bibliography style  
**解决方案**：删除文档中的 `\bibliographystyle{aaai2026}` 命令；`aaai2026.sty` 会自动处理

#### 2. 参考文献格式不正确
**原因**：可能缺少 natbib 宏包，或 BibTeX 文件存在问题  
**解决方案**：按照标准 LaTeX 编译流程操作：pdflatex → bibtex → pdflatex → pdflatex

---

## English Version

### Overview ✅

I have **completely merged** the two AAAI 2026 versions (anonymous submission and camera-ready) into a single unified template file `aaai2026-unified-template.tex`.

This template contains **all content** from both original templates (886 lines total, making it more comprehensive than either original file), including:
- All formatting instructions and requirements
- Complete example code and tables
- Image-handling guidelines
- Reference-formatting requirements
- All sections and appendix content
- Version-specific Acknowledgments sections

### Key Differences

A comparison of the two original templates shows the following key differences:

#### 1. Package Loading
- **Anonymous version**: `\usepackage[submission]{aaai2026}`
- **Camera-ready version**: `\usepackage{aaai2026}`

#### 2. Title
- **Anonymous version**: "AAAI Press Anonymous Submission Instructions for Authors Using LaTeX"
- **Camera-ready version**: "AAAI Press Formatting Instructions for Authors Using LaTeX --- A Guide"

#### 3. Handling of the Links Environment
- **Anonymous version**: The Links environment is commented out to prevent author identity disclosure
- **Camera-ready version**: The Links environment is displayed normally

#### 4. Content
- **Anonymous version**: Includes special instructions in the "Preparing an Anonymous Submission" section
- **Camera-ready version**: Includes complete formatting instructions and copyright information

### Dependency File Verification

✅ **Files verified and copied to the main directory**:

- `aaai2026.sty` - AAAI 2026 style file (identical in both versions)
- `aaai2026.bst` - Bibliography style file (identical in both versions)
- `aaai2026.bib` - Sample bibliography file
- `figure1.pdf` and `figure2.pdf` - Sample image files

All these files are identical in both versions, so the unified template works correctly.

### How to Use the Unified Template

#### Switch to the Anonymous Submission Version
On line 11 of the template file, **uncomment** the following line:
```latex
\def\aaaianonymous{true}
```

#### Switch to the Camera-ready Version
On line 11 of the template file, **comment out** or **delete** the following line:
```latex
% \def\aaaianonymous{true}
```

### One-Line Switching Mechanism

The unified template uses LaTeX conditional compilation:

```latex
% Conditional package loading
\ifdefined\aaaianonymous
    \usepackage[submission]{aaai2026}  % Anonymous version
\else
    \usepackage{aaai2026}              % Camera-ready version
\fi

% Conditional title setting
\ifdefined\aaaianonymous
    \title{AAAI Press Anonymous Submission\\Instructions for Authors Using \LaTeX{}}
\else
    \title{AAAI Press Formatting Instructions \\for Authors Using \LaTeX{} --- A Guide}
\fi

% Conditional content display
\ifdefined\aaaianonymous
    % Anonymous version specific content
\else
    % Camera-ready version specific content
\fi
```

### File List

The main directory contains the following files:

- `aaai2026-unified-template.tex` - Unified main-paper template
- `aaai2026-unified-supp.tex` - Unified supplementary-material template
- `aaai2026.sty` - AAAI 2026 LaTeX style file
- `aaai2026.bst` - Bibliography style file
- `aaai2026.bib` - Sample bibliography file
- `figure1.pdf` - Sample image 1
- `figure2.pdf` - Sample image 2
- `README.md` - This guide

### Supplementary Material Template

#### Overview
`aaai2026-unified-supp.tex` is a unified template designed specifically for AAAI 2026 supplementary materials. It uses the same version-switching mechanism as the main-paper template.

#### Key Features
- **Version Switching**: Switch between the anonymous-submission and camera-ready versions by changing one line of code
- **Supplementary Content Support**: Supports additional experiments, derivations, data, figures, algorithms, and more
- **Format Consistency**: Maintains the same formatting requirements as the main-paper template
- **Code Examples**: Includes examples of algorithms, code listings, and other supplementary materials

#### Usage
As with the main-paper template, simply modify line 11:
```latex
% Anonymous submission version
\def\aaaianonymous{true}

% Camera-ready version
% \def\aaaianonymous{true}
```

#### Supplementary Material Content Suggestions
- Additional experimental results and ablation studies
- Detailed mathematical derivations and proofs
- Additional figures and visualizations
- Algorithm pseudocode and implementation details
- Dataset descriptions and preprocessing steps
- Hyperparameter settings and experimental configurations
- Failure-case analysis
- Computational-complexity analysis

### Usage Checklist

#### 📋 Pre-Submission Checklist

**Version Setup**:
- [ ] Set `\def\aaaianonymous{true}` (anonymous submission)
- [ ] Comment out all information that could reveal the authors' identities
- [ ] Anonymize any self-referential wording that could reveal the authors' identities

**Content Completeness**:
- [ ] Fill in the title, abstract, and keywords
- [ ] Complete all sections
- [ ] Ensure figure and table numbers are sequential and correct
- [ ] Verify reference formatting
- [ ] Prepare supplementary materials (if any)

**Format Check**:
- [ ] Ensure page margins meet the requirements
- [ ] Verify fonts and font sizes
- [ ] Ensure line spacing meets the requirements
- [ ] Check that figures and tables are appropriately positioned and sized
- [ ] Verify mathematical formula formatting

**Technical Check**:
- [ ] Compile LaTeX without errors
- [ ] Generate references correctly
- [ ] Verify the PDF output
- [ ] Keep the file size within the specified limit

#### 📋 Post-Acceptance Checklist

**Version Switch**:
- [ ] Comment out `\def\aaaianonymous{true}` (camera-ready)
- [ ] Add complete author information
- [ ] Add all author affiliations
- [ ] Restore all content that was commented out for anonymization

**Content Updates**:
- [ ] Revise the content according to reviewer feedback
- [ ] Update all figures and experiments
- [ ] Complete the supplementary materials
- [ ] Check all links and citations

**Final Check**:
- [ ] Check the quality of the final PDF
- [ ] Back up all files
- [ ] Ensure compliance with the conference's final-submission requirements
- [ ] Submit supplementary materials separately (if required)

#### 📋 Supplementary Material Checklist

**Content Organization**:
- [ ] Ensure the supplementary materials correspond to the main-paper content
- [ ] Use a clear and logical section structure
- [ ] Ensure figure and table numbers do not conflict with those in the main paper
- [ ] Use consistent reference formatting

**Technical Details**:
- [ ] Ensure algorithm pseudocode is clear and complete
- [ ] Explain the experimental setup in detail
- [ ] Clearly describe data-preprocessing steps
- [ ] Provide a complete hyperparameter configuration

**Format Requirements**:
- [ ] Use the unified supp template
- [ ] Keep page settings consistent with the main paper
- [ ] Ensure fonts and formatting meet the requirements
- [ ] Keep the file size within the specified limit

### Practical Recommendations

1. **Submission Stage**:
   - Uncomment `\def\aaaianonymous{true}`
   - Ensure the paper contains no information that could reveal the authors' identities
   - Check that any identity-revealing self-references are anonymized

2. **Preparing the Final Version After Acceptance**:
   - Comment out or delete the `\def\aaaianonymous{true}` line
   - Add complete author information and affiliations
   - Uncomment the Links environment (if needed)

3. **Compilation Testing**:
   - Compile in both modes to ensure that each works correctly
   - Check that the output PDF meets the requirements
   - Verify that reference formatting is correct

4. **Dependency File Check**:
   - Ensure all dependency files are in the same directory
   - When moving the template file, move its dependency files as well

### Important Notes

⚠️ **Bibliography Style**:
- The `aaai2026.sty` file automatically sets `\bibliographystyle{aaai2026}`
- **Do NOT** add the `\bibliographystyle{aaai2026}` command again in your document
- Otherwise, you will get an "`Illegal, another \bibstyle command`" error
- Use only the `\bibliography{aaai2026}` command

### Compilation Command Example

```bash
# Compile LaTeX document
pdflatex aaai2026-unified-template.tex
bibtex aaai2026-unified-template
pdflatex aaai2026-unified-template.tex
pdflatex aaai2026-unified-template.tex
```

### Common Issues and Solutions

#### 1. "Illegal, another \bibstyle command" Error
**Cause**: The bibliography style is set more than once  
**Solution**: Remove the `\bibliographystyle{aaai2026}` command from your document; `aaai2026.sty` handles it automatically

#### 2. Incorrect Reference Formatting
**Cause**: The natbib package may be missing, or there may be an issue with the BibTeX file  
**Solution**: Follow the standard LaTeX compilation sequence: pdflatex → bibtex → pdflatex → pdflatex

---

## 版本信息 / Version Information

- **模板版本 / Template Version**：AAAI 2026 Unified (Main + Supplementary)
- **创建日期 / Created**：2024 年 12 月
- **支持格式 / Supported Formats**：Anonymous Submission & Camera-Ready
- **模板类型 / Template Types**：Main Paper Template & Supplementary Material Template
- **兼容性 / Compatibility**：LaTeX 2020+ / TeXLive 2024+

---

🎉 **现在只需修改一行代码，即可在两个版本之间切换；所有必要的依赖文件均已准备就绪！**  
🎉 **Now you only need to change one line of code to switch between the two versions, and all required dependency files are ready to use!**