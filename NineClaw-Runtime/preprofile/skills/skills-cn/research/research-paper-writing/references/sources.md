# 参考来源

本文档列出了用于构建此技能的所有权威来源，按主题组织。

---

## 起源与归属

本技能的写作理念、引用核验流程与会议参考资料，最初由 **[Orchestra Research](https://github.com/orchestra-research)** 于 2026 年 1 月整理为 `ml-paper-writing` 技能，参考了 Neel Nanda 的博客文章及下列研究者指南。teknium 于 2026 年 1 月将其集成到 hermes-agent；随后 SHL0MS 于 2026 年 4 月通过 PR #4654 将其扩展为当前的 `research-paper-writing` 工作流，在保留原有写作理念和参考文件的基础上，加入了实验设计、实验执行监控、迭代改进与投稿阶段。

---

## 写作理念与指南

### 主要来源（必读）

| 来源 | 作者 | URL | 关键贡献 |
|--------|--------|-----|------------------|
| **Highly Opinionated Advice on How to Write ML Papers** | Neel Nanda | [Alignment Forum](https://www.alignmentforum.org/posts/eJGptPbbFPZGLpjsp/highly-opinionated-advice-on-how-to-write-ml-papers) | 叙事框架、“What/Why/So What”、时间分配 |
| **How to Write ML Papers** | Sebastian Farquhar (DeepMind) | [Blog](https://sebastianfarquhar.com/on-research/2024/11/04/how_to_write_ml_papers/) | 五句式摘要公式、结构模板 |
| **A Survival Guide to a PhD** | Andrej Karpathy | [Blog](http://karpathy.github.io/2016/09/07/phd/) | 论文结构撰写方案、贡献定位 |
| **Heuristics for Scientific Writing** | Zachary Lipton (CMU) | [Blog](https://www.approximatelycorrect.com/2018/01/29/heuristics-technical-scientific-writing-machine-learning-perspective/) | 选词、章节平衡、避免滥用强调词 |
| **Advice for Authors** | Jacob Steinhardt (UC Berkeley) | [Blog](https://jsteinhardt.stat.berkeley.edu/blog/advice-for-authors) | 准确优先于简洁、术语一致 |
| **Easy Paper Writing Tips** | Ethan Perez (Anthropic) | [Blog](https://ethanperez.net/easy-paper-writing-tips/) | 句子层面的技巧、展开含撇号的缩略形式、提升清晰度 |

### 基础科学写作

| 来源 | 作者 | URL | 关键贡献 |
|--------|--------|-----|------------------|
| **The Science of Scientific Writing** | Gopen & Swan | [PDF](https://cseweb.ucsd.edu/~swanson/papers/science-of-writing.pdf) | 主题位置与强调位置、先旧后新、七项原则 |
| **Summary of Science of Scientific Writing** | Lawrence Crowl | [Summary](https://www.crowl.org/Lawrence/writing/GopenSwan90.html) | Gopen & Swan 一文的精要版 |

### 其他资源

| 来源 | URL | 关键贡献 |
|--------|-----|------------------|
| How To Write A Research Paper In ML | [Blog](https://grigorisg9gr.github.io/machine%20learning/research%20paper/how-to-write-a-research-paper-in-machine-learning/) | 实用写作流程、LaTeX 技巧 |
| A Recipe for Training Neural Networks | [Karpathy Blog](http://karpathy.github.io/2019/04/25/recipe/) | 可迁移到论文结构设计的调试方法 |
| ICML Paper Writing Best Practices | [ICML](https://icml.cc/Conferences/2022/BestPractices) | 会议官方指导 |
| Bill Freeman's Writing Slides | [MIT](https://billf.mit.edu/sites/default/files/documents/cvprPapers.pdf) | 论文结构的可视化指南 |

---

## 官方会议指南

### NeurIPS

| 文档 | URL | 用途 |
|----------|-----|---------|
| Paper Checklist Guidelines | [NeurIPS](https://neurips.cc/public/guides/PaperChecklist) | 16 项必填检查清单 |
| Reviewer Guidelines 2025 | [NeurIPS](https://neurips.cc/Conferences/2025/ReviewerGuidelines) | 评估标准、评分方式 |
| Style Files | [NeurIPS](https://neurips.cc/Conferences/2025/PaperInformation/StyleFiles) | LaTeX 模板 |

### ICML

| 文档 | URL | 用途 |
|----------|-----|---------|
| Paper Guidelines | [ICML](https://icml.cc/Conferences/2024/PaperGuidelines) | 投稿要求 |
| Reviewer Instructions 2025 | [ICML](https://icml.cc/Conferences/2025/ReviewerInstructions) | 评审表、评价 |
| Style & Author Instructions | [ICML](https://icml.cc/Conferences/2022/StyleAuthorInstructions) | 格式规范 |

### ICLR

| 文档 | URL | 用途 |
|----------|-----|---------|
| Author Guide 2026 | [ICLR](https://iclr.cc/Conferences/2026/AuthorGuide) | 投稿要求、LLM 使用披露 |
| Reviewer Guide 2025 | [ICLR](https://iclr.cc/Conferences/2025/ReviewerGuide) | 评审流程、评价标准 |

### ACL/EMNLP

| 文档 | URL | 用途 |
|----------|-----|---------|
| ACL Style Files | [GitHub](https://github.com/acl-org/acl-style-files) | LaTeX 模板 |
| ACL Rolling Review | [ARR](https://aclrollingreview.org/) | 投稿流程 |

### AAAI

| 文档 | URL | 用途 |
|----------|-----|---------|
| Author Kit 2026 | [AAAI](https://aaai.org/authorkit26/) | 模板和指南 |

### COLM

| 文档 | URL | 用途 |
|----------|-----|---------|
| Template | [GitHub](https://github.com/COLM-org/Template) | LaTeX 模板 |

---

## 引用 API 与工具

### API

| API | 文档 | 最适用场景 |
|-----|---------------|----------|
| **Semantic Scholar** | [Docs](https://api.semanticscholar.org/api-docs/) | ML/AI 论文、引用图谱 |
| **CrossRef** | [Docs](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) | DOI 查询、BibTeX 检索 |
| **arXiv** | [Docs](https://info.arxiv.org/help/api/basics.html) | 预印本、PDF 访问 |
| **OpenAlex** | [Docs](https://docs.openalex.org/) | 开放式替代方案、批量访问 |

### Python 库

| 库 | 安装 | 用途 |
|---------|---------|---------|
| `semanticscholar` | `pip install semanticscholar` | Semantic Scholar 封装库 |
| `arxiv` | `pip install arxiv` | arXiv 检索与下载 |
| `habanero` | `pip install habanero` | CrossRef 客户端 |

### 引用核验

| 工具 | URL | 用途 |
|------|-----|---------|
| Citely | [citely.ai](https://citely.ai/citation-checker) | 批量核验 |
| ReciteWorks | [reciteworks.com](https://reciteworks.com/) | 文内引用检查 |

---

## 可视化与格式设置

### 图表制作

| 工具 | URL | 用途 |
|------|-----|---------|
| PlotNeuralNet | [GitHub](https://github.com/HarisIqbal88/PlotNeuralNet) | TikZ 神经网络示意图 |
| SciencePlots | [GitHub](https://github.com/garrettj403/SciencePlots) | 达到发表标准的 matplotlib 图表样式 |
| Okabe-Ito Palette | [Reference](https://jfly.uni-koeln.de/color/) | 对色觉缺陷友好的配色 |

### LaTeX 资源

| 资源 | URL | 用途 |
|----------|-----|---------|
| Overleaf Templates | [Overleaf](https://www.overleaf.com/latex/templates) | 在线 LaTeX 编辑器 |
| BibLaTeX Guide | [CTAN](https://ctan.org/pkg/biblatex) | 现代引用管理 |

---

## AI 写作与幻觉研究

| 来源 | URL | 主要发现 |
|--------|-----|-------------|
| AI Hallucinations in Citations | [Enago](https://www.enago.com/academy/ai-hallucinations-research-citations/) | 约 40% 的错误率 |
| Hallucination in AI Writing | [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC10726751/) | 引用错误的类型 |
| NeurIPS 2025 AI Report | [ByteIota](https://byteiota.com/neurips-2025-100-ai-hallucinations-slip-through-review/) | 100 多条虚构引用 |

---

## 按主题快速参考

### 叙事与结构
→ 建议先读：Neel Nanda、Sebastian Farquhar、Andrej Karpathy

### 句子级清晰度
→ 建议先读：Gopen & Swan、Ethan Perez、Zachary Lipton

### 选词与风格
→ 建议先读：Zachary Lipton、Jacob Steinhardt

### 特定会议要求
→ 建议先查：会议官方指南（NeurIPS、ICML、ICLR、ACL）

### 引用管理
→ 建议先查：Semantic Scholar API、CrossRef、citation-workflow.md

### 审稿人期望
→ 建议先查：各会议审稿人指南、reviewer-guidelines.md

### 人工评估
→ 建议先查：human-evaluation.md、Prolific/MTurk 文档

### 非实证论文（理论、综述、基准、立场论文）
→ 建议先查：paper-types.md

---

## 人工评估与标注

| 来源 | URL | 关键贡献 |
|--------|-----|------------------|
| **Datasheets for Datasets** | Gebru et al., 2021 ([arXiv](https://arxiv.org/abs/1803.09010)) | 结构化数据集文档框架 |
| **Model Cards for Model Reporting** | Mitchell et al., 2019 ([arXiv](https://arxiv.org/abs/1810.03993)) | 结构化模型文档框架 |
| **Crowdsourcing and Human Computation** | [Survey](https://arxiv.org/abs/2202.06516) | 众包标注最佳实践 |
| **Krippendorff's Alpha** | [Wikipedia](https://en.wikipedia.org/wiki/Krippendorff%27s_alpha) | 标注者间一致性指标参考 |
| **Prolific** | [prolific.co](https://www.prolific.co/) | 推荐用于研究的众包平台 |

## 伦理与更广泛影响

| 来源 | URL | 关键贡献 |
|--------|-----|------------------|
| **ML CO2 Impact** | [mlco2.github.io](https://mlco2.github.io/impact/) | 计算碳足迹计算器 |
| **NeurIPS Broader Impact Guide** | [NeurIPS](https://neurips.cc/public/guides/PaperChecklist) | 影响声明的官方指南 |
| **ACL Ethics Policy** | [ACL](https://www.aclweb.org/portal/content/acl-code-ethics) | NLP 研究的伦理要求 |
