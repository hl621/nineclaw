# Nous Portal — 使用订阅为第三方应用进行身份验证

用户反复提出的问题：“应用 X（Karakeep、OpenWebUI、LibreChat、OpenViking、
LangChain 流水线、n8n 工作流等）能否使用我的 Nous Portal 订阅，而无需让我
复制粘贴 API key——最好能直接使用我已有的 Portal 登录状态？”

如实回答这个问题时，需要区分人们常常混为一谈的三个架构层次。在提出解决方案之前，
请按顺序逐层梳理。

---

## 第 1 层——这是 Hermes 插件，还是独立应用？

这是首先要回答的问题。尤其是“OpenViking”这个案例，
很容易让智能体判断失误。

| 使用形态 | 实际性质 | 身份验证路径 |
|---|---|---|
| **OpenViking memory plugin** (`plugins/memory/openviking/`) | 在 **Hermes 进程内部**运行的代码。它的 LLM 调用通过 Hermes 中已配置的 provider 发出。 | 如果用户的 Hermes 已配置为使用 Portal，它就已经在使用 Portal。无需额外操作。`OPENVIKING_API_KEY` 是 OpenViking *server* 自身的身份验证信息，不是 LLM 身份验证信息。 |
| **OpenViking the standalone server**（独立容器） | 独立的上下文数据库服务。如果它会自行调用 LLM，那就是一个独立的 HTTP 客户端。 | 与任何外部应用相同——参见下方第 2/3 层。 |
| **Karakeep、n8n、LibreChat、OpenWebUI、任何自托管应用** | 不同的进程，通常还运行在不同的机器上。它会自行向 `inference-api.nousresearch.com` 发起 HTTPS 调用。 | 参见下方第 2/3 层。 |

**应避免的误区**：不要把“通过 OAuth 登录 Portal”当成已在 Hermes 内部运行的
插件的解决方案。该 LLM 调用已经通过 Hermes 的 provider 配置完成身份验证。
插件自身的 server 身份验证（例如，用于调用 OpenViking REST API 的
`OPENVIKING_API_KEY`）与 Portal 无关。

---

## 第 2 层——对于真正的外部应用，Portal 实际提供了什么？

位于 `https://inference-api.nousresearch.com/v1` 的 Portal 是兼容 OpenAI 的
推理端点。它**只接受 bearer-token 身份验证**，具体可使用以下任一种方式：

1. 来自 `portal.nousresearch.com → API Keys` 的**静态 API key**，或
2. **x402-protocol payment header**（Solana USDC、beta、匿名、按请求付费）。

这里**没有通用的 OAuth 2.0 authorization server**。也不存在可供第三方应用
注册为 client 的“Sign in with Nous Portal”SSO。浏览器中的 Portal 登录
不会产生可扩展到同一台机器上其他应用的共享 cookie 或 session。

Hermes Agent 中确实有一种*感觉像* OAuth 的机制——`hermes login --provider nous`
会打开浏览器，用户登录后，token 会写入 `~/.hermes/auth.json`——但这是
**Hermes 专用的浏览器流程**。其底层会生成一项 credential，
Hermes 将其用作 bearer。Karakeep 等应用无法据此实现 client，因为从外部看来，
它根本不是一个公共 OAuth provider。

---

## 第 3 层——在 Portal 不做任何改动的情况下，能否弥合这一差距？

可以。可采用**本地 credential-broker proxy**模式。即使没有公共
OAuth 流程，用户机器上的应用也可以：

1. 从 `~/.hermes/auth.json` 读取 Hermes 现有的 Portal credential。
2. 在 `http://localhost:NNNN/v1` 暴露一个本地 OpenAI-compatible endpoint。
3. 将传入请求转发至 `inference-api.nousresearch.com/v1`，并附上该
   bearer。

然后让 Karakeep/OpenWebUI 等应用指向 `http://localhost:NNNN/v1`，并填写任意
占位 key。用户无需到处复制 Portal key——proxy 会复用 Hermes 已持有的 credential。

它在 Hermes 中可以放在以下位置：

- `gateway/platforms/api_server.py` 是一个先例——它通过本地 OpenAI-compatible endpoint
  暴露 agent，但请求会经过完整的 agent loop（包括 tool calls）。proxy 变体则是
  **纯推理透传**：不经过 agent loop，不使用 tools，只将 `/chat/completions`
  转发到 upstream，并附上用户已存储的 Portal bearer。
- 可以用约 150 行代码实现为新的 gateway adapter，或放在 `plugins/` 下作为 plugin。
- Token 刷新：如果 browser-OAuth flow 生成的是可刷新的 token，credential pool
  的刷新逻辑已经存在。如果它是长期有效的静态 bearer，实现会更加简单。

这确实非常实用，值得正式发布——它正是“让 $external_app 使用我的
Portal 订阅，但不需要复制粘贴 keys”这一问题的答案。

---

## Portal 上的真正 OAuth provider——什么时候值得提议？

仅当使用方是*另一个 Nous 第一方产品*时才值得提议（例如未来的 SDK、
Nous 品牌的扩展、需要按用户授权的 Discord-bot integration 等）。如果把它作为
“让 Karakeep 使用我的 Portal 订阅”的答案，就是在向用户推销一个无法惠及他们的功能：
即使 Portal 明天就发布 OAuth，Karakeep 的 LLM-provider 配置界面仍然只有 `base_url +
bearer_token`，没有 OAuth client、callback handler 或 token refresh。
OpenAI 生态已经以静态 bearer 为标准，下游应用不会为了适配新的身份验证流程而
重新设计其配置体验。

真正能在今天帮助用户、且 Portal 无需依赖第三方应用改动即可提供的功能包括：

- **带作用域、名称且可撤销的 API keys**，并显示最后使用时间。这样可以用所有现有应用
  都已支持的形式，提供人们期望从 OAuth 获得的同等体验（撤销已泄露的 key、查看哪些应用
  正在使用订阅、将某个 key 的作用域限定到特定 models）。
- **按 key 设置 rate limits**，这样可以限制高频应用，而不会占用用户为 Hermes 本身
  保留的请求余量。

---

## 沟通要点速查表（供下次使用）

当用户询问“$APP 能否使用我的 Portal 订阅”时：

1. 首先判断：它是 Hermes plugin（在 Hermes 内运行），还是独立应用？如果是 plugin，
   它已经通过 Hermes 的 provider 配置使用 Portal——问题解决。
2. 如果是独立应用：当前做法是粘贴来自 Portal → API Keys 的静态 API key。
   Base URL 为 `https://inference-api.nousresearch.com/v1`。Rate limits
   由订阅层级决定，并按 key 应用。
3. 如果用户反问“但我不想粘贴 key”——答案就是本地 broker proxy（第 3 层）。它值得构建，
   而不是一个需要列入 Portal 端 OAuth 路线图的问题。
4. 完全支持混合配置（“部分功能用 Portal，Hermes agent 本身则使用 OpenRouter/Ollama Cloud”）。
   Hermes 将 agent 的 provider/model 与 tool 侧的 LLM 调用视为彼此独立的配置；
   可以让它们分别指向不同 endpoint。

**关于 Tool Gateway 的说明**：Tool Gateway 公告中“无需单独账户，也无需来回管理 API key”的
宣传，特指当 Hermes 被配置为使用 Portal 作为 provider 时，Hermes Agent 的
*tools*（web search、browser、image gen、TTS）会通过 Portal 订阅运行。
这**并不**表示任意第三方应用都能继承 Portal 身份验证。
