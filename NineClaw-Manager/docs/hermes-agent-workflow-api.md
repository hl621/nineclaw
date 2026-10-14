# NineClaw Manager 工作流接口说明（DSL v2）

本文面向工作流编辑器、业务调用方和运维人员。运行边界、调度与安全模型见[Hermes Agent 工作流后端架构](hermes-agent-workflow-architecture.md)。

## 1. 通用约定

公开接口前缀：

```text
https://<manager>/v1/workflows
https://<manager>/v1/workflow-conversations
```

除文件下载和 SSE 外，成功响应统一为：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

当前租户由 `X-Tenant-ID` 决定；缺省时使用 Manager 默认租户。该 Header 用于可信内部网络的数据分区，不构成互联网认证机制。

创建资源返回 `201`，异步排队或异步转发返回 `202`，未单列的成功响应为 `200`。DSL 编译错误通常为 `422`，内容为稳定的 `{path, message}` 列表；临时校验接口以 `code: 1` 返回无效结果。过期的 `expected_draft_revision` 返回 `409`。

## 2. DSL v2

所有定义必须带 `schema_version: 2`。非该版本的定义、已发布快照和启动请求均不兼容，Manager 不提供迁移或回退执行。切换后发现的历史 v1 队列按 `WORKFLOW_DSL_V1_UNSUPPORTED` 失败收敛；已知远端 Run 只发起停止，不自动重派、监控输出或恢复。节点 ID 为 `type_<16位小写UUID4短ID>`，例如 `hermes_agent_0123456789ab4def`。`position` 保存画布坐标，`ui_metadata` 保存编辑器数据；两者不改变执行语义。

最小定义示例：

```json
{
  "schema_version": 2,
  "variables": {
    "approved": {
      "type": "boolean",
      "description": "审核是否通过"
    }
  },
  "limits": {
    "max_node_executions": 100,
    "max_artifact_bytes": 104857600,
    "max_hermes_runs": 10
  },
  "nodes": [
    {
      "id": "start_0123456789ab4def",
      "type": "start",
      "config": {},
      "position": {"x": 0, "y": 0}
    },
    {
      "id": "hermes_agent_0123456789ac4def",
      "type": "hermes_agent",
      "config": {
        "instance_id": "agent-instance-id",
        "prompt": "处理 Workspace 中的任务资料并上传结果。"
      },
      "position": {"x": 240, "y": 0}
    },
    {
      "id": "end_0123456789ad4def",
      "type": "end",
      "config": {},
      "position": {"x": 480, "y": 0}
    }
  ],
  "edges": [
    {
      "id": "edge-start-agent",
      "source_node_id": "start_0123456789ab4def",
      "source_port": "default",
      "target_node_id": "hermes_agent_0123456789ac4def",
      "target_port": "default"
    },
    {
      "id": "edge-agent-end",
      "source_node_id": "hermes_agent_0123456789ac4def",
      "source_port": "default",
      "target_node_id": "end_0123456789ad4def",
      "target_port": "default"
    }
  ]
}
```

### 2.1 节点语义

| 类型 | `config` 要点 | 行为 |
|---|---|---|
| `start` | 空对象。 | Manager 将 Run 输入物化为 `workflow-input.json`。 |
| `end` | 空对象。 | Manager 自动收集已选上游闭包中由成功 Attempt 产生的非系统 Artifact。 |
| `hermes_agent` | 必填 `instance_id`；必填 `prompt` 字符串或 `messages` 数组；可选 `model`、`temperature`、`max_tokens`。 | Manager 异步创建并监控 Hermes Run；成功返回物化为 `node-output.json`。 |
| `condition` | `mode`、唯一 `ports`；公式模式另有 `expression`、`true_port`、`false_port`。 | 只令选中端口的边继续。 |
| `loop` | `body`、`termination`、`limits.max_iterations`。 | 父图的原子复合节点；Body 是只有一个 End 的纯 DAG。 |

普通节点的输入端口和输出端口均为 `default`。Condition 的输出端口来自 `config.ports`。非 Start 节点必须有入边，End 不能有出边；所有节点必须从 Start 可达且能到达 End。

### 2.2 Artifact、变量与公式

Agent 间业务数据仅通过 Artifact Workspace 传递。节点进入 `ready` 时，Manager 固定已选上游祖先闭包、Loop 继承产物和变量快照。Agent 使用 Workspace MCP 列举与下载这些 Artifact，并上传自身产物；任务提示词不包含图结构或存储 URI。

`workflow-input.json` 的种类为 `system_input`，`node-output.json` 的种类为 `system_output`。两者可以在 Workspace 中读取，但不会成为业务 Run 的最终产物；Agent 上传的文件种类为 `user`。

变量定义位于顶层 `variables`。名称以字母开头，只能含字母、数字和下划线，长度不超过 128；类型为 `string`、`integer`、`number`、`boolean`、`object`、`array` 或 `null`。Agent 只能为已定义变量暂存值。成功 Attempt 提交变量，失败、取消、不确定或被替换的 Attempt 会丢弃其变量和控制决定。并行路径向同一节点合流时，同名不同值导致 `VARIABLE_CONFLICT`。

公式是 JSON AST，只能访问 `vars.*` 与 `system.*`。支持 `path`、`eq`、`ne`、`gt`、`gte`、`lt`、`lte`、`in`、`and`、`or`、`not`、`exists`。保存期校验 AST 形状；路径缺失和动态类型不匹配在运行期失败。

### 2.3 Condition 配置

公式 Condition 示例：

```json
{
  "mode": "formula",
  "ports": ["approved", "rework"],
  "expression": {
    "eq": [{"path": "vars.approved"}, true]
  },
  "true_port": "approved",
  "false_port": "rework"
}
```

公式真值选择 `true_port`，否则选择 `false_port`。

Agent Condition 示例：

```json
{
  "mode": "agent",
  "ports": ["approved", "rework"]
}
```

该模式必须只有一个直接 Hermes 上游。Manager 在上游 Agent Attempt 的非用户级 instructions 中提供一次性 token 与允许端口；Agent 通过 `condition_select_port` 提交端口。决定缺失、重复或不在允许集合中时，Condition 失败。

### 2.4 Loop 配置

`body` 是完整 DSL v2 文档，不能重新声明变量，也不能再包含 Loop，且必须只有一个 End。每轮至少执行一次，下一轮继承前轮的成功 Artifact 与该 End 的变量状态。

公式终止示例：

```json
{
  "termination": {
    "mode": "formula",
    "expression": {
      "eq": [{"path": "vars.done"}, true]
    }
  },
  "limits": {"max_iterations": 10}
}
```

公式结果为真时终止；为假时开始下一轮。达到 `max_iterations` 后仍需继续时，Loop 失败。

Agent 终止示例：

```json
{
  "termination": {
    "mode": "agent",
    "source_node_id": "hermes_agent_0123456789ae4def"
  },
  "limits": {"max_iterations": 10}
}
```

`source_node_id` 必须是 Body 内的 Hermes Agent。该 Agent 调用 `loop_continue`，`should_continue: true` 开始下一轮，`false` 结束 Loop。

### 2.5 保存期校验

创建、草稿替换和发布至少校验：DAG、端口、节点可达性、资源上限、变量定义、Condition、Loop、表达式和 Hermes 实例租户归属。实例可在保存时停止；实际派发时不可用会使节点以 `HERMES_INSTANCE_UNAVAILABLE` 失败。

## 3. 定义与目录接口

| 方法与路径 | 请求 | 行为 |
|---|---|---|
| `GET /v1/workflows/node-types` | 无。 | 从数据库查询五种节点类型定义，返回 `{items,total}`；目录缺失或损坏时返回 `503`。 |
| `GET /v1/workflows/agent-catalog` | 无。 | 查询当前租户的 Manager 配置安全快照。 |
| `GET /v1/workflows` | 无。 | 列出当前租户工作流摘要。 |
| `POST /v1/workflows` | `name`、可选 `description`、完整 `definition`。 | `201` 创建经编译校验的草稿。 |
| `GET /v1/workflows/{workflow_id}` | 无。 | 返回摘要、`draft_revision` 与 `draft_definition`。 |
| `PATCH /v1/workflows/{workflow_id}` | `expected_draft_revision`，以及 `name` 或 `description`。 | 更新元数据并递增 revision。 |
| `PUT /v1/workflows/{workflow_id}/draft` | `definition`、`expected_draft_revision`。 | 原子替换已校验草稿并递增 revision。 |
| `POST /v1/workflows/{workflow_id}/validate` | `{}` 或 `{ "definition": {...} }`。 | 不写入草稿；返回校验结果、校验和与编译计划。 |
| `POST /v1/workflows/{workflow_id}/publish` | `expected_draft_revision`。 | 再次校验并将草稿发布为当前最新可执行快照。 |

节点目录由 `workflow_node_type_definitions` 表提供，不读取 Hermes。每项含类型、名称、说明、端口、配置提示、默认配置与能力标记。数据库目录只服务编辑器；插入一条记录不会注册新的运行执行器。

Agent 目录返回实例名称、状态、模型、知识库、MCP、Skill 与快照时间。`snapshot_state: "unknown"` 表示历史实例没有 Manager 快照，不代表 Hermes 没有配置。响应不会返回 Provider Key、MCP Header、私有 URL、存储信息或 Bridge 凭据。

## 4. Run、调试与人工处置

| 方法与路径 | 请求 | 行为 |
|---|---|---|
| `POST /v1/workflows/{workflow_id}/runs` | `{ "input": { ... } }` | `202`。使用当前最新发布快照创建业务 Run。未发布返回 `409`。 |
| `POST /v1/workflows/{workflow_id}/node-debug-runs` | `{ "node_id": "hermes_agent_<短ID>", "input": { ... } }` | `202`。仅调试已发布定义中的顶层 Agent；不执行图中的其他节点。 |
| `GET /v1/workflows/{workflow_id}/runs` | `page`、`page_size`、可选 `status`。 | 分页列出 Run。 |
| `GET /v1/workflows/runs/{run_id}` | 无。 | 返回 Run 及节点状态、输入快照、输出与错误信息。 |
| `POST /v1/workflows/runs/{run_id}/cancel` | 无。 | 记录取消意图，终态以查询或事件为准。 |
| `POST /v1/workflows/node-runs/{node_run_id}/mark-failed` | `{ "reason": "..." }` | 将不确定节点人工收敛为失败。 |
| `POST /v1/workflows/node-runs/{node_run_id}/retry` | `{ "confirm_duplicate_side_effect_risk": true }` | 对不确定或停止结果不确定的节点人工重试。 |

已有 Run 保留其创建时绑定的内部发布快照。请求无法指定版本。业务 Run 与调试 Run 都没有工作流级总时长字段；Manager 持续监控已知 Hermes Run。

## 5. Workspace、Artifact 与事件

### 5.1 前端 Workspace 与 Artifact

| 方法与路径 | 请求 | 行为 |
|---|---|---|
| `GET /v1/workflows/runs/{run_id}/workspace` | 无。 | 按 Agent Node Run 返回 Scope、迭代、当前 Attempt 的可用 Artifact 元数据及成功业务 Run 的最终产物。 |
| `POST /v1/workflows/runs/{run_id}/artifacts` | `multipart/form-data`：`file`，可选 `node_run_id`。 | `201`。受控人工或业务侧上传。 |
| `GET /v1/workflows/runs/{run_id}/artifacts` | `page`、`page_size`、可选 `node_run_id`。 | 分页列出可用 Artifact。 |
| `GET /v1/workflows/runs/{run_id}/artifacts/{artifact_id}` | 无。 | 下载二进制内容。 |

前端接口不返回对象存储位置、执行标识、Attempt ID 或 Bridge 凭据。业务 Artifact 配额只计算 `user` Artifact；Manager 生成的系统 JSON 不占用该配额。

### 5.2 Run 生命周期事件

| 方法与路径 | 请求 | 行为 |
|---|---|---|
| `GET /v1/workflows/runs/{run_id}/events` | `after_sequence`，`limit` 为 `1`–`1000`。 | 拉取持久化生命周期事件。 |
| `GET /v1/workflows/runs/{run_id}/events/stream` | 可选 `after_sequence` 与 `Last-Event-ID`。 | SSE 从两者的较大值重放，并在 Run 终态后关闭。 |

客户端应保存最近的 `sequence`，重连时传递 `Last-Event-ID`，并按 `(run_id, sequence)` 去重。事件只包含 Manager 生命周期投影，不转发 Hermes token delta 或内部执行信息。

## 6. Runtime 内部 Workspace Bridge

以下接口只供 Runtime 镜像内预置的 MCP Bridge 调用，不供前端、浏览器或普通业务客户端调用。每个 MCP 工具均传入 `execution_id` 与 `workspace_token`；Runtime 将后者写入内部请求 Header。

| 方法与路径 | 输入 | 行为 |
|---|---|---|
| `GET /v1/workflow-workspace/artifacts` | 查询 `execution_id`。 | 列出当前冻结快照中的 Artifact。 |
| `GET /v1/workflow-workspace/artifacts/{artifact_id}` | 查询 `execution_id`。 | 下载已授权 Artifact。 |
| `POST /v1/workflow-workspace/uploads` | 表单 `execution_id`、`file`。 | 暂存当前 Attempt 的 Artifact。 |
| `POST /v1/workflow-workspace/uploads/{artifact_id}/commit` | 查询 `execution_id`。 | 原子提交暂存 Artifact。 |
| `DELETE /v1/workflow-workspace/uploads/{artifact_id}` | 查询 `execution_id`。 | 放弃暂存 Artifact。 |
| `GET /v1/workflow-workspace/variables` | 查询 `execution_id`。 | 列出定义、可见值和本 Attempt 暂存值。 |
| `GET /v1/workflow-workspace/variables/{name}`、`PUT /v1/workflow-workspace/variables/{name}` | 查询 `execution_id`；写入 `{ "value": ... }`。 | 读取或暂存一个变量。 |
| `POST /v1/workflow-workspace/variables/set-many` | 查询 `execution_id`；`{ "values": {...} }`。 | 原子暂存多个变量。 |
| `POST /v1/workflow-workspace/condition-selections` | `{ "execution_id", "token", "port" }`。 | 提交一次 Agent Condition 决定。 |
| `POST /v1/workflow-workspace/loop-decisions` | `{ "execution_id", "token", "should_continue" }`。 | 提交一次 Agent Loop 决定。 |

每个内部请求都需要 `Authorization: Bearer <实例派生令牌>`、`X-Nineclaw-Workspace-Instance` 与 `X-Nineclaw-Workspace-Token`。Manager 由 Bridge 密钥、实例 ID 和 `execution_id` 派生并校验 `workspace_token`，再查询关联的活跃 Attempt、Run 状态和输入快照；token 不匹配或无权限对象统一返回 `404`，失效 Attempt 返回 `409`。

Manager 在非用户级 instructions 中同时注入 `execution_id` 与不透明 `workspace_token`。Runtime 在本地校验 token 形状后原样转发；Manager 在数据库查询前校验 HMAC 绑定。`workspace_token` 及 Manager 注入的 `NINECLAW_MANAGER_URL`、`NINECLAW_WORKSPACE_*` 运行环境不持久化到实例配置，也不出现在公开响应、前端 Workspace、Agent 目录或 SSE 中。

Bridge 随后校验 Attempt 关联的发布快照。v1 Attempt 返回 `409` 和 `WORKFLOW_DSL_V1_UNSUPPORTED`，不允许列举、下载、上传 Artifact，或读写变量和控制决定。

## 7. 节点独立对话

| 方法与路径 | 请求 | 行为 |
|---|---|---|
| `POST /v1/workflows/{workflow_id}/nodes/{node_id}/conversations` | 可省略 body 或 `{}`。 | `201`。为当前最新发布快照中的顶层 Agent 创建独立会话。 |
| `GET /v1/workflow-conversations/{conversation_id}` | 无。 | 查询会话安全投影。 |
| `POST /v1/workflow-conversations/{conversation_id}/turns` | `{ "message": "..." }`，可选 `Idempotency-Key`。 | `202`。排队一个串行 Turn。 |
| `GET /v1/workflow-conversations/{conversation_id}/turns` | `after_turn_number`、`limit`。 | 按编号列出 Turn。 |
| `POST /v1/workflow-conversations/{conversation_id}/turns/{turn_id}/cancel` | 可省略 body 或 `{}`。 | `202`。记录取消意图。 |
| `POST /v1/workflow-conversations/{conversation_id}/turns/{turn_id}/mark-failed` | `{ "reason": "..." }`。 | 人工将不确定 Turn 收敛为失败。 |
| `POST /v1/workflow-conversations/{conversation_id}/turns/{turn_id}/approval` | `{ "decision": "allow" | "deny", "reason": "可选" }`。 | `202`。向 Hermes 转发审批决定。 |
| `GET /v1/workflow-conversations/{conversation_id}/events/stream` | 可选 `after_sequence` 与 `Last-Event-ID`。 | SSE 重放会话生命周期事件。 |

对话在创建时固定节点与 Hermes 会话，不随之后发布改变。每个会话同一时间只允许一个未终态 Turn。对话不创建 Workflow Attempt，不能访问工作流 Workspace、Artifact 或变量。

历史 v1 对话不能创建新 Turn 或向 Hermes 发送审批；已排队 Turn 失败收敛。若旧 Worker 已取得 Hermes `run_id`，Manager 记录该 ID 后只排队停止；停止成功后 Turn 标记为 `WORKFLOW_DSL_V1_UNSUPPORTED` 失败，停止结果不确定时保留人工处置状态。

## 8. 接入限制

- 不支持嵌套 Loop、动态 fan-out、跨 Run Artifact、全局变量或隐式合并变量值。
- Hermes 创建、停止或审批结果不确定时不会自动重试；需要人工处置。
- 公开响应不返回存储 URI、Bridge 凭据、`execution_id`、Hermes Run ID 或内部发布标识。
- 运行期仍会校验动态路径、表达式操作数类型和 Artifact 可用性；这些取决于实际运行数据。
