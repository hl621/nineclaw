# 配置、工具集与语音

使用 `hermes config edit` 或 `hermes config set section.key value` 编辑。
完整参考：https://hermes-agent.nousresearch.com/docs/user-guide/configuration

### 配置区段（最常用的 key）

| 区段 | Key 选项 |
|---------|-------------|
| `model` | `default`、`provider`、`base_url`、`api_key`、`context_length`、`aliases` |
| `agent` | `max_turns` (90)、`tool_use_enforcement`、`service_tier`、`verify_on_stop` |
| `terminal` | `backend` (local/docker/ssh/modal/daytona/singularity)、`cwd`、`timeout` (180) |
| `compression` | `enabled`、`threshold` (0.50)、`target_ratio` (0.20) |
| `display` | `skin`、`interface` (cli/tui)、`language`、`show_reasoning`、`show_cost`、`pet` |
| `approvals` | `mode` (smart/manual/off)、`timeout`、`cron_mode` |
| `stt` | `enabled`、`provider` (local/groq/openai/mistral/elevenlabs/deepinfra) |
| `tts` | `provider` (edge/elevenlabs/openai/minimax/mistral/neutts/gemini/piper/kittentts/deepinfra/xai) |
| `memory` | `memory_enabled`、`user_profile_enabled`、`provider`、`write_approval` |
| `security` | `redact_secrets`、`tirith_enabled`、`website_blocklist` |
| `delegation` | `model`、`provider`、`max_concurrent_children`、`max_iterations` (50)、`max_spawn_depth` |
| `checkpoints` | `enabled`、`max_snapshots` (50) |
| `curator` | `enabled`、`consolidate`（false，选择启用辅助模型整合）、`interval_hours`、`stale_after_days` |

`hermes config check` 会报告旧配置中缺失的区段。

### 工具集

可通过 `hermes tools`（交互式）或 `hermes tools enable/disable NAME` 启用/禁用。
完整清单：`TOOLSETS` dict 位于 `toolsets.py` 中（`_HERMES_CORE_TOOLS` 是大多数平台继承的默认集合）。

| 工具集 | 提供的功能 |
|---------|-----------------|
| `web` / `search` | Web 搜索与内容提取 / 仅搜索的子集 |
| `browser` | 浏览器自动化（Browserbase、Camofox 或本地 Chromium） |
| `terminal` | Shell 命令与进程管理 |
| `file` | 文件读取/写入/搜索/补丁 |
| `code_execution` | 沙箱化 Python 执行 |
| `coding` | 代码编辑辅助工具（基于 LSP） |
| `computer_use` | 桌面 GUI 控制（cua-driver） |
| `vision` | 图像分析 |
| `image_gen` | 图像生成和图生图编辑 |
| `video` / `video_gen` | 视频分析 / 视频生成 |
| `x_search` | X（Twitter）搜索（X OAuth 或 API key） |
| `tts` | 文本转语音 |
| `skills` | 技能浏览与管理 |
| `memory` | 跨会话持久记忆 |
| `session_search` | 搜索历史对话 |
| `context_engine` | 可插拔的上下文引擎 hook |
| `project` | 具名多文件夹工作区工具 |
| `delegation` | 子代理任务委派 |
| `cronjob` | 计划任务管理 |
| `clarify` | 向用户提出澄清问题 |
| `todo` | 会话内任务规划 |
| `kanban` | 多代理工作队列工具（仅向 worker 开放） |
| `debugging` | 额外的内省工具（默认关闭） |
| `safe` | 用于受限会话的最小低风险工具集 |
| `spotify`、`homeassistant`、`discord`、`discord_admin`、`feishu_doc`、`feishu_drive`、`yuanbao` | 服务集成（需具备对应凭据） |

工具变更会在 `/reset`（新会话）后生效——绝不会在对话中途生效，以保留 prompt caching。

## 语音

### STT（语音 → 文本）

来自消息平台的语音消息会自动转录。

```yaml
stt:
  enabled: true
  provider: local   # local (faster-whisper, free) | groq | openai | mistral | elevenlabs | deepinfra
  local:
    model: base     # tiny, base, small, medium, large-v3
```

自动检测优先级：本地 faster-whisper（`pip install faster-whisper`）→ Groq（`GROQ_API_KEY`，免费额度）→ OpenAI（`VOICE_TOOLS_OPENAI_KEY`）→ Mistral Voxtral（`MISTRAL_API_KEY`）。

### TTS（文本 → 语音）

| Provider | 环境变量 | 免费？ |
|----------|---------|-------|
| Edge TTS（默认） | None | 是 |
| ElevenLabs | `ELEVENLABS_API_KEY` | 有免费额度 |
| OpenAI | `VOICE_TOOLS_OPENAI_KEY` | 付费 |
| MiniMax | `MINIMAX_API_KEY` | 付费 |
| Mistral | `MISTRAL_API_KEY` | 付费 |
| Gemini | `GOOGLE_API_KEY` | 有免费额度 |
| NeuTTS / Piper / KittenTTS（本地） | None | 免费 |

语音命令：`/voice on`（语音对语音）、`/voice tts`（始终使用语音）、`/voice off`。
