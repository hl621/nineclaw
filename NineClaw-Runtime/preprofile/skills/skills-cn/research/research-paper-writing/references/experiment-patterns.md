# 实验设计模式

本文总结了使用 Hermes agent 开展大规模研究实验时提炼出的设计模式与最佳实践，涵盖实验基础设施、评估协议、监控以及故障恢复。

---

## 实验基础设施

### 目录结构

以一致的结构组织实验：

```
workspace/
  experiments/
    run_main.py                # Core experiment runner
    run_baselines.py           # Baseline comparison
    run_ablation.py            # Ablation studies
    strategies.py              # Method implementations
    config.yaml                # Shared configuration
  results/
    <experiment_name>/
      <task_or_problem>/
        <strategy>/
          result.json          # Final metrics
          final_output.md      # Final output artifact
          history.json         # Full trajectory/log
          pass_01/             # Per-iteration artifacts (if iterative)
            intermediate.md
  analysis/
    analyze_results.py         # Statistical analysis
    compute_stats.py           # Significance tests
    make_charts.py             # Visualization
  paper/
    paper.tex                  # LaTeX source
    fig_*.pdf                  # Generated figures
```

### 脚本设计原则

**1. 增量保存（崩溃恢复）**

每个实验脚本都应该在每个工作单元之后保存结果，并在重新启动时跳过已经完成的工作：

```python
import json, os
from pathlib import Path

def run_experiment(problems, strategies, output_dir):
    for problem in problems:
        for strategy in strategies:
            result_path = Path(output_dir) / problem["id"] / strategy / "result.json"
            if result_path.exists():
                print(f"Skipping {problem['id']}/{strategy} (already done)")
                continue
            
            # Run the experiment
            result = execute_strategy(problem, strategy)
            
            # Save immediately
            result_path.parent.mkdir(parents=True, exist_ok=True)
            with open(result_path, 'w') as f:
                json.dump(result, f, indent=2)
```

这种模式可以安全、高效地重新运行实验。如果进程在第 47/150 个问题处崩溃，重启后会跳过前 46 个问题。

**2. 保留产物**

保存所有中间输出，而不只是最终结果。这样无需重跑实验即可开展事后分析：

```python
def save_pass_artifacts(output_dir, pass_num, artifacts):
    """Save all artifacts from a single pass of an iterative method."""
    pass_dir = Path(output_dir) / f"pass_{pass_num:02d}"
    pass_dir.mkdir(parents=True, exist_ok=True)
    
    for name, content in artifacts.items():
        with open(pass_dir / f"{name}.md", 'w') as f:
            f.write(content)
```

**3. 配置管理**

使用 YAML 配置保证可复现性：

```yaml
# config.yaml
model: anthropic/claude-sonnet-4-20250514
author_temperature: 0.8
judge_temperature: 0.3
max_tokens: 4096
num_judges: 3
max_passes: 15
convergence_k: 2
```

```python
import yaml

with open("config.yaml") as f:
    config = yaml.safe_load(f)
```

**4. 关注点分离**

将生成、评估与可视化分别放在不同脚本中：

| 脚本 | 用途 |
|--------|---------|
| `run_experiment.py` | 核心方法执行 |
| `run_baselines.py` | 等计算量的基线比较 |
| `run_eval.py` | 盲评/评审小组 |
| `analyze_results.py` | 统计分析 |
| `make_charts.py` | 生成图表 |

这样既可单独重跑评估而不必重复昂贵的生成过程，也可重新生成图表而不必重跑分析。

---

## 评估协议

### 盲评评审组（适用于主观任务）

在评估主观输出（写作、分析、建议）时，使用盲评小组：

```python
import random

def run_blind_evaluation(outputs: dict, task_prompt: str, num_judges: int = 7):
    """
    Run blind evaluation of multiple method outputs.
    
    Args:
        outputs: {"method_name": "output_text", ...}
        task_prompt: The original task description
        num_judges: Number of independent judge evaluations
    """
    rankings = []
    
    for judge_i in range(num_judges):
        # Randomize labels and presentation order per judge
        methods = list(outputs.keys())
        random.shuffle(methods)
        labels = {m: chr(65 + i) for i, m in enumerate(methods)}  # A, B, C...
        
        # Present to judge with randomized labels
        prompt = f"Task: {task_prompt}\n\n"
        for method in methods:
            prompt += f"--- Proposal {labels[method]} ---\n{outputs[method]}\n\n"
        prompt += "Rank all proposals from best to worst. Format: RANKING: [best], [second], [worst]"
        
        ranking = call_judge(prompt)
        rankings.append({"labels": labels, "ranking": ranking})
    
    # Aggregate via Borda count
    return compute_borda(rankings)

def compute_borda(rankings, n_methods=3):
    """Borda count: 3/2/1 points for 1st/2nd/3rd."""
    scores = {}
    points = {0: n_methods, 1: n_methods - 1, 2: n_methods - 2}  # Adjust for n_methods
    
    for r in rankings:
        for position, method in enumerate(r["ranking"]):
            scores[method] = scores.get(method, 0) + points.get(position, 0)
    
    return scores
```

关键设计决策：
- 每位评审都要**同时随机化标签和呈现顺序**，以避免位置偏差
- 使用**奇数名评审**（3、5 或 7 名），以便打破平局
- **保守处理平局**：平局时判现有方法/基线胜出，以防止假阳性
- **CoT 评审**可用约 40% 的成本达到非 CoT 评审组的质量（1 名 CoT 评审 ≈ 3 名普通评审）

### 代码/客观评估

对于有客观真值可供评估的任务（代码、数学、事实性任务）：

```python
import subprocess

def evaluate_code(solution: str, test_cases: list, timeout: int = 30):
    """Run code solution against test cases with sandboxed execution."""
    results = {"public": [], "private": []}
    
    for test in test_cases:
        try:
            proc = subprocess.run(
                ["python3", "-c", solution],
                input=test["input"],
                capture_output=True,
                timeout=timeout,
                text=True
            )
            actual = proc.stdout.strip()
            expected = test["expected"].strip()
            passed = actual == expected
        except subprocess.TimeoutExpired:
            passed = False
        
        category = "public" if test.get("public") else "private"
        results[category].append(passed)
    
    return {
        "public_pass_rate": sum(results["public"]) / max(len(results["public"]), 1),
        "private_pass_rate": sum(results["private"]) / max(len(results["private"]), 1),
    }
```

### 等计算量比较

始终在相同计算预算下比较各方法。如果你的方法使用 N 次 API 调用，基线也应获得 N 次调用：

| 方法 | 调用预算 | 分配方式 |
|--------|-----------|------------|
| 单轮生成 | 6 次调用 | 6 次独立生成 |
| 批评与修改 | 6 次调用 | 1 次生成 + 5 轮修改 |
| Autoreason | 6 次调用 | 1 次生成 + 1 次分析 + 4 次修订 |
| Best-of-N | 6 次调用 | 6 次独立生成，根据公开测试选出最佳结果 |

### 人工评估设计

许多 ML/NLP 论文都需要人工评估，尤其是涉及主观质量的任务（文本生成、摘要、对话、创意写作）。人工评估设计不当是论文被拒的常见原因。

#### 何时需要人工评估

| 任务类型 | 是否必需？ | 说明 |
|-----------|-----------|-------|
| 文本生成（开放式） | 是 | 仅使用 LLM-as-judge 通常不足以通过 ACL/EMNLP 的评审 |
| 摘要 | 通常需要 | 至少应评估一部分输出 |
| 对话系统 | 是 | 采用用户研究或人工标注 |
| 代码生成 | 否 | 测试套件可提供客观真值 |
| 分类 | 否 | 标准指标就足够了 |
| 任何涉及主观质量的任务 | 强烈建议 | 可显著增强论文的说服力 |

#### 标注协议设计

```
Human Evaluation Protocol:
1. Define the evaluation dimensions (fluency, relevance, factual accuracy, etc.)
2. Create annotation guidelines with examples of each score level
3. Run a pilot with 2-3 annotators on 20-30 examples
4. Compute pilot inter-annotator agreement — if low, revise guidelines
5. Run full evaluation
6. Report: annotator count, agreement metrics, compensation, time per item
```

**评估维度**（选择相关子集）：

| 维度 | 定义 | 量表 |
|-----------|-----------|-------|
| 流畅度 | 语法和自然度 | 1-5 Likert |
| 相关性 | 它是否解决了该任务？ | 1-5 Likert |
| 事实准确性 | 所陈述的事实是否正确？ | 二元或 1-5 |
| 连贯性 | 逻辑衔接与一致性 | 1-5 Likert |
| 信息性 | 是否提供有用的信息？ | 1-5 Likert |
| 总体偏好 | 哪个输出更好？ | A/B/平局（成对比较） |

**成对比较**（比绝对评分更可靠，优先采用）：
- 并排呈现两个输出（随机左/右位置）
- 问：“哪个更好？A/B/平局”
- 区分能力更强，也较少受到标注者评分尺度漂移的影响

#### 标注者间一致性

务必报告一致性指标；否则，审稿人会认为标注结果不可靠。

```python
# Krippendorff's alpha (preferred — handles missing data, any scale)
# pip install krippendorffs-alpha
import krippendorff

# Ratings: rows = annotators, columns = items, values = scores
ratings = [
    [3, 4, 1, 2, 5, None, 3],  # Annotator 1
    [3, 5, 1, 3, 5, 2, 3],     # Annotator 2
    [4, 4, 2, 2, 4, 2, None],  # Annotator 3
]
alpha = krippendorff.alpha(reliability_data=ratings, level_of_measurement="ordinal")
print(f"Krippendorff's alpha: {alpha:.3f}")
# Interpretation: >0.80 good, 0.67-0.80 acceptable, <0.67 questionable
```

```python
# Cohen's kappa (for exactly 2 annotators, categorical data)
from sklearn.metrics import cohen_kappa_score

annotator_1 = [1, 2, 3, 1, 2, 3, 2]
annotator_2 = [1, 2, 2, 1, 3, 3, 2]
kappa = cohen_kappa_score(annotator_1, annotator_2)
print(f"Cohen's kappa: {kappa:.3f}")
# Interpretation: >0.80 excellent, 0.60-0.80 substantial, 0.40-0.60 moderate
```

| 指标 | 适用情形 | 标注者人数 | 量表 |
|--------|------------|-----------|-------|
| Krippendorff's alpha | 默认选择 | 任意人数 | 任意（有序、名义、比率） |
| Cohen's kappa | 2 名标注者、分类数据 | 恰好 2 名 | 名义/有序 |
| Fleiss' kappa | 3 名以上标注者、分类数据 | 3 名以上 | 名义 |
| Pearson/Spearman | 连续分数 | 2 名 | 区间/比率 |

#### 众包平台

| 平台 | 最适合 | 成本 | 质量 |
|----------|----------|------|---------|
| **Prolific** | 学术研究、较高质量 | $8-15/小时 | 高——以学术研究参与者为主 |
| **MTurk** | 大规模、快速完成 | $2-10/小时 | 不稳定——需设置资格条件 |
| **Surge AI** | NLP 专项标注 | Premium | 高——标注者受过训练 |
| **专家标注者** | 特定领域（医学、法律） | 最高 | 最高——但速度较慢 |

**伦理要求**：
- 报告报酬标准（不得低于当地最低工资）
- 如有相关性，说明标注者的人口统计信息
- 如所在机构有要求，取得 IRB/伦理审批
- ACL 系列会议明确要求提供报酬记录

#### 论文中报告的内容

```
Human Evaluation Section Checklist:
- [ ] Number of annotators
- [ ] Annotator qualifications / recruitment method
- [ ] Number of items evaluated
- [ ] Evaluation dimensions with definitions
- [ ] Scale used (Likert, pairwise, binary)
- [ ] Inter-annotator agreement (Krippendorff's alpha or Cohen's kappa)
- [ ] Compensation rate
- [ ] Time per annotation item
- [ ] Whether annotators saw model identities (should be blind)
- [ ] Randomization of presentation order
```

---

## 统计分析

### 必要检验

| 测试 | 何时使用 | Python |
|------|------------|--------|
| McNemar 检验 | 在同一批问题上比较两种方法 | 小 n 使用 `scipy.stats.binomtest` |
| 双比例 z 检验 | 比较成功率 | 自定义实现或 `statsmodels` |
| Fisher 精确检验 | 小样本成对比较 | `scipy.stats.fisher_exact` |
| Bootstrap CI | 任意指标的置信区间 | 自定义 bootstrap |
| Cohen's h | 比例的效应量 | 手动计算 |

### 标准分析脚本

```python
import numpy as np
from scipy import stats
from pathlib import Path
import json

def load_all_results(results_dir):
    """Load all results into a structured format."""
    results = {}
    for result_file in Path(results_dir).rglob("result.json"):
        parts = result_file.relative_to(results_dir).parts
        if len(parts) >= 3:
            experiment, task, strategy = parts[0], parts[1], parts[2]
            data = json.loads(result_file.read_text())
            results.setdefault(experiment, {}).setdefault(strategy, {})[task] = data
    return results

def pairwise_mcnemar(method_a_results, method_b_results):
    """McNemar's test for paired binary outcomes."""
    a_win_b_lose = sum(1 for a, b in zip(method_a_results, method_b_results) if a and not b)
    b_win_a_lose = sum(1 for a, b in zip(method_a_results, method_b_results) if b and not a)
    
    n = a_win_b_lose + b_win_a_lose
    if n < 25:
        # Use exact binomial for small samples
        result = stats.binomtest(a_win_b_lose, n, 0.5)
        p_value = result.pvalue
    else:
        # Chi-squared approximation
        chi2 = (abs(a_win_b_lose - b_win_a_lose) - 1)**2 / (a_win_b_lose + b_win_a_lose)
        p_value = 1 - stats.chi2.cdf(chi2, df=1)
    
    return {
        "a_wins": a_win_b_lose,
        "b_wins": b_win_a_lose,
        "n_discordant": n,
        "p_value": p_value,
        "significant": p_value < 0.05
    }

def bootstrap_ci(data, n_bootstrap=10000, ci=0.95):
    """Bootstrap confidence interval for mean."""
    means = []
    for _ in range(n_bootstrap):
        sample = np.random.choice(data, size=len(data), replace=True)
        means.append(np.mean(sample))
    lower = np.percentile(means, (1 - ci) / 2 * 100)
    upper = np.percentile(means, (1 + ci) / 2 * 100)
    return {"mean": np.mean(data), "ci_lower": lower, "ci_upper": upper}

def cohens_h(p1, p2):
    """Cohen's h effect size for two proportions."""
    return 2 * np.arcsin(np.sqrt(p1)) - 2 * np.arcsin(np.sqrt(p2))
```

### 报告标准

始终在论文中包含：
- **样本量**：n=X 个问题/任务
- **运行次数**：如适用，报告 K 次独立运行
- **误差条**：说明采用标准差还是标准误
- **置信区间**：关键结果报告 95% CI
- **显著性检验**：关键比较报告 p 值
- **效应量**：报告 Cohen's d 或 h，以体现实际显著性

---

## 监控（Cron 模式）

### Cron 提示模板

对于每个实验批次，创建一个监控提示：

```
Check the status of the [EXPERIMENT_NAME] experiment:

1. Process check: ps aux | grep [PROCESS_PATTERN]
2. Log check: tail -30 [LOG_FILE]
3. Results check: ls [RESULT_DIR]/eval/ (or appropriate result location)
4. If results are available:
   - Read the result JSON files
   - Report metrics in a table (Borda scores, accuracy, etc.)
   - Compute key comparisons between methods
5. If all experiments in this batch are complete:
   - git add -A && git commit -m "[COMMIT_MESSAGE]" && git push
   - Report final summary
6. Key question: [SPECIFIC ANALYTICAL QUESTION]

If nothing has changed since the last check, respond with [SILENT].
```

### 监控最佳实践

1. **先检查进程**——如果实验仍在运行、结果尚不完整，就不要读取结果
2. **读取日志尾部** — 查找错误、进度指示器、完成消息
3. **统计完成数与预期总数**——“已完成 45/150 个问题”比“已有一些结果”更有用
4. **使用结构化表格报告**——始终在表格中列出关键指标
5. **回答关键问题**——每个实验完成后都应该有一个具体的分析问题需要回答
6. **无更新时使用 [SILENT]**——没有变化时抑制通知
7. **完成后提交**——每个完成的批次都应使用说明清晰的消息提交

### 监控报告示例

```
## Code Experiments (Haiku 3.5) - COMPLETE

| Strategy | Pass Rate (150 problems) | vs Single |
|----------|------------------------|-----------|
| single_pass | 38.0% | — |
| critique_revise | 35.2% | -2.8pp |
| **autoreason** | **40.0%** | **+2.0pp** |
| best_of_6 | 31.0% | -7.0pp |

Key finding: Autoreason shows +2pp improvement over single pass, while 
best-of-6 collapses due to single-public-test selection issue.

Committed: `git commit -m "Add Haiku code results (150 problems, 4 strategies)"`
Next: Run significance tests on these results.
```

---

## 故障恢复

### 常见故障及恢复

| 故障 | 检测 | 恢复 |
|---------|-----------|----------|
| **API 额度耗尽** | 日志中出现 402 错误，结果不完整 | 补充额度后重跑（自动跳过已完成的工作） |
| **速率限制** | 出现 429 错误，进度缓慢 | 添加采用指数退避的重试逻辑 |
| **进程崩溃** | PID 消失，日志在处理某个问题时中断 | 重跑脚本（从最近的检查点继续） |
| **模型 ID 错误** | 出现找不到模型的错误 | 修正 ID（例如，应为 `claude-opus-4-6`，而非 `claude-opus-4.6`） |
| **并行导致减速** | 每个实验耗时增至 2 倍 | 将并行实验数降至最多 2–3 个 |
| **安全扫描拦截** | 命令被安全机制阻止 | 使用 `execute_code`，而不是通过管道组合 `terminal` 命令 |
| **委托失败** | `delegate_task` 返回错误 | 回退到直接执行工作 |
| **难题超时** | 进程卡住，日志没有进展 | 终止进程、跳过该问题，并在结果中注明 |
| **数据集路径不匹配** | 出现文件未找到错误 | 启动前验证路径 |

### 重试命名约定

重新运行失败的实验时，使用后缀来跟踪轮次：

```
logs/experiment_haiku_0_50.log       # Round 1
logs/experiment_haiku_0_50_r2.log    # Round 2 (after credit exhaustion)
logs/experiment_haiku_0_50_r3.log    # Round 3 (after bug fix)
```

### 启动前检查清单

在启动任何实验批次之前：

```
Pre-Flight:
- [ ] API credits sufficient for estimated calls
- [ ] Model IDs correct (test with 1 problem first)
- [ ] Output directory exists and is writable
- [ ] Resume logic works (re-run won't overwrite existing results)
- [ ] Log file path is unique (won't overwrite previous logs)
- [ ] Dataset/task files are accessible
- [ ] Config matches intended experiment
```

---

## 任务/基准设计

### 开放式任务（主观评价）

设计目标明确、但质量需要主观判断的任务：

```markdown
# Task: [Title]

## Context
[Specific scenario with concrete details: company size, constraints, timeline]

## Deliverable
[Exact format and structure required]

## Requirements
- [Specific, measurable requirements]
- [Not vague — "be comprehensive" is bad, "include exactly 6 sections" is good]
```

### 约束任务（用于测试范围效应）

约束型任务用于检验方法能否遵守范围边界。设计时应包含：

- **固定事实**：“仅使用这 N 个数据点，不得添加其他内容”
- **固定交付物**：明确指定格式（提案、事后复盘、备忘录——而不是“改进它”）
- **固定结构**：“这些部分按此顺序，请勿添加/删除”
- **固定修改项**：“只处理这 N 点，不得涉及其他内容”

**不要用字数限制来约束范围。** 字数限制会造成假收敛——输出是因长度而非质量被拒。应约束范围（包含什么），而不是篇幅。

### 示例：好约束与坏约束

| 不良约束 | 为什么 | 良好约束 |
|---------------|-----|-----------------|
| “最多 500 字” | 评审会因篇幅而拒绝 | “严格分为 4 节，每节包含 3 个编号条目” |
| “简明扼要” | 太模糊 | “每项禁令必须引用特定的基本事实” |
| “改进它” | 范围无边界 | “严格按此结构撰写一篇 600 字的事件复盘” |
| “让它更好” | 缺乏明确标准 | “只处理这 3 条审稿意见” |

---

## 可视化最佳实践

### 设置：SciencePlots + matplotlib

安装 SciencePlots，以使用适合论文发表的默认设置：

```bash
pip install SciencePlots matplotlib numpy
```

**选项 A：SciencePlots 样式**（推荐 — 自动处理大多数默认值）：

```python
import matplotlib.pyplot as plt
import scienceplots  # registers the styles

# Pick a style:
# 'science'        — clean, serif fonts, suitable for most venues
# 'science+ieee'   — IEEE-style (good for two-column papers)
# 'science+nature' — Nature-style
# Add 'no-latex' if LaTeX is not installed on the machine generating plots

with plt.style.context(['science', 'no-latex']):
    fig, ax = plt.subplots(figsize=(3.5, 2.5))  # single-column width
    # ... plot ...
    fig.savefig('paper/fig_results.pdf', bbox_inches='tight')
```

**选项 B：手动设置 rcParams**（需要完全控制时）：

```python
import matplotlib.pyplot as plt

plt.rcParams.update({
    'font.size': 10,
    'font.family': 'serif',
    'axes.labelsize': 11,
    'axes.titlesize': 11,
    'xtick.labelsize': 9,
    'ytick.labelsize': 9,
    'legend.fontsize': 9,
    'figure.figsize': (3.5, 2.5),    # single-column default
    'figure.dpi': 300,
    'savefig.dpi': 300,
    'savefig.bbox': 'tight',
    'savefig.pad_inches': 0.05,
    'axes.linewidth': 0.8,
    'lines.linewidth': 1.5,
    'lines.markersize': 5,
    'axes.grid': True,
    'grid.alpha': 0.3,
    'grid.linewidth': 0.5,
})
```

### 标准图表尺寸（两栏格式）

| 使用场景 | figsize | 说明 |
|----------|---------|-------|
| 单列 | `(3.5, 2.5)` | 适合两列布局中的一列 |
| 双栏 | `(7.0, 3.0)` | 横跨整个页面宽度 |
| 方形（热图、混淆矩阵） | `(3.5, 3.5)` | 单列 |
| 单栏纵向长图（多行） | `(3.5, 5.0)` | 谨慎使用 |

### 色觉缺陷友好调色板（Okabe-Ito）

所有论文图表都应使用这套调色板。对各种常见色觉缺陷人群而言，其中各颜色仍可区分：

```python
COLORS = {
    'blue':    '#0072B2',
    'orange':  '#E69F00',
    'green':   '#009E73',
    'red':     '#D55E00',
    'purple':  '#CC79A7',
    'cyan':    '#56B4E9',
    'yellow':  '#F0E442',
    'black':   '#000000',
}

# As a list for cycling:
COLOR_CYCLE = ['#0072B2', '#D55E00', '#009E73', '#E69F00', '#CC79A7', '#56B4E9']
```

除颜色外，还应使用**标记点和线型**区分曲线：
```python
STYLES = [
    {'color': '#0072B2', 'marker': 'o', 'linestyle': '-'},
    {'color': '#D55E00', 'marker': 's', 'linestyle': '--'},
    {'color': '#009E73', 'marker': '^', 'linestyle': '-.'},
    {'color': '#E69F00', 'marker': 'D', 'linestyle': ':'},
]
```

### 完整示例：方法对比柱状图

```python
import matplotlib.pyplot as plt
import numpy as np

try:
    import scienceplots
    style = ['science', 'no-latex']
except ImportError:
    style = 'default'

with plt.style.context(style):
    methods = ['Single Pass', 'Critique+Revise', 'Best-of-N', 'Ours']
    scores = [73.2, 74.1, 68.5, 77.0]
    errors = [2.1, 1.8, 3.2, 1.5]
    colors = ['#56B4E9', '#E69F00', '#CC79A7', '#0072B2']
    
    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    bars = ax.bar(methods, scores, yerr=errors, capsize=3,
                  color=colors, edgecolor='black', linewidth=0.5)
    
    # Highlight "Ours"
    bars[-1].set_edgecolor('#0072B2')
    bars[-1].set_linewidth(1.5)
    
    ax.set_ylabel('Pass Rate (%)')
    ax.set_ylim(60, 85)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    fig.savefig('paper/fig_comparison.pdf', bbox_inches='tight')
```

### 完整示例：收敛/轨迹折线图

```python
with plt.style.context(style):
    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    
    passes = np.arange(1, 16)
    ours = [65, 72, 78, 82, 85, 87, 88, 89, 89.5, 90, 90, 90, 90, 90, 90]
    baseline = [65, 68, 70, 71, 69, 67, 66, 65, 64, 63, 62, 61, 60, 59, 58]
    
    ax.plot(passes, ours, **STYLES[0], label='Ours', markersize=4)
    ax.plot(passes, baseline, **STYLES[1], label='Critique+Revise', markersize=4)
    
    # Mark convergence point
    ax.axvline(x=10, color='gray', linestyle=':', alpha=0.5, linewidth=0.8)
    ax.annotate('Converged', xy=(10, 90), fontsize=8, ha='center',
                xytext=(10, 93), arrowprops=dict(arrowstyle='->', color='gray'))
    
    ax.set_xlabel('Iteration')
    ax.set_ylabel('Quality Score')
    ax.legend(loc='lower right')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    fig.savefig('paper/fig_trajectory.pdf', bbox_inches='tight')
```

### 输出规则

- **始终保存为 PDF**：`fig.savefig('fig.pdf')`——矢量图形在任意缩放比例下都清晰
- **论文图表切勿保存为 PNG**——光栅 PNG 在打印或缩放时会显得模糊
- **例外**：截图、照片或像素艺术可视化应保存为 600 DPI 的 PNG
- **检查灰度效果**：输出灰度 PDF，确认所有信息仍清晰可辨

### 用于常见比较的图表类型

| 比较类型 | 图表 | 注释 |
|----------------|-------|-------|
| 方法间比较 | 分组柱状图 | 包含误差条 |
| 不同模型规模 | 带 CI 区间带的折线图 | 模型规模轴使用对数刻度 |
| 消融实验 | 堆叠/分组柱状图 | 突出被移除的组件 |
| 轨迹/收敛 | 按迭代轮次绘制折线图 | 展示每轮的最佳方法 |
| 分任务结果 | 热图或分组柱状图 | 展示不同任务间的差异 |
