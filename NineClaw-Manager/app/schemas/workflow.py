"""Pydantic contracts for the workflow DSL and API."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    field_validator,
    model_validator,
)


NodeType = Literal["start", "end", "hermes_agent", "condition", "loop"]
WorkflowVariableType = Literal[
    "string",
    "integer",
    "number",
    "boolean",
    "object",
    "array",
    "null",
]
_SHORT_UUID_HEX = re.compile(r"^[0-9a-f]{12}4[0-9a-f]{3}$")


class WorkflowNodePosition(BaseModel):
    """Persisted canvas position. It never changes workflow execution."""

    model_config = ConfigDict(extra="forbid")

    x: FiniteFloat = 0.0
    y: FiniteFloat = 0.0


class WorkflowVariableDefinition(BaseModel):
    """Workflow-level immutable contract for one runtime variable."""

    model_config = ConfigDict(extra="forbid")

    type: WorkflowVariableType
    description: str | None = Field(default=None, max_length=512)


class WorkflowNodeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    type: NodeType
    type_version: int = Field(default=1, ge=1)
    executor_version: int = Field(default=1, ge=1)
    config: dict[str, Any] = Field(default_factory=dict)
    position: WorkflowNodePosition = Field(default_factory=WorkflowNodePosition)
    ui_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_typed_short_id(self) -> "WorkflowNodeDefinition":
        prefix, separator, short_id = self.id.rpartition("_")
        if (
            not separator
            or prefix != self.type
            or _SHORT_UUID_HEX.fullmatch(short_id) is None
        ):
            raise ValueError("节点 ID 必须为 '<type>_<16位小写UUID4 hex短ID>'")
        return self


class WorkflowEdgeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    source_node_id: str = Field(min_length=1, max_length=128)
    source_port: str = Field(default="default", min_length=1, max_length=128)
    target_node_id: str = Field(min_length=1, max_length=128)
    target_port: str = Field(default="default", min_length=1, max_length=128)


class WorkflowLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_node_executions: int | None = Field(default=None, ge=1)
    max_artifact_bytes: int | None = Field(default=None, ge=1)
    max_hermes_runs: int | None = Field(default=None, ge=1)


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Version is intentionally explicit.  Omitting it must not make a legacy
    # v1 definition look like a valid v2 document during the hard cutover.
    schema_version: int = Field(ge=1)
    nodes: list[WorkflowNodeDefinition] = Field(default_factory=list)
    edges: list[WorkflowEdgeDefinition] = Field(default_factory=list)
    variables: dict[str, WorkflowVariableDefinition] = Field(default_factory=dict)
    limits: WorkflowLimits = Field(default_factory=WorkflowLimits)
    ui_metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2048)
    # The compiler owns all DSL validation so writes always return its stable
    # value-free CompilationIssue projection rather than FastAPI's raw errors.
    definition: Any


class WorkflowDraftUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: Any
    expected_draft_revision: int = Field(ge=1)


class WorkflowMetadataUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2048)
    expected_draft_revision: int = Field(ge=1)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("工作流名称不能为空")
        return normalized


class WorkflowValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: Any = None


class WorkflowPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_draft_revision: int = Field(ge=1)


class WorkflowStartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: dict[str, Any] = Field(default_factory=dict)


class WorkflowNodeDebugRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, max_length=128)
    input: dict[str, Any] = Field(default_factory=dict)


class WorkflowRetryRequest(BaseModel):
    confirm_duplicate_side_effect_risk: bool = False


class WorkflowResolveFailedRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2048)


class WorkflowArtifactResponse(BaseModel):
    id: UUID
    name: str
    kind: str
    mime_type: str
    size_bytes: int
    sha256: str
    created_at: datetime


class WorkflowResponse(BaseModel):
    id: UUID
    name: str
    description: str
    draft_revision: int
    created_at: datetime
    updated_at: datetime


class WorkflowRunResponse(BaseModel):
    id: UUID
    workflow_id: UUID
    run_kind: str
    debug_node_id: str | None
    status: str
    input: dict[str, Any]
    output: dict[str, Any] | None
    attention_reason: str | None
    cancel_requested_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class WorkflowNodeRunResponse(BaseModel):
    id: UUID
    node_definition_id: str
    node_type: str
    status: str
    input_snapshot: dict[str, Any] | None
    output: dict[str, Any] | None
    generation: int
    error_code: str | None
    error_message: str | None


class WorkflowEventResponse(BaseModel):
    sequence: int
    event_type: str
    data: dict[str, Any]
    created_at: datetime


class WorkflowConversationCreateRequest(BaseModel):
    """Empty body reserved for a Manager-owned node conversation creation."""

    model_config = ConfigDict(extra="forbid")


class WorkflowConversationTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=65536)

    @field_validator("message")
    @classmethod
    def _require_nonblank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("消息不能为空")
        return value


class WorkflowConversationCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowConversationApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["allow", "deny"]
    reason: str | None = Field(default=None, max_length=2048)


class WorkflowConversationResponse(BaseModel):
    """Public projection. Internal Hermes session/version identifiers stay hidden."""

    id: UUID
    workflow_id: UUID
    node_definition_id: str
    status: str
    attention_reason: str | None
    created_at: datetime
    updated_at: datetime


class WorkflowConversationTurnResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    turn_number: int
    user_message: dict[str, Any]
    assistant_message: dict[str, Any] | None
    status: str
    error_code: str | None
    error_message: str | None
    cancel_requested_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class WorkflowConversationEventResponse(BaseModel):
    sequence: int
    event_type: str
    data: dict[str, Any]
    created_at: datetime


class WorkflowApiResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: Any = None
