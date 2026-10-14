---
name: evaluating-llms-harness
description: "lm-eval-harness：对 LLM 进行 benchmark（MMLU、GSM8K 等）。"
version: 1.0.1
author: Orchestra Research
license: MIT
dependencies: [lm-eval, transformers, vllm]
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Evaluation, LM Evaluation Harness, Benchmarking, MMLU, HumanEval, GSM8K, EleutherAI, Model Quality, Academic Benchmarks, Industry Standard]

---

# lm-evaluation-harness - LLM 基准评测

## 内容概览

在 60 多个学术 benchmark（MMLU、HumanEval、GSM8K、TruthfulQA、HellaSwag）上评测 LLM。适用于评测模型质量、比较模型、报告学术结果或跟踪训练进度。它是 EleutherAI、HuggingFace 和各大实验室采用的行业标准。支持 HuggingFace、vLLM 和 API。

## 快速开始

lm-evaluation-harness 使用标准化 prompt 和 metric，在 60 多个学术 benchmark 上评测 LLM。

**安装**：
```bash
pip install lm-eval
```

**评测任意 HuggingFace 模型**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks mmlu,gsm8k,hellaswag \
  --device cuda:0 \
  --batch_size 8
```

**查看可用 task**：
```bash
lm-eval ls tasks
```

## 常见工作流

### 工作流 1：标准 benchmark 评测

在核心 benchmark（MMLU、GSM8K、HumanEval）上评测模型。

复制此检查清单：

```
Benchmark Evaluation:
- [ ] Step 1: Choose benchmark suite
- [ ] Step 2: Configure model
- [ ] Step 3: Run evaluation
- [ ] Step 4: Analyze results
```

**步骤 1：选择 benchmark 套件**

**核心推理 benchmark**：
- **MMLU** (Massive Multitask Language Understanding) - 57 个学科，多项选择题
- **GSM8K** - 小学数学文字题
- **HellaSwag** - 常识推理
- **TruthfulQA** - 真实性与事实性
- **ARC** (AI2 Reasoning Challenge) - 科学问题

**代码 benchmark**：
- **HumanEval** - Python 代码生成（164 道题）
- **MBPP** (Mostly Basic Python Problems) - Python 编程

**标准套件**（推荐用于模型发布）：
```bash
--tasks mmlu,gsm8k,hellaswag,truthfulqa,arc_challenge
```

**步骤 2：配置模型**

**HuggingFace 模型**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf,dtype=bfloat16 \
  --tasks mmlu \
  --device cuda:0 \
  --batch_size auto  # Auto-detect optimal batch size
```

**量化模型（4-bit/8-bit）**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf,load_in_4bit=True \
  --tasks mmlu \
  --device cuda:0
```

**自定义 checkpoint**：
```bash
lm_eval --model hf \
  --model_args pretrained=/path/to/my-model,tokenizer=/path/to/tokenizer \
  --tasks mmlu \
  --device cuda:0
```

**步骤 3：运行评测**

```bash
# Full MMLU evaluation (57 subjects)
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks mmlu \
  --num_fewshot 5 \  # 5-shot evaluation (standard)
  --batch_size 8 \
  --output_path results/ \
  --log_samples  # Save individual predictions

# Multiple benchmarks at once
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks mmlu,gsm8k,hellaswag,truthfulqa,arc_challenge \
  --num_fewshot 5 \
  --batch_size 8 \
  --output_path results/llama2-7b-eval.json
```

**步骤 4：分析结果**

结果保存到 `results/llama2-7b-eval.json`：

```json
{
  "results": {
    "mmlu": {
      "acc": 0.459,
      "acc_stderr": 0.004
    },
    "gsm8k": {
      "exact_match": 0.142,
      "exact_match_stderr": 0.006
    },
    "hellaswag": {
      "acc_norm": 0.765,
      "acc_norm_stderr": 0.004
    }
  },
  "config": {
    "model": "hf",
    "model_args": "pretrained=meta-llama/Llama-2-7b-hf",
    "num_fewshot": 5
  }
}
```

### 工作流 2：跟踪训练进度

在训练期间评测 checkpoint。

```
Training Progress Tracking:
- [ ] Step 1: Set up periodic evaluation
- [ ] Step 2: Choose quick benchmarks
- [ ] Step 3: Automate evaluation
- [ ] Step 4: Plot learning curves
```

**步骤 1：设置周期性评测**

每隔 N 个训练 step 评测一次：

```bash
#!/bin/bash
# eval_checkpoint.sh

CHECKPOINT_DIR=$1
STEP=$2

lm_eval --model hf \
  --model_args pretrained=$CHECKPOINT_DIR/checkpoint-$STEP \
  --tasks gsm8k,hellaswag \
  --num_fewshot 0 \  # 0-shot for speed
  --batch_size 16 \
  --output_path results/step-$STEP.json
```

**步骤 2：选择快速 benchmark**

适合频繁评测的快速 benchmark：
- **HellaSwag**：单张 GPU 约 10 分钟
- **GSM8K**：约 5 分钟
- **PIQA**：约 2 分钟

不适合频繁评测（速度太慢）：
- **MMLU**：约 2 小时（57 个学科）
- **HumanEval**：需要执行代码

**步骤 3：自动执行评测**

集成到训练脚本中：

```python
# In training loop
if step % eval_interval == 0:
    model.save_pretrained(f"checkpoints/step-{step}")

    # Run evaluation
    os.system(f"./eval_checkpoint.sh checkpoints step-{step}")
```

或者使用 PyTorch Lightning callback：

```python
from pytorch_lightning import Callback

class EvalHarnessCallback(Callback):
    def on_validation_epoch_end(self, trainer, pl_module):
        step = trainer.global_step
        checkpoint_path = f"checkpoints/step-{step}"

        # Save checkpoint
        trainer.save_checkpoint(checkpoint_path)

        # Run lm-eval
        os.system(f"lm_eval --model hf --model_args pretrained={checkpoint_path} ...")
```

**步骤 4：绘制学习曲线**

```python
import json
import matplotlib.pyplot as plt

# Load all results
steps = []
mmlu_scores = []

for file in sorted(glob.glob("results/step-*.json")):
    with open(file) as f:
        data = json.load(f)
        step = int(file.split("-")[1].split(".")[0])
        steps.append(step)
        mmlu_scores.append(data["results"]["mmlu"]["acc"])

# Plot
plt.plot(steps, mmlu_scores)
plt.xlabel("Training Step")
plt.ylabel("MMLU Accuracy")
plt.title("Training Progress")
plt.savefig("training_curve.png")
```

### 工作流 3：比较多个模型

用于模型比较的 benchmark 套件。

```
Model Comparison:
- [ ] Step 1: Define model list
- [ ] Step 2: Run evaluations
- [ ] Step 3: Generate comparison table
```

**步骤 1：定义模型列表**

```bash
# models.txt
meta-llama/Llama-2-7b-hf
meta-llama/Llama-2-13b-hf
mistralai/Mistral-7B-v0.1
microsoft/phi-2
```

**步骤 2：运行评测**

```bash
#!/bin/bash
# eval_all_models.sh

TASKS="mmlu,gsm8k,hellaswag,truthfulqa"

while read model; do
    echo "Evaluating $model"

    # Extract model name for output file
    model_name=$(echo $model | sed 's/\//-/g')

    lm_eval --model hf \
      --model_args pretrained=$model,dtype=bfloat16 \
      --tasks $TASKS \
      --num_fewshot 5 \
      --batch_size auto \
      --output_path results/$model_name.json

done < models.txt
```

**步骤 3：生成对比表**

```python
import json
import pandas as pd

models = [
    "meta-llama-Llama-2-7b-hf",
    "meta-llama-Llama-2-13b-hf",
    "mistralai-Mistral-7B-v0.1",
    "microsoft-phi-2"
]

tasks = ["mmlu", "gsm8k", "hellaswag", "truthfulqa"]

results = []
for model in models:
    with open(f"results/{model}.json") as f:
        data = json.load(f)
        row = {"Model": model.replace("-", "/")}
        for task in tasks:
            # Get primary metric for each task
            metrics = data["results"][task]
            if "acc" in metrics:
                row[task.upper()] = f"{metrics['acc']:.3f}"
            elif "exact_match" in metrics:
                row[task.upper()] = f"{metrics['exact_match']:.3f}"
        results.append(row)

df = pd.DataFrame(results)
print(df.to_markdown(index=False))
```

输出：
```
| Model                  | MMLU  | GSM8K | HELLASWAG | TRUTHFULQA |
|------------------------|-------|-------|-----------|------------|
| meta-llama/Llama-2-7b  | 0.459 | 0.142 | 0.765     | 0.391      |
| meta-llama/Llama-2-13b | 0.549 | 0.287 | 0.801     | 0.430      |
| mistralai/Mistral-7B   | 0.626 | 0.395 | 0.812     | 0.428      |
| microsoft/phi-2        | 0.560 | 0.613 | 0.682     | 0.447      |
```

### 工作流 4：使用 vLLM 评测（推理更快）

使用 vLLM backend 可使评测速度达到原来的 5–10 倍。

```
vLLM Evaluation:
- [ ] Step 1: Install vLLM
- [ ] Step 2: Configure vLLM backend
- [ ] Step 3: Run evaluation
```

**步骤 1：安装 vLLM**

```bash
pip install vllm
```

**步骤 2：配置 vLLM backend**

```bash
lm_eval --model vllm \
  --model_args pretrained=meta-llama/Llama-2-7b-hf,tensor_parallel_size=1,dtype=auto,gpu_memory_utilization=0.8 \
  --tasks mmlu \
  --batch_size auto
```

**步骤 3：运行评测**

vLLM 比标准 HuggingFace 快 5–10 倍：

```bash
# Standard HF: ~2 hours for MMLU on 7B model
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks mmlu \
  --batch_size 8

# vLLM: ~15-20 minutes for MMLU on 7B model
lm_eval --model vllm \
  --model_args pretrained=meta-llama/Llama-2-7b-hf,tensor_parallel_size=2 \
  --tasks mmlu \
  --batch_size auto
```

## 何时使用及替代方案

**适合使用 lm-evaluation-harness 的情形：**
- 为学术论文评测模型
- 在标准 task 间比较模型质量
- 跟踪训练进度
- 报告标准化 metric（所有人使用相同的 prompt）
- 需要可复现的评测

**改用替代方案的情形：**
- **HELM** (Stanford)：更广泛的评测（公平性、效率、校准）
- **AlpacaEval**：使用 LLM judge 的指令遵循评测
- **MT-Bench**：对话式多轮评测
- **自定义脚本**：特定领域评测

## 常见问题

**问题：评测速度太慢**

使用 vLLM backend：
```bash
lm_eval --model vllm \
  --model_args pretrained=model-name,tensor_parallel_size=2
```

或者减少 few-shot 示例：
```bash
--num_fewshot 0  # Instead of 5
```

或者只评测 MMLU 的子集：
```bash
--tasks mmlu_stem  # Only STEM subjects
```

**问题：内存不足**

减小 batch size：
```bash
--batch_size 1  # Or --batch_size auto
```

使用量化：
```bash
--model_args pretrained=model-name,load_in_8bit=True
```

启用 CPU offloading：
```bash
--model_args pretrained=model-name,device_map=auto,offload_folder=offload
```

**问题：结果与报告值不同**

检查 few-shot 数量：
```bash
--num_fewshot 5  # Most papers use 5-shot
```

检查确切的 task 名称：
```bash
--tasks mmlu  # Not mmlu_direct or mmlu_fewshot
```

验证模型与 tokenizer 是否匹配：
```bash
--model_args pretrained=model-name,tokenizer=same-model-name
```

**问题：HumanEval 未执行代码**

执行生成代码的 task（HumanEval、MBPP 等）必须通过显式
确认后才能启用——运行时必须传入 `--confirm_run_unsafe_code`：

```bash
lm_eval --model hf \
  --model_args pretrained=model-name \
  --tasks humaneval \
  --confirm_run_unsafe_code  # Required to run tasks that execute generated code
```

如果不提供此 flag，lm-eval 会拒绝运行该 task，而不会静默跳过
代码执行。

## 高级主题

**Benchmark 说明**：请参阅 [references/benchmark-guide.md](references/benchmark-guide.md)，了解全部 60 多个 task 的详细说明、各自衡量的内容以及结果解读方法。

**自定义 task**：请参阅 [references/custom-tasks.md](references/custom-tasks.md)，了解如何创建特定领域的评测 task。

**API 评测**：请参阅 [references/api-evaluation.md](references/api-evaluation.md)，了解如何评测 OpenAI、Anthropic 及其他 API 模型。

**Multi-GPU 策略**：请参阅 [references/distributed-eval.md](references/distributed-eval.md)，了解 data parallel 和 tensor parallel 评测。

## 硬件要求

- **GPU**：NVIDIA（CUDA 11.8+），也可在 CPU 上运行（速度很慢）
- **VRAM**：
  - 7B 模型：16GB（bf16）或 8GB（8-bit）
  - 13B 模型：28GB（bf16）或 14GB（8-bit）
  - 70B 模型：需要 Multi-GPU 或量化
- **耗时**（7B 模型，单张 A100）：
  - HellaSwag：10 分钟
  - GSM8K：5 分钟
  - MMLU（完整）：2 小时
  - HumanEval：20 分钟

## 资源

- GitHub：https://github.com/EleutherAI/lm-evaluation-harness
- 文档：https://github.com/EleutherAI/lm-evaluation-harness/tree/main/docs
- Task 库：60 多个 task，包括 MMLU、GSM8K、HumanEval、TruthfulQA、HellaSwag、ARC、WinoGrande 等
- Leaderboard：https://huggingface.co/spaces/HuggingFaceH4/open_llm_leaderboard (使用此 harness)



