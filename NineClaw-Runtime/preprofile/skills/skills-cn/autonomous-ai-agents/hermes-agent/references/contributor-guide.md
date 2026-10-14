# 贡献者快速参考

供偶尔参与贡献的开发者和 PR 作者使用。完整开发者文档：https://hermes-agent.nousresearch.com/docs/developer-guide/

### 项目布局

```
hermes-agent/
├── run_agent.py          # AIAgent — core conversation loop
├── model_tools.py        # Tool discovery and dispatch
├── toolsets.py           # Toolset definitions
├── cli.py                # Interactive CLI (HermesCLI)
├── hermes_state.py       # SQLite session store
├── agent/                # Prompt builder, context compression, memory, model routing, credential pooling, skill dispatch
├── hermes_cli/           # CLI subcommands, config, setup, commands
│   ├── commands.py       # Slash command registry (CommandDef)
│   ├── config.py         # DEFAULT_CONFIG, env var definitions
│   └── main.py           # CLI entry point and argparse
├── tools/                # One file per tool
│   └── registry.py       # Central tool registry
├── gateway/              # Messaging gateway
│   └── platforms/        # Platform adapters (telegram, discord, etc.)
├── cron/                 # Job scheduler
├── tests/                # Extensive pytest suite (run via scripts/run_tests.sh)
└── website/              # Docusaurus docs site
```

配置：`~/.hermes/config.yaml`（设置）、`~/.hermes/.env`（API keys）——设置 `$HERMES_HOME` 后，两者都位于其目录下。

### 添加工具

需要修改两个文件。自动发现机制会导入所有 `tools/*.py` 文件，只要其中包含顶层
`registry.register()` 调用；但只有当工具名称出现在某个 toolset 中时，
该工具才会向 agent *公开*。

**1. 创建 `tools/your_tool.py`：**
```python
import json, os
from tools.registry import registry

def check_requirements() -> bool:
    return bool(os.getenv("EXAMPLE_API_KEY"))

def example_tool(param: str, task_id: str = None) -> str:
    return json.dumps({"success": True, "data": "..."})

registry.register(
    name="example_tool",
    toolset="example",
    schema={"name": "example_tool", "description": "...", "parameters": {...}},
    handler=lambda args, **kw: example_tool(
        param=args.get("param", ""), task_id=kw.get("task_id")),
    check_fn=check_requirements,
    requires_env=["EXAMPLE_API_KEY"],
)
```

**2. 在 `toolsets.py` 中将其接入 toolset** —— 把名称加入
`_HERMES_CORE_TOOLS`（所有平台）或某个特定 toolset。

所有 handler 都必须返回 JSON 字符串。路径应使用 `get_hermes_home()`，
绝不要硬编码 `~/.hermes`。对于自定义或仅限本地使用的工具，请在
`~/.hermes/plugins/` 中编写 plugin，而不是修改 core——参见开发者文档。

### 添加 Slash Command

1. 将 `CommandDef` 添加到 `COMMAND_REGISTRY`（位于 `hermes_cli/commands.py`）
2. 在 `cli.py` → `process_command()` 中添加 handler
3. （可选）在 `gateway/run.py` 中添加 gateway handler

所有使用方（帮助文本、自动补全、Telegram 菜单、Slack mapping）都会自动派生自中央 registry。

### Agent 循环（高层视角）

```
run_conversation():
  1. Build system prompt
  2. Loop while iterations < max:
     a. Call LLM (OpenAI-format messages + tool schemas)
     b. If tool_calls → dispatch each via handle_function_call() → append results → continue
     c. If text response → return
  3. Context compression triggers automatically near token limit
```

### 测试

请使用标准 runner——它会强制与 CI 保持一致（隔离的 `env -i`、取消设置
凭据、TZ=UTC，并通过
`scripts/run_tests_parallel.py` 实现逐文件 subprocess 隔离——不使用 xdist，worker 数量自动伸缩）：

```bash
scripts/run_tests.sh                          # full suite
scripts/run_tests.sh tests/tools/             # one directory
scripts/run_tests.sh tests/tools/test_x.py    # one file
scripts/run_tests.sh -v --tb=long             # pass-through pytest flags
```

- 测试会自动把 `HERMES_HOME` 重定向到临时目录——绝不会接触真实的 `~/.hermes/`。
- 脚本会依次探测 `.venv`、`venv`，然后探测共享的 worktree venv。
- **Windows：**该 wrapper 仅支持 POSIX；直接运行 pytest 的替代方案请参阅 `references/windows-quirks.md`。

**跨平台测试 guard：**使用仅限 POSIX syscall 的测试需要 skip marker。代码库中已有的常见示例：
- 创建 symlink → `@pytest.mark.skipif(sys.platform == "win32", reason="Symlinks require elevated privileges on Windows")`（参见 `tests/cron/test_cron_script.py`）
- POSIX 文件 mode（0o600 等）→ `@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX mode bits not enforced on Windows")`（参见 `tests/hermes_cli/test_auth_toctou_file_modes.py`）
- `signal.SIGALRM` → 仅限 Unix（单项测试 timeout 已不再直接使用它；参见 `tests/conftest.py::pytest_configure` 中的 win32 timeout-method shim）
- 实时 Winsock / Windows 特有 regression 测试 → `@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific regression")`

**只 monkeypatch `sys.platform` 并不够**，因为被测代码还可能调用 `platform.system()` / `platform.release()` / `platform.mac_ver()`。这些函数会独立地重新读取真实 OS，因此在 Windows runner 上把 `sys.platform = "linux"` 的测试仍会看到 `platform.system() == "Windows"`，继而走入 Windows 分支。请同时 patch 三者：

```python
monkeypatch.setattr(sys, "platform", "linux")
monkeypatch.setattr(platform, "system", lambda: "Linux")
monkeypatch.setattr(platform, "release", lambda: "6.8.0-generic")
```

完整示例参见 `tests/agent/test_prompt_builder.py::TestEnvironmentHints`。

### System prompt 的执行环境区块

有关 host/backend 的事实性指引（OS、`$HOME`、cwd、terminal backend、shell）
由 `agent/prompt_builder.py::build_environment_hints()` 生成。Prompt 作者需要遵守的关键
不变量是：使用**远程** terminal backend
（`docker, singularity, modal, daytona, ssh, managed_modal`）时，会隐藏 host 信息，
并且*所有*文件工具都在 backend container 内运行——prompt 绝不能描述 agent 无法访问的 host。

### Commit 约定

```
type: concise subject line

Optional body.
```

类型：`fix:`、`feat:`、`refactor:`、`docs:`、`chore:`

### 关键规则

- **绝不能破坏 prompt caching**——不要在对话进行中更改 context、tools 或 system prompt
- **消息 role 交替**——绝不能连续出现两条 assistant 消息或两条 user 消息
- 所有路径都使用 `get_hermes_home()`（来自 `hermes_constants`，可安全支持 profile）
- Config 值放在 `config.yaml` 中，secret 放在 `.env` 中
- 新工具需要 `check_fn`，以便只在满足要求时出现
