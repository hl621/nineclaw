# Autoreason：迭代优化方法

Autoreason 迭代优化方法的完整参考，内容来自针对主观写作任务、算法竞赛及四个模型层级开展的实验。凡是需要通过迭代提升输出质量（如论文草稿、实验脚本、分析或任务定义），均可参考本方法。

**来源**：[NousResearch/autoreason](https://github.com/NousResearch/autoreason) — “Autoreason：LLM 迭代优化何时有效、为何失败”

---

## 策略选择指南

### 决策树

```
Is the task objectively verifiable (code, math, factual)?
├── YES → Does the model solve it on the first attempt?
│   ├── YES → Use single pass (no refinement needed)
│   └── NO → Use autoreason (structured analysis → reason-informed revision)
│
└── NO (subjective) → What model tier are you using?
    ├── Weak (Llama 8B, small models)
    │   → Single pass. Model too weak for refinement to help.
    │     Invest in generation quality, not iteration.
    │
    ├── Mid-tier (Haiku 3.5, Gemini Flash)
    │   → Autoreason with stronger judges. This is the sweet spot.
    │     Self-refinement DESTROYS weak model outputs — autoreason prevents this.
    │
    ├── Strong (Sonnet 4)
    │   → Autoreason for open-ended tasks. Wins 3/5.
    │     Critique-and-revise for concrete technical tasks (2/5).
    │
    └── Frontier (Sonnet 4.6, Opus)
        ├── Constrained scope? → Autoreason. Wins 2/3 constrained tasks.
        └── Unconstrained? → Critique-and-revise or single pass.
            Autoreason FAILS on unconstrained frontier tasks (comes last).
```

### 策略对比表

| 策略 | 最适用场景 | 不宜使用的场景 | 计算量（每次迭代） |
|----------|----------|------------|------------------------|
| **单次生成** | 前沿模型、模板化任务、预算紧张 | 质量上限偏低且可从迭代中受益的中等模型 | 1 次调用 |
| **批评后修订** | 具有明确技术要求的任务（系统设计、规格说明） | 弱模型（会使输出退化）、无约束的主观任务 | 2 次调用 |
| **Autoreason** | 中等模型、范围受限、确实存在取舍的任务 | 弱模型（Llama 8B）、前沿模型 + 无约束任务 | ~6 次调用 |
| **Best-of-N** | 几乎从不推荐 | 尤其不适用于弱模型——效果不如单次生成 | N 次调用 |

### 各策略为何会失败

| 策略 | 失败模式 | 机制 |
|----------|-------------|-----------|
| **单次生成** | 质量受限 | 没有任何机制能在首次尝试后继续改进 |
| **批评后修订** | 逐轮退化 | 模型迎合指令、虚构问题；每轮范围不断膨胀，而且从不判断是否无需修改 |
| **Best-of-N** | 随机选优 | 缺乏可靠的排序信号时，样本越多只会得到越多平庸选项 |
| **Autoreason（无约束）** | 综合漂移 | 强模型生成的综合版本几乎总是更受偏爱，导致当前最优版本始终无法稳定下来 |

---

## Autoreason 循环

### 架构

```
┌──────────────────────────────────────────────────────────┐
│                    ITERATION LOOP                         │
│                                                           │
│   Incumbent A ──► Critic ──► Author B ──► Synthesizer     │
│       │                                      │            │
│       │              ┌───────────────────────┘            │
│       ▼              ▼                                    │
│      [A]           [AB]          [B]                      │
│       │              │            │                       │
│       └──────────────┼────────────┘                       │
│                      ▼                                    │
│              Judge Panel (blind)                          │
│                      │                                    │
│                      ▼                                    │
│                   Winner                                  │
│                      │                                    │
│              ┌───────┴───────┐                            │
│              ▼               ▼                            │
│         A wins k=2      B or AB wins                      │
│         consecutive?    → new incumbent                   │
│              │                                            │
│              ▼                                            │
│           CONVERGED                                       │
└──────────────────────────────────────────────────────────┘
```

### 角色

每个角色都由一个**全新且相互隔离的智能体**承担，彼此不共享上下文：

| 角色 | 输入 | 输出 | 核心规则 |
|------|-------|--------|----------|
| **Critic** | 任务 + 当前最优版本 A | 问题列表 | 只找问题。不修复，不提建议。 |
| **Author B** | 任务 + A + 批评意见 | 修订版 B | 逐一回应批评，并说明每项改动解决了哪个问题。 |
| **Synthesizer** | 任务 + X + Y（标签随机） | 综合版 AB | 提取两个版本各自最强的部分，而不是折中。 |
| **Judge Panel** | 任务 + A、AB、B（标签与顺序均随机） | 排名 | 从优到劣排序，不因参与创作而对任何版本有所偏袒。 |

### 配置

| 参数 | 取值 | 理由 |
|-----------|-------|-----------|
| **收敛阈值 k** | 2 | k=1 会过早收敛（其中 94% 后续会被替换）。k=2 可实现 100% 收敛，且质量趋于平台期。k=3 有 24% 无法收敛，成本翻倍而质量无提升。 |
| **作者温度** | 0.7-0.8 | 鼓励产生多样化的修订方案 |
| **评审温度** | 0.3 | 提高评估一致性 |
| **循环内评审数** | 3 | 在每轮成本与评估稳定性之间取得平衡 |
| **最终评估评审数** | 7 | 提高最终比较的统计功效 |
| **最大 token 数** | 4096 | 常规设置；长篇内容（如论文）使用 8192 |
| **评审类型** | Chain-of-thought | 在部分任务上可使收敛速度提高 3 倍，应始终使用 |
| **平局处理** | 保守策略（当前最优版本胜出） | 防止假阳性——A 必须被确凿击败才会替换 |
| **最大轮数** | 25（受限任务），50（补救） | 安全上限；大多数任务会在第 10-15 轮收敛 |

### 提示词

#### Critic
```
System: You are a critical reviewer. Your only job is to find real problems. 
Be specific and concrete. Do not suggest fixes.

User: Find real problems with this proposal. Focus on:
- Things that won't work as described
- Complexity that doesn't pay for itself
- Assumptions that are wrong
- Missing pieces
Do NOT propose fixes. Just the problems.
```

#### Author B
```
System: You are a senior consultant revising a proposal based on specific 
criticisms. Address each valid criticism directly. Do not make changes not 
motivated by an identified problem.

User: [TASK] + [VERSION A] + [CRITIC OUTPUT]
Revise to address these problems. For each change, state which problem it fixes.
```

#### Synthesizer
```
System: You are given two versions as equal inputs. Take the strongest elements 
from each and produce a coherent synthesis. This is not a compromise.

User: [TASK] + [VERSION X] + [VERSION Y]
(labels randomized — synthesizer doesn't know which is incumbent)
```

#### Judge（Chain-of-Thought）——始终使用此版本
```
System: You are an independent evaluator. Think carefully before deciding.

User: [TASK] + Three proposals. For each, think step by step:
1. What does it get right?
2. What does it get wrong or miss?
3. Are numbers and claims defensible?
4. Is detail appropriate or bloated?
After reasoning, rank all three.
RANKING: [best], [second], [worst]
```

#### 基线提示词（用于对比实验）

| 基线 | 提示词 |
|----------|--------|
| **Conservative** | “在保留有效内容的前提下做最小幅度的改进。不要新增章节，也不要显著扩大范围。” |
| **Improve this** | “改进这份文档。”（无其他指导） |
| **Harsh critic** | “批判性地评估并重写，修复你发现的所有缺陷。” |
| **Critique & revise** | 第 1 步：“给出结构化批评，列出具体缺陷。”第 2 步：“修订内容，逐一回应每项批评。” |

---

## 评分：Borda 计数法

评审对候选版本排序，并按名次计分：

| 名次 | 分数（3 个候选版本） |
|------|----------------------|
| 第 1 名 | 3 |
| 第 2 名 | 2 |
| 第 3 名 | 1 |

**汇总方式**：将所有评审给出的分数相加，总分最高者胜出。
**平局处理**：任何平局均由当前最优版本（A）胜出。

**示例**（3 名评审）：
- 评审 1：AB > A > B → AB 得 3 分，A 得 2 分，B 得 1 分
- 评审 2：A > AB > B → A 得 3 分，AB 得 2 分，B 得 1 分
- 评审 3：AB > B > A → AB 得 3 分，B 得 2 分，A 得 1 分
- 总分：AB=8，A=6，B=4 → AB 胜出，成为新的当前最优版本

**针对每名评审的随机化处理**：
- 随机化候选版本标签（对一名评审而言，A 可能叫“提案 X”；对另一名评审则可能叫“提案 Z”）
- 随机化呈现顺序（AB 可能排在最前或最后）
- 由此避免位置偏差和标签偏差

---

## 模型选择指南

### 各模型层级的实证结果

| 模型 | Autoreason 获胜次数 | Autoreason 平均 Borda 分 | 最佳基线 | 差值 | 建议 |
|-------|----------------|---------------------|---------------|--------|----------------|
| **Llama 3.1 8B** | 1/3 | 23.7 | 25.0（单次生成） | -1.3 | 跳过 Autoreason。模型能力太弱，无法生成多样化候选版本。 |
| **Gemini 2.0 Flash** | 2/3 | 25.0 | 20.0（单次生成） | +5.0 | 适合采用，可获得中等幅度提升。 |
| **Haiku 3.5** | 3/3 | **42.0** | 33.7（单次生成） | **+8.3** | **最合适。** 得分完美；基线方法反而会显著破坏质量。 |
| **Sonnet 4** | 3/5 | 27.8 | 22.4（C&R） | +5.4 | 适合开放式任务；技术任务使用 C&R 更好。 |
| **Sonnet 4.6（无约束）** | 0/1 | 7.0 | 31.0（C&R） | -24.0 | 没有约束时切勿使用 Autoreason。 |
| **Sonnet 4.6（受限）** | 2/3 | 29.0 | 27.0（改进） | +2.0 | 仅在有范围约束时使用。 |

### 生成—评估差距

核心洞见：**Autoreason 的价值取决于模型生成能力与自我评估能力之间的差距。**

```
Weak models (Llama 8B):
  Generation: Poor  |  Self-evaluation: Poor
  Gap: Small (both bad) → Autoreason can't help, no diverse candidates

Mid-tier models (Haiku, Flash):
  Generation: Decent  |  Self-evaluation: Poor
  Gap: LARGE → Autoreason's sweet spot. External eval bridges the gap.

Strong models (Sonnet 4):
  Generation: Good  |  Self-evaluation: Decent
  Gap: Moderate → Autoreason helps on 3/5 tasks

Frontier models (Sonnet 4.6):
  Generation: Excellent  |  Self-evaluation: Good
  Gap: Small → Simple methods suffice. Autoreason hurts on unconstrained tasks.
```

**实用原则**：随着模型成本下降、能力增强，今天的前沿模型会成为明天的中等模型。生成—评估差距是结构性的，而非暂时现象。应根据模型在能力曲线上的位置，选择与之匹配的优化架构。

### 评审模型选择

| 作者模型 | 建议的评审模型 | 理由 |
|-------------|------------------|-----------|
| Llama 8B | 不要使用 Autoreason | 模型能力太弱 |
| Gemini Flash | Sonnet 4 | 跨模型评估有效 |
| Haiku 3.5 | Sonnet 4 | 强外部评估正是发挥作用的关键机制 |
| Haiku 3.5 | Haiku 3.5（同模型） | 仍然有效——即使没有更强的评审模型，锦标赛结构本身也能创造价值（平均 Borda 分为 20.7，而非 18.3） |
| Sonnet 4 | Sonnet 4（同模型） | 在此层级，同模型评审有效 |
| Sonnet 4.6 | Sonnet 4.6（同模型） | 仅限有范围约束的任务 |

---

## 范围约束设计

### 为何 Autoreason 在受限任务上有效

加入范围约束后，同一个模型（Sonnet 4.6）从**最后一名**（无约束）跃升至**第一名**（有约束）。约束为改进空间划定了边界，使综合漂移无法持续累积。

### 有效约束

| 约束类型 | 示例 | 有效原因 |
|----------------|---------|-------------|
| **固定事实** | “只能使用这 8 个数据点，不得添加其他信息” | 限定信息空间 |
| **固定交付物** | “一份 500 词的创业公司推介稿”（而非“改进这份内容”） | 明确定义完成条件 |
| **固定结构** | “严格分为 4 节，每节包含 3 个编号条目” | 防止结构漂移 |
| **固定修改项** | “只处理这 3 条评审意见” | 限定修改范围 |

### 无效约束

| 约束 | 失败原因 | 后果 |
|-----------|-------------|-------------|
| 只有字数限制 | 字数限制并不等于范围约束 | 出现虚假收敛——版本因长度而非质量被否决 |
| “保持简洁” | 过于模糊 | 经过 2-3 轮后即被忽略 |
| “做到全面” | 属于反向约束 | 诱发范围膨胀 |
| 完全无约束 | 改进空间没有边界 | 综合版本持续占优，无法收敛 |

### 任务类别

| 任务类型 | Autoreason 是否有效？ | 原因 |
|-----------|-------------------|-----|
| 确实存在取舍的任务（战略、政策） | 是 | 存在多种合理路径，可由锦标赛机制进行选择 |
| 受限写作（推介稿、备忘录、复盘报告） | 大多有效（2/3） | 范围有边界，评估标准清晰 |
| 模板填充（事故复盘） | 否 | 正确结构只有一种，决策空间很小 |
| 算法竞赛 | 是 | 任务天然受限，测试套件可提供外部验证 |
| 无约束开放任务 + 前沿模型 | 否 | 综合漂移，无法收敛 |

---

## 失败模式分类

| 失败模式 | 条件 | 识别方式 | 证据 |
|-------------|-----------|-----------|----------|
| **自我纠错不可靠** | 缺少外部评估信号 | 基线结果劣于单次生成 | Haiku 基线平均分为 16.3，单次生成则为 33.7 |
| **漂移／综合版本占优** | 范围无约束 | A 的胜率 <15%，AB 占据主导 | Sonnet 4.6 无约束任务中：A 胜率 12%，AB 胜率 60%+ |
| **过拟合可见反馈** | 浅层修订循环（C&R） | 公开测试与私有测试表现差异大 | C&R 在高难代码题上的过拟合率为 32% |
| **无法收敛** | 评审流程故障 | 解析失败，有效评审少于 3 名 | 混合评审组解析器故障：持续 11+ 轮 |
| **模型能力太弱** | 生成结果缺乏多样性 | 所有候选版本都很相似 | Llama 8B 仅在 1/3 的任务上获胜 |

### 恢复策略

| 失败情况 | 恢复方法 |
|---------|----------|
| 无法收敛（漂移） | 为任务添加范围约束 |
| 无法收敛（评审故障） | 修复解析器，并确保有 3 名有效评审后再继续 |
| 质量随迭代下降 | 改用单次生成，或添加约束 |
| 模型能力太弱 | 使用更强的模型生成内容，将弱模型保留给低成本角色 |
| 过拟合（代码） | 加入结构化分析步骤，而不是只依赖测试反馈 |

---

## 代码领域适配

Autoreason 在代码与写作任务中的适配方式不同：

### 写作领域
```
Call 1: Critic (find problems in incumbent)
Call 2: Author B (revise based on critique)
Call 3: Synthesizer (merge A and B)
Calls 4-6: Judge Panel (3 blind judges rank A, B, AB)
```

### 代码领域（6 次调用预算）
```
Call 1: Initial generation
Call 2: Structured analysis (5 points — NO CODE):
  - Problem analysis: what does the problem actually require?
  - Approach analysis: what approach did we use, is it correct?
  - Failure analysis: why did tests fail?
  - Alternative approaches: what else could work?
  - Edge cases: what inputs might break the solution?
Calls 3-6: Reason-informed revisions
  - Each revision must explain WHY it fixes the issue
  - Sees test results from public (visible) test cases
```

**核心区别**：代码策略以测试套件评估（客观真值）取代评审组。结构化分析步骤（Call 2）是促成恢复的关键：它迫使模型先分析方法*为何*失败，再尝试修复。

**结果**：恢复能力正是该方法发挥作用的机制。在 Autoreason 与单次生成首次均告失败的问题中，Autoreason 的恢复率为 62%，单次生成则为 43%（McNemar p=0.041，Cohen's h=0.32）。

---

## 将 Autoreason 用于论文写作

论文自身也使用 Autoreason 完成了优化（见论文第 8 节）：

### 设置
- 模型：claude-opus-4
- 评审：3 名 Opus 评审
- 增强措施：引入可访问真实实验数据的 Ground-truth critic
- 结果：9 轮后收敛

### 论文优化的关键发现

1. **Ground-truth critic 至关重要**：无法访问真实数据时，Opus 虚构了并不存在的消融研究、置信区间，写错了模型名称和角色描述。获得真实数据后，Critic 在第 1 轮便发现了全部四类问题。

2. **评审组的完整性至关重要**：一名评审的解析器发生故障（Gemini 输出格式不匹配），使有效评审从 3 名降至 2 名，导致流程持续 11+ 轮仍无法收敛。恢复为 3 名正常评审后，同一个当前最优版本仅用 2 轮便收敛。评审故障不仅会增加噪声，更会破坏均衡、阻止收敛。

### 论文优化的建议配置

```
Critic prompt: "You are reviewing a research paper draft. You have access to the 
actual experimental results [GROUND TRUTH DATA]. Find factual errors, unsupported 
claims, hallucinated results, and structural problems. Do not suggest fixes."

Author B prompt: "Revise this paper draft to fix the identified problems. For each 
change, cite the specific problem it addresses. Do not add claims not supported by 
the provided experimental data."

Judge prompt (CoT): "Compare three versions of this paper. For each, evaluate:
1. Factual accuracy against the provided results
2. Clarity of the narrative and contribution
3. Whether claims are properly hedged and supported
4. Writing quality (concision, precision, no filler)
After reasoning, rank all three. RANKING: [best], [second], [worst]"
```

### 应提供哪些真实依据
- 所有实验结果 JSON 文件
- 统计检验输出
- 每张表格和图表的原始数值
- 记录精确超参数的配置文件
- 生成实验结果的代码（用于核实方法描述是否准确）

---

## 计算预算参考

| 方法 | 每轮调用次数 | 典型轮数 | 总调用次数 | 相对成本 |
|--------|---------------|----------------|-------------|---------------|
| 单次生成 | 1 | 1 | 1 | 1x |
| Best-of-N | N | 1 | N | Nx |
| 批评后修订 | 2 | 15 | 30 | 30x |
| Autoreason（循环内） | ~6 | 10-15 | 60-90 | 60-90x |
| Autoreason（含最终评估） | ~6 + 7 | 10-15 + 1 | 67-97 | ~80x |

**成本—质量权衡**：Autoreason 每轮使用约 6 倍计算量，通常还会运行更多轮次。这是切实存在的取舍：该方法以计算成本换取评估质量。对采用中等模型的受限任务而言，这笔交换非常划算；对采用前沿模型的无约束任务而言，则得不偿失。

**CoT 评审可降低成本**：1 名 CoT 评审的评估质量可与 3 名普通评审相当，同时节省约 40% 的成本。应始终使用 CoT 评审。
