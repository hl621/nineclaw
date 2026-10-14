# Providers 与 Model Aliases

通过 `hermes model`（选择器）或 `hermes setup` 进行设置。随附的 35+ 个 provider profile 以
plugin 形式位于 `plugins/model-providers/` 下；同名的用户 plugin 会覆盖它们。
完整文档：https://hermes-agent.nousresearch.com/docs/integrations/providers

### Providers

| Provider | 身份验证 | Key 环境变量 |
|----------|------|----------------|
| openrouter | API key | `OPENROUTER_API_KEY` |
| anthropic | API key | `ANTHROPIC_API_KEY`（也支持 `CLAUDE_CODE_OAUTH_TOKEN`） |
| nous | OAuth device code | `hermes auth add nous`（或 `NOUS_API_KEY`） |
| openai-codex | OAuth | `hermes auth add openai-codex` |
| qwen-oauth | OAuth | `hermes auth add qwen-oauth` |
| minimax-oauth | OAuth | `hermes auth add minimax-oauth` |
| copilot | Token | `COPILOT_GITHUB_TOKEN` / `GH_TOKEN`（Copilot device flow——`gh auth login` 的 tokens **无法**使用） |
| copilot-acp | 外部 CLI | PATH 中的 Copilot CLI 或 `COPILOT_CLI_PATH` |
| gemini | API key | `GOOGLE_API_KEY` 或 `GEMINI_API_KEY` |
| xai | API key | `XAI_API_KEY`（也支持 SuperGrok OAuth） |
| deepseek | API key | `DEEPSEEK_API_KEY` |
| zai (GLM) | API key | `GLM_API_KEY` / `ZAI_API_KEY` |
| minimax / minimax-cn | API key | `MINIMAX_API_KEY` / `MINIMAX_CN_API_KEY` |
| kimi-coding / -cn | API key | `KIMI_API_KEY` / `KIMI_CN_API_KEY` |
| alibaba (+coding-plan) | API key | `DASHSCOPE_API_KEY` / `ALIBABA_CODING_PLAN_API_KEY` |
| xiaomi | API key | `XIAOMI_API_KEY` |
| huggingface | Token | `HF_TOKEN` |
| fireworks / novita / nvidia / deepinfra / gmi / arcee / stepfun / upstage / kilocode / ai-gateway / opencode-zen / opencode-go / ollama-cloud | API key | `<NAME>_API_KEY` |
| bedrock / vertex / azure-foundry | Cloud SDK / key | AWS SDK creds / Vertex ADC / `AZURE_FOUNDRY_API_KEY` |
| custom | 配置 | config.yaml 中的 `model.base_url` + `model.api_key` |

每个 provider pool 可包含多项 credential，并会自动轮换（`hermes auth`）。
主 provider 失败时使用的 fallback chain：`hermes fallback add|remove|list`。

### 用户自定义 model aliases

可在 CLI 和所有 gateway platform 中配合 `/model <name>` 使用。由
`hermes_cli/model_switch.py::resolve_alias()` 解析；用户 alias 会在
内置表**之前**检查，因此用户定义的 `sonnet`/`grok` 会覆盖内置 alias。

```yaml
# Full form
model_aliases:
  fav:
    model: claude-sonnet-4.6
    provider: anthropic
  local-qwen:
    model: qwen3.5:397b
    provider: custom
    base_url: "https://ollama.com/v1"

# Short form ("provider/model"), also via CLI:
#   hermes config set model.aliases.fav openrouter/anthropic/claude-sonnet-4.6
model:
  aliases:
    fav: openrouter/anthropic/claude-sonnet-4.6
```

`/model fav`——仅作用于当前 session；添加 `--global` 可持久化为默认值。

内置 aliases（根据当前 provider 的 catalog 进行解析）：`sonnet`、
`opus`、`haiku`、`claude`、`gpt5`、`gpt`、`codex`、`o3`、`o4`、`gemini`、
`deepseek`、`grok`、`llama`、`qwen`、`minimax`、`nemotron`、`kimi`、`glm`、
`step`、`mimo`、`trinity`。
