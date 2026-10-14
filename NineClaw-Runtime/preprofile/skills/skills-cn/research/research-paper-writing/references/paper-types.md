# 经验型机器学习论文之外的论文类型

非标准论文类型的写作指南，涵盖理论论文、综述/教程论文、基准/数据集论文和立场论文。每种类型都有独特的结构、证据标准和投稿渠道要求。

---

## 目录

- [理论论文](#theory-papers)
- [综述与教程论文](#survey-and-tutorial-papers)
- [基准和数据集论文](#benchmark-and-dataset-papers)
- [立场论文](#position-papers)
- [可复现性与重复研究论文](#reproducibility-and-replication-papers)

---

<a id="theory-papers"></a>

## 理论论文

### 何时撰写理论论文

如果符合以下条件，应将论文写成理论论文：
- 主要贡献是定理、界、不可能性结果或形式化刻画
- 实验是补充验证，不是核心证据
- 贡献旨在深化理解，而非取得最先进的性能指标

### 结构

```
1. Introduction (1-1.5 pages)
   - Problem statement and motivation
   - Informal statement of main results
   - Comparison to prior theoretical work
   - Contribution bullets (state theorems informally)

2. Preliminaries (0.5-1 page)
   - Notation table
   - Formal definitions
   - Assumptions (numbered, referenced later)
   - Known results you build on

3. Main Results (2-3 pages)
   - Theorem statements (formal)
   - Proof sketches (intuition + key steps)
   - Corollaries and special cases
   - Discussion of tightness / optimality

4. Experimental Validation (1-2 pages, optional but recommended)
   - Do theoretical predictions match empirical behavior?
   - Synthetic experiments that isolate the phenomenon
   - Comparison to bounds from prior work

5. Related Work (1 page)
   - Theoretical predecessors
   - Empirical work your theory explains

6. Discussion & Open Problems (0.5 page)
   - Limitations of your results
   - Conjectures suggested by your analysis
   - Concrete open problems

Appendix:
   - Full proofs
   - Technical lemmas
   - Extended experimental details
```

### 定理的撰写

**表述严谨的定理模板：**

```latex
\begin{assumption}[Bounded Gradients]\label{assum:bounded-grad}
There exists $G > 0$ such that $\|\nabla f(x)\| \leq G$ for all $x \in \mathcal{X}$.
\end{assumption}

\begin{theorem}[Convergence Rate]\label{thm:convergence}
Under Assumptions~\ref{assum:bounded-grad} and~\ref{assum:smoothness},
Algorithm~\ref{alg:method} with step size $\eta = \frac{1}{\sqrt{T}}$ satisfies
\[
\frac{1}{T}\sum_{t=1}^{T} \mathbb{E}\left[\|\nabla f(x_t)\|^2\right]
\leq \frac{2(f(x_1) - f^*)}{\sqrt{T}} + \frac{G^2}{\sqrt{T}}.
\]
In particular, after $T = O(1/\epsilon^2)$ iterations, we obtain an
$\epsilon$-stationary point.
\end{theorem}
```

**定理陈述规则：**
- 明确陈述所有假设（编号并命名）
- 给出形式化的界，而不能只写 "converges at rate O(·)"
- 用通俗语言补充推论："In particular, this means..."
- 与已知界进行比较："This improves over [prior work]'s bound of O(·) by a factor of..."

### 证明概要

证明概要是理论论文正文中最重要的部分。审稿人会据此判断作者究竟提出了真正的洞见，还是仅仅进行了机械推导。

**优秀证明概要的写作模式：**

```latex
\begin{proof}[Proof Sketch of Theorem~\ref{thm:convergence}]
The key insight is that [one sentence describing the main idea].

The proof proceeds in three steps:
\begin{enumerate}
\item \textbf{Decomposition.} We decompose the error into [term A]
  and [term B] using [technique]. This reduces the problem to
  bounding each term separately.

\item \textbf{Bounding [term A].} By [assumption/lemma], [term A]
  is bounded by $O(\cdot)$. The critical observation is that
  [specific insight that makes this non-trivial].

\item \textbf{Combining.} Choosing $\eta = 1/\sqrt{T}$ balances
  the two terms, yielding the stated bound.
\end{enumerate}

The full proof, including the technical lemma for Step 2,
appears in Appendix~\ref{app:proofs}.
\end{proof}
```

**糟糕的证明概要**：仅用略有不同的符号重述定理，或只说 "the proof follows standard techniques."

### 附录中的完整证明

```latex
\appendix
\section{Proofs}\label{app:proofs}

\subsection{Proof of Theorem~\ref{thm:convergence}}

We first establish two technical lemmas.

\begin{lemma}[Descent Lemma]\label{lem:descent}
Under Assumption~\ref{assum:smoothness}, for any step size $\eta \leq 1/L$:
\[
f(x_{t+1}) \leq f(x_t) - \frac{\eta}{2}\|\nabla f(x_t)\|^2 + \frac{\eta^2 L}{2}\|\nabla f(x_t)\|^2.
\]
\end{lemma}

\begin{proof}
[Complete proof with all steps]
\end{proof}

% Continue with remaining lemmas and main theorem proof
```

### 理论论文的常见误区

| 误区 | 问题 | 改进方法 |
|---------|---------|-----|
| 假设过强 | 使结果沦为平凡结论 | 讨论哪些假设确有必要；证明下界 |
| 未与现有界进行比较 | 审稿人无法判断贡献 | 添加不同界的对比表 |
| 证明概要只是完整证明的缩写 | 无法传达核心洞见 | 聚焦一两个关键思想；将机械性的推导移至附录 |
| 缺少实验验证 | 审稿人会质疑实际意义 | 添加检验理论预测的合成实验 |
| 符号不一致 | 给审稿人造成理解障碍 | 在预备知识部分提供符号表 |
| 本可简洁证明却写得过于复杂 | 审稿人可能怀疑其中有误 | 相比追求一般性，更应优先保证清晰 |

### 理论论文投稿渠道

| 投稿渠道 | 理论论文接纳程度 | 备注 |
|-------|----------------------|-------|
| **NeurIPS** | 中等 | 重视具有实际意义的理论 |
| **ICML** | 高 | 理论方向实力强 |
| **ICLR** | 中等 | 偏好有实证验证的理论 |
| **COLT** | 高 | 专注理论研究的会议 |
| **ALT** | 高 | 算法学习理论 |
| **STOC/FOCS** | 适合具有 TCS 风格的成果 | 适用于贡献主要属于组合或算法方向的论文 |
| **JMLR** | 高 | 无页数限制；适合包含较长证明的论文 |

---

<a id="survey-and-tutorial-papers"></a>

## 综述与教程论文

### 何时撰写综述

- 某个子领域已足够成熟，系统梳理具有价值
- 你发现了单篇论文未曾揭示的多项工作之间的联系
- 该领域缺少适合初学者的优质入门资料
- 自上一篇综述发表以来，该领域的格局已发生显著变化

**警告**：撰写综述需要真正的专业积累。领域外人士撰写的综述无论多么全面，都可能忽略细微差异并曲解相关工作。

### 结构

```
1. Introduction (1-2 pages)
   - Scope definition (what's included and excluded, and why)
   - Motivation for the survey now
   - Overview of organization (often with a figure)

2. Background / Problem Formulation (1-2 pages)
   - Formal problem definition
   - Notation (used consistently throughout)
   - Historical context

3. Taxonomy (the core contribution)
   - Organize methods along meaningful axes
   - Present taxonomy as a figure or table
   - Each category gets a subsection

4. Detailed Coverage (bulk of paper)
   - For each category: representative methods, key ideas, strengths/weaknesses
   - Comparison tables within and across categories
   - Don't just describe — analyze and compare

5. Experimental Comparison (if applicable)
   - Standardized benchmark comparison
   - Fair hyperparameter tuning for all methods
   - Not always feasible but significantly strengthens the survey

6. Open Problems & Future Directions (1-2 pages)
   - Unsolved problems the field should tackle
   - Promising but underexplored directions
   - This section is what makes a survey a genuine contribution

7. Conclusion
```

### 分类体系设计

分类体系是综述的核心学术贡献，应当满足以下要求：

- **有意义**：类别应反映真实的方法论差异，而不是随意分组
- **完备**：每篇相关论文都应能归入某一类别
- **互斥**（理想情况下）：每篇论文只归入一个主要类别
- **名称具有信息量**："Attention-based methods" > "Category 3"
- **可视化**：用图呈现分类体系几乎总能帮助读者理解

**“LLM Reasoning”综述的分类维度示例：**
- 按技术：chain-of-thought、tree-of-thought、self-consistency、工具使用
- 按训练要求：仅使用提示、微调、RLHF
- 按推理类型：数学、常识、逻辑、因果

### 写作标准

- **引用每一篇相关论文**——作者会核查自己的工作是否被纳入
- **保持公允**——不要贬低你不偏好的方法
- **重在综合，而非罗列**——提炼共性模式、权衡关系和开放问题
- **加入对比表**——即使只是定性对比（特征/属性检查表）
- **投稿前更新内容**——在 arXiv 上检查从动笔至今新发表的论文

### 综述论文投稿渠道

| 投稿渠道 | 备注 |
|-------|-------|
| **TMLR** (Survey track) | 接收专门的综述投稿；无页数限制 |
| **JMLR** | 支持长篇论文，声誉卓著 |
| **Foundations and Trends in ML** | 主要采用约稿制，但也可主动提案 |
| **ACM Computing Surveys** | 面向广泛的计算机科学读者 |
| **arXiv**（独立发布） | 不经过同行评审，但高质量综述可获得很高的关注度 |
| **会议教程** | 在 NeurIPS/ICML/ACL 以教程形式讲授，并整理成论文 |

---

<a id="benchmark-and-dataset-papers"></a>

## 基准和数据集论文

### 何时写基准论文

- 现有基准无法衡量你认为重要的方面
- 出现了一种新能力，但尚无标准评估方法
- 现有基准已饱和（所有方法得分 >95%）
- 你希望统一某个分散子领域的评估方式

### 结构

```
1. Introduction
   - What evaluation gap does this benchmark fill?
   - Why existing benchmarks are insufficient

2. Task Definition
   - Formal task specification
   - Input/output format
   - Evaluation criteria (what makes a good answer?)

3. Dataset Construction
   - Data source and collection methodology
   - Annotation process (if human-annotated)
   - Quality control measures
   - Dataset statistics (size, distribution, splits)

4. Baseline Evaluation
   - Run strong baselines (don't just report random/majority)
   - Show the benchmark is challenging but not impossible
   - Human performance baseline (if feasible)

5. Analysis
   - Error analysis on baselines
   - What makes items hard/easy?
   - Construct validity: does the benchmark measure what you claim?

6. Intended Use & Limitations
   - What should this benchmark be used for?
   - What should it NOT be used for?
   - Known biases or limitations

7. Datasheet (Appendix)
   - Full datasheet for datasets (Gebru et al.)
```

### 证据标准

审稿人评估基准论文时所依据的标准不同于方法论文：

| 评估标准 | 审稿人关注的内容 |
|-----------|---------------------|
| **评估的新颖性** | 是否衡量了现有基准未能衡量的内容？ |
| **构念效度** | 该基准是否确实衡量了其声称的能力？ |
| **难度校准** | 既不能过于简单（趋于饱和），也不能过难（表现接近随机） |
| **标注质量** | 一致性指标、标注者资质、标注指南 |
| **文档完备性** | 数据表、许可证、维护计划 |
| **可复现性** | 其他研究者能否轻松使用该基准？ |
| **伦理考量** | 偏差分析、知情同意、敏感内容处理 |

### 数据集文档（必需）

遵循 Datasheets for Datasets 框架（Gebru et al., 2021）：

```
Datasheet Questions:
1. Motivation
   - Why was this dataset created?
   - Who created it and on behalf of whom?
   - Who funded the creation?

2. Composition
   - What do the instances represent?
   - How many instances are there?
   - Does it contain all possible instances or a sample?
   - Is there a label? If so, how was it determined?
   - Are there recommended data splits?

3. Collection Process
   - How was the data collected?
   - Who was involved in collection?
   - Over what timeframe?
   - Was ethical review conducted?

4. Preprocessing
   - What preprocessing was done?
   - Was the "raw" data saved?

5. Uses
   - What tasks has this been used for?
   - What should it NOT be used for?
   - Are there other tasks it could be used for?

6. Distribution
   - How is it distributed?
   - Under what license?
   - Are there any restrictions?

7. Maintenance
   - Who maintains it?
   - How can users contact the maintainer?
   - Will it be updated? How?
   - Is there an erratum?
```

### 基准论文投稿渠道

| 投稿渠道 | 备注 |
|-------|-------|
| **NeurIPS Datasets & Benchmarks** | 专门方向；此类论文的首选投稿渠道 |
| **ACL** (Resource papers) | 侧重 NLP 数据集 |
| **LREC-COLING** | 语言资源 |
| **TMLR** | 适合分析充分的基准论文 |

---

<a id="position-papers"></a>

## 立场论文

### 何时撰写立场论文

- 你对该领域应如何发展有明确主张
- 你希望挑战一项普遍接受的假设
- 你希望在分析基础上提出研究议程
- 你发现了当前方法论中的系统性问题

### 结构

```
1. Introduction
   - State your thesis clearly in the first paragraph
   - Why this matters now

2. Background
   - Current state of the field
   - Prevailing assumptions you're challenging

3. Argument
   - Present your thesis with supporting evidence
   - Evidence can be: empirical data, theoretical analysis, logical argument,
     case studies, historical precedent
   - Be rigorous — this isn't an opinion piece

4. Counterarguments
   - Engage seriously with the strongest objections
   - Explain why they don't undermine your thesis
   - Concede where appropriate — it strengthens credibility

5. Implications
   - What should the field do differently?
   - Concrete research directions your thesis suggests
   - How should evaluation/methodology change?

6. Conclusion
   - Restate thesis
   - Call to action
```

### 写作标准

- **开篇即提出最有力的论证版本**——不要在第一段含糊其词
- **诚实回应反驳意见**——优秀的立场论文会回应最有力、而非最薄弱的反对意见
- **提供证据**——没有证据的立场论文只是评论文章
- **表述具体**——"the field should do X" 优于 "more work is needed"
- **不要把现有工作当作稻草人**——应公允地描述对立立场

### 立场论文投稿渠道

| 投稿渠道 | 备注 |
|-------|-------|
| **ICML** (Position track) | 专门接收立场论文 |
| **NeurIPS** (Workshop papers) | 研讨会通常欢迎立场类文章 |
| **ACL** (Theme papers) | 适用于论文立场契合会议主题的情况 |
| **TMLR** | 接收论证充分的立场论文 |
| **CACM** | 面向更广泛的计算机科学读者 |

---

<a id="reproducibility-and-replication-papers"></a>

## 可复现性与重复研究论文

### 何时撰写可复现性论文

- 你尝试复现一项已发表的结果，无论最终成功还是失败
- 你希望验证相关论断在不同条件下是否成立
- 你发现某种常用方法的性能取决于论文未报告的细节

### 结构

```
1. Introduction
   - What paper/result are you reproducing?
   - Why is this reproduction valuable?

2. Original Claims
   - State the exact claims from the original paper
   - What evidence was provided?

3. Methodology
   - Your reproduction approach
   - Differences from original (if any) and why
   - What information was missing from the original paper?

4. Results
   - Side-by-side comparison with original results
   - Statistical comparison (confidence intervals overlap?)
   - What reproduced and what didn't?

5. Analysis
   - If results differ: why? What's sensitive?
   - Hidden hyperparameters or implementation details?
   - Robustness to seed, hardware, library versions?

6. Recommendations
   - For original authors: what should be clarified?
   - For practitioners: what to watch out for?
   - For the field: what reproducibility lessons emerge?
```

### 投稿渠道

| 投稿渠道 | 备注 |
|-------|-------|
| **ML Reproducibility Challenge** | NeurIPS 每年举办的挑战赛 |
| **ReScience** | 专门发表重复研究的期刊 |
| **TMLR** | 接收包含深入分析的复现研究 |
| **研讨会** | 各大会议举办的可复现性研讨会 |
