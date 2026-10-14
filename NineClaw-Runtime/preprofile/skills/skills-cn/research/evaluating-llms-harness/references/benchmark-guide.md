# Benchmark 指南

lm-evaluation-harness 中全部 60 多项评测任务的完整指南，介绍它们衡量什么，以及如何解读结果。

## 概述

lm-evaluation-harness 包含 60 多项 benchmark，涵盖：
- 语言理解（MMLU、GLUE）
- 数学推理（GSM8K、MATH）
- 代码生成（HumanEval、MBPP）
- 指令遵循（IFEval、AlpacaEval）
- 长上下文理解（LongBench）
- 多语言能力（AfroBench、NorEval）
- 推理（BBH、ARC）
- 真实性（TruthfulQA）

**列出所有任务**：
```bash
lm_eval --tasks list
```

## 主要 Benchmark

### MMLU (Massive Multitask Language Understanding)

**衡量内容**：涵盖 57 个学科（STEM、人文学科、社会科学、法律）的广泛知识。

**任务变体**：
- `mmlu`：原始的 57 学科 benchmark
- `mmlu_pro`：更具挑战性的版本，问题更侧重推理
- `mmlu_prox`：多语言扩展版本

**格式**：多项选择题（4 个选项）

**示例**：
```
Question: What is the capital of France?
A. Berlin
B. Paris
C. London
D. Madrid
Answer: B
```

**命令**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks mmlu \
  --num_fewshot 5
```

**结果解读**：
- 随机猜测：25%（随机基线）
- GPT-3 (175B)：43.9%
- GPT-4：86.4%
- 人类专家：约 90%

**适用于**：评估通用知识和领域专业能力。

### GSM8K (Grade School Math 8K)

**衡量内容**：针对小学水平数学应用题的数学推理能力。

**任务变体**：
- `gsm8k`：基础任务
- `gsm8k_cot`：使用 chain-of-thought 提示
- `gsm_plus`：包含扰动的对抗性变体

**格式**：自由形式生成，提取数值答案

**示例**：
```
Question: A baker made 200 cookies. He sold 3/5 of them in the morning and 1/4 of the remaining in the afternoon. How many cookies does he have left?
Answer: 60
```

**命令**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks gsm8k \
  --num_fewshot 5
```

**结果解读**：
- 随机猜测：约 0%
- GPT-3 (175B)：17.0%
- GPT-4：92.0%
- Llama 2 70B：56.8%

**适用于**：测试多步推理和算术能力。

### HumanEval

**衡量内容**：根据 docstring 生成 Python 代码的能力（功能正确性）。

**任务变体**：
- `humaneval`：标准 benchmark
- `humaneval_instruct`：适用于指令微调模型

**格式**：代码生成，基于执行的评测

**示例**：
```python
def has_close_elements(numbers: List[float], threshold: float) -> bool:
    """ Check if in given list of numbers, are any two numbers closer to each other than
    given threshold.
    >>> has_close_elements([1.0, 2.0, 3.0], 0.5)
    False
    >>> has_close_elements([1.0, 2.8, 3.0, 4.0, 5.0, 2.0], 0.3)
    True
    """
```

**命令**：
```bash
lm_eval --model hf \
  --model_args pretrained=codellama/CodeLlama-7b-hf \
  --tasks humaneval \
  --batch_size 1
```

**结果解读**：
- 随机基线：0%
- GPT-3 (175B)：0%
- Codex：28.8%
- GPT-4：67.0%
- Code Llama 34B：53.7%

**适用于**：评估代码生成能力。

### BBH (BIG-Bench Hard)

**衡量内容**：23 项极具挑战性的推理任务；此前模型在这些任务上的表现无法超越人类。

**类别**：
- 逻辑推理
- 数学应用题
- 社会理解
- 算法推理

**格式**：多项选择和自由形式

**命令**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks bbh \
  --num_fewshot 3
```

**结果解读**：
- 随机猜测：约 25%
- GPT-3 (175B)：33.9%
- PaLM 540B：58.3%
- GPT-4：86.7%

**适用于**：测试高级推理能力。

### IFEval (Instruction-Following Evaluation)

**衡量内容**：遵循具体且可验证指令的能力。

**指令类型**：
- 格式约束（例如，"answer in 3 sentences"）
- 长度约束（例如，"use at least 100 words"）
- 内容约束（例如，"include the word 'banana'"）
- 结构约束（例如，"use bullet points"）

**格式**：自由形式生成，并使用基于规则的方法进行验证

**命令**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-chat-hf \
  --tasks ifeval \
  --batch_size auto
```

**结果解读**：
- 衡量指标：指令遵循程度（而非回答质量）
- GPT-4：指令遵循率 86%
- Claude 2：84%

**适用于**：评估聊天/指令模型。

### GLUE (General Language Understanding Evaluation)

**衡量内容**：通过 9 项任务评估自然语言理解能力。

**任务**：
- `cola`：语法可接受性
- `sst2`：情感分析
- `mrpc`：复述识别
- `qqp`：问题对
- `stsb`：语义相似度
- `mnli`：自然语言推断
- `qnli`：问答式 NLI（自然语言推断）
- `rte`：文本蕴含识别
- `wnli`：Winograd schema

**命令**：
```bash
lm_eval --model hf \
  --model_args pretrained=bert-base-uncased \
  --tasks glue \
  --num_fewshot 0
```

**结果解读**：
- BERT Base：78.3（GLUE 分数）
- RoBERTa Large：88.5
- 人类基线：87.1

**适用于**：仅编码器模型、微调基线。

### LongBench

**衡量内容**：长上下文理解能力（4K–32K tokens）。

**涵盖 21 项任务**：
- 单文档问答
- 多文档问答
- 摘要生成
- Few-shot learning
- 代码补全
- 合成任务

**命令**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks longbench \
  --batch_size 1
```

**结果解读**：
- 测试上下文利用能力
- 许多模型在上下文超过 4K tokens 后表现不佳
- GPT-4 Turbo：54.3%

**适用于**：评估长上下文模型。

## 其他 Benchmark

### TruthfulQA

**衡量内容**：模型倾向于如实回答，还是生成听起来可信的虚假信息。

**格式**：多项选择题，包含 4–5 个选项

**命令**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks truthfulqa_mc2 \
  --batch_size auto
```

**结果解读**：
- 更大的模型往往得分更低（因为生成的谎言更有说服力）
- GPT-3：58.8%
- GPT-4：59.0%
- 人类：约 94%

### ARC (AI2 Reasoning Challenge)

**衡量内容**：小学水平的科学问题。

**变体**：
- `arc_easy`：较简单的问题
- `arc_challenge`：需要推理的较难问题

**命令**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks arc_challenge \
  --num_fewshot 25
```

**结果解读**：
- ARC-Easy：大多数模型得分 >80%
- ARC-Challenge 随机猜测：25%
- GPT-4：96.3%

### HellaSwag

**衡量内容**：对日常情境的常识推理能力。

**格式**：选择最合理的后续内容

**命令**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks hellaswag \
  --num_fewshot 10
```

**结果解读**：
- 随机猜测：25%
- GPT-3：78.9%
- Llama 2 70B：85.3%

### WinoGrande

**衡量内容**：通过代词指代消解评估常识推理能力。

**示例**：
```
The trophy doesn't fit in the brown suitcase because _ is too large.
A. the trophy
B. the suitcase
```

**命令**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks winogrande \
  --num_fewshot 5
```

### PIQA

**衡量内容**：物理常识推理能力。

**示例**："To clean a keyboard, use compressed air or..."

**命令**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks piqa
```

## 多语言 Benchmark

### AfroBench

**衡量内容**：在 64 种非洲语言上的表现。

**15 项任务**：NLU、文本生成、知识、问答、数学推理

**命令**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks afrobench
```

### NorEval

**衡量内容**：挪威语理解能力（9 个任务类别）。

**命令**：
```bash
lm_eval --model hf \
  --model_args pretrained=NbAiLab/nb-gpt-j-6B \
  --tasks noreval
```

## 特定领域 Benchmark

### MATH

**衡量内容**：高中数学竞赛题。

**命令**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks math \
  --num_fewshot 4
```

**结果解读**：
- 极具挑战性
- GPT-4：42.5%
- Minerva 540B：33.6%

### MBPP (Mostly Basic Python Problems)

**衡量内容**：根据自然语言描述编写 Python 程序的能力。

**命令**：
```bash
lm_eval --model hf \
  --model_args pretrained=codellama/CodeLlama-7b-hf \
  --tasks mbpp \
  --batch_size 1
```

### DROP

**衡量内容**：需要离散推理的阅读理解能力。

**命令**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks drop
```

## Benchmark 选择指南

### 通用模型

运行以下套件：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks mmlu,gsm8k,hellaswag,arc_challenge,truthfulqa_mc2 \
  --num_fewshot 5
```

### 代码模型

```bash
lm_eval --model hf \
  --model_args pretrained=codellama/CodeLlama-7b-hf \
  --tasks humaneval,mbpp \
  --batch_size 1
```

### 聊天/指令模型

```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-chat-hf \
  --tasks ifeval,mmlu,gsm8k_cot \
  --batch_size auto
```

### 长上下文模型

```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-3.1-8B \
  --tasks longbench \
  --batch_size 1
```

## 结果解读

### 理解各项指标

**Accuracy**：正确答案的百分比（最常用）

**Exact Match (EM)**：要求字符串完全匹配（严格）

**F1 Score**：兼顾 precision 与 recall

**BLEU/ROUGE**：文本生成相似度

**Pass@k**：生成 k 个样本时通过测试的比例

### 典型分数范围

| 模型规模 | MMLU | GSM8K | HumanEval | HellaSwag |
|------------|------|-------|-----------|-----------|
| 7B | 40-50% | 10-20% | 5-15% | 70-80% |
| 13B | 45-55% | 20-35% | 15-25% | 75-82% |
| 70B | 60-70% | 50-65% | 35-50% | 82-87% |
| GPT-4 | 86% | 92% | 67% | 95% |

### 危险信号

- **所有任务均处于随机猜测水平**：说明模型训练不正确
- **生成任务的得分恰好为 0%**：很可能存在格式或解析问题
- **不同运行之间方差巨大**：检查 seed/sampling 设置
- **所有任务都优于 GPT-4**：很可能存在数据污染

## 最佳实践

1. **始终报告 few-shot 设置**：0-shot、5-shot 等
2. **使用多个 seed 运行**：报告 mean ± std
3. **检查数据污染**：在训练数据中搜索 benchmark 示例
4. **与已发布的基线比较**：验证评测设置是否正确
5. **报告所有超参数**：模型、batch size、max tokens、temperature

## 参考资料

- 任务列表：`lm_eval --tasks list`
- 任务 README：`lm_eval/tasks/README.md`
- 论文：参阅各 benchmark 对应的论文
