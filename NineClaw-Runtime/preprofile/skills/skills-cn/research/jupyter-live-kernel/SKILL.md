---
name: jupyter-live-kernel
description: "通过实时 Jupyter 内核（hamelnb）迭代运行 Python。"
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [jupyter, notebook, repl, data-science, exploration, iterative]
    category: data-science
---

# Jupyter 实时内核（hamelnb）

通过实时 Jupyter 内核提供**有状态的 Python REPL**。变量会在多次执行之间保留。当你需要逐步构建状态、探索 API、检查 DataFrame 或迭代开发复杂代码时，应使用此 Skill，而不是 `execute_code`。

## 何时使用此 Skill，何时使用其他工具

| 工具 | 适用场景 |
|------|----------|
| **此 Skill** | 迭代探索、跨步骤保留状态、数据科学、机器学习，以及“先试一下再检查”的场景 |
| `execute_code` | 需要访问 Hermes 工具（web_search、文件操作）的一次性脚本。无状态。 |
| `terminal` | Shell 命令、构建、安装、git 和进程管理 |

**经验法则：**如果这项任务适合使用 Jupyter notebook，就使用此 Skill。

## 前置条件

1. 必须已安装 **uv**（检查：`which uv`）
2. 必须已安装 **JupyterLab**：`uv tool install jupyterlab`
3. 必须有一个正在运行的 Jupyter 服务器（参见下方“设置”）

## 设置

hamelnb 脚本位置：
```
SCRIPT="$HOME/.agent-skills/hamelnb/skills/jupyter-live-kernel/scripts/jupyter_live_kernel.py"
```

如果尚未克隆：
```
git clone https://github.com/hamelsmu/hamelnb.git ~/.agent-skills/hamelnb
```

### 启动 JupyterLab

检查服务器是否已在运行：
```
uv run "$SCRIPT" servers
```

如果未找到服务器，请启动一个：
```
jupyter-lab --no-browser --port=8888 --notebook-dir=$HOME/notebooks \
  --IdentityProvider.token='' --ServerApp.password='' > /tmp/jupyter.log 2>&1 &
sleep 3
```

注意：为便于本地 Agent 访问，token/password 已禁用。服务器以无头模式运行。

### 创建用于 REPL 的 Notebook

如果只需要 REPL（没有现有 notebook），请创建一个最小 notebook 文件：
```
mkdir -p ~/notebooks
```
编写一个仅含空代码单元的最小 .ipynb JSON 文件，然后通过 Jupyter REST API 启动内核会话：
```
curl -s -X POST http://127.0.0.1:8888/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"path":"scratch.ipynb","type":"notebook","name":"scratch.ipynb","kernel":{"name":"python3"}}'
```

## 核心工作流

所有命令都返回结构化 JSON。始终使用 `--compact` 以节省 token。

### 1. 发现服务器和 Notebook

```
uv run "$SCRIPT" servers --compact
uv run "$SCRIPT" notebooks --compact
```

### 2. 执行代码（主要操作）

```
uv run "$SCRIPT" execute --path <notebook.ipynb> --code '<python code>' --compact
```

状态会在多次 execute 调用之间保留。变量、导入项和对象都会继续存在。

多行代码可使用 $'...' 引用方式：
```
uv run "$SCRIPT" execute --path scratch.ipynb --code $'import os\nfiles = os.listdir(".")\nprint(f"Found {len(files)} files")' --compact
```

### 3. 检查实时变量

```
uv run "$SCRIPT" variables --path <notebook.ipynb> list --compact
uv run "$SCRIPT" variables --path <notebook.ipynb> preview --name <varname> --compact
```

### 4. 编辑 Notebook 单元格

```
# View current cells
uv run "$SCRIPT" contents --path <notebook.ipynb> --compact

# Insert a new cell
uv run "$SCRIPT" edit --path <notebook.ipynb> insert \
  --at-index <N> --cell-type code --source '<code>' --compact

# Replace cell source (use cell-id from contents output)
uv run "$SCRIPT" edit --path <notebook.ipynb> replace-source \
  --cell-id <id> --source '<new code>' --compact

# Delete a cell
uv run "$SCRIPT" edit --path <notebook.ipynb> delete --cell-id <id> --compact
```

### 5. 验证（重启并运行全部内容）

仅当用户要求进行干净验证，或需要确认 notebook 能从头到尾运行时，才使用此操作：

```
uv run "$SCRIPT" restart-run-all --path <notebook.ipynb> --save-outputs --compact
```

## 实践经验

1. **服务器启动后的首次执行可能超时**——内核需要一点时间完成初始化。如果遇到超时，直接重试即可。

2. **内核使用的是 JupyterLab 的 Python**——软件包必须安装在该环境中。如果需要其他软件包，请先将其安装到 JupyterLab 工具环境。

3. **--compact 标志可显著节省 token**——始终使用它。若不使用，JSON 输出可能非常冗长。

4. **仅将其用作 REPL 时**，创建 scratch.ipynb 即可，无需编辑单元格。只需重复使用 `execute`。

5. **参数顺序很重要**——`--path` 等子命令标志应放在更下一级子命令之前。例如：`variables --path nb.ipynb list`，而不是 `variables list --path nb.ipynb`。

6. **如果会话尚不存在**，需要通过 REST API 启动会话（参见“设置”部分）。没有实时内核会话时，该工具无法执行代码。

7. **错误以带 traceback 的 JSON 返回**——读取 `ename` 和 `evalue` 字段，以了解问题原因。

8. **偶发 websocket 超时**——某些操作第一次尝试时可能超时，尤其是在内核重启后。升级处理前先重试一次。

## 默认超时时间

脚本每次执行的默认超时时间为 30 秒。对于长时间运行的操作，请传入 `--timeout 120`。初始设置或繁重计算应使用较宽裕的超时时间（60 秒以上）。
