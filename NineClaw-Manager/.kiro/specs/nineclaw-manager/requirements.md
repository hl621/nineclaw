# 需求文档

## 简介

本系统是一个基于 Python + FastAPI + PostgreSQL + Traefik 的多租户容器管理后端平台。系统允许用户创建、管理和访问基于容器的服务实例（如 nineclaw），通过 Traefik 实现自动服务发现和流量转发，并通过声明式状态管理（Reconcile Loop）确保容器实际状态与期望状态一致。系统提供统一的 API 网关，将外部请求路由到正确的容器服务端口，同时支持通过 Docker Socket 对容器进行文件操作和命令执行等细粒度管理。

## 术语表

- **Orchestrator**：容器编排后端系统，负责管理容器生命周期、服务发现和流量转发的核心平台
- **Tenant**：租户，系统中的一个用户实体，拥有独立的服务实例集合
- **Service_Template**：服务模板，定义了一类容器服务的固定配置（镜像、端口、卷挂载等），用户创建实例时基于模板生成
- **Service_Instance**：服务实例，由 Tenant 基于 Service_Template 创建的一个具体容器或容器组，拥有唯一标识符
- **Instance_ID**：服务实例的唯一标识符，用于在 API 路径中定位具体的服务实例
- **Desired_State**：期望状态，存储在数据库中的服务实例目标状态（如 running、stopped）
- **Actual_State**：实际状态，Docker 引擎报告的容器真实运行状态
- **Reconcile_Loop**：调和循环，Manager_Service 中的后台进程，持续比对 Desired_State 与 Actual_State 并自动修复差异
- **Traffic_Router**：流量路由器，基于 Traefik 的组件，负责将统一 API 请求转发到对应的 Service_Instance 端口
- **Docker_Client**：Docker 客户端，通过 Docker Socket 与 Docker 引擎通信的组件，执行容器操作
- **Service_Group**：服务组，由 docker compose 启动的一组关联容器，共同构成一个完整服务，通过项目名（project name）标识
- **Port_Prefix**：端口前缀，API 路径中用于区分同一 Service_Instance 或 Service_Group 内不同端口服务的特殊路径段
- **Event_Stream**：事件流，通过监听 Docker 事件（/events）实现的容器状态实时推送机制
- **Health_Check**：健康检查，用于判断容器服务是否处于可用状态的检测机制

## 需求

### 需求 1：服务模板管理

**用户故事：** 作为平台管理员，我希望能够定义和管理服务模板，以便租户可以基于模板快速创建标准化的服务实例。

#### 验收标准

1. THE Orchestrator SHALL 为每个 Service_Template 存储镜像名称、暴露端口列表、卷挂载配置、环境变量模板和资源限制配置
2. WHEN 创建 Service_Template 时，THE Orchestrator SHALL 验证镜像名称非空且端口列表至少包含一个有效端口
3. THE Orchestrator SHALL 支持在 Service_Template 中定义变量占位符，供 Tenant 创建实例时替换为自定义参数
4. WHEN Tenant 请求创建 Service_Instance 时，THE Orchestrator SHALL 使用 Tenant 提供的参数替换 Service_Template 中的变量占位符，生成最终的容器配置
5. THE Orchestrator SHALL 通过 API 提供 Service_Template 的列表查询功能，返回所有可用模板及其配置摘要

### 需求 2：服务实例生命周期管理

**用户故事：** 作为租户，我希望能够创建、启动、停止、重启和删除我的服务实例，以便灵活管理我的容器服务。

#### 验收标准

1. WHEN Tenant 发送创建请求并提供有效参数时，THE Orchestrator SHALL 基于指定的 Service_Template 创建一个新的 Service_Instance，并将 Desired_State 设置为 running
2. WHEN Tenant 发送停止请求并提供有效的 Instance_ID 时，THE Orchestrator SHALL 将该 Service_Instance 的 Desired_State 更新为 stopped
3. WHEN Tenant 发送启动请求并提供有效的 Instance_ID 时，THE Orchestrator SHALL 将该 Service_Instance 的 Desired_State 更新为 running
4. WHEN Tenant 发送重启请求并提供有效的 Instance_ID 时，THE Orchestrator SHALL 将该 Service_Instance 的 Desired_State 更新为 restarting，并在容器重启完成后自动将 Desired_State 恢复为 running
5. WHEN Tenant 发送删除请求并提供有效的 Instance_ID 时，THE Orchestrator SHALL 将该 Service_Instance 的 Desired_State 更新为 removed，并在容器删除完成后从数据库中移除该实例记录
6. IF Tenant 请求操作的 Instance_ID 不存在，THEN THE Orchestrator SHALL 返回 404 错误响应，包含明确的错误描述
7. IF Tenant 请求操作不属于自己的 Service_Instance，THEN THE Orchestrator SHALL 返回 403 错误响应，拒绝该操作
8. WHEN 创建 Service_Instance 时，THE Orchestrator SHALL 通过 Event_Stream 向客户端流式返回容器创建过程中的状态变化（如 creating、pulling、starting、running）

### 需求 3：服务实例状态查询

**用户故事：** 作为租户，我希望能够查询我的服务实例列表和详细状态，以便了解服务的运行情况。

#### 验收标准

1. WHEN Tenant 请求查询某类服务的实例列表时，THE Orchestrator SHALL 返回该 Tenant 拥有的所有该类 Service_Instance 的列表，包含 Instance_ID、名称、Desired_State 和 Actual_State
2. WHEN Tenant 请求查询某个 Service_Instance 的详情时，THE Orchestrator SHALL 返回该实例的完整信息，包括 Instance_ID、Service_Template 名称、创建时间、Desired_State、Actual_State（Created、Running、Paused、Restarting、Exited、Removing、Dead）、端口映射和资源使用情况
3. THE Orchestrator SHALL 通过监听 Docker 事件（/events）实时更新 Service_Instance 的 Actual_State，而非依赖轮询机制
4. IF Docker 引擎连接中断导致事件监听失败，THEN THE Orchestrator SHALL 记录错误日志并在连接恢复后自动重新建立事件监听

### 需求 4：声明式状态调和

**用户故事：** 作为平台运维人员，我希望系统能够自动检测并修复容器实际状态与期望状态的偏差，以确保服务的高可用性。

#### 验收标准

1. THE Reconcile_Loop SHALL 周期性地比对每个 Service_Instance 的 Desired_State 与 Actual_State
2. WHEN Desired_State 为 running 但 Actual_State 为 exited 或 dead 时，THE Reconcile_Loop SHALL 自动重新启动该 Service_Instance 的容器
3. WHEN Desired_State 为 stopped 但 Actual_State 为 running 时，THE Reconcile_Loop SHALL 自动停止该 Service_Instance 的容器
4. WHEN Desired_State 为 removed 但容器仍然存在时，THE Reconcile_Loop SHALL 自动删除该 Service_Instance 的容器并清理相关资源
5. THE Reconcile_Loop SHALL 在每次调和操作后记录操作日志，包含 Instance_ID、操作前状态、操作后状态和操作时间
6. IF 调和操作连续失败超过 3 次，THEN THE Reconcile_Loop SHALL 将该 Service_Instance 标记为 error 状态，并生成告警通知

### 需求 5：统一流量路由

**用户故事：** 作为租户，我希望通过统一的 API 网关访问我的服务实例，而无需知道容器的内部地址和端口，以简化服务调用。

#### 验收标准

1. WHEN Tenant 发送请求到 `/api/{service_type}/{instance_id}/{path}` 时，THE Traffic_Router SHALL 将请求转发到对应 Service_Instance 的默认服务端口
2. WHEN Tenant 发送请求到 `/api/{service_type}/{instance_id}/{port_prefix}/{path}` 时，THE Traffic_Router SHALL 根据 Port_Prefix 将请求转发到对应 Service_Instance 的指定端口
3. WHEN 新的 Service_Instance 创建并进入 running 状态时，THE Orchestrator SHALL 自动在 Traefik 中注册该实例的路由规则
4. WHEN Service_Instance 被删除或进入 stopped 状态时，THE Orchestrator SHALL 自动从 Traefik 中移除该实例的路由规则
5. THE Traffic_Router SHALL 在转发请求时保留原始请求的 HTTP 方法、请求头和请求体
6. IF 目标 Service_Instance 不处于 running 状态，THEN THE Traffic_Router SHALL 返回 503 错误响应，说明服务当前不可用
7. WHEN Service_Instance 属于一个 Service_Group 时，THE Traffic_Router SHALL 支持通过 Port_Prefix 将流量路由到该 Service_Group 中的不同容器

### 需求 6：容器文件与命令操作

**用户故事：** 作为租户，我希望能够通过 API 浏览容器内的文件、下载文件以及在容器中执行命令，以便进行服务的细粒度管理和调试。

#### 验收标准

1. WHEN Tenant 请求列出容器内指定目录的内容时，THE Docker_Client SHALL 返回该目录下的文件和子目录列表，包含名称、大小、修改时间和类型信息
2. WHEN Tenant 请求下载容器内指定文件时，THE Docker_Client SHALL 以二进制流的形式返回该文件的内容
3. WHEN Tenant 请求上传或替换容器内指定路径的文件时，THE Docker_Client SHALL 将文件写入容器的目标路径
4. WHEN Tenant 请求在容器中执行命令时，THE Docker_Client SHALL 在目标容器中执行该命令并返回标准输出和标准错误的内容
5. IF Tenant 请求操作的容器不处于 running 状态，THEN THE Docker_Client SHALL 返回 409 错误响应，说明容器当前状态不支持该操作
6. THE Orchestrator SHALL 将容器文件和命令操作的 API 路由绑定在与流量转发相同的路径前缀下，使其对前端呈现为统一的服务接口

### 需求 7：服务更新与滚动操作

**用户故事：** 作为租户，我希望能够通过 API 更新服务实例（如替换容器内文件后重启），并实时获取更新进度，以便在不中断服务的情况下完成服务升级。

#### 验收标准

1. WHEN Tenant 发送更新请求时，THE Orchestrator SHALL 按顺序执行文件替换、容器重启操作，并通过 Event_Stream 流式返回每个步骤的执行状态
2. WHEN 容器重启后，THE Orchestrator SHALL 持续检测 Health_Check 状态，直到服务恢复健康或超时
3. IF 更新过程中任一步骤失败，THEN THE Orchestrator SHALL 停止后续步骤执行，返回失败原因，并将 Service_Instance 标记为 error 状态
4. IF Health_Check 在指定超时时间内未通过，THEN THE Orchestrator SHALL 将该 Service_Instance 标记为 unhealthy 状态并通知 Tenant

### 需求 8：多租户隔离与安全

**用户故事：** 作为平台管理员，我希望系统能够确保租户之间的数据和操作完全隔离，以保障多租户环境下的安全性。

#### 验收标准

1. THE Orchestrator SHALL 在每个 API 请求中验证 Tenant 身份，确保 Tenant 仅能访问和操作自己拥有的 Service_Instance
2. THE Orchestrator SHALL 为每个 Service_Instance 分配独立的 Docker 网络命名空间或网络标签，防止不同 Tenant 的容器之间直接通信
3. WHEN Tenant 请求查询服务列表时，THE Orchestrator SHALL 仅返回属于该 Tenant 的 Service_Instance，过滤掉其他 Tenant 的数据
4. THE Orchestrator SHALL 对容器命令执行接口实施权限控制，仅允许执行预定义的安全命令集合或经过审核的命令

### 需求 9：服务组（Compose）管理

**用户故事：** 作为租户，我希望能够创建和管理由多个容器组成的服务组，以便部署需要多个协作容器的复杂服务。

#### 验收标准

1. WHEN Tenant 请求创建 Service_Group 时，THE Orchestrator SHALL 使用 docker compose 以指定的项目名启动一组关联容器
2. THE Orchestrator SHALL 将 Service_Group 中的所有容器作为一个整体进行生命周期管理（启动、停止、重启、删除）
3. WHEN Tenant 对 Service_Group 执行停止操作时，THE Orchestrator SHALL 停止该组内的所有容器
4. WHEN Tenant 对 Service_Group 执行删除操作时，THE Orchestrator SHALL 删除该组内的所有容器及其关联的网络和卷资源
5. THE Orchestrator SHALL 在 Service_Group 的状态查询中返回组内每个容器的独立状态信息

### 需求 10：数据持久化与配置管理

**用户故事：** 作为平台运维人员，我希望系统能够可靠地存储服务实例的元数据和配置信息，以便在系统重启后恢复所有服务状态。

#### 验收标准

1. THE Orchestrator SHALL 将所有 Service_Instance 的元数据（Instance_ID、Tenant 归属、Service_Template 引用、Desired_State、创建时间、配置参数）持久化存储到 PostgreSQL 数据库
2. WHEN Orchestrator 启动时，THE Reconcile_Loop SHALL 读取数据库中所有 Service_Instance 的 Desired_State，并与 Docker 引擎中的 Actual_State 进行比对和调和
3. THE Orchestrator SHALL 为每个 Service_Instance 存储其 Traefik 路由配置，确保系统重启后路由规则可自动恢复
4. IF 数据库连接失败，THEN THE Orchestrator SHALL 拒绝新的创建和删除请求，但允许对已运行容器的流量转发继续工作
