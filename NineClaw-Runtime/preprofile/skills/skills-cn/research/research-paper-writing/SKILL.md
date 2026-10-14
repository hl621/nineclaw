---
name: research-paper-writing
title: Research Paper Writing Pipeline
description: "为 NeurIPS/ICML/ICLR 撰写 ML 论文：从设计到投稿。"
version: 1.1.0
author: Orchestra Research
license: MIT
dependencies: [semanticscholar, arxiv, habanero, requests, scipy, numpy, matplotlib, SciencePlots]
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Research, Paper Writing, Experiments, ML, AI, NeurIPS, ICML, ICLR, ACL, AAAI, COLM, LaTeX, Citations, Statistical Analysis]
    category: research
    related_skills: [arxiv, subagent-driven-development, plan]
    requires_toolsets: [terminal, files]

---

# 研究论文写作流程

用于产出可投稿的 ML/AI 研究论文的端到端流程，目标会议包括 **NeurIPS、ICML、ICLR、ACL、AAAI 和 COLM**。本技能覆盖完整的研究生命周期：实验设计、执行、监控、分析、论文撰写、评审、修订与投稿。

这**不是线性流程**，而是一个迭代循环：实验结果会触发新的实验，评审意见会触发新的分析。Agent 必须能够处理这些反馈循环。

<!-- ascii-guard-ignore -->
```
┌─────────────────────────────────────────────────────────────┐
│                    RESEARCH PAPER PIPELINE                  │
│                                                             │
│  Phase 0: Project Setup ──► Phase 1: Literature Review      │
│       │                          │                          │
│       ▼                          ▼                          │
│  Phase 2: Experiment     Phase 5: Paper Drafting ◄──┐      │
│       Design                     │                   │      │
│       │                          ▼                   │      │
│       ▼                    Phase 6: Self-Review      │      │
│  Phase 3: Execution &           & Revision ──────────┘      │
│       Monitoring                 │                          │
│       │                          ▼                          │
│       ▼                    Phase 7: Submission               │
│  Phase 4: Analysis ─────► (feeds back to Phase 2 or 5)     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```
<!-- ascii-guard-ignore-end -->

---

## 何时使用此技能

在以下情况下使用此技能：
- **从现有代码库或想法出发撰写新的研究论文**
- **设计并运行实验**，为论文主张提供支撑
- **撰写或修订**研究论文的任何章节
- **准备向特定会议或研讨会投稿**
- **回应评审意见**，补充实验或进行修订
- **在不同会议模板之间转换**论文格式
- **撰写非实证类论文**——理论、综述、基准测试或立场论文（参见[实证 ML 以外的论文类型](#paper-types-beyond-empirical-ml)）
- **为 NLP、HCI 或对齐研究设计人工评测**
- **准备论文接收后的交付材料**——海报、报告和代码发布

## 核心理念

1. **积极主动。** 交付完整草稿，而不是只提出问题。科研人员时间有限——先给出可供审阅的具体成果，再根据反馈迭代。
2. **绝不捏造引用信息。** AI 生成的参考文献引用约有 40% 的错误率。务必通过程序检索引用信息；无法核验的引用应标记为 `[CITATION NEEDED]`。
3. **论文讲述的是一个完整故事，而不是实验的堆砌。** 每篇论文都需要用一句话清晰概括核心贡献。如果做不到，说明论文尚未准备好。
4. **实验服务于论文主张。** 每个实验都必须明确说明它支撑哪项主张。不要开展与论文叙事无关的实验。
5. **尽早提交，频繁提交。** 每完成一批实验、每更新一次论文草稿，都应使用描述清晰的消息提交。Git log 就是实验历史。

### 主动协作

**默认原则：保持主动。先起草，再带着草稿提问。**

| 置信度 | 行动 |
|-----------------|--------|
| **High**（代码仓库清晰、贡献明确） | 完成全文草稿，交付后根据反馈迭代 |
| **Medium**（存在一些不确定之处） | 起草并标注不确定项，然后继续推进 |
| **Low**（存在重大未知事项） | 通过 `clarify` 提出 1–2 个针对性问题，然后起草 |

| 章节 | 是否自主起草？ | 随草稿标注的说明 |
|---------|-------------------|-----------------|
| 摘要 | 是 | “我将贡献定位为 X——如有需要请调整” |
| 引言 | 是 | “我重点强调了问题 Y——如有偏差请指出” |
| 方法 | 是 | “已包含细节 A、B、C——请补充遗漏内容” |
| 实验 | 是 | “重点展示了结果 1、2、3——如有需要请调整顺序” |
| 相关工作 | 是 | “已引用论文 X、Y、Z——请补充我遗漏的文献” |

**仅在以下情况等待输入**：目标投稿会议或期刊尚未明确、存在多个相互矛盾的论述框架、结果似乎不完整，或对方明确要求先审阅。

---

## 阶段 0：项目设置

**目标**：建立工作区，了解现有工作，并确定论文贡献。

### 步骤 0.1：探索代码仓库

```bash
# Understand project structure
ls -la
find . -name "*.py" | head -30
find . -name "*.md" -o -name "*.txt" | xargs grep -l -i "result\|conclusion\|finding"
```

重点查看：
- `README.md`——项目概述与主张
- `results/`、`outputs/`、`experiments/`——已有实验发现
- `configs/`——实验配置
- `.bib` 文件——已有引文
- 草稿文档或研究笔记

### 步骤 0.2：组织工作区

建立统一的工作区结构：

```
workspace/
  paper/               # LaTeX source, figures, compiled PDFs
  experiments/         # Experiment runner scripts
  code/                # Core method implementation
  results/             # Raw experiment results (auto-generated)
  tasks/               # Task/benchmark definitions
  human_eval/          # Human evaluation materials (if needed)
```

### 步骤 0.3：设置版本控制

```bash
git init  # if not already
git remote add origin <repo-url>
git checkout -b paper-draft  # or main
```

**Git 规范**：每完成一批实验，都使用描述清晰的消息提交。例如：
```
Add Monte Carlo constrained results (5 runs, Sonnet 4.6, policy memo task)
Add Haiku baseline comparison: autoreason vs refinement baselines at cheap model tier
```

### 步骤 0.4：确定贡献

在动笔之前，先明确以下三点：
- **核心内容（The What）**：这篇论文唯一且核心的贡献是什么？
- **论据（The Why）**：有哪些证据支撑这一贡献？
- **意义（The So What）**：读者为什么应该关心？

> 向科研人员提出：“根据我的理解，论文的主要贡献是：[一句话]。关键结果表明 [Y]。这是否是你希望采用的论述框架？”

### 步骤 0.5：创建 TODO 列表

使用 `todo` 工具创建结构化项目计划：

```
Research Paper TODO:
- [ ] Define one-sentence contribution
- [ ] Literature review (related work + baselines)
- [ ] Design core experiments
- [ ] Run experiments
- [ ] Analyze results
- [ ] Write first draft
- [ ] Self-review (simulate reviewers)
- [ ] Revise based on review
- [ ] Submission prep
```

在整个项目期间持续更新该列表。它可作为跨会话保留的持久状态。

### 步骤 0.6：估算计算预算

运行实验前，估算总成本和所需时间：

```
Compute Budget Checklist:
- [ ] API costs: (model price per token) × (estimated tokens per run) × (number of runs)
- [ ] GPU hours: (time per experiment) × (number of experiments) × (number of seeds)
- [ ] Human evaluation costs: (annotators) × (hours) × (hourly rate)
- [ ] Total budget ceiling and contingency (add 30-50% for reruns)
```

在实验运行过程中跟踪实际支出：
```python
# Simple cost tracker pattern
import json, os
from datetime import datetime

COST_LOG = "results/cost_log.jsonl"

def log_cost(experiment: str, model: str, input_tokens: int, output_tokens: int, cost_usd: float):
    entry = {
        "timestamp": datetime.now().isoformat(),
        "experiment": experiment,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
    }
    with open(COST_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
```

**预算紧张时**：先运行试点实验（1–2 个随机种子、部分任务），再投入完整的参数扫描。调试实验流程时使用成本较低的模型，最终运行时再切换到目标模型。

### 步骤 0.7：多作者协作

大多数论文有 3–10 位作者。应尽早建立协作流程：

| 协作方式 | 工具 | 适用场景 |
|----------|------|-------------|
| **Overleaf** | 浏览器端 | 多位作者需要同时编辑，且缺乏 git 使用经验 |
| **Git + LaTeX** | 使用 `git`，并通过 `.gitignore` 忽略辅助文件 | 技术团队，需要基于分支进行审阅 |
| **Overleaf + Git 同步** | Overleaf Premium | 兼顾两者优势——实时协作并保留版本历史 |

**章节负责人**：每个章节指定一位主要作者。其他作者只添加评论，不直接修改，以避免合并冲突和文风不一致。

```
Author Coordination Checklist:
- [ ] Agree on section ownership (who writes what)
- [ ] Set up shared workspace (Overleaf or git repo)
- [ ] Establish notation conventions (before anyone writes)
- [ ] Schedule internal review rounds (not just at the end)
- [ ] Designate one person for final formatting pass
- [ ] Agree on figure style (colors, fonts, sizes) before creating figures
```

**需要尽早统一的 LaTeX 约定**：
- 使用 `\method{}` 宏统一方法名称
- 引用格式：明确 `\citet{}` 与 `\citep{}` 的使用规则
- 数学符号：向量使用小写粗体，矩阵使用大写粗体，等等
- 统一使用英式或美式拼写

---

## 阶段 1：文献综述

**目标**：查找相关工作、确定基线并收集引文。

### 步骤 1.1：确定种子论文

从代码库中已引用的论文开始：

```bash
# Via terminal:
grep -r "arxiv\|doi\|cite" --include="*.md" --include="*.bib" --include="*.py"
find . -name "*.bib"
```

### 步骤 1.2：搜索相关工作

**加载 `arxiv` 技能**以便结构化地发现论文：`skill_view("arxiv")`。该技能支持 arXiv REST API 搜索、Semantic Scholar 引用图谱、作者档案和 BibTeX 生成。

使用 `web_search` 进行广泛检索，使用 `web_extract` 获取特定论文：

```
# Via web_search:
web_search("[main technique] + [application domain] site:arxiv.org")
web_search("[baseline method] comparison ICML NeurIPS 2024")

# Via web_extract (for specific papers):
web_extract("https://arxiv.org/abs/2303.17651")
```

还可以尝试以下检索式：

```
Search queries:
- "[main technique] + [application domain]"
- "[baseline method] comparison"
- "[problem name] state-of-the-art"
- Author names from existing citations
```

**推荐**：安装 **Exa MCP**，用于实时学术检索：
```bash
claude mcp add exa -- npx -y mcp-remote "https://mcp.exa.ai/mcp"
```

### 步骤 1.2b：深化检索（先广度，后深度）

仅进行一轮查询的平面检索通常会遗漏重要的相关工作。采用受深度研究流程启发的迭代式**先广度、后深度**模式：

```
Iterative Literature Search:

Round 1 (Breadth): 4-6 parallel queries covering different angles
  - "[method] + [domain]"
  - "[problem name] state-of-the-art 2024 2025"
  - "[baseline method] comparison"
  - "[alternative approach] vs [your approach]"
  → Collect papers, extract key concepts and terminology

Round 2 (Depth): Generate follow-up queries from Round 1 learnings
  - New terminology discovered in Round 1 papers
  - Papers cited by the most relevant Round 1 results
  - Contradictory findings that need investigation
  → Collect papers, identify remaining gaps

Round 3 (Targeted): Fill specific gaps
  - Missing baselines identified in Rounds 1-2
  - Concurrent work (last 6 months, same problem)
  - Key negative results or failed approaches
  → Stop when new queries return mostly papers you've already seen
```

**停止条件**：如果某一轮返回的论文中，超过 80% 已存在于你的文献库，说明检索已趋于饱和。通常 2–3 轮即可；综述论文一般需要 4–5 轮。

**对于基于 Agent 的工作流**：通过 `delegate_task` 并行委派每轮查询。收集结果并去重，再根据汇总后的发现生成下一轮查询。

### 步骤 1.3：验证每条引文

**切勿凭记忆生成 BibTeX。务必通过程序获取。**

对每条引文，都必须执行以下 5 个步骤：

```
Citation Verification (MANDATORY per citation):
1. SEARCH → Query Semantic Scholar or Exa MCP with specific keywords
2. VERIFY → Confirm paper exists in 2+ sources (Semantic Scholar + arXiv/CrossRef)
3. RETRIEVE → Get BibTeX via DOI content negotiation (programmatically, not from memory)
4. VALIDATE → Confirm the claim you're citing actually appears in the paper
5. ADD → Add verified BibTeX to bibliography
If ANY step fails → mark as [CITATION NEEDED], inform scientist
```

```python
# Fetch BibTeX via DOI
import requests

def doi_to_bibtex(doi: str) -> str:
    response = requests.get(
        f"https://doi.org/{doi}",
        headers={"Accept": "application/x-bibtex"}
    )
    response.raise_for_status()
    return response.text
```

如果某条引文无法验证：

```latex
\cite{PLACEHOLDER_author2024_verify_this}  % TODO: Verify this citation exists
```

**务必告知科研人员**：“我已将 [X] 条引用标记为需要核验的占位符。”

有关完整 API 文档和完整的 `CitationManager` 类，请参阅 [references/citation-workflow.md](references/citation-workflow.md)。

### 步骤 1.4：组织相关工作

按研究方法对论文分组，而不要逐篇罗列：

**Good**：“一类工作采用 X 的假设 [引文]，而我们采用 Y 的假设，因为……”
**Bad**：“Smith et al. 提出了 X。Jones et al. 提出了 Y。我们将二者结合。”

---

## 阶段 2：实验设计

**目标**：设计能够直接支撑论文主张的实验。每个实验都必须回答一个具体问题。

### 步骤 2.1：将论文主张映射到实验

建立明确的映射关系：

| 论文主张 | 实验 | 预期证据 |
|-------|-----------|-------------------|
| “我们的方法优于基线” | 主要对比实验（表 1） | 胜率、统计显著性 |
| “模型越弱，效果提升越明显” | 模型规模扩展研究 | 单调上升的改进曲线 |
| “收敛需要限定范围” | 有约束与无约束的对比 | 收敛率对比 |

**规则**：如果某项实验无法对应到一项论文主张，就不要运行它。

### 步骤 2.2：设计基线

高质量的基线设置是论文能否被接收的关键分水岭。审稿人会问：“是否与 X 进行了比较？”

标准基线类别：
- **朴素基线**：最简单的方法
- **强基线**：当前已知的最佳方法
- **消融基线**：从你的方法中移除一个组件
- **计算量匹配基线**：使用相同计算预算，但采用不同分配方式

### 步骤 2.3：定义评测协议

运行任何实验之前，先明确：
- **指标**：测量什么，以及方向符号（越高/越低越好）
- **聚合方式**：如何汇总多次运行或多个任务的结果
- **统计检验**：使用哪些检验来确认统计显著性
- **样本量**：运行、问题或任务的数量

### 步骤 2.4：编写实验脚本

遵循成功研究工作流中的以下模式：

**增量保存**——每一步完成后都保存结果，以便在崩溃后恢复：
```python
# Save after each problem/task
result_path = f"results/{task}/{strategy}/result.json"
if os.path.exists(result_path):
    continue  # Skip already-completed work
# ... run experiment ...
with open(result_path, 'w') as f:
    json.dump(result, f, indent=2)
```

**产物保存** — 保存所有中间输出：
```
results/<experiment>/
  <task>/
    <strategy>/
      final_output.md          # Final result
      history.json             # Full trajectory
      pass_01/                 # Per-iteration artifacts
        version_a.md
        version_b.md
        critic.md
```

**关注点分离** — 将生成、评估与可视化相互分离：
```
run_experiment.py              # Core experiment runner
run_baselines.py               # Baseline comparison
run_comparison_judge.py        # Blind evaluation
analyze_results.py             # Statistical analysis
make_charts.py                 # Visualization
```

完整的设计模式、cron 监控与错误恢复方法，请参阅 [references/experiment-patterns.md](references/experiment-patterns.md)。

### 步骤 2.5：设计人工评估（如适用）

许多 NLP、HCI 和对齐研究论文都需要以人工评估作为主要或补充证据。应在运行自动化实验之前完成设计，因为人工评估通常筹备周期更长（例如 IRB 审批和标注者招募）。

**何时需要人工评估：**
- 自动化指标无法衡量你真正关心的属性（如流畅性、有用性、安全性）
- 你的贡献涉及面向用户的品质（如可读性、偏好、信任）
- NLP 会议（ACL、EMNLP）的审稿人通常期望生成任务包含人工评估

**关键设计决策：**

| 决策 | 选项 | 建议 |
|----------|---------|----------|
| **标注者类型** | 专家、众包工作者、最终用户 | 根据论文主张所需的专业程度选择 |
| **量表** | Likert (1-5)、成对比较、排序 | 对 LLM 输出而言，成对比较通常比 Likert 量表更可靠 |
| **样本量** | 每位标注者的样本数和总条目数 | 进行功效分析；或至少评估 100 个条目，每个条目由 3 名以上标注者评估 |
| **一致性指标** | Cohen's kappa、Krippendorff's alpha、ICC | 标注者超过 2 名时使用 Krippendorff's alpha；同时报告原始一致率 |
| **平台** | Prolific、MTurk、内部团队 | 注重质量时选 Prolific；注重规模时选 MTurk；需要领域专长时选内部团队 |

**标注指南检查清单：**
```
- [ ] Clear task description with examples (good AND bad)
- [ ] Decision criteria for ambiguous cases
- [ ] At least 2 worked examples per category
- [ ] Attention checks / gold standard items (10-15% of total)
- [ ] Qualification task or screening round
- [ ] Estimated time per item and fair compensation (>= local minimum wage)
- [ ] IRB/ethics review if required by your institution
```

**报告要求**（审稿人会逐项检查）：
- 标注者人数及其资质
- 标注者间一致性，并明确报告所用指标及数值
- 报酬详情（金额、估算时薪）
- 标注界面说明或截图（放入附录）
- 标注总耗时

完整指南（包括人工评估数据的统计检验、众包质量控制模式和 IRB 指引）请参阅 [references/human-evaluation.md](references/human-evaluation.md)。

---

## 第 3 阶段：实验执行与监控

**目标**：可靠地运行实验、监控进度，并从故障中恢复。

### 步骤 3.1：启动实验

对长时间运行的实验使用 `nohup`：

```bash
nohup python run_experiment.py --config config.yaml > logs/experiment_01.log 2>&1 &
echo $!  # Record the PID
```

**并行执行**：可以同时运行相互独立的实验，但要留意 API 速率限制。在同一 API 上并发运行 4 个以上的实验，会使每个实验都变慢。

### 步骤 3.2：设置监控（Cron 模式）

对长时间运行的实验，应设置定期状态检查。cron 提示词应遵循以下模板：

```
Monitor Prompt Template:
1. Check if process is still running: ps aux | grep <pattern>
2. Read last 30 lines of log: tail -30 <logfile>
3. Check for completed results: ls <result_dir>
4. If results exist, read and report: cat <result_file>
5. If all done, commit: git add -A && git commit -m "<descriptive message>" && git push
6. Report in structured format (tables with key metrics)
7. Answer the key analytical question for this experiment
```

**静默模式**：如果自上次检查后没有任何变化，则回复 `[SILENT]`，以免向用户发送通知。仅在有新进展时报告。

### 步骤 3.3：处理故障

常见故障模式及恢复方法：

| 故障 | 检测 | 恢复 |
|---------|-----------|----------|
| API 速率限制 / 额度耗尽 | 日志中出现 402/429 错误 | 等待后重新运行（脚本应跳过已完成的工作） |
| 进程崩溃 | PID 已消失、结果不完整 | 从最近的检查点重新运行 |
| 困难问题导致超时 | 进程卡住、日志无进展 | 终止并跳过，在结果中注明 |
| 模型 ID 错误 | 报错信息提及模型名称 | 修正 ID 后重新运行 |

**关键要求**：脚本应始终检查已有结果，并跳过已完成的工作，从而确保重复运行既安全又高效。

### 步骤 3.4：提交已完成的结果

每批实验完成后：

```bash
git add -A
git commit -m "Add <experiment name>: <key finding in 1 line>"
git push
```

### 步骤 3.5：维护实验日志

Git 提交会记录发生了什么，却不会记录**探索树**——即你根据已获得的认识决定下一步尝试什么。应维护结构化实验日志来记录这棵树：

```json
// experiment_journal.jsonl — append one entry per experiment attempt
{
  "id": "exp_003",
  "parent": "exp_001",
  "timestamp": "2025-05-10T14:30:00Z",
  "hypothesis": "Adding scope constraints will fix convergence failure from exp_001",
  "plan": "Re-run autoreason with max_tokens=2000 and fixed structure template",
  "config": {"model": "haiku", "strategy": "autoreason", "max_tokens": 2000},
  "status": "completed",
  "result_path": "results/exp_003/",
  "key_metrics": {"win_rate": 0.85, "convergence_rounds": 3},
  "analysis": "Scope constraints fixed convergence. Win rate jumped from 0.42 to 0.85.",
  "next_steps": ["Try same constraints on Sonnet", "Test without structure template"],
  "figures": ["figures/exp003_convergence.pdf"]
}
```

**为什么需要日志，而不能只依靠 Git？** Git 记录文件变更；实验日志记录推理过程：为什么尝试 X、从中学到了什么，以及这些认识对下一项实验意味着什么。撰写论文时，这棵树对 Methods 部分（“我们观察到 X，因此开展了 Y”）以及如实报告失败都非常宝贵。

**选择最佳路径**：当日志呈现分支树（exp_001 → exp_002a、exp_002b、exp_003）时，应找出最能支持论文主张的路径。将未走通的分支作为消融实验或负面结果记录在附录中。

**为每次实验保存代码快照**：每次运行后复制实验脚本：
```bash
cp experiment.py results/exp_003/experiment_snapshot.py
```
这样，即使后续代码发生变化，也能精确复现实验。

---

## 第 4 阶段：结果分析

**目标**：提炼研究发现、计算统计量，并明确论文叙事主线。

### 步骤 4.1：汇总结果

编写分析脚本以完成以下工作：
1. 加载同一批次的所有结果文件
2. 计算各任务指标和汇总指标
3. 生成汇总表

```python
# Standard analysis pattern
import json, os
from pathlib import Path

results = {}
for result_file in Path("results/").rglob("result.json"):
    data = json.loads(result_file.read_text())
    strategy = result_file.parent.name
    task = result_file.parent.parent.name
    results.setdefault(strategy, {})[task] = data

# Compute aggregate metrics
for strategy, tasks in results.items():
    scores = [t["score"] for t in tasks.values()]
    print(f"{strategy}: mean={np.mean(scores):.1f}, std={np.std(scores):.1f}")
```

### 步骤 4.2：统计显著性

始终计算：
- **误差线**：标准差或标准误，并明确说明使用哪一种
- **置信区间**：为关键结果计算 95% CI
- **成对检验**：比较两种方法时使用 McNemar's test
- **效应量**：使用 Cohen's d 或 h 衡量实际意义

McNemar's test、bootstrap CI 和 Cohen's h 的完整实现，请参阅 [references/experiment-patterns.md](references/experiment-patterns.md)。

### 步骤 4.3：明确论文叙事

分析完成后，明确回答：
1. **主要发现是什么？** 用一句话概括。
2. **哪些结果出乎意料？** 意外结果往往能成就优秀论文。
3. **哪些实验失败了？** 失败的实验可能最具启发性。如实报告失败会增强论文的可信度。
4. **还需要哪些后续实验？** 现有结果往往会引出新问题。

#### 处理负面结果或无显著结果

当假设不成立或结果尚无定论时，可以采取以下几种做法：

| 情况 | 做法 | 适合投稿的会议或期刊 |
|-----------|--------|-----------|
| 假设不成立，但分析**原因**很有价值 | 围绕原因分析组织论文 | NeurIPS、ICML（前提是分析足够严谨） |
| 方法未超越基线，但**揭示了新现象** | 将贡献重新定位为理解或分析 | ICLR（重视机制理解）、研讨会论文 |
| 针对流行观点得出了严谨的负面结果 | 写成论文——研究社区需要了解这一结果 | NeurIPS Datasets & Benchmarks、TMLR、研讨会 |
| 结果尚无定论，也没有清晰主线 | 转向——开展其他实验或重构问题 | 不要勉强写一篇缺乏实质内容的论文 |

**如何撰写负面结果论文：**
- 首先说明研究社区普遍相信什么，以及检验这一观点为何重要
- 说明严谨的研究方法（必须经得起推敲——审稿人会更加严格地审视）
- 用统计证据清楚呈现无显著结果
- 分析预期结果**为何**没有出现
- 讨论该结果对领域的影响

**明确欢迎负面结果的会议、期刊或研讨会**：NeurIPS（Datasets & Benchmarks track）、TMLR、ML Reproducibility Challenge，以及主要会议的研讨会。部分研讨会还会专门征集负面结果。

### 步骤 4.4：制作图表

**图：**
- 所有绘图均使用矢量格式（PDF）：`plt.savefig('fig.pdf')`
- 使用色盲友好配色（Okabe-Ito 或 Paul Tol）
- 图注应自成一体——读者无需阅读正文也能理解图意
- 图内不设标题——由图注承担这一功能

**表：**
- 使用 `booktabs` LaTeX 宏包
- 每项指标的最优值加粗
- 标注方向符号（越高越好 / 越低越好）
- 小数精度保持一致

```latex
\usepackage{booktabs}
\begin{tabular}{lcc}
\toprule
Method & Accuracy $\uparrow$ & Latency $\downarrow$ \\
\midrule
Baseline & 85.2 & 45ms \\
\textbf{Ours} & \textbf{92.1} & 38ms \\
\bottomrule
\end{tabular}
```

### 步骤 4.5：决定继续实验还是开始写作

| 情况 | 做法 |
|-----------|--------|
| 核心主张已有支持，结果具有统计显著性 | 进入第 5 阶段（写作） |
| 结果尚无定论，需要更多数据 | 返回第 2 阶段（设计） |
| 意外发现指向新的研究方向 | 返回第 2 阶段（设计） |
| 缺少一项审稿人必然会要求的消融实验 | 完成该实验，再进入第 5 阶段 |
| 所有实验均已完成，但其中一些失败 | 记录失败，然后进入第 5 阶段 |

### 步骤 4.6：编写实验日志（连接实验与论文写作）

开始撰写论文前，应创建结构化实验日志，将实验结果衔接到论文叙述中。这是连接实验与成稿最重要的一环；如果缺少它，写作智能体只能从原始结果文件中重新梳理论文主线。

**创建 `experiment_log.md`**，结构如下：

```markdown
# Experiment Log

## Contribution (one sentence)
[The paper's main claim]

## Experiments Run

### Experiment 1: [Name]
- **Claim tested**: [Which paper claim this supports]
- **Setup**: [Model, dataset, config, number of runs]
- **Key result**: [One sentence with the number]
- **Result files**: results/exp1/final_info.json
- **Figures generated**: figures/exp1_comparison.pdf
- **Surprising findings**: [Anything unexpected]

### Experiment 2: [Name]
...

## Figures
| Filename | Description | Which section it belongs in |
|----------|-------------|---------------------------|
| figures/main_comparison.pdf | Bar chart comparing all methods on benchmark X | Results, Figure 2 |
| figures/ablation.pdf | Ablation removing components A, B, C | Results, Figure 3 |
...

## Failed Experiments (document for honesty)
- [What was tried, why it failed, what it tells us]

## Open Questions
- [Anything the results raised that the paper should address]
```

**为什么这很重要**：起草时，智能体（或受委派的子智能体）可以同时加载 `experiment_log.md` 和 LaTeX 模板，据此生成以真实结果为依据的初稿。如果缺少这座桥梁，写作智能体就必须解析原始 JSON/CSV 文件并推断论文主线，这很容易导致数值幻觉或误报。

**Git 规范**：将这份日志与其描述的实验结果一并提交。

---

## 迭代改进：策略选择

该流程中的任何产出——论文草稿、实验脚本、分析结果——都可以迭代改进。autoreason 研究以实证结果说明了各种改进策略何时有效、何时失效。可依据本节选择合适的方法。

### 快速决策表

| 你的情况 | 策略 | 原因 |
|---------------|----------|-----|
| 中等规模模型 + 受约束任务 | **Autoreason** | 最适用的场景。生成与评估能力之间的差距最大；基线方法反而会主动破坏较弱模型的输出。 |
| 中等规模模型 + 开放式任务 | **Autoreason**（增加范围约束） | 加入固定事实、结构或交付物，以限定改进空间。 |
| 前沿模型 + 受约束任务 | **Autoreason** | 即使使用前沿模型，也能在 3 项受约束任务中的 2 项获胜。 |
| 前沿模型 + 无约束任务 | **Critique-and-revise** 或 **single pass** | Autoreason 表现垫底；模型的自我评估能力已足够好。 |
| 具体的技术任务（如系统设计） | **Critique-and-revise** | 直接查找并修复问题的循环更高效。 |
| 模板填充任务（只有一种正确结构） | **Single pass** 或 **conservative** | 决策空间极小，迭代不会带来收益。 |
| 带测试用例的代码任务 | **Autoreason（代码变体）** | 修复前先结构化分析失败的*原因*；恢复率为 62%，而非 43%。 |
| 极弱模型（Llama 8B 级别） | **Single pass** | 模型能力太弱，无法生成多样化候选项；应优先提升生成质量。 |

### 生成—评估能力差距

**核心洞见**：Autoreason 的价值取决于模型生成能力与自我评估能力之间的差距。

```
Model Tier        │ Generation │ Self-Eval │ Gap    │ Autoreason Value
──────────────────┼────────────┼───────────┼────────┼─────────────────
Weak (Llama 8B)   │ Poor       │ Poor      │ Small  │ None — can't generate diverse candidates
Mid (Haiku 3.5)   │ Decent     │ Poor      │ LARGE  │ MAXIMUM — 42/42 perfect Borda
Mid (Gemini Flash)│ Decent     │ Moderate  │ Large  │ High — wins 2/3
Strong (Sonnet 4) │ Good       │ Decent    │ Medium │ Moderate — wins 3/5
Frontier (S4.6)   │ Excellent  │ Good      │ Small  │ Only with constraints
```

这种差距是结构性的，而非暂时现象。随着成本下降，今天的前沿模型会成为明天的中等规模模型。最适用的区间会移动，但不会消失。

### Autoreason 循环（摘要）

每一轮都会由全新且彼此隔离的智能体生成三个候选版本：

1. **Critic** → 找出现有版本 A 的问题（不提供修复方案）
2. **Author B** → 根据批评意见修改 A
3. **Synthesizer** → 合并 A 与 B（标签随机化）
4. **Judge Panel** → 3 名盲评 CoT judges 通过 Borda count 对 A、B、AB 排序
5. **Convergence** → A 连续 k=2 轮获胜 → 完成

**关键参数：**
- k=2 收敛（k=1 过早；k=3 成本过高，且没有质量收益）
- 始终使用 CoT judges（收敛速度提高 3 倍）
- 作者 temperature 为 0.8，评审为 0.3
- 保守的平局处理：平局时现有版本获胜
- 每个角色均由全新智能体承担，且不共享上下文

### 应用于论文草稿

使用 autoreason 改进论文时：
- **向 critic 提供 ground truth**：真实实验数据、结果 JSON 和统计输出。否则，模型会凭空编造消融实验和虚假的置信区间。
- **至少使用 3 个正常工作的 judges**：judge parser 出错不会只是增加噪声，而会彻底阻止系统达到均衡。
- **限定修改范围**：应使用“解决这些具体问题”，而不是“改进论文”。

### 失败模式

| 故障 | 检测 | 修复 |
|---------|-----------|-----|
| 不收敛（A 从未获胜） | 20 多轮中 A 的胜率低于 15% | 为任务添加范围约束 |
| 综合结果漂移 | 字数持续无限增长 | 约束结构与交付物 |
| 质量下降到 single pass 以下 | 迭代输出得分低于基线 | 切换到 single pass；模型可能太弱 |
| 过拟合（代码） | 公开测试通过率高、私有测试通过率低 | 使用结构化分析，而不只是测试反馈 |
| judges 故障 | 解析失败导致评审团少于 3 名 | 修复 parser 后再继续 |

完整提示词、Borda 评分细节、模型选择指南、范围约束设计模式和计算预算参考，请参阅 [references/autoreason-methodology.md](references/autoreason-methodology.md)。

---

## 第 5 阶段：论文起草

**目标**：撰写完整、达到发表标准的论文。

### 大型项目的上下文管理

包含 50 多个实验文件、多个结果目录和大量文献笔记的论文项目，很容易超出智能体的上下文窗口。应主动管理上下文：

**每项起草任务应加载到上下文中的内容：**

| 起草任务 | 应加载到上下文 | 不应加载 |
|---------------|------------------|-------------|
| 撰写 Introduction | `experiment_log.md`、贡献陈述、最相关的 5-10 篇论文摘要 | 原始结果 JSON、完整实验脚本、全部文献笔记 |
| 撰写 Methods | 实验配置、伪代码、架构说明 | 原始日志、其他实验的结果 |
| 撰写 Results | `experiment_log.md`、结果汇总表、图表清单 | 完整分析脚本、中间数据 |
| 撰写 Related Work | 整理后的引文笔记（步骤 1.4 的输出）、.bib 文件 | 实验文件、原始 PDF |
| 修改稿件 | 完整论文草稿、具体的审稿意见 | 其他所有内容 |

**原则：**
- **`experiment_log.md` 是主要的上下文桥梁**——它在不加载原始数据文件的情况下，汇总了写作所需的一切信息（见步骤 4.6）
- **委派任务时，每次只加载一个章节所需的上下文**。负责起草 Methods 的子智能体不需要文献综述笔记。
- **加载摘要，不要加载原始文件。** 对于 200 行的结果 JSON，应加载 10 行汇总表；对于 50 页的相关论文，应加载 5 句话的摘要，以及 2 行说明其相关性的笔记。
- **对于超大型项目**：创建包含预压缩摘要的 `context/` 目录：
  ```
  context/
    contribution.md          # 1 sentence
    experiment_summary.md    # Key results table (from experiment_log.md)
    literature_map.md        # Organized citation notes
    figure_inventory.md      # List of figures with descriptions
  ```

### 叙事原则

**最关键的洞见**：论文不是一堆实验的集合，而是一个由证据支撑、围绕明确贡献展开的故事。

每篇成功的机器学习论文都围绕 Neel Nanda 所说的“叙事”（narrative）展开：一个简洁、严谨、以证据为基础的技术故事，并给出读者真正关心的结论。

**三大支柱（必须在引言结束前阐述得一清二楚）：**

| 支柱 | 说明 | 测试 |
|--------|-------------|------|
| **做了什么（The What）** | 1–3 项具体的新颖主张 | 能否用一句话概括？ |
| **为何成立（The Why）** | 严谨的实证证据 | 实验能否将你的假设与其他解释区分开？ |
| **有何意义（The So What）** | 读者为何应当关心 | 是否关联到社区公认的重要问题？ |

**如果你还无法用一句话说清贡献，就说明论文尚未成形。**

### 本指南背后的来源

本技能综合了多位在顶级会议和期刊上拥有丰富发表经验的研究者的写作理念。其中的写作理念层最初由 [Orchestra Research](https://github.com/orchestra-research) 整理为 `ml-paper-writing` 技能。

| 来源 | 关键贡献 | 链接 |
|--------|-----------------|------|
| **Neel Nanda** (Google DeepMind) | 叙事原则与 What/Why/So What 框架 | [如何撰写 ML 论文](https://www.alignmentforum.org/posts/eJGptPbbFPZGLpjsp/highly-opinionated-advice-on-how-to-write-ml-papers) |
| **Sebastian Farquhar** (DeepMind) | 五句式摘要公式 | [如何撰写 ML 论文](https://sebastianfarquhar.com/on-research/2024/11/04/how_to_write_ml_papers/) |
| **Gopen & Swan** | 读者期望的 7 条原则 | [科学写作的科学](https://cseweb.ucsd.edu/~swanson/papers/science-of-writing.pdf) |
| **Zachary Lipton** | 词语选择、消除模糊限定语 | [科学写作启发式](https://www.approximatelycorrect.com/2018/01/29/heuristics-technical-scientific-writing-machine-learning-perspective/) |
| **Jacob Steinhardt** (加州大学伯克利分校) | 精确、一致的术语 | [写作技巧](https://bounded-regret.ghost.io/) |
| **Ethan Perez** (Anthropic) | 微观层面的清晰表达技巧 | [简易论文写作技巧](https://ethanperez.net/easy-paper-writing-tips/) |
| **Andrej Karpathy** | 聚焦单一贡献 | 多场讲座 |

**如需深入了解上述任一内容，请参阅：**
- [references/writing-guide.md](references/writing-guide.md) — 含示例的完整说明
- [references/sources.md](references/sources.md) — 完整参考书目

### 时间分配

以下四项应投入大致**相同的时间**：
1. 摘要
2. 引言
3. 图表
4. 其余所有内容的总和

**为什么？** 大多数审稿人在读到方法部分之前就已形成初步判断。读者通常按以下顺序接触论文：标题 → 摘要 → 引言 → 图表 → 也许才会阅读其余部分。

### 写作工作流

```
Paper Writing Checklist:
- [ ] Step 1: Define the one-sentence contribution
- [ ] Step 2: Draft Figure 1 (core idea or most compelling result)
- [ ] Step 3: Draft abstract (5-sentence formula)
- [ ] Step 4: Draft introduction (1-1.5 pages max)
- [ ] Step 5: Draft methods
- [ ] Step 6: Draft experiments & results
- [ ] Step 7: Draft related work
- [ ] Step 8: Draft conclusion & discussion
- [ ] Step 9: Draft limitations (REQUIRED by all venues)
- [ ] Step 10: Plan appendix (proofs, extra experiments, details)
- [ ] Step 11: Complete paper checklist
- [ ] Step 12: Final review
```

### 两轮精修模式

使用 AI 智能体起草时，采用**两轮精修（two-pass）**方法；这一做法已在 SakanaAI 的 AI-Scientist 流程中证明有效：

**第一轮——每完成一节，立即精修：**
每一节先写出完整草稿，再立即在同一上下文中精修。趁该节内容仍然清晰地留在上下文中，可以及时发现清晰度、行文衔接和完整性等局部问题。

**第二轮——结合全文上下文进行全局精修：**
所有章节起草完成后，结合全文重新审视每一节。这样可以发现跨章节问题，例如内容重复、术语不一致、叙事不连贯，以及某一节作出承诺但另一节没有兑现的缺口。

```
Second-pass refinement prompt (per section):
"Review the [SECTION] in the context of the complete paper.
- Does it fit with the rest of the paper? Are there redundancies with other sections?
- Is terminology consistent with Introduction and Methods?
- Can anything be cut without weakening the message?
- Does the narrative flow from the previous section and into the next?
Make minimal, targeted edits. Do not rewrite from scratch."
```

### LaTeX 错误检查表

将此检查表附在每个精修提示之后。以下是 LLM 编写 LaTeX 时最常见的错误：

```
LaTeX Quality Checklist (verify after every edit):
- [ ] No unenclosed math symbols ($ signs balanced)
- [ ] Only reference figures/tables that exist (\ref matches \label)
- [ ] No fabricated citations (\cite matches entries in .bib)
- [ ] Every \begin{env} has matching \end{env} (especially figure, table, algorithm)
- [ ] No HTML contamination (</end{figure}> instead of \end{figure})
- [ ] No unescaped underscores outside math mode (use \_ in text)
- [ ] No duplicate \label definitions
- [ ] No duplicate section headers
- [ ] Numbers in text match actual experimental results
- [ ] All figures have captions and labels
- [ ] No overly long lines that cause overfull hbox warnings
```

### 步骤 5.0：标题

标题是论文中阅读量最高的单个元素，也决定了读者是否会点开摘要继续阅读。

**优秀标题**：
- 直接说明贡献或发现："Autoreason: When Iterative LLM Refinement Works and Why It Fails"
- 突出意外发现："Scaling Data-Constrained Language Models"（标题暗示这件事确实可行）
- 给出方法名及其作用："DPO: Direct Preference Optimization of Language Models"

**不佳标题**：
- 过于宽泛："An Approach to Improving Language Model Outputs"
- 过长：超过约 15 个单词
- 只有行话："Asymptotic Convergence of Iterative Stochastic Policy Refinement"（目标读者究竟是谁？）

**规则**：
- 若有方法名称，应将其写入标题（便于引用）
- 加入审稿人可能搜索的 1–2 个关键词
- 避免使用冒号，除非两半都有意义
- 测试：审稿人仅从标题就能知道领域和贡献吗？

### 步骤 5.1：摘要（5 句公式）

来自 Sebastian Farquhar（DeepMind）：

```
1. What you achieved: "We introduce...", "We prove...", "We demonstrate..."
2. Why this is hard and important
3. How you do it (with specialist keywords for discoverability)
4. What evidence you have
5. Your most remarkable number/result
```

**删除**诸如“大型语言模型取得了显著成功……”之类的套话式开头。

### 步骤 5.2：图 1

图 1 是大多数读者继摘要之后第二个会查看的内容。应在撰写引言前先起草图 1，因为这会迫使你明确论文的核心思想。

| 图 1 类型 | 何时使用 | 示例 |
|---------------|-------------|---------|
| **方法示意图** | 新架构或处理流程 | 用 TikZ 流程图展示系统 |
| **结果预览** | 一个有说服力的结果足以讲清整个故事 | 条形图：清晰展示“Ours vs baselines”的差距 |
| **问题示意图** | 问题本身不够直观 | 用前后对比展示你所解决的失效模式 |
| **概念图** | 抽象贡献需要视觉化说明 | 展示方法属性的 2×2 矩阵 |

**规则**：即使不阅读正文，读者也必须能看懂图 1；仅凭图注就应理解核心思想。颜色应服务于信息表达，而不是单纯装饰。

### 步骤 5.3：引言（最多 1–1.5 页）

必须包括：
- 清晰的问题陈述
- 简要方法概述
- 用 2–4 个要点列出贡献（双栏排版下每点最多 1–2 行）
- 方法应从第 2-3 页开始

### 步骤 5.4：方法

提供足够信息，使他人能够复现实现：
- 概念概要或伪代码
- 列出所有超参数
- 提供足以复现的架构细节
- 正文呈现最终设计决策；消融实验放在实验部分

### 步骤 5.5：实验与结果

对于每个实验，明确说明：
- **该实验支持哪项主张**
- 它如何与主要贡献联系起来
- 应观察什么，例如：“蓝线显示 X，从而证明 Y”

要求：
- 误差线及其计算方法（标准差还是标准误）
- 超参数搜索范围
- 计算基础设施（GPU 类型，总小时数）
- 随机种子的设置方法

### 步骤 5.6：相关工作

按方法类别组织，而不是逐篇论文罗列。引用应充分，因为审稿人很可能正是相关工作的作者。

### 步骤 5.7：局限性（必需）

所有主要会议都要求这一部分。坦诚说明局限反而有益：
- 审稿指南通常明确要求，不应因作者坦诚承认局限而扣分
- 主动指出弱点，预先回应潜在批评
- 解释这些局限为何不会削弱核心主张

### 步骤 5.8：结论与讨论

**结论**（必需，0.5–1 页）：
- 用一句话重述贡献（与摘要的措辞不同）
- 总结主要发现（2-3 句话，不是列表）
- 影响：这对该领域意味着什么？
- 未来工作：列出 2–3 个具体的后续步骤（不要含糊地写“我们将 X 留作未来工作”）

**讨论**（可选，有时与结论合并）：
- 超越直接结果的更广泛影响
- 与其他子领域的联系
- 诚实评估该方法何时有效、何时无效
- 实际部署注意事项

**不要**在结论中引入新的结果或主张。

### 步骤 5.9：附录策略

在所有主要投稿会议和期刊中，附录均不计入正文篇幅限制，而且附录对可复现性至关重要。建议结构如下：

| 附录部分 | 这里的内容 |
|-----------------|---------------|
| **证明与推导** | 正文放不下的完整证明。正文可陈述定理，并注明“证明见附录 A”。 |
| **补充实验** | 消融实验、缩放曲线、按数据集细分的结果、超参数敏感性分析 |
| **实现细节** | 完整的超参数表、训练细节、硬件规格、随机种子 |
| **数据集文档** | 数据收集过程、注释指南、许可、预处理 |
| **提示词与模板** | 实际使用的完整提示词（适用于基于 LLM 的方法）、评估模板 |
| **人工评估** | 标注界面截图、提供给标注员的说明、IRB 相关细节 |
| **补充图表** | 按任务细分的结果、轨迹可视化、失败案例 |

**规则**：
- 正文必须自成一体——审稿人没有义务阅读附录
- 切勿仅将关键证据放在附录中
- 交叉引用：“表 5（附录 B）中的完整结果”而不仅仅是“参见附录”
- 使用 `\appendix` 命令，然后使用 `\section{A: Proofs}` 等。

### 页面预算管理

当超过页数限制时：

| 削减策略 | 节省 | 风险 |
|-------------|-------|------|
| 将证明移至附录 | 0.5–2 页 | 低——标准做法 |
| 压缩相关工作 | 0.5-1 页 | 中等 — 可能会错过关键引用 |
| 将表格与子图合并 | 0.25-0.5 页 | 低 — 通常提高可读性 |
| 谨慎使用 `\vspace{-Xpt}` | 0.1–0.3 页 | 不易察觉时风险低，明显挤压版面时风险高 |
| 删除定性示例 | 0.5–1 页 | 中——审稿人通常重视示例 |
| 缩小图表尺寸 | 0.25–0.5 页 | 高——图表必须保持清晰可读 |

**不要**：缩小字号、更改页边距、删除必需章节（局限性、更广泛影响），或在正文中使用 `\small`/`\footnotesize`。

### 步骤 5.10：伦理与更广泛影响声明

如今，大多数会议都要求或强烈建议提交伦理/更广泛影响声明。这不是可随意套用的模板文字；审稿人会认真阅读，伦理问题还可能触发直接拒稿。

**应包含的内容：**

| 组成部分 | 内容 | 要求方 |
|-----------|---------|-------------|
| **积极的社会影响** | 你的工作如何造福社会 | NeurIPS、ICML |
| **潜在负面影响** | 滥用风险、双重用途风险、失效模式 | NeurIPS、ICML |
| **公平性与偏差** | 你的方法或数据是否存在已知偏差？ | 所有会议（隐含要求） |
| **环境影响** | 估算大规模训练的碳足迹 | ICML；NeurIPS 也日益重视 |
| **隐私** | 研究是否使用个人数据，或使处理个人数据成为可能？ | ACL、NeurIPS |
| **LLM 使用披露** | 写作或实验中是否使用了 AI？ | ICLR（强制）、ACL |

**撰写声明：**

```latex
\section*{Broader Impact Statement}
% NeurIPS/ICML: after conclusion, does not count toward page limit

% 1. Positive applications (1-2 sentences)
This work enables [specific application] which may benefit [specific group].

% 2. Risks and mitigations (1-3 sentences, be specific)
[Method/model] could potentially be misused for [specific risk]. We mitigate
this by [specific mitigation, e.g., releasing only model weights above size X,
including safety filters, documenting failure modes].

% 3. Limitations of impact claims (1 sentence)
Our evaluation is limited to [specific domain]; broader deployment would
require [specific additional work].
```

**常见错误：**
- 写“我们预计不会产生任何负面影响”（几乎从来不真实，审稿人也不会信任这种说法）
- 表述含糊：只说“可能被滥用”，却不说明具体方式
- 在大规模研究中忽略计算成本
- 在要求披露的会议中忘记说明 LLM 的使用情况

**计算碳足迹**（适用于训练计算量较大的论文）：
```python
# Estimate using ML CO2 Impact tool methodology
gpu_hours = 1000  # total GPU hours
gpu_tdp_watts = 400  # e.g., A100 = 400W
pue = 1.1  # Power Usage Effectiveness (data center overhead)
carbon_intensity = 0.429  # kg CO2/kWh (US average; varies by region)

energy_kwh = (gpu_hours * gpu_tdp_watts * pue) / 1000
carbon_kg = energy_kwh * carbon_intensity
print(f"Energy: {energy_kwh:.0f} kWh, Carbon: {carbon_kg:.0f} kg CO2eq")
```

### 步骤 5.11：数据表（Datasheets）与模型卡（Model Cards，适用时）

如果论文引入了**新数据集**或**发布了模型**，请提供结构化文档。审稿人对此的期待越来越高，NeurIPS Datasets & Benchmarks 赛道更是明确要求提供。

**Datasheets for Datasets**（Gebru 等，2021）——应放入附录：

```
Dataset Documentation (Appendix):
- Motivation: Why was this dataset created? What task does it support?
- Composition: What are the instances? How many? What data types?
- Collection: How was data collected? What was the source?
- Preprocessing: What cleaning/filtering was applied?
- Distribution: How is the dataset distributed? Under what license?
- Maintenance: Who maintains it? How to report issues?
- Ethical considerations: Contains personal data? Consent obtained?
  Potential for harm? Known biases?
```

**Model Cards**（Mitchell 等，2019）——发布模型时应放入附录：

```
Model Card (Appendix):
- Model details: Architecture, training data, training procedure
- Intended use: Primary use cases, out-of-scope uses
- Metrics: Evaluation metrics and results on benchmarks
- Ethical considerations: Known biases, fairness evaluations
- Limitations: Known failure modes, domains where model underperforms
```

### 写作风格

**句子级清晰度（Gopen & Swan 的 7 条原则）：**

| 原则 | 规则 |
|-----------|------|
| 主语与谓语邻近 | 尽量让主语和谓语靠近 |
| 重音位置 | 将需要强调的信息放在句末 |
| 主题位置 | 先交代上下文，再给出新信息 |
| 旧信息在前、新信息在后 | 熟悉信息 → 陌生信息 |
| 一个单元，一个功能 | 每个段落只表达一个要点 |
| 用动词表达动作 | 使用动词，避免名词化 |
| 上下文先于新内容 | 先铺垫背景，再呈现新内容 |

**词语选择（Lipton、Steinhardt）：**
- 表述要具体：用“准确率”，不要笼统地写“性能”
- 消除不必要的模糊限定：除非确实存在不确定性，否则删去“可能”
- 始终使用一致的术语
- 避免显得只是增量拼接的词汇：用“开发”，而不是“组合”

**含示例的完整写作指南**：参见 [references/writing-guide.md](references/writing-guide.md)

### 使用 LaTeX 模板

**务必先复制整个模板目录，再在副本中写作。**

```
Template Setup Checklist:
- [ ] Step 1: Copy entire template directory to new project
- [ ] Step 2: Verify template compiles as-is (before any changes)
- [ ] Step 3: Read the template's example content to understand structure
- [ ] Step 4: Replace example content section by section
- [ ] Step 5: Use template macros (check preamble for \newcommand definitions)
- [ ] Step 6: Clean up template artifacts only at the end
```

**步骤 1：复制完整模板**

```bash
cp -r templates/neurips2025/ ~/papers/my-paper/
cd ~/papers/my-paper/
ls -la  # Should see: main.tex, neurips.sty, Makefile, etc.
```

复制整个目录，而不是只复制 .tex 文件。模板还包含样式文件（.sty）、参考文献样式（.bst）、示例内容和 Makefile。

**第 2 步：首先验证模板是否编译**

在进行任何修改之前：
```bash
latexmk -pdf main.tex
# Or manual: pdflatex main.tex && bibtex main && pdflatex main.tex && pdflatex main.tex
```

如果未经修改的模板都无法编译，应先解决这一问题（通常是缺少 TeX 软件包，可通过 `tlmgr install <package>` 安装）。

**步骤 3：保留模板内容作为参考**

不要立即删除示例内容。将其注释掉并用作格式参考：
```latex
% Template example (keep for reference):
% \begin{figure}[t]
%   \centering
%   \includegraphics[width=0.8\linewidth]{example-image}
%   \caption{Template shows caption style}
% \end{figure}

% Your actual figure:
\begin{figure}[t]
  \centering
  \includegraphics[width=0.8\linewidth]{your-figure.pdf}
  \caption{Your caption following the same style.}
\end{figure}
```

**步骤 4：逐节替换内容**

按以下顺序系统推进：标题/作者 → 摘要 → 引言 → 方法 → 实验 → 相关工作 → 结论 → 参考文献 → 附录。完成每一节后都进行编译。

**步骤 5：使用模板宏**

```latex
\newcommand{\method}{YourMethodName}  % Consistent method naming
\newcommand{\eg}{e.g.,\xspace}        % Proper abbreviations
\newcommand{\ie}{i.e.,\xspace}
```

### 模板陷阱

| 陷阱 | 问题 | 解决方案 |
|---------|---------|----------|
| 只复制 `.tex` 文件 | 缺少 `.sty`，无法编译 | 复制整个目录 |
| 修改 `.sty` 文件 | 破坏会议规定的格式 | 永远不要编辑样式文件 |
| 随意添加软件包 | 产生冲突并破坏模板 | 仅在确有必要时添加 |
| 过早删除模板示例内容 | 失去格式参考 | 完成前将其保留为注释 |
| 编译不够频繁 | 错误不断累积 | 每完成一节就编译 |
| 图表使用光栅 PNG | 论文中显示模糊 | 始终通过 `savefig('fig.pdf')` 使用矢量 PDF |

### 快速模板参考

| 会议 | 主文件 | 样式文件 | 页数限制 |
|------------|-----------|------------|------------|
| NeurIPS 2025 | `main.tex` | `neurips.sty` | 9 页 |
| ICML 2026 | `example_paper.tex` | `icml2026.sty` | 8页 |
| ICLR 2026 | `iclr2026_conference.tex` | `iclr2026_conference.sty` | 9 页 |
| ACL 2025 | `acl_latex.tex` | `acl.sty` | 8页（长） |
| AAAI 2026 | `aaai2026-unified-template.tex` | `aaai2026.sty` | 7 页 |
| COLM 2025 | `colm2025_conference.tex` | `colm2025_conference.sty` | 9 页 |

**通用要求**：双盲评审；参考文献不计入页数；附录不限篇幅；必须使用 LaTeX。

模板位于 `templates/` 目录中。请参阅 [templates/README.md](templates/README.md) 了解编译设置（VS Code、CLI、Overleaf、其他 IDE）。

### 表格与图表

**表格**——使用 `booktabs` 获得专业排版效果：

```latex
\usepackage{booktabs}
\begin{tabular}{lcc}
\toprule
Method & Accuracy $\uparrow$ & Latency $\downarrow$ \\
\midrule
Baseline & 85.2 & 45ms \\
\textbf{Ours} & \textbf{92.1} & 38ms \\
\bottomrule
\end{tabular}
```

规则：
- 每项指标的最佳值使用粗体
- 加入方向符号（$\uparrow$ 表示越高越好，$\downarrow$ 表示越低越好）
- 数值列右对齐
- 一致的小数精度

**图表**：
- 所有绘图和示意图都使用**矢量图形**（PDF、EPS）——`plt.savefig('fig.pdf')`
- **光栅图**（PNG，600 DPI）仅用于照片
- 使用**色觉缺陷友好配色**（Okabe-Ito 或 Paul Tol）
- 检查**灰度可读性**（约 8% 的男性存在色觉缺陷）
- **图内不要放标题**——标题功能由图注承担
- **图注应自包含**——读者不看正文也能理解

### 会议重新提交

如需在不同会议之间转换投稿版本，请参阅第 7 阶段（投稿准备），其中包含完整的转换流程、页数变化表和拒稿后的处理建议。

### 专业 LaTeX 导言区

将以下软件包加入论文，可提升专业排版质量。它们与所有主流会议的样式文件兼容：

```latex
% --- Professional Packages (add after conference style file) ---

% Typography
\usepackage{microtype}              % Microtypographic improvements (protrusion, expansion)
                                     % Makes text noticeably more polished — always include

% Tables
\usepackage{booktabs}               % Professional table rules (\toprule, \midrule, \bottomrule)
\usepackage{siunitx}                % Consistent number formatting, decimal alignment
                                     % Usage: \num{12345} → 12,345; \SI{3.5}{GHz} → 3.5 GHz
                                     % Table alignment: S column type for decimal-aligned numbers

% Figures
\usepackage{graphicx}               % Include graphics (\includegraphics)
\usepackage{subcaption}             % Subfigures with (a), (b), (c) labels
                                     % Usage: \begin{subfigure}{0.48\textwidth} ... \end{subfigure}

% Diagrams and Algorithms
\usepackage{tikz}                   % Programmable vector diagrams
\usetikzlibrary{arrows.meta, positioning, shapes.geometric, calc, fit, backgrounds}
\usepackage[ruled,vlined]{algorithm2e}  % Professional pseudocode
                                     % Alternative: \usepackage{algorithmicx} if template bundles it

% Cross-references
\usepackage{cleveref}               % Smart references: \cref{fig:x} → "Figure 1"
                                     % MUST be loaded AFTER hyperref
                                     % Handles: figures, tables, sections, equations, algorithms

% Math (usually included by conference .sty, but verify)
\usepackage{amsmath,amssymb}        % AMS math environments and symbols
\usepackage{mathtools}              % Extends amsmath (dcases, coloneqq, etc.)

% Colors (for figures and diagrams)
\usepackage{xcolor}                 % Color management
% Okabe-Ito colorblind-safe palette:
\definecolor{okblue}{HTML}{0072B2}
\definecolor{okorange}{HTML}{E69F00}
\definecolor{okgreen}{HTML}{009E73}
\definecolor{okred}{HTML}{D55E00}
\definecolor{okpurple}{HTML}{CC79A7}
\definecolor{okcyan}{HTML}{56B4E9}
\definecolor{okyellow}{HTML}{F0E442}
```

**说明：**
- `microtype` 是对视觉质量提升最大的单个软件包。它会在亚像素级调整字符间距，应始终启用。
- `siunitx` 通过 `S` 列类型对齐表格中的小数点，无需手动添加间距。
- `cleveref` 必须在 `hyperref` **之后**加载。大多数会议的 .sty 文件会加载 hyperref，因此应将 cleveref 放在最后。
- 检查会议模板是否已经加载其中某些软件包（尤其是 `algorithm`、`amsmath`、`graphicx`），不要重复加载。

### 使用 siunitx 对齐表格

`siunitx` 使数字较多的表格更具可读性：

```latex
\begin{tabular}{l S[table-format=2.1] S[table-format=2.1] S[table-format=2.1]}
\toprule
Method & {Accuracy $\uparrow$} & {F1 $\uparrow$} & {Latency (ms) $\downarrow$} \\
\midrule
Baseline         & 85.2  & 83.7  & 45.3 \\
Ablation (no X)  & 87.1  & 85.4  & 42.1 \\
\textbf{Ours}    & \textbf{92.1} & \textbf{90.8} & \textbf{38.7} \\
\bottomrule
\end{tabular}
```

`S` 列类型会自动按小数点对齐；用 `{}` 包住表头即可避开这种对齐处理。

### 子图

并排图形的标准模式：

```latex
\begin{figure}[t]
  \centering
  \begin{subfigure}[b]{0.48\textwidth}
    \centering
    \includegraphics[width=\textwidth]{fig_results_a.pdf}
    \caption{Results on Dataset A.}
    \label{fig:results-a}
  \end{subfigure}
  \hfill
  \begin{subfigure}[b]{0.48\textwidth}
    \centering
    \includegraphics[width=\textwidth]{fig_results_b.pdf}
    \caption{Results on Dataset B.}
    \label{fig:results-b}
  \end{subfigure}
  \caption{Comparison of our method across two datasets. (a) shows the scaling
  behavior and (b) shows the ablation results. Both use 5 random seeds.}
  \label{fig:results}
\end{figure}
```

使用 `\cref{fig:results}` → “Figure 1”，使用 `\cref{fig:results-a}` → “Figure 1a”。

### 使用 algorithm2e 编写伪代码

```latex
\begin{algorithm}[t]
\caption{Iterative Refinement with Judge Panel}
\label{alg:method}
\KwIn{Task $T$, model $M$, judges $J_1 \ldots J_n$, convergence threshold $k$}
\KwOut{Final output $A^*$}
$A \gets M(T)$ \tcp*{Initial generation}
$\text{streak} \gets 0$\;
\While{$\text{streak} < k$}{
  $C \gets \text{Critic}(A, T)$ \tcp*{Identify weaknesses}
  $B \gets M(T, C)$ \tcp*{Revised version addressing critique}
  $AB \gets \text{Synthesize}(A, B)$ \tcp*{Merge best elements}
  \ForEach{judge $J_i$}{
    $\text{rank}_i \gets J_i(\text{shuffle}(A, B, AB))$ \tcp*{Blind ranking}
  }
  $\text{winner} \gets \text{BordaCount}(\text{ranks})$\;
  \eIf{$\text{winner} = A$}{
    $\text{streak} \gets \text{streak} + 1$\;
  }{
    $A \gets \text{winner}$; $\text{streak} \gets 0$\;
  }
}
\Return{$A$}\;
\end{algorithm}
```

### TikZ 图示模式

TikZ 是 ML 论文绘制方法示意图的标准工具。常见模式如下：

**流水线/流程图**（ML 论文中最常见）：

```latex
\begin{figure}[t]
\centering
\begin{tikzpicture}[
  node distance=1.8cm,
  box/.style={rectangle, draw, rounded corners, minimum height=1cm, 
              minimum width=2cm, align=center, font=\small},
  arrow/.style={-{Stealth[length=3mm]}, thick},
]
  \node[box, fill=okcyan!20] (input) {Input\\$x$};
  \node[box, fill=okblue!20, right of=input] (encoder) {Encoder\\$f_\theta$};
  \node[box, fill=okgreen!20, right of=encoder] (latent) {Latent\\$z$};
  \node[box, fill=okorange!20, right of=latent] (decoder) {Decoder\\$g_\phi$};
  \node[box, fill=okred!20, right of=decoder] (output) {Output\\$\hat{x}$};
  
  \draw[arrow] (input) -- (encoder);
  \draw[arrow] (encoder) -- (latent);
  \draw[arrow] (latent) -- (decoder);
  \draw[arrow] (decoder) -- (output);
\end{tikzpicture}
\caption{Architecture overview. The encoder maps input $x$ to latent 
representation $z$, which the decoder reconstructs.}
\label{fig:architecture}
\end{figure}
```

**对比/矩阵图**（用于展示方法变体）：

```latex
\begin{tikzpicture}[
  cell/.style={rectangle, draw, minimum width=2.5cm, minimum height=1cm, 
               align=center, font=\small},
  header/.style={cell, fill=gray!20, font=\small\bfseries},
]
  % Headers
  \node[header] at (0, 0) {Method};
  \node[header] at (3, 0) {Converges?};
  \node[header] at (6, 0) {Quality?};
  % Rows
  \node[cell] at (0, -1) {Single Pass};
  \node[cell, fill=okgreen!15] at (3, -1) {N/A};
  \node[cell, fill=okorange!15] at (6, -1) {Baseline};
  \node[cell] at (0, -2) {Critique+Revise};
  \node[cell, fill=okred!15] at (3, -2) {No};
  \node[cell, fill=okred!15] at (6, -2) {Degrades};
  \node[cell] at (0, -3) {Ours};
  \node[cell, fill=okgreen!15] at (3, -3) {Yes ($k$=2)};
  \node[cell, fill=okgreen!15] at (6, -3) {Improves};
\end{tikzpicture}
```

**迭代循环图**（适用于带反馈机制的方法）：

```latex
\begin{tikzpicture}[
  node distance=2cm,
  box/.style={rectangle, draw, rounded corners, minimum height=0.8cm, 
              minimum width=1.8cm, align=center, font=\small},
  arrow/.style={-{Stealth[length=3mm]}, thick},
  label/.style={font=\scriptsize, midway, above},
]
  \node[box, fill=okblue!20] (gen) {Generator};
  \node[box, fill=okred!20, right=2.5cm of gen] (critic) {Critic};
  \node[box, fill=okgreen!20, below=1.5cm of $(gen)!0.5!(critic)$] (judge) {Judge Panel};
  
  \draw[arrow] (gen) -- node[label] {output $A$} (critic);
  \draw[arrow] (critic) -- node[label, right] {critique $C$} (judge);
  \draw[arrow] (judge) -| node[label, left, pos=0.3] {winner} (gen);
\end{tikzpicture}
```

### 使用 latexdiff 跟踪修订

latexdiff 对 rebuttal 至关重要，它可以生成带修订标记的 PDF，直观显示不同版本之间的变化：

```bash
# Install
# macOS: brew install latexdiff (or comes with TeX Live)
# Linux: sudo apt install latexdiff

# Generate diff
latexdiff paper_v1.tex paper_v2.tex > paper_diff.tex
pdflatex paper_diff.tex

# For multi-file projects (with \input{} or \include{})
latexdiff --flatten paper_v1.tex paper_v2.tex > paper_diff.tex
```

生成的 PDF 会用红色删除线标出删除内容、用蓝色标出新增内容，这是 rebuttal 补充材料的标准格式。

### 将 SciencePlots 用于 matplotlib

安装后，可用它绘制达到论文发表质量的图表：

```bash
pip install SciencePlots
```

```python
import matplotlib.pyplot as plt
import scienceplots  # registers styles

# Use science style (IEEE-like, clean)
with plt.style.context(['science', 'no-latex']):
    fig, ax = plt.subplots(figsize=(3.5, 2.5))  # Single-column width
    ax.plot(x, y, label='Ours', color='#0072B2')
    ax.plot(x, y2, label='Baseline', color='#D55E00', linestyle='--')
    ax.set_xlabel('Training Steps')
    ax.set_ylabel('Accuracy')
    ax.legend()
    fig.savefig('paper/fig_results.pdf', bbox_inches='tight')

# Available styles: 'science', 'ieee', 'nature', 'science+ieee'
# Add 'no-latex' if LaTeX is not installed on the machine generating plots
```

**标准图表尺寸**（双栏格式）：
- 单栏：`figsize=(3.5, 2.5)`——适合单栏宽度
- 双栏：`figsize=(7.0, 3.0)`——横跨两栏
- 方形：`figsize=(3.5, 3.5)`——适用于热力图、混淆矩阵

---

## 第 6 阶段：自审与修订

**目标**：在投稿前模拟评审流程，尽早发现薄弱环节。

### 步骤 6.1：模拟评审（集成模式）

从多个视角生成评审意见。自动化研究流程（尤其是 SakanaAI 的 AI-Scientist）带来的一项关键经验是：**由多位审稿人分别评审，再由元审稿人汇总，其反馈尺度会比单轮评审一致、可靠得多。**

**步骤 1：生成 N 份相互独立的评审意见**（N=3–5）

使用不同模型或不同温度设置。每位审稿人只能看到论文，不能看到其他评审意见。**默认采用偏负面的评审倾向，宁可多指出潜在问题**——已有大量研究表明，LLM 在评估时存在明显的正向偏差。

```
You are an expert reviewer for [VENUE]. You are critical and thorough.
If a paper has weaknesses or you are unsure about a claim, flag it clearly
and reflect that in your scores. Do not give the benefit of the doubt.

Review this paper according to the official reviewer guidelines. Evaluate:

1. Soundness (are claims well-supported? are baselines fair and strong?)
2. Clarity (is the paper well-written? could an expert reproduce it?)
3. Significance (does this matter to the community?)
4. Originality (new insights, not just incremental combination?)

Provide your review as structured JSON:
{
  "summary": "2-3 sentence summary",
  "strengths": ["strength 1", "strength 2", ...],
  "weaknesses": ["weakness 1 (most critical)", "weakness 2", ...],
  "questions": ["question for authors 1", ...],
  "missing_references": ["paper that should be cited", ...],
  "soundness": 1-4,
  "presentation": 1-4,
  "contribution": 1-4,
  "overall": 1-10,
  "confidence": 1-5
}
```

**步骤 2：元评审（Area Chair 汇总）**

将全部 N 份评审意见交给元审稿人：

```
You are an Area Chair at [VENUE]. You have received [N] independent reviews
of a paper. Your job is to:

1. Identify consensus strengths and weaknesses across reviewers
2. Resolve disagreements by examining the paper directly
3. Produce a meta-review that represents the aggregate judgment
4. Use AVERAGED numerical scores across all reviews

Be conservative: if reviewers disagree on whether a weakness is serious,
treat it as serious until the authors address it.

Reviews:
[review_1]
[review_2]
...
```

**步骤 3：反思循环**（可选，2–3 轮）

每位审稿人看到元评审后，可以继续修正自己的评审意见。设置提前终止标记：如果审稿人回复“I am done”（无需修改），则停止迭代。

**评审模型的选择**：评审应使用当前可用的最强模型，即使论文是用成本较低的模型撰写的。评审模型应独立于写作模型来选择。

**少样本校准**：如条件允许，可加入目标会议已发表的 1–2 篇真实评审意见作为示例。这能显著改善评分校准。示例评审见 [references/reviewer-guidelines.md](references/reviewer-guidelines.md)。

### 步骤 6.1b：视觉审查（VLM）

纯文本审查会漏掉一整类问题，例如图表质量、版面问题和视觉一致性。如果可以使用具备视觉能力的模型，请对编译后的 PDF 单独进行一次**视觉审查**：

```
You are reviewing the visual presentation of this research paper PDF.
Check for:
1. Figure quality: Are plots readable? Labels legible? Colors distinguishable?
2. Figure-caption alignment: Does each caption accurately describe its figure?
3. Layout issues: Orphaned section headers, awkward page breaks, figures far from their references
4. Table formatting: Aligned columns, consistent decimal precision, bold for best results
5. Visual consistency: Same color scheme across all figures, consistent font sizes
6. Grayscale readability: Would the figures be understandable if printed in B&W?

For each issue, specify the page number and exact location.
```

这能发现文本审查无法发现的问题，例如坐标轴标签难以辨认、图与首次引用它的位置相隔 3 页、图 2 与图 5 的配色不一致，或表格明显超出栏宽。

### 步骤 6.1c：论断核验

完成模拟评审后，再单独进行一次核验，以发现审稿人可能遗漏的事实性错误：

```
Claim Verification Protocol:
1. Extract every factual claim from the paper (numbers, comparisons, trends)
2. For each claim, trace it to the specific experiment/result that supports it
3. Verify the number in the paper matches the actual result file
4. Flag any claim without a traceable source as [VERIFY]
```

对于 Agent 工作流：将核验委托给一个**全新的子 Agent**，且只向其提供论文正文和原始结果文件。全新上下文有助于避免确认偏误——核验者不会“记得”结果原本应该是什么。

### 步骤 6.2：确定反馈优先级

收集评审意见后，按以下类别归类：

| 优先级 | 处理方式 |
|----------|--------|
| **Critical**（技术缺陷、缺少基线） | 必须修复。可能需要补做实验 → 返回阶段 2 |
| **High**（表述不清、缺少消融实验） | 应在本轮修订中修复 |
| **Medium**（轻微写作问题、额外实验） | 时间允许时修复 |
| **Low**（风格偏好、离题建议） | 留作后续工作参考 |

### 步骤 6.3：修订循环

针对每个 Critical/High 问题：
1. 确定受影响的具体章节
2. 起草修改方案
3. 验证修改不会破坏其他论断
4. 更新论文
5. 对照审稿人的关切再次检查

### 步骤 6.4：撰写 rebuttal

回应投稿后的真实评审意见时，撰写 rebuttal 与修改论文是两项不同的技能：

**格式**：逐点回应。针对审稿人的每一项关切：
```
> R1-W1: "The paper lacks comparison with Method X."

We thank the reviewer for this suggestion. We have added a comparison with 
Method X in Table 3 (revised). Our method outperforms X by 3.2pp on [metric] 
(p<0.05). We note that X requires 2x our compute budget.
```

**规则**：
- 回应每一项关切——漏掉任何一项都会被审稿人注意到
- 优先给出最有力的回应
- 简洁直接——审稿人需要阅读数十份 rebuttal
- 如果在 rebuttal 期间补做了实验，应加入新结果
- 即使面对依据不足的批评，也绝不要表现出防御或轻蔑态度
- 使用 `latexdiff` 生成标示修改内容的 PDF（参见“专业 LaTeX 工具”一节）
- 感谢审稿人提出具体且可操作的反馈，而不是泛泛称赞

**不要这样做**：没有证据就说“我们谨表异议”；没有解释就说“这超出了本文范围”；只回应正面评价，却忽视审稿人指出的缺点。

### 步骤 6.5：跟踪论文版本演进

在关键里程碑保存快照：
```
paper/
  paper.tex                    # Current working version
  paper_v1_first_draft.tex     # First complete draft
  paper_v2_post_review.tex     # After simulated review
  paper_v3_pre_submission.tex  # Final before submission
  paper_v4_camera_ready.tex    # Post-acceptance final
```

---

## 阶段 7：投稿准备

**目标**：完成最终检查、格式整理与投稿。

### 步骤 7.1：会议检查清单

每个会议都有强制检查清单。请认真填写——清单不完整可能导致 desk reject（编辑直接拒稿）。

以下内容见 [references/checklists.md](references/checklists.md)：
- NeurIPS 16 项论文检查清单
- ICML broader impact 与可复现性要求
- ICLR LLM 披露政策
- ACL 强制要求的 Limitations 章节
- 通用投稿前检查清单

### 步骤 7.2：匿名化检查清单

双盲评审意味着审稿人不能知道论文作者的身份。请逐项检查以下所有内容：

```
Anonymization Checklist:
- [ ] No author names or affiliations anywhere in the PDF
- [ ] No acknowledgments section (add after acceptance)
- [ ] Self-citations written in third person: "Smith et al. [1] showed..." not "We previously showed [1]..."
- [ ] No GitHub/GitLab URLs pointing to your personal repos
- [ ] Use Anonymous GitHub (https://anonymous.4open.science/) for code links
- [ ] No institutional logos or identifiers in figures
- [ ] No file metadata containing author names (check PDF properties)
- [ ] No "our previous work" or "in our earlier paper" phrasing
- [ ] Dataset names don't reveal institution (rename if needed)
- [ ] Supplementary materials don't contain identifying information
```

**常见错误**：补充代码中暴露 Git commit 信息；图片带有机构工具生成的水印；沿用旧稿时遗留了致谢；在匿名期开始前发布 arXiv 预印本。

### 步骤 7.3：格式核验

```
Pre-Submission Format Check:
- [ ] Page limit respected (excluding references and appendix)
- [ ] All figures are vector (PDF) or high-res raster (600 DPI PNG)
- [ ] All figures readable in grayscale
- [ ] All tables use booktabs
- [ ] References compile correctly (no "?" in citations)
- [ ] No overfull hboxes in critical areas
- [ ] Appendix clearly labeled and separated
- [ ] Required sections present (limitations, broader impact, etc.)
```

### 步骤 7.4：编译前验证

在尝试运行 `pdflatex` **之前**执行以下自动检查。在这里发现错误，比调试编译器输出更快。

```bash
# 1. Lint with chktex (catches common LaTeX mistakes)
# Suppress noisy warnings: -n2 (sentence end), -n24 (parens), -n13 (intersentence), -n1 (command terminated)
chktex main.tex -q -n2 -n24 -n13 -n1

# 2. Verify all citations exist in .bib
# Extract \cite{...} from .tex, check each against .bib
python3 -c "
import re
tex = open('main.tex').read()
bib = open('references.bib').read()
cites = set(re.findall(r'\\\\cite[tp]?{([^}]+)}', tex))
for cite_group in cites:
    for cite in cite_group.split(','):
        cite = cite.strip()
        if cite and cite not in bib:
            print(f'WARNING: \\\\cite{{{cite}}} not found in references.bib')
"

# 3. Verify all referenced figures exist on disk
python3 -c "
import re, os
tex = open('main.tex').read()
figs = re.findall(r'\\\\includegraphics(?:\[.*?\])?{([^}]+)}', tex)
for fig in figs:
    if not os.path.exists(fig):
        print(f'WARNING: Figure file not found: {fig}')
"

# 4. Check for duplicate \label definitions
python3 -c "
import re
from collections import Counter
tex = open('main.tex').read()
labels = re.findall(r'\\\\label{([^}]+)}', tex)
dupes = {k: v for k, v in Counter(labels).items() if v > 1}
for label, count in dupes.items():
    print(f'WARNING: Duplicate label: {label} (appears {count} times)')
"
```

继续之前先修复所有警告。对于 Agent 工作流：将 chktex 输出反馈给 Agent，并要求只做必要的最小修改。

### 步骤 7.5：最终编译

```bash
# Clean build
rm -f *.aux *.bbl *.blg *.log *.out *.pdf
latexmk -pdf main.tex

# Or manual (triple pdflatex + bibtex for cross-references)
pdflatex -interaction=nonstopmode main.tex
bibtex main
pdflatex -interaction=nonstopmode main.tex
pdflatex -interaction=nonstopmode main.tex

# Verify output exists and has content
ls -la main.pdf
```

**如果编译失败**：解析 `.log` 文件中的第一个错误。常见修复方法：
- "Undefined control sequence" → 缺少宏包，或命令名称有拼写错误
- "Missing $ inserted" → 数学符号出现在数学模式之外
- "File not found" → 图片路径错误，或缺少 .sty 文件
- "Citation undefined" → 缺少 .bib 条目，或尚未运行 bibtex

### 步骤 7.6：会议特定要求

| 会议 | 特殊要求 |
|-------|---------------------|
| **NeurIPS** | 附录中包含论文检查清单；录用后提供面向大众的摘要 |
| **ICML** | Broader Impact Statement（置于结论之后，不计入页数限制） |
| **ICLR** | 必须披露 LLM 使用情况；实行 reciprocal reviewing agreement |
| **ACL** | 强制要求 Limitations 章节和 Responsible NLP 检查清单 |
| **AAAI** | 严格遵循样式文件——不得作任何修改 |
| **COLM** | 从语言模型社区的角度阐述贡献 |

### 步骤 7.7：改投会议与格式转换

在不同会议模板之间转换时，**绝不要直接复制 LaTeX 导言区**：

```bash
# 1. Start fresh with target template
cp -r templates/icml2026/ new_submission/

# 2. Copy ONLY content sections (not preamble)
#    - Abstract text, section content, figures, tables, bib entries

# 3. Adjust for page limits
# 4. Add venue-specific required sections
# 5. Update references
```

| 从 → 到 | 页数变化 | 关键调整 |
|-----------|-------------|-----------------|
| NeurIPS → ICML | 9 → 8 | 删减 1 页，增加 Broader Impact |
| ICML → ICLR | 8 → 9 | 扩充实验，增加 LLM 披露 |
| NeurIPS → ACL | 9 → 8 | 按 NLP 论文惯例重组，增加 Limitations |
| ICLR → AAAI | 9 → 7 | 大幅删减，严格遵守样式要求 |
| 任意会议 → COLM | 页数不一 → 9 | 围绕语言模型重新定位论文 |

需要删减页数时：将证明移到附录、压缩相关工作、合并表格、使用子图。
需要扩充内容时：增加消融实验、扩展局限性讨论、加入更多基线和定性示例。

**被拒稿后**：在新版本中回应审稿人的关切，但不要加入“修改说明”章节，也不要提及上一次投稿（盲审要求）。

### 步骤 7.8：准备 camera-ready 版本（录用后）

论文录用后，准备 camera-ready 终稿：

```
Camera-Ready Checklist:
- [ ] De-anonymize: add author names, affiliations, email addresses
- [ ] Add Acknowledgments section (funding, compute grants, helpful reviewers)
- [ ] Add public code/data URL (real GitHub, not anonymous)
- [ ] Address any mandatory revisions from meta-reviewer
- [ ] Switch template to camera-ready mode (if applicable — e.g., AAAI \anon → \camera)
- [ ] Add copyright notice if required by venue
- [ ] Update any "anonymous" placeholders in text
- [ ] Verify final PDF compiles cleanly
- [ ] Check page limit for camera-ready (sometimes differs from submission)
- [ ] Upload supplementary materials (code, data, appendix) to venue portal
```

### 步骤 7.9：arXiv 与预印本策略

在 ML 领域，将论文发布到 arXiv 是惯常做法，但需要特别注意发布时间和匿名政策。

**发布时间决策树：**

| 情况 | 建议 |
|-----------|---------------|
| 投稿至双盲会议（NeurIPS、ICML、ACL） | 在投稿截止日期**之后**而非之前发布到 arXiv。提前发布在技术上可能违反匿名政策，不过不同会议的执行尺度有所不同。 |
| 投稿至 ICLR | ICLR 明确允许投稿前发布 arXiv，但投稿稿件本身仍不得出现作者姓名。 |
| 论文已发布到 arXiv，现改投新会议 | 大多数会议允许。评审期间不要更新 arXiv 版本，使改动明显对应评审意见。 |
| Workshop 论文 | 随时发布 arXiv 通常都可以——Workshop 一般不采用双盲评审。 |
| 希望确立优先权 | 若担心被抢先，可立即发布，但需接受匿名性方面的取舍。 |

**arXiv 类别选择**（ML/AI 论文）：

| 类别 | 代码 | 最适合 |
|----------|------|----------|
| Machine Learning | `cs.LG` | 通用 ML 方法 |
| Computation and Language | `cs.CL` | NLP、语言模型 |
| Artificial Intelligence | `cs.AI` | 推理、规划、Agent |
| Computer Vision | `cs.CV` | 视觉模型 |
| Information Retrieval | `cs.IR` | 搜索、推荐 |

**列出 1 个主类别和 1–2 个交叉类别。**类别越多，曝光度越高，但只应在确实相关时交叉列出。

**版本策略：**
- **v1**：初始投稿版本（与会议投稿稿一致）
- **v2**：录用后的 camera-ready 修订版（在摘要中注明“accepted at [Venue]”）
- 评审期间不要发布明显针对审稿意见修改的 v2

```bash
# Check if your paper's title is already taken on arXiv
# (before choosing a title)
pip install arxiv
python -c "
import arxiv
results = list(arxiv.Search(query='ti:\"Your Exact Title\"', max_results=5).results())
print(f'Found {len(results)} matches')
for r in results: print(f'  {r.title} ({r.published.year})')
"
```

### 步骤 7.10：研究代码打包

发布整洁、可运行的代码能显著提升引用量和审稿人的信任。请在提交 camera-ready 版本时一并整理并发布代码。

**代码仓库结构：**

```
your-method/
  README.md              # Setup, usage, reproduction instructions
  requirements.txt       # Or environment.yml for conda
  setup.py               # For pip-installable packages
  LICENSE                # MIT or Apache 2.0 recommended for research
  configs/               # Experiment configurations
  src/                   # Core method implementation
  scripts/               # Training, evaluation, analysis scripts
    train.py
    evaluate.py
    reproduce_table1.sh  # One script per main result
  data/                  # Small data or download scripts
    download_data.sh
  results/               # Expected outputs for verification
```

**研究代码 README 模板：**

```markdown
# [Paper Title]

Official implementation of "[Paper Title]" (Venue Year).

## Setup
[Exact commands to set up environment]

## Reproduction
To reproduce Table 1: `bash scripts/reproduce_table1.sh`
To reproduce Figure 2: `python scripts/make_figure2.py`

## Citation
[BibTeX entry]
```

**发布前检查清单：**
```
- [ ] Code runs from a clean clone (test on fresh machine or Docker)
- [ ] All dependencies pinned to specific versions
- [ ] No hardcoded absolute paths
- [ ] No API keys, credentials, or personal data in repo
- [ ] README covers setup, reproduction, and citation
- [ ] LICENSE file present (MIT or Apache 2.0 for max reuse)
- [ ] Results are reproducible within expected variance
- [ ] .gitignore excludes data files, checkpoints, logs
```

**投稿阶段的匿名代码**（录用前）：
```bash
# Use Anonymous GitHub for double-blind review
# https://anonymous.4open.science/
# Upload your repo → get an anonymous URL → put in paper
```

---

## 阶段 8：录用后交付物

**目标**：通过展示材料和社区传播，最大化已录用论文的影响力。

### 步骤 8.1：会议海报

大多数会议都设有海报展示环节。海报设计原则：

| 要素 | 指南 |
|---------|-----------|
| **尺寸** | 查看会议要求（通常为 24"x36"，或 A0 纵向/横向） |
| **内容** | 标题、作者、一句话贡献、方法图、2–3 项关键结果、结论 |
| **阅读动线** | 从左上到右下（Z 字形），或采用分栏布局 |
| **文字** | 标题应在 3 米外可读，正文应在 1 米外可读。不要使用完整段落，只列要点。 |
| **图表** | 以更高分辨率复用论文图表，并放大最关键的结果。 |

**工具**：LaTeX（`beamerposter` 宏包）、PowerPoint/Keynote、Figma、Canva。

**制作**：至少提前两周向印刷方下单。布质海报重量更轻，便于旅行携带。如今许多会议也支持虚拟/电子海报。

### 步骤 8.2：会议报告 / Spotlight

如果论文获选 Oral 或 Spotlight：

| 报告类型 | 时长 | 内容 |
|-----------|----------|---------|
| **Spotlight** | 5 分钟 | 问题、方法、一项关键结果。反复排练，确保正好 5 分钟。 |
| **Oral** | 15–20 分钟 | 完整讲述：问题、方法、关键结果、消融实验和局限性。 |
| **Workshop 报告** | 10–15 分钟 | 根据 Workshop 听众调整内容——可能需要补充更多背景。 |

**幻灯片设计规则：**
- 每页只讲一个观点
- 尽量减少文字——细节用口头讲述，不要全部投到屏幕上
- 为关键图表添加逐步动画，帮助听众建立理解
- 最后一页给出“takeaway”（用一句话概括贡献）
- 针对预期问题准备备用幻灯片

### 步骤 8.3：博客文章 / 社交媒体

通俗易懂的摘要能显著扩大论文影响力：

- **Twitter/X 帖子串**：5–8 条。开头先讲结果，而不是方法。附上图 1 和关键结果图。
- **博客文章**：800–1500 字。面向 ML 从业者而非审稿人撰写。省略形式化细节，强调直觉和实际意义。
- **项目页面**：用 HTML 页面展示摘要、图表、Demo、代码链接和 BibTeX。可使用 GitHub Pages。

**发布时间**：在论文出现在会议论文集或 arXiv camera-ready 版本后的 1–2 天内发布。

---

## Workshop 论文与短论文

Workshop 论文和短论文（例如 ACL short paper、Findings 论文）沿用同一套流程，但约束和评审预期不同。

### Workshop 论文

| 属性 | Workshop | 主会 |
|----------|----------|-----------------|
| **页数限制** | 通常为 4–6 页 | 7–9 页 |
| **评审标准** | 对完整性的要求较低 | 必须完整、充分 |
| **评审流程** | 通常为单盲或较轻量的评审 | 双盲、严格 |
| **看重的内容** | 有趣的想法、初步结果、立场观点 | 基线充分、实证链条完整 |
| **arXiv** | 可随时发布 | 发布时间很重要（参见 arXiv 策略） |
| **贡献门槛** | 新颖方向、有趣的负面结果、进行中的工作 | 有强证据支持的显著进展 |

**适合投稿 Workshop 的情况：**
- 处于早期阶段，希望在扩展为完整论文前获得反馈
- 负面结果不足以支撑 8 页以上的长论文
- 针对热点议题撰写立场文章或观点文章
- 复现研究或可复现性报告

### ACL 短论文与 Findings

ACL 系列会议设有不同的投稿类型：

| 类型 | 页数 | 预期内容 |
|------|-------|-----------------|
| **长论文** | 8 | 完整研究、强基线、消融实验 |
| **短论文** | 4 | 聚焦一个贡献：提出一个明确观点，并用证据充分支持 |
| **Findings** | 8 | 质量扎实、但以微小差距未进入主会的工作 |

**短论文策略**：只选择**一个**论断，并为其提供充分支持。不要试图把长论文硬压缩成 4 页，而要另写一篇重点更集中的论文。

---

<a id="paper-types-beyond-empirical-ml"></a>

## 实证 ML 以外的论文类型

以上主流程面向实证 ML 论文。其他论文类型需要不同的结构和证据标准。各类型的详细指南见 [references/paper-types.md](references/paper-types.md)。

### 理论论文

**结构**：引言 → 预备知识（定义、符号）→ 主要结果（定理）→ 证明概要 → 讨论 → 完整证明（附录）

**与实证论文的主要区别：**
- 贡献是定理、界或不可能性结果，而不是实验数值
- “方法”章节由“预备知识”和“主要结果”取代
- 证明就是证据，而不是实验（不过，能验证理论的实证结果会受到欢迎）
- 正文给出证明概要、附录给出完整证明，是标准做法
- 实验章节是可选的；若能验证理论预测，则会增强论文说服力

**证明写作原则：**
- 以形式化方式陈述定理，并明确写出全部假设
- 在形式化证明前先给出直觉解释（“关键洞见是……”）
- 证明概要应在 0.5–1 页内传达核心思路
- 使用 `\begin{proof}...\end{proof}` 环境
- 对假设编号，并在定理中引用，例如：“在假设 1–3 下，……”

### 综述 / 教程论文

**结构**：引言 → 分类体系 / 组织框架 → 详细综述 → 开放问题 → 结论

**主要区别：**
- 贡献在于组织、综合并识别开放问题，而不是提出新方法
- 在所定义的范围内必须全面（审稿人会检查是否遗漏文献）
- 需要清晰的分类体系或组织框架
- 价值来自揭示单篇论文未能建立的跨工作联系
- 最适合的会议/期刊：TMLR（survey track）、JMLR、Foundations and Trends in ML、ACM Computing Surveys

### Benchmark 论文

**结构**：引言 → 任务定义 → 数据集构建 → 基线评估 → 分析 → 预期用途与局限性

**主要区别：**
- 贡献是 benchmark 本身——它必须填补真实存在的评估空白
- 数据集文档是强制要求，而非可选项（参见步骤 5.11 的 Datasheets）
- 必须证明 benchmark 具有挑战性（基线尚未达到饱和）
- 必须证明 benchmark 确实测量了其声称要测量的内容（构念效度）
- 最适合的会议：NeurIPS Datasets & Benchmarks track、ACL（resource papers）、LREC-COLING

### 立场论文

**结构**：引言 → 背景 → 核心主张 / 论证 → 支持证据 → 反方观点 → 启示

**主要区别：**
- 贡献是一项论证，而不是一个结果
- 必须认真回应反方观点
- 证据可以来自实证、理论或逻辑分析
- 最适合的会议/期刊：ICML（position track）、Workshop、TMLR

---

## Hermes Agent 集成

本技能专为 Hermes Agent 设计，在完整研究生命周期中使用 Hermes 的工具、委托、调度和记忆能力。

### 相关技能

在不同阶段，可将本技能与其他 Hermes 技能组合使用：

| 技能 | 使用时机 | 加载方式 |
|-------|-------------|-------------|
| **arxiv** | 阶段 1（文献综述）：搜索 arXiv、生成 BibTeX、通过 Semantic Scholar 查找相关论文 | `skill_view("arxiv")` |
| **subagent-driven-development** | 阶段 5（起草）：并行撰写各章节，并进行两阶段审查（先检查规范符合性，再检查质量） | `skill_view("subagent-driven-development")` |
| **plan** | 阶段 0（设置）：执行前创建结构化计划。写入 `.hermes/plans/` | `skill_view("plan")` |
| **qmd** | 阶段 1（文献）：通过 BM25 + 向量混合搜索检索本地知识库（笔记、转录稿、文档） | 安装：`skill_manage("install", "qmd")` |
| **diagramming** | 阶段 4–5：创建基于 Excalidraw 的图表和架构图 | `skill_view("diagramming")` |
| **data-science** | 阶段 4（分析）：使用 Jupyter live kernel 进行交互式分析和可视化 | `skill_view("data-science")` |

**本技能取代 `ml-paper-writing`**——它包含 ml-paper-writing 的全部内容，并补充了完整的实验/分析流程和 autoreason 方法。

### Hermes 工具参考

| 工具 | 在本流程中的用途 |
|------|----------------------|
| **`terminal`** | 编译 LaTeX（`latexmk -pdf`）、执行 git 操作、启动实验（`nohup python run.py &`）、检查进程 |
| **`process`** | 管理后台实验：`process("start", ...)`、`process("poll", pid)`、`process("log", pid)`、`process("kill", pid)` |
| **`execute_code`** | 运行 Python，完成引用核验、统计分析和数据聚合；可通过 RPC 访问工具。 |
| **`read_file`** / **`write_file`** / **`patch`** | 编辑论文、实验脚本和结果文件。对大型 .tex 文件应使用 `patch` 进行定点修改。 |
| **`web_search`** | 发现文献：`web_search("transformer attention mechanism 2024")` |
| **`web_extract`** | 获取论文内容、核验引文：`web_extract("https://arxiv.org/abs/2303.17651")` |
| **`delegate_task`** | **并行起草章节**——为每个章节启动独立子 Agent；也可用于并发核验引用。 |
| **`todo`** | 跨会话使用的主要状态跟踪器。每次阶段转换后更新。 |
| **`memory`** | 跨会话保存关键决策：贡献定位、会议选择、审稿人反馈。 |
| **`cronjob`** | 安排实验监控、截止日期倒计时和自动 arXiv 检查。 |
| **`clarify`** | 受阻时向用户提出针对性问题（会议选择、贡献定位）。 |
| **cron `deliver:`** | 即使用户不在聊天中，也能在实验完成或草稿就绪时通知用户——把检查安排为带消息 `deliver:` 目标的 cron 作业（Agent 已不再提供 `send_message` 工具；对外发送由 cron/`hermes send` 处理）。 |

### 工具使用模式

**实验监控**（最常见）：
```
terminal("ps aux | grep <pattern>")
→ terminal("tail -30 <logfile>")
→ terminal("ls results/")
→ execute_code("analyze results JSON, compute metrics")
→ terminal("git add -A && git commit -m '<descriptive message>' && git push")
→ (final response auto-delivers "Experiment complete: <summary>"; for unattended runs, schedule via cron with a deliver: target)
```

**并行起草章节**（使用委托）：
```
delegate_task("Draft the Methods section based on these experiment scripts and configs. 
  Include: pseudocode, all hyperparameters, architectural details sufficient for 
  reproduction. Write in LaTeX using the neurips2025 template conventions.")

delegate_task("Draft the Related Work section. Use web_search and web_extract to 
  find papers. Verify every citation via Semantic Scholar. Group by methodology.")

delegate_task("Draft the Experiments section. Read all result files in results/. 
  State which claim each experiment supports. Include error bars and significance.")
```

每个 delegate 都是一个**全新的子 Agent**，彼此不共享上下文——因此必须在提示词中提供全部必要信息。随后收集并整合各自输出。

**引用核验**（使用 execute_code）：
```python
# In execute_code:
from semanticscholar import SemanticScholar
import requests

sch = SemanticScholar()
results = sch.search_paper("attention mechanism transformers", limit=5)
for paper in results:
    doi = paper.externalIds.get('DOI', 'N/A')
    if doi != 'N/A':
        bibtex = requests.get(f"https://doi.org/{doi}", 
                              headers={"Accept": "application/x-bibtex"}).text
        print(bibtex)
```

### 使用 `memory` 和 `todo` 管理状态

**`memory` 工具**——持久保存关键决策（容量有限：MEMORY.md 约 2200 个字符）：

```
memory("add", "Paper: autoreason. Venue: NeurIPS 2025 (9 pages). 
  Contribution: structured refinement works when generation-evaluation gap is wide.
  Key results: Haiku 42/42, Sonnet 3/5, S4.6 constrained 2/3.
  Status: Phase 5 — drafting Methods section.")
```

在重大决策或阶段转换后更新 memory；这些内容会跨会话保留。

**`todo` 工具**——跟踪细粒度进度：

```
todo("add", "Design constrained task experiments for Sonnet 4.6")
todo("add", "Run Haiku baseline comparison")
todo("add", "Draft Methods section")
todo("update", id=3, status="in_progress")
todo("update", id=1, status="completed")
```

**会话启动流程：**
```
1. todo("list")                           # Check current task list
2. memory("read")                         # Recall key decisions
3. terminal("git log --oneline -10")      # Check recent commits
4. terminal("ps aux | grep python")       # Check running experiments
5. terminal("ls results/ | tail -20")     # Check for new results
6. Report status to user, ask for direction
```

### 使用 `cronjob` 进行定时监控

使用 `cronjob` 工具安排定期实验检查：

```
cronjob("create", {
  "schedule": "*/30 * * * *",  # Every 30 minutes
  "prompt": "Check experiment status:
    1. ps aux | grep run_experiment
    2. tail -30 logs/experiment_haiku.log
    3. ls results/haiku_baselines/
    4. If complete: read results, compute Borda scores, 
       git add -A && git commit -m 'Add Haiku results' && git push
    5. Report: table of results, key finding, next step
    6. If nothing changed: respond with [SILENT]"
})
```

**[SILENT] 协议**：如果自上次检查以来没有任何变化，请只回复 `[SILENT]`，不多不少。这样可以抑制向用户发送通知。只有出现确实值得用户了解的变化时才报告。

**截止日期跟踪**：
```
cronjob("create", {
  "schedule": "0 9 * * *",  # Daily at 9am
  "prompt": "NeurIPS 2025 deadline: May 22. Today is {date}. 
    Days remaining: {compute}. 
    Check todo list — are we on track? 
    If <7 days: warn user about remaining tasks."
})
```

### 沟通模式

**何时通知用户**（通过直接/最终回复；无人值守运行则使用 cron `deliver:` 目标）：
- 一批实验完成（附结果表）
- 出现需要用户决策的意外发现或失败
- 草稿章节已准备好供审阅
- 截止日期临近，但仍有未完成任务

**何时不要通知：**
- 实验仍在运行，且没有新结果 → `[SILENT]`
- 例行监控无变化 → `[SILENT]`
- 不需要用户关注的中间步骤

**报告格式**——始终提供结构化数据：
```
## Experiment: <name>
Status: Complete / Running / Failed

| Task | Method A | Method B | Method C |
|------|---------|---------|---------|
| Task 1 | 85.2 | 82.1 | **89.4** |

Key finding: <one sentence>
Next step: <what happens next>
```

### 需要人工决策的节点

仅在确实受阻时，使用 `clarify` 提出针对性问题：

| 决策 | 何时询问 |
|----------|-------------|
| 目标会议 | 开始写论文前（会影响页数限制和叙事定位） |
| 贡献定位 | 存在多种合理的叙事方式时 |
| 实验优先级 | TODO 列表中的实验数量超出剩余时间所能完成的范围时 |
| 是否已可投稿 | 最终提交之前 |

**不要询问以下事项**（应主动判断、作出选择并明确标注）：
- 具体措辞、章节顺序
- 应重点突出哪些具体结果
- 引文是否完整（先用已找到的文献起草，并标注缺口）

---

## 审稿人评估标准

理解审稿人的关注点，有助于集中投入：

| 标准 | 审稿人检查什么 |
|-----------|----------------|
| **Quality** | 技术是否可靠、论断是否有充分支撑、基线是否公平 |
| **Clarity** | 写作是否清晰、专家能否复现、符号是否一致 |
| **Significance** | 对社区的影响、是否增进理解 |
| **Originality** | 是否有新洞见（不要求一定提出新方法） |

**评分（NeurIPS 6 分制）：**
- 6：Strong Accept——具有突破性，几乎无可挑剔
- 5：Accept——技术扎实，影响力高
- 4：Borderline Accept——工作扎实，但评估有限
- 3：Borderline Reject——缺点超过优点
- 2：Reject——存在技术缺陷
- 1：Strong Reject——结果已为人所知，或存在伦理问题

详细指南、常见关切和 rebuttal 策略见 [references/reviewer-guidelines.md](references/reviewer-guidelines.md)。

---

## 常见问题与解决方案

| 问题 | 解决方案 |
|-------|----------|
| 摘要过于泛泛 | 如果第一句可以放在任何 ML 论文开头，就删掉它；直接从你的具体贡献讲起。 |
| 引言超过 1.5 页 | 将背景内容移到 Related Work；把贡献要点提前。 |
| 实验没有对应明确论断 | 在每项实验前补充：“本实验检验[具体论断]是否成立……”。 |
| 审稿人认为论文难以理解 | 增加结构提示，统一术语，并让图注能够独立理解。 |
| 缺少统计显著性 | 补充误差线、运行次数、统计检验和置信区间。 |
| 实验范围不断膨胀 | 每项实验都必须对应一个具体论断；删掉无法对应的实验。 |
| 论文被拒，需要改投 | 参见阶段 7 的“改投会议”。回应审稿人的关切，但不要提及之前的评审意见。 |
| 缺少 broader impact statement | 参见步骤 5.10。大多数会议都有此要求。“没有负面影响”几乎从来都不可信。 |
| 人类评估被批评薄弱 | 参见步骤 2.5 和 [references/human-evaluation.md](references/human-evaluation.md)。报告一致性指标、标注者信息和报酬。 |
| 审稿人质疑可复现性 | 发布代码（步骤 7.9），记录所有超参数，并提供随机种子和计算资源详情。 |
| 理论论文缺乏直觉解释 | 在形式化证明前加入用通俗语言解释的证明概要。参见 [references/paper-types.md](references/paper-types.md)。 |
| 结果为负面结果或零结果 | 参见阶段 4.3 关于处理负面结果的内容。可考虑投稿 Workshop、TMLR，或将论文重新定位为分析工作。 |

---

## 参考文档

| 文档 | 内容 |
|----------|----------|
| [references/writing-guide.md](references/writing-guide.md) | Gopen & Swan 的 7 项原则、Perez 的微观技巧、Lipton 的选词建议、Steinhardt 的精确性原则、图表设计 |
| [references/citation-workflow.md](references/citation-workflow.md) | 文献引用 API、Python 代码、CitationManager 类、BibTeX 管理 |
| [references/checklists.md](references/checklists.md) | NeurIPS 16 项检查清单、ICML、ICLR、ACL 要求，以及通用投稿前检查清单 |
| [references/reviewer-guidelines.md](references/reviewer-guidelines.md) | 评估标准、评分、常见关切、rebuttal 模板 |
| [references/sources.md](references/sources.md) | 所有写作指南、会议要求和 API 的完整参考书目 |
| [references/experiment-patterns.md](references/experiment-patterns.md) | 实验设计模式、评估协议、监控和错误恢复 |
| [references/autoreason-methodology.md](references/autoreason-methodology.md) | Autoreason 循环、策略选择、模型指南、提示词、范围约束、Borda 评分 |
| [references/human-evaluation.md](references/human-evaluation.md) | 人类评估设计、标注指南、一致性指标、众包 QC、IRB 指南 |
| [references/paper-types.md](references/paper-types.md) | 理论论文（证明写作、定理结构）、综述论文、benchmark 论文、立场论文 |

### LaTeX 模板

`templates/` 中提供以下模板：**NeurIPS 2025**、**ICML 2026**、**ICLR 2026**、**ACL**、**AAAI 2026**、**COLM 2025**。

编译说明见 [templates/README.md](templates/README.md)。

### 主要外部资料

**写作理念：**
- [Neel Nanda: How to Write ML Papers](https://www.alignmentforum.org/posts/eJGptPbbFPZGLpjsp/highly-opinionated-advice-on-how-to-write-ml-papers)
- [Sebastian Farquhar: How to Write ML Papers](https://sebastianfarquhar.com/on-research/2024/11/04/how_to_write_ml_papers/)
- [Gopen & Swan: Science of Scientific Writing](https://cseweb.ucsd.edu/~swanson/papers/science-of-writing.pdf)
- [Lipton: Heuristics for Scientific Writing](https://www.approximatelycorrect.com/2018/01/29/heuristics-technical-scientific-writing-machine-learning-perspective/)
- [Perez: Easy Paper Writing Tips](https://ethanperez.net/easy-paper-writing-tips/)

**API：** [Semantic Scholar](https://api.semanticscholar.org/api-docs/) | [CrossRef](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) | [arXiv](https://info.arxiv.org/help/api/basics.html)

**会议：** [NeurIPS](https://neurips.cc/Conferences/2025/PaperInformation/StyleFiles) | [ICML](https://icml.cc/Conferences/2025/AuthorInstructions) | [ICLR](https://iclr.cc/Conferences/2026/AuthorGuide) | [ACL](https://github.com/acl-org/acl-style-files)
