# ML 论文写作理念与最佳实践

本参考资料汇集了 Neel Nanda、Andrej Karpathy、Sebastian Farquhar、Zachary Lipton 和 Jacob Steinhardt 等知名机器学习研究者的写作建议。

---

## 目录

- [叙事原则](#the-narrative-principle)
- [时间分配](#time-allocation)
- [摘要写作公式](#abstract-writing-formula)
- [引言结构](#introduction-structure)
- [句子层面的清晰度](#sentence-level-clarity)
- [措辞与精确性](#word-choice-and-precision)
- [数学写作](#mathematical-writing)
- [图表设计](#figure-design)
- [应避免的常见错误](#common-mistakes-to-avoid)

---

<a id="the-narrative-principle"></a>

## 叙事原则

### Neel Nanda 的观点

“论文是一个简短、严谨、有证据支撑的技术故事，并且要有读者关心的核心结论。”

这一叙事建立在三大支柱之上；在引言结束前，三者都必须清晰明确：

**“做了什么”（What）**：围绕一个连贯主题，提出一至三个具体且新颖的主张。“我们研究了 X”之类含糊的贡献表述一开始就站不住脚——审稿人需要的是精确、可证伪的主张。

**“为什么可信”（Why）**：用严谨的实证证据有力支持这些主张，包括经过公平且充分调优的强基线，以及能够区分相互竞争的假设、而非仅仅展示“结果还不错”的实验。

**“有何意义”（So What）**：说明读者为何应当关心，并将你的贡献与研究社区公认的重要问题联系起来。

### Andrej Karpathy 的观点

“论文不是你随意汇报的一堆实验。论文要推介的，是一项此前并不显然或尚未出现的核心成果。整篇论文都应像外科手术一样精准地围绕这一核心贡献组织。”

无论你提出的是新架构、理论结果，还是对现有方法更深入的理解，这一原则都适用——NeurIPS 也明确指出，“原创性并不一定要求提出全新的方法”。

**实践含义**：如果你无法用一句话说明自己的贡献，就还没有形成一篇论文。其他所有内容——实验、相关工作、讨论——都只是为了支撑这一核心主张。

---

<a id="time-allocation"></a>

## 时间分配

### Neel Nanda 的观点

以下四部分应各投入大致**相同的时间**：
1. 摘要
2. 引言
3. 图表
4. 其余所有内容的总和

这并非夸张——多数审稿人在读到方法部分之前便已形成初步判断。读者通常按可预测的顺序接触论文：**标题 → 摘要 → 引言 → 图表 → 也许再读其余内容。**

### 审稿人的阅读模式

有关审稿行为的研究表明：
- 摘要的阅读率为 100%
- 超过 90% 的审稿人会浏览引言
- 多数审稿人会先看图表，再看方法
- 只有论文成功引起兴趣，审稿人才会完整阅读方法部分

**启示**：应尽早展示论文的价值，不要把贡献埋在后文。

---

<a id="abstract-writing-formula"></a>

## 摘要写作公式

### Sebastian Farquhar 的五句公式

1. **你取得了什么成果**："We introduce..."、"We prove..."、"We demonstrate..."
2. **这件事为什么困难且重要**
3. **你如何做到**（加入便于检索的专业关键词）
4. **你有哪些证据**
5. **最有说服力的数据或结果**

### 示例（优秀摘要）

```
We prove that gradient descent on overparameterized neural networks
converges to global minima at a linear rate. [What]
This resolves a fundamental question about why deep learning works
despite non-convex optimization landscapes. [Why hard/important]
Our proof relies on showing that the Neural Tangent Kernel remains
approximately constant during training, reducing the problem to
kernel regression. [How with keywords]
We validate our theory on CIFAR-10 and ImageNet, showing that
predicted convergence rates match experiments within 5%. [Evidence]
This is the first polynomial-time convergence guarantee for
networks with practical depth and width. [Remarkable result]
```

### 应避免的写法

Zachary Lipton 说：“如果第一句话可以原封不动地放到任何一篇 ML 论文前面，就删掉它。”

**删除这类开头**：
- “大型语言模型取得了非凡的成功……”
- “深度学习彻底改变了……”
- “近年来，神经网络……”

**直接从你的具体贡献讲起。**

---

<a id="introduction-structure"></a>

## 引言结构

### 要求

- **最多 1–1.5 页**（双栏格式）
- **方法部分应在第 2–3 页开始**
- 必须包含 **2–4 条贡献要点**（每条最多 1–2 行）

### 结构模板

```markdown
1. Opening Hook (2-3 sentences)
   - State the problem your paper addresses
   - Why it matters RIGHT NOW

2. Background/Challenge (1 paragraph)
   - What makes this problem hard?
   - What have others tried? Why is it insufficient?

3. Your Approach (1 paragraph)
   - What do you do differently?
   - Key insight that enables your contribution

4. Contribution Bullets (2-4 items)
   - Be specific and falsifiable
   - Each bullet: 1-2 lines maximum

5. Results Preview (2-3 sentences)
   - Most impressive numbers
   - Scope of evaluation

6. Paper Organization (optional, 1-2 sentences)
   - "Section 2 presents... Section 3 describes..."
```

### 贡献要点：好的写法与差的写法

**好：**
- 我们证明了在假设 Y 下，X 可在 O(n log n) 时间内收敛
- 我们提出 Z：一种将内存用量降低 40% 的三层架构
- 我们的实验表明，A 在基准 C 上的表现比 B 高出 15%

**差：**
- 我们研究了 X 问题（这不是贡献）
- 我们开展了大量实验（过于含糊）
- 我们为该领域做出了多项贡献（没有提供任何信息）

---

<a id="sentence-level-clarity"></a>

## 句子层面的清晰度

### Gopen 与 Swan：《The Science of Scientific Writing》

George Gopen 与 Judith Swan 在 1990 年发表的奠基性论文指出，**读者对信息在行文中出现的位置有结构上的预期**。违背这些预期，会迫使读者把精力耗费在解析结构而非理解内容上。

> “要让读者理解作者的意思，作者必须先理解读者的需要。”

#### 读者预期的七项原则

**原则 1：主语与谓语相邻**

让语法主语和谓语尽量靠近。夹在二者之间的内容会被读成次要的插入信息。

**较弱**：“该模型使用 1 亿个 token 训练，并通过 rank 为 16 的 LoRA 在领域特定数据上微调，取得了 state-of-the-art 结果”

**较强**：“该模型取得了 state-of-the-art 结果；训练使用 1 亿个 token，之后又通过 LoRA（rank 16）进行了微调”

**原则 2：重读位置（把重点留到最后）**

读者自然会强调**句末的词语**。将最重要的信息放在那里。

**较弱**：“使用注意力机制后，准确率提高了 15%”
**较强**：“使用注意力机制后，准确率提高了 **15%**”

**原则 3：主题位置（开门见山）**

句首决定了读者理解句子的视角。先写“这是谁的故事”——读者会期待句子围绕最先出现的对象展开。

**较弱**：“一种用于计算对齐分数的新型注意力机制被提出”
**较强**：“为解决对齐问题，我们提出了一种新的注意力机制”

**原则 4：旧信息在前，新信息在后**

把熟悉的信息（旧信息）放在主题位置，以承接上文；把新信息放在重读位置，以突出重点。

**较弱**：“Child 等人提出了稀疏注意力。标准注意力的二次复杂度促使了这项工作。”
**较强**：“标准注意力具有二次复杂度。为解决这一问题，Child 等人提出了稀疏注意力。”

**原则 5：一个单元承担一种功能**

每个论述单元（句子、段落或章节）都应只承担一种功能。如果有两个要点，就使用两个单元。

**原则 6：用动词表达动作**

用句子的动词表达动作，而不要把动作名词化。

**较弱**：“我们对结果进行了分析”（名词化）
**较强**：“我们分析了结果”（用动词表达动作）

**原则 7：先交代语境，再引入新信息**

要求读者思考新内容之前，先提供必要语境。这适用于句子、段落和章节等各个层级。

**较弱**：“公式 3 表明，当学习率满足……时，可以保证收敛”
**较强**：“为保证收敛，学习率必须满足公式 3 中的条件……”

#### 汇总表

| 原则 | 规则 | 助记语 |
|-----------|------|----------|
| 主谓相邻 | 让主语与谓语靠近 | “不要打断自己” |
| 重读位置 | 在句末强调重点 | “把最好的留到最后” |
| 主题位置 | 在句首交代语境 | “开门见山” |
| 旧信息在前 | 熟悉 → 陌生 | “立足已知再推进” |
| 一个单元，一种功能 | 每段只讲一个要点 | “一个容器装一个想法” |
| 动作用动词表达 | 使用动词，避免名词化 | “动词做事，名词静止” |
| 语境先于新信息 | 先解释，再呈现 | “先搭好舞台” |

---

## 微观写作技巧

### Ethan Perez（Anthropic）的建议

以下实用的微观技巧可提升句子和词语层面的清晰度。

#### 代词管理

**尽量少用代词**（"this"、"it"、"these"、"that"）。必须使用时，让代词修饰一个名词：

**较弱**：“这表明模型收敛了。”
**较强**：“这一结果表明模型收敛了。”

**较弱**：“它提升了性能。”
**较强**：“这一修改提升了性能。”

#### 动词位置

**尽早在句中出现动词**，让句子更易解析：

**较弱**：“梯度在经过计算和归一化后更新权重。”
**较强**：“梯度更新权重，而更新前会先完成计算和归一化。”

#### 展开所有格

为提升清晰度，可以改写所有格结构：

**原形式**："X's Y" → **展开后**："The Y of X"

**改写前**："The model's accuracy on the test set"
**改写后**："The accuracy of the model on the test set"

这种改写并非总是更好，但句子显得别扭时，可以尝试展开所有格。

#### 应删除的词

几乎在所有情况下，都应删除以下填充词：
- "actually"
- "a bit"
- "fortunately" / "unfortunately"
- "very" / "really"
- "quite"
- "basically"
- "essentially"
- 不必要的连接词（如 "however"、"moreover"、"furthermore"）

#### 句子构造规则

1. **每句话只表达一个想法**——如果一个想法很难用一句话说清，就拆成两句
2. **避免声音重复**——同一句中避免使用发音相近的词
3. **每句话都应增加信息**——删除仅仅复述前文的句子
4. **始终使用主动语态**——明确动作发出者（用 "We find..."，不用 "It is found..."）
5. **展开缩约形式**——正式写作中将 "don't" 改为 "do not"

#### 段落结构

- **第一句**：清楚陈述要点
- **中间各句**：用证据支撑要点
- **最后一句**：强化要点或过渡到下文

不要把关键信息埋在段落中间。

---

<a id="word-choice-and-precision"></a>

## 措辞与精确性

### Zachary Lipton 的建议

除非确实存在不确定性，否则应**消除模糊限定语**：
- 除非必要，否则删除 "may" 和 "can"
- "provides *very* tight approximation" 显得底气不足
- "provides tight approximation" 更加自信

**避免空洞的程度副词**：
- 删除 very、extremely、highly、significantly（表达统计显著性时除外）
- 这些词传达的不是力度，而是不自信

### Jacob Steinhardt 的建议

**精确胜于简洁**：用具体术语替换模糊词语。

| 模糊 | 具体 |
|-------|----------|
| 性能 | 准确率、延迟、吞吐量 |
| 改进 | 准确率提高 X%，延迟降低 Y |
| 大 | 1B 参数、100M token |
| 快 | 快 3 倍、延迟 50ms |
| 结果好 | 准确率 92%、F1 为 0.85 |

**术语保持一致**：用不同术语指代同一个概念会造成混淆。

**选择一种说法并坚持使用**：
- "model"、"network" 与 "architecture"
- "training"、"learning" 与 "optimization"
- "sample"、"example" 与 "instance"

### 用词传递的信号

**避免暗示工作只是渐进式改进的词**：
- 绝不要用："combine"、"modify"、"expand"、"extend"
- 改用："develop"、"propose"、"introduce"

**原因**："We combine X and Y" 听起来像是把两个既有想法拼在一起；"We develop a method that leverages X for Y" 则更像一项真正的贡献。

---

<a id="mathematical-writing"></a>

## 数学写作

### Ethan Perez 的建议

为提升清晰度，应**展开所有格**：
- 较弱："X's Y"
- 较强："The Y of X"

示例："the model's accuracy" → "the accuracy of the model"

### 一般原则

1. **在定理之前正式陈述所有假设**
2. **在给出证明的同时提供直观解释**
3. **整篇论文使用一致的符号**
4. **符号首次出现时即给出定义**

### 符号约定

```latex
% Scalars: lowercase italic
$x$, $y$, $\alpha$, $\beta$

% Vectors: lowercase bold
$\mathbf{x}$, $\mathbf{v}$

% Matrices: uppercase bold
$\mathbf{W}$, $\mathbf{X}$

% Sets: uppercase calligraphic
$\mathcal{X}$, $\mathcal{D}$

% Functions: roman for named functions
$\mathrm{softmax}$, $\mathrm{ReLU}$
```

---

<a id="figure-design"></a>

## 图表设计

### Neel Nanda 的建议

即使读者跳过正文，图表本身也应讲述一个连贯的故事。许多读者最初确实会跳过正文。

### 设计原则

1. **图 1 至关重要**：它通常是读者读完摘要后首先查看的内容
2. **图注应当自包含**：不看正文也能理解图表
3. **图内不要放标题**：标题功能由图注承担（ICML/NeurIPS 的规则）
4. **使用矢量图**：绘图使用 PDF/EPS；只有照片才使用 PNG（600 DPI）

### 无障碍要求

8% 的男性存在色觉障碍。图表必须对他们同样可读。

**解决方案**：
- 使用色觉障碍友好的调色板，如 Okabe-Ito 或 Paul Tol
- 避免红绿配色
- 检查图表在灰度模式下是否仍然清晰
- 除颜色外，再用实线、虚线、点线等不同线型加以区分

### 工具

```python
# SciencePlots: Publication-ready styles
import matplotlib.pyplot as plt
plt.style.use(['science', 'ieee'])

# Or for Nature-style
plt.style.use(['science', 'nature'])
```

---

<a id="common-mistakes-to-avoid"></a>

## 应避免的常见错误

### 结构错误

| 错误 | 解决方案 |
|---------|----------|
| 引言过长（>1.5 页） | 将背景内容移至相关工作 |
| 方法部分埋得太深（第 3 页以后） | 提前呈现贡献，精简引言 |
| 缺少贡献要点 | 添加 2–4 条具体、可证伪的主张 |
| 实验没有明确对应的主张 | 说明每项实验检验什么 |

### 写作错误

| 错误 | 解决方案 |
|---------|----------|
| 摘要以泛泛之谈开头 | 从具体贡献讲起 |
| 术语不一致 | 每个概念只选择一个术语 |
| 过度使用被动语态 | 使用主动语态：写 "We show"，不要写 "It is shown" |
| 到处使用模糊限定语 | 除非确实不确定，否则语气应当明确 |

### 图表错误

| 错误 | 解决方案 |
|---------|----------|
| 绘图使用光栅图 | 使用矢量格式（PDF/EPS） |
| 使用红绿色系 | 使用色觉障碍友好的调色板 |
| 图内包含标题 | 将标题信息放入图注 |
| 必须阅读正文才能理解图注 | 让图注自包含 |

### 引用错误

| 错误 | 解决方案 |
|---------|----------|
| 相关工作逐篇罗列 | 按方法类别组织 |
| 遗漏相关引用 | 审稿人也可能是相关论文作者，应充分引用 |
| 使用 AI 生成的引用 | 始终通过 API 核验 |
| 引用格式不一致 | 使用 BibLaTeX，并统一 citation key |

---

## 投稿前检查清单

提交前请确认：

**叙事**：
- [ ] 能用一句话陈述贡献
- [ ] 引言中清楚呈现三大支柱（What/Why/So What）
- [ ] 每项实验都支撑一个具体主张

**结构**：
- [ ] 摘要遵循五句公式
- [ ] 引言不超过 1.5 页
- [ ] 方法部分在第 2–3 页开始
- [ ] 包含 2–4 条贡献要点
- [ ] 包含局限性章节

**写作**：
- [ ] 全文术语一致
- [ ] 没有泛泛而谈的开场句
- [ ] 已删除不必要的模糊限定语
- [ ] 所有图表都有自包含的图注

**技术**：
- [ ] 所有引用均已通过 API 核验
- [ ] 提供误差条，并说明计算方法
- [ ] 记录计算资源
- [ ] 说明代码和数据的可用性
