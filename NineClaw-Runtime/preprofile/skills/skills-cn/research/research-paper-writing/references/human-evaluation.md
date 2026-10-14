# ML/AI 研究中的人工评估指南

本指南全面介绍如何在 ML/AI 论文中设计、实施和报告人工评估。人工评估是许多 NLP、HCI 和对齐研究论文的主要证据；如今，各类 ML 会议也越来越期待研究者将其作为补充证据。

---

## 目录

- [何时需要人工评估](#when-human-evaluation-is-needed)
- [研究设计](#study-design)
- [标注指南](#annotation-guidelines)
- [平台与招募](#platforms-and-recruitment)
- [质量控制](#quality-control)
- [一致性指标](#agreement-metrics)
- [人工评估的统计分析](#statistical-analysis-for-human-eval)
- [报告要求](#reporting-requirements)
- [IRB 与伦理](#irb-and-ethics)
- [常见问题](#common-pitfalls)

---

<a id="when-human-evaluation-is-needed"></a>

## 何时需要人工评估

| 场景 | 是否需要人工评估？ | 说明 |
|----------|---------------------|-------|
| 文本生成质量（流畅性、连贯性） | **是** | 自动指标（BLEU、ROUGE）与人类判断的相关性较弱 |
| 生成文本的事实准确性 | **强烈建议** | 自动事实核查并不可靠 |
| 安全性/毒性评估 | **细微复杂的情形需要** | 分类器容易遗漏依赖上下文的危害 |
| 比较两个系统的偏好 | **是** | 这是比较 LLM 输出最可靠的方法 |
| 摘要质量 | **是** | ROUGE 难以充分反映忠实性和相关性 |
| 任务完成情况（UI、智能体） | **是** | 用户研究是金标准 |
| 分类准确率 | **通常不需要** | 有真实标签即可；人工评估只会增加成本，却无法带来额外洞见 |
| 困惑度或损失的比较 | **否** | 此时应使用自动指标进行评估 |

---

<a id="study-design"></a>

## 研究设计

### 评估类型

| 类型 | 何时使用 | 优点 | 缺点 |
|------|-------------|------|------|
| **成对比较** | 比较两个系统 | 最可靠，可最大限度减小量表偏差 | 每次只能比较一对；比较次数随系统数量呈二次增长 |
| **Likert 量表**（1-5 或 1-7） | 为单个输出评分 | 便于汇总 | 易受主观锚定影响，且评分容易向少数档位集中 |
| **排序** | 对 3 个以上的系统排序 | 能体现完整的偏好次序 | 项目越多，认知负荷越高 |
| **最佳—最差量表法** | 高效比较多个系统 | 比 Likert 量表更可靠，所需比较量随项目数线性增长 | 需要仔细选择比较项目 |
| **二元判断** | 是/否判断（是否合乎语法？是否符合事实？） | 简单，一致性高 | 无法体现细微差异 |
| **错误标注** | 识别具体的错误类型 | 可提供丰富的诊断信息 | 成本高，需要受过训练的标注者 |

**对大多数 ML 论文的建议**：成对比较最经得起推敲，审稿人很少质疑其有效性。如果使用 Likert 量表，务必同时报告均值和分布。

### 样本量规划

**最低可行样本量：**

| 研究类型 | 最少项目数 | 最少标注者数 | 说明 |
|------------|--------------|-------------------|-------|
| 成对比较 | 100 对 | 每对 3 人 | 在 p<0.05 时可检出约 10% 的胜率差异 |
| Likert 评分 | 100 项 | 每项 3 人 | 足以得到有意义的平均分 |
| 排序 | 50 组 | 每组 3 人 | 每组包含所有待比较的系统 |
| 错误标注 | 200 项 | 每项 2 人 | 结构化标注方案通常能达到更高的一致性 |

**功效分析**（用于更精确地规划样本量）：

```python
from scipy import stats
import numpy as np

def sample_size_pairwise(effect_size=0.10, alpha=0.05, power=0.80):
    """
    Estimate sample size for pairwise comparison (sign test).
    effect_size: expected win rate difference from 0.50
    """
    p_expected = 0.50 + effect_size
    # Normal approximation to binomial
    z_alpha = stats.norm.ppf(1 - alpha / 2)
    z_beta = stats.norm.ppf(power)
    n = ((z_alpha * np.sqrt(0.25) + z_beta * np.sqrt(p_expected * (1 - p_expected))) ** 2) / (effect_size ** 2)
    return int(np.ceil(n))

print(f"Sample size for 10% effect: {sample_size_pairwise(0.10)}")  # ~200
print(f"Sample size for 15% effect: {sample_size_pairwise(0.15)}")  # ~90
print(f"Sample size for 20% effect: {sample_size_pairwise(0.20)}")  # ~50
```

### 控制偏差

| 偏差 | 缓解方法 |
|------|-----------|
| **顺序偏差**（倾向于选择第一项） | 针对每位标注者随机安排呈现顺序 |
| **长度偏差**（越长越好） | 控制文本长度，或按长度分别分析 |
| **锚定效应**（第一次标注为后续评分设定基准） | 加入不计入结果的热身项目 |
| **疲劳效应**（质量随时间下降） | 限制单次标注时长（最长 30-45 分钟），并随机安排项目顺序 |
| **标注者专业水平** | 报告标注者背景，并设置资格测试 |

---

<a id="annotation-guidelines"></a>

## 标注指南

标注指南的质量是影响评估质量的首要因素，值得投入充足的时间精心编写。

### 优质指南的结构

```markdown
# [Task Name] Annotation Guidelines

## Overview
[1-2 sentences describing the task]

## Definitions
[Define every term annotators will use in their judgments]
- Quality: [specific definition for this study]
- Fluency: [specific definition]
- Factuality: [specific definition]

## Rating Scale
[For each scale point, provide:]
- Numeric value
- Label (e.g., "Excellent", "Good", "Acceptable", "Poor", "Unacceptable")
- Definition of what qualifies for this rating
- 1-2 concrete examples at this level

## Examples

### Example 1: [Rating = 5]
Input: [exact input]
Output: [exact output]
Rating: 5
Explanation: [why this is a 5]

### Example 2: [Rating = 2]
Input: [exact input]
Output: [exact output]
Rating: 2
Explanation: [why this is a 2]

[Include at least 2 examples per rating level, covering edge cases]

## Edge Cases
- If the output is [ambiguous case]: [instruction]
- If the input is [unusual case]: [instruction]

## Common Mistakes
- Don't [common annotator error]
- Don't let [bias] influence your rating
```

### 试点测试

**正式开展完整研究前，务必先进行试点测试**：
1. 邀请 3-5 名标注者，标注 20-30 个项目
2. 计算一致性指标
3. 组织小组讨论，分析意见分歧
4. 针对容易引起困惑之处修订指南
5. 若一致性较差（kappa <0.40），再进行一轮试点测试

---

<a id="platforms-and-recruitment"></a>

## 平台与招募

| 平台 | 最适合 | 成本 | 质量 |
|----------|----------|------|---------|
| **Prolific** | 通用标注、问卷调查 | $8-15/小时 | 高（参与者以学术研究为主） |
| **Amazon MTurk** | 大规模简单任务 | $5-12/小时 | 参差不齐（需要严格的质量控制） |
| **Surge AI** | NLP 专项标注 | $15-25/小时 | 很高（标注者经过培训） |
| **Scale AI** | 生产级数据标注 | 视情况而定 | 高（由平台管理标注团队） |
| **内部团队** | 需要领域专业知识的任务 | 视情况而定 | 对专业任务而言最高 |
| **Upwork/承包人员** | 长期标注项目 | $10-30/小时 | 取决于招募质量 |

**公平报酬**：报酬至少应达到标注者所在地的最低工资标准。许多会议（尤其是 ACL）如今会询问标注者报酬；低于最低工资会带来伦理风险。

**Prolific 设置（适合大多数 ML 论文）：**
1. 在 prolific.co 上创建研究项目
2. 设置预筛选条件（语言、国家、通过率 >95%）
3. 根据试点测试估算每项任务的用时 → 据此设定公平报酬
4. 使用 Prolific 内置的注意力检查，或自行添加检查项
5. 收集 Prolific ID 以便跟踪质量（但不要在论文中披露）

---

<a id="quality-control"></a>

## 质量控制

### 注意力检查

加入正确答案明确无歧义的项目：

```python
# Types of attention checks
attention_checks = {
    "instructed_response": "For this item, please select 'Strongly Agree' regardless of content.",
    "obvious_quality": "Rate this clearly ungrammatical text: 'The cat dog house green yesterday.'",  # Should get lowest score
    "gold_standard": "Items where expert consensus exists (pre-annotated by authors)",
    "trap_question": "What color is the sky on a clear day? (embedded in annotation interface)"
}

# Recommended: 10-15% of total items should be checks
# Exclusion criterion: fail 2+ attention checks → exclude annotator
```

### 标注者资格筛选

对于需要专业知识的任务，可按以下方式进行筛选：

```
Qualification Task Design:
1. Create a set of 20-30 items with known-correct labels
2. Require annotators to complete this before the main task
3. Set threshold: ≥80% agreement with gold labels to qualify
4. Record qualification scores for reporting
```

### 数据收集期间的监控

```python
# Real-time quality monitoring
def monitor_quality(annotations):
    """Check for annotation quality issues during collection."""
    issues = []
    
    # 1. Check for straight-lining (same answer for everything)
    for annotator_id, items in annotations.groupby('annotator'):
        if items['rating'].nunique() <= 1:
            issues.append(f"Annotator {annotator_id}: straight-lining detected")
    
    # 2. Check time per item (too fast = not reading)
    median_time = annotations['time_seconds'].median()
    fast_annotators = annotations.groupby('annotator')['time_seconds'].median()
    for ann_id, time in fast_annotators.items():
        if time < median_time * 0.3:
            issues.append(f"Annotator {ann_id}: suspiciously fast ({time:.0f}s vs median {median_time:.0f}s)")
    
    # 3. Check attention check performance
    checks = annotations[annotations['is_attention_check']]
    for ann_id, items in checks.groupby('annotator'):
        accuracy = (items['rating'] == items['gold_rating']).mean()
        if accuracy < 0.80:
            issues.append(f"Annotator {ann_id}: failing attention checks ({accuracy:.0%})")
    
    return issues
```

---

<a id="agreement-metrics"></a>

## 一致性指标

### 如何选择指标

| 指标 | 适用情形 | 含义 |
|--------|-------------|---------------|
| **Cohen's kappa (κ)** | 恰好 2 名标注者，类别型数据 | 经随机一致性校正后的一致程度 |
| **Fleiss' kappa** | 3 名及以上标注者；所有人评估相同项目；类别型数据 | Cohen's kappa 的多标注者扩展 |
| **Krippendorff's alpha (α)** | 任意数量的标注者，可处理缺失数据 | 适用范围最广；建议作为默认选择 |
| **ICC（组内相关系数）** | 连续型评分（Likert） | 评分者之间的一致性 |
| **一致率** | 与 kappa/alpha 一并报告 | 未经随机一致性校正的原始一致程度 |
| **Kendall's W** | 排序数据 | 多名排序者之间的协调一致程度 |

**务必至少报告两项指标**：一项经随机一致性校正的指标（kappa 或 alpha），以及原始一致率。

### 解读指南

| 数值 | Krippendorff's α / Cohen's κ | 质量 |
|-------|-------------------------------|---------|
| > 0.80 | 一致性极佳 | 对大多数用途都足够可靠 |
| 0.67 - 0.80 | 一致性良好 | 大多数 ML 论文可以接受 |
| 0.40 - 0.67 | 一致性中等 | 处于临界水平；应在论文中讨论 |
| < 0.40 | 一致性较差 | 修订指南并重新标注 |

**注意**：Krippendorff 建议以 α > 0.667 作为得出初步结论的最低标准。对于涉及主观判断（如流畅性、有用性）的 NLP 任务，通常只能达到 0.40-0.70。

### 实现

```python
import numpy as np
from sklearn.metrics import cohen_kappa_score
import krippendorff  # pip install krippendorff

def compute_agreement(annotations_matrix):
    """
    annotations_matrix: shape (n_items, n_annotators)
    Values: ratings (int or float). Use np.nan for missing.
    """
    results = {}
    
    # Krippendorff's alpha (handles missing data, any number of annotators)
    results['krippendorff_alpha'] = krippendorff.alpha(
        annotations_matrix.T,  # krippendorff expects (annotators, items)
        level_of_measurement='ordinal'  # or 'nominal', 'interval', 'ratio'
    )
    
    # Pairwise Cohen's kappa (for 2 annotators at a time)
    n_annotators = annotations_matrix.shape[1]
    kappas = []
    for i in range(n_annotators):
        for j in range(i + 1, n_annotators):
            mask = ~np.isnan(annotations_matrix[:, i]) & ~np.isnan(annotations_matrix[:, j])
            if mask.sum() > 0:
                k = cohen_kappa_score(
                    annotations_matrix[mask, i].astype(int),
                    annotations_matrix[mask, j].astype(int)
                )
                kappas.append(k)
    results['mean_pairwise_kappa'] = np.mean(kappas) if kappas else None
    
    # Raw percent agreement
    agree_count = 0
    total_count = 0
    for item in range(annotations_matrix.shape[0]):
        ratings = annotations_matrix[item, ~np.isnan(annotations_matrix[item, :])]
        if len(ratings) >= 2:
            # All annotators agree
            if len(set(ratings.astype(int))) == 1:
                agree_count += 1
            total_count += 1
    results['percent_agreement'] = agree_count / total_count if total_count > 0 else None
    
    return results
```

---

<a id="statistical-analysis-for-human-eval"></a>

## 人工评估的统计分析

### 成对比较

```python
from scipy import stats

def analyze_pairwise(wins_a, wins_b, ties=0):
    """
    Analyze pairwise comparison results.
    wins_a: number of times system A won
    wins_b: number of times system B won
    ties: number of ties (excluded from sign test)
    """
    n = wins_a + wins_b  # exclude ties
    
    # Sign test (exact binomial)
    p_value = stats.binom_test(wins_a, n, 0.5, alternative='two-sided')
    
    # Win rate with 95% CI (Wilson score interval)
    win_rate = wins_a / n if n > 0 else 0.5
    z = 1.96
    denominator = 1 + z**2 / n
    center = (win_rate + z**2 / (2 * n)) / denominator
    margin = z * np.sqrt((win_rate * (1 - win_rate) + z**2 / (4 * n)) / n) / denominator
    ci_lower = center - margin
    ci_upper = center + margin
    
    return {
        'win_rate_a': win_rate,
        'win_rate_b': 1 - win_rate,
        'p_value': p_value,
        'ci_95': (ci_lower, ci_upper),
        'significant': p_value < 0.05,
        'n_comparisons': n,
        'ties': ties,
    }
```

### Likert 量表分析

```python
def analyze_likert(ratings_a, ratings_b):
    """Compare Likert ratings between two systems (paired)."""
    # Wilcoxon signed-rank test (non-parametric, paired)
    stat, p_value = stats.wilcoxon(ratings_a, ratings_b, alternative='two-sided')
    
    # Effect size (rank-biserial correlation)
    n = len(ratings_a)
    r = 1 - (2 * stat) / (n * (n + 1))
    
    return {
        'mean_a': np.mean(ratings_a),
        'mean_b': np.mean(ratings_b),
        'std_a': np.std(ratings_a),
        'std_b': np.std(ratings_b),
        'wilcoxon_stat': stat,
        'p_value': p_value,
        'effect_size_r': r,
        'significant': p_value < 0.05,
    }
```

### 多重比较校正

比较两个以上的系统时：

```python
from statsmodels.stats.multitest import multipletests

# After computing p-values for all pairs
p_values = [0.03, 0.001, 0.08, 0.04, 0.15, 0.002]
rejected, corrected_p, _, _ = multipletests(p_values, method='holm')
# Use corrected p-values in your paper
```

---

<a id="reporting-requirements"></a>

## 报告要求

NLP 会议（ACL、EMNLP、NAACL）的审稿人会逐项核查以下内容；ML 会议（NeurIPS、ICML）也越来越重视这些信息。

### 必须报告的内容

```latex
% In your paper's human evaluation section:
\paragraph{Annotators.} We recruited [N] annotators via [platform].
[Describe qualifications or screening.] Annotators were paid
\$[X]/hour, above the [country] minimum wage.

\paragraph{Agreement.} Inter-annotator agreement was [metric] = [value]
(Krippendorff's $\alpha$ = [value]; raw agreement = [value]\%).
[If low: explain why the task is subjective and how you handle disagreements.]

\paragraph{Evaluation Protocol.} Each [item type] was rated by [N]
annotators on a [scale description]. We collected [total] annotations
across [N items]. [Describe randomization and blinding.]
```

### 附录应包含的内容

```
Appendix: Human Evaluation Details
- Full annotation guidelines (verbatim)
- Screenshot of annotation interface
- Qualification task details and threshold
- Attention check items and failure rates
- Per-annotator agreement breakdown
- Full results table (not just averages)
- Compensation calculation
- IRB approval number (if applicable)
```

---

<a id="irb-and-ethics"></a>

## IRB 与伦理

### 何时需要 IRB 批准

| 情形 | 是否需要 IRB？ |
|-----------|---------------|
| 众包工作者评估文本质量 | **通常不需要**（多数机构不将其视为“人类受试者研究”） |
| 针对真实用户开展用户研究 | **需要**（在大多数美国/欧盟机构） |
| 收集个人信息 | **是** |
| 研究标注者的行为或认知 | **是**（标注者本身成为研究对象） |
| 使用已有的标注数据 | **通常不需要**（属于二次数据分析） |

**请查阅所在机构的政策。** 各机构对“人类受试者研究”的定义并不相同。如有疑问，应提交 IRB 审查方案；对于最低风险研究，审查通常很快。

### 人工评估伦理核对清单

```
- [ ] Annotators informed about task purpose (not deceptive)
- [ ] Annotators can withdraw at any time without penalty
- [ ] No personally identifiable information collected beyond platform ID
- [ ] Content being evaluated does not expose annotators to harm
  (if it does: content warnings + opt-out + higher compensation)
- [ ] Fair compensation (>= equivalent local minimum wage)
- [ ] Data stored securely, access limited to research team
- [ ] IRB approval obtained if required by institution
```

---

<a id="common-pitfalls"></a>

## 常见问题

| 问题 | 后果 | 解决办法 |
|---------|---------|-----|
| 标注者太少（1-2 人） | 无法计算一致性指标 | 每个项目至少安排 3 名标注者 |
| 未设置注意力检查 | 无法识别低质量标注 | 让注意力检查占全部项目的 10-15% |
| 未报告报酬 | 审稿人会将其视为伦理问题 | 务必报告时薪 |
| 评估生成任务时只使用自动指标 | 审稿人会要求补充人工评估 | 至少加入成对比较 |
| 未对标注指南进行试点测试 | 一致性低，浪费预算 | 务必先用 3-5 人进行试点测试 |
| 只报告平均值 | 掩盖标注者之间的分歧 | 同时报告分布和一致性 |
| 未控制顺序/位置 | 位置偏差会夸大结果 | 随机安排呈现顺序 |
| 将标注者一致性等同于真实正确性 | 高一致性并不代表判断正确 | 对照专家判断进行验证 |
