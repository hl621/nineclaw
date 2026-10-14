# 任务与外部依赖隔离设计记录

本文档记录一次由 RAGFlow 异常引出的系统性问题、当前已经落地的修复、设计原则和后续路线。它的目标是让后续继续处理时，能快速恢复上下文，而不是重新从 RAG 页面卡死现象开始排查。

## 背景

用户在前端点击 `mcp`、`skill`、`model` 都能快速加载，但点击 `RAG` 后，由于 RAGFlow 配置不完整或后端连接不可用，请求进入长时间 pending。随后刷新页面，再点击 `mcp`、`skill`、`model`，这些原本无关的数据也加载不出来。

这不是单纯的前端卡死。排查后判断核心风险在后端：FastAPI 的异步路由中调用了同步的 RAGFlow HTTP 客户端，一旦同步调用长时间阻塞，就会占住事件循环或工作线程，使其他请求无法被及时处理。在默认单进程/单 worker 部署下，这种问题会被放大成“一个外部依赖挂住，拖住整个后端”。

用户明确指出：大型 SaaS 系统不应该因为一个用户或一个外部依赖的 pending 请求，让其他用户和其他功能全部等待。正确方向应该是任务隔离、依赖隔离、状态可观测、必要时降级，而不是只靠一个粗暴的总超时时间把任务杀掉。

## 设计原则

1. 长时间运行不等于异常。
   例如工作流、解析、部署、重建索引等任务可能本来就需要长时间运行，不能简单用总运行时长作为失败标准。

2. 连接失败和依赖不可达应该尽早暴露。
   如果请求没有被对方服务接住，或者依赖已经不可用，应尽快返回可理解的错误，而不是无限占住系统资源。

3. 外部依赖必须被隔离。
   RAGFlow、MCP 服务、模型供应商、Docker、Hermes 等都应该有各自的并发上限、排队策略、错误边界和降级策略。一个依赖慢或挂，不应该阻塞全站。

4. 后端事件循环不能被同步 I/O 阻塞。
   FastAPI 的 `async def` 路由里不能直接执行可能阻塞的同步网络调用。同步 SDK 或同步 HTTP client 应该被放到线程中执行，并通过 bulkhead 控制并发。

5. 保持现有前端接口兼容。
   当前阶段不是重写业务 API。已有 `/v1/knowledge` 等接口不能因为引入任务系统而让前端全部重对。

6. 为未来消息系统预留形态。
   用户希望未来系统状态可以推送给前端，所以任务抽象需要同时包含 job 状态和事件流，而不是只做后台 fire-and-forget。

## 当前已落地

### 1. Taskiq 内存任务基础设施

当前已经引入 `taskiq`，并先使用内存 broker：

- `JOB_BACKEND=memory`
- 后端启动时初始化 Taskiq broker
- 当前代码只支持 memory，避免误配成 redis 后产生不完整行为

新增模块：

- `app/jobs/broker.py`
- `app/jobs/models.py`
- `app/jobs/store.py`
- `app/jobs/service.py`
- `app/jobs/registry.py`
- `app/jobs/tasks.py`

这个基础设施提供了：

- job 创建
- job 状态记录
- job 事件记录
- job handler 注册
- job dispatch
- 取消请求标记
- 内存事件订阅

### 2. Job API 和事件流

新增接口位于 `app/api/routes/jobs.py`，路径为 `/v1/jobs`：

- `GET /v1/jobs`
- `POST /v1/jobs`
- `GET /v1/jobs/{job_id}`
- `POST /v1/jobs/{job_id}/cancel`
- `GET /v1/jobs/{job_id}/events`
- `GET /v1/jobs/{job_id}/events/stream`

其中 `events/stream` 使用 SSE，为后续“系统运作状态推送给用户”预留了接口形态。

注意：当前这套 job API 是新增能力，不替代已有业务接口。它是未来把长任务迁移出去的基础。

### 3. RAGFlow 外部依赖隔离

新增 `app/services/external_call_guard.py`，用于将同步外部调用隔离出去。

当前已经对 RAGFlow 后端的 knowledge 路由做了包裹：

- 同步 RAGFlow 调用会通过 `anyio.to_thread.run_sync` 放入线程执行
- 使用 `anyio.CapacityLimiter` 限制 RAGFlow 调用并发
- 如果 RAGFlow 调用 pending，它占住的是 RAGFlow 自己的隔离槽位和线程，不再直接占住 FastAPI 事件循环
- 如果 RAGFlow 并发已经打满，请求最多等待 `EXTERNAL_QUEUE_WAIT_TIMEOUT_SECONDS`，之后返回 `503`
- 没有设置总运行时长超时，因此不会因为“任务运行久”而强杀正常工作流

相关配置：

```env
EXTERNAL_RAGFLOW_MAX_CONCURRENCY=4
EXTERNAL_QUEUE_WAIT_TIMEOUT_SECONDS=1.0
```

这里的 `EXTERNAL_QUEUE_WAIT_TIMEOUT_SECONDS` 不是业务执行超时，而是“能不能拿到隔离槽位”的等待时间。它控制的是排队背压，不控制任务总运行时间。

### 4. 保持旧接口兼容

本次没有替换前端使用的旧接口。已有 knowledge 路由仍然保留原路径和响应形态，例如 `/v1/knowledge` 仍然是前端原来的调用方式。

本次改动的重点是把 RAGFlow 同步阻塞调用从事件循环里移出去，并加上依赖级 bulkhead。

## 当前效果

在当前阶段，目标不是彻底完成全系统任务化，而是先解决最危险的问题：

- RAGFlow 配置错误或连接挂住时，不应该继续拖死后端主事件循环
- 用户刷新网站后，`models`、`skill`、`mcp` 这类与 RAGFlow 无关的接口应该仍然有机会正常响应
- RAGFlow 请求如果过多，会被限制在 RAGFlow 自己的并发范围内
- 排队拿不到槽位时返回 `503`，前端可以提示“依赖繁忙/不可用”，而不是一直 pending

这是一种局部 bulkhead 修复，不是完整的高并发架构终态。

## 当前限制

1. 目前只对 RAGFlow knowledge 路由做了隔离。
   MCP、provider、Docker、Hermes 等其他外部依赖还没有统一接入 `ExternalCallGuard`。

2. 任务系统目前是内存模式。
   内存模式适合当前快速落地和验证抽象，但不具备跨进程、跨 worker、重启恢复能力。

3. 当前 job store 也是进程内存。
   如果未来开启多个 uvicorn worker，job 状态、事件订阅和 handler dispatch 不能依赖进程内存，需要迁移到 Redis/Postgres 等共享存储。

4. 还没有熔断和降级缓存。
   当前只有并发隔离和排队背压。后续需要在依赖连续失败时进入 open/half-open 状态，并对部分只读接口返回上一次可用快照。

5. 旧接口仍然可能承载长任务。
   例如 parse、reindex、deploy、远程发现等动作未来更适合迁移到 job 模式，让 HTTP 请求只负责提交任务和查询状态。

## 后续路线

### 阶段 1：扩大依赖隔离范围

将 `ExternalCallGuard` 从 RAGFlow 扩展到其他外部依赖：

- MCP server discovery / tool invocation
- provider health check / model list
- Docker remote calls
- Hermes gateway calls
- 其他同步 SDK 或同步 HTTP client

每类依赖应该有独立的并发上限，例如：

```env
EXTERNAL_RAGFLOW_MAX_CONCURRENCY=4
EXTERNAL_MCP_MAX_CONCURRENCY=8
EXTERNAL_PROVIDER_MAX_CONCURRENCY=8
EXTERNAL_DOCKER_MAX_CONCURRENCY=2
```

这样某个依赖打满时，只影响自己的功能域。

### 阶段 2：引入熔断和降级

对外部依赖增加状态机：

- closed：正常调用
- open：依赖连续失败，短时间内直接失败或返回降级结果
- half-open：少量探测请求验证依赖是否恢复

降级策略可以按接口类型区分：

- 只读列表类：返回上一次成功快照，并标记 stale
- 写入/部署类：拒绝提交，提示依赖不可用
- 健康检查类：返回 degraded 状态

这个阶段可以减少无意义的等待和重试风暴。

### 阶段 3：把长任务迁移到 job 模式

适合优先迁移的任务：

- RAG parse / reindex
- knowledge deploy
- MCP tool discovery
- provider model sync
- Docker instance setup
- Hermes 相关长流程

迁移后的模式：

1. 前端提交任务
2. 后端立即返回 `job_id`
3. 任务在后台执行
4. 前端通过 `/v1/jobs/{job_id}` 查询状态
5. 前端通过 `/v1/jobs/{job_id}/events/stream` 接收事件

这样 HTTP 请求不再承担长流程本身，用户也能看到系统正在做什么。

### 阶段 4：Redis 化

用户倾向使用 Redis，不采用 Temporal、Kafka、NATS 这类更重的系统。推荐未来演进方向：

- Redis 作为 queue / event stream / short-lived state
- Postgres 作为业务事实和长期记录
- Taskiq broker 从 memory 切换到 Redis
- job event 可用 Redis Streams 或类似结构承载

需要注意：当前代码还没有实现 `JOB_BACKEND=redis`，不要直接配置成 redis。

### 阶段 5：多 worker 和多实例安全

如果后续启用多个 uvicorn worker 或多容器部署，需要处理：

- job handler 注册在每个 worker 中的一致性
- job store 从内存迁移到共享存储
- SSE 事件订阅跨进程分发
- 依赖并发限制从进程内 limiter 升级为全局 limiter，或者接受“每进程限流”

这一步做完后，系统才能更接近大型 SaaS 的隔离模型。

## 配置说明

当前新增配置：

```env
JOB_BACKEND=memory
EXTERNAL_QUEUE_WAIT_TIMEOUT_SECONDS=1.0
EXTERNAL_RAGFLOW_MAX_CONCURRENCY=4
```

含义：

- `JOB_BACKEND`：当前只支持 `memory`
- `EXTERNAL_QUEUE_WAIT_TIMEOUT_SECONDS`：等待依赖隔离槽位的时间，不是任务执行超时
- `EXTERNAL_RAGFLOW_MAX_CONCURRENCY`：RAGFlow 同时执行的同步外部调用数量

后续可以把这些配置暴露给客户，让客户根据自己的部署规模和依赖稳定性调整。

## 已修改文件

任务系统：

- `app/jobs/broker.py`
- `app/jobs/models.py`
- `app/jobs/store.py`
- `app/jobs/service.py`
- `app/jobs/registry.py`
- `app/jobs/tasks.py`
- `app/api/routes/jobs.py`

外部依赖隔离：

- `app/services/external_call_guard.py`
- `app/api/routes/knowledge.py`

应用启动与配置：

- `app/main.py`
- `app/core/config.py`
- `env.example`
- `pyproject.toml`
- `requirements.txt`
- `uv.lock`

测试：

- `tests/test_jobs_api.py`
- `tests/test_knowledge_bulkhead.py`

注意：本地 `.env` 有未提交改动，但不属于这次设计改造的核心内容，后续处理时不要误删用户本地配置。

## 验证记录

已经运行过以下测试：

```bash
./.venv/bin/pytest tests/test_knowledge_bulkhead.py tests/test_knowledge_routes_design.py tests/test_knowledge_name_unique.py tests/test_jobs_api.py -q
```

结果：

```text
9 passed, 1 warning
```

warning 是已有的 FastAPI duplicate Operation ID 警告：

```text
Duplicate Operation ID deploy_knowledge_v1_knowledge_deploy_post
```

它不是本次隔离方案引入的问题。

## 下次继续时建议先看哪里

1. 先看 `app/services/external_call_guard.py`，理解当前 bulkhead 的行为。
2. 再看 `app/api/routes/knowledge.py` 中的 `run_knowledge_sync`，理解旧接口如何保持兼容。
3. 再看 `app/jobs/` 和 `app/api/routes/jobs.py`，理解 Taskiq/job/event 的基础形态。
4. 如果继续扩大范围，优先搜索同步外部调用：

```bash
rg "httpx.Client|requests\\.|subprocess|docker|Ragflow|MCP|Provider" app
```

5. 不要急着给所有任务加总超时。先判断它是“连接/排队问题”还是“合法长任务”，再决定使用连接超时、排队背压、任务状态、取消语义、熔断或降级。

