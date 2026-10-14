# 实现计划：容器编排后端平台（Nineclaw Manager）— MVP

## 概述

MVP 聚焦两个核心能力：
1. **Nineclaw 容器生命周期管理**：创建、启动、停止、重启、删除 nineclaw 实例
2. **Traefik 接口聚合**：通过 Traefik 统一路由，将外部请求转发到各 nineclaw 实例的服务端口

后续迭代再实现：多租户隔离、服务模板变量渲染、服务组（compose）、容器文件操作、服务更新管道、声明式调和循环等。

## 已完成的基础设施

- [x] 项目目录结构和配置文件（pyproject.toml, requirements.txt, .env.example）
- [x] 数据库模型定义（Tenant, ServiceTemplate, ServiceInstance, ServiceGroup, ReconcileLog）
- [x] 数据库会话管理（async engine + session factory）
- [x] Alembic 迁移配置和初始 schema
- [x] 应用配置（pydantic-settings）

## Phase 1：Nineclaw 容器生命周期管理

- [x] 1. 实现 Docker 服务层（容器操作核心）
  - 创建 `app/services/docker_service.py`
  - 使用 aiodocker 通过 Docker Socket 与 Docker 引擎通信
  - 实现 `create_nineclaw(instance_id, config)` — 基于 nineclaw 镜像创建容器，配置端口映射、卷挂载、环境变量、资源限制、网络
  - 实现 `start_container(container_id)` — 启动已停止的容器
  - 实现 `stop_container(container_id)` — 停止运行中的容器
  - 实现 `restart_container(container_id)` — 重启容器
  - 实现 `remove_container(container_id, force=True)` — 删除容器（强制移除）
  - 实现 `get_container_status(container_id)` — 获取容器当前状态（running/exited/dead 等）
  - 实现 `list_containers(label_filter)` — 按标签过滤列出容器
  - 容器创建时打上标签 `orchestrator.instance_id={instance_id}` 用于关联
  - _需求: 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 2. 实现实例服务层（业务逻辑）
  - 创建 `app/services/instance_service.py`
  - 实现 `create_instance(name, tenant_id)` — 在数据库创建记录 + 调用 DockerService 创建并启动容器，分配端口，记录 container_id 和 port_mappings
  - 实现 `start_instance(instance_id)` — 更新 desired_state=running，调用 DockerService 启动容器
  - 实现 `stop_instance(instance_id)` — 更新 desired_state=stopped，调用 DockerService 停止容器
  - 实现 `restart_instance(instance_id)` — 调用 DockerService 重启容器
  - 实现 `delete_instance(instance_id)` — 调用 DockerService 删除容器，从数据库删除记录
  - 实现 `get_instance(instance_id)` — 查询实例详情（含实时容器状态）
  - 实现 `list_instances(tenant_id)` — 列出租户的所有实例
  - 端口分配策略：从配置的端口范围中自动分配可用端口
  - _需求: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2_

- [x] 3. 实现 Nineclaw 实例 API 路由
  - 创建 `app/api/routes/instances.py`
  - `POST /api/orchestrator/instances` — 创建 nineclaw 实例（参数：name, tenant_id）
  - `GET /api/orchestrator/instances` — 列出实例（query param: tenant_id）
  - `GET /api/orchestrator/instances/{instance_id}` — 获取实例详情
  - `POST /api/orchestrator/instances/{instance_id}/start` — 启动实例
  - `POST /api/orchestrator/instances/{instance_id}/stop` — 停止实例
  - `POST /api/orchestrator/instances/{instance_id}/restart` — 重启实例
  - `DELETE /api/orchestrator/instances/{instance_id}` — 删除实例
  - 统一错误处理：404（实例不存在）、409（状态冲突）、500（Docker 操作失败）
  - _需求: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2_

- [x] 4. 实现 Pydantic 请求/响应 Schema
  - 创建 `app/schemas/instance.py`
  - `InstanceCreate`: name (str), tenant_id (str, optional, default="default")
  - `InstanceResponse`: id, name, desired_state, actual_state, container_id, port_mappings, created_at
  - `InstanceDetail`: 扩展 InstanceResponse，增加 config, network_name, health_status, error_message
  - `InstanceList`: items (list[InstanceResponse]), total (int)
  - _需求: 2.1, 3.1, 3.2_

- [x] 5. 实现 FastAPI 应用入口和启动
  - 创建 `app/main.py` — FastAPI 应用实例，注册路由，配置 CORS
  - 创建 `app/api/__init__.py` 和 `app/api/routes/__init__.py`
  - 实现 lifespan 事件：启动时初始化 Docker 客户端连接，关闭时清理
  - 配置统一异常处理器
  - _需求: 全部_

- [x] 6. 检查点 — Phase 1 验证
  - 手动测试：通过 API 创建一个 nineclaw 实例，验证容器启动
  - 手动测试：停止、启动、重启、删除实例
  - 验证数据库记录与容器状态一致
  - 确保所有 API 端点正常工作

## Phase 2：Traefik 接口聚合

- [x] 7. 实现 Traefik 动态路由配置服务
  - 创建 `app/services/traefik_config.py`
  - 实现 `register_route(instance)` — 为实例生成 Traefik File Provider 格式的路由配置
  - 实现 `unregister_route(instance_id)` — 移除实例的路由配置
  - 实现 `rebuild_all_routes()` — 从数据库读取所有 running 实例，重建路由配置文件
  - 路由规则：`/api/nineclaw/{instance_id}/` → `http://{container_ip}:{port}/`
  - 支持 nineclaw 的三个端口（8642 API Server, 8643 WebUI, 8644）通过 path prefix 区分
  - 路由配置写入 Traefik 动态配置目录（YAML 格式），Traefik 自动热加载
  - _需求: 5.1, 5.2, 5.3, 5.4_

- [x] 8. 集成 Traefik 路由到实例生命周期
  - 在 `create_instance` 成功后调用 `register_route`
  - 在 `delete_instance` 时调用 `unregister_route`
  - 在 `stop_instance` 时调用 `unregister_route`（停止的实例不应路由流量）
  - 在 `start_instance` 时调用 `register_route`（重新注册路由）
  - _需求: 5.3, 5.4_

- [x] 9. 配置 Traefik 服务
  - 更新 `docker-compose.yml` 添加 Traefik 服务，挂载配置目录
  - 配置 Traefik 使用 File Provider 监听动态配置目录
  - 确保 Traefik 与 nineclaw 容器在同一 Docker 网络（qiyuan_net）
  - _需求: 5.1, 5.2, 5.5_

- [ ] 10. 检查点 — Phase 2 验证
  - 创建 nineclaw 实例后，验证通过 Traefik 统一入口可以访问该实例的各端口服务
  - 停止实例后，验证 Traefik 返回 503 或路由消失
  - 启动实例后，验证路由恢复
  - 删除实例后，验证路由被清理

## Phase 3：后续迭代（MVP 之后）

- [ ] 11. 声明式状态调和（Reconcile Loop）
  - 实现后台调和循环，周期性比对 desired_state 与 actual_state
  - 自动修复状态偏差（容器意外退出时自动重启）
  - 连续失败超过阈值标记为 error
  - _需求: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

- [ ] 12. Docker 事件监听
  - 监听 Docker 事件流，实时更新 actual_state
  - 自动重连机制
  - _需求: 3.3, 3.4_

- [ ] 13. JWT 认证与多租户隔离
  - 实现 JWT token 验证
  - 实现租户访问控制
  - 网络命名空间隔离
  - _需求: 8.1, 8.2, 8.3, 8.4_

- [ ] 14. 容器文件与命令操作
  - 列目录、下载文件、上传文件、执行命令
  - _需求: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

- [ ] 15. 服务模板管理
  - 模板 CRUD、变量渲染
  - _需求: 1.1, 1.2, 1.3, 1.4, 1.5_

- [ ] 16. 服务组（Compose）管理
  - docker compose 服务组的创建和生命周期管理
  - _需求: 9.1, 9.2, 9.3, 9.4, 9.5_

- [ ] 17. 服务更新管道
  - 文件替换 + 重启 + 健康检查
  - SSE 事件流返回进度
  - _需求: 7.1, 7.2, 7.3, 7.4_

## 备注

- MVP 阶段暂不实现 JWT 认证，API 直接接受 tenant_id 参数（默认 "default"）
- Nineclaw 容器配置硬编码为当前 docker-compose.yml 中的配置（镜像、端口、卷、环境变量）
- 端口分配从 8522 开始，每个实例分配 3 个连续端口（对应 8642/8643/8644）
- 所有 nineclaw 容器加入 qiyuan_net 网络
- Traefik 路由格式：`/api/nineclaw/{instance_id}/api/` → 8642, `/api/nineclaw/{instance_id}/webui/` → 8643, `/api/nineclaw/{instance_id}/ws/` → 8644
