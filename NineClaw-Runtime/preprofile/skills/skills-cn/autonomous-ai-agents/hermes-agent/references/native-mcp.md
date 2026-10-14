# 原生 MCP 客户端

Hermes Agent 内置 MCP 客户端，会在启动时连接 MCP servers、发现其工具，并将它们作为一等工具提供给智能体直接调用。无需 bridge CLI——MCP servers 提供的工具会与 `terminal`、`read_file` 等内置工具并列出现。

## 何时使用

在以下任何情况下，都可以使用此功能：
- 连接 MCP servers，并从 Hermes Agent 内部使用其工具
- 通过 MCP 添加外部能力（文件系统访问、GitHub、数据库、API）
- 运行基于本地 stdio 的 MCP servers（npx、uvx 或任意命令）
- 连接远程 HTTP/StreamableHTTP MCP servers
- 让 MCP 工具自动被发现，并在每次对话中都可使用

如果只是想从终端临时、一次性调用 MCP 工具，而不进行任何配置，请改用 `mcporter` 技能。

## 前置条件

- **mcp Python package** —— 可选依赖；使用 `pip install mcp` 安装。如果未安装，MCP 支持会被静默禁用。
- **Node.js** —— 基于 `npx` 的 MCP servers（大多数社区服务器）需要它
- **uv** —— 基于 `uvx` 的 MCP servers（Python 服务器）需要它

安装 MCP SDK：

```bash
pip install mcp
# or, if using uv:
uv pip install mcp
```

## 快速上手

在 `~/.hermes/config.yaml` 的 `mcp_servers` key 下添加 MCP servers：

```yaml
mcp_servers:
  time:
    command: "uvx"
    args: ["mcp-server-time"]
```

重启 Hermes Agent。启动时，它将：
1. 连接服务器
2. 发现可用工具
3. 使用前缀 `mcp_time_*` 注册这些工具
4. 将它们注入所有平台 toolsets

之后即可自然地使用这些工具——只需让智能体获取当前时间即可。

## 配置参考

`mcp_servers` 下的每个条目都以服务器名称映射到其配置。支持两种 transport 类型：**stdio**（基于命令）和 **HTTP**（基于 URL）。

### Stdio Transport（command + args）

```yaml
mcp_servers:
  server_name:
    command: "npx"             # (required) executable to run
    args: ["-y", "pkg-name"]   # (optional) command arguments, default: []
    env:                       # (optional) environment variables for the subprocess
      SOME_API_KEY: "value"
    timeout: 120               # (optional) per-tool-call timeout in seconds, default: 120
    connect_timeout: 60        # (optional) initial connection timeout in seconds, default: 60
```

### HTTP Transport（url）

```yaml
mcp_servers:
  server_name:
    url: "https://my-server.example.com/mcp"   # (required) server URL
    headers:                                     # (optional) HTTP headers
      Authorization: "Bearer sk-..."
    timeout: 180               # (optional) per-tool-call timeout in seconds, default: 120
    connect_timeout: 60        # (optional) initial connection timeout in seconds, default: 60
```

### 所有配置选项

| 选项              | 类型   | 默认值 | 说明                                              |
|-------------------|--------|---------|---------------------------------------------------|
| `command`         | string | --      | 要运行的可执行文件（stdio transport，必填）       |
| `args`            | list   | `[]`    | 传递给命令的参数                                  |
| `env`             | dict   | `{}`    | 为子进程额外提供的环境变量                        |
| `url`             | string | --      | 服务器 URL（HTTP transport，必填）                |
| `headers`         | dict   | `{}`    | 随每个请求发送的 HTTP headers                     |
| `timeout`         | int    | `120`   | 每次工具调用的超时时间（秒）                      |
| `connect_timeout` | int    | `60`    | 初始连接与发现过程的超时时间                      |

注意：服务器配置必须包含 `command`（stdio）或 `url`（HTTP）之一，不能同时包含二者。

## 工作原理

### 启动时发现

Hermes Agent 启动时，会在工具初始化期间调用 `discover_mcp_tools()`：

1. 读取 `mcp_servers`，其来源为 `~/.hermes/config.yaml`
2. 针对每台服务器，在专用后台 event loop 中建立连接
3. 初始化 MCP session，并调用 `list_tools()` 发现可用工具
4. 在 Hermes 工具注册表中注册每个工具

### 工具命名约定

MCP 工具使用以下命名模式注册：

```
mcp_{server_name}_{tool_name}
```

为了兼容 LLM API，名称中的连字符和点号会替换为下划线。

示例：
- 服务器 `filesystem`，工具 `read_file` → `mcp_filesystem_read_file`
- 服务器 `github`，工具 `list-issues` → `mcp_github_list_issues`
- 服务器 `my-api`，工具 `fetch.data` → `mcp_my_api_fetch_data`

### 自动注入

发现后，MCP 工具会自动注入所有 `hermes-*` 平台 toolsets（CLI、Discord、Telegram 等）。这意味着无需任何额外配置，每次对话都可以使用 MCP 工具。

### 连接生命周期

- 每台服务器都作为长时间运行的 asyncio Task，在后台 daemon thread 中运行
- 连接会在智能体进程的整个生命周期内保持
- 如果连接中断，会自动使用指数退避方式重连（最多重试 5 次，最大退避时间 60 秒）
- 智能体关闭时，所有连接都会优雅关闭

### 幂等性

`discover_mcp_tools()` 是幂等的——多次调用时，只会连接尚未连接的服务器。连接失败的服务器会在后续调用时重试。

## Transport 类型

### Stdio Transport

这是最常见的 transport。Hermes 将 MCP server 作为子进程启动，并通过 stdin/stdout 通信。

```yaml
mcp_servers:
  filesystem:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]
```

该子进程会继承一个**经过筛选的**环境（参见下方“安全性”部分），以及你在 `env` 中指定的所有变量。

### HTTP / StreamableHTTP Transport

适用于远程或共享 MCP servers。要求 `mcp` package 包含 HTTP client 支持（`mcp.client.streamable_http`）。

```yaml
mcp_servers:
  remote_api:
    url: "https://mcp.example.com/mcp"
    headers:
      Authorization: "Bearer sk-..."
```

如果已安装的 `mcp` 版本不支持 HTTP，该服务器将因 ImportError 而失败，其他服务器则会继续正常运行。

## 安全性

### 环境变量筛选

对于 stdio servers，Hermes 不会将完整的 shell 环境传递给 MCP 子进程。只会继承以下安全的基础变量：

- `PATH`、`HOME`、`USER`、`LANG`、`LC_ALL`、`TERM`、`SHELL`、`TMPDIR`
- 所有 `XDG_*` 变量

其他所有环境变量（API keys、tokens、secrets）都会被排除，除非你通过 `env` config key 显式添加。这可防止凭据意外泄露给不受信任的 MCP servers。

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      # Only this token is passed to the subprocess
      GITHUB_PERSONAL_ACCESS_TOKEN: "ghp_..."
```

### 错误消息中的凭据移除

如果 MCP 工具调用失败，错误消息中任何类似凭据的模式都会在显示给 LLM 前自动脱敏。覆盖范围包括：

- GitHub PATs（`ghp_...`）
- OpenAI 风格的 keys（`sk-...`）
- Bearer tokens
- 通用的 `token=`、`key=`、`API_KEY=`、`password=`、`secret=` 模式

## 故障排除

### “MCP SDK not available -- skipping MCP tool discovery”

未安装 `mcp` Python package。请安装：

```bash
pip install mcp
```

### “No MCP servers configured”

没有找到 `mcp_servers` key：`~/.hermes/config.yaml` 中未配置该 key，或其内容为空。请至少添加一台服务器。

### “Failed to connect to MCP server 'X'”

常见原因：
- **找不到命令**：`command` binary 不在 PATH 中。请确保已安装 `npx`、`uvx` 或相关命令。
- **找不到 package**：对于 npx servers，npm package 可能不存在，或者需要在 args 中添加 `-y` 才能自动安装。
- **超时**：服务器启动耗时过长。请增大 `connect_timeout`。
- **端口冲突**：对于 HTTP servers，URL 可能无法访问。

### “MCP server 'X' requires HTTP transport but mcp.client.streamable_http is not available”

你的 `mcp` package 版本不支持 HTTP client。请升级：

```bash
pip install --upgrade mcp
```

### 工具未出现

- 检查服务器是否列在 `mcp_servers` 下（而不是 `mcp` 或 `servers`）
- 确保 YAML 缩进正确
- 查看 Hermes Agent 启动日志中的连接消息
- 工具名称带有 `mcp_{server}_{tool}` 前缀——请查找这一模式

### 连接持续中断

客户端会使用指数退避方式最多重试 5 次（1 秒、2 秒、4 秒、8 秒、16 秒，最大 60 秒）。如果服务器从根本上无法访问，客户端会在 5 次尝试后放弃。请检查服务器进程和网络连接。

## 示例

### Time Server（uvx）

```yaml
mcp_servers:
  time:
    command: "uvx"
    args: ["mcp-server-time"]
```

注册 `mcp_time_get_current_time` 等工具。

### Filesystem Server（npx）

```yaml
mcp_servers:
  filesystem:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/documents"]
    timeout: 30
```

注册 `mcp_filesystem_read_file`、`mcp_filesystem_write_file`、`mcp_filesystem_list_directory` 等工具。

### 经过身份验证的 GitHub Server

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "ghp_xxxxxxxxxxxxxxxxxxxx"
    timeout: 60
```

注册 `mcp_github_list_issues`、`mcp_github_create_pull_request` 等工具。

### 远程 HTTP Server

```yaml
mcp_servers:
  company_api:
    url: "https://mcp.mycompany.com/v1/mcp"
    headers:
      Authorization: "Bearer sk-xxxxxxxxxxxxxxxxxxxx"
      X-Team-Id: "engineering"
    timeout: 180
    connect_timeout: 30
```

### 多台服务器

```yaml
mcp_servers:
  time:
    command: "uvx"
    args: ["mcp-server-time"]

  filesystem:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "ghp_xxxxxxxxxxxxxxxxxxxx"

  company_api:
    url: "https://mcp.internal.company.com/mcp"
    headers:
      Authorization: "Bearer sk-xxxxxxxxxxxxxxxxxxxx"
    timeout: 300
```

所有服务器提供的全部工具都会同时注册并可用。每台服务器的工具都以其名称为前缀，以避免冲突。

## Sampling（服务器发起的 LLM 请求）

Hermes 支持 MCP 的 `sampling/createMessage` capability——MCP servers 可以在工具执行期间，通过智能体请求 LLM completions。由此可实现智能体参与其中的工作流（数据分析、内容生成、决策制定）。

Sampling **默认启用**。可以按服务器配置：

```yaml
mcp_servers:
  my_server:
    command: "npx"
    args: ["-y", "my-mcp-server"]
    sampling:
      enabled: true           # default: true
      model: "gemini-3-flash" # model override (optional)
      max_tokens_cap: 4096    # max tokens per request
      timeout: 30             # LLM call timeout (seconds)
      max_rpm: 10             # max requests per minute
      allowed_models: []      # model whitelist (empty = all)
      max_tool_rounds: 5      # tool loop limit (0 = disable)
      log_level: "info"       # audit verbosity
```

服务器还可以在 sampling requests 中包含 `tools`，从而实现由工具增强的多轮工作流。`max_tool_rounds` config 可防止工具无限循环。系统会通过 `get_mcp_status()` 跟踪每台服务器的审计指标（requests、errors、tokens、tool use count）。

对于不受信任的服务器，请使用 `sampling: { enabled: false }` 禁用 sampling。

## 注意事项

- 从智能体视角看，MCP 工具以同步方式调用，但实际上在专用后台 event loop 上异步运行
- 工具结果以 JSON 返回，格式为 `{"result": "..."}` 或 `{"error": "..."}`
- 原生 MCP 客户端独立于 `mcporter`——二者可以同时使用
- 服务器连接是持久的，并由同一智能体进程中的所有对话共享
- 添加或删除服务器需要重启智能体（目前不支持热重载）
