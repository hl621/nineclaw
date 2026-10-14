# Windows 特有注意事项

Hermes 可在 Windows 上原生运行（PowerShell、cmd、Windows Terminal、git-bash
mintty、VS Code integrated terminal）。大部分功能都能直接正常工作，但 Win32
与 POSIX 之间少数差异曾给我们带来问题 — 遇到新问题时请记录在此，以免后来的
人（或后续会话）不得不从头重新摸索。

### 输入/快捷键绑定

**Alt+Enter 无法插入换行符** — Windows Terminal（以及 mintty）会先于
prompt_toolkit 捕获该按键以切换全屏。请改用 **Ctrl+Enter**（CLI 在 Windows
上将其绑定为插入换行；直接按 Ctrl+J 也会产生相同效果，且没有副作用）。
要检查终端如何报告某个按键，请从仓库根目录运行
`python scripts/keystroke_diagnostic.py`。

### 配置/文件

**首次运行时出现 HTTP 400 "No models provided"** — `config.yaml` 保存时带有
UTF-8 BOM（Notepad 会这样做）。请将其重新保存为不带 BOM 的 UTF-8；
`hermes config edit` 能以正确格式写入。

### `execute_code`/沙箱

沙箱子进程中出现 **WinError 10106** — 它无法创建 `AF_INET` socket。根本原因
通常不是 Winsock LSP 损坏，而是 Hermes 的环境清理器移除了
`SYSTEMROOT`/`WINDIR`/`COMSPEC`（Python 的 `socket` 需要 `SYSTEMROOT` 才能找到
`mswsock.dll`）。`_WINDOWS_ESSENTIAL_ENV_VARS` 允许列表位于
`tools/code_execution_tool.py` 中，已经涵盖这些变量；如果仍遇到此问题，请输出
`os.environ`，在 `execute_code` 代码块中确认已设置 `SYSTEMROOT`。

### 在 Windows 上测试

`scripts/run_tests.sh` 仅适用于 POSIX（它预期存在 `.venv/bin/activate`）；Hermes
安装的 `venv/Scripts/` 中没有 pip/pytest（为减小体积而移除）。请将 pytest
安装到系统 Python 中并直接运行（仓库已不再使用 pytest-xdist；标准运行器通过
为每个文件启动独立子进程来实现隔离，而这一过程由仅适用于 POSIX 的封装脚本处理）：

```bash
"/c/Program Files/Python311/python" -m pip install --user pytest pyyaml
export PYTHONPATH="$(pwd)"
"/c/Program Files/Python311/python" -m pytest tests/foo/test_bar.py -v --tb=short
```

（仅适用于 POSIX 的测试需要添加跳过保护 — 请参阅
`references/contributor-guide.md` 中的跨平台保护列表。）

### 路径/文件系统

**行尾格式。** Git 可能会警告 `LF will be replaced by CRLF`。这只是表象问题 —
仓库的 `.gitattributes` 会进行规范化。不要让编辑器把已提交、使用 POSIX 换行的
文件自动转换为 CRLF。

**正斜杠几乎在所有地方都有效。** 每个 Hermes 工具以及大多数 Windows API 都接受
`C:/Users/...`。在代码和日志中优先使用正斜杠 — 这样可避免在 bash 中对反斜杠
进行 shell 转义。
