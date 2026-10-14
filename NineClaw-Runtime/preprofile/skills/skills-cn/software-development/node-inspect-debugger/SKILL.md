---
name: node-inspect-debugger
description: "通过 --inspect + Chrome DevTools Protocol CLI 调试 Node.js。"
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [debugging, nodejs, node-inspect, cdp, breakpoints, ui-tui]
    related_skills: [systematic-debugging, python-debugpy]
---

# Node.js Inspect 调试器

## 概述

当 `console.log` 不够用时，可以从终端以编程方式操控 Node 内置的 V8 检查器。你将获得真正的断点、单步进入/越过/跳出、调用栈遍历、局部/闭包作用域转储，以及在暂停帧中对任意表达式求值的能力。

有两种工具，任选其一：

- **`node inspect`** — 内置、无需安装的 CLI REPL。最适合快速探查。
- **`ndb` / CDP（通过 `chrome-remote-interface`）** — 可用 Node/Python 编写脚本；最适合自动设置大量断点、跨多次运行收集状态，或从智能体循环中进行非交互式调试。

**优先尝试 `node inspect`。** 它始终可用，而且 REPL 响应迅速。

## 适用场景

- Node 测试失败，需要查看中间状态
- ui-tui 崩溃或行为异常，希望检查渲染前的 React/Ink 状态
- tui_gateway 子进程（`_SlashWorker`、PTY 桥接工作进程）行为异常
- 需要检查闭包中的某个值，而 `console.log` 若不修改代码便无法触及该值
- 性能分析：附加到正在运行的进程，以捕获 CPU 性能分析或堆快照

**不适用于：** `console.log` 能在一分钟内解决的问题。断点驱动的调试成本更高；只有收益确实时才使用它。

## 快速参考：`node inspect` REPL

启动并暂停在第一行：

```bash
node inspect path/to/script.js
# or with tsx
node --inspect-brk $(which tsx) path/to/script.ts
```

`debug>` 提示符接受以下命令：

| 命令 | 操作 |
|---|---|
| `c` 或 `cont` | 继续执行 |
| `n` 或 `next` | 单步越过 |
| `s` 或 `step` | 单步进入 |
| `o` 或 `out` | 单步跳出 |
| `pause` | 暂停正在运行的代码 |
| `sb('file.js', 42)` | 在 file.js 第 42 行设置断点 |
| `sb(42)` | 在当前文件第 42 行设置断点 |
| `sb('functionName')` | 在函数被调用时中断 |
| `cb('file.js', 42)` | 清除断点 |
| `breakpoints` | 列出所有断点 |
| `bt` | 回溯（调用栈） |
| `list(5)` | 显示当前位置附近的 5 行源代码 |
| `watch('expr')` | 每次暂停时对 expr 求值 |
| `watchers` | 显示监视表达式 |
| `repl` | 进入当前作用域中的 REPL（按 Ctrl+C 退出 REPL） |
| `exec expr` | 对表达式求值一次 |
| `restart` | 重启脚本 |
| `kill` | 终止脚本 |
| `.exit` | 退出调试器 |

**在 `repl` 子模式中：** 可以输入任意 JS 表达式，包括访问局部变量/闭包变量。按 `Ctrl+C` 可退出并返回 `debug>`。

## 附加到正在运行的进程

当进程已经在运行时（例如长期运行的开发服务器或 TUI 网关）：

```bash
# 1. Send SIGUSR1 to enable the inspector on an existing process
kill -SIGUSR1 <pid>
# Node prints: Debugger listening on ws://127.0.0.1:9229/<uuid>

# 2. Attach the debugger CLI
node inspect -p <pid>
# or by URL
node inspect ws://127.0.0.1:9229/<uuid>
```

若要从一开始就启用检查器来启动进程：

```bash
node --inspect script.js           # listen on 127.0.0.1:9229, keep running
node --inspect-brk script.js       # listen AND pause on first line
node --inspect=0.0.0.0:9230 script.js   # custom host:port
```

通过 tsx 运行 TypeScript 时：

```bash
node --inspect-brk --import tsx script.ts
# or older tsx
node --inspect-brk -r tsx/cjs script.ts
```

## 编程式 CDP（从终端编写脚本）

如果想实现自动化——设置大量断点、捕获作用域状态、用脚本复现问题——请使用 `chrome-remote-interface`：

```bash
npm i -g chrome-remote-interface        # or project-local
# Start your target:
node --inspect-brk=9229 target.js &
```

驱动脚本（保存为 `/tmp/cdp-debug.js`）：

```javascript
const CDP = require('chrome-remote-interface');

(async () => {
  const client = await CDP({ port: 9229 });
  const { Debugger, Runtime } = client;

  Debugger.paused(async ({ callFrames, reason }) => {
    const top = callFrames[0];
    console.log(`PAUSED: ${reason} @ ${top.url}:${top.location.lineNumber + 1}`);

    // Walk scopes for locals
    for (const scope of top.scopeChain) {
      if (scope.type === 'local' || scope.type === 'closure') {
        const { result } = await Runtime.getProperties({
          objectId: scope.object.objectId,
          ownProperties: true,
        });
        for (const p of result) {
          console.log(`  ${scope.type}.${p.name} =`, p.value?.value ?? p.value?.description);
        }
      }
    }

    // Evaluate an expression in the paused frame
    const { result } = await Debugger.evaluateOnCallFrame({
      callFrameId: top.callFrameId,
      expression: 'typeof state !== "undefined" ? JSON.stringify(state) : "n/a"',
    });
    console.log('state =', result.value ?? result.description);

    await Debugger.resume();
  });

  await Runtime.enable();
  await Debugger.enable();

  // Set a breakpoint by URL regex + line
  await Debugger.setBreakpointByUrl({
    urlRegex: '.*app\\.tsx$',
    lineNumber: 119,       // 0-indexed
    columnNumber: 0,
  });

  await Runtime.runIfWaitingForDebugger();
})();
```

运行该脚本：

```bash
node /tmp/cdp-debug.js
```

Hermes 特别说明：`chrome-remote-interface` **不在** `ui-tui/package.json` 中。如果不想弄脏项目，请将它安装到一个用完即弃的位置：

```bash
mkdir -p /tmp/cdp-tools && cd /tmp/cdp-tools && npm i chrome-remote-interface
NODE_PATH=/tmp/cdp-tools/node_modules node /tmp/cdp-debug.js
```

## 调试 Hermes ui-tui

TUI 使用 Ink + tsx 构建。常见场景有两种：

### 在开发环境下调试单个 Ink 组件

`ui-tui/package.json` 中提供了 `npm run dev`（tsx --watch）。直接运行 tsx 即可添加 `--inspect-brk`：

```bash
cd /home/bb/hermes-agent/ui-tui
npm run build    # produce dist/ once so transpile isn't needed on first load
node --inspect-brk dist/entry.js
# In another terminal:
node inspect -p <node pid>
```

然后在 `debug>` 中执行：

```
sb('dist/app.js', 220)     # or wherever the suspect render is
cont
```

暂停后，进入 `repl` → 检查 `props`、状态引用、`useInput` 处理程序的值等。

### 调试正在运行的 `hermes --tui`

TUI 由 Python CLI 启动 Node。最简单的方法如下：

```bash
# 1. Launch TUI
hermes --tui &
TUI_PID=$(pgrep -f 'ui-tui/dist/entry' | head -1)

# 2. Enable inspector on that Node PID
kill -SIGUSR1 "$TUI_PID"

# 3. Find the WS URL
curl -s http://127.0.0.1:9229/json/list | jq -r '.[0].webSocketDebuggerUrl'

# 4. Attach
node inspect ws://127.0.0.1:9229/<uuid>
```

与 TUI 交互（在其窗口中输入）会让执行继续推进；调试器可在任意 `sb(...)` 断点处将其暂停。

### 调试 `_SlashWorker` / PTY 子进程

这些是 Python 进程，而不是 Node 进程——请使用 `python-debugpy` 技能。只有 Node 部分（Ink UI、tui_gateway 客户端，以及 `ui-tui/` 下通过 tsx 运行的测试）使用本技能。

## 在调试器下运行 Vitest 测试

```bash
cd /home/bb/hermes-agent/ui-tui
# Run a single test file paused on entry
node --inspect-brk ./node_modules/vitest/vitest.mjs run --no-file-parallelism src/app/foo.test.tsx
```

在另一个终端中执行：`node inspect -p <pid>`，然后依次执行 `sb('src/app/foo.tsx', 42)`、`cont`。

使用 `--no-file-parallelism`（vitest）或 `--runInBand`（jest），确保只存在一个工作进程——调试进程池非常痛苦。

## 堆快照与 CPU 性能分析（非交互式）

在上面的 CDP 驱动中，将 Debugger 换成 `HeapProfiler` / `Profiler`：

```javascript
// CPU profile for 5 seconds
await client.Profiler.enable();
await client.Profiler.start();
await new Promise(r => setTimeout(r, 5000));
const { profile } = await client.Profiler.stop();
require('fs').writeFileSync('/tmp/cpu.cpuprofile', JSON.stringify(profile));
// Open /tmp/cpu.cpuprofile in Chrome DevTools → Performance tab
```

```javascript
// Heap snapshot
await client.HeapProfiler.enable();
const chunks = [];
client.HeapProfiler.addHeapSnapshotChunk(({ chunk }) => chunks.push(chunk));
await client.HeapProfiler.takeHeapSnapshot({ reportProgress: false });
require('fs').writeFileSync('/tmp/heap.heapsnapshot', chunks.join(''));
```

## 常见陷阱

1. **TS 源代码中的行号错误。** 断点命中的是生成后的 JS，而不是 `.ts`。可以选择：(a) 在构建后的 `dist/*.js` 中设置断点；或 (b) 启用 source map（`node --enable-source-maps`）并使用 `sb('src/app.tsx', N)`——但这仅适用于会跟随 source map 的 CDP 客户端。`node inspect` CLI 不支持。

2. **`--inspect` 与 `--inspect-brk`。** `--inspect` 会启动检查器，但不会暂停；如果附加得太晚，脚本可能在设置第一个断点前就已经执行过去了。如需在任何代码运行前设置断点，请使用 `--inspect-brk`。

3. **端口冲突。** 默认端口是 `9229`。如果有多个 Node 进程正在接受检查，请传入 `--inspect=0`（随机端口），并从 `/json/list` 读取实际 URL：
   ```bash
   curl -s http://127.0.0.1:9229/json/list   # lists all inspectable targets on the host
   ```

4. **子进程。** 父进程上的 `--inspect` **不会**检查其子进程。使用 `NODE_OPTIONS='--inspect-brk' node parent.js` 将该选项传播到每个子进程；请注意，它们都需要唯一的端口（继承 `NODE_OPTIONS='--inspect'` 时，Node 会自动递增端口）。

5. **后台终止问题。** 如果目标暂停时按 `Ctrl+C` 退出 `node inspect`，目标会保持暂停状态。请先执行 `cont`，或显式使用 `kill` 终止目标。

6. **通过智能体终端运行 `node inspect`。** 它是一个适合 PTY 的 REPL。在 Hermes 中，请使用 `terminal(pty=true)` 启动，或使用 `background=true` + `process(action='submit', data='...')`。非 PTY 前台模式可用于一次性命令，但无法进行交互式单步调试。

7. **安全性。** `--inspect=0.0.0.0:9229` 会暴露任意代码执行能力。除非拥有隔离网络，否则始终绑定到 `127.0.0.1`（默认值）。

## 验证清单

设置好调试会话后，请验证：

- [ ] `curl -s http://127.0.0.1:9229/json/list` 恰好返回预期目标
- [ ] 第一个断点确实被命中（如果未命中，很可能是漏用了 `--inspect-brk`，或在执行完成后才附加）
- [ ] 暂停时显示的源代码是正确文件（不匹配 = source map 问题，参见陷阱 1）
- [ ] 执行 `exec process.pid` 时所在的 `repl` 返回的是原本打算附加到的 PID

## 一次性操作方案

**“为什么这个变量在第 X 行是 undefined？”**
```bash
node --inspect-brk script.js &
node inspect -p $!
# debug>
sb('script.js', X)
cont
# paused. Now:
repl
> myVariable
> Object.keys(this)
```

**“进入这个函数的调用路径是什么？”**
```
debug> sb('suspectFn')
debug> cont
# paused on entry
debug> bt
```

**“这条异步链挂住了——挂在哪里？”**
```
# Start with --inspect (no -brk), let it run to the hang, then:
debug> pause
debug> bt
# Now you see the stuck frame
```
