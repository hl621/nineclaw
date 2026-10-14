# 设计文档：容器编排后端平台（Nineclaw Manager）

## 概述

本设计文档描述一个多租户容器管理后端平台的技术架构。该平台基于 Python + FastAPI + PostgreSQL + Traefik 构建，为租户提供容器服务的全生命周期管理能力，包括：服务模板管理、服务实例创建/启停/删除、声明式状态调和、统一流量路由、容器文件与命令操作、服务组（Compose）管理，以及多租户隔离与安全。

系统采用声明式状态管理模型：用户通过 API 设置期望状态（Desired State），后台 Reconcile Loop 持续将容器实际状态（Actual State）向期望状态收敛。Traefik 作为反向代理，通过 Docker Provider 或 File Provider 实现自动服务发现和流量转发，使租户无需关心容器内部地址。

### 设计目标

- **声明式管理**：用户只需声明期望状态，系统自动调和实际状态
- **多租户隔离**：数据、网络、操作三层隔离，确保租户间互不干扰
- **统一入口**：通过 Traefik 提供统一 API 网关，屏蔽容器内部细节
- **可观测性**：通过 Docker 事件流实时推送状态变化，支持 SSE 事件流
- **可扩展性**：服务模板支持变量占位符，服务组支持 docker compose 编排

## 架构

### 整体架构图

```mermaid
graph TB
    Client[客户端 / 前端] -->|HTTP/HTTPS| Traefik[Traefik 反向代理]
    Traefik -->|/api/orchestrator/*| FastAPI[FastAPI 应用服务]
    Traefik -->|/api/{service_type}/{instance_id}/*| Container[目标容器服务端口]
    
    FastAPI -->|读写元数据| PostgreSQL[(PostgreSQL)]
    FastAPI -->|容器操作| DockerSocket[Docker Socket]
    FastAPI -->|路由配置| TraefikProvider[Traefik File Provider]
    
    subgraph "后台进程"
        ReconcileLoop[Reconcile Loop]
        EventListener[Docker Event Listener]
    end
    
    ReconcileLoop -->|比对状态 & 修复| DockerSocket
    ReconcileLoop -->|读写状态| PostgreSQL
    EventListener -->|监听 /events| DockerSocket
    EventListener -->|更新 Actual State| PostgreSQL
    
    FastAPI -->|SSE 事件流| Client
```

### 分层架构

系统采用分层架构，自上而下分为：

1. **API 层（FastAPI Routers）**：处理 HTTP 请求，参数校验，权限验证，返回响应
2. **服务层（Service Layer）**：业务逻辑编排，模板渲染，状态机管理
3. **数据访问层（Repository Layer）**：PostgreSQL 数据读写，使用 SQLModel ORM
4. **基础设施层（Infrastructure Layer）**：Docker Client（aiodocker）、Traefik 配置生成、事件监听

### 技术选型

| 组件 | 技术 | 理由 |
|------|------|------|
| Web 框架 | FastAPI | 原生 async 支持，自动 OpenAPI 文档，Pydantic 校验 |
| 数据库 | PostgreSQL | 成熟的关系型数据库，支持 JSONB 存储灵活配置 |
| ORM | SQLModel | 基于 Pydantic 的现代 ORM，同时支持类型注解和数据验证 |
| Docker 交互 | aiodocker | 异步 Docker SDK，通过 Unix Socket 通信 |
| 反向代理 | Traefik | 原生 Docker 支持，动态配置，自动服务发现 |
| 数据库迁移 | Alembic | SQLAlchemy 配套迁移工具 |
| 认证 | JWT (python-jose) | 无状态令牌，适合多租户场景 |
| 任务调度 | asyncio.Task | 内置异步任务，用于 Reconcile Loop 和事件监听 |

## 组件与接口

### 1. API 路由模块

#### 1.1 服务模板 API (`/api/orchestrator/templates`)

```python
# POST /api/orchestrator/templates
# 创建服务模板
async def create_template(template: TemplateCreate, tenant: Tenant = Depends(get_current_tenant)) -> TemplateResponse

# GET /api/orchestrator/templates
# 列出所有可用模板
async def list_templates(tenant: Tenant = Depends(get_current_tenant)) -> list[TemplateSummary]

# GET /api/orchestrator/templates/{template_id}
# 获取模板详情
async def get_template(template_id: UUID, tenant: Tenant = Depends(get_current_tenant)) -> TemplateResponse
```

#### 1.2 服务实例 API (`/api/orchestrator/instances`)

```python
# POST /api/orchestrator/instances
# 创建服务实例（返回 SSE 事件流）
async def create_instance(req: InstanceCreate, tenant: Tenant = Depends(get_current_tenant)) -> EventSourceResponse

# GET /api/orchestrator/instances
# 列出租户的服务实例
async def list_instances(service_type: str | None = None, tenant: Tenant = Depends(get_current_tenant)) -> list[InstanceSummary]

# GET /api/orchestrator/instances/{instance_id}
# 获取实例详情
async def get_instance(instance_id: str, tenant: Tenant = Depends(get_current_tenant)) -> InstanceDetail

# POST /api/orchestrator/instances/{instance_id}/start
async def start_instance(instance_id: str, tenant: Tenant = Depends(get_current_tenant)) -> InstanceResponse

# POST /api/orchestrator/instances/{instance_id}/stop
async def stop_instance(instance_id: str, tenant: Tenant = Depends(get_current_tenant)) -> InstanceResponse

# POST /api/orchestrator/instances/{instance_id}/restart
async def restart_instance(instance_id: str, tenant: Tenant = Depends(get_current_tenant)) -> InstanceResponse

# DELETE /api/orchestrator/instances/{instance_id}
async def delete_instance(instance_id: str, tenant: Tenant = Depends(get_current_tenant)) -> InstanceResponse
```

#### 1.3 容器文件与命令 API (`/api/orchestrator/instances/{instance_id}/container`)

```python
# GET /api/orchestrator/instances/{instance_id}/container/files?path=/some/dir
# 列出容器内目录
async def list_container_files(instance_id: str, path: str = "/", tenant: Tenant = Depends(get_current_tenant)) -> list[FileEntry]

# GET /api/orchestrator/instances/{instance_id}/container/files/download?path=/some/file
# 下载容器内文件
async def download_container_file(instance_id: str, path: str, tenant: Tenant = Depends(get_current_tenant)) -> StreamingResponse

# PUT /api/orchestrator/instances/{instance_id}/container/files?path=/some/file
# 上传/替换容器内文件
async def upload_container_file(instance_id: str, path: str, file: UploadFile, tenant: Tenant = Depends(get_current_tenant)) -> FileUploadResponse

# POST /api/orchestrator/instances/{instance_id}/container/exec
# 在容器中执行命令
async def exec_in_container(instance_id: str, req: ExecRequest, tenant: Tenant = Depends(get_current_tenant)) -> ExecResponse
```

#### 1.4 服务更新 API

```python
# POST /api/orchestrator/instances/{instance_id}/update
# 执行服务更新（文件替换 + 重启，返回 SSE 事件流）
async def update_instance(instance_id: str, req: UpdateRequest, tenant: Tenant = Depends(get_current_tenant)) -> EventSourceResponse
```

#### 1.5 服务组 API (`/api/orchestrator/groups`)

```python
# POST /api/orchestrator/groups
# 创建服务组
async def create_group(req: GroupCreate, tenant: Tenant = Depends(get_current_tenant)) -> GroupResponse

# GET /api/orchestrator/groups/{group_id}
# 获取服务组详情（含各容器状态）
async def get_group(group_id: str, tenant: Tenant = Depends(get_current_tenant)) -> GroupDetail

# POST /api/orchestrator/groups/{group_id}/stop
async def stop_group(group_id: str, tenant: Tenant = Depends(get_current_tenant)) -> GroupResponse

# POST /api/orchestrator/groups/{group_id}/restart
async def restart_group(group_id: str, tenant: Tenant = Depends(get_current_tenant)) -> GroupResponse

# DELETE /api/orchestrator/groups/{group_id}
async def delete_group(group_id: str, tenant: Tenant = Depends(get_current_tenant)) -> GroupResponse
```

#### 1.6 统一流量路由

流量路由通过 Traefik 实现，不经过 FastAPI 应用层。Orchestrator 负责在实例状态变化时动态更新 Traefik 路由配置。

路由规则格式：
- 默认端口：`/api/{service_type}/{instance_id}/{path}` → `http://container_ip:{default_port}/{path}`
- 指定端口：`/api/{service_type}/{instance_id}/{port_prefix}/{path}` → `http://container_ip:{mapped_port}/{path}`
- 服务组端口：`/api/{service_type}/{group_id}/{port_prefix}/{path}` → `http://group_container_ip:{mapped_port}/{path}`

### 2. 服务层组件

#### 2.1 TemplateService

负责服务模板的 CRUD 操作和模板变量渲染。

```python
class TemplateService:
    async def create_template(self, data: TemplateCreate) -> ServiceTemplate
    async def get_template(self, template_id: UUID) -> ServiceTemplate | None
    async def list_templates(self) -> list[ServiceTemplate]
    def render_template(self, template: ServiceTemplate, params: dict[str, str]) -> ContainerConfig
```

`render_template` 方法将模板中的变量占位符（如 `${CUSTOM_PORT}`、`${API_KEY}`）替换为租户提供的参数值，生成最终的容器运行配置。

#### 2.2 InstanceService

负责服务实例的生命周期管理和状态转换。

```python
class InstanceService:
    async def create_instance(self, tenant_id: str, template_id: UUID, params: dict) -> AsyncGenerator[SSEEvent, None]
    async def start_instance(self, instance_id: str, tenant_id: str) -> ServiceInstance
    async def stop_instance(self, instance_id: str, tenant_id: str) -> ServiceInstance
    async def restart_instance(self, instance_id: str, tenant_id: str) -> ServiceInstance
    async def delete_instance(self, instance_id: str, tenant_id: str) -> None
    async def get_instance(self, instance_id: str, tenant_id: str) -> ServiceInstance
    async def list_instances(self, tenant_id: str, service_type: str | None = None) -> list[ServiceInstance]
    async def update_instance(self, instance_id: str, tenant_id: str, req: UpdateRequest) -> AsyncGenerator[SSEEvent, None]
```

#### 2.3 ReconcileService

后台调和循环，周期性比对 Desired State 与 Actual State。

```python
class ReconcileService:
    def __init__(self, interval_seconds: int = 30):
        self._interval = interval_seconds
        self._failure_counts: dict[str, int] = {}  # instance_id -> consecutive failure count
    
    async def run_loop(self) -> None:
        """主调和循环，作为 asyncio.Task 运行"""
    
    async def reconcile_instance(self, instance: ServiceInstance) -> ReconcileResult:
        """对单个实例执行调和操作"""
    
    async def _handle_reconcile_failure(self, instance_id: str, error: Exception) -> None:
        """处理调和失败，超过 3 次标记为 error"""
```

#### 2.4 DockerService

封装 Docker Socket 操作。

```python
class DockerService:
    async def create_container(self, config: ContainerConfig) -> str  # returns container_id
    async def start_container(self, container_id: str) -> None
    async def stop_container(self, container_id: str) -> None
    async def restart_container(self, container_id: str) -> None
    async def remove_container(self, container_id: str, force: bool = False) -> None
    async def get_container_status(self, container_id: str) -> ContainerStatus
    async def list_directory(self, container_id: str, path: str) -> list[FileEntry]
    async def download_file(self, container_id: str, path: str) -> AsyncGenerator[bytes, None]
    async def upload_file(self, container_id: str, path: str, content: bytes) -> None
    async def exec_command(self, container_id: str, command: list[str]) -> ExecResult
    async def pull_image(self, image: str) -> AsyncGenerator[dict, None]
```

#### 2.5 DockerEventService

监听 Docker 事件流，实时更新容器状态。

```python
class DockerEventService:
    async def start_listening(self) -> None:
        """启动事件监听，作为 asyncio.Task 运行"""
    
    async def _handle_event(self, event: dict) -> None:
        """处理单个 Docker 事件，更新数据库中的 Actual State"""
    
    async def _reconnect(self) -> None:
        """连接中断后自动重连"""
```

#### 2.6 TraefikConfigService

管理 Traefik 动态路由配置。

```python
class TraefikConfigService:
    async def register_route(self, instance: ServiceInstance) -> None:
        """为实例注册 Traefik 路由规则"""
    
    async def unregister_route(self, instance_id: str) -> None:
        """移除实例的 Traefik 路由规则"""
    
    async def rebuild_all_routes(self) -> None:
        """系统启动时重建所有路由（从数据库恢复）"""
    
    def _generate_route_config(self, instance: ServiceInstance) -> dict:
        """生成 Traefik File Provider 格式的路由配置"""
```

#### 2.7 GroupService

管理服务组（docker compose）的生命周期。

```python
class GroupService:
    async def create_group(self, tenant_id: str, req: GroupCreate) -> ServiceGroup
    async def stop_group(self, group_id: str, tenant_id: str) -> ServiceGroup
    async def restart_group(self, group_id: str, tenant_id: str) -> ServiceGroup
    async def delete_group(self, group_id: str, tenant_id: str) -> None
    async def get_group(self, group_id: str, tenant_id: str) -> ServiceGroup
```

### 3. 认证与权限中间件

```python
async def get_current_tenant(request: Request) -> Tenant:
    """从 JWT token 中提取并验证租户身份"""

class TenantAccessMiddleware:
    """确保租户只能访问自己的资源"""
```

## 数据模型

### PostgreSQL 表结构

#### service_templates 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID (PK) | 模板唯一标识 |
| name | VARCHAR(255) | 模板名称 |
| image | VARCHAR(512) | Docker 镜像名称 |
| ports | JSONB | 暴露端口列表，如 `[{"container_port": 8080, "prefix": "web"}, {"container_port": 3000, "prefix": "api"}]` |
| volumes | JSONB | 卷挂载配置，如 `[{"host_path": "/data", "container_path": "/app/data"}]` |
| env_template | JSONB | 环境变量模板，如 `{"API_KEY": "${API_KEY}", "PORT": "8080"}` |
| resource_limits | JSONB | 资源限制，如 `{"memory": "2G", "cpus": "1.0"}` |
| variables | JSONB | 可替换变量定义，如 `[{"name": "API_KEY", "required": true, "default": null}]` |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

#### service_instances 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(64) (PK) | 实例唯一标识（Instance_ID） |
| tenant_id | VARCHAR(64) (FK, INDEX) | 所属租户 |
| template_id | UUID (FK) | 基于的服务模板 |
| name | VARCHAR(255) | 实例名称 |
| desired_state | VARCHAR(32) | 期望状态：running, stopped, restarting, removed |
| actual_state | VARCHAR(32) | 实际状态：created, running, paused, restarting, exited, removing, dead |
| container_id | VARCHAR(128) | Docker 容器 ID |
| config | JSONB | 渲染后的最终容器配置 |
| port_mappings | JSONB | 端口映射，如 `{"web": {"host_port": 32001, "container_port": 8080}}` |
| network_name | VARCHAR(255) | 分配的 Docker 网络名称 |
| group_id | VARCHAR(64) (FK, nullable) | 所属服务组（如有） |
| error_message | TEXT (nullable) | 最近一次错误信息 |
| health_status | VARCHAR(32) | 健康状态：healthy, unhealthy, unknown |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

#### service_groups 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(64) (PK) | 服务组唯一标识 |
| tenant_id | VARCHAR(64) (FK, INDEX) | 所属租户 |
| name | VARCHAR(255) | 服务组名称 |
| project_name | VARCHAR(255) | docker compose 项目名 |
| compose_config | JSONB | compose 配置内容 |
| desired_state | VARCHAR(32) | 期望状态 |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

#### tenants 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(64) (PK) | 租户唯一标识 |
| name | VARCHAR(255) | 租户名称 |
| api_key_hash | VARCHAR(512) | API Key 哈希值 |
| allowed_commands | JSONB | 允许执行的命令白名单 |
| created_at | TIMESTAMP | 创建时间 |
| is_active | BOOLEAN | 是否启用 |

#### reconcile_logs 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGSERIAL (PK) | 日志 ID |
| instance_id | VARCHAR(64) (FK, INDEX) | 关联实例 |
| action | VARCHAR(64) | 操作类型：start, stop, remove, restart |
| state_before | VARCHAR(32) | 操作前状态 |
| state_after | VARCHAR(32) | 操作后状态 |
| success | BOOLEAN | 是否成功 |
| error_message | TEXT (nullable) | 错误信息 |
| created_at | TIMESTAMP | 操作时间 |

### SQLAlchemy 模型

```python
class ServiceTemplate(Base):
    __tablename__ = "service_templates"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    image: Mapped[str] = mapped_column(String(512), nullable=False)
    ports: Mapped[dict] = mapped_column(JSONB, nullable=False)
    volumes: Mapped[dict] = mapped_column(JSONB, default=list)
    env_template: Mapped[dict] = mapped_column(JSONB, default=dict)
    resource_limits: Mapped[dict] = mapped_column(JSONB, default=dict)
    variables: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

class ServiceInstance(Base):
    __tablename__ = "service_instances"
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True)
    template_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("service_templates.id"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    desired_state: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    actual_state: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    container_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    port_mappings: Mapped[dict] = mapped_column(JSONB, default=dict)
    network_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    group_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("service_groups.id"), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    health_status: Mapped[str] = mapped_column(String(32), default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    
    tenant: Mapped["Tenant"] = relationship(back_populates="instances")
    template: Mapped["ServiceTemplate"] = relationship()
    group: Mapped["ServiceGroup | None"] = relationship(back_populates="instances")

class ServiceGroup(Base):
    __tablename__ = "service_groups"
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    compose_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    desired_state: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    
    instances: Mapped[list["ServiceInstance"]] = relationship(back_populates="group")

class Tenant(Base):
    __tablename__ = "tenants"
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    allowed_commands: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    instances: Mapped[list["ServiceInstance"]] = relationship(back_populates="tenant")

class ReconcileLog(Base):
    __tablename__ = "reconcile_logs"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(String(64), ForeignKey("service_instances.id"), index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    state_before: Mapped[str] = mapped_column(String(32), nullable=False)
    state_after: Mapped[str] = mapped_column(String(32), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
```

### Pydantic 请求/响应模型

```python
# --- 模板相关 ---
class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    image: str = Field(..., min_length=1)
    ports: list[PortConfig] = Field(..., min_length=1)
    volumes: list[VolumeConfig] = Field(default_factory=list)
    env_template: dict[str, str] = Field(default_factory=dict)
    resource_limits: ResourceLimits | None = None
    variables: list[VariableDefinition] = Field(default_factory=list)

class PortConfig(BaseModel):
    container_port: int = Field(..., ge=1, le=65535)
    prefix: str = Field(..., pattern=r"^[a-z][a-z0-9-]*$")

class VariableDefinition(BaseModel):
    name: str = Field(..., pattern=r"^[A-Z_][A-Z0-9_]*$")
    required: bool = True
    default: str | None = None

# --- 实例相关 ---
class InstanceCreate(BaseModel):
    template_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    params: dict[str, str] = Field(default_factory=dict)

class InstanceDetail(BaseModel):
    id: str
    name: str
    template_name: str
    desired_state: str
    actual_state: str
    port_mappings: dict
    health_status: str
    created_at: datetime
    resource_usage: ResourceUsage | None = None

# --- 容器操作相关 ---
class ExecRequest(BaseModel):
    command: list[str] = Field(..., min_length=1)

class ExecResponse(BaseModel):
    exit_code: int
    stdout: str
    stderr: str

# --- 服务组相关 ---
class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    compose_config: dict  # docker compose YAML 内容（已解析为 dict）
    project_name: str = Field(..., pattern=r"^[a-z][a-z0-9-]*$")
```


## 正确性属性（Correctness Properties）

*属性（Property）是一种在系统所有有效执行中都应成立的特征或行为——本质上是对系统应做什么的形式化陈述。属性是人类可读规范与机器可验证正确性保证之间的桥梁。*

### Property 1: 模板存储往返一致性（Template Storage Round-Trip）

*For any* 有效的 ServiceTemplate（包含非空镜像名、至少一个端口、任意卷挂载配置、环境变量模板和资源限制），将其存储到数据库后再读取，所有字段应与原始值完全一致。

**Validates: Requirements 1.1**

### Property 2: 模板创建输入验证（Template Validation）

*For any* 模板创建请求，当且仅当镜像名称非空且端口列表至少包含一个有效端口（端口号在 1-65535 范围内）时，创建操作应成功；否则应被拒绝并返回验证错误。

**Validates: Requirements 1.2**

### Property 3: 模板变量渲染完整性（Template Variable Rendering）

*For any* 包含变量占位符的 ServiceTemplate 和一组覆盖所有必需变量的参数字典，调用 `render_template` 后生成的容器配置中不应包含任何未替换的 `${...}` 占位符，且每个变量的值应等于参数字典中对应的值。

**Validates: Requirements 1.4**

### Property 4: 生命周期操作状态转换正确性（Lifecycle State Transition）

*For any* 有效的 ServiceInstance 和生命周期操作（create → running, stop → stopped, start → running, restart → restarting, delete → removed），执行操作后实例的 desired_state 应等于该操作对应的目标状态。

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

### Property 5: 不存在的实例返回 404（Non-Existent Instance 404）

*For any* 不存在于系统中的 instance_id，对其执行任何生命周期操作（start、stop、restart、delete、查询详情）应返回 404 错误响应。

**Validates: Requirements 2.6**

### Property 6: 跨租户访问隔离（Cross-Tenant Access Isolation）

*For any* 属于 Tenant A 的 ServiceInstance，当 Tenant B（B ≠ A）尝试对其执行任何操作时，系统应返回 403 错误响应。

**Validates: Requirements 2.7, 8.1**

### Property 7: 租户实例列表过滤正确性（Tenant Instance List Filtering）

*For any* 包含多个租户和多个实例的系统状态，当 Tenant 查询实例列表时，返回的每一个实例都应属于该 Tenant，且不应遗漏该 Tenant 拥有的任何实例。

**Validates: Requirements 3.1, 8.3**

### Property 8: 实例详情数据完整性（Instance Detail Completeness）

*For any* 已创建的 ServiceInstance，查询其详情时返回的数据应包含 Instance_ID、模板名称、创建时间、desired_state、actual_state、端口映射和资源使用情况，且各字段值与数据库中存储的值一致。

**Validates: Requirements 3.2, 10.1**

### Property 9: 调和决策正确性（Reconcile Decision Correctness）

*For any* ServiceInstance 的 (desired_state, actual_state) 状态对，调和决策函数应产生正确的操作：desired=running 且 actual∈{exited, dead} 时产生 start 操作；desired=stopped 且 actual=running 时产生 stop 操作；desired=removed 且容器存在时产生 remove 操作；desired_state 与 actual_state 一致时不产生任何操作。

**Validates: Requirements 4.2, 4.3, 4.4**

### Property 10: 调和失败阈值触发（Reconcile Failure Threshold）

*For any* ServiceInstance，当连续调和失败次数超过 3 次时，该实例应被标记为 error 状态；当连续失败次数不超过 3 次时，不应被标记为 error。

**Validates: Requirements 4.6**

### Property 11: 路由配置生成正确性（Route Config Generation）

*For any* 处于 running 状态的 ServiceInstance（包含一个或多个端口映射），生成的 Traefik 路由配置应满足：默认路径 `/api/{service_type}/{instance_id}/{path}` 映射到默认端口，每个 port_prefix 路径 `/api/{service_type}/{instance_id}/{port_prefix}/{path}` 映射到对应的容器端口。

**Validates: Requirements 5.1, 5.2**

### Property 12: 服务组路由配置正确性（Group Route Config Generation）

*For any* 属于 ServiceGroup 的多个容器，生成的 Traefik 路由配置应正确地将每个 port_prefix 映射到组内对应容器的指定端口。

**Validates: Requirements 5.7**

### Property 13: 非运行容器操作拒绝（Non-Running Container Operation Rejection）

*For any* actual_state 不为 running 的 ServiceInstance，对其执行文件列表、文件下载、文件上传或命令执行操作时，系统应返回 409 错误响应。

**Validates: Requirements 6.5**

### Property 14: 更新管道失败中断（Update Pipeline Failure Halt）

*For any* 包含 N 个步骤的更新管道，当第 K 步（K < N）失败时，第 K+1 到第 N 步不应被执行，且 ServiceInstance 应被标记为 error 状态。

**Validates: Requirements 7.3**

### Property 15: 命令执行权限验证（Command Execution Authorization）

*For any* 命令字符串和租户的允许命令列表，当命令不在允许列表中时，执行请求应被拒绝；当命令在允许列表中时，执行请求应被接受。

**Validates: Requirements 8.4**

### Property 16: 租户网络隔离（Tenant Network Isolation）

*For any* 两个不同租户的 ServiceInstance，它们分配的 Docker 网络名称应不同，确保网络层面的隔离。

**Validates: Requirements 8.2**

### Property 17: 服务组生命周期一致性（Group Lifecycle Consistency）

*For any* ServiceGroup 及其包含的所有容器，对服务组执行停止操作后，组内每个容器的 desired_state 都应为 stopped。

**Validates: Requirements 9.2**

### Property 18: 服务组状态查询完整性（Group Status Completeness）

*For any* ServiceGroup，查询其详情时返回的数据应包含组内每个容器的独立状态信息，且容器数量与实际组内容器数量一致。

**Validates: Requirements 9.5**

### Property 19: 路由配置持久化往返一致性（Route Config Persistence Round-Trip）

*For any* ServiceInstance 的 Traefik 路由配置，存储到数据库后系统重启，重建的路由配置应与原始配置等价。

**Validates: Requirements 10.3**

## 错误处理

### 错误分类与响应

| HTTP 状态码 | 场景 | 响应格式 |
|-------------|------|----------|
| 400 | 请求参数校验失败（Pydantic 验证错误） | `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}` |
| 401 | JWT token 缺失或无效 | `{"detail": "未提供有效的认证凭据"}` |
| 403 | 租户无权访问目标资源 | `{"detail": "无权访问该资源"}` |
| 404 | 实例/模板/服务组不存在 | `{"detail": "资源不存在", "resource_type": "...", "resource_id": "..."}` |
| 409 | 容器状态不支持当前操作 | `{"detail": "容器当前状态不支持该操作", "current_state": "...", "required_state": "running"}` |
| 500 | 内部服务器错误 | `{"detail": "内部服务器错误", "request_id": "..."}` |
| 503 | 目标服务不可用（Traefik 返回） | `{"detail": "服务当前不可用"}` |

### 数据库连接失败处理

当 PostgreSQL 连接失败时：
- 拒绝所有创建和删除请求（返回 503）
- 允许已运行容器的流量转发继续工作（Traefik 路由不依赖数据库）
- 后台 Reconcile Loop 暂停，等待连接恢复后自动恢复
- 记录错误日志并触发告警

### Docker 连接失败处理

当 Docker Socket 连接失败时：
- 事件监听器自动重连（指数退避，最大间隔 60 秒）
- Reconcile Loop 跳过当前周期，记录错误日志
- API 层的容器操作返回 503，说明 Docker 引擎不可用
- 数据库中的状态信息保持不变，等待连接恢复后重新同步

### 调和失败处理

- 每次调和失败递增该实例的连续失败计数器
- 连续失败超过 3 次：标记实例为 error 状态，生成告警
- 调和成功时重置失败计数器
- error 状态的实例不再参与自动调和，需人工介入

### 更新管道失败处理

- 管道中任一步骤失败立即中断后续步骤
- 通过 SSE 事件流通知客户端失败原因
- 将实例标记为 error 状态
- 不自动回滚（避免回滚失败导致更复杂的状态）

## 测试策略

### 测试框架与工具

| 工具 | 用途 |
|------|------|
| pytest | 测试运行器 |
| pytest-asyncio | 异步测试支持 |
| hypothesis | 属性基测试（Property-Based Testing） |
| httpx | 异步 HTTP 客户端（测试 FastAPI） |
| testcontainers-python | 集成测试中的 Docker/PostgreSQL 容器 |
| factory-boy | 测试数据工厂 |

### 属性基测试（Property-Based Testing）

每个正确性属性对应一个 hypothesis 属性测试，最少运行 100 次迭代。

测试标签格式：`Feature: nineclaw-manager, Property {number}: {property_text}`

重点属性测试覆盖：
- **模板渲染**（Property 3）：生成随机模板和参数，验证渲染结果无残留占位符
- **状态转换**（Property 4）：生成随机生命周期操作序列，验证状态转换正确性
- **调和决策**（Property 9）：生成随机 (desired, actual) 状态对，验证决策正确性
- **路由配置生成**（Property 11, 12）：生成随机实例和端口映射，验证路由配置正确性
- **租户隔离**（Property 6, 7）：生成随机多租户场景，验证隔离正确性
- **命令权限验证**（Property 15）：生成随机命令和允许列表，验证权限判断正确性

### 单元测试

单元测试覆盖具体示例和边界情况：
- 模板创建的具体有效/无效输入示例
- 实例生命周期的具体状态转换序列
- SSE 事件流的事件格式和顺序
- 健康检查超时场景
- 数据库连接失败的降级行为

### 集成测试

使用 testcontainers 启动真实的 PostgreSQL 和 Docker 环境：
- Docker 事件监听和状态同步
- Traefik 路由配置的实际生效验证
- docker compose 服务组的创建和管理
- 容器文件操作（列目录、上传、下载）
- 容器命令执行
- 系统启动时的状态恢复和调和

### 测试分层

```
┌─────────────────────────────────────┐
│  属性基测试 (hypothesis)             │  纯逻辑验证，100+ 迭代
│  - 模板渲染、状态转换、调和决策       │
│  - 路由配置生成、租户隔离过滤         │
├─────────────────────────────────────┤
│  单元测试 (pytest)                   │  具体示例和边界情况
│  - API 端点、服务层方法              │
│  - 错误处理、输入验证                │
├─────────────────────────────────────┤
│  集成测试 (testcontainers)           │  真实环境验证
│  - Docker 操作、PostgreSQL 持久化    │
│  - Traefik 路由、事件监听            │
└─────────────────────────────────────┘
```
