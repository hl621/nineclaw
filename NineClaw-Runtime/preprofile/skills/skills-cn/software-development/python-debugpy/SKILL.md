---
name: python-debugpy
description: "调试 Python：pdb REPL + debugpy 远程调试（DAP）。"
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [debugging, python, pdb, debugpy, breakpoints, dap, post-mortem]
    related_skills: [systematic-debugging, node-inspect-debugger]
---

# Python 调试器（pdb + debugpy）

## 概述

根据场景选择三种工具：

| 工具 | 适用场景 |
|---|---|
| **`breakpoint()` + pdb** | 本地、交互式且最简单。在源码中加入 `breakpoint()`，正常运行，即可在该行进入 REPL。 |
| **`python -m pdb`** | 无需修改源码，直接在 pdb 下启动现有脚本。适合快速探查。 |
| **`debugpy`** | 远程、无头环境，或“附加到已在运行的进程”。它使用 DAP，可从终端编写脚本控制，适用于长时间运行的进程（gateway、daemon、PTY 子进程）。 |

**从 `breakpoint()` 开始。** 这是成本最低且能奏效的方法。

## 使用时机

- 测试失败，但 traceback 无法说明某个值为什么不正确
- 需要逐步执行函数并观察集合如何变化
- 长时间运行的进程（hermes gateway、tui_gateway）行为异常，且无法重启
- 事后调试（post-mortem）：类生产代码中触发异常，需要检查崩溃位置的局部变量
- 实际缺陷位于 subprocess / child 中（Python `_SlashWorker`、PTY bridge worker）

**以下情况不要使用：** `print()` / `logging.debug` 能在一分钟内解决的问题，或 `pytest -vv --tb=long --showlocals` 已经能揭示的问题。

## pdb 快速参考

在任意 pdb 提示符（`(Pdb)`）内：

| 命令 | 操作 |
|---|---|
| `h` / `h cmd` | 显示帮助 |
| `n` | 执行下一行（单步跳过） |
| `s` | 单步进入 |
| `r` | 从当前函数返回 |
| `c` | 继续执行 |
| `unt N` | 继续执行至第 N 行 |
| `j N` | 跳转至第 N 行（仅限同一函数） |
| `l` / `ll` | 列出当前行附近的源码 / 完整函数 |
| `w` | 显示当前位置（调用栈） |
| `u` / `d` | 在调用栈中上移 / 下移 |
| `a` | 打印当前函数的参数 |
| `p expr` / `pp expr` | 打印 / 美化打印表达式 |
| `display expr` | 每次暂停时自动打印表达式 |
| `b file:line` | 设置断点 |
| `b func` | 在进入函数时中断 |
| `b file:line, cond` | 设置条件断点 |
| `cl N` | 清除第 N 个断点 |
| `tbreak file:line` | 设置一次性断点 |
| `!stmt` | 执行任意 Python 语句（包括赋值） |
| `interact` | 在当前作用域进入完整的 Python REPL（按 Ctrl+D 退出） |
| `q` | 退出 |

`interact` 命令功能最强——你可以导入任何内容、检查复杂对象，甚至调用会改变状态的方法。默认情况下局部变量只读；若要修改，请使用 `!x = 42`，该命令需在 `(Pdb)` 提示符中输入。

## 配方 1：本地断点

最简单的方法。编辑文件：

```python
def compute(x, y):
    result = some_helper(x)
    breakpoint()           # <-- drops into pdb here
    return result + y
```

正常运行代码。程序会在 `breakpoint()` 所在行停下，你可以完整访问局部变量。

**提交前不要忘记移除 `breakpoint()`。** 使用 `git diff` 或提交前 grep：
```bash
rg -n 'breakpoint\(\)' --type py
```

## 配方 2：在 pdb 下启动脚本（不修改源码）

```bash
python -m pdb path/to/script.py arg1 arg2
# Lands at first line of script
(Pdb) b path/to/script.py:42
(Pdb) c
```

## 配方 3：调试 pytest 测试

hermes 测试运行器和 pytest 都支持此功能：

```bash
# Drop to pdb on failure (or on any raised exception):
scripts/run_tests.sh tests/path/to/test_file.py::test_name --pdb

# Drop to pdb at the START of the test:
scripts/run_tests.sh tests/path/to/test_file.py::test_name --trace

# Show locals in tracebacks without pdb:
scripts/run_tests.sh tests/path/to/test_file.py --showlocals --tb=long
```

注意：`scripts/run_tests.sh` 通过 `run_tests_parallel.py` 在捕获输出的子进程中运行每个测试文件（不使用 xdist），因此交互式 pdb 在该包装器下无法工作。使用 `--pdb` 时请直接运行 pytest：

```bash
source .venv/bin/activate
python -m pytest tests/foo_test.py::test_bar --pdb
```

这会绕过 hermetic-env 保证——用于调试没有问题，但推送前必须在包装器下重新运行以确认结果。

## 配方 4：对任意异常进行事后调试

```python
import pdb, sys
try:
    run_the_thing()
except Exception:
    pdb.post_mortem(sys.exc_info()[2])
```

或者包装整个脚本：

```bash
python -m pdb -c continue script.py
# When it crashes, pdb catches it and you're in the frame of the exception
```

或者在 repl/jupyter 中设置全局 hook：

```python
import sys
def excepthook(etype, value, tb):
    import pdb; pdb.post_mortem(tb)
sys.excepthook = excepthook
```

## 配方 5：使用 debugpy 远程调试（附加到运行中的进程）

适用于长时间运行的进程：Hermes gateway、tui_gateway、daemon，或已经出现异常且无法干净重启的进程。

### 设置

```bash
source /home/bb/hermes-agent/.venv/bin/activate
pip install debugpy
```

### 模式 A：修改源码——进程启动时等待调试器

在入口点顶部附近（或要调试的函数内部）添加：

```python
import debugpy
debugpy.listen(("127.0.0.1", 5678))
print("debugpy listening on 5678, waiting for client...", flush=True)
debugpy.wait_for_client()
debugpy.breakpoint()       # optional: pause immediately once attached
```

启动进程；它会阻塞在 `wait_for_client()`。

### 模式 B：不修改源码——使用 `-m debugpy` 启动

```bash
python -m debugpy --listen 127.0.0.1:5678 --wait-for-client your_script.py arg1
```

模块入口的等效写法：

```bash
python -m debugpy --listen 127.0.0.1:5678 --wait-for-client -m your.module
```

### 模式 C：附加到已在运行的进程

需要 PID，并且目标环境中已预装 debugpy：

```bash
python -m debugpy --listen 127.0.0.1:5678 --pid <pid>
# debugpy injects itself into the process. Then attach a client as below.
```

某些内核/安全配置会阻止基于 ptrace 的注入（`/proc/sys/kernel/yama/ptrace_scope`）。可通过以下方式修复：
```bash
echo 0 | sudo tee /proc/sys/kernel/yama/ptrace_scope
```

### 从终端连接客户端

终端侧最简单的 DAP 客户端是 VS Code CLI 或一个小脚本。在 Hermes 内部有两种实用选择：

**选项 1：`debugpy` 自带的 CLI REPL**——这不是官方功能，而是一个微型 DAP 客户端脚本：

```python
# /tmp/dap_client.py
import socket, json, itertools, time, sys

HOST, PORT = "127.0.0.1", 5678
s = socket.create_connection((HOST, PORT))
seq = itertools.count(1)

def send(msg):
    msg["seq"] = next(seq)
    body = json.dumps(msg).encode()
    s.sendall(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)

def recv():
    header = b""
    while b"\r\n\r\n" not in header:
        header += s.recv(1)
    length = int(header.decode().split("Content-Length:")[1].split("\r\n")[0].strip())
    body = b""
    while len(body) < length:
        body += s.recv(length - len(body))
    return json.loads(body)

send({"type": "request", "command": "initialize", "arguments": {"adapterID": "python"}})
print(recv())
send({"type": "request", "command": "attach", "arguments": {}})
print(recv())
send({"type": "request", "command": "setBreakpoints",
      "arguments": {"source": {"path": sys.argv[1]},
                    "breakpoints": [{"line": int(sys.argv[2])}]}})
print(recv())
send({"type": "request", "command": "configurationDone"})
# ... loop reading events and sending continue/stepIn/etc.
```

用于一次性自动化没有问题，但作为交互式用户体验会很痛苦。

**选项 2：从 VS Code / Cursor / Zed 附加**——如果用户已打开其中之一，可以添加 `launch.json`：

```json
{
  "name": "Attach to Hermes",
  "type": "debugpy",
  "request": "attach",
  "connect": { "host": "127.0.0.1", "port": 5678 },
  "justMyCode": false,
  "pathMappings": [
    { "localRoot": "${workspaceFolder}", "remoteRoot": "/home/bb/hermes-agent" }
  ]
}
```

**选项 3：使用 `remote-pdb`，放弃 DAP**——对于终端代理，这通常才是实际需要的方案：

```bash
pip install remote-pdb
```

在代码中：
```python
from remote_pdb import set_trace
set_trace(host="127.0.0.1", port=4444)   # blocks until connection
```

然后在终端中：
```bash
nc 127.0.0.1 4444
# You get a (Pdb) prompt exactly as if debugging locally.
```

`remote-pdb` 是最简洁、最适合代理的选择；当 `debugpy` 的 DAP 协议显得过度复杂时，通常应选择前者。只有确实需要 IDE 集成时才使用 `debugpy`。

## 调试 Hermes 特有的进程

### 测试
参见配方 3。包装器会捕获子进程输出，因此交互式 pdb 需要直接运行 pytest。

### `run_agent.py` / CLI——一次性进程
最简单的方法：在可疑行附近添加 `breakpoint()`，然后正常运行 `hermes`。程序暂停后，控制权会返回终端。

### `tui_gateway` 子进程（由 `hermes --tui` 生成）
该 gateway 作为 Node TUI 的子进程运行。可选方案：

**A. 修改 gateway 源码：**
```python
# tui_gateway/server.py near the top of serve()
import debugpy
debugpy.listen(("127.0.0.1", 5678))
debugpy.wait_for_client()
```
启动 `hermes --tui`。TUI 看起来会冻结（其后端正在等待）。附加客户端；当你执行 `continue` 时，程序恢复运行。

**B. 在特定 handler 中使用 `remote-pdb`：**
```python
from remote_pdb import set_trace
set_trace(host="127.0.0.1", port=4444)   # in the RPC handler you want to trap
```
在 TUI 中触发对应的斜杠命令，然后在另一个终端中执行 `nc 127.0.0.1 4444`。

### `_SlashWorker` 子进程
模式相同——使用 `remote-pdb` 并调用 `set_trace()`，将它放在 worker 的 `exec` 路径内。该 worker 会在多个斜杠命令之间持续存在，因此第一次触发会阻塞，直到你连接；除非重新布置断点，后续斜杠命令将正常通过。

### Gateway（`gateway/run.py`）
这是长时间运行的进程。可在 handler 中使用 `remote-pdb`；如果本来就要重启 gateway，则使用 `debugpy` 并添加 `--wait-for-client`。

## 常见陷阱

1. **pdb 在并行运行器或捕获输出的运行器下会悄无声息地失效。** 你看不到提示符，测试只会挂起（pytest-xdist 以及 `scripts/run_tests.sh` 中捕获每个文件输出的子进程都是如此）。交互式调试时应直接对单个文件运行 pytest。

2. **在 CI / 非 TTY 上下文中的 `breakpoint()` 会导致进程挂起。** 本地使用安全，但绝不能提交。添加提交前 grep 作为安全网。

3. **`PYTHONBREAKPOINT=0`** 会禁用所有 `breakpoint()` 调用。如果断点未命中，请检查环境变量：
   ```bash
   echo $PYTHONBREAKPOINT
   ```

4. **`debugpy.listen` 只有在同时调用 `wait_for_client()` 时才会阻塞。** 如果不调用，程序将继续执行，第一个断点可能在客户端附加前就已触发。

5. **在加固内核上附加 PID 会失败。** `ptrace_scope=1`（Ubuntu 默认值）只允许同一用户对其子进程执行 ptrace。解决方法：执行 `echo 0 > /proc/sys/kernel/yama/ptrace_scope`（需要 root），或从一开始就在 `debugpy` 下启动。

6. **线程。** `pdb` 只能调试当前线程。对于多线程代码，请使用 `debugpy`（支持线程的 DAP），或为每个线程设置 `threading.settrace()`。

7. **asyncio。** `pdb` 可在协程中工作，但在 pdb 内使用 `await` 需要 Python 3.13+；旧版本则需执行 `await`，但要在 `interact` 模式中进行。对于 3.11/3.12，可使用 `asyncio.run_coroutine_threadsafe` 技巧，或采用基于 `!stmt` 的 await，并借助 `asyncio.ensure_future` 实现。

8. **`scripts/run_tests.sh` 会移除凭据并设置 `HOME=<tmpdir>`。** 如果缺陷依赖用户配置或真实 API 密钥，就无法在包装器下复现。先用原始 `pytest` 进行调试和复现，再在包装器下重新确认。

9. **Fork / 多进程。** pdb 不会跟随 fork。每个子进程都需要自己的 `breakpoint()` 或 `set_trace()`。对于 Hermes 子代理，请一次只调试一个进程。

## 验证清单

- [ ] 执行 `pip install debugpy` 后，确认：`python -c "import debugpy; print(debugpy.__version__)"`
- [ ] 远程调试时，确认端口确实正在监听：`ss -tlnp | grep 5678`
- [ ] 第一个断点确实命中（如果没有，可能设置了 `PYTHONBREAKPOINT=0`、正在并行/捕获输出的运行器下运行，或程序在附加前已执行完毕）
- [ ] `where` / `w` 显示预期的调用栈
- [ ] 调试后清理：提交的代码中没有遗留 `breakpoint()` / `set_trace()`
  ```bash
  rg -n 'breakpoint\(\)|set_trace\(|debugpy\.listen' --type py
  ```

## 一次性配方

**“为什么这个 dict 缺少一个 key？”**
```python
# add above the KeyError site
breakpoint()
# then in pdb:
(Pdb) pp d
(Pdb) pp list(d.keys())
(Pdb) w                # how did we get here
```

**“这个测试单独运行时通过，但在测试套件中失败。”**
```bash
scripts/run_tests.sh tests/the_test.py   # confirm it fails under the isolated runner first
# For interactive debugging, or if it only fails WITH other tests:
source .venv/bin/activate
python -m pytest tests/ -x --pdb
# Now it pdb-traps at the exact failing test after state accumulated.
```

**“我的异步 handler 死锁了。”**
```python
# Add at handler entry
import remote_pdb; remote_pdb.set_trace(host="127.0.0.1", port=4444)
```
触发该 handler。执行 `nc 127.0.0.1 4444`，然后用 `w` 查看暂停的 frame，用 `!import asyncio; asyncio.all_tasks()` 查看还有哪些任务处于 pending 状态。

**“对 Ink 子进程 / subprocess 中的崩溃进行事后调试。”**
```bash
PYTHONFAULTHANDLER=1 python -m pdb -c continue path/to/entrypoint.py
# On crash, pdb lands at the frame of the exception with full locals
```
