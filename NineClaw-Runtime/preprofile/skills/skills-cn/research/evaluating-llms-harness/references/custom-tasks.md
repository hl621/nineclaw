# 自定义任务

在 lm-evaluation-harness 中创建领域专用评测任务的完整指南。

## 概述

自定义任务可用于在您自己的数据集上，使用自定义指标评测模型。任务通过 YAML 配置文件定义；对于复杂逻辑，还可选择使用 Python 实用函数。

**为什么要创建自定义任务**：
- 在专有数据或领域专用数据上进行评测
- 测试现有 benchmark 未覆盖的特定能力
- 为内部模型创建评测流水线
- 复现研究实验

## 快速开始

### 最简自定义任务

创建 `my_tasks/simple_qa.yaml`：

```yaml
task: simple_qa
dataset_path: data/simple_qa.jsonl
output_type: generate_until
doc_to_text: "Question: {{question}}\nAnswer:"
doc_to_target: "{{answer}}"
metric_list:
  - metric: exact_match
    aggregation: mean
    higher_is_better: true
```

**运行任务**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks simple_qa \
  --include_path my_tasks/
```

## 任务配置参考

### 核心字段

```yaml
# Task identification
task: my_custom_task           # Unique task name (required)
task_alias: "My Task"          # Display name
tag:                           # Tags for grouping
  - custom
  - domain_specific

# Dataset configuration
dataset_path: data/my_data.jsonl  # HuggingFace dataset or local path
dataset_name: default             # Subset name (if applicable)
training_split: train
validation_split: validation
test_split: test

# Evaluation configuration
output_type: generate_until    # or loglikelihood, multiple_choice
num_fewshot: 5                 # Number of few-shot examples
batch_size: auto               # Batch size

# Prompt templates (Jinja2)
doc_to_text: "Question: {{question}}"
doc_to_target: "{{answer}}"

# Metrics
metric_list:
  - metric: exact_match
    aggregation: mean
    higher_is_better: true

# Metadata
metadata:
  version: 1.0
```

### 输出类型

**`generate_until`**：自由形式生成
```yaml
output_type: generate_until
generation_kwargs:
  max_gen_toks: 256
  until:
    - "\n"
    - "."
  temperature: 0.0
```

**`loglikelihood`**：计算目标文本的对数概率
```yaml
output_type: loglikelihood
# Used for perplexity, classification
```

**`multiple_choice`**：从选项中选择答案
```yaml
output_type: multiple_choice
doc_to_choice: "{{choices}}"  # List of choices
```

## 数据格式

### 本地 JSONL 文件

`data/my_data.jsonl`：
```json
{"question": "What is 2+2?", "answer": "4"}
{"question": "Capital of France?", "answer": "Paris"}
```

**任务配置**：
```yaml
dataset_path: data/my_data.jsonl
dataset_kwargs:
  data_files:
    test: data/my_data.jsonl
```

### HuggingFace 数据集

```yaml
dataset_path: squad
dataset_name: plain_text
test_split: validation
```

### CSV 文件

`data/my_data.csv`：
```csv
question,answer,category
What is 2+2?,4,math
Capital of France?,Paris,geography
```

**任务配置**：
```yaml
dataset_path: data/my_data.csv
dataset_kwargs:
  data_files:
    test: data/my_data.csv
```

## Prompt 设计

### 简单模板

```yaml
doc_to_text: "Question: {{question}}\nAnswer:"
doc_to_target: "{{answer}}"
```

### 条件逻辑

```yaml
doc_to_text: |
  {% if context %}
  Context: {{context}}
  {% endif %}
  Question: {{question}}
  Answer:
```

### 多项选择

```yaml
doc_to_text: |
  Question: {{question}}
  A. {{choices[0]}}
  B. {{choices[1]}}
  C. {{choices[2]}}
  D. {{choices[3]}}
  Answer:

doc_to_target: "{{ 'ABCD'[answer_idx] }}"
doc_to_choice: ["A", "B", "C", "D"]
```

### Few-shot 格式

```yaml
fewshot_delimiter: "\n\n"        # Between examples
target_delimiter: " "            # Between question and answer
doc_to_text: "Q: {{question}}"
doc_to_target: "A: {{answer}}"
```

## 自定义 Python 函数

对于复杂逻辑，请使用 `utils.py` 中的 Python 函数。

### 创建 `my_tasks/utils.py`

```python
def process_docs(dataset):
    """Preprocess documents."""
    def _process(doc):
        # Custom preprocessing
        doc["question"] = doc["question"].strip().lower()
        return doc

    return dataset.map(_process)

def doc_to_text(doc):
    """Custom prompt formatting."""
    context = doc.get("context", "")
    question = doc["question"]

    if context:
        return f"Context: {context}\nQuestion: {question}\nAnswer:"
    return f"Question: {question}\nAnswer:"

def doc_to_target(doc):
    """Custom target extraction."""
    return doc["answer"].strip().lower()

def aggregate_scores(items):
    """Custom metric aggregation."""
    correct = sum(1 for item in items if item == 1.0)
    total = len(items)
    return correct / total if total > 0 else 0.0
```

### 在任务配置中使用

```yaml
task: my_custom_task
dataset_path: data/my_data.jsonl

# Use Python functions
process_docs: !function utils.process_docs
doc_to_text: !function utils.doc_to_text
doc_to_target: !function utils.doc_to_target

metric_list:
  - metric: exact_match
    aggregation: !function utils.aggregate_scores
    higher_is_better: true
```

## 实际应用示例

### 示例 1：领域问答任务

**目标**：评测医学问答能力。

`medical_qa/medical_qa.yaml`：
```yaml
task: medical_qa
dataset_path: data/medical_qa.jsonl
output_type: generate_until
num_fewshot: 3

doc_to_text: |
  Medical Question: {{question}}
  Context: {{context}}
  Answer (be concise):

doc_to_target: "{{answer}}"

generation_kwargs:
  max_gen_toks: 100
  until:
    - "\n\n"
  temperature: 0.0

metric_list:
  - metric: exact_match
    aggregation: mean
    higher_is_better: true
  - metric: !function utils.medical_f1
    aggregation: mean
    higher_is_better: true

filter_list:
  - name: lowercase
    filter:
      - function: lowercase
      - function: remove_whitespace

metadata:
  version: 1.0
  domain: medical
```

`medical_qa/utils.py`：
```python
from sklearn.metrics import f1_score
import re

def medical_f1(predictions, references):
    """Custom F1 for medical terms."""
    pred_terms = set(extract_medical_terms(predictions[0]))
    ref_terms = set(extract_medical_terms(references[0]))

    if not pred_terms and not ref_terms:
        return 1.0
    if not pred_terms or not ref_terms:
        return 0.0

    tp = len(pred_terms & ref_terms)
    fp = len(pred_terms - ref_terms)
    fn = len(ref_terms - pred_terms)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0

    return 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

def extract_medical_terms(text):
    """Extract medical terminology."""
    # Custom logic
    return re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)*\b', text)
```

### 示例 2：代码评测

`code_eval/python_challenges.yaml`：
```yaml
task: python_challenges
dataset_path: data/python_problems.jsonl
output_type: generate_until
num_fewshot: 0

doc_to_text: |
  Write a Python function to solve:
  {{problem_statement}}

  Function signature:
  {{function_signature}}

doc_to_target: "{{canonical_solution}}"

generation_kwargs:
  max_gen_toks: 512
  until:
    - "\n\nclass"
    - "\n\ndef"
  temperature: 0.2

metric_list:
  - metric: !function utils.execute_code
    aggregation: mean
    higher_is_better: true

process_results: !function utils.process_code_results

metadata:
  version: 1.0
```

`code_eval/utils.py`：
```python
import subprocess
import json

def execute_code(predictions, references):
    """Execute generated code against test cases."""
    generated_code = predictions[0]
    test_cases = json.loads(references[0])

    try:
        # Execute code with test cases
        for test_input, expected_output in test_cases:
            result = execute_with_timeout(generated_code, test_input, timeout=5)
            if result != expected_output:
                return 0.0
        return 1.0
    except Exception:
        return 0.0

def execute_with_timeout(code, input_data, timeout=5):
    """Safely execute code with timeout."""
    # Implementation with subprocess and timeout
    pass

def process_code_results(doc, results):
    """Process code execution results."""
    return {
        "passed": results[0] == 1.0,
        "generated_code": results[1]
    }
```

### 示例 3：指令遵循

`instruction_eval/instruction_eval.yaml`：
```yaml
task: instruction_following
dataset_path: data/instructions.jsonl
output_type: generate_until
num_fewshot: 0

doc_to_text: |
  Instruction: {{instruction}}
  {% if constraints %}
  Constraints: {{constraints}}
  {% endif %}
  Response:

doc_to_target: "{{expected_response}}"

generation_kwargs:
  max_gen_toks: 256
  temperature: 0.7

metric_list:
  - metric: !function utils.check_constraints
    aggregation: mean
    higher_is_better: true
  - metric: !function utils.semantic_similarity
    aggregation: mean
    higher_is_better: true

process_docs: !function utils.add_constraint_checkers
```

`instruction_eval/utils.py`：
```python
from sentence_transformers import SentenceTransformer, util

model = SentenceTransformer('all-MiniLM-L6-v2')

def check_constraints(predictions, references):
    """Check if response satisfies constraints."""
    response = predictions[0]
    constraints = json.loads(references[0])

    satisfied = 0
    total = len(constraints)

    for constraint in constraints:
        if verify_constraint(response, constraint):
            satisfied += 1

    return satisfied / total if total > 0 else 1.0

def verify_constraint(response, constraint):
    """Verify single constraint."""
    if constraint["type"] == "length":
        return len(response.split()) >= constraint["min_words"]
    elif constraint["type"] == "contains":
        return constraint["keyword"] in response.lower()
    # Add more constraint types
    return True

def semantic_similarity(predictions, references):
    """Compute semantic similarity."""
    pred_embedding = model.encode(predictions[0])
    ref_embedding = model.encode(references[0])
    return float(util.cos_sim(pred_embedding, ref_embedding))

def add_constraint_checkers(dataset):
    """Parse constraints into verifiable format."""
    def _parse(doc):
        # Parse constraint string into structured format
        doc["parsed_constraints"] = parse_constraints(doc.get("constraints", ""))
        return doc
    return dataset.map(_parse)
```

## 高级功能

### 输出过滤

```yaml
filter_list:
  - name: extract_answer
    filter:
      - function: regex
        regex_pattern: "Answer: (.*)"
        group: 1
      - function: lowercase
      - function: strip_whitespace
```

### 多项指标

```yaml
metric_list:
  - metric: exact_match
    aggregation: mean
    higher_is_better: true
  - metric: f1
    aggregation: mean
    higher_is_better: true
  - metric: bleu
    aggregation: mean
    higher_is_better: true
```

### 任务组

创建 `my_tasks/_default.yaml`：
```yaml
group: my_eval_suite
task:
  - simple_qa
  - medical_qa
  - python_challenges
```

**运行整个任务套件**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks my_eval_suite \
  --include_path my_tasks/
```

## 测试任务

### 验证配置

```bash
# Test task loading
lm_eval --tasks my_custom_task --include_path my_tasks/ --limit 0

# Run on 5 samples
lm_eval --model hf \
  --model_args pretrained=gpt2 \
  --tasks my_custom_task \
  --include_path my_tasks/ \
  --limit 5
```

### 调试模式

```bash
lm_eval --model hf \
  --model_args pretrained=gpt2 \
  --tasks my_custom_task \
  --include_path my_tasks/ \
  --limit 1 \
  --log_samples  # Save input/output samples
```

## 最佳实践

1. **从简单配置开始**：先使用最简配置进行测试
2. **对任务进行版本管理**：使用 `metadata.version`
3. **记录指标定义**：在注释中说明自定义指标
4. **使用多个模型进行测试**：确保任务具有稳健性
5. **在已知样例上验证**：加入基本正确性检查
6. **谨慎使用 filter**：filter 可能掩盖错误
7. **处理边界情况**：包括空字符串和字段缺失

## 常见模式

### 分类任务

```yaml
output_type: loglikelihood
doc_to_text: "Text: {{text}}\nLabel:"
doc_to_target: " {{label}}"  # Space prefix important!
metric_list:
  - metric: acc
    aggregation: mean
```

### 困惑度评测

```yaml
output_type: loglikelihood_rolling
doc_to_text: "{{text}}"
metric_list:
  - metric: perplexity
    aggregation: perplexity
```

### 排序任务

```yaml
output_type: loglikelihood
doc_to_text: "Query: {{query}}\nPassage: {{passage}}\nRelevant:"
doc_to_target: [" Yes", " No"]
metric_list:
  - metric: acc
    aggregation: mean
```

## 故障排查

**“Task not found”**：检查 `--include_path` 和 task 名称

**结果为空**：检查 `doc_to_text` 和 `doc_to_target` 模板

**指标错误**：确保 metric 名称正确（应为 exact_match，而不是 exact-match）

**filter 问题**：使用 `--log_samples` 测试 filter

**找不到 Python 函数**：检查 `!function module.function_name` 语法

## 参考资料

- 任务系统：EleutherAI/lm-evaluation-harness 文档
- 示例任务：`lm_eval/tasks/` 目录
- TaskConfig：`lm_eval/api/task.py`
