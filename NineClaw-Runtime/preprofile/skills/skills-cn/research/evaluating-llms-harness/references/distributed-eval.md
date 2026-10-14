# 分布式评测

本指南介绍如何使用数据并行和张量/流水线并行，在多个 GPU 上运行评测。

## 概述

分布式评测通过以下方式加快基准测试：
- **数据并行（Data Parallelism）**：将评测样本分配到多个 GPU（每个 GPU 都有完整的模型副本）
- **张量并行（Tensor Parallelism）**：将模型权重拆分到多个 GPU（适用于大型模型）
- **流水线并行（Pipeline Parallelism）**：将模型层拆分到多个 GPU（适用于超大型模型）

**适用场景**：
- 数据并行：模型可装入单个 GPU，希望加快评测速度
- 张量/流水线并行：模型过大，无法装入单个 GPU

## HuggingFace 模型（`hf`）

### 数据并行（推荐）

每个 GPU 加载一份完整的模型副本，并处理评测数据的一个子集。

**单节点（8 个 GPU）**：
```bash
accelerate launch --multi_gpu --num_processes 8 \
  -m lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf,dtype=bfloat16 \
  --tasks mmlu,gsm8k,hellaswag \
  --batch_size 16
```

**加速效果**：接近线性加速（8 个 GPU = 约快 8 倍）

**显存**：每个 GPU 都需容纳完整模型（7B 模型约 14GB × 8 = 总计 112GB）

### 张量并行（模型分片）

对于无法装入单个 GPU 的模型，将模型权重拆分到多个 GPU。

**不使用 accelerate launcher**：
```bash
lm_eval --model hf \
  --model_args \
    pretrained=meta-llama/Llama-2-70b-hf,\
    parallelize=True,\
    dtype=bfloat16 \
  --tasks mmlu,gsm8k \
  --batch_size 8
```

**使用 8 个 GPU**：70B 模型（140GB）/ 8 = 每个 GPU 17.5GB ✅

**高级分片**：
```bash
lm_eval --model hf \
  --model_args \
    pretrained=meta-llama/Llama-2-70b-hf,\
    parallelize=True,\
    device_map_option=auto,\
    max_memory_per_gpu=40GB,\
    max_cpu_memory=100GB,\
    dtype=bfloat16 \
  --tasks mmlu
```

**选项**：
- `device_map_option`：`"auto"`（默认）、`"balanced"`、`"balanced_low_0"`
- `max_memory_per_gpu`：每个 GPU 的最大显存（例如 `"40GB"`）
- `max_cpu_memory`：用于卸载的最大 CPU 内存
- `offload_folder`：磁盘卸载目录

### 组合使用数据并行与张量并行

对于超大型模型，同时使用两种并行方式。

**示例：在 16 个 GPU 上运行 70B 模型（2 个副本，每个副本使用 8 个 GPU）**：
```bash
accelerate launch --multi_gpu --num_processes 2 \
  -m lm_eval --model hf \
  --model_args \
    pretrained=meta-llama/Llama-2-70b-hf,\
    parallelize=True,\
    dtype=bfloat16 \
  --tasks mmlu \
  --batch_size 8
```

**结果**：数据并行带来 2 倍加速，张量并行使 70B 模型能够装入 GPU

### 使用 `accelerate config` 进行配置

创建 `~/.cache/huggingface/accelerate/default_config.yaml`：
```yaml
compute_environment: LOCAL_MACHINE
distributed_type: MULTI_GPU
num_machines: 1
num_processes: 8
gpu_ids: all
mixed_precision: bf16
```

**然后运行**：
```bash
accelerate launch -m lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks mmlu
```

## vLLM 模型（`vllm`）

vLLM 提供高度优化的分布式推理。

### 张量并行

**单节点（4 个 GPU）**：
```bash
lm_eval --model vllm \
  --model_args \
    pretrained=meta-llama/Llama-2-70b-hf,\
    tensor_parallel_size=4,\
    dtype=auto,\
    gpu_memory_utilization=0.9 \
  --tasks mmlu,gsm8k \
  --batch_size auto
```

**显存占用**：70B 模型拆分到 4 个 GPU = 每个 GPU 约 35GB

### 数据并行

**多个模型副本**：
```bash
lm_eval --model vllm \
  --model_args \
    pretrained=meta-llama/Llama-2-7b-hf,\
    data_parallel_size=4,\
    dtype=auto,\
    gpu_memory_utilization=0.8 \
  --tasks hellaswag,arc_challenge \
  --batch_size auto
```

**结果**：4 个模型副本 = 4 倍吞吐量

### 组合使用张量并行与数据并行

**示例：8 个 GPU = 4 TP × 2 DP**：
```bash
lm_eval --model vllm \
  --model_args \
    pretrained=meta-llama/Llama-2-70b-hf,\
    tensor_parallel_size=4,\
    data_parallel_size=2,\
    dtype=auto,\
    gpu_memory_utilization=0.85 \
  --tasks mmlu \
  --batch_size auto
```

**结果**：70B 模型可以装入 GPU（TP=4），并获得 2 倍加速（DP=2）

### 多节点 vLLM

vLLM 原生不支持多节点。请使用 Ray：

```bash
# Start Ray cluster
ray start --head --port=6379

# Run evaluation
lm_eval --model vllm \
  --model_args \
    pretrained=meta-llama/Llama-2-70b-hf,\
    tensor_parallel_size=8,\
    dtype=auto \
  --tasks mmlu
```

## NVIDIA NeMo 模型（`nemo_lm`）

### 数据复制

**在 8 个 GPU 上运行 8 个副本**：
```bash
torchrun --nproc-per-node=8 --no-python \
  lm_eval --model nemo_lm \
  --model_args \
    path=/path/to/model.nemo,\
    devices=8 \
  --tasks hellaswag,arc_challenge \
  --batch_size 32
```

**加速效果**：接近线性加速（快 8 倍）

### 张量并行

**4 路张量并行**：
```bash
torchrun --nproc-per-node=4 --no-python \
  lm_eval --model nemo_lm \
  --model_args \
    path=/path/to/70b_model.nemo,\
    devices=4,\
    tensor_model_parallel_size=4 \
  --tasks mmlu,gsm8k \
  --batch_size 16
```

### 流水线并行

**在 4 个 GPU 上使用 2 TP × 2 PP**：
```bash
torchrun --nproc-per-node=4 --no-python \
  lm_eval --model nemo_lm \
  --model_args \
    path=/path/to/model.nemo,\
    devices=4,\
    tensor_model_parallel_size=2,\
    pipeline_model_parallel_size=2 \
  --tasks mmlu \
  --batch_size 8
```

**约束**：`devices = TP × PP`

### 多节点 NeMo

lm-evaluation-harness 目前不支持此功能。

## SGLang 模型（`sglang`）

### 张量并行

```bash
lm_eval --model sglang \
  --model_args \
    pretrained=meta-llama/Llama-2-70b-hf,\
    tp_size=4,\
    dtype=auto \
  --tasks gsm8k \
  --batch_size auto
```

### 数据并行（已弃用）

**注意**：SGLang 正在弃用数据并行。请改用张量并行。

```bash
lm_eval --model sglang \
  --model_args \
    pretrained=meta-llama/Llama-2-7b-hf,\
    dp_size=4,\
    dtype=auto \
  --tasks mmlu
```

## 性能比较

### 70B 模型评测（MMLU，5-shot）

| 方法 | GPU 数量 | 时间 | 每个 GPU 的显存 | 备注 |
|--------|------|------|------------|-------|
| HF（无并行） | 1 | 8 小时 | 140GB（OOM） | 无法装入 |
| HF（TP=8） | 8 | 2 小时 | 17.5GB | 较慢，但能装入 |
| HF（DP=8） | 8 | 1 小时 | 140GB（OOM） | 无法装入 |
| vLLM（TP=4） | 4 | 30 分钟 | 35GB | 快！ |
| vLLM（TP=4，DP=2） | 8 | 15 分钟 | 35GB | 最快 |

### 7B 模型评测（多个任务）

| 方法 | GPU 数量 | 时间 | 加速倍数 |
|--------|------|------|---------|
| HF（单 GPU） | 1 | 4 小时 | 1× |
| HF（DP=4） | 4 | 1 小时 | 4× |
| HF（DP=8） | 8 | 30 分钟 | 8× |
| vLLM（DP=8） | 8 | 15 分钟 | 16× |

**要点**：在推理方面，vLLM 明显快于 HuggingFace。

## 选择并行策略

### 决策树

```
Model fits on single GPU?
├─ YES: Use data parallelism
│   ├─ HF: accelerate launch --multi_gpu --num_processes N
│   └─ vLLM: data_parallel_size=N (fastest)
│
└─ NO: Use tensor/pipeline parallelism
    ├─ Model < 70B:
    │   └─ vLLM: tensor_parallel_size=4
    ├─ Model 70-175B:
    │   ├─ vLLM: tensor_parallel_size=8
    │   └─ Or HF: parallelize=True
    └─ Model > 175B:
        └─ Contact framework authors
```

### 显存估算

**经验公式**：
```
Memory (GB) = Parameters (B) × Precision (bytes) × 1.2 (overhead)
```

**示例**：
- 7B FP16：7 × 2 × 1.2 = 16.8GB ✅ 可装入 A100 40GB
- 13B FP16：13 × 2 × 1.2 = 31.2GB ✅ 可装入 A100 40GB
- 70B FP16：70 × 2 × 1.2 = 168GB ❌ 需要 TP=4 或 TP=8
- 70B BF16：70 × 2 × 1.2 = 168GB（与 FP16 相同）

**使用张量并行时**：
```
Memory per GPU = Total Memory / TP
```

- 70B 模型使用 4 个 GPU：168GB / 4 = 每个 GPU 42GB ✅
- 70B 模型使用 8 个 GPU：168GB / 8 = 每个 GPU 21GB ✅

## 多节点评测

### 配合 SLURM 使用 HuggingFace

**提交作业**：
```bash
#!/bin/bash
#SBATCH --nodes=4
#SBATCH --gpus-per-node=8
#SBATCH --ntasks-per-node=1

srun accelerate launch --multi_gpu \
  --num_processes $((SLURM_NNODES * 8)) \
  -m lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks mmlu,gsm8k,hellaswag \
  --batch_size 16
```

**提交**：
```bash
sbatch eval_job.sh
```

### 手动设置多节点

**在每个节点上运行**：
```bash
accelerate launch \
  --multi_gpu \
  --num_machines 4 \
  --num_processes 32 \
  --main_process_ip $MASTER_IP \
  --main_process_port 29500 \
  --machine_rank $NODE_RANK \
  -m lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks mmlu
```

**环境变量**：
- `MASTER_IP`：rank 0 节点的 IP
- `NODE_RANK`：每个节点分别为 0、1、2、3

## 最佳实践

### 1. 从小规模开始

先使用少量样本进行测试：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-70b-hf,parallelize=True \
  --tasks mmlu \
  --limit 100  # Just 100 samples
```

### 2. 监控 GPU 使用情况

```bash
# Terminal 1: Run evaluation
lm_eval --model hf ...

# Terminal 2: Monitor
watch -n 1 nvidia-smi
```

检查以下方面：
- GPU 利用率 > 90%
- 显存使用量保持稳定
- 所有 GPU 均处于活跃状态

### 3. 优化批次大小

```bash
# Auto batch size (recommended)
--batch_size auto

# Or tune manually
--batch_size 16  # Start here
--batch_size 32  # Increase if memory allows
```

### 4. 使用混合精度

```bash
--model_args dtype=bfloat16  # Faster, less memory
```

### 5. 检查通信

对于数据并行，请检查网络带宽：
```bash
# Should see InfiniBand or high-speed network
nvidia-smi topo -m
```

## 故障排除

### "CUDA out of memory"

**解决方案**：
1. 提高张量并行度：
   ```bash
   --model_args tensor_parallel_size=8  # Was 4
   ```

2. 减小批次大小：
   ```bash
   --batch_size 4  # Was 16
   ```

3. 降低精度：
   ```bash
   --model_args dtype=int8  # Quantization
   ```

### "NCCL error" 或挂起

**检查**：
1. 所有 GPU 均可见：`nvidia-smi`
2. 已安装 NCCL：`python -c "import torch; print(torch.cuda.nccl.version())"`
3. 节点之间的网络连通性

**修复方法**：
```bash
export NCCL_DEBUG=INFO  # Enable debug logging
export NCCL_IB_DISABLE=0  # Use InfiniBand if available
```

### 评测速度缓慢

**可能的原因**：
1. **数据加载瓶颈**：预处理数据集
2. **GPU 利用率低**：增大批次大小
3. **通信开销**：降低并行度

**性能分析**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks mmlu \
  --limit 100 \
  --log_samples  # Check timing
```

### GPU 负载不均衡

**现象**：GPU 0 的利用率为 100%，其他 GPU 为 50%

**解决方案**：使用 `device_map_option=balanced`：
```bash
--model_args parallelize=True,device_map_option=balanced
```

## 配置示例

### 小型模型（7B）——快速评测

```bash
# 8 A100s, data parallel
accelerate launch --multi_gpu --num_processes 8 \
  -m lm_eval --model hf \
  --model_args \
    pretrained=meta-llama/Llama-2-7b-hf,\
    dtype=bfloat16 \
  --tasks mmlu,gsm8k,hellaswag,arc_challenge \
  --num_fewshot 5 \
  --batch_size 32

# Time: ~30 minutes
```

### 大型模型（70B）——vLLM

```bash
# 8 H100s, tensor parallel
lm_eval --model vllm \
  --model_args \
    pretrained=meta-llama/Llama-2-70b-hf,\
    tensor_parallel_size=8,\
    dtype=auto,\
    gpu_memory_utilization=0.9 \
  --tasks mmlu,gsm8k,humaneval \
  --num_fewshot 5 \
  --batch_size auto

# Time: ~1 hour
```

### 超大型模型（175B+）

**需要专门配置——请联系框架维护者**

## 参考资料

- HuggingFace Accelerate：https://huggingface.co/docs/accelerate/
- vLLM 文档：https://docs.vllm.ai/
- NeMo 文档：https://docs.nvidia.com/nemo-framework/
- lm-eval 分布式指南：`docs/model_guide.md`
