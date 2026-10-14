# 持久化与后台系统

有四套系统与主对话循环并行运行。这里提供快速参考；完整的开发者说明位于 `AGENTS.md`，面向用户的文档位于
`website/docs/user-guide/features/`。

### 委派（`delegate_task`）

生成一个拥有隔离上下文和独立终端会话的子代理。

- **单个：** `delegate_task(goal, context)`。
- **批量：** `delegate_task(tasks=[{goal, ...}, ...])` 会并行运行子代理，
  并受 `delegation.max_concurrent_children` 限制（默认值为 3）。
- **后台：** `delegate_task(background=true)` 会立即返回一个句柄，
  同时让父循环继续运行；子代理完成后，其结果会作为一个新轮次重新进入对话。
- **角色：** `leaf`（默认；不能再次委派）与 `orchestrator`
  （可以生成自己的工作代理，但受 `delegation.max_spawn_depth` 限制）。
- **不具备持久性。** 后台子代理仍局限于当前进程——如果父进程退出，
  子代理也会丢失。对于必须在该进程退出后继续存在的工作，请使用 `cronjob` 或
  `terminal(background=True, notify_on_complete=True)`。

配置：`delegation.*` 位于 `config.yaml` 中。

### Cron（计划任务）

持久化调度器——`cron/jobs.py` + `cron/scheduler.py`。可通过
`cronjob` 工具、`hermes cron` CLI（`list`、`add`、`edit`、
`pause`、`resume`、`run`、`remove`）或 `/cron` 斜杠命令进行操作。

- **调度方式：** 时长（`"30m"`、`"2h"`）、“every”短语
  （`"every monday 9am"`）、5 字段 cron（`"0 9 * * *"`）或 ISO 时间戳。
- **每个任务的可调参数：** `skills`、`model`/`provider` 覆盖项、`script`
  （运行前采集数据；`no_agent=True` 会让脚本构成整个任务）、`context_from`
  （将任务 A 的输出串接到任务 B）、`workdir`
  （在指定目录中运行，并加载其中的 `AGENTS.md` / `CLAUDE.md`），
  以及多平台投递。
- **不变量：** 每次运行在 3 分钟时强制中断；`.tick.lock` 文件可防止多个进程重复触发；
  cron 会话默认传入 `skip_memory=True`；cron 投递会用页眉/页脚封装，
  而不是镜像写入目标网关会话（从而保持角色交替不被破坏）。

用户文档：https://hermes-agent.nousresearch.com/docs/user-guide/features/cron

### Curator（技能生命周期）

对代理创建的技能执行后台维护。它会跟踪使用情况，将闲置技能标记为过期，
归档过期技能，并在运行前保留 tar.gz 备份，确保不会丢失任何内容。

- **CLI：** `hermes curator <verb>` — `status`、`usage`、`run`、`pause`、
  `resume`、`pin`、`unpin`、`archive`、`restore`、`list-archived`、`prune`、
  `backup`、`rollback`。
- **斜杠命令：** `/curator <subcommand>` 与 CLI 对应。
- **作用范围：** 只处理来源标记为 `created_by: "agent"` 的技能。
  内置技能和从 Hub 安装的技能均不可触碰。**绝不删除**——
  破坏性最强的操作也只是归档。已固定的技能不参与任何自动状态转换，
  也不会进入任何 LLM 审查流程。
- **成本：** 确定性的闲置检测/清理扫描免费运行。使用辅助模型
  “将重叠技能整合到统合技能中”的流程**默认关闭**——可通过
  `curator.consolidate: true` 或 `hermes curator run --consolidate` 启用。
  常规后台整理不消耗 token。
- **遥测：** `~/.hermes/skills/.usage.json` 中的伴随文件保存每个技能的
  `use_count`、`view_count`、`patch_count`、
  `last_activity_at`、`state`、`pinned`。

配置：`curator.*`（`enabled`、`interval_hours`、`min_idle_hours`、
`stale_after_days`、`archive_after_days`、`backup.*`）。
用户文档：https://hermes-agent.nousresearch.com/docs/user-guide/features/curator

### Kanban（多代理工作队列）

用于多 profile / 多 worker 协作的持久化 SQLite 看板。
用户通过 `hermes kanban <verb>` 操作；由调度器生成的 worker 会看到一组专用
`kanban_*` 工具，这组工具受 `HERMES_KANBAN_TASK` 控制，orchestrator profile
则可选择启用范围更广的 `kanban` 工具集。除非经过配置，普通会话中仍不会出现任何
`kanban_*` schema。

- **常用 CLI 动词：** `init`、`create`、`list`（别名 `ls`）、
  `show`、`assign`、`link`、`unlink`、`comment`、`complete`、`block`、
  `unblock`、`archive`、`tail`。较少使用的有：`watch`、`stats`、`runs`、
  `log`、`dispatch`、`daemon`、`gc`。
- **Worker/orchestrator 工具集：** `kanban_show`、`kanban_complete`、
  `kanban_block`、`kanban_heartbeat`、`kanban_comment`、`kanban_create`、
  `kanban_link`；在非调度器生成任务中显式启用 `kanban` 工具集的 profile，
  还会获得用于看板路由的 `kanban_list` 和 `kanban_unblock`。
- **调度器**默认在网关内部运行
  （`kanban.dispatch_in_gateway: true`）——回收过期认领、提升已就绪任务、
  以原子方式认领任务，并生成被指派的 profile。任务连续生成失败达到
  `failure_limit` 次后会被自动阻塞
  （默认值为 2；可通过 `kanban.failure_limit` 或每个任务的
  `max_retries` 配置）。
- **隔离：** 看板是硬边界（worker 的环境中会固定
  `HERMES_KANBAN_BOARD`）；tenant 是看板内部的软命名空间，
  用于隔离工作区路径和 memory key。

用户文档：https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban
